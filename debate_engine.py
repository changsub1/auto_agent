"""Sequential multi-agent orchestration for Discord human-in-the-loop runs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import discord

from agents import DeveloperAgent, PlannerAgentA, PlannerAgentB
from codex_runner import CodexExecutionError, CodexResult
from discord_reporter import DiscordReporter
from discord_ui import PlanApprovalView
from qa import QAResult, run_python_syntax_check
from state_store import StateStore
from workspace_manager import (
    create_generated_app_dir,
    create_logs_dir,
    create_run_dir,
    normalize_windows_command_files,
    save_text,
)


class DebateEngine:
    """Coordinates Codex-backed agents and Discord approval steps."""

    def __init__(
        self,
        *,
        project_root: Path,
        reporter: DiscordReporter,
        planner_a_codex_home: str | None = None,
        planner_b_codex_home: str | None = None,
        developer_codex_home: str | None = None,
        max_fix_iterations: int = 1,
        codex_timeout_seconds: int = 900,
    ) -> None:
        self.project_root = Path(project_root)
        self.reporter = reporter
        self.planner_a_codex_home = planner_a_codex_home
        self.planner_b_codex_home = planner_b_codex_home
        self.developer_codex_home = developer_codex_home
        self.max_fix_iterations = max_fix_iterations
        self.codex_timeout_seconds = codex_timeout_seconds
        self.run_dirs: dict[str, Path] = {}
        self.locks: dict[str, asyncio.Lock] = {}

    async def start_discord_request(
        self,
        *,
        request: str,
        channel: discord.abc.Messageable,
        requester_id: int,
        guild_id: int | None = None,
        request_interaction_id: int | None = None,
    ) -> tuple[str, Path]:
        run_dir = create_run_dir(self.project_root)
        create_logs_dir(run_dir)
        store = StateStore(run_dir)
        store.initialize(
            user_request=request,
            discord={
                "guild_id": str(guild_id) if guild_id else None,
                "channel_id": str(getattr(channel, "id", "")),
                "requester_id": str(requester_id),
                "request_interaction_id": str(request_interaction_id) if request_interaction_id else None,
            },
            max_fix_iterations=self.max_fix_iterations,
        )
        self._register_run(run_dir)

        await self.reporter.send_status(
            channel,
            f"Started development run `{run_dir.name}`.\nRun directory: `{run_dir}`",
        )
        await self.run_planning_round(run_dir.name, channel=channel, requester_id=requester_id)
        return run_dir.name, run_dir

    async def run_planning_round(
        self,
        run_id: str,
        *,
        channel: discord.abc.Messageable,
        requester_id: int,
        user_feedback: str | None = None,
    ) -> None:
        run_dir = self._run_dir(run_id)
        lock = self._lock(run_id)
        async with lock:
            store = StateStore(run_dir)
            state = store.load()
            user_request = state["user_request"]
            logs_dir = create_logs_dir(run_dir)
            planning_dir = run_dir / "planning"
            planning_dir.mkdir(parents=True, exist_ok=True)

            store.set_status("planning_running")
            if user_feedback:
                store.add_approval(action="revision_requested", user_id=requester_id, feedback=user_feedback)
                store.append_transcript("User Revision Feedback", user_feedback)

            await self.reporter.send_status(channel, f"`{run_id}` Planning: Planner A is drafting.")
            planner_a = PlannerAgentA(
                codex_home=self.planner_a_codex_home,
                logs_dir=logs_dir,
                timeout=self.codex_timeout_seconds,
            )
            planner_b = PlannerAgentB(
                codex_home=self.planner_b_codex_home,
                logs_dir=logs_dir,
                timeout=self.codex_timeout_seconds,
            )

            previous_final = self._read_artifact_if_present(store, "final_plan")
            planner_a_session = store.get_agent_session_id("planner_a")
            if previous_final and user_feedback:
                draft_result = await self._call_codex(
                    lambda session_id: planner_a.revise_final_plan(
                        user_request,
                        previous_final,
                        "User requested a new planning round. Planner B will review after this updated draft.",
                        run_dir,
                        user_feedback=user_feedback,
                        session_id=session_id,
                    ),
                    session_id=planner_a_session,
                )
            else:
                draft_result = await self._call_codex(
                    lambda session_id: planner_a.create_initial_plan(
                        user_request,
                        run_dir,
                        session_id=session_id,
                    ),
                    session_id=planner_a_session,
                )

            draft_path = store.write_artifact(
                "planning/01_planner_a_draft.md",
                draft_result.stdout,
                artifact_name="planner_a_draft",
            )
            store.update_agent_session(
                "planner_a",
                session_id=draft_result.session_id,
                codex_home=self.planner_a_codex_home,
                last_step="draft",
            )
            store.append_event("agent_output", "planner_a", "Planner A draft created", {"path": store.to_relative(draft_path)})
            store.append_transcript("Planner A Draft", draft_result.stdout)
            await self.reporter.send_markdown(
                channel,
                title=f"{run_id} Planner A Draft",
                content=draft_result.stdout,
                artifact_path=draft_path,
            )
            await self.reporter.send_status(
                channel,
                self._agent_session_message(run_id, "Planner A", draft_result),
            )

            await self.reporter.send_status(channel, f"`{run_id}` Planning: Planner B is reviewing.")
            planner_b_session = store.get_agent_session_id("planner_b")
            review_result = await self._call_codex(
                lambda session_id: planner_b.review_plan(
                    user_request,
                    draft_result.stdout,
                    run_dir,
                    user_feedback=user_feedback,
                    session_id=session_id,
                ),
                session_id=planner_b_session,
            )
            review_path = store.write_artifact(
                "planning/02_planner_b_review.md",
                review_result.stdout,
                artifact_name="planner_b_review",
            )
            store.update_agent_session(
                "planner_b",
                session_id=review_result.session_id,
                codex_home=self.planner_b_codex_home,
                last_step="review",
            )
            store.append_event("agent_output", "planner_b", "Planner B review created", {"path": store.to_relative(review_path)})
            store.append_transcript("Planner B Review", review_result.stdout)
            await self.reporter.send_markdown(
                channel,
                title=f"{run_id} Planner B Review",
                content=review_result.stdout,
                artifact_path=review_path,
            )
            await self.reporter.send_status(
                channel,
                self._agent_session_message(run_id, "Planner B", review_result),
            )

            await self.reporter.send_status(channel, f"`{run_id}` Planning: Planner A is preparing the final plan.")
            final_result = await self._call_codex(
                lambda session_id: planner_a.revise_final_plan(
                    user_request,
                    draft_result.stdout,
                    review_result.stdout,
                    run_dir,
                    user_feedback=user_feedback,
                    session_id=session_id,
                ),
                session_id=store.get_agent_session_id("planner_a"),
            )
            final_path = store.write_artifact(
                "planning/03_final_plan.md",
                final_result.stdout,
                artifact_name="final_plan",
            )
            save_text(run_dir / "plan.md", final_result.stdout)
            store.record_artifact("plan_md", run_dir / "plan.md")
            store.update_agent_session(
                "planner_a",
                session_id=final_result.session_id,
                codex_home=self.planner_a_codex_home,
                last_step="final_plan",
            )
            store.set_status("awaiting_plan_approval")
            store.append_event("agent_output", "planner_a", "Final plan created", {"path": store.to_relative(final_path)})
            store.append_transcript("Final Plan", final_result.stdout)
            await self.reporter.send_markdown(
                channel,
                title=f"{run_id} Final Plan",
                content=final_result.stdout,
                artifact_path=final_path,
            )
            await self.reporter.send_status(
                channel,
                self._agent_session_message(run_id, "Planner A", final_result),
            )

            view = PlanApprovalView(engine=self, run_id=run_id, requester_id=requester_id)
            approval_message = await channel.send(
                f"<@{requester_id}> Review final plan for run `{run_id}`.",
                view=view,
            )
            store.update_discord(approval_message_id=str(approval_message.id))

    async def handle_plan_approval(self, run_id: str, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if channel is None:
            await interaction.followup.send("Cannot continue because this interaction has no channel.", ephemeral=True)
            return

        run_dir = self._run_dir(run_id)
        lock = self._lock(run_id)
        async with lock:
            store = StateStore(run_dir)
            store.add_approval(action="approved", user_id=interaction.user.id)
            store.set_status("development_running")
            await self.reporter.send_status(channel, f"`{run_id}` Plan approved. Developer Agent is creating the app.")

            try:
                qa_result, generated_app_dir, developer_result = await self._run_development(run_dir)
            except CodexExecutionError as exc:
                store.set_status("development_failed")
                store.append_event("codex_error", "developer", str(exc), {"stderr": exc.stderr})
                await interaction.followup.send(f"Developer Agent failed: `{exc}`")
                return

            store.set_status("completed" if qa_result.ok else "qa_failed")
            await self.reporter.send_status(
                channel,
                self._agent_session_message(run_id, "Developer", developer_result),
            )
            await self.reporter.send_artifact_paths(
                channel,
                run_dir=run_dir,
                generated_app_dir=generated_app_dir,
                qa_report_path=qa_result.report_path,
                ok=qa_result.ok,
            )
            await self.reporter.send_markdown(
                channel,
                title=f"{run_id} QA Report",
                content=qa_result.report_markdown,
                artifact_path=qa_result.report_path,
            )
            await interaction.followup.send(f"Run `{run_id}` finished with QA status: {'PASS' if qa_result.ok else 'FAIL'}.")

    async def handle_plan_revision(
        self,
        run_id: str,
        feedback: str,
        interaction: discord.Interaction,
    ) -> None:
        channel = interaction.channel
        if channel is None:
            await interaction.followup.send("Cannot revise because this interaction has no channel.", ephemeral=True)
            return
        await interaction.followup.send(f"Revision request received for run `{run_id}`.")
        await self.run_planning_round(
            run_id,
            channel=channel,
            requester_id=interaction.user.id,
            user_feedback=feedback,
        )

    async def handle_plan_cancel(self, run_id: str, interaction: discord.Interaction) -> None:
        run_dir = self._run_dir(run_id)
        store = StateStore(run_dir)
        store.add_approval(action="cancelled", user_id=interaction.user.id)
        store.set_status("cancelled")
        await interaction.followup.send(f"Run `{run_id}` cancelled.")

    async def _run_development(self, run_dir: Path) -> tuple[QAResult, Path, CodexResult]:
        store = StateStore(run_dir)
        state = store.load()
        user_request = state["user_request"]
        final_plan = self._read_artifact_if_present(store, "final_plan")
        if not final_plan:
            raise RuntimeError("Final plan artifact is missing.")

        logs_dir = create_logs_dir(run_dir)
        generated_app_dir = create_generated_app_dir(run_dir)
        developer = DeveloperAgent(
            codex_home=self.developer_codex_home,
            logs_dir=logs_dir,
            timeout=self.codex_timeout_seconds,
        )

        developer_session = store.get_agent_session_id("developer")
        create_result = await self._call_codex(
            lambda session_id: developer.create_app_result(
                user_request,
                final_plan,
                generated_app_dir,
                session_id=session_id,
            ),
            session_id=developer_session,
        )
        store.update_agent_session(
            "developer",
            session_id=create_result.session_id,
            codex_home=self.developer_codex_home,
            last_step="initial_app",
        )
        store.append_event("agent_output", "developer", "Initial app generation completed")
        store.append_transcript("Developer Initial Output", create_result.stdout)
        store.append_event(
            "agent_session",
            "developer",
            "Developer session updated",
            self._session_event_data(create_result),
        )
        normalize_windows_command_files(generated_app_dir)

        qa_report_path = run_dir / "qa_report.md"
        qa_result = run_python_syntax_check(
            generated_app_dir,
            qa_report_path,
            attempt_name="initial syntax check",
        )

        fix_iterations_used = 0
        while not qa_result.ok and fix_iterations_used < self.max_fix_iterations:
            fix_iterations_used += 1
            store.append_event("qa_failed", "qa", "Syntax QA failed", {"iteration": fix_iterations_used})
            fix_result = await self._call_codex(
                lambda session_id: developer.fix_app_result(
                    user_request,
                    final_plan,
                    generated_app_dir,
                    qa_result.error_log,
                    iteration=fix_iterations_used,
                    session_id=session_id,
                ),
                session_id=store.get_agent_session_id("developer"),
            )
            store.update_agent_session(
                "developer",
                session_id=fix_result.session_id,
                codex_home=self.developer_codex_home,
                last_step=f"fix_{fix_iterations_used}",
            )
            store.append_event("agent_output", "developer", "Fix attempt completed", {"iteration": fix_iterations_used})
            store.append_transcript(f"Developer Fix {fix_iterations_used}", fix_result.stdout)
            store.append_event(
                "agent_session",
                "developer",
                "Developer fix session updated",
                self._session_event_data(fix_result),
            )
            normalize_windows_command_files(generated_app_dir)
            qa_result = run_python_syntax_check(
                generated_app_dir,
                qa_report_path,
                attempt_name=f"syntax check after fix {fix_iterations_used}",
                append=True,
            )
            create_result = fix_result

        store.record_artifact("generated_app", generated_app_dir)
        store.record_artifact("qa_report", qa_report_path)
        store.append_transcript("QA Report", qa_result.report_markdown)
        store.append_event(
            "qa_completed",
            "qa",
            "Syntax QA completed",
            {"ok": qa_result.ok, "checked_files": [path.as_posix() for path in qa_result.checked_files]},
        )
        return qa_result, generated_app_dir, create_result

    async def _call_codex(self, func: Any, *, session_id: str | None) -> CodexResult:
        try:
            return await asyncio.to_thread(func, session_id)
        except CodexExecutionError:
            if not session_id:
                raise
            return await asyncio.to_thread(func, None)

    def _read_artifact_if_present(self, store: StateStore, artifact_name: str) -> str:
        state = store.load()
        relative_path = state.get("artifacts", {}).get(artifact_name)
        if not relative_path:
            return ""
        path = store.run_dir / relative_path
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def _register_run(self, run_dir: Path) -> None:
        self.run_dirs[run_dir.name] = Path(run_dir)
        self.locks.setdefault(run_dir.name, asyncio.Lock())

    def _run_dir(self, run_id: str) -> Path:
        if run_id in self.run_dirs:
            return self.run_dirs[run_id]
        run_dir = self.project_root / "runs" / run_id
        if not run_dir.exists():
            raise FileNotFoundError(f"Run directory not found: {run_dir}")
        self._register_run(run_dir)
        return run_dir

    def _lock(self, run_id: str) -> asyncio.Lock:
        return self.locks.setdefault(run_id, asyncio.Lock())

    def _agent_session_message(self, run_id: str, agent_label: str, result: CodexResult) -> str:
        session = _short_session_id(result.session_id)
        resumed = "yes" if result.resumed_session_id else "no"
        return f"`{run_id}` {agent_label} session: `{session}` | resumed: `{resumed}`"

    def _session_event_data(self, result: CodexResult) -> dict[str, str | None]:
        return {
            "session_id": result.session_id,
            "resumed_session_id": result.resumed_session_id,
        }


def _short_session_id(session_id: str | None) -> str:
    if not session_id:
        return "none"
    return f"{session_id[:8]}..."
