"""Syntax QA for generated Python apps."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from executable_qa import ExecutableQAResult


@dataclass(frozen=True)
class QAResult:
    ok: bool
    checked_files: list[Path]
    error_log: str
    report_path: Path
    report_markdown: str
    screenshots: list[Path] = field(default_factory=list)
    artifact_paths: list[Path] = field(default_factory=list)
    executable_status: str | None = None
    executable_app_type: str | None = None
    affected_paths: list[str] = field(default_factory=list)
    suspected_owners: list[str] = field(default_factory=list)


def run_python_syntax_check(
    app_dir: Path,
    report_path: Path,
    *,
    attempt_name: str = "syntax check",
    append: bool = False,
    timeout: int = 120,
    fail_on_missing_python: bool = True,
) -> QAResult:
    """Run `python -m py_compile` for every .py file under app_dir."""

    app_dir = Path(app_dir)
    report_path = Path(report_path)
    py_files = sorted(path for path in app_dir.rglob("*.py") if path.is_file())

    errors: list[str] = []
    checked_files: list[Path] = []

    if not py_files and fail_on_missing_python:
        errors.append(f"No Python files were found in {app_dir}.")

    for py_file in py_files:
        relative_file = py_file.relative_to(app_dir)
        checked_files.append(relative_file)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", str(relative_file)],
                cwd=str(app_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_utf8_child_env(),
                timeout=timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _safe_process_text(exc.stdout)
            stderr = _safe_process_text(exc.stderr)
            errors.append(
                "\n".join(
                    [
                        f"File: {relative_file}",
                        f"Result: timed out after {timeout} seconds",
                        stdout,
                        stderr,
                    ]
                ).strip()
            )
            continue

        if result.returncode != 0:
            errors.append(
                "\n".join(
                    [
                        f"File: {relative_file}",
                        f"Return code: {result.returncode}",
                        "stdout:",
                        result.stdout or "",
                        "stderr:",
                        result.stderr or "",
                    ]
                ).strip()
            )

    error_log = "\n\n".join(error for error in errors if error)
    ok = not error_log
    report = _build_report(attempt_name, app_dir, checked_files, ok, error_log)
    _write_report(report_path, report, append=append)

    return QAResult(
        ok=ok,
        checked_files=checked_files,
        error_log=error_log,
        report_path=report_path,
        report_markdown=report,
    )


def combine_mechanical_qa_results(
    *,
    syntax_result: QAResult,
    executable_result: ExecutableQAResult,
    report_path: Path,
    attempt_name: str,
) -> QAResult:
    """Combine syntax QA and executable QA into the public run QA report."""

    executable_blocks = executable_result.status == "FAIL"
    ok = syntax_result.ok and not executable_blocks
    error_parts = []
    if syntax_result.error_log:
        error_parts.append(syntax_result.error_log)
    if executable_blocks and executable_result.error_log:
        error_parts.append(executable_result.error_log)
    error_log = "\n\n".join(error_parts)

    status = "PASS" if ok else "FAIL"
    report = "\n".join(
        [
            f"# {attempt_name}",
            "",
            f"- Time: {datetime.now().isoformat(timespec='seconds')}",
            f"- Status: {status}",
            f"- Syntax QA: {'PASS' if syntax_result.ok else 'FAIL'}",
            f"- Executable QA: {executable_result.status}",
            f"- Executable app type: `{executable_result.app_type}`",
            "",
            "## Syntax QA",
            "",
            syntax_result.report_markdown.strip(),
            "",
            "## Executable QA",
            "",
            executable_result.report_markdown.strip(),
            "",
        ]
    )
    _write_report(report_path, report, append=False)

    return QAResult(
        ok=ok,
        checked_files=syntax_result.checked_files,
        error_log=error_log,
        report_path=report_path,
        report_markdown=report,
        screenshots=executable_result.screenshots,
        artifact_paths=[syntax_result.report_path, executable_result.report_path, *executable_result.artifact_paths],
        executable_status=executable_result.status,
        executable_app_type=executable_result.app_type,
        affected_paths=[path.as_posix() for path in syntax_result.checked_files if not syntax_result.ok],
    )


def _build_report(
    attempt_name: str,
    app_dir: Path,
    checked_files: list[Path],
    ok: bool,
    error_log: str,
) -> str:
    status = "PASS" if ok else "FAIL"
    checked = "\n".join(f"- `{path.as_posix()}`" for path in checked_files) or "- None"
    details = "No syntax errors found." if ok else f"```text\n{error_log}\n```"

    return "\n".join(
        [
            f"## {attempt_name}",
            "",
            f"- Time: {datetime.now().isoformat(timespec='seconds')}",
            f"- App directory: `{app_dir}`",
            f"- Status: {status}",
            "",
            "### Checked files",
            checked,
            "",
            "### Details",
            details,
            "",
        ]
    )


def _write_report(report_path: Path, report: str, *, append: bool) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if append and report_path.exists():
        with report_path.open("a", encoding="utf-8") as file:
            file.write("\n")
            file.write(report)
            if not report.endswith("\n"):
                file.write("\n")
        return
    report_path.write_text(report if report.endswith("\n") else f"{report}\n", encoding="utf-8")


def _safe_process_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _utf8_child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("LANG", "C.UTF-8")
    return env
