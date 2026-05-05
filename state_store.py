"""Persistent run state for Discord human-in-the-loop workflows."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class StateStore:
    """Read and write state, events, and transcript files for one run."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = Path(run_dir)
        self.state_path = self.run_dir / "state.json"
        self.events_path = self.run_dir / "events.jsonl"
        self.transcript_path = self.run_dir / "transcript.md"

    @property
    def run_id(self) -> str:
        return self.run_dir.name

    def initialize(
        self,
        *,
        user_request: str,
        discord: dict[str, Any] | None = None,
        max_fix_iterations: int = 1,
        code_agent_count: int = 1,
        qa_agent_count: int = 1,
    ) -> dict[str, Any]:
        agent_sessions = {
            "planner_a": {"session_id": None, "codex_home": None, "last_step": None},
            "planner_b": {"session_id": None, "codex_home": None, "last_step": None},
            "architect": {"session_id": None, "codex_home": None, "last_step": None},
            "scaffold": {"session_id": None, "codex_home": None, "last_step": None},
            "developer": {"session_id": None, "codex_home": None, "last_step": None},
            "integrator": {"session_id": None, "codex_home": None, "last_step": None},
            "qa": {"session_id": None, "codex_home": None, "last_step": None},
        }
        for index in range(1, max(1, code_agent_count) + 1):
            agent_sessions[f"code_{index}"] = {"session_id": None, "codex_home": None, "last_step": None}
        for index in range(1, max(0, qa_agent_count) + 1):
            agent_sessions[f"qa_{index}"] = {"session_id": None, "codex_home": None, "last_step": None}

        state = {
            "run_id": self.run_id,
            "status": "planning_started",
            "created_at": _now(),
            "updated_at": _now(),
            "user_request": user_request,
            "max_fix_iterations": max_fix_iterations,
            "discord": discord or {},
            "parallel": {"code_agent_count": max(1, code_agent_count), "qa_agent_count": max(0, qa_agent_count)},
            "agent_sessions": agent_sessions,
            "artifacts": {},
            "approval_history": [],
            "active_step": _empty_active_step(),
            "control": _empty_control(),
            "workflow": {"mode": "balanced", "stages": []},
        }
        self.save(state)
        self.append_event("run_created", "system", "Run created", {"discord": discord or {}})
        self.append_transcript("User Request", user_request)
        return state

    def load(self) -> dict[str, Any]:
        return json.loads(_read_state_file(self.state_path))

    def save(self, state: dict[str, Any]) -> None:
        state["updated_at"] = _now()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_path.with_name(f"{self.state_path.name}.{threading.get_ident()}.tmp")
        tmp_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _replace_state_file(tmp_path, self.state_path)

    def set_status(self, status: str) -> dict[str, Any]:
        state = self.load()
        state["status"] = status
        self.save(state)
        self.append_event("status_changed", "system", status)
        return state

    def set_active_step(
        self,
        *,
        stage: str,
        agent_id: str | None = None,
        pid: int | None = None,
        interruptible: bool = False,
    ) -> dict[str, Any]:
        state = self.load()
        state["active_step"] = {
            "stage": stage,
            "agent_id": agent_id,
            "pid": pid,
            "started_at": _now(),
            "interruptible": interruptible,
        }
        self.save(state)
        self.append_event(
            "active_step_changed",
            "system",
            f"{stage} started",
            {
                "stage": stage,
                "agent_id": agent_id,
                "pid": pid,
                "interruptible": interruptible,
            },
        )
        return state

    def clear_active_step(self) -> dict[str, Any]:
        state = self.load()
        state["active_step"] = _empty_active_step()
        self.save(state)
        self.append_event("active_step_changed", "system", "active step cleared")
        return state

    def request_control_action(
        self,
        *,
        action: str,
        requested_by: int | str,
        feedback: str | None = None,
    ) -> dict[str, Any]:
        state = self.load()
        state["control"] = {
            "requested_action": action,
            "feedback": feedback or "",
            "requested_by": str(requested_by),
            "requested_at": _now(),
        }
        self.save(state)
        self.append_event(
            "control_requested",
            "user",
            action,
            {
                "requested_by": str(requested_by),
                "feedback": feedback or "",
            },
        )
        return state

    def clear_control_action(self) -> dict[str, Any]:
        state = self.load()
        state["control"] = _empty_control()
        self.save(state)
        self.append_event("control_requested", "system", "control cleared")
        return state

    def set_workflow(self, workflow: dict[str, Any]) -> dict[str, Any]:
        state = self.load()
        state["workflow"] = workflow
        self.save(state)
        self.append_event("workflow_saved", "system", "Workflow saved", workflow)
        return state

    def update_discord(self, **values: Any) -> dict[str, Any]:
        state = self.load()
        state.setdefault("discord", {}).update({key: value for key, value in values.items() if value is not None})
        self.save(state)
        return state

    def update_agent_session(
        self,
        agent_name: str,
        *,
        session_id: str | None = None,
        codex_home: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        last_step: str | None = None,
    ) -> dict[str, Any]:
        state = self.load()
        agent = state.setdefault("agent_sessions", {}).setdefault(agent_name, {})
        if session_id:
            agent["session_id"] = session_id
        if codex_home is not None:
            agent["codex_home"] = codex_home
        if model is not None:
            agent["model"] = model
        if reasoning_effort is not None:
            agent["reasoning_effort"] = reasoning_effort
        if last_step:
            agent["last_step"] = last_step
        self.save(state)
        return state

    def get_agent_session_id(self, agent_name: str) -> str | None:
        state = self.load()
        value = state.get("agent_sessions", {}).get(agent_name, {}).get("session_id")
        return str(value) if value else None

    def record_artifact(self, name: str, path: Path) -> dict[str, Any]:
        state = self.load()
        state.setdefault("artifacts", {})[name] = self.to_relative(path)
        self.save(state)
        return state

    def add_approval(self, *, action: str, user_id: int | str, feedback: str | None = None) -> dict[str, Any]:
        state = self.load()
        state.setdefault("approval_history", []).append(
            {
                "at": _now(),
                "action": action,
                "user_id": str(user_id),
                "feedback": feedback or "",
            }
        )
        self.save(state)
        self.append_event("approval", "user", action, {"user_id": str(user_id), "feedback": feedback or ""})
        return state

    def append_event(
        self,
        event_type: str,
        actor: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "at": _now(),
            "run_id": self.run_id,
            "type": event_type,
            "actor": actor,
            "message": message,
            "data": data or {},
        }
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")

    def append_transcript(self, title: str, content: str) -> None:
        self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
        with self.transcript_path.open("a", encoding="utf-8") as file:
            file.write(f"\n\n## {title}\n\n")
            file.write(content.rstrip())
            file.write("\n")

    def write_artifact(self, relative_path: str, content: str, *, artifact_name: str | None = None) -> Path:
        path = self.run_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        if artifact_name:
            self.record_artifact(artifact_name, path)
        return path

    def to_relative(self, path: Path) -> str:
        path = Path(path)
        try:
            return path.relative_to(self.run_dir).as_posix()
        except ValueError:
            return str(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty_active_step() -> dict[str, Any]:
    return {
        "stage": None,
        "agent_id": None,
        "pid": None,
        "started_at": None,
        "interruptible": False,
    }


def _empty_control() -> dict[str, Any]:
    return {
        "requested_action": "none",
        "feedback": "",
        "requested_by": "",
        "requested_at": None,
    }


def _replace_state_file(tmp_path: Path, state_path: Path) -> None:
    last_error: PermissionError | None = None
    for attempt in range(8):
        try:
            tmp_path.replace(state_path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.025 * (attempt + 1))
    if last_error is not None:
        raise last_error


def _read_state_file(state_path: Path) -> str:
    last_error: PermissionError | None = None
    for attempt in range(8):
        try:
            return state_path.read_text(encoding="utf-8")
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.025 * (attempt + 1))
    if last_error is not None:
        raise last_error
    return state_path.read_text(encoding="utf-8")
