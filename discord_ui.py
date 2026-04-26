"""Discord views for human approval of generated contract bundles."""

from __future__ import annotations

from typing import Any

import discord


class PlanApprovalView(discord.ui.View):
    """Approval controls shown after a contract bundle is produced."""

    def __init__(self, *, engine: Any, run_id: str, requester_id: int, timeout: float | None = 3600) -> None:
        super().__init__(timeout=timeout)
        self.engine = engine
        self.run_id = run_id
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user.id == self.requester_id:
            return True
        await interaction.response.send_message("Only the requester can control this run.", ephemeral=True)
        return False

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer(thinking=True)
        self._disable_all()
        await interaction.message.edit(view=self)
        await self.engine.handle_plan_approval(self.run_id, interaction)

    @discord.ui.button(label="Request changes", style=discord.ButtonStyle.primary)
    async def request_changes(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(RevisionRequestModal(engine=self.engine, run_id=self.run_id))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer(thinking=True)
        self._disable_all()
        await interaction.message.edit(view=self)
        await self.engine.handle_plan_cancel(self.run_id, interaction)

    def _disable_all(self) -> None:
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True


class RevisionRequestModal(discord.ui.Modal, title="Contract revision request"):
    feedback = discord.ui.TextInput(
        label="What should change?",
        style=discord.TextStyle.paragraph,
        max_length=1800,
        required=True,
    )

    def __init__(self, *, engine: Any, run_id: str) -> None:
        super().__init__()
        self.engine = engine
        self.run_id = run_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        await self.engine.handle_plan_revision(self.run_id, str(self.feedback.value), interaction)


class QAApprovalView(discord.ui.View):
    """Approval controls shown after executable QA artifacts are posted."""

    def __init__(self, *, engine: Any, run_id: str, requester_id: int, timeout: float | None = 3600) -> None:
        super().__init__(timeout=timeout)
        self.engine = engine
        self.run_id = run_id
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user.id == self.requester_id:
            return True
        await interaction.response.send_message("Only the requester can control this QA review.", ephemeral=True)
        return False

    @discord.ui.button(label="Approve result", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer(thinking=True)
        self._disable_all()
        await interaction.message.edit(view=self)
        await self.engine.handle_qa_approval(self.run_id, interaction)

    @discord.ui.button(label="Request fixes", style=discord.ButtonStyle.primary)
    async def request_fixes(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(QARevisionRequestModal(engine=self.engine, run_id=self.run_id))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.defer(thinking=True)
        self._disable_all()
        await interaction.message.edit(view=self)
        await self.engine.handle_plan_cancel(self.run_id, interaction)

    def _disable_all(self) -> None:
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True


class QARevisionRequestModal(discord.ui.Modal, title="QA fix request"):
    feedback = discord.ui.TextInput(
        label="What should be fixed?",
        style=discord.TextStyle.paragraph,
        max_length=1800,
        required=True,
    )

    def __init__(self, *, engine: Any, run_id: str) -> None:
        super().__init__()
        self.engine = engine
        self.run_id = run_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        await self.engine.handle_qa_revision(self.run_id, str(self.feedback.value), interaction)
