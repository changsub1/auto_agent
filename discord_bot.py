"""Discord bot entrypoint for the Codex multi-agent development workflow."""

from __future__ import annotations

from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from config import DiscordBotConfig, load_discord_bot_config
from debate_engine import DebateEngine
from discord_reporter import DiscordReporter


class CodexDevBot(commands.Bot):
    def __init__(self, config: DiscordBotConfig) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.config_data = config
        self.engine = DebateEngine(
            project_root=Path(__file__).resolve().parent,
            reporter=DiscordReporter(),
            planner_a_codex_home=config.planner_a_codex_home,
            planner_b_codex_home=config.planner_b_codex_home,
            architect_codex_home=config.architect_codex_home,
            scaffold_codex_home=config.scaffold_codex_home,
            developer_codex_home=config.developer_codex_home,
            integrator_codex_home=config.integrator_codex_home,
            code_agent_codex_homes=config.code_agent_codex_homes,
            code_agent_count=config.code_agent_count,
            qa_agent_codex_homes=config.qa_agent_codex_homes,
            qa_agent_count=config.qa_agent_count,
            codex_model=config.codex_model,
            codex_reasoning_effort=config.codex_reasoning_effort,
            max_fix_iterations=config.max_fix_iterations,
            codex_timeout_seconds=config.codex_timeout_seconds,
            executable_qa_enabled=config.executable_qa_enabled,
            executable_qa_timeout_seconds=config.executable_qa_timeout_seconds,
            executable_qa_allow_local_commands=config.executable_qa_allow_local_commands,
        )

    async def setup_hook(self) -> None:
        if self.config_data.guild_id:
            guild = discord.Object(id=self.config_data.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            return
        await self.tree.sync()


def build_bot(config: DiscordBotConfig) -> CodexDevBot:
    bot = CodexDevBot(config)

    @bot.tree.command(name="dev", description="Start a Codex multi-agent app development run.")
    @app_commands.describe(request="Describe the service or app you want the agents to build.")
    async def dev(interaction: discord.Interaction, request: str) -> None:
        if not _is_allowed(config, interaction):
            await interaction.response.send_message("You are not allowed to start runs here.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        channel = interaction.channel
        if channel is None:
            await interaction.followup.send("Cannot start because this interaction has no channel.", ephemeral=True)
            return

        run_id, run_dir = await bot.engine.start_discord_request(
            request=request,
            channel=channel,
            requester_id=interaction.user.id,
            guild_id=interaction.guild_id,
            request_interaction_id=interaction.id,
        )
        await interaction.followup.send(f"Run `{run_id}` started. Local path: `{run_dir}`", ephemeral=True)

    return bot


def _is_allowed(config: DiscordBotConfig, interaction: discord.Interaction) -> bool:
    if config.allowed_channel_id and interaction.channel_id != config.allowed_channel_id:
        return False
    if config.allowed_user_ids and interaction.user.id not in config.allowed_user_ids:
        return False
    return True


def main() -> None:
    config = load_discord_bot_config()
    bot = build_bot(config)
    bot.run(config.token)


if __name__ == "__main__":
    main()
