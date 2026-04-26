"""Environment-driven configuration for the Discord bot workflow."""

from __future__ import annotations

import os
from dataclasses import dataclass


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
        qa_agent_count=_positive_int_value("QA_AGENT_COUNT", 1),
        codex_model=_optional_str("CODEX_MODEL"),
        codex_reasoning_effort=_optional_reasoning_effort("CODEX_REASONING_EFFORT"),
        max_fix_iterations=_int_value("MAX_FIX_ITERATIONS", 1),
        codex_timeout_seconds=_int_value("CODEX_TIMEOUT_SECONDS", 900),
        executable_qa_enabled=_bool_value("EXECUTABLE_QA_ENABLED", True),
        executable_qa_timeout_seconds=_int_value("EXECUTABLE_QA_TIMEOUT_SECONDS", 90),
        executable_qa_allow_local_commands=_bool_value("EXECUTABLE_QA_ALLOW_LOCAL_COMMANDS", False),
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
