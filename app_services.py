"""Local application service layer for GUI, API, and future adapters.

The services in this module deliberately avoid importing FastAPI.  They expose
the local run state, artifacts, configuration defaults, and operator actions in
a UI-agnostic form so Discord, HTTP, and desktop shells can share the same
behavior.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility.
    tomllib = None  # type: ignore[assignment]

from local_dashboard_runner import LocalRunConfig, REASONING_EFFORTS, RUN_MODES
from reference_packs import DEFAULT_REFERENCE_PROFILES
from run_worker import RunJob, RunWorker
from routing import ROUTING_MODES, RoutingDecision, decide_route, normalize_routing_mode
from state_store import StateStore
from workflow_engine import workflow_from_route
from workspace_manager import create_logs_dir, create_run_dir


ArtifactKind = Literal["file", "image", "log", "directory", "unknown"]
DashboardMode = Literal["planning_only", "contract_only", "scaffold_only"]
LOCAL_ENV_KEYS = {
    "CODEX_HOME",
    "PLANNER_A_CODEX_HOME",
    "PLANNER_B_CODEX_HOME",
    "PLANNER_C_CODEX_HOME",
    "ARCHITECT_CODEX_HOME",
    "SCAFFOLD_CODEX_HOME",
    "DEVELOPER_CODEX_HOME",
    "INTEGRATOR_CODEX_HOME",
    "CODE_AGENT_CODEX_HOMES",
    "CODE_AGENT_COUNT",
    "QA_AGENT_CODEX_HOMES",
    "QA_AGENT_COUNT",
    "CODEX_MODEL",
    "CODEX_REASONING_EFFORT",
    "MAX_FIX_ITERATIONS",
    "CODEX_TIMEOUT_SECONDS",
    "LOCAL_API_HOST",
    "LOCAL_API_PORT",
    "EXECUTABLE_QA_ENABLED",
    "EXECUTABLE_QA_TIMEOUT_SECONDS",
    "EXECUTABLE_QA_ALLOW_LOCAL_COMMANDS",
}


class RunCreateRequest(BaseModel):
    """Request body for creating a local run from the app/API."""

    user_request: str = Field(..., min_length=1)
    routing_mode: str = "balanced"
    dashboard_mode: DashboardMode = "planning_only"
    planner_count: int | None = Field(default=None, ge=1, le=3)
    code_agent_count: int | None = Field(default=None, ge=1, le=6)
    qa_agent_count: int | None = Field(default=None, ge=0, le=2)
    model: str | None = None
    reasoning_effort: str | None = None
    max_fix_iterations: int | None = Field(default=None, ge=0, le=5)
    timeout_seconds: int | None = Field(default=None, ge=60, le=7200)
    planner_a_codex_home: str | None = None
    planner_b_codex_home: str | None = None
    planner_c_codex_home: str | None = None
    architect_codex_home: str | None = None
    scaffold_codex_home: str | None = None
    integrator_codex_home: str | None = None
    code_agent_codex_homes: list[str | None] | None = None
    qa_agent_codex_homes: list[str | None] | None = None

    @field_validator("user_request")
    @classmethod
    def _strip_user_request(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("user_request is required")
        return stripped

    @field_validator("routing_mode")
    @classmethod
    def _validate_routing_mode(cls, value: str) -> str:
        return normalize_routing_mode(value)

    @field_validator("reasoning_effort")
    @classmethod
    def _validate_reasoning(cls, value: str | None) -> str | None:
        if value in {None, ""}:
            return None
        if value not in REASONING_EFFORTS:
            allowed = ", ".join(REASONING_EFFORTS)
            raise ValueError(f"reasoning_effort must be one of: {allowed}")
        return value


class OperatorActionRequest(BaseModel):
    user_id: str = "local-operator"
    feedback: str = ""


class RunSummary(BaseModel):
    run_id: str
    status: str
    user_request: str
    created_at: str | None = None
    updated_at: str | None = None
    route_mode: str | None = None
    dashboard_mode: str | None = None
    run_dir: str
    artifact_count: int


class RunDetail(RunSummary):
    state: dict[str, Any]


class TimelineArtifact(BaseModel):
    name: str
    path: str
    type: ArtifactKind


class TimelineEvent(BaseModel):
    id: str
    run_id: str
    kind: str
    actor: str
    who: str
    at: str
    time: str
    status: str
    title: str
    summary: str = ""
    details: list[str] = Field(default_factory=list)
    artifacts: list[TimelineArtifact] = Field(default_factory=list)
    raw: dict[str, Any]


class ArtifactInfo(BaseModel):
    path: str
    name: str
    kind: ArtifactKind
    size_bytes: int | None = None
    modified_at: str | None = None
    media_type: str | None = None
    source: str = "discovered"


class ArtifactContent(BaseModel):
    path: str
    name: str
    kind: ArtifactKind
    media_type: str | None
    size_bytes: int
    encoding: str
    content: str
    truncated: bool = False


class ConfigSnapshot(BaseModel):
    routing_modes: tuple[str, ...]
    dashboard_modes: tuple[str, ...]
    reasoning_efforts: tuple[str, ...]
    reference_profiles: dict[str, str]
    defaults: dict[str, Any]
    providers: list[dict[str, Any]]


class ConfigService:
    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        load_local_app_env(self.project_root)

    def get_config(self) -> ConfigSnapshot:
        defaults = LocalRunConfig.from_env()
        codex_defaults = self._codex_cli_defaults(defaults)
        model = defaults.model or codex_defaults.get("model")
        reasoning_effort = defaults.reasoning_effort or codex_defaults.get("reasoning_effort")
        providers = [
            self._default_codex_provider(),
            *self._codex_home_providers(defaults),
            {
                "name": "Claude",
                "account": "not configured",
                "configured": False,
                "status": "display-only",
                "display_only": True,
            },
        ]
        return ConfigSnapshot(
            routing_modes=ROUTING_MODES,
            dashboard_modes=tuple(mode for mode in RUN_MODES if mode != "full_run"),
            reasoning_efforts=REASONING_EFFORTS,
            reference_profiles=dict(DEFAULT_REFERENCE_PROFILES),
            defaults={
                "dashboard_mode": defaults.run_mode,
                "routing_mode": "balanced",
                "planner_count": defaults.planner_count,
                "code_agent_count": defaults.code_agent_count,
                "qa_agent_count": defaults.qa_agent_count,
                "model": model,
                "model_source": "CODEX_MODEL" if defaults.model else codex_defaults.get("model_source"),
                "reasoning_effort": reasoning_effort,
                "reasoning_source": (
                    "CODEX_REASONING_EFFORT" if defaults.reasoning_effort else codex_defaults.get("reasoning_source")
                ),
                "max_fix_iterations": defaults.max_fix_iterations,
                "timeout_seconds": defaults.timeout_seconds,
                "codex_homes": {
                    "planner_a": defaults.planner_a_codex_home,
                    "planner_b": defaults.planner_b_codex_home,
                    "planner_c": defaults.planner_c_codex_home,
                    "architect": defaults.architect_codex_home,
                    "scaffold": defaults.scaffold_codex_home,
                    "integrator": defaults.integrator_codex_home,
                    "code_agents": defaults.code_agent_codex_homes,
                    "qa_agents": defaults.qa_agent_codex_homes,
                },
            },
            providers=providers,
        )

    def _codex_home_providers(self, defaults: LocalRunConfig) -> list[dict[str, Any]]:
        homes: list[str] = []
        default_home = os.environ.get("CODEX_HOME", "").strip()
        for value in [
            defaults.planner_a_codex_home,
            defaults.planner_b_codex_home,
            defaults.planner_c_codex_home,
            defaults.architect_codex_home,
            defaults.scaffold_codex_home,
            defaults.integrator_codex_home,
            *defaults.code_agent_codex_homes,
            *defaults.qa_agent_codex_homes,
        ]:
            if value and value != default_home and value not in homes:
                homes.append(value)
        return [
            {
                "name": "Codex",
                "account": Path(home).name or home,
                "configured": True,
                "status": home,
                "display_only": False,
            }
            for home in homes
        ]

    def _default_codex_provider(self) -> dict[str, Any]:
        default_home = os.environ.get("CODEX_HOME", "").strip()
        if default_home:
            return {
                "name": "Codex",
                "account": Path(default_home).name or default_home,
                "configured": True,
                "status": default_home,
                "display_only": False,
            }
        return {
            "name": "Codex",
            "account": "default",
            "configured": True,
            "status": "local CLI",
            "display_only": False,
        }

    def _codex_cli_defaults(self, defaults: LocalRunConfig) -> dict[str, str]:
        config_paths = self._codex_config_paths(defaults)
        for path in config_paths:
            if not path.exists() or not path.is_file():
                continue
            try:
                data = _read_codex_config_toml(path)
            except OSError:
                continue
            profile = self._active_profile(data)
            model = _first_str(
                profile.get("model"),
                profile.get("model_id"),
                data.get("model"),
                data.get("model_id"),
            )
            reasoning = _first_str(
                profile.get("model_reasoning_effort"),
                profile.get("reasoning_effort"),
                profile.get("reasoning"),
                data.get("model_reasoning_effort"),
                data.get("reasoning_effort"),
                data.get("reasoning"),
            )
            result: dict[str, str] = {}
            if model:
                result["model"] = model
                result["model_source"] = "Codex config"
            if reasoning:
                result["reasoning_effort"] = reasoning
                result["reasoning_source"] = "Codex config"
            if result:
                return result
        return {}

    def _codex_config_paths(self, defaults: LocalRunConfig) -> list[Path]:
        homes: list[Path] = []
        env_home = os.environ.get("CODEX_HOME", "").strip()
        if env_home:
            homes.append(Path(env_home))
        for value in [
            defaults.planner_a_codex_home,
            defaults.planner_b_codex_home,
            defaults.planner_c_codex_home,
            defaults.architect_codex_home,
            defaults.scaffold_codex_home,
            defaults.integrator_codex_home,
            *defaults.code_agent_codex_homes,
            *defaults.qa_agent_codex_homes,
        ]:
            if value:
                homes.append(Path(value))
        homes.append(Path.home() / ".codex")

        paths: list[Path] = []
        seen: set[str] = set()
        for home in homes:
            path = home / "config.toml"
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            paths.append(path)
        return paths

    def _active_profile(self, data: dict[str, Any]) -> dict[str, Any]:
        profiles = data.get("profiles")
        if not isinstance(profiles, dict):
            return {}
        profile_name = _first_str(data.get("profile"), data.get("active_profile"), data.get("default_profile"))
        if profile_name and isinstance(profiles.get(profile_name), dict):
            return profiles[profile_name]
        default_profile = profiles.get("default")
        return default_profile if isinstance(default_profile, dict) else {}


class RunService:
    def __init__(self, project_root: Path, worker: RunWorker | None = None) -> None:
        self.project_root = Path(project_root)
        load_local_app_env(self.project_root)
        self.runs_root = self.project_root / "runs"
        self.worker = worker

    def list_runs(self, limit: int = 50) -> list[RunSummary]:
        if not self.runs_root.exists():
            return []
        run_dirs = [path for path in self.runs_root.iterdir() if path.is_dir()]
        run_dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        summaries: list[RunSummary] = []
        for run_dir in run_dirs[: max(1, limit)]:
            state_path = run_dir / "state.json"
            if not state_path.exists():
                continue
            summaries.append(self._summary_from_state(run_dir, _read_json(state_path)))
        return summaries

    def get_run(self, run_id: str) -> RunDetail:
        run_dir = self._run_dir(run_id)
        state = _read_json(run_dir / "state.json")
        return RunDetail(**self._summary_from_state(run_dir, state).model_dump(), state=state)

    def create_run(self, request: RunCreateRequest) -> RunDetail:
        config = self._local_config_from_request(request)
        run_dir = create_run_dir(self.project_root)
        create_logs_dir(run_dir)
        store = StateStore(run_dir)
        store.initialize(
            user_request=config.user_request,
            discord={"source": "local_api"},
            max_fix_iterations=config.max_fix_iterations,
            code_agent_count=config.code_agent_count,
            qa_agent_count=config.qa_agent_count,
        )
        self._record_local_config(store, config)
        route = decide_route(
            request.user_request,
            requested_mode=request.routing_mode,
            max_code_agent_count=config.code_agent_count,
            max_qa_agent_count=config.qa_agent_count,
        )
        self._record_route(store, route)
        store.set_status("planning_queued")
        return self.get_run(run_dir.name)

    async def create_run_and_enqueue(self, request: RunCreateRequest) -> RunDetail:
        detail = self.create_run(request)
        if self.worker:
            await self.worker.enqueue(RunJob(run_id=detail.run_id, kind="start_planning"))
        return self.get_run(detail.run_id)

    def approve(self, run_id: str, action: OperatorActionRequest) -> RunDetail:
        store = StateStore(self._run_dir(run_id))
        status = str(store.load().get("status") or "")
        if status not in {"awaiting_plan_approval", "awaiting_contract_approval"}:
            raise ValueError(f"Run {run_id} is not waiting for plan or contract approval.")
        store.add_approval(action="approved", user_id=action.user_id, feedback=action.feedback)
        store.clear_control_action()
        store.set_status("development_queued")
        return self.get_run(run_id)

    async def approve_and_enqueue(self, run_id: str, action: OperatorActionRequest) -> RunDetail:
        detail = self.approve(run_id, action)
        if self.worker:
            await self.worker.enqueue(
                RunJob(
                    run_id=run_id,
                    kind="continue_after_plan_approval",
                    feedback=action.feedback,
                    requested_by=action.user_id,
                )
            )
        return detail

    def request_changes(self, run_id: str, action: OperatorActionRequest) -> RunDetail:
        store = StateStore(self._run_dir(run_id))
        status = str(store.load().get("status") or "")
        if status not in {"awaiting_plan_approval", "awaiting_contract_approval"}:
            raise ValueError(f"Run {run_id} is not waiting for plan or contract revision.")
        store.add_approval(action="revision_requested", user_id=action.user_id, feedback=action.feedback)
        store.append_transcript("Local Revision Feedback", action.feedback or "(no feedback)")
        store.request_control_action(action="revise_plan", requested_by=action.user_id, feedback=action.feedback)
        store.set_status("planning_queued")
        return self.get_run(run_id)

    async def request_changes_and_enqueue(self, run_id: str, action: OperatorActionRequest) -> RunDetail:
        detail = self.request_changes(run_id, action)
        if self.worker:
            await self.worker.enqueue(
                RunJob(
                    run_id=run_id,
                    kind="revise_plan",
                    feedback=action.feedback,
                    requested_by=action.user_id,
                )
            )
        return detail

    def cancel(self, run_id: str, action: OperatorActionRequest) -> RunDetail:
        store = StateStore(self._run_dir(run_id))
        store.add_approval(action="cancelled", user_id=action.user_id, feedback=action.feedback)
        store.request_control_action(action="cancel", requested_by=action.user_id, feedback=action.feedback)
        store.set_status("cancelled")
        return self.get_run(run_id)

    async def cancel_and_enqueue(self, run_id: str, action: OperatorActionRequest) -> RunDetail:
        detail = self.cancel(run_id, action)
        if self.worker:
            await self.worker.enqueue(
                RunJob(
                    run_id=run_id,
                    kind="cancel",
                    feedback=action.feedback,
                    requested_by=action.user_id,
                )
            )
        return detail

    def approve_qa(self, run_id: str, action: OperatorActionRequest) -> RunDetail:
        store = StateStore(self._run_dir(run_id))
        store.add_approval(action="qa_approved", user_id=action.user_id, feedback=action.feedback)
        store.set_status("completed")
        return self.get_run(run_id)

    def request_qa_fix(self, run_id: str, action: OperatorActionRequest) -> RunDetail:
        store = StateStore(self._run_dir(run_id))
        store.add_approval(action="qa_fix_requested", user_id=action.user_id, feedback=action.feedback)
        store.append_transcript("Local QA Fix Feedback", action.feedback or "(no feedback)")
        store.set_status("qa_fix_requested")
        return self.get_run(run_id)

    def _local_config_from_request(self, request: RunCreateRequest) -> LocalRunConfig:
        defaults = LocalRunConfig.from_env()
        code_count = request.code_agent_count if request.code_agent_count is not None else defaults.code_agent_count
        qa_count = request.qa_agent_count if request.qa_agent_count is not None else defaults.qa_agent_count
        return LocalRunConfig(
            user_request=request.user_request,
            run_mode=request.dashboard_mode,
            planner_count=request.planner_count if request.planner_count is not None else defaults.planner_count,
            code_agent_count=code_count,
            qa_agent_count=qa_count,
            planner_a_codex_home=request.planner_a_codex_home or defaults.planner_a_codex_home,
            planner_b_codex_home=request.planner_b_codex_home or defaults.planner_b_codex_home,
            planner_c_codex_home=request.planner_c_codex_home or defaults.planner_c_codex_home,
            architect_codex_home=request.architect_codex_home or defaults.architect_codex_home,
            scaffold_codex_home=request.scaffold_codex_home or defaults.scaffold_codex_home,
            integrator_codex_home=request.integrator_codex_home or defaults.integrator_codex_home,
            code_agent_codex_homes=_expand_list(request.code_agent_codex_homes, defaults.code_agent_codex_homes, code_count),
            qa_agent_codex_homes=_expand_list(request.qa_agent_codex_homes, defaults.qa_agent_codex_homes, qa_count),
            model=request.model if request.model is not None else defaults.model,
            reasoning_effort=request.reasoning_effort if request.reasoning_effort is not None else defaults.reasoning_effort,
            max_fix_iterations=(
                request.max_fix_iterations if request.max_fix_iterations is not None else defaults.max_fix_iterations
            ),
            timeout_seconds=request.timeout_seconds if request.timeout_seconds is not None else defaults.timeout_seconds,
        )

    def _record_route(self, store: StateStore, route: RoutingDecision) -> None:
        payload = route.to_dict()
        state = store.load()
        state["routing"] = payload
        state["parallel"] = {
            "code_agent_count": route.code_agent_count,
            "qa_agent_count": route.qa_agent_count,
        }
        store.save(state)
        store.set_workflow(workflow_from_route(route))
        route_path = store.write_artifact("route.json", _json_text(payload), artifact_name="route")
        store.append_event("routing_decision", "system", f"Selected {route.mode} route", {"path": store.to_relative(route_path), **payload})

    def _record_local_config(self, store: StateStore, config: LocalRunConfig) -> None:
        payload = {
            "source": "local_api",
            "run_mode": config.run_mode,
            "planner_count": config.planner_count,
            "code_agent_count": config.code_agent_count,
            "qa_agent_count": config.qa_agent_count,
            "model": config.model,
            "reasoning_effort": config.reasoning_effort,
            "max_fix_iterations": config.max_fix_iterations,
            "timeout_seconds": config.timeout_seconds,
            "codex_homes": {
                "planner_a": config.planner_a_codex_home,
                "planner_b": config.planner_b_codex_home,
                "planner_c": config.planner_c_codex_home,
                "architect": config.architect_codex_home,
                "scaffold": config.scaffold_codex_home,
                "integrator": config.integrator_codex_home,
                "code_agents": config.code_agent_codex_homes,
                "qa_agents": config.qa_agent_codex_homes,
            },
        }
        state = store.load()
        state["dashboard_config"] = payload
        store.save(state)
        store.append_event("dashboard_config", "system", "Local API run configuration saved", payload)

    def _set_post_create_status(self, store: StateStore, dashboard_mode: str, route: RoutingDecision) -> None:
        if dashboard_mode == "planning_only":
            store.set_status("awaiting_plan_approval")
            return
        if route.uses_contract:
            store.set_status("awaiting_contract_approval")
            return
        store.set_status("awaiting_plan_approval")

    def _summary_from_state(self, run_dir: Path, state: dict[str, Any]) -> RunSummary:
        routing = state.get("routing") or {}
        dashboard_config = state.get("dashboard_config") or {}
        return RunSummary(
            run_id=str(state.get("run_id") or run_dir.name),
            status=str(state.get("status") or "unknown"),
            user_request=str(state.get("user_request") or ""),
            created_at=_optional_str(state.get("created_at")),
            updated_at=_optional_str(state.get("updated_at")),
            route_mode=_optional_str(routing.get("mode")),
            dashboard_mode=_optional_str(dashboard_config.get("run_mode")),
            run_dir=str(run_dir),
            artifact_count=len(state.get("artifacts") or {}),
        )

    def _run_dir(self, run_id: str) -> Path:
        return _safe_run_dir(self.runs_root, run_id)


class EventService:
    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.runs_root = self.project_root / "runs"

    def list_events(self, run_id: str) -> list[TimelineEvent]:
        run_dir = _safe_run_dir(self.runs_root, run_id)
        events_path = run_dir / "events.jsonl"
        if not events_path.exists():
            return []
        events: list[TimelineEvent] = []
        for index, line in enumerate(events_path.read_text(encoding="utf-8", errors="replace").splitlines()):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                raw = {"at": "", "run_id": run_id, "type": "parse_error", "actor": "system", "message": line, "data": {}}
            events.append(self._timeline_event(run_id, index, raw))
        return events

    def _timeline_event(self, run_id: str, index: int, raw: dict[str, Any]) -> TimelineEvent:
        event_type = str(raw.get("type") or "event")
        actor = str(raw.get("actor") or "system")
        message = str(raw.get("message") or event_type)
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        artifacts = _event_artifacts(data)
        details = _event_details(data)
        return TimelineEvent(
            id=f"{index:04d}-{event_type}",
            run_id=run_id,
            kind=_event_kind(event_type, actor),
            actor=actor,
            who=_actor_label(actor),
            at=str(raw.get("at") or ""),
            time=_time_label(str(raw.get("at") or "")),
            status=_event_status(event_type, message, data),
            title=message,
            summary=_event_summary(event_type, data),
            details=details,
            artifacts=artifacts,
            raw=raw,
        )


class ArtifactService:
    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.runs_root = self.project_root / "runs"

    def list_artifacts(self, run_id: str) -> list[ArtifactInfo]:
        run_dir = _safe_run_dir(self.runs_root, run_id)
        state = _read_json(run_dir / "state.json") if (run_dir / "state.json").exists() else {}
        artifacts: dict[str, ArtifactInfo] = {}

        for _name, rel_path in (state.get("artifacts") or {}).items():
            if not isinstance(rel_path, str):
                continue
            path = _safe_artifact_path(run_dir, rel_path)
            if path.exists():
                info = self._artifact_info(run_dir, path, source="state")
                artifacts[info.path] = info

        for path in self._discover_artifact_paths(run_dir):
            info = self._artifact_info(run_dir, path, source="discovered")
            artifacts.setdefault(info.path, info)

        return sorted(artifacts.values(), key=lambda item: (item.kind == "directory", item.path))

    def read_artifact(self, run_id: str, relative_path: str, *, max_bytes: int = 512_000) -> ArtifactContent:
        run_dir = _safe_run_dir(self.runs_root, run_id)
        path = _safe_artifact_path(run_dir, relative_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Artifact not found: {relative_path}")
        data = path.read_bytes()
        truncated = len(data) > max_bytes
        payload = data[:max_bytes]
        kind = _artifact_kind(path)
        media_type = mimetypes.guess_type(path.name)[0]
        if _is_binary(payload, media_type):
            content = base64.b64encode(payload).decode("ascii")
            encoding = "base64"
        else:
            content = payload.decode("utf-8", errors="replace")
            encoding = "utf-8"
        return ArtifactContent(
            path=path.relative_to(run_dir).as_posix(),
            name=path.name,
            kind=kind,
            media_type=media_type,
            size_bytes=len(data),
            encoding=encoding,
            content=content,
            truncated=truncated,
        )

    def _discover_artifact_paths(self, run_dir: Path) -> list[Path]:
        roots = [
            run_dir / "planning",
            run_dir / "contract",
            run_dir / "qa",
            run_dir / "logs",
            run_dir / "agent_outputs",
            run_dir / "generated_app",
            run_dir / "integration",
        ]
        root_files = [
            run_dir / "state.json",
            run_dir / "events.jsonl",
            run_dir / "transcript.md",
            run_dir / "plan.md",
            run_dir / "route.json",
            run_dir / "qa_report.md",
        ]
        paths: list[Path] = [path for path in root_files if path.exists()]
        for root in roots:
            if not root.exists():
                continue
            paths.append(root)
            paths.extend(path for path in root.rglob("*") if path.is_file())
        return paths

    def _artifact_info(self, run_dir: Path, path: Path, *, source: str) -> ArtifactInfo:
        stat = path.stat()
        return ArtifactInfo(
            path=path.relative_to(run_dir).as_posix(),
            name=path.name,
            kind="directory" if path.is_dir() else _artifact_kind(path),
            size_bytes=None if path.is_dir() else stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
            media_type=None if path.is_dir() else mimetypes.guess_type(path.name)[0],
            source=source,
        )


def load_local_app_env(project_root: Path) -> None:
    """Load non-secret local app defaults from .env files without overriding shell env."""

    protected = set(os.environ)
    for env_name in [".env", ".env.local"]:
        env_path = Path(project_root) / env_name
        if not env_path.exists() or not env_path.is_file():
            continue
        try:
            lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for key, value in _iter_local_env_lines(lines):
            if key in LOCAL_ENV_KEYS and key not in protected:
                os.environ[key] = value


def _iter_local_env_lines(lines: list[str]) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, raw_value = [part.strip() for part in line.split("=", 1)]
        if not key:
            continue
        entries.append((key, _env_string_value(raw_value)))
    return entries


def _env_string_value(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value[0] in {'"', "'"}:
        quote = value[0]
        end = value.find(quote, 1)
        return value[1:end] if end > 0 else value[1:]
    return value.split("#", 1)[0].strip()


def _safe_run_dir(runs_root: Path, run_id: str) -> Path:
    if not run_id or any(part in run_id for part in ["/", "\\", ".."]):
        raise FileNotFoundError(f"Invalid run id: {run_id}")
    run_dir = (Path(runs_root) / run_id).resolve()
    runs_root_resolved = Path(runs_root).resolve()
    try:
        run_dir.relative_to(runs_root_resolved)
    except ValueError as exc:
        raise FileNotFoundError(f"Invalid run id: {run_id}") from exc
    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError(f"Run not found: {run_id}")
    return run_dir


def _safe_artifact_path(run_dir: Path, relative_path: str) -> Path:
    rel = Path(relative_path)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise FileNotFoundError(f"Invalid artifact path: {relative_path}")
    path = (run_dir / rel).resolve()
    run_root = run_dir.resolve()
    try:
        path.relative_to(run_root)
    except ValueError as exc:
        raise FileNotFoundError(f"Invalid artifact path: {relative_path}") from exc
    return path


def _expand_list(values: list[str | None] | None, defaults: list[str | None], count: int) -> list[str | None]:
    source = values if values is not None else defaults
    if count <= 0:
        return []
    if not source:
        return [None for _ in range(count)]
    return [source[index % len(source)] for index in range(count)]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_codex_config_toml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if tomllib is not None:
        try:
            return tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            pass
    return _read_minimal_codex_config(text)


def _read_minimal_codex_config(text: str) -> dict[str, Any]:
    """Extract only non-secret Codex display defaults from simple TOML."""

    data: dict[str, Any] = {}
    profiles: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] = data
    tracked_keys = {
        "profile",
        "active_profile",
        "default_profile",
        "model",
        "model_id",
        "model_reasoning_effort",
        "reasoning_effort",
        "reasoning",
    }

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            if section.startswith("profiles."):
                name = section.split(".", 1)[1].strip().strip('"').strip("'")
                current = profiles.setdefault(name, {})
                data["profiles"] = profiles
            else:
                current = {}
            continue
        if "=" not in line:
            continue
        key, raw_value = [part.strip() for part in line.split("=", 1)]
        key = key.strip('"').strip("'")
        if key not in tracked_keys:
            continue
        value = _toml_string_value(raw_value)
        if value:
            current[key] = value
    return data


def _toml_string_value(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value[0] in {'"', "'"}:
        quote = value[0]
        end = value.find(quote, 1)
        return value[1:end].strip() if end > 0 else value[1:].strip()
    return value.split("#", 1)[0].strip()


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _event_kind(event_type: str, actor: str) -> str:
    if event_type == "approval":
        return "approval"
    if "error" in event_type or "failed" in event_type:
        return "error"
    if actor == "system":
        return "system"
    if actor == "user":
        return "user"
    return "agent"


def _actor_label(actor: str) -> str:
    labels = {
        "planner_a": "Planner A",
        "planner_b": "Planner B",
        "planner_c": "Planner C",
        "architect": "Architect",
        "scaffold": "Scaffold",
        "developer": "Developer",
        "integrator": "Integrator",
        "qa": "QA",
        "qa_1": "QA Agent 1",
        "system": "System",
        "user": "Operator",
    }
    if actor.startswith("code_"):
        return f"Code Agent {actor.split('_', 1)[1]}"
    if actor.startswith("qa_"):
        return f"QA Agent {actor.split('_', 1)[1]}"
    return labels.get(actor, actor.replace("_", " ").title())


def _event_status(event_type: str, message: str, data: dict[str, Any]) -> str:
    normalized = f"{event_type} {message}".lower()
    if data.get("ok") is False or "failed" in normalized or "error" in normalized:
        return "error"
    if "awaiting" in normalized or "waiting" in normalized or "requested" in normalized:
        return "waiting"
    if "running" in normalized or "started" in normalized:
        return "running"
    if "cancelled" in normalized:
        return "paused"
    if "completed" in normalized or "created" in normalized or "approved" in normalized or data.get("ok") is True:
        return "done"
    return "idle"


def _event_summary(event_type: str, data: dict[str, Any]) -> str:
    if event_type == "status_changed":
        return ""
    if "path" in data:
        return f"Artifact: {data['path']}"
    if "files" in data and isinstance(data["files"], list):
        return f"{len(data['files'])} files"
    if "agents" in data and isinstance(data["agents"], list):
        return ", ".join(str(agent) for agent in data["agents"])
    if "feedback" in data and data["feedback"]:
        return str(data["feedback"])
    if "qa_status" in data:
        return f"QA status: {data['qa_status']}"
    return ""


def _event_details(data: dict[str, Any]) -> list[str]:
    details: list[str] = []
    for key in ["mode", "reason", "model", "reasoning_effort", "qa_status", "executable_status", "executable_app_type"]:
        if key in data and data[key] not in {None, ""}:
            details.append(f"{key}: {data[key]}")
    for key in ["files", "checked_files", "screenshots", "affected_paths", "suspected_owners"]:
        value = data.get(key)
        if isinstance(value, list):
            details.extend(f"{key}: {item}" for item in value[:12])
    return details


def _event_artifacts(data: dict[str, Any]) -> list[TimelineArtifact]:
    artifacts: list[TimelineArtifact] = []
    if isinstance(data.get("path"), str):
        path = str(data["path"])
        artifacts.append(TimelineArtifact(name=Path(path).name or path, path=path, type=_artifact_kind(Path(path))))
    for key in ["files", "screenshots"]:
        value = data.get(key)
        if not isinstance(value, list):
            continue
        for raw_path in value[:20]:
            path = str(raw_path)
            artifacts.append(TimelineArtifact(name=Path(path).name or path, path=path, type=_artifact_kind(Path(path))))
    return artifacts


def _artifact_kind(path: Path) -> ArtifactKind:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        return "image"
    if suffix in {".log"} or "stdout" in path.name or "stderr" in path.name:
        return "log"
    if suffix in {".md", ".txt", ".json", ".jsonl", ".py", ".tsx", ".ts", ".js", ".css", ".html", ".toml", ".yaml", ".yml"}:
        return "file"
    return "unknown"


def _is_binary(data: bytes, media_type: str | None) -> bool:
    if media_type and (media_type.startswith("image/") or media_type.startswith("application/octet-stream")):
        return True
    return b"\x00" in data[:2048]


def _time_label(value: str) -> str:
    if not value:
        return "--"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%H:%M:%S")
    except ValueError:
        return value


def service_debug_dump(model: BaseModel) -> dict[str, Any]:
    """Small helper for tests and diagnostics."""

    return json.loads(model.model_dump_json())
