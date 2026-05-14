"""Executable QA probes for generated apps.

This module intentionally keeps execution deterministic. The orchestrator
detects the generated app shape, runs an allowlisted probe, stores artifacts,
and gives the LLM/user the resulting report and screenshots.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExecutableQAResult:
    ok: bool
    status: str
    app_type: str
    report_path: Path
    report_markdown: str
    screenshots: list[Path] = field(default_factory=list)
    artifact_paths: list[Path] = field(default_factory=list)
    error_log: str = ""
    command: list[str] = field(default_factory=list)


def run_executable_qa(
    app_dir: Path,
    qa_dir: Path,
    *,
    attempt_name: str = "executable QA",
    timeout: int = 90,
    allow_local_commands: bool = False,
) -> ExecutableQAResult:
    """Run the best available executable probe for the generated app."""

    app_dir = Path(app_dir)
    qa_dir = Path(qa_dir)
    qa_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = app_dir / "codex_app_manifest.json"
    if manifest_path.exists():
        return _run_manifest_probe(app_dir, qa_dir, manifest_path, attempt_name=attempt_name, timeout=timeout)

    target = _detect_target(app_dir, allow_local_commands=allow_local_commands)
    if target["kind"] == "static_html":
        return _run_static_html_probe(app_dir, qa_dir, target, attempt_name=attempt_name, timeout=timeout)
    if target["kind"] == "streamlit":
        return _run_streamlit_probe(app_dir, qa_dir, target, attempt_name=attempt_name, timeout=timeout)
    if target["kind"] == "python_cli":
        return _run_cli_probe(app_dir, qa_dir, target, attempt_name=attempt_name, timeout=timeout)
    if target["kind"] == "windows_command":
        return _run_windows_command_probe(app_dir, qa_dir, target, attempt_name=attempt_name, timeout=timeout)
    return _skipped_result(
        app_dir,
        qa_dir,
        attempt_name=attempt_name,
        app_type="unknown",
        reason=target["reason"],
    )


def _detect_target(app_dir: Path, *, allow_local_commands: bool) -> dict[str, Any]:
    index_html = app_dir / "index.html"
    if index_html.exists():
        return {"kind": "static_html", "path": index_html, "app_type": "static_html"}

    app_py = app_dir / "app.py"
    if app_py.exists():
        app_text = _read_text(app_py)
        requirements = _read_text(app_dir / "requirements.txt").lower()
        lower_app = app_text.lower()
        if "streamlit" in requirements or "import streamlit" in lower_app or "from streamlit" in lower_app:
            return {"kind": "streamlit", "path": app_py, "app_type": "streamlit"}
        if "argparse" in lower_app or "click." in lower_app or "typer." in lower_app:
            return {"kind": "python_cli", "path": app_py, "app_type": "python_cli"}
        return {
            "kind": "skip",
            "app_type": "python_app",
            "reason": "app.py exists, but no safe automatic executable probe was detected.",
        }

    command_candidates = [
        app_dir / "run.bat",
        app_dir / "start.bat",
        app_dir / "run.cmd",
        app_dir / "start.cmd",
    ]
    for command_path in command_candidates:
        if command_path.exists():
            if allow_local_commands:
                return {"kind": "windows_command", "path": command_path, "app_type": "windows_command"}
            return {
                "kind": "skip",
                "app_type": "windows_command",
                "reason": (
                    f"{command_path.name} exists, but local command execution is disabled. "
                    "Set EXECUTABLE_QA_ALLOW_LOCAL_COMMANDS=1 to allow this probe."
                ),
            }

    return {"kind": "skip", "app_type": "unknown", "reason": "No index.html, Streamlit app, CLI app, or allowed launcher was found."}


def _run_manifest_probe(
    app_dir: Path,
    qa_dir: Path,
    manifest_path: Path,
    *,
    attempt_name: str,
    timeout: int,
) -> ExecutableQAResult:
    artifact_paths: list[Path] = [manifest_path]
    screenshots: list[Path] = []
    errors: list[str] = []
    details: list[str] = []
    executed_steps = 0

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return _manifest_failure(
            app_dir,
            qa_dir,
            attempt_name=attempt_name,
            app_type="manifest_invalid",
            details=f"Invalid codex_app_manifest.json: {exc}",
            artifact_paths=artifact_paths,
        )

    validation_errors = _validate_manifest(manifest, app_dir)
    app_type = str(manifest.get("app_type") or manifest.get("runtime") or "manifest")
    if validation_errors:
        return _manifest_failure(
            app_dir,
            qa_dir,
            attempt_name=attempt_name,
            app_type=app_type,
            details="\n".join(f"- {error}" for error in validation_errors),
            artifact_paths=artifact_paths,
        )

    workdir = _manifest_workdir(app_dir, manifest)
    command_timeout = _int_value(manifest.get("timeout_seconds"), timeout)

    for group_name in ("setup", "checks", "smoke"):
        for index, step in enumerate(_manifest_steps(manifest.get(group_name)), start=1):
            result = _run_manifest_command(
                workdir,
                qa_dir,
                step,
                label=f"manifest_{group_name}_{index:02d}",
                default_timeout=command_timeout,
            )
            artifact_paths.extend(result["artifacts"])
            details.append(result["detail"])
            executed_steps += 1
            if result["error"]:
                errors.append(result["error"])

    if not errors:
        run_spec = manifest.get("run")
        if isinstance(run_spec, dict) and run_spec.get("command"):
            run_result = _run_manifest_run_command(
                workdir,
                qa_dir,
                run_spec,
                app_type=app_type,
                attempt_name=attempt_name,
                default_timeout=command_timeout,
            )
            artifact_paths.extend(run_result.artifact_paths)
            screenshots.extend(run_result.screenshots)
            details.append(run_result.report_markdown)
            executed_steps += 1
            if run_result.status == "FAIL":
                errors.append(run_result.error_log or "Manifest run command failed.")
        elif _manifest_expects_browser_probe(app_type, manifest):
            html_path = _manifest_static_html_path(workdir, manifest)
            if html_path is None:
                errors.append(
                    "Manifest describes a browser/static app, but no run.ready_url or local HTML entrypoint was found."
                )
            else:
                browser_result = _run_static_html_probe(
                    workdir,
                    qa_dir,
                    {"kind": "static_html", "path": html_path, "app_type": app_type},
                    attempt_name=f"{attempt_name} manifest static browser probe",
                    timeout=timeout,
                )
                artifact_paths.extend(browser_result.artifact_paths)
                screenshots.extend(browser_result.screenshots)
                details.append(browser_result.report_markdown)
                executed_steps += 1
                if browser_result.status == "FAIL":
                    errors.append(browser_result.error_log or "Manifest static browser probe failed.")

    if executed_steps == 0 and not errors:
        return _skipped_result(
            app_dir,
            qa_dir,
            attempt_name=attempt_name,
            app_type=app_type,
            reason="codex_app_manifest.json exists but declares no executable setup, check, smoke, or run commands.",
            artifact_paths=artifact_paths,
        )

    status = "FAIL" if errors else "PASS"
    report = _build_report(
        attempt_name=attempt_name,
        app_dir=app_dir,
        app_type=app_type,
        status=status,
        command=[],
        screenshots=screenshots,
        artifact_paths=artifact_paths,
        details=_manifest_details(manifest, details, errors),
    )
    report_path = _write_report(qa_dir, report)
    return ExecutableQAResult(
        ok=status == "PASS",
        status=status,
        app_type=app_type,
        report_path=report_path,
        report_markdown=report,
        screenshots=screenshots,
        artifact_paths=artifact_paths,
        error_log="\n".join(errors),
    )


def _manifest_expects_browser_probe(app_type: str, manifest: dict[str, Any]) -> bool:
    values = " ".join(
        str(value).lower()
        for value in [
            app_type,
            manifest.get("runtime"),
            manifest.get("framework"),
            manifest.get("kind"),
        ]
        if value is not None
    )
    return any(token in values for token in ["web", "browser", "html", "static", "frontend", "game"])


def _manifest_static_html_path(workdir: Path, manifest: dict[str, Any]) -> Path | None:
    for key in ("entrypoint", "main", "path", "html"):
        value = manifest.get(key)
        if not isinstance(value, str) or not value.lower().endswith((".html", ".htm")):
            continue
        candidate = (workdir / value).resolve()
        try:
            candidate.relative_to(workdir.resolve())
        except ValueError:
            continue
        if candidate.exists():
            return candidate

    for candidate in [workdir / "index.html", workdir / "public" / "index.html", workdir / "dist" / "index.html"]:
        if candidate.exists():
            return candidate.resolve()
    return None


def _run_manifest_run_command(
    workdir: Path,
    qa_dir: Path,
    run_spec: dict[str, Any],
    *,
    app_type: str,
    attempt_name: str,
    default_timeout: int,
) -> ExecutableQAResult:
    command = _command_list(run_spec.get("command"))
    assert command is not None
    timeout = _int_value(run_spec.get("timeout_seconds"), default_timeout)
    ready_url = run_spec.get("ready_url")
    if not ready_url:
        return _run_process_probe(
            workdir,
            qa_dir,
            command=command,
            app_type=f"{app_type}_run",
            attempt_name=f"{attempt_name} manifest run",
            timeout=timeout,
        )

    runtime_log = qa_dir / "manifest_run_runtime.log"
    with runtime_log.open("w", encoding="utf-8", errors="replace") as log_file:
        process = subprocess.Popen(
            command,
            cwd=str(workdir),
            env=_utf8_child_env(),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            shell=False,
        )
        try:
            if not _wait_for_http(str(ready_url), timeout=min(timeout, 45)):
                error_log = f"Manifest run command did not become reachable at {ready_url} within the timeout."
                report = _build_report(
                    attempt_name=f"{attempt_name} manifest run",
                    app_dir=workdir,
                    app_type=app_type,
                    status="FAIL",
                    command=command,
                    screenshots=[],
                    artifact_paths=[runtime_log],
                    details=error_log,
                )
                report_path = _write_report(qa_dir, report)
                return ExecutableQAResult(
                    ok=False,
                    status="FAIL",
                    app_type=app_type,
                    report_path=report_path,
                    report_markdown=report,
                    artifact_paths=[runtime_log],
                    error_log=error_log,
                    command=command,
                )
            return _run_browser_probe(
                workdir,
                qa_dir,
                url=str(ready_url),
                app_type=app_type,
                attempt_name=f"{attempt_name} manifest browser probe",
                timeout=timeout,
                command=command,
                extra_artifacts=[runtime_log],
            )
        finally:
            _terminate_process(process)


def _run_manifest_command(
    workdir: Path,
    qa_dir: Path,
    step: dict[str, Any],
    *,
    label: str,
    default_timeout: int,
) -> dict[str, Any]:
    command = _command_list(step.get("command"))
    assert command is not None
    timeout = _int_value(step.get("timeout_seconds"), default_timeout)
    safe_label = _safe_label(str(step.get("name") or label))
    stdout_path = qa_dir / f"{safe_label}_stdout.txt"
    stderr_path = qa_dir / f"{safe_label}_stderr.txt"
    error = ""
    try:
        result = subprocess.run(
            command,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_utf8_child_env(),
            timeout=timeout,
            shell=False,
        )
        stdout_path.write_text(result.stdout or "", encoding="utf-8", errors="replace")
        stderr_path.write_text(result.stderr or "", encoding="utf-8", errors="replace")
        if result.returncode != 0:
            error = f"{safe_label} returned exit code {result.returncode}."
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(_safe_process_text(exc.stdout), encoding="utf-8", errors="replace")
        stderr_path.write_text(_safe_process_text(exc.stderr), encoding="utf-8", errors="replace")
        error = f"{safe_label} timed out after {timeout} seconds."

    detail = "\n".join(
        [
            f"### {safe_label}",
            "",
            f"- Command: `{' '.join(command)}`",
            f"- Timeout: {timeout}s",
            f"- Status: {'FAIL' if error else 'PASS'}",
            f"- stdout: `{stdout_path}`",
            f"- stderr: `{stderr_path}`",
            f"- Error: {error or 'None'}",
            "",
        ]
    )
    return {"artifacts": [stdout_path, stderr_path], "detail": detail, "error": error}


def _validate_manifest(manifest: Any, app_dir: Path) -> list[str]:
    if not isinstance(manifest, dict):
        return ["Manifest root must be a JSON object."]

    errors: list[str] = []
    workdir_raw = manifest.get("working_directory", ".")
    if not isinstance(workdir_raw, str):
        errors.append("working_directory must be a string.")
    else:
        try:
            _manifest_workdir(app_dir, manifest)
        except ValueError as exc:
            errors.append(str(exc))

    for group_name in ("setup", "checks", "smoke"):
        raw_steps = manifest.get(group_name, [])
        if raw_steps in (None, ""):
            continue
        if not isinstance(raw_steps, list):
            errors.append(f"{group_name} must be a list.")
            continue
        for index, step in enumerate(raw_steps, start=1):
            errors.extend(_validate_manifest_step(step, f"{group_name}[{index}]"))

    run_spec = manifest.get("run")
    if run_spec not in (None, ""):
        if not isinstance(run_spec, dict):
            errors.append("run must be an object.")
        else:
            errors.extend(_validate_manifest_step(run_spec, "run"))
            ready_url = run_spec.get("ready_url")
            if ready_url is not None and not _safe_local_url(str(ready_url)):
                errors.append("run.ready_url must be a local http://127.0.0.1, http://localhost, or file:// URL.")

    return errors


def _validate_manifest_step(step: Any, label: str) -> list[str]:
    if not isinstance(step, dict):
        return [f"{label} must be an object."]
    command = _command_list(step.get("command"))
    if command is None:
        return [f"{label}.command must be a non-empty JSON array of strings."]
    errors = _validate_command(command, label)
    timeout = step.get("timeout_seconds")
    if timeout is not None:
        try:
            parsed = int(timeout)
            if parsed <= 0 or parsed > 1800:
                errors.append(f"{label}.timeout_seconds must be between 1 and 1800.")
        except (TypeError, ValueError):
            errors.append(f"{label}.timeout_seconds must be an integer.")
    return errors


def _validate_command(command: list[str], label: str) -> list[str]:
    errors: list[str] = []
    executable = command[0]
    executable_name = Path(executable).name.lower()
    allowed = {
        "python",
        "python.exe",
        "py",
        "py.exe",
        "node",
        "node.exe",
        "npm",
        "npm.cmd",
        "npx",
        "npx.cmd",
        "pnpm",
        "pnpm.cmd",
        "yarn",
        "yarn.cmd",
        "bun",
        "bun.exe",
        "go",
        "go.exe",
        "cargo",
        "cargo.exe",
        "rustc",
        "rustc.exe",
        "dotnet",
        "dotnet.exe",
        "java",
        "java.exe",
        "mvn",
        "mvn.cmd",
        "gradle",
        "gradle.bat",
        "gradlew",
        "gradlew.bat",
        "uv",
        "uv.exe",
        "pytest",
        "pytest.exe",
    }
    if executable != sys.executable and executable_name not in allowed:
        errors.append(f"{label}.command executable is not allowlisted: {executable}")
    for part in command:
        if _has_shell_control(part):
            errors.append(f"{label}.command contains shell control syntax: {part}")
            break
    return errors


def _command_list(value: Any) -> list[str] | None:
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(item, str) and item for item in value):
        return None
    return [str(item) for item in value]


def _manifest_workdir(app_dir: Path, manifest: dict[str, Any]) -> Path:
    raw = str(manifest.get("working_directory") or ".")
    workdir = (app_dir / raw).resolve()
    app_root = app_dir.resolve()
    try:
        workdir.relative_to(app_root)
    except ValueError as exc:
        raise ValueError("working_directory must stay inside the generated app directory.") from exc
    if not workdir.exists() or not workdir.is_dir():
        raise ValueError(f"working_directory does not exist: {raw}")
    return workdir


def _manifest_steps(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _manifest_failure(
    app_dir: Path,
    qa_dir: Path,
    *,
    attempt_name: str,
    app_type: str,
    details: str,
    artifact_paths: list[Path],
) -> ExecutableQAResult:
    report = _build_report(
        attempt_name=attempt_name,
        app_dir=app_dir,
        app_type=app_type,
        status="FAIL",
        command=[],
        screenshots=[],
        artifact_paths=artifact_paths,
        details=details,
    )
    report_path = _write_report(qa_dir, report)
    return ExecutableQAResult(
        ok=False,
        status="FAIL",
        app_type=app_type,
        report_path=report_path,
        report_markdown=report,
        artifact_paths=artifact_paths,
        error_log=details,
    )


def _manifest_details(manifest: dict[str, Any], details: list[str], errors: list[str]) -> str:
    summary = [
        f"- Manifest runtime: `{manifest.get('runtime', 'unknown')}`",
        f"- Manifest app type: `{manifest.get('app_type', 'unknown')}`",
        "",
        "Errors:",
        "\n".join(f"- {error}" for error in errors) if errors else "- None",
        "",
        "Step details:",
        "\n".join(details).strip() or "- No commands declared.",
    ]
    return "\n".join(summary)


def _safe_label(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._-")[:80] or "manifest_step"


def _has_shell_control(value: str) -> bool:
    return any(token in value for token in ["&&", "||", ";", "|", ">", "<", "`", "$(", "\n", "\r"])


def _safe_local_url(value: str) -> bool:
    return (
        value.startswith("http://127.0.0.1:")
        or value.startswith("http://localhost:")
        or value.startswith("file://")
    )


def _int_value(value: Any, default: int) -> int:
    if value in (None, ""):
        return int(default)
    return int(value)


def _run_static_html_probe(
    app_dir: Path,
    qa_dir: Path,
    target: dict[str, Any],
    *,
    attempt_name: str,
    timeout: int,
) -> ExecutableQAResult:
    html_path = Path(target["path"]).resolve()
    return _run_browser_probe(
        app_dir,
        qa_dir,
        url=html_path.as_uri(),
        app_type="static_html",
        attempt_name=attempt_name,
        timeout=timeout,
        command=["playwright", "chromium", html_path.as_uri()],
    )


def _run_streamlit_probe(
    app_dir: Path,
    qa_dir: Path,
    target: dict[str, Any],
    *,
    attempt_name: str,
    timeout: int,
) -> ExecutableQAResult:
    port = _free_tcp_port()
    url = f"http://127.0.0.1:{port}"
    runtime_log = qa_dir / "streamlit_runtime.log"
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(Path(target["path"]).name),
        "--server.headless=true",
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--browser.gatherUsageStats=false",
    ]

    with runtime_log.open("w", encoding="utf-8", errors="replace") as log_file:
        process = subprocess.Popen(
            command,
            cwd=str(app_dir),
            env=_utf8_child_env(),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            shell=False,
        )
        try:
            if not _wait_for_http(url, timeout=min(35, timeout)):
                process.poll()
                status = "FAIL"
                error_log = f"Streamlit app did not become reachable at {url} within the timeout."
                report = _build_report(
                    attempt_name=attempt_name,
                    app_dir=app_dir,
                    app_type="streamlit",
                    status=status,
                    command=command,
                    screenshots=[],
                    artifact_paths=[runtime_log],
                    details=error_log,
                )
                report_path = _write_report(qa_dir, report)
                return ExecutableQAResult(
                    ok=False,
                    status=status,
                    app_type="streamlit",
                    report_path=report_path,
                    report_markdown=report,
                    artifact_paths=[runtime_log],
                    error_log=error_log,
                    command=command,
                )

            result = _run_browser_probe(
                app_dir,
                qa_dir,
                url=url,
                app_type="streamlit",
                attempt_name=attempt_name,
                timeout=timeout,
                command=command,
                extra_artifacts=[runtime_log],
            )
            return result
        finally:
            _terminate_process(process)


def _run_browser_probe(
    app_dir: Path,
    qa_dir: Path,
    *,
    url: str,
    app_type: str,
    attempt_name: str,
    timeout: int,
    command: list[str],
    extra_artifacts: list[Path] | None = None,
) -> ExecutableQAResult:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        reason = (
            "Playwright is not installed. Install it with `python -m pip install playwright` "
            "and install a browser with `python -m playwright install chromium`."
        )
        return _skipped_result(
            app_dir,
            qa_dir,
            attempt_name=attempt_name,
            app_type=app_type,
            reason=reason,
            command=command,
            artifact_paths=extra_artifacts or [],
        )

    console_messages: list[dict[str, str]] = []
    page_errors: list[str] = []
    screenshots: list[Path] = []
    artifact_paths: list[Path] = list(extra_artifacts or [])
    browser_log_path = qa_dir / "browser_console.json"
    errors: list[str] = []
    visual_probe: dict[str, Any] = {}
    scenario_path = qa_dir / "qa_scenarios.json"
    scenario_result_path = qa_dir / "scenario_results.json"
    scenario_details: list[str] = []

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.on("console", lambda msg: console_messages.append({"type": msg.type, "text": msg.text}))
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.goto(url, wait_until="load", timeout=timeout * 1000)
            page.wait_for_timeout(500)

            initial_path = qa_dir / "screenshot_initial.png"
            page.screenshot(path=str(initial_path), full_page=True)
            screenshots.append(initial_path)

            if scenario_path.exists():
                scenario_result = _run_browser_scenarios(
                    page,
                    scenario_path=scenario_path,
                    qa_dir=qa_dir,
                    base_url=url,
                )
                screenshots.extend(scenario_result["screenshots"])
                errors.extend(scenario_result["errors"])
                scenario_details.extend(scenario_result["details"])
                scenario_result_path.write_text(
                    json.dumps(scenario_result["results"], ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                artifact_paths.extend([scenario_path, scenario_result_path])
            else:
                scenario_details.append(
                    "No qa_scenarios.json was provided. Browser QA used only load, "
                    "console/page-error capture, initial screenshot, and visual content probe."
                )

            visual_probe = page.evaluate(_VISUAL_PROBE_JS)
            browser.close()
    except Exception as exc:  # noqa: BLE001 - probe errors belong in the QA report.
        errors.append(f"Browser probe raised {type(exc).__name__}: {exc}")

    browser_log_path.write_text(json.dumps(console_messages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifact_paths.append(browser_log_path)

    console_errors = [msg for msg in console_messages if msg.get("type") == "error"]
    if page_errors:
        errors.extend(f"Page error: {error}" for error in page_errors)
    if console_errors:
        errors.extend(f"Console error: {msg.get('text', '')}" for msg in console_errors)
    if visual_probe and not _visual_probe_has_content(visual_probe):
        errors.append(f"Visual probe suggests the page is blank: {json.dumps(visual_probe, ensure_ascii=False)}")

    status = "FAIL" if errors else "PASS"
    details = _browser_details(
        url=url,
        errors=errors,
        page_errors=page_errors,
        console_messages=console_messages,
        visual_probe=visual_probe,
        scenario_path=scenario_path if scenario_path.exists() else None,
        scenario_details=scenario_details,
    )
    report = _build_report(
        attempt_name=attempt_name,
        app_dir=app_dir,
        app_type=app_type,
        status=status,
        command=command,
        screenshots=screenshots,
        artifact_paths=artifact_paths,
        details=details,
    )
    report_path = _write_report(qa_dir, report)

    return ExecutableQAResult(
        ok=status == "PASS",
        status=status,
        app_type=app_type,
        report_path=report_path,
        report_markdown=report,
        screenshots=screenshots,
        artifact_paths=artifact_paths,
        error_log="\n".join(errors),
        command=command,
    )


def _run_browser_scenarios(
    page: Any,
    *,
    scenario_path: Path,
    qa_dir: Path,
    base_url: str,
) -> dict[str, Any]:
    try:
        payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "errors": [f"qa_scenarios.json is invalid JSON: {exc}"],
            "screenshots": [],
            "details": ["qa_scenarios.json could not be parsed."],
            "results": {"status": "FAIL", "error": str(exc), "scenarios": []},
        }

    scenarios = payload.get("scenarios") if isinstance(payload, dict) else None
    if not isinstance(scenarios, list) or not scenarios:
        return {
            "errors": ["qa_scenarios.json must contain a non-empty scenarios array."],
            "screenshots": [],
            "details": ["qa_scenarios.json did not declare any executable scenarios."],
            "results": {"status": "FAIL", "scenarios": []},
        }

    all_errors: list[str] = []
    screenshots: list[Path] = []
    details: list[str] = []
    result_scenarios: list[dict[str, Any]] = []

    for scenario_index, scenario in enumerate(scenarios, start=1):
        if not isinstance(scenario, dict):
            error = f"scenario[{scenario_index}] must be an object."
            all_errors.append(error)
            result_scenarios.append({"index": scenario_index, "status": "FAIL", "errors": [error], "steps": []})
            continue

        name = str(scenario.get("name") or f"scenario_{scenario_index}")
        steps = scenario.get("steps")
        scenario_errors: list[str] = []
        step_results: list[dict[str, Any]] = []
        if not isinstance(steps, list) or not steps:
            scenario_errors.append(f"{name}: steps must be a non-empty array.")
        else:
            for step_index, step in enumerate(steps, start=1):
                step_result = _run_browser_scenario_step(
                    page,
                    qa_dir=qa_dir,
                    base_url=base_url,
                    scenario_name=name,
                    scenario_index=scenario_index,
                    step_index=step_index,
                    step=step,
                )
                step_results.append(step_result)
                screenshots.extend(step_result.get("screenshot_paths", []))
                if step_result.get("status") == "FAIL":
                    scenario_errors.append(str(step_result.get("error") or "unknown step failure"))
                    if bool(scenario.get("stop_on_failure", True)):
                        break

        status = "FAIL" if scenario_errors else "PASS"
        if scenario_errors:
            all_errors.extend(scenario_errors)
        details.append(f"- {name}: {status}")
        serializable_steps = []
        for step_result in step_results:
            serializable_step = dict(step_result)
            serializable_step.pop("screenshot_paths", None)
            serializable_steps.append(serializable_step)
        result_scenarios.append(
            {
                "index": scenario_index,
                "name": name,
                "status": status,
                "errors": scenario_errors,
                "steps": serializable_steps,
            }
        )

    return {
        "errors": all_errors,
        "screenshots": screenshots,
        "details": ["Scenario results:", *details],
        "results": {
            "status": "FAIL" if all_errors else "PASS",
            "scenarios": result_scenarios,
        },
    }


def _run_browser_scenario_step(
    page: Any,
    *,
    qa_dir: Path,
    base_url: str,
    scenario_name: str,
    scenario_index: int,
    step_index: int,
    step: Any,
) -> dict[str, Any]:
    if not isinstance(step, dict):
        return {"step": step_index, "status": "FAIL", "error": f"{scenario_name} step[{step_index}] must be an object."}

    action = str(step.get("action") or "").strip().lower()
    label = f"{scenario_name} step[{step_index}] {action or '(missing action)'}"
    screenshots: list[Path] = []

    try:
        if action == "goto":
            target_url = _resolve_scenario_url(base_url, str(step.get("url") or ""))
            page.goto(target_url, wait_until="load", timeout=_step_timeout_ms(step))
            page.wait_for_timeout(300)
        elif action == "click":
            _locator(page, step).click(timeout=_step_timeout_ms(step))
        elif action == "press":
            key = str(step.get("key") or "")
            if not key:
                raise ValueError("press.key is required")
            selector = str(step.get("selector") or "").strip()
            if selector:
                _locator(page, step).press(key, timeout=_step_timeout_ms(step))
            else:
                page.keyboard.press(key)
        elif action == "type":
            text = str(step.get("text") or "")
            selector = str(step.get("selector") or "").strip()
            if not selector:
                raise ValueError("type.selector is required")
            _locator(page, step).fill(text, timeout=_step_timeout_ms(step))
        elif action == "drag":
            locator = _locator(page, step)
            box = locator.bounding_box(timeout=_step_timeout_ms(step))
            if not box:
                raise ValueError("drag target has no bounding box")
            dx = float(step.get("dx") or 0)
            dy = float(step.get("dy") or 0)
            start_x = box["x"] + box["width"] / 2
            start_y = box["y"] + box["height"] / 2
            page.mouse.move(start_x, start_y)
            page.mouse.down()
            page.mouse.move(start_x + dx, start_y + dy, steps=8)
            page.mouse.up()
        elif action == "expect_text":
            text = str(step.get("text") or "")
            if not text:
                raise ValueError("expect_text.text is required")
            body_text = page.locator("body").inner_text(timeout=_step_timeout_ms(step))
            if text not in body_text:
                raise AssertionError(f"expected text not found: {text}")
        elif action == "expect_visible":
            _locator(page, step).wait_for(state="visible", timeout=_step_timeout_ms(step))
        elif action == "expect_count":
            selector = str(step.get("selector") or "").strip()
            expected = int(step.get("count"))
            actual = page.locator(selector).count()
            if actual != expected:
                raise AssertionError(f"expected {expected} matches for {selector}, got {actual}")
        elif action == "wait":
            page.wait_for_timeout(_wait_ms(step))
        elif action == "screenshot":
            name = _safe_label(str(step.get("name") or f"scenario_{scenario_index}_step_{step_index}"))
            screenshot_path = qa_dir / f"screenshot_{name}.png"
            page.screenshot(path=str(screenshot_path), full_page=True)
            screenshots.append(screenshot_path)
        else:
            raise ValueError(f"unsupported action: {action or '(missing)'}")
    except Exception as exc:  # noqa: BLE001 - scenario failures are QA evidence.
        return {
            "step": step_index,
            "action": action,
            "status": "FAIL",
            "error": f"{label} failed: {type(exc).__name__}: {exc}",
            "screenshots": [str(path) for path in screenshots],
            "screenshot_paths": screenshots,
        }

    return {
        "step": step_index,
        "action": action,
        "status": "PASS",
        "screenshots": [str(path) for path in screenshots],
        "screenshot_paths": screenshots,
    }


def _locator(page: Any, step: dict[str, Any]) -> Any:
    selector = str(step.get("selector") or "").strip()
    if not selector:
        raise ValueError(f"{step.get('action', 'action')}.selector is required")
    return page.locator(selector).first


def _resolve_scenario_url(base_url: str, value: str) -> str:
    value = value.strip()
    if not value:
        return base_url
    if value.startswith(("http://127.0.0.1:", "http://localhost:", "file://")):
        return value
    if value.startswith("/"):
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, value, "", "", ""))
        if parsed.scheme == "file":
            base_dir = Path(urllib.request.url2pathname(parsed.path)).parent
            return (base_dir / value.lstrip("/")).resolve().as_uri()
    return urllib.parse.urljoin(base_url, value)


def _step_timeout_ms(step: dict[str, Any]) -> int:
    return _int_value(step.get("timeout_ms") or step.get("timeout_seconds"), 5) * (1 if step.get("timeout_ms") else 1000)


def _wait_ms(step: dict[str, Any]) -> int:
    return max(0, min(_int_value(step.get("ms") or step.get("timeout_ms"), 500), 30000))


def _run_cli_probe(
    app_dir: Path,
    qa_dir: Path,
    target: dict[str, Any],
    *,
    attempt_name: str,
    timeout: int,
) -> ExecutableQAResult:
    command = [sys.executable, str(Path(target["path"]).name), "--help"]
    return _run_process_probe(
        app_dir,
        qa_dir,
        command=command,
        app_type="python_cli",
        attempt_name=attempt_name,
        timeout=min(timeout, 30),
    )


def _run_windows_command_probe(
    app_dir: Path,
    qa_dir: Path,
    target: dict[str, Any],
    *,
    attempt_name: str,
    timeout: int,
) -> ExecutableQAResult:
    command = ["cmd.exe", "/c", str(Path(target["path"]).name)]
    return _run_process_probe(
        app_dir,
        qa_dir,
        command=command,
        app_type="windows_command",
        attempt_name=attempt_name,
        timeout=min(timeout, 45),
    )


def _run_process_probe(
    app_dir: Path,
    qa_dir: Path,
    *,
    command: list[str],
    app_type: str,
    attempt_name: str,
    timeout: int,
) -> ExecutableQAResult:
    stdout_path = qa_dir / f"{app_type}_stdout.txt"
    stderr_path = qa_dir / f"{app_type}_stderr.txt"
    errors: list[str] = []
    try:
        result = subprocess.run(
            command,
            cwd=str(app_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_utf8_child_env(),
            timeout=timeout,
            shell=False,
        )
        stdout_path.write_text(result.stdout or "", encoding="utf-8", errors="replace")
        stderr_path.write_text(result.stderr or "", encoding="utf-8", errors="replace")
        if result.returncode != 0:
            errors.append(f"Command returned exit code {result.returncode}.")
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(_safe_process_text(exc.stdout), encoding="utf-8", errors="replace")
        stderr_path.write_text(_safe_process_text(exc.stderr), encoding="utf-8", errors="replace")
        errors.append(f"Command timed out after {timeout} seconds.")

    status = "FAIL" if errors else "PASS"
    details = "\n".join(errors) or "Command completed successfully."
    report = _build_report(
        attempt_name=attempt_name,
        app_dir=app_dir,
        app_type=app_type,
        status=status,
        command=command,
        screenshots=[],
        artifact_paths=[stdout_path, stderr_path],
        details=details,
    )
    report_path = _write_report(qa_dir, report)
    return ExecutableQAResult(
        ok=status == "PASS",
        status=status,
        app_type=app_type,
        report_path=report_path,
        report_markdown=report,
        artifact_paths=[stdout_path, stderr_path],
        error_log="\n".join(errors),
        command=command,
    )


def _skipped_result(
    app_dir: Path,
    qa_dir: Path,
    *,
    attempt_name: str,
    app_type: str,
    reason: str,
    command: list[str] | None = None,
    artifact_paths: list[Path] | None = None,
) -> ExecutableQAResult:
    report = _build_report(
        attempt_name=attempt_name,
        app_dir=app_dir,
        app_type=app_type,
        status="SKIP",
        command=command or [],
        screenshots=[],
        artifact_paths=artifact_paths or [],
        details=reason,
    )
    report_path = _write_report(qa_dir, report)
    return ExecutableQAResult(
        ok=False,
        status="SKIP",
        app_type=app_type,
        report_path=report_path,
        report_markdown=report,
        artifact_paths=artifact_paths or [],
        error_log="",
        command=command or [],
    )


def _build_report(
    *,
    attempt_name: str,
    app_dir: Path,
    app_type: str,
    status: str,
    command: list[str],
    screenshots: list[Path],
    artifact_paths: list[Path],
    details: str,
) -> str:
    screenshot_lines = "\n".join(f"- `{path}`" for path in screenshots) or "- None"
    artifact_lines = "\n".join(f"- `{path}`" for path in artifact_paths) or "- None"
    command_text = " ".join(command) if command else "(not executed)"
    return "\n".join(
        [
            f"## {attempt_name}",
            "",
            f"- Time: {datetime.now().isoformat(timespec='seconds')}",
            f"- App directory: `{app_dir}`",
            f"- App type: `{app_type}`",
            f"- Status: {status}",
            f"- Command: `{command_text}`",
            "",
            "### Screenshots",
            screenshot_lines,
            "",
            "### Artifacts",
            artifact_lines,
            "",
            "### Details",
            details.strip() or "No details.",
            "",
        ]
    )


def _write_report(qa_dir: Path, report: str) -> Path:
    report_path = qa_dir / "executable_qa_report.md"
    report_path.write_text(report if report.endswith("\n") else f"{report}\n", encoding="utf-8")
    return report_path


def _browser_details(
    *,
    url: str,
    errors: list[str],
    page_errors: list[str],
    console_messages: list[dict[str, str]],
    visual_probe: dict[str, Any],
    scenario_path: Path | None,
    scenario_details: list[str],
) -> str:
    return "\n".join(
        [
            f"- URL: `{url}`",
            f"- Page errors: {len(page_errors)}",
            f"- Console messages: {len(console_messages)}",
            f"- Scenario file: `{scenario_path}`" if scenario_path else "- Scenario file: None",
            *(scenario_details or ["No scenario details."]),
            f"- Visual probe: `{json.dumps(visual_probe, ensure_ascii=False)}`",
            "",
            "Errors:",
            "\n".join(f"- {error}" for error in errors) if errors else "- None",
        ]
    )


def _visual_probe_has_content(visual_probe: dict[str, Any]) -> bool:
    if visual_probe.get("canvasHasPixels"):
        return True
    if int(visual_probe.get("textLength") or 0) > 0:
        return True
    if int(visual_probe.get("elementCount") or 0) > 3:
        return True
    return False


def _wait_for_http(url: str, *, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if 200 <= response.status < 500:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


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


_VISUAL_PROBE_JS = """
() => {
  const body = document.body;
  const canvases = Array.from(document.querySelectorAll('canvas'));
  let canvasHasPixels = false;
  for (const canvas of canvases) {
    try {
      const ctx = canvas.getContext('2d');
      if (!ctx || canvas.width === 0 || canvas.height === 0) {
        continue;
      }
      const width = Math.min(canvas.width, 96);
      const height = Math.min(canvas.height, 96);
      const data = ctx.getImageData(0, 0, width, height).data;
      for (let i = 0; i < data.length; i += 16) {
        const r = data[i];
        const g = data[i + 1];
        const b = data[i + 2];
        const a = data[i + 3];
        if (a > 0 && (r < 245 || g < 245 || b < 245)) {
          canvasHasPixels = true;
          break;
        }
      }
    } catch (error) {
      continue;
    }
    if (canvasHasPixels) {
      break;
    }
  }
  return {
    title: document.title || '',
    textLength: (body?.innerText || '').trim().length,
    elementCount: body ? body.querySelectorAll('*').length : 0,
    canvasCount: canvases.length,
    canvasHasPixels,
    scrollY: window.scrollY
  };
}
"""
