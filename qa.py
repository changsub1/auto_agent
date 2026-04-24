"""Syntax QA for generated Python apps."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class QAResult:
    ok: bool
    checked_files: list[Path]
    error_log: str
    report_path: Path
    report_markdown: str


def run_python_syntax_check(
    app_dir: Path,
    report_path: Path,
    *,
    attempt_name: str = "syntax check",
    append: bool = False,
    timeout: int = 120,
) -> QAResult:
    """Run `python -m py_compile` for every .py file under app_dir."""

    app_dir = Path(app_dir)
    report_path = Path(report_path)
    py_files = sorted(path for path in app_dir.rglob("*.py") if path.is_file())

    errors: list[str] = []
    checked_files: list[Path] = []

    if not py_files:
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
