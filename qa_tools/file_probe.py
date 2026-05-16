from __future__ import annotations

import argparse
from pathlib import Path

from _common import append_command_log, finish, rel, resolve_workspace_path, safe_name, write_json, write_text, workspace_root


DEFAULT_MAX_FULL_READ_BYTES = 128 * 1024


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a workspace file and record evidence.")
    parser.add_argument("--name", default="file", help="Short evidence name.")
    parser.add_argument("--path", required=True, help="File path relative to the QA workspace.")
    parser.add_argument("--contains", action="append", default=[], help="Text that must appear in the file.")
    parser.add_argument("--max-preview-chars", type=int, default=4000, help="Preview text length.")
    parser.add_argument(
        "--max-full-read-bytes",
        type=int,
        default=DEFAULT_MAX_FULL_READ_BYTES,
        help="Files above this size are treated as large and are never read fully.",
    )
    parser.add_argument("--line-start", type=int, help="1-based line number to preview from.")
    parser.add_argument("--line-count", type=int, default=80, help="Number of lines to preview when --line-start is used.")
    args = parser.parse_args()

    root = workspace_root()
    path = resolve_workspace_path(args.path)
    name = safe_name(args.name, "file")
    evidence_dir = root / "evidence" / "files"
    preview_path = evidence_dir / f"{name}_preview.txt"
    result_path = evidence_dir / f"{name}_result.json"

    status = "PASS"
    findings: list[str] = []
    preview = ""
    preview_truncated = False
    size_bytes: int | None = None
    contains_results: dict[str, bool] = {}
    read_policy = "missing"
    if not path.exists() or not path.is_file():
        status = "FAIL"
        findings.append(f"File does not exist: {rel(path)}")
    else:
        size_bytes = path.stat().st_size
        large_file = size_bytes > max(0, args.max_full_read_bytes)
        if args.line_start is not None:
            preview, preview_truncated = _read_line_window(
                path,
                line_start=max(1, args.line_start),
                line_count=max(1, args.line_count),
                max_chars=max(0, args.max_preview_chars),
            )
            read_policy = "line_window"
        else:
            preview, preview_truncated = _read_prefix_preview(path, max_chars=max(0, args.max_preview_chars))
            read_policy = "prefix_preview_large_file" if large_file else "prefix_preview"
        for expected in args.contains:
            found = _contains_text(path, expected)
            contains_results[expected] = found
            if not found:
                status = "FAIL"
                findings.append(f"Missing expected text: {expected}")

    write_text(preview_path, preview)
    result = {
        "tool": "file_probe",
        "name": name,
        "status": status,
        "path": rel(path),
        "size_bytes": size_bytes,
        "large_file": bool(size_bytes is not None and size_bytes > max(0, args.max_full_read_bytes)),
        "max_full_read_bytes": max(0, args.max_full_read_bytes),
        "read_policy": read_policy,
        "contains": args.contains,
        "contains_results": contains_results,
        "findings": findings,
        "preview_path": rel(preview_path),
        "preview_truncated": preview_truncated,
    }
    write_json(result_path, result)
    append_command_log({**result, "purpose": "File content QA probe.", "exit_code": 0, "result_path": rel(result_path)})
    finish({**result, "result_path": rel(result_path)})


def _read_prefix_preview(path: Path, *, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0:
        return "", path.stat().st_size > 0
    byte_limit = max(1024, max_chars * 4)
    with path.open("rb") as file:
        data = file.read(byte_limit + 1)
    text = data[:byte_limit].decode("utf-8", errors="replace")
    truncated = len(data) > byte_limit or len(text) > max_chars or path.stat().st_size > byte_limit
    return text[:max_chars], truncated


def _read_line_window(path: Path, *, line_start: int, line_count: int, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or line_count <= 0:
        return "", path.stat().st_size > 0
    lines: list[str] = []
    truncated = False
    char_count = 0
    with path.open("r", encoding="utf-8", errors="replace") as file:
        for line_number, line in enumerate(file, start=1):
            if line_number < line_start:
                continue
            if len(lines) >= line_count:
                truncated = True
                break
            remaining = max_chars - char_count
            if remaining <= 0:
                truncated = True
                break
            piece = line[:remaining]
            lines.append(piece)
            char_count += len(piece)
            if len(piece) < len(line):
                truncated = True
                break
    return "".join(lines), truncated


def _contains_text(path: Path, expected: str) -> bool:
    if not expected:
        return True
    needle = expected.encode("utf-8", errors="replace")
    if not needle:
        return True
    overlap_size = max(0, len(needle) - 1)
    previous = b""
    with path.open("rb") as file:
        while True:
            chunk = file.read(64 * 1024)
            if not chunk:
                return False
            haystack = previous + chunk
            if needle in haystack:
                return True
            previous = haystack[-overlap_size:] if overlap_size else b""


if __name__ == "__main__":
    main()
