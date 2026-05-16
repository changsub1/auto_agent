from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from _common import append_command_log, finish, rel, resolve_workspace_path, safe_name, write_json, write_text, workspace_root


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local command and record UTF-8 evidence.")
    parser.add_argument("--name", default="command", help="Short evidence name.")
    parser.add_argument("--cwd", default=".", help="Working directory relative to the QA workspace.")
    parser.add_argument("--timeout", type=float, default=60.0, help="Timeout in seconds.")
    parser.add_argument("--purpose", default="Local QA command probe.", help="Why this command is being run.")
    parser.add_argument("--fail-on-nonzero", action="store_true", help="Return the command exit code when non-zero.")
    parser.add_argument("--max-output-chars", type=int, default=20000, help="Maximum stdout/stderr chars to save.")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command after --, for example: -- python app.py --self-test")
    args = parser.parse_args()

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        finish({"status": "FAIL", "summary": "No command provided."}, exit_code=2)

    root = workspace_root()
    cwd = resolve_workspace_path(args.cwd)
    name = safe_name(args.name, "command")
    evidence_dir = root / "evidence" / "commands"
    stdout_path = evidence_dir / f"{name}_stdout.txt"
    stderr_path = evidence_dir / f"{name}_stderr.txt"
    result_path = evidence_dir / f"{name}_result.json"

    timed_out = False
    exit_code = -1
    stdout = ""
    stderr = ""
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1.0, args.timeout),
        )
        exit_code = int(completed.returncode)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", errors="replace")
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", errors="replace")
        stderr = (stderr + f"\nTimed out after {args.timeout} seconds.").strip()
    except OSError as exc:
        stderr = str(exc)

    stdout_preview, stdout_truncated = _truncate_output(stdout, max_chars=max(0, args.max_output_chars))
    stderr_preview, stderr_truncated = _truncate_output(stderr, max_chars=max(0, args.max_output_chars))
    write_text(stdout_path, stdout_preview)
    write_text(stderr_path, stderr_preview)
    result = {
        "tool": "command_probe",
        "name": name,
        "status": "TIMEOUT" if timed_out else ("PASS" if exit_code == 0 else "FAIL"),
        "command": command,
        "cwd": rel(cwd),
        "purpose": args.purpose,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout_path": rel(stdout_path),
        "stderr_path": rel(stderr_path),
        "stdout_chars": len(stdout),
        "stderr_chars": len(stderr),
        "max_output_chars": max(0, args.max_output_chars),
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }
    write_json(result_path, result)
    append_command_log({**result, "result_path": rel(result_path)})

    tool_exit = exit_code if args.fail_on_nonzero and exit_code != 0 else 0
    finish({**result, "result_path": rel(result_path)}, exit_code=tool_exit)


def _truncate_output(text: str, *, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0:
        return "", bool(text)
    if len(text) <= max_chars:
        return text, False
    omitted = len(text) - max_chars
    return text[:max_chars].rstrip() + f"\n[truncated {omitted} chars]\n", True


if __name__ == "__main__":
    main()
