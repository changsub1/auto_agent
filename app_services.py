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
import queue
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility.
    tomllib = None  # type: ignore[assignment]

from local_dashboard_runner import LocalRunConfig, REASONING_EFFORTS, RUN_MODES
from reference_packs import DEFAULT_REFERENCE_PROFILES, normalize_reference_profile
from run_worker import RunJob, RunWorker
from routing import ROUTING_MODES, RoutingDecision, decide_route, normalize_routing_mode
from state_store import StateStore
from workflow_engine import workflow_from_route
from workspace_manager import create_logs_dir, create_run_dir


ArtifactKind = Literal["file", "image", "log", "directory", "unknown"]
DashboardMode = Literal["planning_only", "contract_only", "scaffold_only"]
WorkflowStageType = Literal["planning", "approval", "contract", "scaffold", "code", "integration", "qa", "fix"]
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
    "CODEX_CHILD_WINDOWS_SANDBOX",
}


class WorkflowStage(BaseModel):
    id: str
    type: WorkflowStageType
    agents: list[str] = Field(default_factory=list)
    after: list[str] = Field(default_factory=list)
    parallel: bool = False

    @field_validator("id")
    @classmethod
    def _strip_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("stage id is required")
        return stripped

    @field_validator("agents", "after")
    @classmethod
    def _strip_values(cls, values: list[str]) -> list[str]:
        return [item.strip() for item in values if item and item.strip()]


class WorkflowGraph(BaseModel):
    mode: str = "manual"
    stages: list[WorkflowStage] = Field(default_factory=list)

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, value: str) -> str:
        mode = value.strip().lower()
        if mode != "manual":
            raise ValueError("workflow_graph.mode must be manual")
        return mode

    @model_validator(mode="after")
    def _validate_graph(self) -> "WorkflowGraph":
        _validate_workflow_graph(self)
        return self


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
    agent_configs: list["AgentProviderConfig"] = Field(default_factory=list)
    workflow_graph: WorkflowGraph | None = None

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

    @model_validator(mode="after")
    def _validate_workflow_graph_mode(self) -> "RunCreateRequest":
        if self.workflow_graph is not None and self.routing_mode != "manual":
            raise ValueError("workflow_graph is only supported when routing_mode is manual")
        return self


class AgentProviderConfig(BaseModel):
    agent_id: str
    provider: str = "codex"
    account: str | None = None
    codex_home: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    enabled: bool = True

    @field_validator("agent_id")
    @classmethod
    def _strip_agent_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("agent_id is required")
        return stripped

    @field_validator("provider")
    @classmethod
    def _normalize_provider(cls, value: str) -> str:
        provider = value.strip().lower()
        if provider not in {"codex", "local", "manual"}:
            raise ValueError(f"unsupported provider for execution: {value}")
        return provider

    @field_validator("reasoning_effort")
    @classmethod
    def _validate_agent_reasoning(cls, value: str | None) -> str | None:
        if value in {None, ""}:
            return None
        if value not in REASONING_EFFORTS:
            allowed = ", ".join(REASONING_EFFORTS)
            raise ValueError(f"reasoning_effort must be one of: {allowed}")
        return value


class LocalAppSettings(BaseModel):
    default_provider: str = "codex"
    default_account: str | None = None
    default_codex_home: str | None = None
    default_model: str | None = None
    default_reasoning_effort: str | None = None
    agent_configs: list[AgentProviderConfig] = Field(default_factory=list)


class AgentPromptOverride(BaseModel):
    agent_id: str
    preset: str | None = None
    skill_markdown: str = ""
    system_prompt: str = ""

    @field_validator("agent_id")
    @classmethod
    def _strip_agent_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("agent_id is required")
        return stripped


class AgentPromptConfig(BaseModel):
    agent_id: str
    display_name: str
    role: str
    preset: str | None = None
    default_skill_markdown: str = ""
    skill_markdown: str = ""
    default_system_prompt: str = ""
    system_prompt: str = ""
    effective_prompt_preview: str = ""
    saved: bool = False


class PromptPresetInfo(BaseModel):
    id: str
    label: str
    description: str
    skill_markdown: str
    system_prompt: str = ""


class PromptCatalog(BaseModel):
    presets: list[PromptPresetInfo]


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
    type: ArtifactKind
    size_bytes: int | None = None
    modified_at: str | None = None
    updated_at: str | None = None
    media_type: str | None = None
    source: str = "discovered"
    exists: bool = True
    stage: str | None = None
    role: str | None = None


class ArtifactContent(BaseModel):
    path: str
    name: str
    kind: ArtifactKind
    media_type: str | None
    size_bytes: int
    encoding: str
    content: str
    truncated: bool = False


class ActiveStepInfo(BaseModel):
    run_id: str
    status: str
    stage: str | None = None
    agent_id: str | None = None
    pid: int | None = None
    started_at: str | None = None
    interruptible: bool = False
    active: bool = False
    label: str = "idle"
    updated_at: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class LogFileInfo(BaseModel):
    path: str
    name: str
    size_bytes: int
    modified_at: str
    updated_at: str
    stage: str | None = None
    agent_id: str | None = None
    stream: str | None = None


class LogTail(BaseModel):
    path: str
    name: str
    size_bytes: int
    modified_at: str
    updated_at: str
    line_count: int
    encoding: str = "utf-8"
    content: str
    truncated: bool = False


class ConfigSnapshot(BaseModel):
    routing_modes: tuple[str, ...]
    dashboard_modes: tuple[str, ...]
    reasoning_efforts: tuple[str, ...]
    reference_profiles: dict[str, str]
    defaults: dict[str, Any]
    providers: list[dict[str, Any]]


class ProviderCliStatus(BaseModel):
    provider: str
    installed: bool
    executable: str | None = None
    version: str | None = None
    logged_in: bool | None = None
    account: str | None = None
    plan: str | None = None
    status: str = "unknown"
    detail: str = ""


class ProviderReasoningLevel(BaseModel):
    effort: str
    description: str = ""


class ProviderModelInfo(BaseModel):
    id: str
    display_name: str
    description: str = ""
    default_reasoning_level: str | None = None
    supported_reasoning_levels: list[ProviderReasoningLevel] = Field(default_factory=list)
    visibility: str | None = None
    supported_in_api: bool | None = None


class ProviderModelCatalog(BaseModel):
    provider: str
    ok: bool
    source: str
    models: list[ProviderModelInfo] = Field(default_factory=list)
    error: str = ""


class UsageLimitInfo(BaseModel):
    name: str
    available: bool = False
    used_percent: int | None = None
    remaining_percent: int | None = None
    reset_at: str | None = None
    reset_at_epoch: int | None = None
    window_duration_mins: int | None = None
    raw: str = ""


class RuntimeUsageSnapshot(BaseModel):
    provider: str
    source: str
    ok: bool
    limits: list[UsageLimitInfo] = Field(default_factory=list)
    message: str = ""


class RuntimeHealthSnapshot(BaseModel):
    status: str
    codex: ProviderCliStatus
    claude: ProviderCliStatus
    discord_token_configured: bool
    executable_qa_enabled: bool
    codex_child_windows_sandbox: str | None = None


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


class SettingsService:
    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.settings_path = self.project_root / "local_app_settings.json"

    def get_settings(self) -> LocalAppSettings:
        if not self.settings_path.exists():
            return LocalAppSettings()
        try:
            payload = _read_json(self.settings_path)
        except (OSError, json.JSONDecodeError):
            return LocalAppSettings()
        if not isinstance(payload, dict):
            return LocalAppSettings()
        return LocalAppSettings(**payload)

    def save_settings(self, settings: LocalAppSettings) -> LocalAppSettings:
        self.settings_path.write_text(_json_text(settings.model_dump()), encoding="utf-8")
        return self.get_settings()


PROMPT_PRESETS: dict[str, PromptPresetInfo] = {
    "default_qa": PromptPresetInfo(
        id="default_qa",
        label="Default QA",
        description="Functional QA against acceptance criteria, runtime evidence, screenshots, and mechanical QA.",
        system_prompt="You are an evidence-based QA reviewer. Decide only from the provided contract, reports, files, and screenshots.",
        skill_markdown=(
            "Review whether the generated app satisfies the approved request and acceptance criteria.\n"
            "- Treat mechanical QA FAIL as blocking.\n"
            "- Treat mechanical QA SKIP as a risk that needs explicit mention.\n"
            "- Use screenshots to identify blank pages, broken layout, missing primary UI, or obvious visual regressions.\n"
            "- Do not invent requirements outside the approved plan.\n"
            "- Return QA_STATUS: PASS only when the available evidence supports the result."
        ),
    ),
    "ethics_bias_qa": PromptPresetInfo(
        id="ethics_bias_qa",
        label="Ethics & Bias QA",
        description="Adds bias, discrimination, privacy, and harmful-output review criteria.",
        system_prompt="You are an ethics-aware QA reviewer. Apply functional QA plus bias, fairness, privacy, and harm checks.",
        skill_markdown=(
            "Apply the default QA checks, then review AI ethics risks.\n"
            "- Flag content or UI flows that could reinforce discrimination by race, gender, age, disability, nationality, religion, or socioeconomic status.\n"
            "- Flag stereotyping, exclusionary defaults, unsafe demographic inference, or unsupported sensitive-attribute collection.\n"
            "- Flag privacy risks such as unnecessary personal data collection, insecure storage hints, or unclear consent.\n"
            "- If an ethics risk is material, return QA_STATUS: FAIL and recommend a planning or implementation fix.\n"
            "- Distinguish concrete evidence from speculative risk."
        ),
    ),
    "accessibility_qa": PromptPresetInfo(
        id="accessibility_qa",
        label="Accessibility QA",
        description="Adds visual accessibility, keyboard, contrast, labeling, and layout review criteria.",
        system_prompt="You are an accessibility-focused QA reviewer. Apply functional QA plus WCAG-oriented usability checks.",
        skill_markdown=(
            "Apply the default QA checks, then review accessibility risks.\n"
            "- Check screenshots and reports for unreadable text, low contrast, tiny controls, clipped text, or overlapping content.\n"
            "- Treat missing keyboard support as a risk for interactive apps when evidence is absent.\n"
            "- Flag unlabeled controls, icon-only actions without clear labels, or forms without clear input purpose when visible.\n"
            "- Return QA_STATUS: FAIL for severe accessibility blockers; otherwise PASS with risks."
        ),
    ),
    "strict_safety_qa": PromptPresetInfo(
        id="strict_safety_qa",
        label="Strict Safety QA",
        description="Conservative review mode for demos that should fail on unresolved safety, privacy, or execution uncertainty.",
        system_prompt="You are a strict safety QA reviewer. Prefer FAIL when important evidence is missing or safety risk is unresolved.",
        skill_markdown=(
            "Apply a conservative review policy.\n"
            "- Return QA_STATUS: FAIL when mechanical QA is FAIL, when browser execution is skipped for a browser app, or when screenshots are missing for a visual app.\n"
            "- Return FAIL for any unresolved privacy, data safety, bias, or harmful-content risk that could affect users.\n"
            "- Require concrete evidence for PASS.\n"
            "- Keep findings actionable and tied to the report, screenshots, files, or approved requirements."
        ),
    ),
}


class PromptService:
    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.prompts_path = self.project_root / "local_prompt_overrides.json"

    def catalog(self) -> PromptCatalog:
        return PromptCatalog(presets=list(PROMPT_PRESETS.values()))

    def get_prompt(self, agent_id: str) -> AgentPromptConfig:
        return self._prompt_config(agent_id)

    def save_prompt(self, payload: AgentPromptOverride) -> AgentPromptConfig:
        data = self._read_overrides()
        override = payload.model_dump()
        data[payload.agent_id] = override
        self.prompts_path.write_text(_json_text({"overrides": data}), encoding="utf-8")
        return self.get_prompt(payload.agent_id)

    def reset_prompt(self, agent_id: str) -> AgentPromptConfig:
        data = self._read_overrides()
        data.pop(agent_id, None)
        self.prompts_path.write_text(_json_text({"overrides": data}), encoding="utf-8")
        return self.get_prompt(agent_id)

    def effective_prompt_overrides(self, agent_ids: list[str] | None = None) -> dict[str, dict[str, str]]:
        ids = agent_ids or self._default_agent_ids()
        result: dict[str, dict[str, str]] = {}
        for agent_id in ids:
            config = self._prompt_config(agent_id)
            if config.skill_markdown.strip() or config.system_prompt.strip():
                result[agent_id] = {
                    "preset": config.preset or "",
                    "skill_markdown": config.skill_markdown,
                    "system_prompt": config.system_prompt,
                }
        return result

    def record_run_snapshots(self, store: StateStore, agent_ids: list[str]) -> dict[str, dict[str, str]]:
        snapshots: dict[str, dict[str, str]] = {}
        prompt_overrides = self.effective_prompt_overrides(agent_ids)
        for agent_id in agent_ids:
            config = self._prompt_config(agent_id)
            if not (config.skill_markdown.strip() or config.system_prompt.strip()):
                continue
            skill_path = store.write_artifact(
                f"prompts/{agent_id}_skill.md",
                config.skill_markdown,
                artifact_name=f"{agent_id}_skill_prompt",
            )
            system_path = store.write_artifact(
                f"prompts/{agent_id}_system.md",
                config.system_prompt,
                artifact_name=f"{agent_id}_system_prompt",
            )
            effective_path = store.write_artifact(
                f"prompts/{agent_id}_effective_preview.md",
                config.effective_prompt_preview,
                artifact_name=f"{agent_id}_effective_prompt",
            )
            snapshots[agent_id] = {
                "preset": config.preset or "",
                "skill": store.to_relative(skill_path),
                "system": store.to_relative(system_path),
                "effective_preview": store.to_relative(effective_path),
            }
        settings_path = store.write_artifact(
            "prompts/prompt_settings.json",
            _json_text(prompt_overrides),
            artifact_name="prompt_settings",
        )
        state = store.load()
        state["prompt_snapshots"] = snapshots
        store.save(state)
        store.append_event(
            "prompt_snapshots_saved",
            "system",
            "Agent prompt snapshots saved",
            {"path": store.to_relative(settings_path), "agents": list(snapshots)},
        )
        return snapshots

    def _prompt_config(self, agent_id: str) -> AgentPromptConfig:
        agent_id = agent_id.strip()
        role = _prompt_role(agent_id)
        preset_id = "default_qa" if role == "qa_agent" else None
        default_skill = _default_skill_markdown(self.project_root, role)
        default_system = _default_system_prompt(role)
        if role == "qa_agent":
            preset = PROMPT_PRESETS[preset_id or "default_qa"]
            default_skill = preset.skill_markdown
            default_system = preset.system_prompt
        override = self._read_overrides().get(agent_id, {})
        if isinstance(override, dict):
            chosen_preset = str(override.get("preset") or preset_id or "")
            if chosen_preset in PROMPT_PRESETS and not override.get("skill_markdown"):
                default_skill = PROMPT_PRESETS[chosen_preset].skill_markdown
                default_system = PROMPT_PRESETS[chosen_preset].system_prompt
            skill = str(override.get("skill_markdown") if override.get("skill_markdown") is not None else default_skill)
            system = str(override.get("system_prompt") if override.get("system_prompt") is not None else default_system)
            preset_id = chosen_preset or preset_id
            saved = bool(override)
        else:
            skill = default_skill
            system = default_system
            saved = False
        preview = _effective_prompt_preview(system, skill)
        return AgentPromptConfig(
            agent_id=agent_id,
            display_name=_actor_label(agent_id),
            role=role,
            preset=preset_id,
            default_skill_markdown=default_skill,
            skill_markdown=skill,
            default_system_prompt=default_system,
            system_prompt=system,
            effective_prompt_preview=preview,
            saved=saved,
        )

    def _read_overrides(self) -> dict[str, dict[str, object]]:
        if not self.prompts_path.exists():
            return {}
        try:
            payload = _read_json(self.prompts_path)
        except (OSError, json.JSONDecodeError):
            return {}
        overrides = payload.get("overrides") if isinstance(payload, dict) else None
        return {key: value for key, value in overrides.items() if isinstance(key, str) and isinstance(value, dict)} if isinstance(overrides, dict) else {}

    def _default_agent_ids(self) -> list[str]:
        return ["planner_a", "planner_b", "planner_c", "code_1", "code_2", "integrator", "qa_1", "qa_2"]


class ProviderService:
    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        load_local_app_env(self.project_root)

    def list_providers(self) -> list[ProviderCliStatus]:
        return [self.get_codex_status(), self.get_claude_status()]

    def get_codex_status(self) -> ProviderCliStatus:
        executable = _find_cli("codex")
        if not executable:
            return ProviderCliStatus(
                provider="codex",
                installed=False,
                status="missing",
                detail="Codex CLI was not found on PATH.",
            )
        version = _run_cli_text(executable, ["--version"], timeout=10)
        login = _run_cli_text(executable, ["login", "status"], timeout=15)
        login_text = f"{login.stdout}\n{login.stderr}"
        logged_in = login.returncode == 0 and "logged in" in login_text.lower()
        return ProviderCliStatus(
            provider="codex",
            installed=True,
            executable=executable,
            version=_first_line(version.stdout) if version.returncode == 0 else None,
            logged_in=logged_in,
            status="ready" if logged_in else "login_required",
            detail=_first_line(login_text),
        )

    def get_claude_status(self) -> ProviderCliStatus:
        executable = _find_cli("claude")
        if not executable:
            return ProviderCliStatus(
                provider="claude",
                installed=False,
                status="missing",
                detail="Claude Code CLI was not found on PATH.",
            )
        version = _run_cli_text(executable, ["--version"], timeout=10)
        return ProviderCliStatus(
            provider="claude",
            installed=True,
            executable=executable,
            version=_first_line(version.stdout) if version.returncode == 0 else None,
            logged_in=None,
            status="detected",
            detail=_first_line(version.stdout or version.stderr),
        )

    def get_codex_models(self, *, bundled: bool = False) -> ProviderModelCatalog:
        executable = _find_cli("codex")
        if not executable:
            return ProviderModelCatalog(provider="codex", ok=False, source="missing", error="Codex CLI was not found.")
        args = ["debug", "models"]
        if bundled:
            args.append("--bundled")
        result = _run_cli_text(executable, args, timeout=30)
        source = "codex debug models --bundled" if bundled else "codex debug models"
        if result.returncode != 0:
            if not bundled:
                fallback = self.get_codex_models(bundled=True)
                if fallback.ok:
                    return fallback
            return ProviderModelCatalog(
                provider="codex",
                ok=False,
                source=source,
                error=_compact_text(result.stderr or result.stdout or "Codex model catalog command failed.", max_chars=1000),
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return ProviderModelCatalog(provider="codex", ok=False, source=source, error=f"Invalid model catalog JSON: {exc}")
        return ProviderModelCatalog(
            provider="codex",
            ok=True,
            source=source,
            models=_parse_codex_models(payload),
        )

    def get_runtime_usage(self) -> RuntimeUsageSnapshot:
        executable = _find_cli("codex")
        if not executable:
            return RuntimeUsageSnapshot(
                provider="codex",
                source="codex app-server account/rateLimits/read",
                ok=False,
                limits=[UsageLimitInfo(name="5h limit"), UsageLimitInfo(name="weekly limit")],
                message="Codex CLI was not found on PATH.",
            )
        try:
            payload = _codex_app_server_request(
                executable,
                "account/rateLimits/read",
                cwd=self.project_root,
                timeout=25,
            )
        except RuntimeError as exc:
            return RuntimeUsageSnapshot(
                provider="codex",
                source="codex app-server account/rateLimits/read",
                ok=False,
                limits=[UsageLimitInfo(name="5h limit"), UsageLimitInfo(name="weekly limit")],
                message=str(exc),
            )
        rate_limits = payload.get("rateLimits")
        if not isinstance(rate_limits, dict):
            return RuntimeUsageSnapshot(
                provider="codex",
                source="codex app-server account/rateLimits/read",
                ok=False,
                limits=[UsageLimitInfo(name="5h limit"), UsageLimitInfo(name="weekly limit")],
                message="Codex app-server returned no rateLimits payload.",
            )
        return RuntimeUsageSnapshot(
            provider="codex",
            source="codex app-server account/rateLimits/read",
            ok=True,
            limits=[
                _usage_limit_from_window("5h limit", rate_limits.get("primary")),
                _usage_limit_from_window("weekly limit", rate_limits.get("secondary")),
            ],
            message=_codex_usage_message(rate_limits),
        )

    def get_runtime_health(self) -> RuntimeHealthSnapshot:
        codex = self.get_codex_status()
        claude = self.get_claude_status()
        status = "ready" if codex.installed and codex.logged_in else "setup_required"
        return RuntimeHealthSnapshot(
            status=status,
            codex=codex,
            claude=claude,
            discord_token_configured=bool(os.environ.get("DISCORD_BOT_TOKEN", "").strip()),
            executable_qa_enabled=_env_bool("EXECUTABLE_QA_ENABLED", default=True),
            codex_child_windows_sandbox=_optional_str(os.environ.get("CODEX_CHILD_WINDOWS_SANDBOX")),
        )


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
        prompt_service = PromptService(self.project_root)
        config = self._local_config_from_request(request, prompt_service=prompt_service)
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
        if request.workflow_graph is not None:
            self._record_workflow_graph(store, request.workflow_graph)
        prompt_service.record_run_snapshots(store, _run_prompt_agent_ids(route, request.workflow_graph))
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
        _require_status(store, run_id, {"awaiting_qa_approval"}, "waiting for QA approval")
        store.add_approval(action="qa_approved", user_id=action.user_id, feedback=action.feedback)
        store.set_status("completed")
        return self.get_run(run_id)

    def request_qa_fix(self, run_id: str, action: OperatorActionRequest) -> RunDetail:
        store = StateStore(self._run_dir(run_id))
        _require_status(store, run_id, {"awaiting_qa_approval"}, "waiting for QA review")
        store.add_approval(action="qa_fix_requested", user_id=action.user_id, feedback=action.feedback)
        store.append_transcript("Local QA Fix Feedback", action.feedback or "(no feedback)")
        store.set_status("qa_fix_requested")
        return self.get_run(run_id)

    def _local_config_from_request(self, request: RunCreateRequest, *, prompt_service: PromptService | None = None) -> LocalRunConfig:
        defaults = LocalRunConfig.from_env()
        code_count = request.code_agent_count if request.code_agent_count is not None else defaults.code_agent_count
        qa_count = request.qa_agent_count if request.qa_agent_count is not None else defaults.qa_agent_count
        agent_ids = (
            _workflow_graph_prompt_agent_ids(request.workflow_graph)
            if request.workflow_graph is not None
            else _request_prompt_agent_ids(
                planner_count=request.planner_count if request.planner_count is not None else defaults.planner_count,
                code_agent_count=code_count,
                qa_agent_count=qa_count,
            )
        )
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
            agent_configs=_agent_config_map(request.agent_configs or []),
            prompt_overrides=(prompt_service or PromptService(self.project_root)).effective_prompt_overrides(agent_ids),
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

    def _record_workflow_graph(self, store: StateStore, graph: WorkflowGraph) -> None:
        payload = graph.model_dump()
        workflow = {
            "mode": "manual",
            "resolved_mode": "manual",
            "graph": payload,
            "stages": payload["stages"],
        }
        store.set_workflow(workflow)
        graph_path = store.write_artifact("workflow_graph.json", _json_text(payload), artifact_name="workflow_graph")
        store.append_event(
            "workflow_graph_saved",
            "system",
            "Manual workflow graph saved",
            {"path": store.to_relative(graph_path), **workflow},
        )

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
            "agent_configs": config.agent_configs,
            "prompt_overrides": config.prompt_overrides,
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
            events.append(self._timeline_event(run_dir, run_id, index, raw))
        return events

    def _timeline_event(self, run_dir: Path, run_id: str, index: int, raw: dict[str, Any]) -> TimelineEvent:
        event_type = str(raw.get("type") or "event")
        actor = str(raw.get("actor") or "system")
        message = str(raw.get("message") or event_type)
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        artifacts = _event_artifacts(data)
        details = _event_details(data)
        summary = _event_artifact_preview(run_dir, event_type, data) or _event_summary(event_type, data)
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
            summary=summary,
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
        kind = "directory" if path.is_dir() else _artifact_kind(path)
        updated_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds")
        rel_path = path.relative_to(run_dir).as_posix()
        return ArtifactInfo(
            path=rel_path,
            name=path.name,
            kind=kind,
            type=kind,
            size_bytes=None if path.is_dir() else stat.st_size,
            modified_at=updated_at,
            updated_at=updated_at,
            media_type=None if path.is_dir() else mimetypes.guess_type(path.name)[0],
            source=source,
            exists=path.exists(),
            stage=_infer_artifact_stage(rel_path),
            role=_infer_artifact_role(rel_path),
        )


class ObservationService:
    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.runs_root = self.project_root / "runs"

    def get_active_step(self, run_id: str) -> ActiveStepInfo:
        run_dir = _safe_run_dir(self.runs_root, run_id)
        state = _read_json(run_dir / "state.json")
        active = state.get("active_step") if isinstance(state.get("active_step"), dict) else {}
        stage = _optional_str(active.get("stage"))
        agent_id = _optional_str(active.get("agent_id"))
        pid = active.get("pid") if isinstance(active.get("pid"), int) else None
        label_parts = [part for part in [stage, agent_id, f"pid={pid}" if pid else None] if part]
        return ActiveStepInfo(
            run_id=str(state.get("run_id") or run_id),
            status=str(state.get("status") or "unknown"),
            stage=stage,
            agent_id=agent_id,
            pid=pid,
            started_at=_optional_str(active.get("started_at")),
            interruptible=bool(active.get("interruptible")),
            active=bool(stage),
            label=", ".join(label_parts) if label_parts else "idle",
            updated_at=_optional_str(state.get("updated_at")),
            raw=active,
        )

    def list_logs(self, run_id: str) -> list[LogFileInfo]:
        run_dir = _safe_run_dir(self.runs_root, run_id)
        logs_dir = run_dir / "logs"
        if not logs_dir.exists():
            return []
        logs = [self._log_info(run_dir, path) for path in logs_dir.rglob("*") if path.is_file()]
        logs.sort(key=lambda item: (item.modified_at, item.path), reverse=True)
        return logs

    def read_log_tail(self, run_id: str, relative_path: str, *, lines: int = 200, max_bytes: int = 262_144) -> LogTail:
        run_dir = _safe_run_dir(self.runs_root, run_id)
        path = _safe_log_path(run_dir, relative_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Log not found: {relative_path}")
        stat = path.stat()
        truncated_by_size = stat.st_size > max_bytes
        with path.open("rb") as file:
            if truncated_by_size:
                file.seek(-max_bytes, os.SEEK_END)
            data = file.read(max_bytes)
        text = data.decode("utf-8", errors="replace")
        split = text.splitlines()
        if lines < 1:
            lines = 1
        selected = split[-lines:]
        truncated_by_lines = len(split) > len(selected)
        if truncated_by_size and selected:
            selected[0] = selected[0].lstrip("\ufeff")
        content = "\n".join(selected)
        updated_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds")
        return LogTail(
            path=path.relative_to(run_dir).as_posix(),
            name=path.name,
            size_bytes=stat.st_size,
            modified_at=updated_at,
            updated_at=updated_at,
            line_count=len(selected),
            content=content,
            truncated=truncated_by_size or truncated_by_lines,
        )

    def _log_info(self, run_dir: Path, path: Path) -> LogFileInfo:
        stat = path.stat()
        updated_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds")
        stage, agent_id, stream = _infer_log_parts(path)
        return LogFileInfo(
            path=path.relative_to(run_dir).as_posix(),
            name=path.name,
            size_bytes=stat.st_size,
            modified_at=updated_at,
            updated_at=updated_at,
            stage=stage,
            agent_id=agent_id,
            stream=stream,
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


def _require_status(store: StateStore, run_id: str, allowed: set[str], description: str) -> None:
    status = str(store.load().get("status") or "")
    if status not in allowed:
        expected = ", ".join(sorted(allowed))
        raise ValueError(f"Run {run_id} is not {description}. Current status: {status or 'unknown'}; expected: {expected}.")


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


def _safe_log_path(run_dir: Path, relative_path: str) -> Path:
    rel = Path(relative_path)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise FileNotFoundError(f"Invalid log path: {relative_path}")
    logs_root = (run_dir / "logs").resolve()
    path = (run_dir / rel).resolve()
    try:
        path.relative_to(logs_root)
    except ValueError as exc:
        raise FileNotFoundError(f"Invalid log path: {relative_path}") from exc
    return path


def _expand_list(values: list[str | None] | None, defaults: list[str | None], count: int) -> list[str | None]:
    source = values if values is not None else defaults
    if count <= 0:
        return []
    if not source:
        return [None for _ in range(count)]
    return [source[index % len(source)] for index in range(count)]


def _agent_config_map(configs: list[AgentProviderConfig]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for config in configs:
        result[config.agent_id] = config.model_dump()
    return result


def _validate_workflow_graph(graph: WorkflowGraph) -> None:
    if not graph.stages:
        raise ValueError("workflow_graph.stages must contain at least one stage")
    stage_ids = [stage.id for stage in graph.stages]
    duplicates = sorted({stage_id for stage_id in stage_ids if stage_ids.count(stage_id) > 1})
    if duplicates:
        raise ValueError(f"workflow_graph has duplicate stage ids: {', '.join(duplicates)}")

    known_ids = set(stage_ids)
    stage_types = {stage.type for stage in graph.stages}
    if "planning" not in stage_types:
        raise ValueError("workflow_graph requires a planning stage")
    if "code" not in stage_types:
        raise ValueError("workflow_graph requires a code stage")
    for stage in graph.stages:
        missing = [dependency for dependency in stage.after if dependency not in known_ids]
        if missing:
            raise ValueError(f"stage {stage.id} references missing dependencies: {', '.join(missing)}")
        if stage.type == "approval" and stage.parallel:
            raise ValueError(f"approval stage {stage.id} cannot be parallel")
        if stage.type != "approval" and not stage.agents:
            raise ValueError(f"stage {stage.id} requires at least one agent")

    _ensure_graph_has_no_cycles(graph.stages)
    _validate_integration_rules(graph.stages)


def _ensure_graph_has_no_cycles(stages: list[WorkflowStage]) -> None:
    by_id = {stage.id: stage for stage in stages}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(stage_id: str) -> None:
        if stage_id in visited:
            return
        if stage_id in visiting:
            raise ValueError(f"workflow_graph contains a cycle at stage {stage_id}")
        visiting.add(stage_id)
        for dependency in by_id[stage_id].after:
            visit(dependency)
        visiting.remove(stage_id)
        visited.add(stage_id)

    for stage in stages:
        visit(stage.id)


def _validate_integration_rules(stages: list[WorkflowStage]) -> None:
    code_stages = [stage for stage in stages if stage.type == "code"]
    integration_stages = [stage for stage in stages if stage.type == "integration"]
    code_ids = {stage.id for stage in code_stages}
    for stage in integration_stages:
        if not code_ids:
            raise ValueError(f"integration stage {stage.id} requires a code stage")
        if stage.after and not any(dependency in code_ids for dependency in stage.after):
            raise ValueError(f"integration stage {stage.id} must depend on a code stage")

    for stage in code_stages:
        if stage.parallel and len(stage.agents) > 1:
            has_integration = any(stage.id in integration.after for integration in integration_stages)
            if not has_integration:
                raise ValueError(f"parallel code stage {stage.id} requires an integration stage")


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


def _find_cli(name: str) -> str | None:
    return shutil.which(name)


def _run_cli_text(executable: str, args: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    command = _cli_command(executable, args)
    try:
        return subprocess.run(
            command,
            cwd=None,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(command, 1, "", str(exc))


def _cli_command(executable: str, args: list[str]) -> list[str]:
    path = Path(executable)
    if os.name == "nt" and path.suffix.lower() == ".ps1":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", executable, *args]
    return [executable, *args]


def _codex_app_server_request(executable: str, method: str, *, cwd: Path, timeout: int) -> dict[str, Any]:
    command = _cli_command(executable, ["app-server", "--listen", "stdio://"])
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        raise RuntimeError(f"Failed to start Codex app-server: {exc}") from exc

    stdout_queue: queue.Queue[str] = queue.Queue()
    stderr_lines: list[str] = []

    def read_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            stdout_queue.put(line)

    def read_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            if len(stderr_lines) < 20:
                stderr_lines.append(line.strip())

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    try:
        _write_app_server_message(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "orchestra-local-api", "version": "0.0.0"},
                    "capabilities": None,
                },
            },
        )
        _wait_app_server_response(stdout_queue, request_id=1, timeout=timeout)
        _write_app_server_message(process, {"jsonrpc": "2.0", "id": 2, "method": method})
        return _wait_app_server_response(stdout_queue, request_id=2, timeout=timeout)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()


def _write_app_server_message(process: subprocess.Popen[str], message: dict[str, Any]) -> None:
    if process.stdin is None:
        raise RuntimeError("Codex app-server stdin is not available.")
    try:
        process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        process.stdin.flush()
    except OSError as exc:
        raise RuntimeError(f"Failed to write Codex app-server request: {exc}") from exc


def _wait_app_server_response(stdout_queue: queue.Queue[str], *, request_id: int, timeout: int) -> dict[str, Any]:
    deadline = datetime.now(timezone.utc).timestamp() + timeout
    while True:
        remaining = deadline - datetime.now(timezone.utc).timestamp()
        if remaining <= 0:
            raise RuntimeError(f"Timed out waiting for Codex app-server response id {request_id}.")
        try:
            line = stdout_queue.get(timeout=remaining)
        except queue.Empty as exc:
            raise RuntimeError(f"Timed out waiting for Codex app-server response id {request_id}.") from exc
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("id") != request_id:
            continue
        if "error" in payload:
            raise RuntimeError(f"Codex app-server request failed: {payload['error']}")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"Codex app-server returned an invalid response for id {request_id}.")
        return result


def _usage_limit_from_window(name: str, value: Any) -> UsageLimitInfo:
    if not isinstance(value, dict):
        return UsageLimitInfo(name=name)
    used = value.get("usedPercent")
    used_percent = int(used) if isinstance(used, int | float) else None
    remaining_percent = max(0, min(100, 100 - used_percent)) if used_percent is not None else None
    reset_epoch = value.get("resetsAt")
    reset_at_epoch = int(reset_epoch) if isinstance(reset_epoch, int | float) else None
    reset_at = _local_iso_from_epoch(reset_at_epoch) if reset_at_epoch is not None else None
    duration = value.get("windowDurationMins")
    return UsageLimitInfo(
        name=name,
        available=True,
        used_percent=used_percent,
        remaining_percent=remaining_percent,
        reset_at=reset_at,
        reset_at_epoch=reset_at_epoch,
        window_duration_mins=int(duration) if isinstance(duration, int | float) else None,
        raw=json.dumps(value, ensure_ascii=False, separators=(",", ":")),
    )


def _local_iso_from_epoch(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


def _codex_usage_message(rate_limits: dict[str, Any]) -> str:
    plan = _optional_str(rate_limits.get("planType"))
    reached = _optional_str(rate_limits.get("rateLimitReachedType"))
    parts = []
    if plan:
        parts.append(f"plan: {plan}")
    if reached:
        parts.append(f"rate limit reached: {reached}")
    return ", ".join(parts)


def _first_line(value: str) -> str:
    for line in value.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _parse_codex_models(payload: dict[str, Any]) -> list[ProviderModelInfo]:
    raw_models = payload.get("models")
    if not isinstance(raw_models, list):
        return []
    models: list[ProviderModelInfo] = []
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        model_id = _first_str(item.get("slug"), item.get("id"), item.get("model"))
        if not model_id:
            continue
        reasoning_levels: list[ProviderReasoningLevel] = []
        raw_reasoning = item.get("supported_reasoning_levels")
        if isinstance(raw_reasoning, list):
            for raw_level in raw_reasoning:
                if not isinstance(raw_level, dict):
                    continue
                effort = _first_str(raw_level.get("effort"), raw_level.get("id"), raw_level.get("name"))
                if not effort:
                    continue
                reasoning_levels.append(
                    ProviderReasoningLevel(
                        effort=effort,
                        description=_first_str(raw_level.get("description")),
                    )
                )
        models.append(
            ProviderModelInfo(
                id=model_id,
                display_name=_first_str(item.get("display_name"), item.get("name"), model_id),
                description=_first_str(item.get("description")),
                default_reasoning_level=_optional_str(item.get("default_reasoning_level")),
                supported_reasoning_levels=reasoning_levels,
                visibility=_optional_str(item.get("visibility")),
                supported_in_api=item.get("supported_in_api") if isinstance(item.get("supported_in_api"), bool) else None,
            )
        )
    return models


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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


def _prompt_role(agent_id: str) -> str:
    if agent_id.startswith("code_"):
        return "code_agent"
    if agent_id.startswith("qa_"):
        return "qa_agent"
    return agent_id


def _default_system_prompt(role: str) -> str:
    if role == "planner_a":
        return "You are a planning agent. Produce a concrete, small, testable implementation plan from the user request."
    if role == "planner_b":
        return "You are a planning reviewer. Find missing requirements, risks, and unclear acceptance criteria."
    if role == "code_agent":
        return "You are a code implementation agent. Modify only the assigned workspace and keep the app runnable."
    if role == "integrator":
        return "You are an integration agent. Merge completed work into a coherent generated app without unrelated changes."
    return ""


def _default_skill_markdown(project_root: Path, role: str) -> str:
    profile = DEFAULT_REFERENCE_PROFILES.get(role, "")
    if not profile:
        return ""
    try:
        normalized = normalize_reference_profile(profile)
    except ValueError:
        return ""
    if not normalized:
        return ""
    pack_id, profile_role = normalized.split("/", 1)
    manifest_path = project_root / "reference_packs" / pack_id / "reference_pack_manifest.json"
    if not manifest_path.exists():
        return ""
    try:
        manifest = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError):
        return ""
    role_map = manifest.get("default_role_files")
    if not isinstance(role_map, dict):
        return ""
    raw_path = role_map.get(profile_role)
    if not isinstance(raw_path, str):
        return ""
    source_path = project_root / raw_path
    source_root = project_root / "reference_packs" / pack_id
    try:
        source_path.resolve().relative_to(source_root.resolve())
    except ValueError:
        return ""
    if not source_path.exists() or not source_path.is_file():
        return ""
    try:
        text = source_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    return text[:12000].rstrip()


def _effective_prompt_preview(system_prompt: str, skill_markdown: str) -> str:
    parts = []
    if system_prompt.strip():
        parts.append(f"System prompt override:\n{system_prompt.strip()}")
    if skill_markdown.strip():
        parts.append(f"Skill / guideline:\n{skill_markdown.strip()}")
    return "\n\n".join(parts)


def _request_prompt_agent_ids(*, planner_count: int, code_agent_count: int, qa_agent_count: int) -> list[str]:
    ids = ["planner_a"]
    if planner_count >= 2:
        ids.append("planner_b")
    if planner_count >= 3:
        ids.append("planner_c")
    ids.extend(f"code_{index}" for index in range(1, max(1, code_agent_count) + 1))
    ids.append("integrator")
    ids.extend(f"qa_{index}" for index in range(1, max(0, qa_agent_count) + 1))
    return ids


def _run_prompt_agent_ids(route: RoutingDecision, graph: WorkflowGraph | None) -> list[str]:
    if graph is not None:
        return _workflow_graph_prompt_agent_ids(graph)
    return _request_prompt_agent_ids(
        planner_count=route.planner_count,
        code_agent_count=route.code_agent_count,
        qa_agent_count=route.qa_agent_count,
    )


def _workflow_graph_prompt_agent_ids(graph: WorkflowGraph) -> list[str]:
    ids: list[str] = []
    for stage in graph.stages:
        ids.extend(agent_id for agent_id in stage.agents if agent_id != "mechanical_qa")
    return _merge_text_values(ids)


def _merge_text_values(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


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


def _event_artifact_preview(run_dir: Path, event_type: str, data: dict[str, Any], *, max_chars: int = 1200) -> str:
    if event_type != "agent_output":
        return ""
    path_value = data.get("path")
    if not isinstance(path_value, str) or not path_value:
        return ""
    try:
        path = _safe_artifact_path(run_dir, path_value)
    except FileNotFoundError:
        return ""
    if not path.exists() or not path.is_file() or _artifact_kind(path) not in {"file", "log"}:
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return _compact_text(text, max_chars=max_chars)


def _compact_text(text: str, *, max_chars: int) -> str:
    compacted = text.strip()
    if len(compacted) <= max_chars:
        return compacted
    return compacted[: max(0, max_chars - 16)].rstrip() + "\n... truncated"


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


def _infer_artifact_stage(path: str) -> str | None:
    first = Path(path).parts[0] if Path(path).parts else path
    mapping = {
        "planning": "planning",
        "contract": "contract",
        "scaffold_app": "scaffold",
        "agent_workspaces": "code_agents",
        "agent_outputs": "code_agents",
        "integration": "integration",
        "generated_app": "generated_app",
        "qa": "qa",
        "logs": "logs",
    }
    if path in {"plan.md"}:
        return "planning"
    if path in {"qa_report.md"}:
        return "qa"
    return mapping.get(first)


def _infer_artifact_role(path: str) -> str | None:
    parts = Path(path).parts
    joined = "_".join(parts).lower()
    for role in ["planner_a", "planner_b", "planner_c", "architect", "scaffold", "integrator"]:
        if role in joined:
            return role
    for part in parts:
        lowered = part.lower()
        if lowered.startswith("code_") or lowered.startswith("qa_"):
            return lowered
    if parts and parts[0] == "contract":
        return "architect"
    if parts and parts[0] == "scaffold_app":
        return "scaffold"
    if parts and parts[0] == "integration":
        return "integrator"
    return None


def _infer_log_parts(path: Path) -> tuple[str | None, str | None, str | None]:
    stem = path.stem
    parts = stem.split("_")
    stream = parts[-1] if parts and parts[-1] in {"prompt", "stdout", "stderr", "meta"} else None
    owner_parts = parts[:-1] if stream else parts
    owner = "_".join(owner_parts)
    agent_id = _infer_log_agent(owner)
    stage = _infer_log_stage(owner, agent_id)
    return stage, agent_id, stream


def _infer_log_agent(owner: str) -> str | None:
    known = ["planner_a", "planner_b", "planner_c", "architect", "scaffold", "developer", "integrator", "qa"]
    for agent_id in known:
        if owner == agent_id or owner.startswith(f"{agent_id}_"):
            return agent_id
    for prefix in ["code", "qa"]:
        parts = owner.split("_")
        if len(parts) >= 2 and parts[0] == prefix and parts[1].isdigit():
            return f"{parts[0]}_{parts[1]}"
    return None


def _infer_log_stage(owner: str, agent_id: str | None) -> str | None:
    if owner.startswith("planning") or (agent_id and agent_id.startswith("planner_")):
        return "planning"
    if agent_id == "architect" or owner.startswith("contract"):
        return "contract"
    if agent_id == "scaffold" or owner.startswith("scaffold"):
        return "scaffold"
    if agent_id and agent_id.startswith("code_"):
        return "code_agents"
    if agent_id == "integrator" or owner.startswith("integration"):
        return "integration"
    if agent_id and agent_id.startswith("qa"):
        return "qa"
    if owner.startswith("fix"):
        return "fix_loop"
    return None


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
