"""CLI entrypoint for the local two-agent Codex development MVP."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agents import DeveloperAgent, PlannerAgent
from codex_runner import CodexExecutionError
from qa import QAResult, run_python_syntax_check
from workspace_manager import (
    create_generated_app_dir,
    create_logs_dir,
    create_run_dir,
    normalize_windows_command_files,
    save_text,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Planner and Developer agents through the local Codex CLI.",
    )
    parser.add_argument(
        "--planner-codex-home",
        help="CODEX_HOME path for Planner Agent. Defaults to the current environment.",
    )
    parser.add_argument(
        "--developer-codex-home",
        help="CODEX_HOME path for Developer Agent. Defaults to the current environment.",
    )
    parser.add_argument(
        "--max-fix-iterations",
        type=int,
        default=1,
        help="Number of syntax-fix retries when generated Python files fail py_compile.",
    )
    parser.add_argument(
        "request",
        nargs="+",
        help="Natural-language app request to pass to the Planner Agent.",
    )

    args = parser.parse_args()
    if args.max_fix_iterations < 0:
        parser.error("--max-fix-iterations must be 0 or greater.")
    return args


def main() -> int:
    args = parse_args()
    user_request = " ".join(args.request).strip()

    project_root = Path(__file__).resolve().parent
    run_dir = create_run_dir(project_root)
    logs_dir = create_logs_dir(run_dir)
    plan_path = run_dir / "plan.md"
    qa_report_path = run_dir / "qa_report.md"

    print(f"Run directory: {run_dir}")
    print("Running Planner Agent...")

    planner = PlannerAgent(codex_home=args.planner_codex_home, logs_dir=logs_dir)
    developer = DeveloperAgent(codex_home=args.developer_codex_home, logs_dir=logs_dir)

    try:
        plan_markdown = planner.create_plan(user_request, run_dir)
        save_text(plan_path, plan_markdown)

        generated_app_dir = create_generated_app_dir(run_dir)
        print("Running Developer Agent...")
        developer.create_app(user_request, plan_markdown, generated_app_dir)
        normalize_windows_command_files(generated_app_dir)

        print("Running Python syntax QA...")
        qa_result = run_python_syntax_check(
            generated_app_dir,
            qa_report_path,
            attempt_name="initial syntax check",
        )

        fix_iterations_used = 0
        while not qa_result.ok and fix_iterations_used < args.max_fix_iterations:
            fix_iterations_used += 1
            print(f"Syntax QA failed. Running Developer fix attempt {fix_iterations_used}...")
            developer.fix_app(
                user_request,
                plan_markdown,
                generated_app_dir,
                qa_result.error_log,
                iteration=fix_iterations_used,
            )
            normalize_windows_command_files(generated_app_dir)
            qa_result = run_python_syntax_check(
                generated_app_dir,
                qa_report_path,
                attempt_name=f"syntax check after fix {fix_iterations_used}",
                append=True,
            )

    except CodexExecutionError as exc:
        _save_run_error(run_dir, exc)
        print(f"Codex CLI failed: {exc}", file=sys.stderr)
        if exc.stderr:
            print(exc.stderr, file=sys.stderr)
        print(f"Logs: {logs_dir}", file=sys.stderr)
        return 1
    except Exception as exc:
        save_text(run_dir / "run_error.md", f"# Run Error\n\n```text\n{exc}\n```")
        print(f"Run failed: {exc}", file=sys.stderr)
        print(f"Run directory: {run_dir}", file=sys.stderr)
        return 1

    _print_summary(
        run_dir=run_dir,
        generated_app_dir=generated_app_dir,
        plan_path=plan_path,
        qa_result=qa_result,
        fix_iterations_used=fix_iterations_used,
        max_fix_iterations=args.max_fix_iterations,
    )
    return 0 if qa_result.ok else 2


def _save_run_error(run_dir: Path, exc: CodexExecutionError) -> None:
    parts = [
        "# Codex CLI Error",
        "",
        f"Message: {exc}",
        "",
        f"Return code: {exc.returncode}",
        "",
        "## stdout",
        "",
        "```text",
        exc.stdout,
        "```",
        "",
        "## stderr",
        "",
        "```text",
        exc.stderr,
        "```",
        "",
    ]
    save_text(run_dir / "run_error.md", "\n".join(parts))


def _print_summary(
    *,
    run_dir: Path,
    generated_app_dir: Path,
    plan_path: Path,
    qa_result: QAResult,
    fix_iterations_used: int,
    max_fix_iterations: int,
) -> None:
    status = "PASS" if qa_result.ok else "FAIL"
    print("")
    print("Done.")
    print(f"Run directory: {run_dir}")
    print(f"Plan: {plan_path}")
    print(f"Generated app: {generated_app_dir}")
    print(f"QA report: {qa_result.report_path}")
    print(f"Syntax QA: {status}")
    print(f"Fix iterations used: {fix_iterations_used}/{max_fix_iterations}")


if __name__ == "__main__":
    raise SystemExit(main())
