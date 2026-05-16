"""Small wrapper around the local Codex CLI."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


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


@dataclass(frozen=True)
class CodexProcessHandle:
    """Cancelable handle for one running Codex CLI subprocess."""

    process: asyncio.subprocess.Process
    command: list[str]

    @property
    def pid(self) -> int | None:
        return self.process.pid

    @property
    def returncode(self) -> int | None:
        return self.process.returncode

    async def cancel(self, *, kill_after: float = 5.0) -> None:
        """Terminate the child process, preferring a process-tree shutdown."""

        if self.process.returncode is not None:
            return
        terminated = await _terminate_process_tree(self.process, kill_after=kill_after)
        if terminated:
            return

        with suppress(ProcessLookupError):
            self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=kill_after)
            return
        except asyncio.TimeoutError:
            pass

        with suppress(ProcessLookupError):
            self.process.kill()
        with suppress(ProcessLookupError):
            await self.process.wait()


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
    windows_sandbox = _windows_sandbox_config(sandbox)
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
    if stderr or _debug_artifacts_enabled() or result.returncode != 0:
        _write_log(logs_dir, f"{call_id}_stderr.txt", stderr)
    if _debug_artifacts_enabled() or result.returncode != 0:
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


async def run_codex_result_async(
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
    process_started: Callable[[CodexProcessHandle], None] | None = None,
) -> CodexResult:
    """Run Codex CLI asynchronously while streaming stdout/stderr to logs."""

    workdir = Path(workdir)
    if not workdir.exists():
        raise FileNotFoundError(f"Work directory does not exist: {workdir}")

    stripped_env_names = _codex_env_names_to_strip(os.environ)
    windows_sandbox = _windows_sandbox_config(sandbox)
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
    stdout_path = _prepare_stream_log(logs_dir, f"{call_id}_stdout.txt")
    stderr_path = _prepare_stream_log(logs_dir, f"{call_id}_stderr.txt")

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(workdir),
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        message = (
            "Codex CLI executable was not found. Install Codex CLI and confirm "
            "`codex --help` works in this shell."
        )
        _write_log(logs_dir, f"{call_id}_stderr.txt", message)
        raise CodexExecutionError(message) from exc

    process_handle = CodexProcessHandle(process=process, command=command)
    if process_started is not None:
        process_started(process_handle)

    stdout_task = asyncio.create_task(_stream_process_output(process.stdout, stdout_path))
    stderr_task = asyncio.create_task(_stream_process_output(process.stderr, stderr_path))
    stdin_task = asyncio.create_task(_send_prompt(process, prompt))

    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        await process_handle.cancel()
        await _finish_stdin_task(stdin_task)
        stdout, stderr = await _finish_stream_tasks(stdout_task, stderr_task)
        message = f"Codex CLI timed out after {timeout} seconds."
        if stderr_path and not stderr:
            stderr_path.write_text(message, encoding="utf-8")
            stderr = message
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

    await _finish_stdin_task(stdin_task)
    stdout, stderr = await _finish_stream_tasks(stdout_task, stderr_task)
    parsed_session_id = _parse_session_id(stderr) or session_id
    effective_approval = _parse_header_value(stderr, "approval")
    effective_sandbox = _parse_header_value(stderr, "sandbox")
    if stderr_path is not None and not stderr and not _debug_artifacts_enabled() and process.returncode == 0:
        with suppress(OSError):
            stderr_path.unlink()
    if _debug_artifacts_enabled() or process.returncode != 0:
        _write_log(
            logs_dir,
            f"{call_id}_meta.txt",
            _meta_text(
                workdir=workdir,
                codex_home=codex_home,
                returncode=process.returncode,
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

    if process.returncode != 0:
        message = (
            f"Codex CLI failed with exit code {process.returncode}. "
            "See the run logs for prompt, stdout, and stderr."
        )
        raise CodexExecutionError(
            message,
            stdout=stdout,
            stderr=stderr,
            returncode=process.returncode,
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
            returncode=process.returncode,
        )

    return CodexResult(
        stdout=stdout.strip(),
        stderr=stderr,
        returncode=int(process.returncode or 0),
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


def _debug_artifacts_enabled() -> bool:
    value = os.environ.get("ORCHESTRA_DEBUG_ARTIFACTS", "")
    return value.strip().lower() in {"1", "true", "yes", "on", "debug"}


def _prepare_stream_log(logs_dir: Path | None, filename: str) -> Path | None:
    if logs_dir is None:
        return None
    logs_dir = Path(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / filename
    path.write_bytes(b"")
    return path


async def _send_prompt(process: asyncio.subprocess.Process, prompt: str) -> None:
    if process.stdin is None:
        return
    try:
        process.stdin.write(prompt.encode("utf-8", errors="replace"))
        await process.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        process.stdin.close()
        with suppress(BrokenPipeError, ConnectionResetError):
            await process.stdin.wait_closed()


async def _stream_process_output(reader: asyncio.StreamReader | None, log_path: Path | None) -> str:
    if reader is None:
        return ""
    chunks: list[bytes] = []
    while True:
        chunk = await reader.read(4096)
        if not chunk:
            break
        chunks.append(chunk)
        if log_path is not None:
            with log_path.open("ab") as file:
                file.write(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace")


async def _finish_stdin_task(task: asyncio.Task[None]) -> None:
    with suppress(BrokenPipeError, ConnectionResetError, asyncio.CancelledError):
        await task


async def _finish_stream_tasks(
    stdout_task: asyncio.Task[str],
    stderr_task: asyncio.Task[str],
) -> tuple[str, str]:
    stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
    return stdout, stderr


async def _terminate_process_tree(process: asyncio.subprocess.Process, *, kill_after: float) -> bool:
    pid = process.pid
    if pid is None or process.returncode is not None:
        return True
    if await _terminate_process_tree_with_psutil(pid, kill_after=kill_after):
        return True
    if os.name == "nt" and await _terminate_process_tree_with_taskkill(pid, kill_after=kill_after):
        return True
    return False


async def _terminate_process_tree_with_taskkill(pid: int, *, kill_after: float) -> bool:
    try:
        taskkill = await asyncio.create_subprocess_exec(
            "taskkill",
            "/T",
            "/F",
            "/PID",
            str(pid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False
    try:
        returncode = await asyncio.wait_for(taskkill.wait(), timeout=kill_after)
    except asyncio.TimeoutError:
        with suppress(ProcessLookupError):
            taskkill.kill()
        with suppress(ProcessLookupError):
            await taskkill.wait()
        return False
    return returncode == 0


async def _terminate_process_tree_with_psutil(pid: int, *, kill_after: float) -> bool:
    def terminate() -> bool:
        try:
            import psutil  # type: ignore[import-not-found]
        except Exception:
            return False
        try:
            parent = psutil.Process(pid)
        except psutil.Error:
            return True

        processes = parent.children(recursive=True)
        processes.append(parent)
        for process_item in processes:
            with suppress(psutil.Error):
                process_item.terminate()
        _, alive = psutil.wait_procs(processes, timeout=kill_after)
        for process_item in alive:
            with suppress(psutil.Error):
                process_item.kill()
        _, alive = psutil.wait_procs(alive, timeout=kill_after)
        return not alive

    return await asyncio.to_thread(terminate)


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
    _apply_utf8_child_env(env)
    return env


def _apply_utf8_child_env(env: dict[str, str]) -> None:
    """Bias nested Codex and its child commands toward UTF-8 text I/O."""

    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("LANG", "C.UTF-8")


def _windows_sandbox_config(sandbox: str) -> str:
    configured = os.environ.get("CODEX_CHILD_WINDOWS_SANDBOX", "").strip()
    if configured:
        return configured
    if os.name == "nt" and sandbox != "read-only":
        return "elevated"
    return ""


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
