from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def workspace_root() -> Path:
    override = os.environ.get("ORCHESTRA_QA_WORKSPACE_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[1]


def safe_name(value: str | None, fallback: str = "probe") -> str:
    text = (value or fallback).strip().lower()
    text = re.sub(r"[^a-z0-9_.-]+", "_", text)
    text = text.strip("._-")
    return text or fallback


def ensure_within(root: Path, target: Path) -> Path:
    root = root.resolve()
    target = target.resolve()
    if root != target and root not in target.parents:
        raise ValueError(f"Refusing to access path outside QA workspace: {target}")
    return target


def resolve_workspace_path(value: str | None, *, default: str = ".") -> Path:
    root = workspace_root()
    raw = Path(value or default)
    path = raw if raw.is_absolute() else root / raw
    return ensure_within(root, path)


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root()).as_posix()
    except ValueError:
        return path.as_posix()


def ensure_dirs() -> None:
    root = workspace_root()
    for folder in ["evidence", "evidence/commands", "evidence/browser", "evidence/files", "screenshots"]:
        (root / folder).mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else f"{text}\n", encoding="utf-8", errors="replace")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_command_log(payload: dict[str, Any]) -> None:
    ensure_dirs()
    enriched = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    log_path = workspace_root() / "evidence" / "command_log.jsonl"
    with log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(enriched, ensure_ascii=False) + "\n")


def finish(payload: dict[str, Any], *, exit_code: int = 0) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    raise SystemExit(exit_code)
