"""Codex-backed agents for planning, debate, and app generation."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent
from typing import Callable

from codex_runner import CodexProcessHandle, CodexResult, run_codex, run_codex_result, run_codex_result_async
from prompt_templates import load_agent_system_prompt


def _reference_block(reference_markdown: str | None) -> str:
    if not reference_markdown or not reference_markdown.strip():
        return ""
    return dedent(
        f"""

        Additional role reference guidance:
        {reference_markdown.strip()}

        Treat the role reference as advisory. The current task instructions,
        file ownership rules, and safety constraints take precedence.
        """
    ).strip()


def _system_prompt(agent_id: str, override: str | None = None) -> str:
    if override and override.strip():
        return override.strip()
    return load_agent_system_prompt(agent_id=agent_id)


def _compact_json_for_prompt(value: str) -> str:
    try:
        return json.dumps(json.loads(value), ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return value.strip()


class PlannerAgent:
    """Backward-compatible single planner used by the CLI MVP."""

    def __init__(
        self,
        *,
        codex_home: str | None = None,
        logs_dir: Path | None = None,
        timeout: int = 600,
        model: str | None = None,
        reasoning_effort: str | None = None,
        system_prompt: str | None = None,
        reference_markdown: str | None = None,
    ) -> None:
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.system_prompt = system_prompt
        self.reference_markdown = reference_markdown

    def create_plan(self, user_request: str, workdir: Path) -> str:
        return PlannerAgentA(
            codex_home=self.codex_home,
            logs_dir=self.logs_dir,
            timeout=self.timeout,
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            system_prompt=self.system_prompt,
            reference_markdown=self.reference_markdown,
        ).create_initial_plan(user_request, workdir).stdout


class PlannerAgentA:
    """Primary planner that drafts and revises the final plan."""

    def __init__(
        self,
        *,
        codex_home: str | None = None,
        logs_dir: Path | None = None,
        timeout: int = 600,
        model: str | None = None,
        reasoning_effort: str | None = None,
        system_prompt: str | None = None,
        reference_markdown: str | None = None,
    ) -> None:
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.system_prompt = system_prompt
        self.reference_markdown = reference_markdown

    def create_initial_plan(
        self,
        user_request: str,
        workdir: Path,
        *,
        session_id: str | None = None,
    ) -> CodexResult:
        prompt = self._initial_plan_prompt(user_request)
        return self._run(prompt, workdir, session_id=session_id, label="planner_a_draft")

    async def create_initial_plan_async(
        self,
        user_request: str,
        workdir: Path,
        *,
        session_id: str | None = None,
        process_started: Callable[[CodexProcessHandle], None] | None = None,
    ) -> CodexResult:
        prompt = self._initial_plan_prompt(user_request)
        return await self._run_async(
            prompt,
            workdir,
            session_id=session_id,
            label="planner_a_draft",
            process_started=process_started,
        )

    def revise_final_plan(
        self,
        user_request: str,
        previous_plan: str,
        review: str,
        workdir: Path,
        *,
        user_feedback: str | None = None,
        session_id: str | None = None,
    ) -> CodexResult:
        prompt = self._final_plan_prompt(
            user_request,
            previous_plan,
            review,
            user_feedback=user_feedback,
        )
        return self._run(prompt, workdir, session_id=session_id, label="planner_a_final")

    async def revise_final_plan_async(
        self,
        user_request: str,
        previous_plan: str,
        review: str,
        workdir: Path,
        *,
        user_feedback: str | None = None,
        session_id: str | None = None,
        process_started: Callable[[CodexProcessHandle], None] | None = None,
    ) -> CodexResult:
        prompt = self._final_plan_prompt(
            user_request,
            previous_plan,
            review,
            user_feedback=user_feedback,
        )
        return await self._run_async(
            prompt,
            workdir,
            session_id=session_id,
            label="planner_a_final",
            process_started=process_started,
        )

    def _initial_plan_prompt(self, user_request: str) -> str:
        return dedent(
            f"""
            {_system_prompt("planner_a", self.system_prompt)}

            Produce the initial planning document now.

            {_reference_block(self.reference_markdown)}

            User request:
            {user_request}

            Create the initial planning document according to your system prompt.
            """
        ).strip()

    def _final_plan_prompt(
        self,
        user_request: str,
        previous_plan: str,
        review: str,
        *,
        user_feedback: str | None,
    ) -> str:
        feedback_block = user_feedback or "(no additional user feedback)"
        return dedent(
            f"""
            {_system_prompt("planner_a", self.system_prompt)}

            Revise the plan into the current final planning document.
            Use your existing session context if available.

            {_reference_block(self.reference_markdown)}

            User request:
            {user_request}

            Current or previous plan:
            {previous_plan}

            Planner Agent B review:
            {review}

            User feedback:
            {feedback_block}

            Create the final planning document according to your system prompt.
            """
        ).strip()

    def _run(
        self,
        prompt: str,
        workdir: Path,
        *,
        session_id: str | None,
        label: str,
    ) -> CodexResult:
        return run_codex_result(
            prompt,
            workdir=workdir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label=label,
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
        )

    async def _run_async(
        self,
        prompt: str,
        workdir: Path,
        *,
        session_id: str | None,
        label: str,
        process_started: Callable[[CodexProcessHandle], None] | None = None,
    ) -> CodexResult:
        return await run_codex_result_async(
            prompt,
            workdir=workdir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label=label,
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            process_started=process_started,
        )


class PlannerAgentB:
    """Reviewer planner that critiques scope, intent fit, and risk."""

    def __init__(
        self,
        *,
        codex_home: str | None = None,
        logs_dir: Path | None = None,
        timeout: int = 600,
        model: str | None = None,
        reasoning_effort: str | None = None,
        system_prompt: str | None = None,
        reference_markdown: str | None = None,
    ) -> None:
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.system_prompt = system_prompt
        self.reference_markdown = reference_markdown

    def review_plan(
        self,
        user_request: str,
        plan_markdown: str,
        workdir: Path,
        *,
        user_feedback: str | None = None,
        session_id: str | None = None,
    ) -> CodexResult:
        prompt = self._review_prompt(user_request, plan_markdown, user_feedback=user_feedback)
        return run_codex_result(
            prompt,
            workdir=workdir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label="planner_b_review",
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
        )

    async def review_plan_async(
        self,
        user_request: str,
        plan_markdown: str,
        workdir: Path,
        *,
        user_feedback: str | None = None,
        session_id: str | None = None,
        process_started: Callable[[CodexProcessHandle], None] | None = None,
    ) -> CodexResult:
        prompt = self._review_prompt(user_request, plan_markdown, user_feedback=user_feedback)
        return await run_codex_result_async(
            prompt,
            workdir=workdir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label="planner_b_review",
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            process_started=process_started,
        )

    def _review_prompt(
        self,
        user_request: str,
        plan_markdown: str,
        *,
        user_feedback: str | None,
    ) -> str:
        feedback_block = user_feedback or "(no additional user feedback)"
        return dedent(
            f"""
            {_system_prompt("planner_b", self.system_prompt)}

            {_reference_block(self.reference_markdown)}

            User request:
            {user_request}

            Planner Agent A plan:
            {plan_markdown}

            User feedback, if any:
            {feedback_block}

            Review the plan according to your system prompt.
            """
        ).strip()


class ArchitectAgent:
    """Creates the contract bundle used to coordinate parallel implementation."""

    def __init__(
        self,
        *,
        codex_home: str | None = None,
        logs_dir: Path | None = None,
        timeout: int = 900,
        model: str | None = None,
        reasoning_effort: str | None = None,
        system_prompt: str | None = None,
        reference_markdown: str | None = None,
    ) -> None:
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.system_prompt = system_prompt
        self.reference_markdown = reference_markdown

    def create_contract_bundle_result(
        self,
        user_request: str,
        planner_a_draft: str,
        planner_b_review: str,
        final_plan: str,
        contract_dir: Path,
        *,
        session_id: str | None = None,
    ) -> CodexResult:
        prompt = self._contract_prompt(user_request, planner_a_draft, planner_b_review, final_plan)
        return run_codex_result(
            prompt,
            workdir=contract_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label="architect_contract",
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            require_writable=True,
        )

    async def create_contract_bundle_result_async(
        self,
        user_request: str,
        planner_a_draft: str,
        planner_b_review: str,
        final_plan: str,
        contract_dir: Path,
        *,
        session_id: str | None = None,
        process_started: Callable[[CodexProcessHandle], None] | None = None,
    ) -> CodexResult:
        prompt = self._contract_prompt(user_request, planner_a_draft, planner_b_review, final_plan)
        return await run_codex_result_async(
            prompt,
            workdir=contract_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label="architect_contract",
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            require_writable=True,
            process_started=process_started,
        )

    def _contract_prompt(
        self,
        user_request: str,
        planner_a_draft: str,
        planner_b_review: str,
        final_plan: str,
    ) -> str:
        return dedent(
            f"""
            {_system_prompt("architect", self.system_prompt)}

            {_reference_block(self.reference_markdown)}

            User request:
            {user_request}

            Planner A draft:
            {planner_a_draft}

            Planner B review:
            {planner_b_review}

            Approved final plan:
            {final_plan}

            Create the contract bundle according to your system prompt.
            """
        ).strip()


class ScaffoldAgent:
    """Creates the shared skeleton that code agents copy before parallel work."""

    def __init__(
        self,
        *,
        codex_home: str | None = None,
        logs_dir: Path | None = None,
        timeout: int = 900,
        model: str | None = None,
        reasoning_effort: str | None = None,
        system_prompt: str | None = None,
        reference_markdown: str | None = None,
    ) -> None:
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.system_prompt = system_prompt
        self.reference_markdown = reference_markdown

    def create_scaffold_result(
        self,
        user_request: str,
        contract_bundle: str,
        scaffold_dir: Path,
        *,
        session_id: str | None = None,
    ) -> CodexResult:
        prompt = self._scaffold_prompt(user_request, contract_bundle)
        return run_codex_result(
            prompt,
            workdir=scaffold_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label="scaffold",
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            require_writable=True,
        )

    async def create_scaffold_result_async(
        self,
        user_request: str,
        contract_bundle: str,
        scaffold_dir: Path,
        *,
        session_id: str | None = None,
        process_started: Callable[[CodexProcessHandle], None] | None = None,
    ) -> CodexResult:
        prompt = self._scaffold_prompt(user_request, contract_bundle)
        return await run_codex_result_async(
            prompt,
            workdir=scaffold_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label="scaffold",
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            require_writable=True,
            process_started=process_started,
        )

    def _scaffold_prompt(self, user_request: str, contract_bundle: str) -> str:
        return dedent(
            f"""
            {_system_prompt("scaffold", self.system_prompt)}

            {_reference_block(self.reference_markdown)}

            User request:
            {user_request}

            Contract bundle:
            {contract_bundle}

            Create the scaffold according to your system prompt.
            """
        ).strip()


class CodeAgent:
    """Implements one assigned task group inside an isolated workspace."""

    def __init__(
        self,
        *,
        agent_id: str,
        codex_home: str | None = None,
        logs_dir: Path | None = None,
        timeout: int = 900,
        model: str | None = None,
        reasoning_effort: str | None = None,
        system_prompt: str | None = None,
        reference_markdown: str | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.system_prompt = system_prompt
        self.reference_markdown = reference_markdown

    def implement_tasks_result(
        self,
        user_request: str,
        contract_bundle: str,
        assigned_tasks_json: str,
        workspace_dir: Path,
        *,
        session_id: str | None = None,
    ) -> CodexResult:
        prompt = self._implement_prompt(user_request, contract_bundle, assigned_tasks_json)
        return run_codex_result(
            prompt,
            workdir=workspace_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label=self.agent_id,
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            require_writable=True,
        )

    async def implement_tasks_result_async(
        self,
        user_request: str,
        contract_bundle: str,
        assigned_tasks_json: str,
        workspace_dir: Path,
        *,
        session_id: str | None = None,
        process_started: Callable[[CodexProcessHandle], None] | None = None,
    ) -> CodexResult:
        prompt = self._implement_prompt(user_request, contract_bundle, assigned_tasks_json)
        return await run_codex_result_async(
            prompt,
            workdir=workspace_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label=self.agent_id,
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            require_writable=True,
            process_started=process_started,
        )

    def _implement_prompt(self, user_request: str, contract_bundle: str, assigned_tasks_json: str) -> str:
        return dedent(
            f"""
            {_system_prompt(self.agent_id, self.system_prompt)}

            Agent id: {self.agent_id}

            {_reference_block(self.reference_markdown)}

            Original user request (highest priority):
            {user_request}

            Planning context:
            {contract_bundle}

            Workspace and ownership assignment:
            {_compact_json_for_prompt(assigned_tasks_json)}

            Build the best local result for the original request. Use the
            planning context as guidance and the assignment as workspace/path
            boundaries. When guidance would weaken the result, follow the user
            request and source-file evidence, then mention the deviation in
            your final notes.
            """
        ).strip()

    def fix_assigned_tasks_result(
        self,
        user_request: str,
        contract_bundle: str,
        assigned_tasks_json: str,
        qa_feedback: str,
        workspace_dir: Path,
        *,
        iteration: int,
        session_id: str | None = None,
    ) -> CodexResult:
        prompt = self._fix_prompt(user_request, contract_bundle, assigned_tasks_json, qa_feedback, iteration=iteration)
        return run_codex_result(
            prompt,
            workdir=workspace_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label=f"{self.agent_id}_fix_{iteration:02d}",
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            require_writable=True,
        )

    async def fix_assigned_tasks_result_async(
        self,
        user_request: str,
        contract_bundle: str,
        assigned_tasks_json: str,
        qa_feedback: str,
        workspace_dir: Path,
        *,
        iteration: int,
        session_id: str | None = None,
        process_started: Callable[[CodexProcessHandle], None] | None = None,
    ) -> CodexResult:
        prompt = self._fix_prompt(user_request, contract_bundle, assigned_tasks_json, qa_feedback, iteration=iteration)
        return await run_codex_result_async(
            prompt,
            workdir=workspace_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label=f"{self.agent_id}_fix_{iteration:02d}",
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            require_writable=True,
            process_started=process_started,
        )

    def _fix_prompt(
        self,
        user_request: str,
        contract_bundle: str,
        assigned_tasks_json: str,
        qa_feedback: str,
        *,
        iteration: int,
    ) -> str:
        return dedent(
            f"""
            {_system_prompt(self.agent_id, self.system_prompt)}

            Agent id: {self.agent_id}
            Continue this code-agent session.
            The integrated app failed QA or the user requested fixes. Resume your own work,
            inspect the feedback, and update only the files owned or allowed by your assignment.

            {_reference_block(self.reference_markdown)}

            Original user request (highest priority):
            {user_request}

            Planning context:
            {contract_bundle}

            Workspace and ownership assignment:
            {_compact_json_for_prompt(assigned_tasks_json)}

            QA/user feedback:
            {qa_feedback}

            Fix iteration: {iteration}

            Fix the assigned work while preserving the original user request.
            Use planning context and QA feedback as guidance, but follow
            source-file evidence when it would produce a better result.
            """
        ).strip()


class IntegratorAgent:
    """Merges parallel code-agent outputs into the final app."""

    def __init__(
        self,
        *,
        codex_home: str | None = None,
        logs_dir: Path | None = None,
        timeout: int = 900,
        model: str | None = None,
        reasoning_effort: str | None = None,
        system_prompt: str | None = None,
        reference_markdown: str | None = None,
    ) -> None:
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.system_prompt = system_prompt
        self.reference_markdown = reference_markdown

    def integrate_result(
        self,
        user_request: str,
        contract_bundle: str,
        assignment_summary: str,
        workspace_listing: str,
        run_dir: Path,
        *,
        session_id: str | None = None,
    ) -> CodexResult:
        prompt = self._integrate_prompt(user_request, contract_bundle, assignment_summary, workspace_listing)
        return run_codex_result(
            prompt,
            workdir=run_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label="integrator",
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            require_writable=True,
        )

    async def integrate_result_async(
        self,
        user_request: str,
        contract_bundle: str,
        assignment_summary: str,
        workspace_listing: str,
        run_dir: Path,
        *,
        session_id: str | None = None,
        process_started: Callable[[CodexProcessHandle], None] | None = None,
    ) -> CodexResult:
        prompt = self._integrate_prompt(user_request, contract_bundle, assignment_summary, workspace_listing)
        return await run_codex_result_async(
            prompt,
            workdir=run_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label="integrator",
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            require_writable=True,
            process_started=process_started,
        )

    def _integrate_prompt(
        self,
        user_request: str,
        contract_bundle: str,
        assignment_summary: str,
        workspace_listing: str,
    ) -> str:
        return dedent(
            f"""
            {_system_prompt("integrator", self.system_prompt)}

            {_reference_block(self.reference_markdown)}

            User request:
            {user_request}

            Contract bundle:
            {contract_bundle}

            Assignment summary:
            {assignment_summary}

            Workspace file listing:
            {workspace_listing}

            Integrate the final app according to your system prompt.
            """
        ).strip()

    def repair_integration_result(
        self,
        user_request: str,
        contract_bundle: str,
        assignment_summary: str,
        workspace_listing: str,
        qa_feedback: str,
        run_dir: Path,
        *,
        iteration: int,
        session_id: str | None = None,
    ) -> CodexResult:
        prompt = self._repair_prompt(
            user_request,
            contract_bundle,
            assignment_summary,
            workspace_listing,
            qa_feedback,
            iteration=iteration,
        )
        return run_codex_result(
            prompt,
            workdir=run_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label=f"integrator_fix_{iteration:02d}",
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            require_writable=True,
        )

    async def repair_integration_result_async(
        self,
        user_request: str,
        contract_bundle: str,
        assignment_summary: str,
        workspace_listing: str,
        qa_feedback: str,
        run_dir: Path,
        *,
        iteration: int,
        session_id: str | None = None,
        process_started: Callable[[CodexProcessHandle], None] | None = None,
    ) -> CodexResult:
        prompt = self._repair_prompt(
            user_request,
            contract_bundle,
            assignment_summary,
            workspace_listing,
            qa_feedback,
            iteration=iteration,
        )
        return await run_codex_result_async(
            prompt,
            workdir=run_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label=f"integrator_fix_{iteration:02d}",
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            require_writable=True,
            process_started=process_started,
        )

    def _repair_prompt(
        self,
        user_request: str,
        contract_bundle: str,
        assignment_summary: str,
        workspace_listing: str,
        qa_feedback: str,
        *,
        iteration: int,
    ) -> str:
        return dedent(
            f"""
            {_system_prompt("integrator", self.system_prompt)}

            Continue this integrator session.
            The integrated app failed QA or the user requested fixes.

            {_reference_block(self.reference_markdown)}

            User request:
            {user_request}

            Contract bundle:
            {contract_bundle}

            Assignment summary:
            {assignment_summary}

            Workspace file listing:
            {workspace_listing}

            QA/user feedback:
            {qa_feedback}

            Fix iteration: {iteration}

            Repair the integration according to your system prompt.
            """
        ).strip()


class QAAgent:
    """Reviews mechanical QA artifacts and screenshots against the contract."""

    def __init__(
        self,
        *,
        agent_id: str,
        codex_home: str | None = None,
        logs_dir: Path | None = None,
        timeout: int = 900,
        model: str | None = None,
        reasoning_effort: str | None = None,
        system_prompt: str | None = None,
        reference_markdown: str | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.system_prompt = system_prompt
        self.reference_markdown = reference_markdown

    def review_result(
        self,
        user_request: str,
        contract_bundle: str,
        generated_app_listing: str,
        qa_report: str,
        screenshot_paths: list[Path],
        run_dir: Path,
        *,
        session_id: str | None = None,
    ) -> CodexResult:
        prompt = self._review_prompt(user_request, contract_bundle, generated_app_listing, qa_report, screenshot_paths)
        return run_codex_result(
            prompt,
            workdir=run_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label=f"{self.agent_id}_review",
            session_id=session_id,
            sandbox="read-only",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            image_paths=screenshot_paths,
        )

    async def review_result_async(
        self,
        user_request: str,
        contract_bundle: str,
        generated_app_listing: str,
        qa_report: str,
        screenshot_paths: list[Path],
        run_dir: Path,
        *,
        session_id: str | None = None,
        process_started: Callable[[CodexProcessHandle], None] | None = None,
    ) -> CodexResult:
        prompt = self._review_prompt(user_request, contract_bundle, generated_app_listing, qa_report, screenshot_paths)
        return await run_codex_result_async(
            prompt,
            workdir=run_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label=f"{self.agent_id}_review",
            session_id=session_id,
            sandbox="read-only",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            image_paths=screenshot_paths,
            process_started=process_started,
        )

    async def plan_scenarios_async(
        self,
        user_request: str,
        contract_bundle: str,
        generated_app_listing: str,
        run_dir: Path,
        *,
        session_id: str | None = None,
        process_started: Callable[[CodexProcessHandle], None] | None = None,
    ) -> CodexResult:
        prompt = self._scenario_plan_prompt(user_request, contract_bundle, generated_app_listing)
        return await run_codex_result_async(
            prompt,
            workdir=run_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label=f"{self.agent_id}_scenario_plan",
            session_id=session_id,
            sandbox="read-only",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            process_started=process_started,
        )

    async def run_workspace_qa_async(
        self,
        user_request: str,
        contract_bundle: str,
        generated_app_listing: str,
        mechanical_qa_report: str,
        qa_workspace_dir: Path,
        *,
        session_id: str | None = None,
        process_started: Callable[[CodexProcessHandle], None] | None = None,
        image_paths: list[Path] | None = None,
    ) -> CodexResult:
        prompt = self._workspace_qa_prompt(
            user_request,
            contract_bundle,
            generated_app_listing,
            mechanical_qa_report,
        )
        return await run_codex_result_async(
            prompt,
            workdir=qa_workspace_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label=f"{self.agent_id}_workspace_qa",
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            image_paths=image_paths or [],
            require_writable=True,
            process_started=process_started,
        )

    async def run_workspace_qa_followup_async(
        self,
        qa_workspace_dir: Path,
        host_evidence_summary: str,
        *,
        session_id: str | None = None,
        process_started: Callable[[CodexProcessHandle], None] | None = None,
        image_paths: list[Path] | None = None,
    ) -> CodexResult:
        prompt = self._workspace_qa_followup_prompt(host_evidence_summary)
        return await run_codex_result_async(
            prompt,
            workdir=qa_workspace_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label=f"{self.agent_id}_workspace_qa_host_followup",
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            image_paths=image_paths or [],
            require_writable=True,
            process_started=process_started,
        )

    def _scenario_plan_prompt(
        self,
        user_request: str,
        contract_bundle: str,
        generated_app_listing: str,
    ) -> str:
        return dedent(
            f"""
            {_system_prompt(self.agent_id, self.system_prompt)}

            Agent id: {self.agent_id}

            {_reference_block(self.reference_markdown)}

            You are starting the QA phase. First, create a deterministic browser
            QA scenario plan for the mechanical QA runner. Do not make a final
            PASS/FAIL judgment yet.

            User request:
            {user_request}

            Contract bundle:
            {contract_bundle}

            Generated app listing:
            {generated_app_listing}

            Read relevant generated app files when useful. On Windows, always
            read text as UTF-8, for example with Python `Path(...).read_text(encoding="utf-8")`
            or PowerShell `Get-Content -Encoding UTF8`.

            Produce the legacy browser scenario plan according to your system prompt.
            """
        ).strip()

    def _workspace_qa_prompt(
        self,
        user_request: str,
        contract_bundle: str,
        generated_app_listing: str,
        mechanical_qa_report: str,
    ) -> str:
        return dedent(
            f"""
            {_system_prompt(self.agent_id, self.system_prompt)}

            Agent id: {self.agent_id}

            {_reference_block(self.reference_markdown)}

            You are now running autonomous QA inside the dedicated QA workspace.
            Use the workspace layout, evidence requirements, browser action JSON
            schema, verdict rules, and final response format from your system prompt.

            User request:
            {user_request}

            Contract bundle:
            {contract_bundle}

            Generated app listing:
            {generated_app_listing}

            QA baseline/mechanical report:
            {mechanical_qa_report}

            Perform the QA review now and write the required evidence files.
            """
        ).strip()

    def _workspace_qa_followup_prompt(self, host_evidence_summary: str) -> str:
        return dedent(
            f"""
            Host browser evidence has been collected by Orchestra outside the Codex
            Windows sandbox. Continue the same QA review from the current workspace
            according to your system prompt.

            Host browser evidence summary:
            {host_evidence_summary}

            Review the evidence, update the required QA files, and print the
            required final response.
            """
        ).strip()

    def _review_prompt(
        self,
        user_request: str,
        contract_bundle: str,
        generated_app_listing: str,
        qa_report: str,
        screenshot_paths: list[Path],
    ) -> str:
        screenshot_list = "\n".join(f"- {path}" for path in screenshot_paths) or "- None"
        return dedent(
            f"""
            {_system_prompt(self.agent_id, self.system_prompt)}

            Agent id: {self.agent_id}

            {_reference_block(self.reference_markdown)}

            User request:
            {user_request}

            Contract bundle:
            {contract_bundle}

            Generated app listing:
            {generated_app_listing}

            Mechanical QA report:
            {qa_report}

            Screenshot paths attached to this review:
            {screenshot_list}

            Review the implementation evidence according to your system prompt
            and use the legacy review output format defined there.
            """
        ).strip()


class DeveloperAgent:
    """Legacy single-agent app generator kept for the original CLI path."""

    def __init__(
        self,
        *,
        codex_home: str | None = None,
        logs_dir: Path | None = None,
        timeout: int = 900,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort

    def create_app(self, user_request: str, plan_markdown: str, app_dir: Path) -> str:
        return self.create_app_result(user_request, plan_markdown, app_dir).stdout

    def create_app_result(
        self,
        user_request: str,
        plan_markdown: str,
        app_dir: Path,
        *,
        session_id: str | None = None,
    ) -> CodexResult:
        prompt = dedent(
            f"""
            {_system_prompt("developer")}

            User request:
            {user_request}

            Approved plan:
            {plan_markdown}

            Create the app according to your system prompt.
            """
        ).strip()

        return run_codex_result(
            prompt,
            workdir=app_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label="developer_initial",
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            require_writable=True,
        )

    def fix_app(
        self,
        user_request: str,
        plan_markdown: str,
        app_dir: Path,
        error_log: str,
        *,
        iteration: int,
    ) -> str:
        return self.fix_app_result(
            user_request,
            plan_markdown,
            app_dir,
            error_log,
            iteration=iteration,
        ).stdout

    def fix_app_result(
        self,
        user_request: str,
        plan_markdown: str,
        app_dir: Path,
        error_log: str,
        *,
        iteration: int,
        session_id: str | None = None,
    ) -> CodexResult:
        prompt = dedent(
            f"""
            {_system_prompt("developer")}

            Continue as Developer Agent.
            The generated app failed validation.

            User request:
            {user_request}

            Approved plan:
            {plan_markdown}

            Validation error log:
            {error_log}

            Fix attempt: {iteration}

            Fix the app according to your system prompt.
            """
        ).strip()

        return run_codex_result(
            prompt,
            workdir=app_dir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label=f"developer_fix_{iteration:02d}",
            session_id=session_id,
            sandbox="workspace-write",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            require_writable=True,
        )
