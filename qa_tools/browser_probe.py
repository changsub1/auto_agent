from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from _common import append_command_log, ensure_within, finish, rel, resolve_workspace_path, safe_name, write_json, workspace_root


def _local_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"}:
        return parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme == "file":
        return True
    return False


def _target_url(entry: str | None, url: str | None) -> str:
    root = workspace_root()
    if entry:
        path = resolve_workspace_path(entry)
        if not path.exists():
            raise FileNotFoundError(f"Entry file does not exist: {entry}")
        return path.as_uri()
    if not url:
        raise ValueError("Provide --entry or --url.")
    if not _local_url(url):
        raise ValueError("Only file, localhost, or 127.0.0.1 URLs are allowed.")
    parsed = urlparse(url)
    if parsed.scheme == "file":
        ensure_within(root, Path(url2pathname(parsed.path)))
    return url


def _parse_viewport(value: str) -> dict[str, int]:
    try:
        width_text, height_text = value.lower().split("x", 1)
        width = int(width_text)
        height = int(height_text)
    except (AttributeError, ValueError) as exc:
        raise ValueError("--viewport must use WIDTHxHEIGHT, for example 1280x900.") from exc
    if width < 320 or height < 240 or width > 4096 or height > 4096:
        raise ValueError("--viewport must be between 320x240 and 4096x4096.")
    return {"width": width, "height": height}


def _load_actions(action_file: str | None) -> list[dict[str, Any]]:
    if not action_file:
        return []
    path = resolve_workspace_path(action_file)
    payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    raw_actions = payload.get("actions") if isinstance(payload, dict) else payload
    if not isinstance(raw_actions, list):
        raise ValueError("Action file must contain a JSON array or an object with an actions array.")
    actions: list[dict[str, Any]] = []
    for index, item in enumerate(raw_actions, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Action {index} must be an object.")
        actions.append(item)
    return actions


def _number(value: Any, fallback: float) -> float:
    if value is None:
        return fallback
    return float(value)


def _point_from_action(action: dict[str, Any], key: str, default_x: float, default_y: float) -> tuple[float, float]:
    raw = action.get(key)
    if isinstance(raw, dict):
        return _number(raw.get("x"), default_x), _number(raw.get("y"), default_y)
    return default_x, default_y


def _run_action(page: Any, action: dict[str, Any], *, root: Path, base_name: str, index: int, timeout_ms: int) -> dict[str, Any]:
    action_type = str(action.get("action") or "").strip().lower()
    label = safe_name(str(action.get("name") or f"{base_name}_{index:02d}"), f"action_{index:02d}")
    result: dict[str, Any] = {"index": index, "action": action_type, "name": label, "status": "PASS"}

    if action_type == "wait":
        ms = int(_number(action.get("ms"), 500))
        page.wait_for_timeout(max(0, min(ms, 10000)))
        result["ms"] = ms
        return result

    if action_type == "screenshot":
        screenshot_path = root / "screenshots" / f"{label}.png"
        page.screenshot(path=screenshot_path, full_page=bool(action.get("full_page", True)))
        result["screenshot_path"] = rel(screenshot_path)
        return result

    if action_type == "expect_text":
        expected = str(action.get("text") or "")
        body_text = page.locator("body").inner_text(timeout=timeout_ms)
        if expected not in body_text:
            raise AssertionError(f"Missing expected text: {expected}")
        result["text"] = expected
        return result

    selector = str(action.get("selector") or "").strip()
    if action_type == "expect_visible":
        if not selector:
            raise ValueError("expect_visible requires selector.")
        page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
        result["selector"] = selector
        return result

    if action_type == "click":
        if not selector:
            raise ValueError("click requires selector.")
        locator = page.locator(selector).first
        locator.wait_for(state="visible", timeout=timeout_ms)
        locator.click(timeout=timeout_ms)
        result["selector"] = selector
        return result

    if action_type == "press":
        key = str(action.get("key") or "")
        if not key:
            raise ValueError("press requires key.")
        if selector:
            page.locator(selector).first.press(key, timeout=timeout_ms)
        else:
            page.keyboard.press(key)
        result["key"] = key
        result["selector"] = selector or None
        return result

    if action_type in {"type", "fill"}:
        if not selector:
            raise ValueError(f"{action_type} requires selector.")
        text = str(action.get("text") or "")
        page.locator(selector).first.fill(text, timeout=timeout_ms)
        result["selector"] = selector
        result["text_length"] = len(text)
        return result

    if action_type == "drag":
        if not selector:
            raise ValueError("drag requires selector.")
        locator = page.locator(selector).first
        locator.wait_for(state="visible", timeout=timeout_ms)
        box = locator.bounding_box(timeout=timeout_ms)
        if not box:
            raise ValueError(f"Could not resolve bounding box for selector: {selector}")
        default_x = float(box["width"]) / 2
        default_y = float(box["height"]) / 2
        start_x, start_y = _point_from_action(action, "from", _number(action.get("start_x"), default_x), _number(action.get("start_y"), default_y))
        if "to" in action:
            end_x, end_y = _point_from_action(action, "to", start_x, start_y)
        else:
            end_x = _number(action.get("end_x"), start_x + _number(action.get("dx"), 0))
            end_y = _number(action.get("end_y"), start_y + _number(action.get("dy"), 0))
        absolute_start_x = float(box["x"]) + start_x
        absolute_start_y = float(box["y"]) + start_y
        absolute_end_x = float(box["x"]) + end_x
        absolute_end_y = float(box["y"]) + end_y
        steps = max(1, min(int(_number(action.get("steps"), 12)), 100))
        page.mouse.move(absolute_start_x, absolute_start_y)
        page.mouse.down()
        page.mouse.move(absolute_end_x, absolute_end_y, steps=steps)
        page.mouse.up()
        result.update(
            {
                "selector": selector,
                "from": {"x": start_x, "y": start_y},
                "to": {"x": end_x, "y": end_y},
                "steps": steps,
            }
        )
        return result

    raise ValueError(f"Unsupported browser action: {action_type}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture browser evidence for a local generated app.")
    parser.add_argument("--name", default="browser", help="Short evidence name.")
    parser.add_argument("--entry", help="HTML entry file relative to the QA workspace.")
    parser.add_argument("--url", help="Local URL, restricted to file/localhost/127.0.0.1.")
    parser.add_argument("--expect-text", action="append", default=[], help="Text expected in page body.")
    parser.add_argument("--expect-selector", action="append", default=[], help="CSS selector expected to be visible.")
    parser.add_argument("--action-file", help="JSON action file relative to the QA workspace.")
    parser.add_argument("--timeout-ms", type=int, default=10000)
    parser.add_argument("--wait-ms", type=int, default=500)
    parser.add_argument("--viewport", default="1280x900", help="Viewport as WIDTHxHEIGHT.")
    parser.add_argument(
        "--wait-until",
        choices=["load", "domcontentloaded", "networkidle"],
        default="load",
        help="Playwright page.goto wait strategy.",
    )
    parser.add_argument("--no-final-screenshot", action="store_true", help="Do not capture the default final screenshot.")
    args = parser.parse_args()

    root = workspace_root()
    name = safe_name(args.name, "browser")
    result_path = root / "evidence" / "browser" / f"{name}_result.json"
    console_path = root / "evidence" / "browser" / f"{name}_console.json"
    screenshot_path = root / "screenshots" / f"{name}.png"
    target = ""
    console_messages: list[dict[str, str]] = []
    findings: list[str] = []
    action_results: list[dict[str, Any]] = []
    screenshots: list[str] = []
    status = "PASS"

    try:
        target = _target_url(args.entry, args.url)
        actions = _load_actions(args.action_file)
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            profile_dir = root / "scratch" / f"chrome-profile-{name}"
            profile_dir.mkdir(parents=True, exist_ok=True)
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=True,
                viewport=_parse_viewport(args.viewport),
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.on(
                    "console",
                    lambda msg: console_messages.append({"type": msg.type, "text": msg.text}),
                )
                page.goto(target, wait_until=args.wait_until, timeout=max(1000, args.timeout_ms))
                if args.wait_ms > 0:
                    page.wait_for_timeout(args.wait_ms)
                body_text = page.locator("body").inner_text(timeout=max(1000, args.timeout_ms))
                for expected in args.expect_text:
                    if expected not in body_text:
                        findings.append(f"Missing expected text: {expected}")
                for selector in args.expect_selector:
                    try:
                        page.locator(selector).first.wait_for(state="visible", timeout=max(1000, args.timeout_ms))
                    except PlaywrightTimeoutError:
                        findings.append(f"Expected selector was not visible: {selector}")
                for index, action in enumerate(actions, start=1):
                    try:
                        action_result = _run_action(
                            page,
                            action,
                            root=root,
                            base_name=name,
                            index=index,
                            timeout_ms=max(1000, args.timeout_ms),
                        )
                        if action_result.get("screenshot_path"):
                            screenshots.append(str(action_result["screenshot_path"]))
                        action_results.append(action_result)
                    except Exception as exc:
                        action_result = {
                            "index": index,
                            "action": str(action.get("action") or ""),
                            "name": str(action.get("name") or f"{name}_{index:02d}"),
                            "status": "FAIL",
                            "error": str(exc),
                        }
                        action_results.append(action_result)
                        if not bool(action.get("optional")):
                            findings.append(f"Action {index} failed: {exc}")
                if not args.no_final_screenshot:
                    page.screenshot(path=screenshot_path, full_page=True)
                    screenshots.append(rel(screenshot_path))
            finally:
                context.close()
    except ImportError as exc:
        status = "UNSUPPORTED"
        findings.append(f"Playwright is unavailable: {exc}")
    except Exception as exc:
        status = "FAIL"
        findings.append(str(exc))

    if status == "PASS" and findings:
        status = "FAIL"
    result = {
        "tool": "browser_probe",
        "name": name,
        "status": status,
        "target": target,
        "expect_text": args.expect_text,
        "expect_selector": args.expect_selector,
        "action_file": args.action_file,
        "actions": action_results,
        "findings": findings,
        "screenshot_path": rel(screenshot_path) if screenshot_path.exists() else None,
        "screenshots": screenshots,
        "console_path": rel(console_path),
    }
    write_json(console_path, {"messages": console_messages})
    write_json(result_path, result)
    append_command_log({**result, "purpose": "Browser visual QA probe.", "exit_code": 0, "result_path": rel(result_path)})
    finish({**result, "result_path": rel(result_path)})


if __name__ == "__main__":
    main()
