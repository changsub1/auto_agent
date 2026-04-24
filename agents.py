"""Codex-backed agents for planning, debate, and app generation."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from codex_runner import CodexResult, run_codex, run_codex_result


class PlannerAgent:
    """Backward-compatible single planner used by the CLI MVP."""

    def __init__(
        self,
        *,
        codex_home: str | None = None,
        logs_dir: Path | None = None,
        timeout: int = 600,
    ) -> None:
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout

    def create_plan(self, user_request: str, workdir: Path) -> str:
        return PlannerAgentA(
            codex_home=self.codex_home,
            logs_dir=self.logs_dir,
            timeout=self.timeout,
        ).create_initial_plan(user_request, workdir).stdout


class PlannerAgentA:
    """Primary planner that drafts and revises the final plan."""

    def __init__(
        self,
        *,
        codex_home: str | None = None,
        logs_dir: Path | None = None,
        timeout: int = 600,
    ) -> None:
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout

    def create_initial_plan(
        self,
        user_request: str,
        workdir: Path,
        *,
        session_id: str | None = None,
    ) -> CodexResult:
        prompt = dedent(
            f"""
            You are Planner Agent A in a Codex CLI multi-agent development workflow.
            Produce the initial planning document now. Do not ask follow-up questions.
            Do not reply with acknowledgements.

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
            - Prefer Python.
            - Prefer Streamlit only when it fits the request.
            - Avoid external APIs.
            - Avoid storing personal information.
            - Keep dependencies minimal.

            Start the response with "# Planner A Draft".
            """
        ).strip()
        return self._run(prompt, workdir, session_id=session_id, label="planner_a_draft")

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
        feedback_block = user_feedback or "(no additional user feedback)"
        prompt = dedent(
            f"""
            Continue as Planner Agent A.
            Revise the plan into the current final planning document.
            Use your existing session context if available.

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
            - Keep the scope realistic for a small executable Python MVP.
            - Mention any explicit tradeoffs.
            - Do not ask follow-up questions.
            - Return only the final Markdown plan.

            Start the response with "# Final Plan".
            """
        ).strip()
        return self._run(prompt, workdir, session_id=session_id, label="planner_a_final")

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
        )


class PlannerAgentB:
    """Reviewer planner that critiques scope, intent fit, and risk."""

    def __init__(
        self,
        *,
        codex_home: str | None = None,
        logs_dir: Path | None = None,
        timeout: int = 600,
    ) -> None:
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout

    def review_plan(
        self,
        user_request: str,
        plan_markdown: str,
        workdir: Path,
        *,
        user_feedback: str | None = None,
        session_id: str | None = None,
    ) -> CodexResult:
        feedback_block = user_feedback or "(no additional user feedback)"
        prompt = dedent(
            f"""
            You are Planner Agent B in a Codex CLI multi-agent development workflow.
            Review Planner Agent A's plan against the user's request.
            Do not rewrite the full plan. Provide focused review comments.

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
        return run_codex_result(
            prompt,
            workdir=workdir,
            codex_home=self.codex_home,
            timeout=self.timeout,
            logs_dir=self.logs_dir,
            label="planner_b_review",
            session_id=session_id,
            sandbox="workspace-write",
        )


class DeveloperAgent:
    """Generates and fixes a runnable Python app from the approved plan."""

    def __init__(
        self,
        *,
        codex_home: str | None = None,
        logs_dir: Path | None = None,
        timeout: int = 900,
    ) -> None:
        self.codex_home = codex_home
        self.logs_dir = logs_dir
        self.timeout = timeout

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
            - Create a runnable Python app in the current working folder.
            - The default deliverables are app.py, requirements.txt, and README.md.
            - Prefer Streamlit only when it fits the request.
            - If the user asks for a local executable-style app, a small standard-library CLI,
              Tkinter app, or launcher script is acceptable.
            - Keep the MVP small.
            - Do not add external API calls.
            - Do not store personal information.
            - Write clear run instructions in README.md.
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
            Keep the approved scope and make app.py runnable.
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
        )
