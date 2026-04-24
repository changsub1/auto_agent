"""Small wrapper around the local Codex CLI."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class CodexExecutionError(RuntimeError):
    """Raised when the Codex CLI cannot complete a request."""

    def __init__(
        self,
        message: str,
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int | None = None,
    ) -> None:
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@dataclass(frozen=True)
class CodexResult:
    """Structured result for one Codex CLI invocation."""

    stdout: str
    stderr: str
    returncode: int
    session_id: str | None
    resumed_session_id: str | None


def run_codex(
    prompt: str,
    workdir: Path,
    codex_home: str | None = None,
    timeout: int = 600,
    logs_dir: Path | None = None,
    label: str = "codex",
) -> str:
    """Run Codex in a specific directory and return stdout."""

    return run_codex_result(
        prompt=prompt,
        workdir=workdir,
        codex_home=codex_home,
        timeout=timeout,
        logs_dir=logs_dir,
        label=label,
    ).stdout


def run_codex_result(
    prompt: str,
    workdir: Path,
    codex_home: str | None = None,
    timeout: int = 600,
    logs_dir: Path | None = None,
    label: str = "codex",
    session_id: str | None = None,
    sandbox: str = "workspace-write",
) -> CodexResult:
    """Run Codex CLI and return stdout, stderr, and the parsed session id.

    New sessions use `codex exec ... -` with the prompt passed over stdin.
    Existing agent sessions use `codex exec resume <session_id> -` so each
    agent can preserve its own conversation context without resending the full
    transcript on every turn.
    """

    workdir = Path(workdir)
    if not workdir.exists():
        raise FileNotFoundError(f"Work directory does not exist: {workdir}")

    env = os.environ.copy()
    if codex_home:
        env["CODEX_HOME"] = codex_home

    call_id = _make_call_id(label)
    _write_log(logs_dir, f"{call_id}_prompt.txt", prompt)

    codex_executable = _resolve_codex_executable()
    command = _build_command(codex_executable, session_id=session_id, sandbox=sandbox)
    try:
        result = subprocess.run(
            command,
            cwd=str(workdir),
            env=env,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except FileNotFoundError as exc:
        message = (
            "Codex CLI executable was not found. Install Codex CLI and confirm "
            "`codex --help` works in this shell."
        )
        _write_log(logs_dir, f"{call_id}_stderr.txt", message)
        raise CodexExecutionError(message) from exc
    except subprocess.TimeoutExpired as exc:
        stdout = _safe_process_text(exc.stdout)
        stderr = _safe_process_text(exc.stderr)
        message = f"Codex CLI timed out after {timeout} seconds."
        _write_log(logs_dir, f"{call_id}_stdout.txt", stdout)
        _write_log(logs_dir, f"{call_id}_stderr.txt", stderr or message)
        _write_log(
            logs_dir,
            f"{call_id}_meta.txt",
            _meta_text(
                workdir=workdir,
                codex_home=codex_home,
                returncode=None,
                timeout=timeout,
                codex_executable=codex_executable,
                command=command,
                resumed_session_id=session_id,
                parsed_session_id=None,
            ),
        )
        raise CodexExecutionError(message, stdout=stdout, stderr=stderr) from exc

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    parsed_session_id = _parse_session_id(stderr) or session_id
    _write_log(logs_dir, f"{call_id}_stdout.txt", stdout)
    _write_log(logs_dir, f"{call_id}_stderr.txt", stderr)
    _write_log(
        logs_dir,
        f"{call_id}_meta.txt",
        _meta_text(
            workdir=workdir,
            codex_home=codex_home,
            returncode=result.returncode,
            timeout=timeout,
            codex_executable=codex_executable,
            command=command,
            resumed_session_id=session_id,
            parsed_session_id=parsed_session_id,
        ),
    )

    if result.returncode != 0:
        message = (
            f"Codex CLI failed with exit code {result.returncode}. "
            "See the run logs for prompt, stdout, and stderr."
        )
        raise CodexExecutionError(
            message,
            stdout=stdout,
            stderr=stderr,
            returncode=result.returncode,
        )

    return CodexResult(
        stdout=stdout.strip(),
        stderr=stderr,
        returncode=result.returncode,
        session_id=parsed_session_id,
        resumed_session_id=session_id,
    )


def _make_call_id(label: str) -> str:
    safe_label = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in label).strip("_")
    if not safe_label:
        safe_label = "codex"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"{timestamp}_{safe_label}"


def _write_log(logs_dir: Path | None, filename: str, content: str) -> None:
    if logs_dir is None:
        return
    logs_dir = Path(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / filename).write_text(content, encoding="utf-8")


def _resolve_codex_executable() -> str:
    candidates = ["codex"]
    if os.name == "nt":
        candidates = ["codex.exe", "codex.cmd", "codex.bat", "codex"]

    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    return "codex"


def _build_command(codex_executable: str, *, session_id: str | None, sandbox: str) -> list[str]:
    if session_id:
        return [
            codex_executable,
            "exec",
            "resume",
            "--skip-git-repo-check",
            session_id,
            "-",
        ]

    return [
        codex_executable,
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        sandbox,
        "--color",
        "never",
        "-",
    ]


def _parse_session_id(stderr: str) -> str | None:
    match = re.search(r"session id:\s*([0-9a-fA-F-]+)", stderr)
    if not match:
        return None
    return match.group(1)


def _safe_process_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _meta_text(
    *,
    workdir: Path,
    codex_home: str | None,
    returncode: int | None,
    timeout: int,
    codex_executable: str,
    command: list[str],
    resumed_session_id: str | None,
    parsed_session_id: str | None,
) -> str:
    codex_home_value = codex_home if codex_home else "(default)"
    redacted_command = " ".join("<codex>" if part == codex_executable else part for part in command)
    return "\n".join(
        [
            f"workdir: {workdir}",
            f"codex_home: {codex_home_value}",
            f"returncode: {returncode}",
            f"timeout_seconds: {timeout}",
            f"resolved_codex_executable: {codex_executable}",
            f"command: {redacted_command}",
            "prompt_transport: stdin",
            f"resumed_session_id: {resumed_session_id}",
            f"parsed_session_id: {parsed_session_id}",
            "",
        ]
    )
