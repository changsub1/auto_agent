"""Shared local workflow stages used by the FastAPI run worker."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from codex_runner import CodexProcessHandle
from local_dashboard_runner import (
    LocalRunConfig,
    run_contract_stage_async,
    run_code_agents_stage_async,
    run_integration_stage_async,
    run_llm_qa_stage_async,
    run_mechanical_qa_stage,
    run_planning_stage,
    run_planning_stage_async,
    run_scaffold_stage_async,
    run_single_code_fix_stage_async,
    run_single_code_stage_async,
    run_targeted_fix_stage_async,
)
from routing import RoutingDecision
from state_store import StateStore
from workspace_manager import create_logs_dir


class WorkflowEngine:
    """Runs workflow stages without depending on FastAPI or Discord objects."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.runs_root = self.project_root / "runs"

    def run_planning(self, run_id: str, *, feedback: str | None = None) -> None:
        run_dir = self._run_dir(run_id)
        store = StateStore(run_dir)
        if _is_cancelled(store.load()):
            store.append_event("worker_skipped", "system", "Planning skipped because run is cancelled")
            return

        config = local_config_from_state(store.load())
        logs_dir = create_logs_dir(run_dir)
        store.set_active_step(stage="planning", agent_id="planner_a", interruptible=True)
        try:
            run_planning_stage(
                run_dir,
                logs_dir,
                store,
                config,
                user_feedback=feedback,
                running_status="planning_running",
            )
            if _control_action(store.load()) == "cancel":
                store.set_status("cancelled")
                return
            store.clear_control_action()
            store.set_status("awaiting_plan_approval")
        finally:
            store.clear_active_step()

    async def run_planning_async(
        self,
        run_id: str,
        *,
        feedback: str | None = None,
        process_started: Callable[[str, CodexProcessHandle], None] | None = None,
    ) -> None:
        run_dir = self._run_dir(run_id)
        store = StateStore(run_dir)
        if _is_cancelled(store.load()):
            store.append_event("worker_skipped", "system", "Planning skipped because run is cancelled")
            return

        config = local_config_from_state(store.load())
        logs_dir = create_logs_dir(run_dir)

        def register_process(agent_id: str, handle: CodexProcessHandle) -> None:
            store.set_active_step(
                stage="planning",
                agent_id=agent_id,
                pid=handle.pid,
                interruptible=True,
            )
            if process_started is not None:
                process_started(agent_id, handle)

        store.set_active_step(stage="planning", agent_id="planner_a", interruptible=True)
        try:
            await run_planning_stage_async(
                run_dir,
                logs_dir,
                store,
                config,
                user_feedback=feedback,
                running_status="planning_running",
                process_started=register_process,
            )
            if _control_action(store.load()) == "cancel":
                store.set_status("cancelled")
                return
            store.clear_control_action()
            store.set_status("awaiting_plan_approval")
        finally:
            store.clear_active_step()

    async def run_development_async(
        self,
        run_id: str,
        *,
        process_started: Callable[[str, str, CodexProcessHandle], None] | None = None,
    ) -> None:
        run_dir = self._run_dir(run_id)
        store = StateStore(run_dir)
        if _is_cancelled(store.load()):
            store.append_event("worker_skipped", "system", "Development skipped because run is cancelled")
            return

        state = store.load()
        config = local_config_from_state(state)
        logs_dir = create_logs_dir(run_dir)
        plan_artifacts = _load_plan_artifacts(run_dir, state)
        route = _route_from_state(state)
        manual_graph = _manual_graph_from_state(state)
        if manual_graph is not None:
            route = _route_from_manual_graph(manual_graph, route)
            config = _config_from_manual_graph(config, manual_graph)
            store.append_event(
                "graph_execution_started",
                "system",
                "Manual workflow graph execution started",
                {
                    "stage_count": len(manual_graph.get("stages") or []),
                    "code_agent_count": route.code_agent_count,
                    "qa_agent_count": route.qa_agent_count,
                    "uses_integrator": route.uses_integrator,
                },
            )

        def register_process(stage: str, agent_id: str, handle: CodexProcessHandle) -> None:
            store.set_active_step(
                stage=stage,
                agent_id=agent_id,
                pid=handle.pid,
                interruptible=True,
            )
            if process_started is not None:
                process_started(stage, agent_id, handle)

        try:
            if not route.uses_integrator:
                if manual_graph is not None:
                    store.append_event("graph_stage_started", "system", "Manual graph code/QA stages started", {"stages": ["code", "qa"]})
                await self._run_single_code_development_async(
                    run_dir=run_dir,
                    store=store,
                    config=config,
                    logs_dir=logs_dir,
                    final_plan=plan_artifacts["final_plan"],
                    route=route,
                    register_process=register_process,
                )
                if manual_graph is not None:
                    store.append_event("graph_execution_completed", "system", "Manual workflow graph execution completed", {"status": "awaiting_qa_approval"})
                return

            if manual_graph is not None:
                store.append_event("graph_stage_started", "system", "Manual graph contract stage started", {"stage": "contract"})
            store.set_active_step(stage="contract", agent_id="architect", interruptible=True)
            contract_dir = await run_contract_stage_async(
                run_dir,
                logs_dir,
                store,
                config,
                plan_artifacts,
                running_status="contract_running",
                process_started=lambda agent_id, handle: register_process("contract", agent_id, handle),
            )
            if _control_action(store.load()) == "cancel":
                store.set_status("cancelled")
                return

            if manual_graph is not None:
                store.append_event("graph_stage_completed", "system", "Manual graph contract stage completed", {"stage": "contract"})
                store.append_event("graph_stage_started", "system", "Manual graph scaffold stage started", {"stage": "scaffold"})
            store.set_active_step(stage="scaffold", agent_id="scaffold", interruptible=True)
            scaffold_dir = await run_scaffold_stage_async(
                run_dir,
                logs_dir,
                store,
                config,
                contract_dir,
                running_status="scaffold_running",
                process_started=lambda agent_id, handle: register_process("scaffold", agent_id, handle),
            )
            if _control_action(store.load()) == "cancel":
                store.set_status("cancelled")
                return

            if manual_graph is not None:
                store.append_event("graph_stage_completed", "system", "Manual graph scaffold stage completed", {"stage": "scaffold"})
                store.append_event("graph_stage_started", "system", "Manual graph code stage started", {"stage": "code"})
            assignments = await run_code_agents_stage_async(
                run_dir,
                logs_dir,
                store,
                config,
                contract_dir,
                scaffold_dir,
                running_status="code_agents_running",
                process_started=lambda agent_id, handle: register_process("code_agents", agent_id, handle),
            )
            if _control_action(store.load()) == "cancel":
                store.set_status("cancelled")
                return

            if manual_graph is not None:
                store.append_event("graph_stage_completed", "system", "Manual graph code stage completed", {"stage": "code"})
                store.append_event("graph_stage_started", "system", "Manual graph integration stage started", {"stage": "integration"})
            generated_app_dir = await run_integration_stage_async(
                run_dir,
                logs_dir,
                store,
                config,
                contract_dir,
                scaffold_dir,
                assignments,
                running_status="integration_running",
                process_started=lambda agent_id, handle: register_process("integration", agent_id, handle),
            )
            if _control_action(store.load()) == "cancel":
                store.set_status("cancelled")
                return

            if manual_graph is not None:
                store.append_event("graph_stage_completed", "system", "Manual graph integration stage completed", {"stage": "integration"})
                store.append_event("graph_stage_started", "system", "Manual graph QA stage started", {"stage": "qa"})
            store.set_active_step(stage="mechanical_qa", agent_id="mechanical_qa", interruptible=False)
            qa_result = await asyncio.to_thread(
                run_mechanical_qa_stage,
                run_dir,
                store,
                generated_app_dir,
                attempt_name="integrated mechanical QA",
                attempt_index=0,
            )
            qa_result = await run_llm_qa_stage_async(
                run_dir,
                logs_dir,
                store,
                config,
                contract_dir,
                generated_app_dir,
                qa_result,
                attempt_index=0,
                process_started=lambda agent_id, handle: register_process("llm_qa", agent_id, handle),
            )
            if _control_action(store.load()) == "cancel":
                store.set_status("cancelled")
                return

            fix_iterations_used = 0
            while not qa_result.ok and fix_iterations_used < config.max_fix_iterations:
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
                generated_app_dir = await run_targeted_fix_stage_async(
                    run_dir,
                    logs_dir,
                    store,
                    config,
                    contract_dir,
                    scaffold_dir,
                    assignments,
                    qa_result,
                    iteration=fix_iterations_used,
                    process_started=lambda agent_id, handle: register_process("fix", agent_id, handle),
                )
                if _control_action(store.load()) == "cancel":
                    store.set_status("cancelled")
                    return

                store.set_active_step(stage="mechanical_qa", agent_id="mechanical_qa", interruptible=False)
                qa_result = await asyncio.to_thread(
                    run_mechanical_qa_stage,
                    run_dir,
                    store,
                    generated_app_dir,
                    attempt_name=f"mechanical QA after fix {fix_iterations_used}",
                    attempt_index=fix_iterations_used,
                )
                qa_result = await run_llm_qa_stage_async(
                    run_dir,
                    logs_dir,
                    store,
                    config,
                    contract_dir,
                    generated_app_dir,
                    qa_result,
                    attempt_index=fix_iterations_used,
                    process_started=lambda agent_id, handle: register_process("llm_qa", agent_id, handle),
                )
                if _control_action(store.load()) == "cancel":
                    store.set_status("cancelled")
                    return

            store.clear_control_action()
            store.set_status("awaiting_qa_approval")
            if manual_graph is not None:
                store.append_event("graph_execution_completed", "system", "Manual workflow graph execution completed", {"status": "awaiting_qa_approval"})
            store.append_event(
                "worker_checkpoint",
                "system",
                "Development and mechanical QA completed",
                {
                    "stage": "mechanical_qa",
                    "qa_status": "PASS" if qa_result.ok else "FAIL",
                    "executable_status": qa_result.executable_status,
                    "executable_app_type": qa_result.executable_app_type,
                    "fix_iterations_used": fix_iterations_used,
                },
            )
        finally:
            store.clear_active_step()

    async def _run_single_code_development_async(
        self,
        *,
        run_dir: Path,
        store: StateStore,
        config: LocalRunConfig,
        logs_dir: Path,
        final_plan: str,
        route: RoutingDecision,
        register_process: Callable[[str, str, CodexProcessHandle], None],
    ) -> None:
        generated_app_dir, assignment, _code_result = await run_single_code_stage_async(
            run_dir,
            logs_dir,
            store,
            config,
            final_plan,
            route,
            running_status="code_agent_running",
            process_started=lambda agent_id, handle: register_process("code_agent", agent_id, handle),
        )
        if _control_action(store.load()) == "cancel":
            store.set_status("cancelled")
            return

        fix_iterations_used = 0
        store.set_active_step(stage="mechanical_qa", agent_id="mechanical_qa", interruptible=False)
        qa_result = await asyncio.to_thread(
            run_mechanical_qa_stage,
            run_dir,
            store,
            generated_app_dir,
            attempt_name="single-agent mechanical QA",
            attempt_index=0,
        )
        if route.uses_llm_qa:
            qa_result = await run_llm_qa_stage_async(
                run_dir,
                logs_dir,
                store,
                config,
                run_dir / "contract",
                generated_app_dir,
                qa_result,
                attempt_index=0,
                process_started=lambda agent_id, handle: register_process("llm_qa", agent_id, handle),
            )
        if _control_action(store.load()) == "cancel":
            store.set_status("cancelled")
            return

        while not qa_result.ok and fix_iterations_used < config.max_fix_iterations:
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
            await run_single_code_fix_stage_async(
                run_dir,
                logs_dir,
                store,
                config,
                final_plan,
                route,
                assignment,
                qa_result,
                iteration=fix_iterations_used,
                process_started=lambda agent_id, handle: register_process("fix", agent_id, handle),
            )
            if _control_action(store.load()) == "cancel":
                store.set_status("cancelled")
                return

            store.set_active_step(stage="mechanical_qa", agent_id="mechanical_qa", interruptible=False)
            qa_result = await asyncio.to_thread(
                run_mechanical_qa_stage,
                run_dir,
                store,
                generated_app_dir,
                attempt_name=f"single-agent mechanical QA after fix {fix_iterations_used}",
                attempt_index=fix_iterations_used,
            )
            if route.uses_llm_qa:
                qa_result = await run_llm_qa_stage_async(
                    run_dir,
                    logs_dir,
                    store,
                    config,
                    run_dir / "contract",
                    generated_app_dir,
                    qa_result,
                    attempt_index=fix_iterations_used,
                    process_started=lambda agent_id, handle: register_process("llm_qa", agent_id, handle),
                )
            if _control_action(store.load()) == "cancel":
                store.set_status("cancelled")
                return

        store.clear_control_action()
        store.set_status("awaiting_qa_approval")
        store.append_event(
            "worker_checkpoint",
            "system",
            "Single-code development and mechanical QA completed",
            {
                "stage": "mechanical_qa",
                "route": route.mode,
                "qa_status": "PASS" if qa_result.ok else "FAIL",
                "executable_status": qa_result.executable_status,
                "executable_app_type": qa_result.executable_app_type,
                "fix_iterations_used": fix_iterations_used,
            },
        )

    def mark_development_queued(self, run_id: str) -> None:
        run_dir = self._run_dir(run_id)
        store = StateStore(run_dir)
        state = store.load()
        if _is_cancelled(state):
            store.append_event("worker_skipped", "system", "Development skipped because run is cancelled")
            return
        store.set_status("development_queued")
        store.append_event(
            "worker_checkpoint",
            "system",
            "Development worker migration pending",
            {"stage": "development"},
        )

    def mark_cancelled(self, run_id: str, *, requested_by: str = "local-operator", feedback: str = "") -> None:
        run_dir = self._run_dir(run_id)
        store = StateStore(run_dir)
        store.request_control_action(action="cancel", requested_by=requested_by, feedback=feedback)
        store.set_status("cancelled")
        store.clear_active_step()

    def _run_dir(self, run_id: str) -> Path:
        if not run_id or any(part in run_id for part in ["/", "\\", ".."]):
            raise FileNotFoundError(f"Invalid run id: {run_id}")
        run_dir = (self.runs_root / run_id).resolve()
        runs_root = self.runs_root.resolve()
        try:
            run_dir.relative_to(runs_root)
        except ValueError as exc:
            raise FileNotFoundError(f"Invalid run id: {run_id}") from exc
        if not run_dir.exists() or not run_dir.is_dir():
            raise FileNotFoundError(f"Run not found: {run_id}")
        return run_dir


def local_config_from_state(state: dict[str, Any]) -> LocalRunConfig:
    dashboard_config = state.get("dashboard_config") if isinstance(state.get("dashboard_config"), dict) else {}
    homes = dashboard_config.get("codex_homes") if isinstance(dashboard_config.get("codex_homes"), dict) else {}
    routing = state.get("routing") if isinstance(state.get("routing"), dict) else {}
    planner_count = _int_value(routing.get("planner_count"), _int_value(dashboard_config.get("planner_count"), 2))
    code_agent_count = _int_value(
        routing.get("code_agent_count"),
        _int_value(dashboard_config.get("code_agent_count"), 1),
    )
    qa_agent_count = _int_value(routing.get("qa_agent_count"), _int_value(dashboard_config.get("qa_agent_count"), 0))
    return LocalRunConfig(
        user_request=str(state.get("user_request") or dashboard_config.get("user_request") or ""),
        run_mode=str(dashboard_config.get("run_mode") or "planning_only"),
        planner_count=planner_count,
        code_agent_count=code_agent_count,
        qa_agent_count=qa_agent_count,
        planner_a_codex_home=_optional_str(homes.get("planner_a")),
        planner_b_codex_home=_optional_str(homes.get("planner_b")),
        planner_c_codex_home=_optional_str(homes.get("planner_c")),
        architect_codex_home=_optional_str(homes.get("architect")),
        scaffold_codex_home=_optional_str(homes.get("scaffold")),
        integrator_codex_home=_optional_str(homes.get("integrator")),
        code_agent_codex_homes=_str_list(homes.get("code_agents")),
        qa_agent_codex_homes=_str_list(homes.get("qa_agents")),
        model=_optional_str(dashboard_config.get("model")),
        reasoning_effort=_optional_str(dashboard_config.get("reasoning_effort")),
        agent_configs=_agent_configs(dashboard_config.get("agent_configs")),
        max_fix_iterations=_int_value(dashboard_config.get("max_fix_iterations"), 1),
        timeout_seconds=_int_value(dashboard_config.get("timeout_seconds"), 900),
    )


def _route_from_state(state: dict[str, Any]) -> RoutingDecision:
    payload = state.get("routing")
    if isinstance(payload, dict):
        return RoutingDecision.from_dict(payload)
    mode = str((state.get("dashboard_config") or {}).get("routing_mode") or "balanced")
    return RoutingDecision.from_dict({"requested_mode": mode, "mode": "balanced"})


def _manual_graph_from_state(state: dict[str, Any]) -> dict[str, Any] | None:
    workflow = state.get("workflow")
    if not isinstance(workflow, dict):
        return None
    graph = workflow.get("graph")
    if isinstance(graph, dict) and workflow.get("mode") == "manual":
        return graph
    return None


def _route_from_manual_graph(graph: dict[str, Any], fallback: RoutingDecision) -> RoutingDecision:
    stages = _graph_stages(graph)
    code_agents = _stage_agents(stages, "code")
    qa_agents = [agent for agent in _stage_agents(stages, "qa") if agent != "mechanical_qa"]
    uses_integrator = any(stage.get("type") == "integration" for stage in stages)
    uses_contract = uses_integrator or any(stage.get("type") == "contract" for stage in stages)
    uses_scaffold = uses_integrator or any(stage.get("type") == "scaffold" for stage in stages)
    code_count = max(1, len(code_agents) or fallback.code_agent_count)
    qa_count = max(0, len(qa_agents))
    mode = "parallel" if uses_integrator or code_count > 1 else "balanced"
    pipeline = ["manual_graph", "code_agents" if code_count > 1 else "code_1", "mechanical_qa"]
    if uses_integrator:
        pipeline = ["manual_graph", "architect_contract", "scaffold", "code_agents", "integrator", "mechanical_qa"]
    if qa_count:
        pipeline.append("qa_agent")
    return RoutingDecision(
        requested_mode="manual",
        mode=mode,
        reason="Manual workflow graph execution.",
        planner_count=max(1, len(_stage_agents(stages, "planning")) or fallback.planner_count),
        code_agent_count=code_count,
        qa_agent_count=qa_count,
        pipeline=pipeline,
        uses_contract=uses_contract,
        uses_scaffold=uses_scaffold,
        uses_integrator=uses_integrator,
        uses_llm_qa=qa_count > 0,
    )


def _config_from_manual_graph(config: LocalRunConfig, graph: dict[str, Any]) -> LocalRunConfig:
    stages = _graph_stages(graph)
    code_count = max(1, len(_stage_agents(stages, "code")) or config.code_agent_count)
    qa_count = max(0, len([agent for agent in _stage_agents(stages, "qa") if agent != "mechanical_qa"]))
    return replace(
        config,
        code_agent_count=code_count,
        qa_agent_count=qa_count,
        code_agent_codex_homes=_pad_list(config.code_agent_codex_homes, code_count),
        qa_agent_codex_homes=_pad_list(config.qa_agent_codex_homes, qa_count),
    )


def _graph_stages(graph: dict[str, Any]) -> list[dict[str, Any]]:
    stages = graph.get("stages")
    return [stage for stage in stages if isinstance(stage, dict)] if isinstance(stages, list) else []


def _stage_agents(stages: list[dict[str, Any]], stage_type: str) -> list[str]:
    agents: list[str] = []
    for stage in stages:
        if stage.get("type") != stage_type:
            continue
        raw_agents = stage.get("agents")
        if isinstance(raw_agents, list):
            agents.extend(str(agent) for agent in raw_agents if agent)
    return agents


def _pad_list(values: list[str | None], count: int) -> list[str | None]:
    padded = list(values[:count])
    while len(padded) < count:
        padded.append(None)
    return padded


def workflow_from_route(route: RoutingDecision) -> dict[str, Any]:
    stages: list[dict[str, Any]] = [
        {
            "id": "planning",
            "type": "planning",
            "agents": [item for item in ["planner_a", "planner_b", "planner_c"][: route.planner_count]],
            "parallel": False,
        },
        {"id": "approval_plan", "type": "approval", "after": ["planning"]},
    ]
    if route.uses_contract:
        stages.extend(
            [
                {"id": "contract", "type": "contract", "agents": ["architect"], "parallel": False},
            ]
        )
    stages.append(
        {
            "id": "code",
            "type": "code",
            "agents": [f"code_{index}" for index in range(1, route.code_agent_count + 1)],
            "parallel": route.code_agent_count > 1,
        }
    )
    if route.uses_integrator:
        stages.append({"id": "integration", "type": "integration", "agents": ["integrator"], "after": ["code"]})
    stages.append({"id": "qa", "type": "qa", "agents": ["mechanical_qa"], "after": ["code"]})
    if route.uses_llm_qa:
        stages.append(
            {
                "id": "llm_qa",
                "type": "qa",
                "agents": [f"qa_{index}" for index in range(1, route.qa_agent_count + 1)],
                "parallel": route.qa_agent_count > 1,
            }
        )
    stages.append({"id": "approval_qa", "type": "approval", "after": ["qa"]})
    return {
        "mode": route.requested_mode,
        "resolved_mode": route.mode,
        "stages": stages,
    }


def _control_action(state: dict[str, Any]) -> str:
    control = state.get("control")
    if not isinstance(control, dict):
        return "none"
    return str(control.get("requested_action") or "none")


def _is_cancelled(state: dict[str, Any]) -> bool:
    return state.get("status") == "cancelled" or _control_action(state) == "cancel"


def _load_plan_artifacts(run_dir: Path, state: dict[str, Any]) -> dict[str, str]:
    final_plan = _read_first_existing(
        run_dir,
        [
            _artifact_relative_path(state, "final_plan"),
            "planning/03_final_plan.md",
            "plan.md",
        ],
    )
    if not final_plan:
        raise FileNotFoundError("Approved final plan artifact is missing.")

    planner_a_draft = _read_first_existing(
        run_dir,
        [
            _artifact_relative_path(state, "planner_a_draft"),
            "planning/01_planner_a_draft.md",
        ],
    ) or final_plan
    planner_review = _read_first_existing(
        run_dir,
        [
            _artifact_relative_path(state, "planner_b_review"),
            "planning/02_planner_b_review.md",
        ],
    ) or "(planner review unavailable)"
    return {
        "planner_a_draft": planner_a_draft,
        "planner_review": planner_review,
        "final_plan": final_plan,
    }


def _artifact_relative_path(state: dict[str, Any], name: str) -> str | None:
    artifacts = state.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    value = artifacts.get(name)
    if not isinstance(value, str) or not value:
        return None
    return value


def _read_first_existing(run_dir: Path, relative_paths: list[str | None]) -> str:
    root = run_dir.resolve()
    for relative_path in relative_paths:
        if not relative_path:
            continue
        path = (run_dir / relative_path).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    return ""


def _optional_str(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    return str(value)


def _int_value(value: Any, default: int) -> int:
    if value in {None, ""}:
        return default
    return int(value)


def _str_list(value: Any) -> list[str | None]:
    if not isinstance(value, list):
        return []
    return [str(item) if item else None for item in value]


def _agent_configs(value: Any) -> dict[str, dict[str, object]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, object]] = {}
    for agent_id, config in value.items():
        if isinstance(agent_id, str) and isinstance(config, dict):
            result[agent_id] = dict(config)
    return result
