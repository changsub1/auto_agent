"""Codex-backed agents for planning, debate, and app generation."""

from __future__ import annotations

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


MANIFEST_CONTRACT_NOTE = (
    "Final runnable outputs must include codex_app_manifest.json. "
    "Follow docs/CODEX_APP_MANIFEST.md. "
    "Commands must be JSON arrays, not shell strings."
)


def _system_prompt(agent_id: str, override: str | None = None) -> str:
    if override and override.strip():
        return override.strip()
    return load_agent_system_prompt(agent_id=agent_id)


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
            {_system_prompt(self.agent_id, self.system_prompt)}

            Agent id: {self.agent_id}
            Continue this code-agent session.
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
            {_system_prompt("integrator", self.system_prompt)}

            Continue this integrator session.
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

            Output only valid JSON. Do not wrap it in Markdown fences.

            Schema:
            {{
              "version": 1,
              "summary": "short explanation of what this plan checks",
              "scenarios": [
                {{
                  "name": "short scenario name",
                  "intent": "why this scenario matters",
                  "stop_on_failure": true,
                  "steps": [
                    {{"action": "goto", "url": "/index.html"}},
                    {{"action": "expect_text", "text": "visible text"}},
                    {{"action": "expect_visible", "selector": "css selector"}},
                    {{"action": "click", "selector": "css selector"}},
                    {{"action": "press", "key": "ArrowRight"}},
                    {{"action": "type", "selector": "css selector", "text": "input text"}},
                    {{"action": "drag", "selector": "css selector", "dx": -300, "dy": 0}},
                    {{"action": "wait", "ms": 500}},
                    {{"action": "screenshot", "name": "after_interaction"}}
                  ]
                }}
              ]
            }}

            Allowed actions:
            - goto: local path or local URL only.
            - expect_text: checks body text contains the given text.
            - expect_visible: CSS selector must become visible.
            - click: click first matching CSS selector.
            - press: browser keyboard key, optionally with selector.
            - type: fill text into selector.
            - drag: drag selector center by dx/dy pixels.
            - wait: bounded wait in milliseconds.
            - screenshot: capture evidence.

            Planning rules:
            - Choose scenarios that match the user's actual app type. Do not use
              game keyboard controls for ordinary web pages unless the app needs them.
            - Prefer stable selectors such as data-testid, aria-label, ids, or
              clear semantic elements visible in the generated files.
            - Keep it small: 1-3 scenarios and 3-8 steps each.
            - Include at least one screenshot step.
            - Do not invent login credentials, secrets, network services, or
              external dependencies.
            - If the app cannot be meaningfully interacted with, produce a load
              and visibility scenario instead of random input.
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

            You are now running autonomous QA inside a dedicated QA workspace.
            The current working directory is the only workspace you may write to.
            Write user-facing summaries, findings, and timeline-visible explanations in Korean.
            Keep machine-readable keys, file paths, commands, and QA_STATUS values in English.

            Workspace layout:
            - app/: copy of the completed generated app. Treat it as the subject under test.
            - context/: request, contract, generated app listing, and QA baseline/mechanical report.
            - qa_tools/: safe evidence-producing tools for local commands, file checks, and local browser screenshots.
            - evidence/: write command logs, findings, helper scripts, and verdict.json here.
            - screenshots/: write visual evidence here for browser, game, dashboard, or other visual apps.
            - scratch/: optional temporary experiments. Do not modify files outside this workspace.

            User request:
            {user_request}

            Contract bundle:
            {contract_bundle}

            Generated app listing:
            {generated_app_listing}

            QA baseline/mechanical report:
            {mechanical_qa_report}

            Duties:
            - Inspect the app and decide what evidence is needed to judge the user's request.
            - Run safe local commands only from this workspace.
            - Prefer `qa_tools/command_probe.py`, `qa_tools/file_probe.py`, and `qa_tools/browser_probe.py`
              because they write evidence and command logs consistently.
            - On Windows, prefer the generated `.cmd` launchers such as `qa_tools\\browser_probe.cmd`
              because they use Orchestra's Python environment with installed QA dependencies.
            - You may create small QA scripts, smoke tests, or CLI probes in evidence/ or scratch/ when the provided tools are insufficient.
            - Do not use external network services or secrets.
            - Prefer commands that only read app files, build locally, run local tests, or launch local app servers.
            - If this is a visual/browser app, capture at least one screenshot into screenshots/.
            - For browser games or canvas apps, use `qa_tools\\browser_probe.cmd --action-file ...`
              with page-scoped actions such as screenshot, wait, click, press, and drag.
              Drag coordinates are relative to the selected element and are allowed because
              they operate only inside the generated app page.
            - Do not use global screenshots, pyautogui, OS-wide mouse/keyboard automation, Alt+Tab, Win-key shortcuts, or desktop window control.
            - For desktop GUI apps, do not launch the interactive GUI unless there is a bounded self-test, smoke-test, or unit-test mode.
              Test importable logic, CLI flags, or unit tests instead.
            - If an action fails because the test method is wrong, adapt and retry before judging the app.
            - If evidence is missing, do not mark PASS.
            - If a baseline/mechanical report is FAIL, treat it as blocking unless your own evidence clearly proves it was a harness error.
            - If text appears corrupted on Windows, re-read files as UTF-8 before using encoding corruption as evidence.
            - Do not edit the final app in app/. If you need to experiment with a fix, copy files to scratch/ and describe it.

            Required files to create before finishing:
            1. evidence/command_log.jsonl
               - JSON lines, one per command/probe you intentionally ran.
               - Include command, cwd, purpose, exit_code when known, and related evidence paths.
            2. evidence/qa_findings.md
               - Human-readable summary of what you tested, what evidence you collected, and findings.
            3. evidence/verdict.json
               - Strict JSON object with this schema:
                 {{
                   "status": "PASS" | "FAIL" | "INCONCLUSIVE" | "UNSUPPORTED",
                   "summary": "one paragraph",
                   "findings": ["concrete issue or none"],
                   "evidence": ["relative evidence path or observation"],
                   "affected_paths": ["app-relative path or none"],
                   "suspected_owners": ["code_1", "code_2", "integrator", "unknown", "none"]
                 }}

            Verdict rules:
            - PASS only when the app has runnable evidence for the core requested behavior.
            - FAIL when the app runs but violates a requirement or has blocking runtime/build/visual defects.
            - INCONCLUSIVE when the app type is partly testable but evidence is insufficient.
            - UNSUPPORTED when the app cannot be safely executed by local QA tooling.
            - For browser/game/dashboard apps, PASS requires screenshot evidence.
            - For desktop GUI apps, PASS requires a self-test/unit-test/import evidence path because GUI input automation is disabled by default.

            Final response:
            - Print a concise summary.
            - Include a first line `QA_STATUS: PASS`, `QA_STATUS: FAIL`,
              `QA_STATUS: INCONCLUSIVE`, or `QA_STATUS: UNSUPPORTED`.
            - Reference evidence/verdict.json and evidence/qa_findings.md.
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

            Review duties:
            - Compare the implementation evidence against the acceptance criteria.
            - Inspect attached screenshots for obvious visual breakage, blank pages,
              broken layout, or missing primary UI.
            - Use the scenario plan you created earlier in this same session as
              context for interpreting the mechanical QA results.
            - If file text appears mojibake-corrupted on Windows, re-read it as
              UTF-8 before using encoding corruption as failure evidence.
            - Treat mechanical QA FAIL as a blocking issue.
            - Treat mechanical QA SKIP as a risk, not automatically a failure.
            - For browser/game apps, verify whether the executed scenarios and
              screenshots support the intended interaction enough for this run.
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
