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
    model: str | None
    reasoning_effort: str | None
    effective_approval: str | None
    effective_sandbox: str | None


def run_codex(
    prompt: str,
    workdir: Path,
    codex_home: str | None = None,
    timeout: int = 600,
    logs_dir: Path | None = None,
    label: str = "codex",
    model: str | None = None,
    reasoning_effort: str | None = None,
    image_paths: list[Path] | None = None,
) -> str:
    """Run Codex in a specific directory and return stdout."""

    return run_codex_result(
        prompt=prompt,
        workdir=workdir,
        codex_home=codex_home,
        timeout=timeout,
        logs_dir=logs_dir,
        label=label,
        model=model,
        reasoning_effort=reasoning_effort,
        image_paths=image_paths,
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
    model: str | None = None,
    reasoning_effort: str | None = None,
    image_paths: list[Path] | None = None,
    require_writable: bool = False,
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

    stripped_env_names = _codex_env_names_to_strip(os.environ)
    windows_sandbox = os.environ.get("CODEX_CHILD_WINDOWS_SANDBOX", "").strip()
    env = _clean_child_codex_env(os.environ)
    if codex_home:
        env["CODEX_HOME"] = codex_home

    call_id = _make_call_id(label)
    _write_log(logs_dir, f"{call_id}_prompt.txt", prompt)

    codex_executable = _resolve_codex_executable()
    image_paths = [Path(path) for path in (image_paths or [])]
    command = _build_command(
        codex_executable,
        session_id=session_id,
        sandbox=sandbox,
        model=model,
        reasoning_effort=reasoning_effort,
        image_paths=image_paths,
        windows_sandbox=windows_sandbox,
    )
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
                model=model,
                reasoning_effort=reasoning_effort,
                image_paths=image_paths,
                requested_sandbox=sandbox,
                effective_approval=None,
                effective_sandbox=None,
                stripped_env_names=stripped_env_names,
                windows_sandbox=windows_sandbox,
            ),
        )
        raise CodexExecutionError(message, stdout=stdout, stderr=stderr) from exc

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    parsed_session_id = _parse_session_id(stderr) or session_id
    effective_approval = _parse_header_value(stderr, "approval")
    effective_sandbox = _parse_header_value(stderr, "sandbox")
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
            model=model,
            reasoning_effort=reasoning_effort,
            image_paths=image_paths,
            requested_sandbox=sandbox,
            effective_approval=effective_approval,
            effective_sandbox=effective_sandbox,
            stripped_env_names=stripped_env_names,
            windows_sandbox=windows_sandbox,
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

    if require_writable and effective_sandbox == "read-only":
        message = (
            "Codex CLI started with an effective read-only sandbox, but this "
            "agent step requires file writes. See the run logs for the command "
            "and stderr header."
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
        model=model,
        reasoning_effort=reasoning_effort,
        effective_approval=effective_approval,
        effective_sandbox=effective_sandbox,
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


def _codex_env_names_to_strip(source_env: os._Environ[str]) -> list[str]:
    names = []
    for name in list(source_env):
        if name.startswith("CODEX_INTERNAL_"):
            names.append(name)
    for name in [
        "CODEX_THREAD_ID",
        "CODEX_SANDBOX",
        "CODEX_SANDBOX_MODE",
        "CODEX_SANDBOX_NETWORK_DISABLED",
        "CODEX_APPROVAL_POLICY",
    ]:
        if name in source_env:
            names.append(name)
    return sorted(set(names))


def _clean_child_codex_env(source_env: os._Environ[str]) -> dict[str, str]:
    """Remove parent Codex runtime markers before launching nested Codex CLI."""

    env = dict(source_env)
    for name in _codex_env_names_to_strip(source_env):
        env.pop(name, None)
    return env


def _build_command(
    codex_executable: str,
    *,
    session_id: str | None,
    sandbox: str,
    model: str | None,
    reasoning_effort: str | None,
    image_paths: list[Path],
    windows_sandbox: str,
) -> list[str]:
    options = ["--skip-git-repo-check"]
    if sandbox != "read-only":
        options.append("--full-auto")
    if os.name == "nt" and windows_sandbox:
        options.extend(["-c", f'windows.sandbox="{windows_sandbox}"'])
    if model:
        options.extend(["--model", model])
    if reasoning_effort:
        options.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    for image_path in image_paths:
        options.extend(["--image", str(image_path)])

    if session_id:
        return [
            codex_executable,
            "exec",
            "resume",
            *options,
            session_id,
            "-",
        ]

    return [
        codex_executable,
        "exec",
        *options,
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


def _parse_header_value(stderr: str, name: str) -> str | None:
    pattern = rf"(?im)^\s*{re.escape(name)}:\s*(.+?)\s*$"
    match = re.search(pattern, stderr)
    if not match:
        return None
    return match.group(1).strip()


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
    model: str | None,
    reasoning_effort: str | None,
    image_paths: list[Path],
    requested_sandbox: str,
    effective_approval: str | None,
    effective_sandbox: str | None,
    stripped_env_names: list[str],
    windows_sandbox: str,
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
            f"model: {model or '(configured default)'}",
            f"reasoning_effort: {reasoning_effort or '(configured default)'}",
            f"requested_sandbox: {requested_sandbox}",
            f"effective_approval: {effective_approval or '(not parsed)'}",
            f"effective_sandbox: {effective_sandbox or '(not parsed)'}",
            f"windows_sandbox_config: {windows_sandbox or '(not set)'}",
            f"stripped_codex_env: {', '.join(stripped_env_names) or '(none)'}",
            f"image_paths: {', '.join(str(path) for path in image_paths) or '(none)'}",
            f"resumed_session_id: {resumed_session_id}",
            f"parsed_session_id: {parsed_session_id}",
            "",
        ]
    )
