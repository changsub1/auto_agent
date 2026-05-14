from __future__ import annotations

import argparse

from _common import append_command_log, finish, rel, resolve_workspace_path, safe_name, write_json, write_text, workspace_root


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a workspace file and record evidence.")
    parser.add_argument("--name", default="file", help="Short evidence name.")
    parser.add_argument("--path", required=True, help="File path relative to the QA workspace.")
    parser.add_argument("--contains", action="append", default=[], help="Text that must appear in the file.")
    parser.add_argument("--max-preview-chars", type=int, default=4000, help="Preview text length.")
    args = parser.parse_args()

    root = workspace_root()
    path = resolve_workspace_path(args.path)
    name = safe_name(args.name, "file")
    evidence_dir = root / "evidence" / "files"
    preview_path = evidence_dir / f"{name}_preview.txt"
    result_path = evidence_dir / f"{name}_result.json"

    status = "PASS"
    findings: list[str] = []
    text = ""
    if not path.exists() or not path.is_file():
        status = "FAIL"
        findings.append(f"File does not exist: {rel(path)}")
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
        for expected in args.contains:
            if expected not in text:
                status = "FAIL"
                findings.append(f"Missing expected text: {expected}")

    write_text(preview_path, text[: max(0, args.max_preview_chars)])
    result = {
        "tool": "file_probe",
        "name": name,
        "status": status,
        "path": rel(path),
        "contains": args.contains,
        "findings": findings,
        "preview_path": rel(preview_path),
    }
    write_json(result_path, result)
    append_command_log({**result, "purpose": "File content QA probe.", "exit_code": 0, "result_path": rel(result_path)})
    finish({**result, "result_path": rel(result_path)})


if __name__ == "__main__":
    main()
