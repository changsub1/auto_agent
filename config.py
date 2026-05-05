"""Environment-driven configuration for the Discord bot workflow."""

from __future__ import annotations

import os
from dataclasses import dataclass

from reference_packs import DEFAULT_REFERENCE_PROFILES, normalize_reference_profile
from routing import ROUTING_MODES, normalize_routing_mode


REASONING_EFFORT_VALUES = {"minimal", "low", "medium", "high", "xhigh"}


@dataclass(frozen=True)
class DiscordBotConfig:
    token: str
    guild_id: int | None
    allowed_channel_id: int | None
    allowed_user_ids: set[int]
    planner_a_codex_home: str | None
    planner_b_codex_home: str | None
    architect_codex_home: str | None
    scaffold_codex_home: str | None
    developer_codex_home: str | None
    integrator_codex_home: str | None
    code_agent_codex_homes: list[str | None]
    code_agent_count: int
    qa_agent_codex_homes: list[str | None]
    qa_agent_count: int
    codex_model: str | None
    codex_reasoning_effort: str | None
    max_fix_iterations: int
    codex_timeout_seconds: int
    executable_qa_enabled: bool
    executable_qa_timeout_seconds: int
    executable_qa_allow_local_commands: bool
    routing_mode: str
    reference_pack_enabled: bool
    agent_reference_profiles: dict[str, str]
    local_api_base_url: str


def load_discord_bot_config() -> DiscordBotConfig:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is required.")

    return DiscordBotConfig(
        token=token,
        guild_id=_optional_int("DISCORD_GUILD_ID"),
        allowed_channel_id=_optional_int("DISCORD_ALLOWED_CHANNEL_ID"),
        allowed_user_ids=_int_set("DISCORD_ALLOWED_USER_IDS"),
        planner_a_codex_home=_optional_str("PLANNER_A_CODEX_HOME"),
        planner_b_codex_home=_optional_str("PLANNER_B_CODEX_HOME"),
        architect_codex_home=_optional_str("ARCHITECT_CODEX_HOME"),
        scaffold_codex_home=_optional_str("SCAFFOLD_CODEX_HOME"),
        developer_codex_home=_optional_str("DEVELOPER_CODEX_HOME"),
        integrator_codex_home=_optional_str("INTEGRATOR_CODEX_HOME"),
        code_agent_codex_homes=_optional_str_list("CODE_AGENT_CODEX_HOMES"),
        code_agent_count=_positive_int_value("CODE_AGENT_COUNT", 2),
        qa_agent_codex_homes=_optional_str_list("QA_AGENT_CODEX_HOMES"),
        qa_agent_count=_nonnegative_int_value("QA_AGENT_COUNT", 1),
        codex_model=_optional_str("CODEX_MODEL"),
        codex_reasoning_effort=_optional_reasoning_effort("CODEX_REASONING_EFFORT"),
        max_fix_iterations=_int_value("MAX_FIX_ITERATIONS", 1),
        codex_timeout_seconds=_int_value("CODEX_TIMEOUT_SECONDS", 900),
        executable_qa_enabled=_bool_value("EXECUTABLE_QA_ENABLED", True),
        executable_qa_timeout_seconds=_int_value("EXECUTABLE_QA_TIMEOUT_SECONDS", 90),
        executable_qa_allow_local_commands=_bool_value("EXECUTABLE_QA_ALLOW_LOCAL_COMMANDS", False),
        routing_mode=_routing_mode("ROUTING_MODE"),
        reference_pack_enabled=_bool_value("REFERENCE_PACK_ENABLED", True),
        agent_reference_profiles=_agent_reference_profiles(),
        local_api_base_url=_local_api_base_url(),
    )


def _optional_str(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _optional_int(name: str) -> int | None:
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    return int(value)


def _optional_reasoning_effort(name: str) -> str | None:
    value = _optional_str(name)
    if value is None:
        return None
    if value not in REASONING_EFFORT_VALUES:
        allowed = ", ".join(sorted(REASONING_EFFORT_VALUES))
        raise RuntimeError(f"{name} must be one of: {allowed}.")
    return value


def _optional_str_list(name: str) -> list[str | None]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return []
    return [part.strip() or None for part in raw.split(",") if part.strip()]


def _int_value(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    return int(value)


def _positive_int_value(name: str, default: int) -> int:
    parsed = _int_value(name, default)
    if parsed < 1:
        raise RuntimeError(f"{name} must be 1 or greater.")
    return parsed


def _nonnegative_int_value(name: str, default: int) -> int:
    parsed = _int_value(name, default)
    if parsed < 0:
        raise RuntimeError(f"{name} must be 0 or greater.")
    return parsed


def _int_set(name: str) -> set[int]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return set()
    return {int(part.strip()) for part in raw.split(",") if part.strip()}


def _bool_value(name: str, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean value.")


def _routing_mode(name: str) -> str:
    value = os.environ.get(name, "balanced").strip() or "balanced"
    try:
        return normalize_routing_mode(value)
    except ValueError as exc:
        allowed = ", ".join(ROUTING_MODES)
        raise RuntimeError(f"{name} must be one of: {allowed}.") from exc


def _agent_reference_profiles() -> dict[str, str]:
    env_names = {
        "planner_a": "PLANNER_A_REFERENCE",
        "planner_b": "PLANNER_B_REFERENCE",
        "code_agent": "CODE_AGENT_REFERENCE",
        "integrator": "INTEGRATOR_REFERENCE",
        "qa_agent": "QA_AGENT_REFERENCE",
    }
    if _legacy_reference_pack_requested(env_names.values()):
        pack_id = os.environ.get("REFERENCE_PACK_ID", "").strip()
        return {
            role: normalize_reference_profile(f"{pack_id}/{role}")
            for role in env_names
        }

    profiles: dict[str, str] = {}
    for role, env_name in env_names.items():
        raw = os.environ.get(env_name)
        if raw is None:
            raw = DEFAULT_REFERENCE_PROFILES.get(role, "")
        try:
            profiles[role] = normalize_reference_profile(raw)
        except ValueError as exc:
            raise RuntimeError(f"{env_name} must be empty, none, or pack/role.") from exc
    return profiles


def _local_api_base_url() -> str:
    value = os.environ.get("DISCORD_LOCAL_API_BASE_URL", "").strip()
    if not value:
        host = os.environ.get("LOCAL_API_HOST", "127.0.0.1").strip() or "127.0.0.1"
        port = os.environ.get("LOCAL_API_PORT", "8765").strip() or "8765"
        value = f"http://{host}:{port}"
    value = value.rstrip("/")
    if not (value.startswith("http://127.0.0.1:") or value.startswith("http://localhost:")):
        raise RuntimeError("DISCORD_LOCAL_API_BASE_URL must point to localhost or 127.0.0.1.")
    return value


def _legacy_reference_pack_requested(role_env_names: object) -> bool:
    legacy_pack = os.environ.get("REFERENCE_PACK_ID", "").strip()
    if not legacy_pack:
        return False
    return not any(name in os.environ for name in role_env_names)
