"""Persistent run state for Discord human-in-the-loop workflows."""

from __future__ import annotations

import json
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
        }
        self.save(state)
        self.append_event("run_created", "system", "Run created", {"discord": discord or {}})
        self.append_transcript("User Request", user_request)
        return state

    def load(self) -> dict[str, Any]:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def save(self, state: dict[str, Any]) -> None:
        state["updated_at"] = _now()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def set_status(self, status: str) -> dict[str, Any]:
        state = self.load()
        state["status"] = status
        self.save(state)
        self.append_event("status_changed", "system", status)
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
