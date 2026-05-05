"""Discord adapter that controls runs through the local FastAPI API."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import discord

from discord_api_client import LocalApiClient, LocalApiError
from discord_reporter import DiscordReporter
from discord_ui import PlanApprovalView, QAApprovalView


TERMINAL_STATUSES = {"completed", "cancelled", "failed", "development_failed", "qa_revision_failed"}
PLAN_READY_STATUSES = {"awaiting_plan_approval", "awaiting_contract_approval"}
QA_READY_STATUS = "awaiting_qa_approval"
STATUS_MESSAGE_LIMIT = 1900
LOG_SNIPPET_LIMIT = 700


class DiscordApiEngine:
    """Presentation-only Discord engine backed by the local FastAPI server."""

    def __init__(
        self,
        *,
        api_client: LocalApiClient,
        reporter: DiscordReporter,
        routing_mode: str,
        code_agent_count: int,
        qa_agent_count: int,
        codex_model: str | None = None,
        codex_reasoning_effort: str | None = None,
        max_fix_iterations: int = 1,
        codex_timeout_seconds: int = 900,
        planner_a_codex_home: str | None = None,
        planner_b_codex_home: str | None = None,
        architect_codex_home: str | None = None,
        scaffold_codex_home: str | None = None,
        integrator_codex_home: str | None = None,
        code_agent_codex_homes: list[str | None] | None = None,
        qa_agent_codex_homes: list[str | None] | None = None,
    ) -> None:
        self.api = api_client
        self.reporter = reporter
        self.routing_mode = routing_mode
        self.code_agent_count = max(1, code_agent_count)
        self.qa_agent_count = max(0, qa_agent_count)
        self.codex_model = codex_model
        self.codex_reasoning_effort = codex_reasoning_effort
        self.max_fix_iterations = max_fix_iterations
        self.codex_timeout_seconds = codex_timeout_seconds
        self.planner_a_codex_home = planner_a_codex_home
        self.planner_b_codex_home = planner_b_codex_home
        self.architect_codex_home = architect_codex_home
        self.scaffold_codex_home = scaffold_codex_home
        self.integrator_codex_home = integrator_codex_home
        self.code_agent_codex_homes = code_agent_codex_homes or []
        self.qa_agent_codex_homes = qa_agent_codex_homes or []

    async def start_discord_request(
        self,
        *,
        request: str,
        channel: discord.abc.Messageable,
        requester_id: int,
        guild_id: int | None = None,
        request_interaction_id: int | None = None,
    ) -> tuple[str, Path]:
        await self.api.health()
        detail = await self.api.create_run(self._create_payload(request))
        run_id = str(detail["run_id"])
        run_dir = Path(str(detail["run_dir"]))
        route = _route_label(detail)
        await self.reporter.send_status(
            channel,
            "\n".join(
                [
                    f"Started development run `{run_id}` through local API.",
                    f"Route: `{route}`",
                    f"Run directory: `{run_dir}`",
                ]
            ),
        )
        detail = await self._wait_for_status(
            run_id,
            channel=channel,
            ready=PLAN_READY_STATUSES,
            timeout_seconds=max(300, self.codex_timeout_seconds * 4),
        )
        await self._publish_planning_review(channel, detail, requester_id)
        return run_id, run_dir

    async def handle_plan_approval(self, run_id: str, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if channel is None:
            await interaction.followup.send("Cannot continue because this interaction has no channel.", ephemeral=True)
            return
        try:
            await self.api.approve_run(run_id, user_id=interaction.user.id)
            await self.reporter.send_status(channel, f"`{run_id}` approved through local API. Development is running.")
            detail = await self._wait_for_status(
                run_id,
                channel=channel,
                ready={QA_READY_STATUS},
                timeout_seconds=max(900, self.codex_timeout_seconds * 12),
            )
            await self._publish_qa_review(channel, detail, interaction.user.id)
            await interaction.followup.send(f"Run `{run_id}` is waiting for QA approval.")
        except LocalApiError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)

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
        try:
            await self.api.request_changes(run_id, user_id=interaction.user.id, feedback=feedback)
            await self.reporter.send_status(channel, f"`{run_id}` revision requested through local API.")
            detail = await self._wait_for_status(
                run_id,
                channel=channel,
                ready=PLAN_READY_STATUSES,
                timeout_seconds=max(300, self.codex_timeout_seconds * 4),
            )
            await self._publish_planning_review(channel, detail, interaction.user.id)
            await interaction.followup.send(f"Run `{run_id}` revised and is waiting for approval.")
        except LocalApiError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)

    async def handle_plan_cancel(self, run_id: str, interaction: discord.Interaction) -> None:
        try:
            await self.api.cancel_run(run_id, user_id=interaction.user.id)
            await interaction.followup.send(f"Run `{run_id}` cancel requested through local API.")
        except LocalApiError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)

    async def handle_qa_approval(self, run_id: str, interaction: discord.Interaction) -> None:
        try:
            await self.api.approve_qa(run_id, user_id=interaction.user.id)
            await interaction.followup.send(f"Run `{run_id}` approved and completed.")
        except LocalApiError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)

    async def handle_qa_revision(
        self,
        run_id: str,
        feedback: str,
        interaction: discord.Interaction,
    ) -> None:
        try:
            await self.api.request_qa_fix(run_id, user_id=interaction.user.id, feedback=feedback)
            await interaction.followup.send(
                f"Run `{run_id}` QA fix request was recorded. Worker re-enqueue for operator QA fixes is a later stage."
            )
        except LocalApiError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)

    async def build_status_message(self, run_id: str) -> str:
        detail = await self.api.get_run(run_id)
        active = await self._get_active_step(run_id)
        logs = await self._list_logs(run_id)
        tail = await self._latest_log_tail(run_id, logs)
        return _format_run_status(detail, active=active, logs=logs, tail=tail)

    async def build_runs_message(self, *, limit: int = 10) -> str:
        runs = await self.api.list_runs(limit=max(1, min(limit, 20)))
        return _format_runs_summary(runs)

    def _create_payload(self, request: str) -> dict[str, Any]:
        return {
            "user_request": request,
            "routing_mode": self.routing_mode,
            "dashboard_mode": "planning_only",
            "code_agent_count": self.code_agent_count,
            "qa_agent_count": self.qa_agent_count,
            "model": self.codex_model,
            "reasoning_effort": self.codex_reasoning_effort,
            "max_fix_iterations": self.max_fix_iterations,
            "timeout_seconds": self.codex_timeout_seconds,
            "planner_a_codex_home": self.planner_a_codex_home,
            "planner_b_codex_home": self.planner_b_codex_home,
            "architect_codex_home": self.architect_codex_home,
            "scaffold_codex_home": self.scaffold_codex_home,
            "integrator_codex_home": self.integrator_codex_home,
            "code_agent_codex_homes": self.code_agent_codex_homes or None,
            "qa_agent_codex_homes": self.qa_agent_codex_homes or None,
        }

    async def _wait_for_status(
        self,
        run_id: str,
        *,
        channel: discord.abc.Messageable,
        ready: set[str],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        last_reported = ""
        last_heartbeat = 0.0
        while True:
            detail = await self.api.get_run(run_id)
            status = str(detail.get("status") or "")
            if status in ready:
                return detail
            if status in TERMINAL_STATUSES:
                await self.reporter.send_status(channel, f"`{run_id}` stopped with status `{status}`.")
                raise LocalApiError(f"Run `{run_id}` stopped with status `{status}`.")
            now = asyncio.get_running_loop().time()
            active = await self._get_active_step(run_id)
            logs = await self._list_logs(run_id)
            tail = await self._latest_log_tail(run_id, logs)
            active_label = _active_step_label(detail, active)
            tail_marker = str(tail.get("path") or "") if tail else ""
            label = f"{status} {active_label} {tail_marker}".strip()
            if label != last_reported or now - last_heartbeat >= 60:
                await self.reporter.send_status(channel, _format_progress_message(run_id, status, detail, active, tail))
                last_reported = label
                last_heartbeat = now
            if now >= deadline:
                raise LocalApiError(f"Timed out waiting for run `{run_id}`. Last status: {status or 'unknown'}.")
            await asyncio.sleep(5)

    async def _publish_planning_review(
        self,
        channel: discord.abc.Messageable,
        detail: dict[str, Any],
        requester_id: int,
    ) -> None:
        run_id = str(detail["run_id"])
        await self._send_artifact_markdown(channel, run_id, "planning/01_planner_a_draft.md", f"{run_id} Planner A Draft")
        await self._send_artifact_markdown(channel, run_id, "planning/02_planner_b_review.md", f"{run_id} Planner B Review")
        await self._send_artifact_markdown(channel, run_id, "planning/03_final_plan.md", f"{run_id} Final Plan")
        view = PlanApprovalView(engine=self, run_id=run_id, requester_id=requester_id)
        await channel.send(
            f"<@{requester_id}> Review the plan for run `{run_id}`. Route: `{_route_label(detail)}`.",
            view=view,
        )

    async def _publish_qa_review(
        self,
        channel: discord.abc.Messageable,
        detail: dict[str, Any],
        requester_id: int,
    ) -> None:
        run_id = str(detail["run_id"])
        run_dir = Path(str(detail["run_dir"]))
        generated_app = _artifact_path(detail, "generated_app")
        qa_report = _artifact_path(detail, "qa_report")
        await self.reporter.send_artifact_paths(
            channel,
            run_dir=run_dir,
            generated_app_dir=run_dir / generated_app if generated_app else None,
            qa_report_path=run_dir / qa_report if qa_report else None,
            ok=None,
        )
        await self._send_artifact_markdown(channel, run_id, qa_report or "qa_report.md", f"{run_id} QA Report")
        screenshots = await self._screenshot_paths(detail)
        if screenshots:
            await self.reporter.send_files(channel, title=f"{run_id} QA Screenshot", paths=screenshots)
        view = QAApprovalView(engine=self, run_id=run_id, requester_id=requester_id)
        await channel.send(f"<@{requester_id}> Review QA artifacts for run `{run_id}`.", view=view)

    async def _send_artifact_markdown(
        self,
        channel: discord.abc.Messageable,
        run_id: str,
        path: str,
        title: str,
    ) -> None:
        try:
            artifact = await self.api.read_artifact(run_id, path)
        except LocalApiError:
            return
        if artifact.get("encoding") != "utf-8":
            return
        await self.reporter.send_markdown(
            channel,
            title=title,
            content=str(artifact.get("content") or ""),
            artifact_path=Path(path),
        )

    async def _screenshot_paths(self, detail: dict[str, Any]) -> list[Path]:
        run_id = str(detail["run_id"])
        run_dir = Path(str(detail["run_dir"]))
        artifacts = await self.api.list_artifacts(run_id)
        paths = []
        for artifact in artifacts:
            path = str(artifact.get("path") or "")
            if path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                candidate = run_dir / path
                if candidate.exists():
                    paths.append(candidate)
        return paths

    async def _get_active_step(self, run_id: str) -> dict[str, Any] | None:
        try:
            return await self.api.get_active_step(run_id)
        except LocalApiError:
            return None

    async def _list_logs(self, run_id: str) -> list[dict[str, Any]]:
        try:
            return await self.api.list_logs(run_id)
        except LocalApiError:
            return []

    async def _latest_log_tail(self, run_id: str, logs: list[dict[str, Any]]) -> dict[str, Any] | None:
        for log in _select_progress_logs(logs):
            path = str(log.get("path") or "")
            if not path:
                continue
            try:
                tail = await self.api.read_log_tail(run_id, path, lines=20)
            except LocalApiError:
                continue
            if str(tail.get("content") or "").strip():
                return tail
        return None


def _route_label(detail: dict[str, Any]) -> str:
    state = detail.get("state") if isinstance(detail.get("state"), dict) else {}
    routing = state.get("routing") if isinstance(state.get("routing"), dict) else {}
    return str(routing.get("mode") or detail.get("route_mode") or "unknown")


def _artifact_path(detail: dict[str, Any], name: str) -> str | None:
    state = detail.get("state") if isinstance(detail.get("state"), dict) else {}
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    value = artifacts.get(name)
    return str(value) if value else None


def _format_runs_summary(runs: list[dict[str, Any]]) -> str:
    if not runs:
        return "No local API runs found."
    lines = ["**Recent local runs**"]
    for run in runs[:20]:
        run_id = str(run.get("run_id") or "unknown")
        status = str(run.get("status") or "unknown")
        route = str(run.get("route_mode") or "unknown")
        updated = str(run.get("updated_at") or run.get("created_at") or "")
        request = _compact(str(run.get("user_request") or ""), 90)
        lines.append(f"- `{run_id}` `{status}` route=`{route}` updated=`{updated}`")
        if request:
            lines.append(f"  {request}")
    return _fit_message("\n".join(lines))


def _format_run_status(
    detail: dict[str, Any],
    *,
    active: dict[str, Any] | None,
    logs: list[dict[str, Any]],
    tail: dict[str, Any] | None,
) -> str:
    run_id = str(detail.get("run_id") or "unknown")
    status = str(detail.get("status") or "unknown")
    lines = [
        "**Run status**",
        f"- Run: `{run_id}`",
        f"- Status: `{status}`",
        f"- Route: `{_route_label(detail)}`",
        f"- Active: `{_active_step_text(detail, active)}`",
        f"- Artifacts: `{detail.get('artifact_count') or 0}`",
        f"- Logs: `{len(logs)}`",
    ]
    run_dir = detail.get("run_dir")
    if run_dir:
        lines.append(f"- Directory: `{run_dir}`")
    request = _compact(str(detail.get("user_request") or ""), 220)
    if request:
        lines.append(f"- Request: {request}")
    snippet = _format_log_snippet(tail)
    if snippet:
        lines.append(snippet)
    return _fit_message("\n".join(lines))


def _format_progress_message(
    run_id: str,
    status: str,
    detail: dict[str, Any],
    active: dict[str, Any] | None,
    tail: dict[str, Any] | None,
) -> str:
    lines = [
        f"`{run_id}` status: `{status}`",
        f"Active: `{_active_step_text(detail, active)}`",
    ]
    snippet = _format_log_snippet(tail)
    if snippet:
        lines.append(snippet)
    return _fit_message("\n".join(lines))


def _format_log_snippet(tail: dict[str, Any] | None) -> str:
    if not tail:
        return ""
    content = str(tail.get("content") or "").strip()
    if not content:
        return ""
    path = str(tail.get("path") or "log")
    content = _compact_code(content, LOG_SNIPPET_LIMIT)
    return f"Latest log `{path}`:\n```text\n{content}\n```"


def _active_step_label(detail: dict[str, Any], active: dict[str, Any] | None = None) -> str:
    label = _active_step_text(detail, active)
    return f" ({label})" if label != "idle" else ""


def _active_step_text(detail: dict[str, Any], active: dict[str, Any] | None = None) -> str:
    active = active or {}
    if active.get("label"):
        label = str(active["label"])
        if label and label != "idle":
            return label
    state = detail.get("state") if isinstance(detail.get("state"), dict) else {}
    active = state.get("active_step") if isinstance(state.get("active_step"), dict) else {}
    stage = active.get("stage")
    agent_id = active.get("agent_id")
    pid = active.get("pid")
    parts = [str(item) for item in [stage, agent_id, f"pid={pid}" if pid else None] if item]
    return ", ".join(parts) if parts else "idle"


def _select_progress_logs(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def score(log: dict[str, Any]) -> tuple[int, str]:
        stream = str(log.get("stream") or "")
        path = str(log.get("path") or "")
        priority = 0
        if stream == "stderr":
            priority = 3
        elif stream == "stdout":
            priority = 2
        elif stream == "meta":
            priority = 1
        return priority, str(log.get("updated_at") or log.get("modified_at") or path)

    return sorted(logs, key=score, reverse=True)


def _compact(value: str, limit: int) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _compact_code(value: str, limit: int) -> str:
    value = value.replace("```", "'''")
    if len(value) <= limit:
        return value
    return "...\n" + value[-max(0, limit - 7) :].lstrip()


def _fit_message(message: str) -> str:
    if len(message) <= STATUS_MESSAGE_LIMIT:
        return message
    return message[: STATUS_MESSAGE_LIMIT - 14].rstrip() + "\n...truncated"
