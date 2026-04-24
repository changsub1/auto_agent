"""Environment-driven configuration for the Discord bot workflow."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DiscordBotConfig:
    token: str
    guild_id: int | None
    allowed_channel_id: int | None
    allowed_user_ids: set[int]
    planner_a_codex_home: str | None
    planner_b_codex_home: str | None
    developer_codex_home: str | None
    max_fix_iterations: int
    codex_timeout_seconds: int


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
        developer_codex_home=_optional_str("DEVELOPER_CODEX_HOME"),
        max_fix_iterations=_int_value("MAX_FIX_ITERATIONS", 1),
        codex_timeout_seconds=_int_value("CODEX_TIMEOUT_SECONDS", 900),
    )


def _optional_str(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _optional_int(name: str) -> int | None:
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    return int(value)


def _int_value(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    return int(value)


def _int_set(name: str) -> set[int]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return set()
    return {int(part.strip()) for part in raw.split(",") if part.strip()}
