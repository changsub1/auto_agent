"""Codex-backed agents for planning, debate, and app generation."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Callable

from codex_runner import CodexProcessHandle, CodexResult, run_codex, run_codex_result, run_codex_result_async


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


MANIFEST_CONTRACT_NOTE = (
    "Final runnable outputs must include codex_app_manifest.json. "
    "Follow docs/CODEX_APP_MANIFEST.md. "
    "Commands must be JSON arrays, not shell strings."
)


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
        reference_markdown: str | None = None,
    ) -> None:
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.reference_markdown = reference_markdown

    def create_plan(self, user_request: str, workdir: Path) -> str:
        return PlannerAgentA(
            codex_home=self.codex_home,
            logs_dir=self.logs_dir,
            timeout=self.timeout,
            model=self.model,
            reasoning_effort=self.reasoning_effort,
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
        reference_markdown: str | None = None,
    ) -> None:
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort
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
            You are Planner Agent A in a Codex CLI multi-agent development workflow.
            Produce the initial planning document now. Do not ask follow-up questions.
            Do not reply with acknowledgements.

            {_reference_block(self.reference_markdown)}

            User request:
            {user_request}

            Create a concise Markdown plan in the user's language when practical.
            Include these sections:
            1. Service purpose
            2. Core features, limited to 2 or 3
            3. User inputs
            4. System outputs
            5. Screen flow or user flow
            6. Files to generate
            7. Implementation constraints
            8. Acceptance criteria

            Constraints:
            - Keep the app small and executable.
            - Choose the simplest local implementation stack that fits the user request.
            - If the user did not specify a stack, pick one and state why.
            - Prefer standard project conventions for the chosen stack.
            - Avoid external APIs.
            - Avoid storing personal information.
            - Keep dependencies minimal.
            - Include the expected runtime, entrypoint, run command, and verification approach.

            Start the response with "# Planner A Draft".
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
            Continue as Planner Agent A.
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

            Requirements:
            - Resolve the review comments.
            - Keep the scope realistic for a small executable local MVP.
            - Preserve or clearly justify the chosen language, framework, and runtime.
            - Mention any explicit tradeoffs.
            - Do not ask follow-up questions.
            - Return only the final Markdown plan.

            Start the response with "# Final Plan".
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
        reference_markdown: str | None = None,
    ) -> None:
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort
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
            You are Planner Agent B in a Codex CLI multi-agent development workflow.
            Review Planner Agent A's plan against the user's request.
            Do not rewrite the full plan. Provide focused review comments.

            {_reference_block(self.reference_markdown)}

            User request:
            {user_request}

            Planner Agent A plan:
            {plan_markdown}

            User feedback, if any:
            {feedback_block}

            Review checklist:
            - Does the plan match the user's intent?
            - Is the feature scope too broad for a small MVP?
            - Are there implementation risks?
            - Are required features missing?
            - Are file outputs and acceptance criteria clear?

            Return Markdown with:
            1. Summary verdict
            2. Required changes
            3. Optional improvements
            4. Risks
            5. Recommendation: approve for final planning or revise

            Start the response with "# Planner B Review".
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
    ) -> None:
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort

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
            You are Architect Agent in a Codex CLI multi-agent development workflow.
            Create a contract bundle for parallel code agents. Do not ask follow-up questions.

            Work only in the current working directory. The current working directory is
            the contract directory. Create or overwrite only these files:
            - requirements.md
            - architecture.md
            - api_contract.md
            - data_model.md
            - task_manifest.json
            - file_ownership.md
            - acceptance_tests.md
            - integration_plan.md

            User request:
            {user_request}

            Planner A draft:
            {planner_a_draft}

            Planner B review:
            {planner_b_review}

            Approved final plan:
            {final_plan}

            Contract rules:
            - Keep the MVP small and runnable locally.
            - Select or preserve the implementation stack from the approved plan.
            - Use standard project layout and dependency files for the chosen stack.
            - Split work into 2 to 6 implementation tasks.
            - Design task boundaries so code agents can work in parallel.
            - Each task must have clear owned_paths that avoid overlap with other tasks.
            - Shared entrypoint files should be handled by the Integrator where possible.
            - {MANIFEST_CONTRACT_NOTE}
            - Include dependencies between tasks only when necessary.
            - Do not require external APIs unless explicitly requested.
            - Do not store personal information.

            task_manifest.json must be valid JSON with this shape:
            {{
              "version": 1,
              "tasks": [
                {{
                  "id": "T1",
                  "title": "...",
                  "summary": "...",
                  "dependencies": [],
                  "owned_paths": ["..."],
                  "allowed_shared_paths": ["..."],
                  "forbidden_paths": ["contract/", "runs/", "agent_workspaces/"],
                  "interfaces": ["..."],
                  "acceptance_criteria": ["..."]
                }}
              ]
            }}

            When finished, print a concise summary of the contract and task split.
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
    ) -> None:
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort

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
            You are Scaffold Agent in a Codex CLI multi-agent development workflow.
            Create only the shared project skeleton for later parallel code agents.
            Do not ask follow-up questions.

            Work only in the current working directory. The current working directory is
            scaffold_app. Do not modify files outside it.

            User request:
            {user_request}

            Contract bundle:
            {contract_bundle}

            Requirements:
            - Create the minimal project skeleton for the stack chosen in the contract.
            - Include conventional dependency, config, and entrypoint files only when needed.
            - Include README.md with the expected setup, run, and verification commands.
            - {MANIFEST_CONTRACT_NOTE}
            - Add empty or minimal modules that match the contract boundaries.
            - Add placeholders only; do not implement feature-specific logic in full.
            - Keep dependencies minimal.

            When finished, print a short summary of files created.
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
        reference_markdown: str | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort
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
            You are {self.agent_id}, a Code Agent in a parallel Codex development workflow.
            Implement only your assigned tasks. Do not ask follow-up questions.

            {_reference_block(self.reference_markdown)}

            Work only in the current working directory. The current working directory is
            your isolated agent workspace. Do not modify files outside it.

            User request:
            {user_request}

            Contract bundle:
            {contract_bundle}

            Your assignment:
            {assigned_tasks_json}

            Implementation rules:
            - Implement only the assigned tasks.
            - Follow the language, framework, runtime, and project conventions declared
              by the approved plan and contract.
            - Do not change the chosen stack unless required; if you do, explain why.
            - Prefer editing owned_paths from your assignment.
            - Avoid editing allowed_shared_paths unless your task cannot work without it.
            - Never edit forbidden_paths.
            - Keep public interfaces compatible with the contract.
            - Keep the app runnable locally.
            - Keep dependencies minimal.
            - If you add tests, keep them lightweight and local.
            - If your assignment changes setup, run, test, smoke, server, or
              browser behavior, update codex_app_manifest.json according to
              docs/CODEX_APP_MANIFEST.md.

            When finished, print:
            1. Files changed
            2. Tasks completed
            3. Tests added or run
            4. Any integration notes for the Integrator Agent
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
            Continue as {self.agent_id}, a Code Agent in a parallel Codex development workflow.
            The integrated app failed QA or the user requested fixes. Resume your own work,
            inspect the feedback, and update only the files owned or allowed by your assignment.

            {_reference_block(self.reference_markdown)}

            Work only in the current working directory. Do not modify files outside it.
            Do not ask follow-up questions.

            User request:
            {user_request}

            Contract bundle:
            {contract_bundle}

            Your assignment:
            {assigned_tasks_json}

            QA/user feedback:
            {qa_feedback}

            Fix iteration: {iteration}

            Rules:
            - Follow the language, framework, runtime, and project conventions declared
              by the approved plan and contract.
            - Do not change the chosen stack unless required; if you do, explain why.
            - Prefer owned_paths from your assignment.
            - Edit allowed_shared_paths only when necessary.
            - Never edit forbidden_paths.
            - Keep public interfaces compatible with the contract.
            - Keep the app runnable locally.
            - Update codex_app_manifest.json according to docs/CODEX_APP_MANIFEST.md
              if setup, run, test, smoke, server, or browser behavior changes.

            When finished, print:
            1. Files changed
            2. Issues fixed
            3. Tests added or run
            4. Any integration notes for the Integrator Agent
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
        reference_markdown: str | None = None,
    ) -> None:
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort
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
            You are Integrator Agent in a parallel Codex development workflow.
            Merge the code-agent outputs into integration/merged_app.
            Do not ask follow-up questions.

            {_reference_block(self.reference_markdown)}

            Work in the run directory. You may read contract/, scaffold_app/,
            agent_workspaces/, agent_outputs/, and integration/.
            Write only inside integration/merged_app.

            User request:
            {user_request}

            Contract bundle:
            {contract_bundle}

            Assignment summary:
            {assignment_summary}

            Workspace file listing:
            {workspace_listing}

            Requirements:
            - Ensure integration/merged_app is the final runnable local project.
            - Preserve the chosen stack's conventional entrypoints and dependency files.
            - Connect feature modules through the shared entrypoint when the stack uses one.
            - Resolve conflicts consistently with the contract.
            - Preserve useful tests and docs from code agents.
            - Ensure README.md exists with setup, run, and verification instructions.
            - {MANIFEST_CONTRACT_NOTE}
            - Keep dependencies minimal.
            - Do not write outside integration/merged_app.

            When finished, print a concise integration report with files changed and any residual risks.
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
            Continue as Integrator Agent in a parallel Codex development workflow.
            The integrated app failed QA or the user requested fixes.

            {_reference_block(self.reference_markdown)}

            Work in the run directory. You may read contract/, scaffold_app/,
            agent_workspaces/, agent_outputs/, and integration/.
            Write only inside integration/merged_app. Do not ask follow-up questions.

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

            Requirements:
            - Fix shared entrypoints, merge errors, missing files, or cross-agent integration bugs.
            - Do not overwrite a code agent's owned implementation unless needed to connect it.
            - Preserve the chosen stack's conventional entrypoints and dependency files.
            - Keep README.md valid and aligned with the final runnable project.
            - Keep codex_app_manifest.json valid, aligned with the final runnable app,
              and compliant with docs/CODEX_APP_MANIFEST.md.
            - Keep dependencies minimal.
            - Do not write outside integration/merged_app.

            When finished, print a concise repair report with files changed and residual risks.
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
        reference_markdown: str | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout
        self.model = model
        self.reasoning_effort = reasoning_effort
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
            You are {self.agent_id}, a QA Agent in a Codex CLI multi-agent development workflow.
            Review the completed app using the approved contract, generated app listing,
            mechanical QA report, and attached screenshots when present.

            Do not modify files. Do not ask follow-up questions.

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

            Review duties:
            - Compare the implementation evidence against the acceptance criteria.
            - Inspect attached screenshots for obvious visual breakage, blank pages,
              broken layout, or missing primary UI.
            - Treat mechanical QA FAIL as a blocking issue.
            - Treat mechanical QA SKIP as a risk, not automatically a failure.
            - For browser/game apps, verify whether the evidence supports keyboard
              handling and visible gameplay enough for this run.
            - Avoid inventing requirements outside the approved contract.

            Output format:
            QA_STATUS: PASS or FAIL
            Suspected owners:
            - code_1, code_2, integrator, unknown, or "None"
            Affected paths:
            - relative/path.ext, or "None"
            Summary: one short paragraph
            Findings:
            - bullet list of concrete issues or "None"
            Evidence:
            - bullet list referencing report sections, screenshot names, or files
            Recommended fixes:
            - bullet list, or "None"
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
            You are Developer Agent in a Codex CLI multi-agent development workflow.
            Create the app files now. Do not ask follow-up questions.
            Do not reply with acknowledgements.

            Work only in the current working directory.
            Do not modify files outside this generated_app directory.

            User request:
            {user_request}

            Approved plan:
            {plan_markdown}

            Requirements:
            - Create a runnable local project in the current working folder.
            - Choose the simplest language, framework, and runtime that fits the user request
              and approved plan.
            - Use conventional entrypoint and dependency files for the chosen stack.
            - Keep the MVP small.
            - Do not add external API calls.
            - Do not store personal information.
            - Write clear run instructions in README.md.
            - {MANIFEST_CONTRACT_NOTE}
            - Keep dependencies minimal.
            - If you create Windows .bat or .cmd launchers, keep their contents ASCII-only.

            When finished, print a short summary of files created or changed.
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
            Continue as Developer Agent.
            The generated app failed validation.
            Read the error log and modify files in the current working directory.
            Keep the approved scope and make the generated project runnable.
            Do not ask for more input.

            User request:
            {user_request}

            Approved plan:
            {plan_markdown}

            Validation error log:
            {error_log}

            Fix attempt: {iteration}

            Constraints:
            - Work only in the current working directory.
            - Do not modify files outside this generated_app directory.
            - Preserve the chosen stack unless changing it is required to satisfy the approved scope.
            - Keep codex_app_manifest.json valid, aligned with the final runnable
              project, and compliant with docs/CODEX_APP_MANIFEST.md.
            - Do not add external API calls.
            - Do not store personal information.
            - Keep Windows .bat or .cmd launchers ASCII-only.

            When finished, print a short summary of files changed.
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
