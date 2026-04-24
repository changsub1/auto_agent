"""Workspace helpers for timestamped runs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def create_run_dir(project_root: Path) -> Path:
    """Create runs/YYYYMMDD_HHMMSS under the project root."""

    runs_root = Path(project_root) / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = runs_root / timestamp
    suffix = 1
    while run_dir.exists():
        run_dir = runs_root / f"{timestamp}_{suffix:02d}"
        suffix += 1

    run_dir.mkdir(parents=True)
    return run_dir


def create_generated_app_dir(run_dir: Path) -> Path:
    """Create the isolated app generation directory for a run."""

    app_dir = Path(run_dir) / "generated_app"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def create_logs_dir(run_dir: Path) -> Path:
    """Create the Codex call logs directory for a run."""

    logs_dir = Path(run_dir) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def save_text(path: Path, content: str) -> None:
    """Persist UTF-8 text, creating parent directories as needed."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_with_trailing_newline(content), encoding="utf-8")


def append_text(path: Path, content: str) -> None:
    """Append UTF-8 text, creating parent directories as needed."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(_with_trailing_newline(content))


def normalize_windows_command_files(app_dir: Path) -> list[Path]:
    """Normalize generated .bat/.cmd scripts to CRLF line endings."""

    normalized_files: list[Path] = []
    for path in sorted(Path(app_dir).rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".bat", ".cmd"}:
            continue

        content = path.read_text(encoding="utf-8", errors="replace")
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        path.write_text(content, encoding="utf-8", newline="\r\n")
        normalized_files.append(path)

    return normalized_files


def _with_trailing_newline(content: str) -> str:
    return content if content.endswith("\n") else f"{content}\n"
