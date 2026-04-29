"""Sequential multi-agent orchestration for Discord human-in-the-loop runs."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import discord

from agents import ArchitectAgent, CodeAgent, IntegratorAgent, PlannerAgentA, PlannerAgentB, QAAgent, ScaffoldAgent
from codex_runner import CodexExecutionError, CodexResult
from discord_reporter import DiscordReporter
from discord_ui import PlanApprovalView, QAApprovalView
from executable_qa import ExecutableQAResult, run_executable_qa
from parallel_workflow import (
    CodeAgentAssignment,
    assign_code_agent_tasks,
    build_existing_code_agent_assignments,
    copy_tree_contents,
    create_agent_outputs_dir,
    create_agent_workspaces_dir,
    create_contract_dir,
    create_merged_app_dir,
    create_scaffold_dir,
    list_workspace_files,
    load_task_manifest,
    normalize_contract_bundle,
    render_assignment_summary,
    render_contract_bundle,
    reset_generated_app_from_merged,
    seed_merged_app_from_owned_paths,
)
from qa import QAResult, combine_mechanical_qa_results, run_python_syntax_check
from reference_packs import DEFAULT_REFERENCE_PROFILES, load_profile_reference_text, prepare_reference_profiles
from routing import RoutingDecision, decide_route, normalize_routing_mode
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
        architect_codex_home: str | None = None,
        scaffold_codex_home: str | None = None,
        developer_codex_home: str | None = None,
        integrator_codex_home: str | None = None,
        code_agent_codex_homes: list[str | None] | None = None,
        code_agent_count: int = 2,
        qa_agent_codex_homes: list[str | None] | None = None,
        qa_agent_count: int = 1,
        codex_model: str | None = None,
        codex_reasoning_effort: str | None = None,
        max_fix_iterations: int = 1,
        codex_timeout_seconds: int = 900,
        executable_qa_enabled: bool = True,
        executable_qa_timeout_seconds: int = 90,
        executable_qa_allow_local_commands: bool = False,
        routing_mode: str = "balanced",
        reference_pack_enabled: bool = True,
        agent_references: dict[str, str | None] | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.reporter = reporter
        self.planner_a_codex_home = planner_a_codex_home
        self.planner_b_codex_home = planner_b_codex_home
        self.architect_codex_home = architect_codex_home if architect_codex_home is not None else planner_b_codex_home
        self.scaffold_codex_home = scaffold_codex_home if scaffold_codex_home is not None else developer_codex_home
        self.developer_codex_home = developer_codex_home
        self.integrator_codex_home = integrator_codex_home if integrator_codex_home is not None else developer_codex_home
        self.code_agent_codex_homes = code_agent_codex_homes or [developer_codex_home]
        self.code_agent_count = max(1, code_agent_count)
        self.qa_agent_codex_homes = qa_agent_codex_homes or [self.integrator_codex_home]
        self.qa_agent_count = max(0, qa_agent_count)
        self.codex_model = codex_model
        self.codex_reasoning_effort = codex_reasoning_effort
        self.max_fix_iterations = max_fix_iterations
        self.codex_timeout_seconds = codex_timeout_seconds
        self.executable_qa_enabled = executable_qa_enabled
        self.executable_qa_timeout_seconds = executable_qa_timeout_seconds
        self.executable_qa_allow_local_commands = executable_qa_allow_local_commands
        self.routing_mode = normalize_routing_mode(routing_mode)
        self.reference_pack_enabled = reference_pack_enabled
        self.agent_references = dict(DEFAULT_REFERENCE_PROFILES)
        if agent_references is not None:
            self.agent_references.update(agent_references)
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
        route = decide_route(
            request,
            requested_mode=self.routing_mode,
            max_code_agent_count=self.code_agent_count,
            max_qa_agent_count=self.qa_agent_count,
        )
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
            code_agent_count=route.code_agent_count,
            qa_agent_count=route.qa_agent_count,
        )
        self._record_route(store, route)
        self._prepare_reference_profiles(run_dir, store)
        self._register_run(run_dir)

        await self.reporter.send_status(
            channel,
            "\n".join(
                [
                    f"Started development run `{run_dir.name}`.",
                    f"Route: `{route.mode}` ({route.reason})",
                    f"Run directory: `{run_dir}`",
                ]
            ),
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
            route = self._route_for_state(state)
            logs_dir = create_logs_dir(run_dir)
            planning_dir = run_dir / "planning"
            planning_dir.mkdir(parents=True, exist_ok=True)

            store.set_status("planning_running")
            if user_feedback:
                store.add_approval(action="revision_requested", user_id=requester_id, feedback=user_feedback)
                store.append_transcript("User Revision Feedback", user_feedback)

            await self.reporter.send_status(
                channel,
                f"`{run_id}` Planning: Planner A is drafting. Route: `{route.mode}`.",
            )
            planner_a = PlannerAgentA(
                codex_home=self.planner_a_codex_home,
                logs_dir=logs_dir,
                timeout=self.codex_timeout_seconds,
                model=self.codex_model,
                reasoning_effort=self.codex_reasoning_effort,
                reference_markdown=self._reference_for_role(run_dir, "planner_a"),
            )
            planner_b = PlannerAgentB(
                codex_home=self.planner_b_codex_home,
                logs_dir=logs_dir,
                timeout=self.codex_timeout_seconds,
                model=self.codex_model,
                reasoning_effort=self.codex_reasoning_effort,
                reference_markdown=self._reference_for_role(run_dir, "planner_b"),
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
                model=draft_result.model,
                reasoning_effort=draft_result.reasoning_effort,
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

            review_text = f"(Planner B review skipped by `{route.mode}` route.)"
            if route.planner_count >= 2:
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
                review_text = review_result.stdout
                review_path = store.write_artifact(
                    "planning/02_planner_b_review.md",
                    review_text,
                    artifact_name="planner_b_review",
                )
                store.update_agent_session(
                    "planner_b",
                    session_id=review_result.session_id,
                    codex_home=self.planner_b_codex_home,
                    model=review_result.model,
                    reasoning_effort=review_result.reasoning_effort,
                    last_step="review",
                )
                store.append_event("agent_output", "planner_b", "Planner B review created", {"path": store.to_relative(review_path)})
                store.append_transcript("Planner B Review", review_text)
                await self.reporter.send_markdown(
                    channel,
                    title=f"{run_id} Planner B Review",
                    content=review_text,
                    artifact_path=review_path,
                )
                await self.reporter.send_status(
                    channel,
                    self._agent_session_message(run_id, "Planner B", review_result),
                )
            else:
                review_path = store.write_artifact(
                    "planning/02_planner_b_review.md",
                    review_text,
                    artifact_name="planner_b_review",
                )
                store.append_event("agent_output", "planner_b", "Planner B skipped", {"path": store.to_relative(review_path)})
                store.append_transcript("Planner B Review", review_text)

            final_result = draft_result
            final_text = draft_result.stdout
            if route.planner_count >= 2:
                await self.reporter.send_status(channel, f"`{run_id}` Planning: Planner A is preparing the final plan.")
                final_result = await self._call_codex(
                    lambda session_id: planner_a.revise_final_plan(
                        user_request,
                        draft_result.stdout,
                        review_text,
                        run_dir,
                        user_feedback=user_feedback,
                        session_id=session_id,
                    ),
                    session_id=store.get_agent_session_id("planner_a"),
                )
                final_text = final_result.stdout
            final_path = store.write_artifact(
                "planning/03_final_plan.md",
                final_text,
                artifact_name="final_plan",
            )
            save_text(run_dir / "plan.md", final_text)
            store.record_artifact("plan_md", run_dir / "plan.md")
            store.update_agent_session(
                "planner_a",
                session_id=final_result.session_id,
                codex_home=self.planner_a_codex_home,
                model=final_result.model,
                reasoning_effort=final_result.reasoning_effort,
                last_step="final_plan",
            )
            store.append_event("agent_output", "planner_a", "Final plan created", {"path": store.to_relative(final_path)})
            store.append_transcript("Final Plan", final_text)
            await self.reporter.send_markdown(
                channel,
                title=f"{run_id} Final Plan",
                content=final_text,
                artifact_path=final_path,
            )
            await self.reporter.send_status(
                channel,
                self._agent_session_message(run_id, "Planner A", final_result),
            )

            approval_target = "final plan"
            if route.uses_contract:
                store.set_status("contract_running")
                await self.reporter.send_status(channel, f"`{run_id}` Architecture: Architect Agent is creating the contract bundle.")
                contract_dir = create_contract_dir(run_dir)
                architect = ArchitectAgent(
                    codex_home=self.architect_codex_home,
                    logs_dir=logs_dir,
                    timeout=self.codex_timeout_seconds,
                    model=self.codex_model,
                    reasoning_effort=self.codex_reasoning_effort,
                )
                try:
                    architect_result = await self._call_codex(
                        lambda session_id: architect.create_contract_bundle_result(
                            user_request,
                            draft_result.stdout,
                            review_text,
                            final_text,
                            contract_dir,
                            session_id=session_id,
                        ),
                        session_id=store.get_agent_session_id("architect"),
                    )
                except CodexExecutionError as exc:
                    store.set_status("contract_failed")
                    store.append_event("codex_error", "architect", str(exc), {"stderr": exc.stderr})
                    await self.reporter.send_status(channel, f"`{run_id}` Architect Agent failed: `{exc}`")
                    return
                contract_paths = normalize_contract_bundle(contract_dir, user_request, final_text)
                store.record_artifact("contract_dir", contract_dir)
                for path in contract_paths:
                    store.record_artifact(f"contract_{path.stem}", path)
                store.update_agent_session(
                    "architect",
                    session_id=architect_result.session_id,
                    codex_home=self.architect_codex_home,
                    model=architect_result.model,
                    reasoning_effort=architect_result.reasoning_effort,
                    last_step="contract_bundle",
                )
                store.append_event(
                    "agent_output",
                    "architect",
                    "Contract bundle created",
                    {"path": store.to_relative(contract_dir), "files": [store.to_relative(path) for path in contract_paths]},
                )
                store.append_transcript("Architect Contract Summary", architect_result.stdout)
                await self.reporter.send_markdown(
                    channel,
                    title=f"{run_id} Architect Contract Summary",
                    content=architect_result.stdout,
                    artifact_path=contract_dir / "requirements.md",
                )
                await self.reporter.send_status(
                    channel,
                    self._agent_session_message(run_id, "Architect", architect_result),
                )
                await self.reporter.send_status(
                    channel,
                    f"`{run_id}` Contract bundle ready: `{contract_dir}`",
                )
                approval_target = "contract bundle"

            store.set_status("awaiting_contract_approval" if route.uses_contract else "awaiting_plan_approval")
            view = PlanApprovalView(engine=self, run_id=run_id, requester_id=requester_id)
            approval_message = await channel.send(
                f"<@{requester_id}> Review the {approval_target} for run `{run_id}`. Route: `{route.mode}`.",
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
            route = self._route_for_state(store.load())
            store.add_approval(action="approved", user_id=interaction.user.id)
            store.set_status("development_running")
            await self.reporter.send_status(
                channel,
                f"`{run_id}` Plan approved. Starting `{route.mode}` development route.",
            )

            try:
                qa_result, generated_app_dir, developer_result = await self._run_development(run_dir)
            except CodexExecutionError as exc:
                store.set_status("development_failed")
                store.append_event("codex_error", "developer", str(exc), {"stderr": exc.stderr})
                await interaction.followup.send(f"Developer Agent failed: `{exc}`")
                return

            store.set_status("awaiting_qa_approval")
            final_agent_label = "Integrator" if route.uses_integrator else "Code Agent"
            await self.reporter.send_status(
                channel,
                self._agent_session_message(run_id, final_agent_label, developer_result),
            )
            await self._publish_qa_review(
                channel,
                run_id=run_id,
                run_dir=run_dir,
                generated_app_dir=generated_app_dir,
                qa_result=qa_result,
                requester_id=interaction.user.id,
            )
            await interaction.followup.send(
                f"Run `{run_id}` is waiting for QA review. QA status: {'PASS' if qa_result.ok else 'FAIL'}."
            )

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

    async def handle_qa_approval(self, run_id: str, interaction: discord.Interaction) -> None:
        run_dir = self._run_dir(run_id)
        store = StateStore(run_dir)
        store.add_approval(action="qa_approved", user_id=interaction.user.id)
        store.set_status("completed")
        await interaction.followup.send(f"Run `{run_id}` approved and completed.")

    async def handle_qa_revision(
        self,
        run_id: str,
        feedback: str,
        interaction: discord.Interaction,
    ) -> None:
        channel = interaction.channel
        if channel is None:
            await interaction.followup.send("Cannot revise QA because this interaction has no channel.", ephemeral=True)
            return

        run_dir = self._run_dir(run_id)
        lock = self._lock(run_id)
        async with lock:
            store = StateStore(run_dir)
            store.add_approval(action="qa_revision_requested", user_id=interaction.user.id, feedback=feedback)
            store.append_transcript("QA Revision Feedback", feedback)
            store.set_status("qa_revision_running")
            await self.reporter.send_status(channel, f"`{run_id}` QA fix requested. Integrator is applying feedback.")

            try:
                qa_result, generated_app_dir, fix_result = await self._run_qa_revision(run_dir, feedback)
            except CodexExecutionError as exc:
                store.set_status("qa_revision_failed")
                store.append_event("codex_error", "integrator", str(exc), {"stderr": exc.stderr})
                await interaction.followup.send(f"QA revision failed: `{exc}`")
                return

            store.set_status("awaiting_qa_approval")
            await self.reporter.send_status(channel, self._agent_session_message(run_id, "Integrator", fix_result))
            await self._publish_qa_review(
                channel,
                run_id=run_id,
                run_dir=run_dir,
                generated_app_dir=generated_app_dir,
                qa_result=qa_result,
                requester_id=interaction.user.id,
            )
            await interaction.followup.send(
                f"Run `{run_id}` QA revision finished. QA status: {'PASS' if qa_result.ok else 'FAIL'}."
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
        route = self._route_for_state(state)
        if not route.uses_integrator:
            return await self._run_single_code_development(run_dir, route)

        logs_dir = create_logs_dir(run_dir)
        contract_dir = run_dir / state.get("artifacts", {}).get("contract_dir", "contract")
        contract_paths = normalize_contract_bundle(contract_dir, user_request, final_plan)
        for path in contract_paths:
            store.record_artifact(f"contract_{path.stem}", path)
        contract_bundle = render_contract_bundle(contract_dir)

        store.set_status("scaffold_running")
        scaffold_dir = create_scaffold_dir(run_dir)
        scaffold = ScaffoldAgent(
            codex_home=self.scaffold_codex_home,
            logs_dir=logs_dir,
            timeout=self.codex_timeout_seconds,
            model=self.codex_model,
            reasoning_effort=self.codex_reasoning_effort,
        )
        scaffold_result = await self._call_codex(
            lambda session_id: scaffold.create_scaffold_result(
                user_request,
                contract_bundle,
                scaffold_dir,
                session_id=session_id,
            ),
            session_id=store.get_agent_session_id("scaffold"),
        )
        store.update_agent_session(
            "scaffold",
            session_id=scaffold_result.session_id,
            codex_home=self.scaffold_codex_home,
            model=scaffold_result.model,
            reasoning_effort=scaffold_result.reasoning_effort,
            last_step="scaffold_app",
        )
        store.record_artifact("scaffold_app", scaffold_dir)
        store.append_event("agent_output", "scaffold", "Scaffold app created", {"path": store.to_relative(scaffold_dir)})
        store.append_transcript("Scaffold Output", scaffold_result.stdout)
        normalize_windows_command_files(scaffold_dir)

        tasks = load_task_manifest(contract_dir)
        workspaces_dir = create_agent_workspaces_dir(run_dir)
        outputs_dir = create_agent_outputs_dir(run_dir)
        assignments = assign_code_agent_tasks(
            tasks,
            code_agent_count=route.code_agent_count,
            code_agent_codex_homes=self.code_agent_codex_homes,
            scaffold_dir=scaffold_dir,
            workspaces_dir=workspaces_dir,
        )
        store.record_artifact("agent_workspaces", workspaces_dir)
        store.record_artifact("agent_outputs", outputs_dir)
        store.write_artifact(
            "agent_outputs/assignment_summary.md",
            render_assignment_summary(assignments),
            artifact_name="assignment_summary",
        )

        store.set_status("code_agents_running")
        store.append_event(
            "code_agents_started",
            "system",
            "Parallel code agents started",
            {"agents": [assignment.agent_id for assignment in assignments]},
        )
        code_results = await asyncio.gather(
            *[
                self._run_code_agent_assignment(
                    user_request=user_request,
                    contract_bundle=contract_bundle,
                    assignment=assignment,
                    logs_dir=logs_dir,
                    store=store,
                )
                for assignment in assignments
            ]
        )
        for assignment, code_result in zip(assignments, code_results, strict=True):
            output_path = store.write_artifact(
                f"agent_outputs/{assignment.agent_id}_summary.md",
                code_result.stdout,
                artifact_name=f"{assignment.agent_id}_summary",
            )
            store.update_agent_session(
                assignment.agent_id,
                session_id=code_result.session_id,
                codex_home=assignment.codex_home,
                model=code_result.model,
                reasoning_effort=code_result.reasoning_effort,
                last_step="implement_tasks",
            )
            store.append_event(
                "agent_output",
                assignment.agent_id,
                "Code agent completed assigned tasks",
                {"path": store.to_relative(output_path), **self._session_event_data(code_result)},
            )
            store.append_transcript(f"{assignment.agent_id} Output", code_result.stdout)
            normalize_windows_command_files(assignment.workspace_dir)

        store.set_status("integration_running")
        merged_app_dir = create_merged_app_dir(run_dir)
        # Start with scaffold, then deterministic owned-path copies. The
        # Integrator Agent handles shared entrypoints and conflicts after this.
        copy_tree_contents(scaffold_dir, merged_app_dir)
        merge_seed_report = seed_merged_app_from_owned_paths(assignments, merged_app_dir)
        store.write_artifact(
            "integration/merge_seed_report.md",
            merge_seed_report,
            artifact_name="merge_seed_report",
        )
        assignment_summary = render_assignment_summary(assignments)
        workspace_listing = "\n\n".join(
            [
                f"## {assignment.agent_id}\n\n{list_workspace_files(assignment.workspace_dir)}"
                for assignment in assignments
            ]
        )
        integrator = IntegratorAgent(
            codex_home=self.integrator_codex_home,
            logs_dir=logs_dir,
            timeout=self.codex_timeout_seconds,
            model=self.codex_model,
            reasoning_effort=self.codex_reasoning_effort,
            reference_markdown=self._reference_for_role(run_dir, "integrator"),
        )
        integration_result = await self._call_codex(
            lambda session_id: integrator.integrate_result(
                user_request,
                contract_bundle,
                assignment_summary,
                workspace_listing,
                run_dir,
                session_id=session_id,
            ),
            session_id=store.get_agent_session_id("integrator"),
        )
        store.update_agent_session(
            "integrator",
            session_id=integration_result.session_id,
            codex_home=self.integrator_codex_home,
            model=integration_result.model,
            reasoning_effort=integration_result.reasoning_effort,
            last_step="integrated_app",
        )
        store.record_artifact("merged_app", merged_app_dir)
        store.append_event(
            "agent_output",
            "integrator",
            "Integration completed",
            {"path": store.to_relative(merged_app_dir), **self._session_event_data(integration_result)},
        )
        store.append_transcript("Integrator Output", integration_result.stdout)
        normalize_windows_command_files(merged_app_dir)

        generated_app_dir = reset_generated_app_from_merged(run_dir, merged_app_dir)
        normalize_windows_command_files(generated_app_dir)
        store.record_artifact("generated_app", generated_app_dir)

        fix_iterations_used = 0
        final_agent_result = integration_result
        qa_result = await self._run_qa_cycle(
            run_dir,
            generated_app_dir,
            "integrated mechanical QA",
            fix_iterations_used,
        )

        while not qa_result.ok and fix_iterations_used < self.max_fix_iterations:
            fix_iterations_used += 1
            store.append_event(
                "qa_failed",
                "qa",
                "QA failed",
                {
                    "iteration": fix_iterations_used,
                    "executable_status": qa_result.executable_status,
                    "suspected_owners": qa_result.suspected_owners,
                    "affected_paths": qa_result.affected_paths,
                },
            )
            fix_result = await self._run_targeted_fix(
                run_dir=run_dir,
                user_request=user_request,
                contract_bundle=contract_bundle,
                assignments=assignments,
                qa_result=qa_result,
                feedback=qa_result.error_log or qa_result.report_markdown,
                iteration=fix_iterations_used,
            )
            merged_app_dir = run_dir / "integration" / "merged_app"
            generated_app_dir = reset_generated_app_from_merged(run_dir, merged_app_dir)
            normalize_windows_command_files(generated_app_dir)
            store.record_artifact("generated_app", generated_app_dir)
            qa_result = await self._run_qa_cycle(
                run_dir,
                generated_app_dir,
                f"mechanical QA after fix {fix_iterations_used}",
                fix_iterations_used,
            )
            final_agent_result = fix_result

        store.append_transcript("QA Report", qa_result.report_markdown)
        store.append_event(
            "qa_completed",
            "qa",
            "Mechanical QA completed",
            {
                "ok": qa_result.ok,
                "checked_files": [path.as_posix() for path in qa_result.checked_files],
                "executable_status": qa_result.executable_status,
                "executable_app_type": qa_result.executable_app_type,
                "screenshots": [store.to_relative(path) for path in qa_result.screenshots],
            },
        )
        return qa_result, generated_app_dir, final_agent_result

    async def _run_single_code_development(
        self,
        run_dir: Path,
        route: RoutingDecision,
    ) -> tuple[QAResult, Path, CodexResult]:
        store = StateStore(run_dir)
        state = store.load()
        user_request = state["user_request"]
        final_plan = self._read_artifact_if_present(store, "final_plan")
        logs_dir = create_logs_dir(run_dir)
        generated_app_dir = create_generated_app_dir(run_dir)
        outputs_dir = create_agent_outputs_dir(run_dir)
        assignment = self._single_code_assignment(generated_app_dir)
        assignment_summary = render_assignment_summary([assignment])

        store.record_artifact("generated_app", generated_app_dir)
        store.record_artifact("agent_outputs", outputs_dir)
        store.write_artifact(
            "agent_outputs/assignment_summary.md",
            assignment_summary,
            artifact_name="assignment_summary",
        )
        store.append_event(
            "code_agents_started",
            "system",
            "Single code agent started",
            {"agents": [assignment.agent_id], "route": route.mode},
        )

        store.set_status("code_agent_running")
        code_result = await self._run_code_agent_assignment(
            user_request=user_request,
            contract_bundle=self._single_code_context(final_plan, route),
            assignment=assignment,
            logs_dir=logs_dir,
            store=store,
        )
        output_path = store.write_artifact(
            "agent_outputs/code_1_summary.md",
            code_result.stdout,
            artifact_name="code_1_summary",
        )
        store.update_agent_session(
            "code_1",
            session_id=code_result.session_id,
            codex_home=assignment.codex_home,
            model=code_result.model,
            reasoning_effort=code_result.reasoning_effort,
            last_step="implement_tasks",
        )
        store.append_event(
            "agent_output",
            "code_1",
            "Code agent completed assigned tasks",
            {"path": store.to_relative(output_path), **self._session_event_data(code_result)},
        )
        store.append_transcript("code_1 Output", code_result.stdout)
        normalize_windows_command_files(generated_app_dir)

        fix_iterations_used = 0
        final_agent_result = code_result
        qa_result = await self._run_qa_cycle(
            run_dir,
            generated_app_dir,
            "single-agent mechanical QA",
            fix_iterations_used,
        )
        while not qa_result.ok and fix_iterations_used < self.max_fix_iterations:
            fix_iterations_used += 1
            fix_result = await self._run_code_agent_fix(
                user_request=user_request,
                contract_bundle=self._single_code_context(final_plan, route),
                assignment=assignment,
                feedback=qa_result.error_log or qa_result.report_markdown,
                iteration=fix_iterations_used,
                logs_dir=logs_dir,
                store=store,
            )
            output_path = store.write_artifact(
                f"agent_outputs/code_1_fix_{fix_iterations_used:02d}.md",
                fix_result.stdout,
                artifact_name=f"code_1_fix_{fix_iterations_used:02d}",
            )
            store.update_agent_session(
                "code_1",
                session_id=fix_result.session_id,
                codex_home=assignment.codex_home,
                model=fix_result.model,
                reasoning_effort=fix_result.reasoning_effort,
                last_step=f"fix_{fix_iterations_used}",
            )
            store.append_event(
                "agent_output",
                "code_1",
                "Code agent fix completed",
                {"path": store.to_relative(output_path), **self._session_event_data(fix_result)},
            )
            store.append_transcript(f"code_1 Fix {fix_iterations_used}", fix_result.stdout)
            normalize_windows_command_files(generated_app_dir)
            qa_result = await self._run_qa_cycle(
                run_dir,
                generated_app_dir,
                f"single-agent mechanical QA after fix {fix_iterations_used}",
                fix_iterations_used,
            )
            final_agent_result = fix_result

        store.append_transcript("QA Report", qa_result.report_markdown)
        store.append_event(
            "qa_completed",
            "qa",
            "Mechanical QA completed",
            {
                "ok": qa_result.ok,
                "checked_files": [path.as_posix() for path in qa_result.checked_files],
                "executable_status": qa_result.executable_status,
                "executable_app_type": qa_result.executable_app_type,
                "screenshots": [store.to_relative(path) for path in qa_result.screenshots],
            },
        )
        return qa_result, generated_app_dir, final_agent_result

    async def _run_qa_revision(self, run_dir: Path, feedback: str) -> tuple[QAResult, Path, CodexResult]:
        store = StateStore(run_dir)
        state = store.load()
        route = self._route_for_state(state)
        if not route.uses_integrator:
            return await self._run_single_qa_revision(run_dir, feedback, route)

        user_request = state["user_request"]
        logs_dir = create_logs_dir(run_dir)
        generated_app_dir = run_dir / state.get("artifacts", {}).get("generated_app", "generated_app")
        if not generated_app_dir.exists():
            raise FileNotFoundError(f"Generated app directory not found: {generated_app_dir}")

        final_plan = self._read_artifact_if_present(store, "final_plan")
        contract_dir = run_dir / state.get("artifacts", {}).get("contract_dir", "contract")
        contract_bundle = render_contract_bundle(contract_dir) if contract_dir.exists() else final_plan
        latest_qa = self._read_artifact_if_present(store, "qa_report")
        revision_count = sum(
            1
            for item in state.get("approval_history", [])
            if item.get("action") == "qa_revision_requested"
        )
        error_log = "\n\n".join(
            part
            for part in [
                "User QA feedback:",
                feedback,
                "Latest QA report:",
                latest_qa,
            ]
            if part
        )
        tasks = load_task_manifest(contract_dir)
        assignments = self._existing_code_assignments(run_dir, tasks)
        synthetic_qa_result = QAResult(
            ok=False,
            checked_files=[],
            error_log=error_log,
            report_path=run_dir / "qa_report.md",
            report_markdown=latest_qa,
            affected_paths=_extract_affected_paths(error_log),
            suspected_owners=_extract_suspected_owners(error_log),
        )
        fix_result = await self._run_targeted_fix(
            run_dir=run_dir,
            user_request=user_request,
            contract_bundle=contract_bundle,
            assignments=assignments,
            qa_result=synthetic_qa_result,
            feedback=error_log,
            iteration=revision_count,
        )
        merged_app_dir = run_dir / "integration" / "merged_app"
        generated_app_dir = reset_generated_app_from_merged(run_dir, merged_app_dir)
        normalize_windows_command_files(generated_app_dir)
        store.record_artifact("generated_app", generated_app_dir)

        qa_result = await self._run_qa_cycle(
            run_dir,
            generated_app_dir,
            f"mechanical QA after user revision {revision_count}",
            100 + revision_count,
        )
        store.append_transcript("QA Report", qa_result.report_markdown)
        store.append_event(
            "qa_completed",
            "qa",
            "Mechanical QA completed after user revision",
            {
                "ok": qa_result.ok,
                "executable_status": qa_result.executable_status,
                "executable_app_type": qa_result.executable_app_type,
                "screenshots": [store.to_relative(path) for path in qa_result.screenshots],
            },
        )
        return qa_result, generated_app_dir, fix_result

    async def _run_single_qa_revision(
        self,
        run_dir: Path,
        feedback: str,
        route: RoutingDecision,
    ) -> tuple[QAResult, Path, CodexResult]:
        store = StateStore(run_dir)
        state = store.load()
        user_request = state["user_request"]
        logs_dir = create_logs_dir(run_dir)
        generated_app_dir = run_dir / state.get("artifacts", {}).get("generated_app", "generated_app")
        if not generated_app_dir.exists():
            raise FileNotFoundError(f"Generated app directory not found: {generated_app_dir}")

        final_plan = self._read_artifact_if_present(store, "final_plan")
        latest_qa = self._read_artifact_if_present(store, "qa_report")
        revision_count = sum(
            1
            for item in state.get("approval_history", [])
            if item.get("action") == "qa_revision_requested"
        )
        qa_feedback = "\n\n".join(
            part
            for part in [
                "User QA feedback:",
                feedback,
                "Latest QA report:",
                latest_qa,
            ]
            if part
        )
        assignment = self._single_code_assignment(generated_app_dir)
        fix_result = await self._run_code_agent_fix(
            user_request=user_request,
            contract_bundle=self._single_code_context(final_plan, route),
            assignment=assignment,
            feedback=qa_feedback,
            iteration=revision_count,
            logs_dir=logs_dir,
            store=store,
        )
        output_path = store.write_artifact(
            f"agent_outputs/code_1_user_fix_{revision_count:02d}.md",
            fix_result.stdout,
            artifact_name=f"code_1_user_fix_{revision_count:02d}",
        )
        store.update_agent_session(
            "code_1",
            session_id=fix_result.session_id,
            codex_home=assignment.codex_home,
            model=fix_result.model,
            reasoning_effort=fix_result.reasoning_effort,
            last_step=f"user_fix_{revision_count}",
        )
        store.append_event(
            "agent_output",
            "code_1",
            "Code agent user-requested fix completed",
            {"path": store.to_relative(output_path), **self._session_event_data(fix_result)},
        )
        store.append_transcript(f"code_1 User Fix {revision_count}", fix_result.stdout)
        normalize_windows_command_files(generated_app_dir)

        qa_result = await self._run_qa_cycle(
            run_dir,
            generated_app_dir,
            f"mechanical QA after user revision {revision_count}",
            100 + revision_count,
        )
        store.append_transcript("QA Report", qa_result.report_markdown)
        store.append_event(
            "qa_completed",
            "qa",
            "Mechanical QA completed after user revision",
            {
                "ok": qa_result.ok,
                "executable_status": qa_result.executable_status,
                "executable_app_type": qa_result.executable_app_type,
                "screenshots": [store.to_relative(path) for path in qa_result.screenshots],
            },
        )
        return qa_result, generated_app_dir, fix_result

    async def _run_code_agent_assignment(
        self,
        *,
        user_request: str,
        contract_bundle: str,
        assignment: CodeAgentAssignment,
        logs_dir: Path,
        store: StateStore,
    ) -> CodexResult:
        code_agent = CodeAgent(
            agent_id=assignment.agent_id,
            codex_home=assignment.codex_home,
            logs_dir=logs_dir,
            timeout=self.codex_timeout_seconds,
            model=self.codex_model,
            reasoning_effort=self.codex_reasoning_effort,
            reference_markdown=self._reference_for_role(store.run_dir, "code_agent"),
        )
        return await self._call_codex(
            lambda session_id: code_agent.implement_tasks_result(
                user_request,
                contract_bundle,
                assignment.to_prompt_json(),
                assignment.workspace_dir,
                session_id=session_id,
            ),
            session_id=store.get_agent_session_id(assignment.agent_id),
        )

    async def _run_targeted_fix(
        self,
        *,
        run_dir: Path,
        user_request: str,
        contract_bundle: str,
        assignments: list[CodeAgentAssignment],
        qa_result: QAResult,
        feedback: str,
        iteration: int,
    ) -> CodexResult:
        store = StateStore(run_dir)
        logs_dir = create_logs_dir(run_dir)
        targets = self._resolve_fix_targets(assignments, qa_result)
        store.append_event(
            "fix_routing",
            "system",
            "Routed QA fix",
            {
                "iteration": iteration,
                "targets": targets,
                "affected_paths": qa_result.affected_paths,
                "suspected_owners": qa_result.suspected_owners,
            },
        )

        code_targets = [target for target in targets if target.startswith("code_")]
        for assignment in assignments:
            if assignment.agent_id not in code_targets:
                continue
            result = await self._run_code_agent_fix(
                user_request=user_request,
                contract_bundle=contract_bundle,
                assignment=assignment,
                feedback=feedback,
                iteration=iteration,
                logs_dir=logs_dir,
                store=store,
            )
            output_path = store.write_artifact(
                f"agent_outputs/{assignment.agent_id}_fix_{iteration:02d}.md",
                result.stdout,
                artifact_name=f"{assignment.agent_id}_fix_{iteration:02d}",
            )
            store.update_agent_session(
                assignment.agent_id,
                session_id=result.session_id,
                codex_home=assignment.codex_home,
                model=result.model,
                reasoning_effort=result.reasoning_effort,
                last_step=f"fix_{iteration}",
            )
            store.append_event(
                "agent_output",
                assignment.agent_id,
                "Code agent fix completed",
                {"path": store.to_relative(output_path), **self._session_event_data(result)},
            )
            store.append_transcript(f"{assignment.agent_id} Fix {iteration}", result.stdout)
            normalize_windows_command_files(assignment.workspace_dir)

        if code_targets:
            merged_app_dir = create_merged_app_dir(run_dir)
            scaffold_dir = run_dir / "scaffold_app"
            copy_tree_contents(scaffold_dir, merged_app_dir)
            merge_seed_report = seed_merged_app_from_owned_paths(assignments, merged_app_dir)
            store.write_artifact(
                f"integration/merge_seed_report_fix_{iteration:02d}.md",
                merge_seed_report,
                artifact_name=f"merge_seed_report_fix_{iteration:02d}",
            )

        return await self._run_integrator_repair(
            run_dir=run_dir,
            user_request=user_request,
            contract_bundle=contract_bundle,
            assignments=assignments,
            feedback=feedback,
            iteration=iteration,
            store=store,
            logs_dir=logs_dir,
        )

    async def _run_code_agent_fix(
        self,
        *,
        user_request: str,
        contract_bundle: str,
        assignment: CodeAgentAssignment,
        feedback: str,
        iteration: int,
        logs_dir: Path,
        store: StateStore,
    ) -> CodexResult:
        code_agent = CodeAgent(
            agent_id=assignment.agent_id,
            codex_home=assignment.codex_home,
            logs_dir=logs_dir,
            timeout=self.codex_timeout_seconds,
            model=self.codex_model,
            reasoning_effort=self.codex_reasoning_effort,
            reference_markdown=self._reference_for_role(store.run_dir, "code_agent"),
        )
        return await self._call_codex(
            lambda session_id: code_agent.fix_assigned_tasks_result(
                user_request,
                contract_bundle,
                assignment.to_prompt_json(),
                feedback,
                assignment.workspace_dir,
                iteration=iteration,
                session_id=session_id,
            ),
            session_id=store.get_agent_session_id(assignment.agent_id),
        )

    async def _run_integrator_repair(
        self,
        *,
        run_dir: Path,
        user_request: str,
        contract_bundle: str,
        assignments: list[CodeAgentAssignment],
        feedback: str,
        iteration: int,
        store: StateStore,
        logs_dir: Path,
    ) -> CodexResult:
        assignment_summary = render_assignment_summary(assignments)
        workspace_listing = "\n\n".join(
            [
                f"## {assignment.agent_id}\n\n{list_workspace_files(assignment.workspace_dir)}"
                for assignment in assignments
            ]
        )
        integrator = IntegratorAgent(
            codex_home=self.integrator_codex_home,
            logs_dir=logs_dir,
            timeout=self.codex_timeout_seconds,
            model=self.codex_model,
            reasoning_effort=self.codex_reasoning_effort,
            reference_markdown=self._reference_for_role(run_dir, "integrator"),
        )
        result = await self._call_codex(
            lambda session_id: integrator.repair_integration_result(
                user_request,
                contract_bundle,
                assignment_summary,
                workspace_listing,
                feedback,
                run_dir,
                iteration=iteration,
                session_id=session_id,
            ),
            session_id=store.get_agent_session_id("integrator"),
        )
        store.update_agent_session(
            "integrator",
            session_id=result.session_id,
            codex_home=self.integrator_codex_home,
            model=result.model,
            reasoning_effort=result.reasoning_effort,
            last_step=f"fix_{iteration}",
        )
        store.append_event("agent_output", "integrator", "Integrator repair completed", self._session_event_data(result))
        store.append_transcript(f"Integrator Repair {iteration}", result.stdout)
        normalize_windows_command_files(run_dir / "integration" / "merged_app")
        return result

    def _existing_code_assignments(self, run_dir: Path, tasks: list[dict[str, Any]]) -> list[CodeAgentAssignment]:
        state = StateStore(run_dir).load()
        code_agent_count = int(state.get("parallel", {}).get("code_agent_count", self.code_agent_count))
        workspaces_dir = run_dir / state.get("artifacts", {}).get("agent_workspaces", "agent_workspaces")
        assignments = build_existing_code_agent_assignments(
            tasks,
            code_agent_count=code_agent_count,
            code_agent_codex_homes=self.code_agent_codex_homes,
            workspaces_dir=workspaces_dir,
        )
        resolved: list[CodeAgentAssignment] = []
        for assignment in assignments:
            session = state.get("agent_sessions", {}).get(assignment.agent_id, {})
            codex_home = session.get("codex_home", assignment.codex_home)
            if codex_home == assignment.codex_home:
                resolved.append(assignment)
            else:
                resolved.append(
                    CodeAgentAssignment(
                    agent_id=assignment.agent_id,
                    codex_home=codex_home,
                    workspace_dir=assignment.workspace_dir,
                    tasks=assignment.tasks,
                    )
                )
        return resolved

    def _single_code_assignment(self, generated_app_dir: Path) -> CodeAgentAssignment:
        return CodeAgentAssignment(
            agent_id="code_1",
            codex_home=self.code_agent_codex_homes[0] if self.code_agent_codex_homes else self.developer_codex_home,
            workspace_dir=generated_app_dir,
            tasks=[
                {
                    "id": "T1",
                    "title": "Complete application implementation",
                    "summary": "Implement the approved app end to end in the generated_app directory.",
                    "dependencies": [],
                    "owned_paths": ["."],
                    "allowed_shared_paths": [],
                    "forbidden_paths": ["contract/", "runs/", "agent_workspaces/", "integration/"],
                    "interfaces": [
                        "Create the complete runnable app.",
                        "Create README.md with setup, run, and test instructions.",
                        "Create codex_app_manifest.json with at least one safe non-interactive check.",
                    ],
                    "acceptance_criteria": [
                        "The app satisfies the approved plan.",
                        "The app can be checked by the local QA harness without human input when practical.",
                    ],
                }
            ],
        )

    def _single_code_context(self, final_plan: str, route: RoutingDecision) -> str:
        return "\n\n".join(
            [
                "# Approved Plan",
                final_plan.strip() or "(missing final plan)",
                "# Routing",
                f"- mode: {route.mode}",
                f"- reason: {route.reason}",
                "# App Manifest Requirement",
                (
                    "Create `codex_app_manifest.json` in the app root. It must describe safe local "
                    "setup, test, smoke, server, or browser checks using JSON array commands, not shell strings. "
                    "Prefer checks that need no network and no human input."
                ),
            ]
        )

    def _route_for_state(self, state: dict[str, Any]) -> RoutingDecision:
        payload = state.get("routing")
        if isinstance(payload, dict):
            return RoutingDecision.from_dict(payload)
        return decide_route(
            str(state.get("user_request", "")),
            requested_mode=self.routing_mode,
            max_code_agent_count=self.code_agent_count,
            max_qa_agent_count=self.qa_agent_count,
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
        route_path = store.write_artifact(
            "route.json",
            _json_text(payload),
            artifact_name="route",
        )
        store.append_event("routing_decision", "system", f"Selected {route.mode} route", {"path": store.to_relative(route_path), **payload})

    def _prepare_reference_profiles(self, run_dir: Path, store: StateStore) -> None:
        if not self.reference_pack_enabled:
            return
        prepared = prepare_reference_profiles(self.project_root, run_dir, self.agent_references)
        payload = {
            "enabled": True,
            "profiles": prepared.role_profiles,
            "packs": {
                pack_id: store.to_relative(pack.run_pack_dir)
                for pack_id, pack in prepared.packs.items()
            },
            "missing_profiles": prepared.missing_profiles,
        }
        profiles_path = store.write_artifact(
            "reference_profiles.json",
            _json_text(payload),
            artifact_name="reference_profiles",
        )
        for pack_id, pack in prepared.packs.items():
            store.record_artifact(f"reference_pack_{pack_id}", pack.run_pack_dir)
            for role, path in pack.role_files.items():
                store.record_artifact(f"reference_{pack_id}_{role}", path)
        if prepared.missing_profiles:
            store.append_event(
                "reference_profiles_missing",
                "system",
                "One or more reference profiles could not be loaded",
                {"path": store.to_relative(profiles_path), **payload},
            )
            return
        store.append_event(
            "reference_profiles_prepared",
            "system",
            "Reference profiles copied into run",
            {"path": store.to_relative(profiles_path), **payload},
        )

    def _reference_for_role(self, run_dir: Path, role: str) -> str:
        if not self.reference_pack_enabled:
            return ""
        return load_profile_reference_text(run_dir, self.agent_references.get(role, ""))

    def _resolve_fix_targets(self, assignments: list[CodeAgentAssignment], qa_result: QAResult) -> list[str]:
        valid_code_agents = {assignment.agent_id for assignment in assignments}
        targets = [owner for owner in qa_result.suspected_owners if owner in valid_code_agents or owner == "integrator"]
        if targets:
            return _merge_unique(targets)

        path_targets: list[str] = []
        for affected_path in qa_result.affected_paths:
            owner = _owner_for_path(assignments, affected_path)
            if owner:
                path_targets.append(owner)

        if path_targets:
            return _merge_unique(path_targets)
        return ["integrator"]


    async def _call_codex(self, func: Any, *, session_id: str | None) -> CodexResult:
        try:
            return await asyncio.to_thread(func, session_id)
        except CodexExecutionError:
            if not session_id:
                raise
            return await asyncio.to_thread(func, None)

    async def _publish_qa_review(
        self,
        channel: discord.abc.Messageable,
        *,
        run_id: str,
        run_dir: Path,
        generated_app_dir: Path,
        qa_result: QAResult,
        requester_id: int,
    ) -> None:
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
        await self.reporter.send_files(
            channel,
            title=f"{run_id} QA Screenshot",
            paths=qa_result.screenshots,
        )

        view = QAApprovalView(engine=self, run_id=run_id, requester_id=requester_id)
        review_message = await channel.send(
            f"<@{requester_id}> Review QA artifacts for run `{run_id}`.",
            view=view,
        )
        StateStore(run_dir).update_discord(qa_approval_message_id=str(review_message.id))

    async def _run_qa_cycle(
        self,
        run_dir: Path,
        generated_app_dir: Path,
        attempt_name: str,
        attempt_index: int,
    ) -> QAResult:
        store = StateStore(run_dir)
        mechanical_result = await asyncio.to_thread(
            self._run_mechanical_qa,
            run_dir,
            generated_app_dir,
            attempt_name,
            attempt_index,
        )
        self._record_qa_result(store, mechanical_result)
        route = self._route_for_state(store.load())
        if route.qa_agent_count <= 0:
            return mechanical_result
        qa_result = await self._run_llm_qa_agents(
            run_dir=run_dir,
            generated_app_dir=generated_app_dir,
            mechanical_result=mechanical_result,
            attempt_index=attempt_index,
        )
        self._record_qa_result(store, qa_result)
        return qa_result

    async def _run_llm_qa_agents(
        self,
        *,
        run_dir: Path,
        generated_app_dir: Path,
        mechanical_result: QAResult,
        attempt_index: int,
    ) -> QAResult:
        store = StateStore(run_dir)
        state = store.load()
        route = self._route_for_state(state)
        user_request = state["user_request"]
        contract_dir = run_dir / state.get("artifacts", {}).get("contract_dir", "contract")
        contract_bundle = render_contract_bundle(contract_dir) if contract_dir.exists() else ""
        generated_app_listing = list_workspace_files(generated_app_dir)
        logs_dir = create_logs_dir(run_dir)
        attempt_dir = run_dir / "qa" / f"attempt_{attempt_index:02d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)

        async def run_one(index: int) -> tuple[str, str | None, CodexResult]:
            agent_id = f"qa_{index}"
            codex_home = self.qa_agent_codex_homes[(index - 1) % len(self.qa_agent_codex_homes)] if self.qa_agent_codex_homes else None
            agent = QAAgent(
                agent_id=agent_id,
                codex_home=codex_home,
                logs_dir=logs_dir,
                timeout=self.codex_timeout_seconds,
                model=self.codex_model,
                reasoning_effort=self.codex_reasoning_effort,
                reference_markdown=self._reference_for_role(run_dir, "qa_agent"),
            )
            result = await self._call_codex(
                lambda session_id: agent.review_result(
                    user_request,
                    contract_bundle,
                    generated_app_listing,
                    mechanical_result.report_markdown,
                    mechanical_result.screenshots,
                    run_dir,
                    session_id=session_id,
                ),
                session_id=store.get_agent_session_id(agent_id),
            )
            return agent_id, codex_home, result

        qa_agent_count = route.qa_agent_count
        reviews = await asyncio.gather(*[run_one(index) for index in range(1, qa_agent_count + 1)])
        review_sections: list[str] = []
        failed_reviews: list[str] = []
        artifact_paths = list(mechanical_result.artifact_paths)

        for agent_id, codex_home, result in reviews:
            review_path = store.write_artifact(
                f"qa/attempt_{attempt_index:02d}/{agent_id}_review.md",
                result.stdout,
                artifact_name=f"{agent_id}_review",
            )
            artifact_paths.append(review_path)
            status = _parse_qa_status(result.stdout)
            affected_paths = _extract_affected_paths(result.stdout)
            suspected_owners = _extract_suspected_owners(result.stdout)
            if status != "PASS":
                failed_reviews.append(f"{agent_id}: {status}")
            store.update_agent_session(
                agent_id,
                session_id=result.session_id,
                codex_home=codex_home,
                model=result.model,
                reasoning_effort=result.reasoning_effort,
                last_step=f"review_attempt_{attempt_index}",
            )
            store.append_event(
                "agent_output",
                agent_id,
                "QA Agent review completed",
                {
                    "path": store.to_relative(review_path),
                    "qa_status": status,
                    "affected_paths": affected_paths,
                    "suspected_owners": suspected_owners,
                    **self._session_event_data(result),
                },
            )
            store.append_transcript(f"{agent_id} Review", result.stdout)
            review_sections.append(f"### {agent_id} Review\n\n{result.stdout.strip()}")

        llm_ok = not failed_reviews
        ok = mechanical_result.ok and llm_ok
        llm_error_log = "\n".join(failed_reviews)
        error_log = "\n\n".join(part for part in [mechanical_result.error_log, llm_error_log] if part)
        affected_paths = _merge_unique(
            [*mechanical_result.affected_paths, *[path for section in review_sections for path in _extract_affected_paths(section)]]
        )
        suspected_owners = _merge_unique(
            [*mechanical_result.suspected_owners, *[owner for section in review_sections for owner in _extract_suspected_owners(section)]]
        )
        status = "PASS" if ok else "FAIL"
        report = "\n".join(
            [
                mechanical_result.report_markdown.strip(),
                "",
                "## Codex QA Agent Reviews",
                "",
                f"- Status: {status}",
                f"- QA agent count: {qa_agent_count}",
                f"- Blocking reviews: {', '.join(failed_reviews) if failed_reviews else 'None'}",
                "",
                "\n\n".join(review_sections),
                "",
            ]
        )
        mechanical_result.report_path.write_text(report if report.endswith("\n") else f"{report}\n", encoding="utf-8")
        return QAResult(
            ok=ok,
            checked_files=mechanical_result.checked_files,
            error_log=error_log,
            report_path=mechanical_result.report_path,
            report_markdown=report,
            screenshots=mechanical_result.screenshots,
            artifact_paths=artifact_paths,
            executable_status=mechanical_result.executable_status,
            executable_app_type=mechanical_result.executable_app_type,
            affected_paths=affected_paths,
            suspected_owners=suspected_owners,
        )

    def _run_mechanical_qa(
        self,
        run_dir: Path,
        generated_app_dir: Path,
        attempt_name: str,
        attempt_index: int,
    ) -> QAResult:
        qa_attempt_dir = run_dir / "qa" / f"attempt_{attempt_index:02d}"
        qa_attempt_dir.mkdir(parents=True, exist_ok=True)
        syntax_result = run_python_syntax_check(
            generated_app_dir,
            qa_attempt_dir / "syntax_report.md",
            attempt_name=f"{attempt_name} syntax check",
            fail_on_missing_python=False,
        )
        if self.executable_qa_enabled:
            executable_result = run_executable_qa(
                generated_app_dir,
                qa_attempt_dir,
                attempt_name=f"{attempt_name} executable probe",
                timeout=self.executable_qa_timeout_seconds,
                allow_local_commands=self.executable_qa_allow_local_commands,
            )
        else:
            executable_result = _disabled_executable_qa_result(generated_app_dir, qa_attempt_dir, attempt_name)

        return combine_mechanical_qa_results(
            syntax_result=syntax_result,
            executable_result=executable_result,
            report_path=run_dir / "qa_report.md",
            attempt_name=attempt_name,
        )

    def _record_qa_result(self, store: StateStore, qa_result: QAResult) -> None:
        store.record_artifact("qa_report", qa_result.report_path)
        for index, screenshot_path in enumerate(qa_result.screenshots, start=1):
            store.record_artifact(f"qa_screenshot_{index}", screenshot_path)
        for index, artifact_path in enumerate(qa_result.artifact_paths, start=1):
            store.record_artifact(f"qa_artifact_{index}", artifact_path)

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
        model = result.model or "default"
        reasoning = result.reasoning_effort or "default"
        return (
            f"`{run_id}` {agent_label} session: `{session}` | resumed: `{resumed}` "
            f"| model: `{model}` | reasoning: `{reasoning}`"
        )

    def _session_event_data(self, result: CodexResult) -> dict[str, str | None]:
        return {
            "session_id": result.session_id,
            "resumed_session_id": result.resumed_session_id,
            "model": result.model,
            "reasoning_effort": result.reasoning_effort,
        }


def _short_session_id(session_id: str | None) -> str:
    if not session_id:
        return "none"
    return f"{session_id[:8]}..."


def _parse_qa_status(output: str) -> str:
    for line in output.splitlines()[:12]:
        normalized = line.strip().upper()
        if normalized.startswith("QA_STATUS:"):
            value = normalized.split(":", 1)[1].strip()
            if value.startswith("PASS"):
                return "PASS"
            if value.startswith("FAIL"):
                return "FAIL"
    return "UNKNOWN"


def _extract_affected_paths(output: str) -> list[str]:
    return _extract_bullets_after_heading(output, "affected paths")


def _extract_suspected_owners(output: str) -> list[str]:
    values: list[str] = []
    for item in _extract_bullets_after_heading(output, "suspected owners"):
        for part in re.split(r"[,/]", item):
            owner = part.strip().strip("`").lower()
            if owner in {"none", "n/a", "unknown", ""}:
                continue
            if owner == "integration":
                owner = "integrator"
            if owner == "all":
                values.append("integrator")
                continue
            code_match = re.fullmatch(r"code[_\s-]?(\d+)", owner)
            if code_match:
                values.append(f"code_{code_match.group(1)}")
                continue
            if owner == "integrator" or re.fullmatch(r"code_\d+", owner):
                values.append(owner)
    return _merge_unique(values)


def _extract_bullets_after_heading(output: str, heading: str) -> list[str]:
    values: list[str] = []
    in_section = False
    wanted = heading.lower().rstrip(":")
    for line in output.splitlines():
        stripped = line.strip()
        normalized = stripped.lower().rstrip(":")
        if normalized == wanted:
            in_section = True
            continue
        if in_section and stripped and not stripped.startswith("-") and stripped.endswith(":"):
            break
        if not in_section:
            continue
        if not stripped.startswith("-"):
            continue
        value = stripped[1:].strip().strip("`")
        if value.lower() in {"none", "n/a", "unknown", ""}:
            continue
        values.append(value.replace("\\", "/"))
    return _merge_unique(values)


def _owner_for_path(assignments: list[CodeAgentAssignment], affected_path: str) -> str | None:
    normalized = affected_path.strip().strip("`").replace("\\", "/")
    if not normalized or normalized.lower() in {"none", "unknown"}:
        return None
    if normalized.startswith("generated_app/"):
        normalized = normalized.removeprefix("generated_app/")
    if normalized.startswith("integration/merged_app/"):
        normalized = normalized.removeprefix("integration/merged_app/")

    shared_match = False
    for assignment in assignments:
        for task in assignment.tasks:
            owned_paths = [path.rstrip("/") for path in _task_paths(task, "owned_paths")]
            if any(normalized == path or normalized.startswith(f"{path}/") for path in owned_paths):
                return assignment.agent_id
            shared_paths = [path.rstrip("/") for path in _task_paths(task, "allowed_shared_paths")]
            if any(normalized == path or normalized.startswith(f"{path}/") for path in shared_paths):
                shared_match = True
    if shared_match:
        return "integrator"
    return None


def _task_paths(task: dict[str, Any], key: str) -> list[str]:
    value = task.get(key, [])
    if not isinstance(value, list):
        return []
    return [str(item).strip().replace("\\", "/") for item in value if str(item).strip()]


def _merge_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _disabled_executable_qa_result(app_dir: Path, qa_dir: Path, attempt_name: str) -> ExecutableQAResult:
    report_path = qa_dir / "executable_qa_report.md"
    report = "\n".join(
        [
            f"## {attempt_name} executable probe",
            "",
            "- Status: SKIP",
            f"- App directory: `{app_dir}`",
            "- App type: `disabled`",
            "",
            "Executable QA is disabled by EXECUTABLE_QA_ENABLED=0.",
            "",
        ]
    )
    report_path.write_text(report, encoding="utf-8")
    return ExecutableQAResult(
        ok=False,
        status="SKIP",
        app_type="disabled",
        report_path=report_path,
        report_markdown=report,
    )
