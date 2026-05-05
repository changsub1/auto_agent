"""Local non-Discord run helpers for the Streamlit dashboard."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Any, Callable

import asyncio
import re

from agents import ArchitectAgent, CodeAgent, IntegratorAgent, PlannerAgentA, PlannerAgentB, QAAgent, ScaffoldAgent
from codex_runner import CodexExecutionError, CodexProcessHandle, CodexResult, run_codex_result, run_codex_result_async
from executable_qa import run_executable_qa
from parallel_workflow import (
    CodeAgentAssignment,
    assign_code_agent_tasks,
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
from state_store import StateStore
from workspace_manager import create_logs_dir, create_run_dir, normalize_windows_command_files, save_text
from workspace_manager import create_generated_app_dir


RUN_MODES = ("planning_only", "contract_only", "scaffold_only", "full_run")
REASONING_EFFORTS = ("", "minimal", "low", "medium", "high", "xhigh")


@dataclass(frozen=True)
class LocalRunConfig:
    user_request: str
    run_mode: str
    planner_count: int
    code_agent_count: int
    qa_agent_count: int
    planner_a_codex_home: str | None
    planner_b_codex_home: str | None
    planner_c_codex_home: str | None
    architect_codex_home: str | None
    scaffold_codex_home: str | None
    integrator_codex_home: str | None
    code_agent_codex_homes: list[str | None]
    qa_agent_codex_homes: list[str | None]
    model: str | None
    reasoning_effort: str | None
    max_fix_iterations: int
    timeout_seconds: int

    @staticmethod
    def from_env() -> "LocalRunConfig":
        return LocalRunConfig(
            user_request="CSV 파일을 업로드하면 미리보기와 결측치 개수를 보여주는 앱 만들어줘",
            run_mode="planning_only",
            planner_count=2,
            code_agent_count=_int_env("CODE_AGENT_COUNT", 2),
            qa_agent_count=_int_env("QA_AGENT_COUNT", 0),
            planner_a_codex_home=_str_env("PLANNER_A_CODEX_HOME"),
            planner_b_codex_home=_str_env("PLANNER_B_CODEX_HOME"),
            planner_c_codex_home=_str_env("PLANNER_C_CODEX_HOME"),
            architect_codex_home=_str_env("ARCHITECT_CODEX_HOME") or _str_env("PLANNER_B_CODEX_HOME"),
            scaffold_codex_home=_str_env("SCAFFOLD_CODEX_HOME") or _str_env("DEVELOPER_CODEX_HOME"),
            integrator_codex_home=_str_env("INTEGRATOR_CODEX_HOME") or _str_env("DEVELOPER_CODEX_HOME"),
            code_agent_codex_homes=_str_list_env("CODE_AGENT_CODEX_HOMES"),
            qa_agent_codex_homes=_str_list_env("QA_AGENT_CODEX_HOMES"),
            model=_str_env("CODEX_MODEL"),
            reasoning_effort=_str_env("CODEX_REASONING_EFFORT"),
            max_fix_iterations=_int_env("MAX_FIX_ITERATIONS", 1),
            timeout_seconds=_int_env("CODEX_TIMEOUT_SECONDS", 900),
        )


def run_local_dashboard_workflow(project_root: Path, config: LocalRunConfig) -> Path:
    """Run planning/contract/scaffold stages locally and return the run directory."""

    if config.run_mode not in RUN_MODES:
        raise ValueError(f"Unsupported run mode: {config.run_mode}")
    if config.run_mode == "full_run":
        raise NotImplementedError("full_run is not wired to the local dashboard yet.")

    run_dir = create_run_dir(project_root)
    logs_dir = create_logs_dir(run_dir)
    store = StateStore(run_dir)
    store.initialize(
        user_request=config.user_request,
        discord={"source": "streamlit_dashboard"},
        max_fix_iterations=config.max_fix_iterations,
        code_agent_count=config.code_agent_count,
        qa_agent_count=config.qa_agent_count,
    )
    _record_dashboard_config(store, config)

    plan_artifacts = run_planning_stage(run_dir, logs_dir, store, config)
    if config.run_mode == "planning_only":
        store.set_status("dashboard_planning_completed")
        return run_dir

    contract_dir = _run_contract(run_dir, logs_dir, store, config, plan_artifacts)
    if config.run_mode == "contract_only":
        store.set_status("dashboard_contract_completed")
        return run_dir

    _run_scaffold(run_dir, logs_dir, store, config, contract_dir)
    store.set_status("dashboard_scaffold_completed")
    return run_dir


def run_planning_stage(
    run_dir: Path,
    logs_dir: Path,
    store: StateStore,
    config: LocalRunConfig,
    *,
    user_feedback: str | None = None,
    running_status: str = "dashboard_planning_running",
) -> dict[str, str]:
    store.set_status(running_status)
    planning_request = config.user_request
    if user_feedback:
        planning_request = "\n\n".join(
            [
                config.user_request,
                "User revision feedback:",
                user_feedback,
            ]
        )
    planner_a = PlannerAgentA(
        codex_home=config.planner_a_codex_home,
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        model=config.model,
        reasoning_effort=config.reasoning_effort,
    )
    draft_result = _call_codex_with_resume(
        lambda session_id: planner_a.create_initial_plan(planning_request, run_dir, session_id=session_id),
        store.get_agent_session_id("planner_a"),
    )
    draft_path = store.write_artifact(
        "planning/01_planner_a_draft.md",
        draft_result.stdout,
        artifact_name="planner_a_draft",
    )
    store.update_agent_session(
        "planner_a",
        session_id=draft_result.session_id,
        codex_home=config.planner_a_codex_home,
        model=draft_result.model,
        reasoning_effort=draft_result.reasoning_effort,
        last_step="draft",
    )
    store.append_event("agent_output", "planner_a", "Planner A draft created", {"path": store.to_relative(draft_path)})
    store.append_transcript("Planner A Draft", draft_result.stdout)
    _raise_if_planning_cancelled(store)

    review_text = "(planner review skipped because planner_count is 1)"
    if config.planner_count >= 2:
        planner_b = PlannerAgentB(
            codex_home=config.planner_b_codex_home,
            logs_dir=logs_dir,
            timeout=config.timeout_seconds,
            model=config.model,
            reasoning_effort=config.reasoning_effort,
        )
        review_result = _call_codex_with_resume(
            lambda session_id: planner_b.review_plan(
                config.user_request,
                draft_result.stdout,
                run_dir,
                user_feedback=user_feedback,
                session_id=session_id,
            ),
            store.get_agent_session_id("planner_b"),
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
            codex_home=config.planner_b_codex_home,
            model=review_result.model,
            reasoning_effort=review_result.reasoning_effort,
            last_step="review",
        )
        store.append_event("agent_output", "planner_b", "Planner B review created", {"path": store.to_relative(review_path)})
        store.append_transcript("Planner B Review", review_text)
        _raise_if_planning_cancelled(store)

    if config.planner_count >= 3:
        planner_c_result = _run_planner_c_review(
            config=config,
            draft=draft_result.stdout,
            review=review_text,
            run_dir=run_dir,
            logs_dir=logs_dir,
        )
        planner_c_path = store.write_artifact(
            "planning/02b_planner_c_risk_review.md",
            planner_c_result.stdout,
            artifact_name="planner_c_review",
        )
        store.update_agent_session(
            "planner_c",
            session_id=planner_c_result.session_id,
            codex_home=config.planner_c_codex_home,
            model=planner_c_result.model,
            reasoning_effort=planner_c_result.reasoning_effort,
            last_step="risk_review",
        )
        store.append_event("agent_output", "planner_c", "Planner C risk review created", {"path": store.to_relative(planner_c_path)})
        store.append_transcript("Planner C Risk Review", planner_c_result.stdout)
        review_text = "\n\n".join([review_text, planner_c_result.stdout])
        _raise_if_planning_cancelled(store)

    if config.planner_count >= 2:
        final_result = _call_codex_with_resume(
            lambda session_id: planner_a.revise_final_plan(
                config.user_request,
                draft_result.stdout,
                review_text,
                run_dir,
                user_feedback=user_feedback,
                session_id=session_id,
            ),
            store.get_agent_session_id("planner_a"),
        )
        final_text = final_result.stdout
        store.update_agent_session(
            "planner_a",
            session_id=final_result.session_id,
            codex_home=config.planner_a_codex_home,
            model=final_result.model,
            reasoning_effort=final_result.reasoning_effort,
            last_step="final_plan",
        )
    else:
        final_text = draft_result.stdout

    final_path = store.write_artifact(
        "planning/03_final_plan.md",
        final_text,
        artifact_name="final_plan",
    )
    save_text(run_dir / "plan.md", final_text)
    store.record_artifact("plan_md", run_dir / "plan.md")
    store.append_event("agent_output", "planner_a", "Final plan created", {"path": store.to_relative(final_path)})
    store.append_transcript("Final Plan", final_text)

    return {
        "planner_a_draft": draft_result.stdout,
        "planner_review": review_text,
        "final_plan": final_text,
    }


async def run_planning_stage_async(
    run_dir: Path,
    logs_dir: Path,
    store: StateStore,
    config: LocalRunConfig,
    *,
    user_feedback: str | None = None,
    running_status: str = "dashboard_planning_running",
    process_started: Callable[[str, CodexProcessHandle], None] | None = None,
) -> dict[str, str]:
    store.set_status(running_status)
    planning_request = config.user_request
    if user_feedback:
        planning_request = "\n\n".join(
            [
                config.user_request,
                "User revision feedback:",
                user_feedback,
            ]
        )
    planner_a = PlannerAgentA(
        codex_home=config.planner_a_codex_home,
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        model=config.model,
        reasoning_effort=config.reasoning_effort,
    )
    draft_result = await _call_codex_with_resume_async(
        lambda session_id: planner_a.create_initial_plan_async(
            planning_request,
            run_dir,
            session_id=session_id,
            process_started=_agent_process_started(process_started, "planner_a"),
        ),
        store.get_agent_session_id("planner_a"),
    )
    draft_path = store.write_artifact(
        "planning/01_planner_a_draft.md",
        draft_result.stdout,
        artifact_name="planner_a_draft",
    )
    store.update_agent_session(
        "planner_a",
        session_id=draft_result.session_id,
        codex_home=config.planner_a_codex_home,
        model=draft_result.model,
        reasoning_effort=draft_result.reasoning_effort,
        last_step="draft",
    )
    store.append_event("agent_output", "planner_a", "Planner A draft created", {"path": store.to_relative(draft_path)})
    store.append_transcript("Planner A Draft", draft_result.stdout)
    _raise_if_cancelled(store, "Planning cancelled")

    review_text = "(planner review skipped because planner_count is 1)"
    if config.planner_count >= 2:
        planner_b = PlannerAgentB(
            codex_home=config.planner_b_codex_home,
            logs_dir=logs_dir,
            timeout=config.timeout_seconds,
            model=config.model,
            reasoning_effort=config.reasoning_effort,
        )
        review_result = await _call_codex_with_resume_async(
            lambda session_id: planner_b.review_plan_async(
                config.user_request,
                draft_result.stdout,
                run_dir,
                user_feedback=user_feedback,
                session_id=session_id,
                process_started=_agent_process_started(process_started, "planner_b"),
            ),
            store.get_agent_session_id("planner_b"),
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
            codex_home=config.planner_b_codex_home,
            model=review_result.model,
            reasoning_effort=review_result.reasoning_effort,
            last_step="review",
        )
        store.append_event("agent_output", "planner_b", "Planner B review created", {"path": store.to_relative(review_path)})
        store.append_transcript("Planner B Review", review_text)
        _raise_if_cancelled(store, "Planning cancelled")

    if config.planner_count >= 3:
        planner_c_result = await _run_planner_c_review_async(
            config=config,
            draft=draft_result.stdout,
            review=review_text,
            run_dir=run_dir,
            logs_dir=logs_dir,
            process_started=_agent_process_started(process_started, "planner_c"),
        )
        planner_c_path = store.write_artifact(
            "planning/02b_planner_c_risk_review.md",
            planner_c_result.stdout,
            artifact_name="planner_c_review",
        )
        store.update_agent_session(
            "planner_c",
            session_id=planner_c_result.session_id,
            codex_home=config.planner_c_codex_home,
            model=planner_c_result.model,
            reasoning_effort=planner_c_result.reasoning_effort,
            last_step="risk_review",
        )
        store.append_event("agent_output", "planner_c", "Planner C risk review created", {"path": store.to_relative(planner_c_path)})
        store.append_transcript("Planner C Risk Review", planner_c_result.stdout)
        review_text = "\n\n".join([review_text, planner_c_result.stdout])
        _raise_if_cancelled(store, "Planning cancelled")

    if config.planner_count >= 2:
        final_result = await _call_codex_with_resume_async(
            lambda session_id: planner_a.revise_final_plan_async(
                config.user_request,
                draft_result.stdout,
                review_text,
                run_dir,
                user_feedback=user_feedback,
                session_id=session_id,
                process_started=_agent_process_started(process_started, "planner_a"),
            ),
            store.get_agent_session_id("planner_a"),
        )
        final_text = final_result.stdout
        store.update_agent_session(
            "planner_a",
            session_id=final_result.session_id,
            codex_home=config.planner_a_codex_home,
            model=final_result.model,
            reasoning_effort=final_result.reasoning_effort,
            last_step="final_plan",
        )
    else:
        final_text = draft_result.stdout

    final_path = store.write_artifact(
        "planning/03_final_plan.md",
        final_text,
        artifact_name="final_plan",
    )
    save_text(run_dir / "plan.md", final_text)
    store.record_artifact("plan_md", run_dir / "plan.md")
    store.append_event("agent_output", "planner_a", "Final plan created", {"path": store.to_relative(final_path)})
    store.append_transcript("Final Plan", final_text)

    return {
        "planner_a_draft": draft_result.stdout,
        "planner_review": review_text,
        "final_plan": final_text,
    }


def _run_contract(
    run_dir: Path,
    logs_dir: Path,
    store: StateStore,
    config: LocalRunConfig,
    plan_artifacts: dict[str, str],
) -> Path:
    store.set_status("dashboard_contract_running")
    contract_dir = create_contract_dir(run_dir)
    architect = ArchitectAgent(
        codex_home=config.architect_codex_home,
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        model=config.model,
        reasoning_effort=config.reasoning_effort,
    )
    result = _call_codex_with_resume(
        lambda session_id: architect.create_contract_bundle_result(
            config.user_request,
            plan_artifacts["planner_a_draft"],
            plan_artifacts["planner_review"],
            plan_artifacts["final_plan"],
            contract_dir,
            session_id=session_id,
        ),
        store.get_agent_session_id("architect"),
    )
    contract_paths = normalize_contract_bundle(contract_dir, config.user_request, plan_artifacts["final_plan"])
    store.record_artifact("contract_dir", contract_dir)
    for path in contract_paths:
        store.record_artifact(f"contract_{path.stem}", path)
    store.update_agent_session(
        "architect",
        session_id=result.session_id,
        codex_home=config.architect_codex_home,
        model=result.model,
        reasoning_effort=result.reasoning_effort,
        last_step="contract_bundle",
    )
    store.append_event(
        "agent_output",
        "architect",
        "Contract bundle created",
        {"path": store.to_relative(contract_dir), "files": [store.to_relative(path) for path in contract_paths]},
    )
    store.append_transcript("Architect Contract Summary", result.stdout)
    return contract_dir


async def run_contract_stage_async(
    run_dir: Path,
    logs_dir: Path,
    store: StateStore,
    config: LocalRunConfig,
    plan_artifacts: dict[str, str],
    *,
    running_status: str = "contract_running",
    process_started: Callable[[str, CodexProcessHandle], None] | None = None,
) -> Path:
    store.set_status(running_status)
    contract_dir = create_contract_dir(run_dir)
    architect = ArchitectAgent(
        codex_home=config.architect_codex_home,
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        model=config.model,
        reasoning_effort=config.reasoning_effort,
    )
    result = await _call_codex_with_resume_async(
        lambda session_id: architect.create_contract_bundle_result_async(
            config.user_request,
            plan_artifacts["planner_a_draft"],
            plan_artifacts["planner_review"],
            plan_artifacts["final_plan"],
            contract_dir,
            session_id=session_id,
            process_started=_agent_process_started(process_started, "architect"),
        ),
        store.get_agent_session_id("architect"),
    )
    contract_paths = normalize_contract_bundle(contract_dir, config.user_request, plan_artifacts["final_plan"])
    store.record_artifact("contract_dir", contract_dir)
    for path in contract_paths:
        store.record_artifact(f"contract_{path.stem}", path)
    store.update_agent_session(
        "architect",
        session_id=result.session_id,
        codex_home=config.architect_codex_home,
        model=result.model,
        reasoning_effort=result.reasoning_effort,
        last_step="contract_bundle",
    )
    store.append_event(
        "agent_output",
        "architect",
        "Contract bundle created",
        {"path": store.to_relative(contract_dir), "files": [store.to_relative(path) for path in contract_paths]},
    )
    store.append_transcript("Architect Contract Summary", result.stdout)
    _raise_if_cancelled(store, "Development cancelled")
    return contract_dir


def _run_scaffold(
    run_dir: Path,
    logs_dir: Path,
    store: StateStore,
    config: LocalRunConfig,
    contract_dir: Path,
) -> Path:
    store.set_status("dashboard_scaffold_running")
    scaffold_dir = create_scaffold_dir(run_dir)
    scaffold = ScaffoldAgent(
        codex_home=config.scaffold_codex_home,
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        model=config.model,
        reasoning_effort=config.reasoning_effort,
    )
    result = _call_codex_with_resume(
        lambda session_id: scaffold.create_scaffold_result(
            config.user_request,
            render_contract_bundle(contract_dir),
            scaffold_dir,
            session_id=session_id,
        ),
        store.get_agent_session_id("scaffold"),
    )
    store.update_agent_session(
        "scaffold",
        session_id=result.session_id,
        codex_home=config.scaffold_codex_home,
        model=result.model,
        reasoning_effort=result.reasoning_effort,
        last_step="scaffold_app",
    )
    store.record_artifact("scaffold_app", scaffold_dir)
    store.append_event("agent_output", "scaffold", "Scaffold app created", {"path": store.to_relative(scaffold_dir)})
    store.append_transcript("Scaffold Output", result.stdout)
    normalize_windows_command_files(scaffold_dir)
    return scaffold_dir


async def run_scaffold_stage_async(
    run_dir: Path,
    logs_dir: Path,
    store: StateStore,
    config: LocalRunConfig,
    contract_dir: Path,
    *,
    running_status: str = "scaffold_running",
    process_started: Callable[[str, CodexProcessHandle], None] | None = None,
) -> Path:
    store.set_status(running_status)
    scaffold_dir = create_scaffold_dir(run_dir)
    scaffold = ScaffoldAgent(
        codex_home=config.scaffold_codex_home,
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        model=config.model,
        reasoning_effort=config.reasoning_effort,
    )
    result = await _call_codex_with_resume_async(
        lambda session_id: scaffold.create_scaffold_result_async(
            config.user_request,
            render_contract_bundle(contract_dir),
            scaffold_dir,
            session_id=session_id,
            process_started=_agent_process_started(process_started, "scaffold"),
        ),
        store.get_agent_session_id("scaffold"),
    )
    store.update_agent_session(
        "scaffold",
        session_id=result.session_id,
        codex_home=config.scaffold_codex_home,
        model=result.model,
        reasoning_effort=result.reasoning_effort,
        last_step="scaffold_app",
    )
    store.record_artifact("scaffold_app", scaffold_dir)
    store.append_event("agent_output", "scaffold", "Scaffold app created", {"path": store.to_relative(scaffold_dir)})
    store.append_transcript("Scaffold Output", result.stdout)
    normalize_windows_command_files(scaffold_dir)
    _raise_if_cancelled(store, "Development cancelled")
    return scaffold_dir


async def run_code_agents_stage_async(
    run_dir: Path,
    logs_dir: Path,
    store: StateStore,
    config: LocalRunConfig,
    contract_dir: Path,
    scaffold_dir: Path,
    *,
    running_status: str = "code_agents_running",
    process_started: Callable[[str, CodexProcessHandle], None] | None = None,
) -> list[CodeAgentAssignment]:
    tasks = load_task_manifest(contract_dir)
    workspaces_dir = create_agent_workspaces_dir(run_dir)
    outputs_dir = create_agent_outputs_dir(run_dir)
    assignments = assign_code_agent_tasks(
        tasks,
        code_agent_count=config.code_agent_count,
        code_agent_codex_homes=config.code_agent_codex_homes,
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
    store.set_status(running_status)
    store.append_event(
        "code_agents_started",
        "system",
        "Parallel code agents started",
        {"agents": [assignment.agent_id for assignment in assignments]},
    )
    contract_bundle = render_contract_bundle(contract_dir)
    code_results = await asyncio.gather(
        *[
            _run_code_agent_assignment_async(
                config=config,
                contract_bundle=contract_bundle,
                assignment=assignment,
                logs_dir=logs_dir,
                session_id=store.get_agent_session_id(assignment.agent_id),
                process_started=_agent_process_started(process_started, assignment.agent_id),
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
            {"path": store.to_relative(output_path), **_session_event_data(code_result)},
        )
        store.append_transcript(f"{assignment.agent_id} Output", code_result.stdout)
        normalize_windows_command_files(assignment.workspace_dir)
    _raise_if_cancelled(store, "Development cancelled")
    return assignments


async def run_integration_stage_async(
    run_dir: Path,
    logs_dir: Path,
    store: StateStore,
    config: LocalRunConfig,
    contract_dir: Path,
    scaffold_dir: Path,
    assignments: list[CodeAgentAssignment],
    *,
    running_status: str = "integration_running",
    process_started: Callable[[str, CodexProcessHandle], None] | None = None,
) -> Path:
    store.set_status(running_status)
    merged_app_dir = create_merged_app_dir(run_dir)
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
        codex_home=config.integrator_codex_home,
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        model=config.model,
        reasoning_effort=config.reasoning_effort,
    )
    integration_result = await _call_codex_with_resume_async(
        lambda session_id: integrator.integrate_result_async(
            config.user_request,
            render_contract_bundle(contract_dir),
            assignment_summary,
            workspace_listing,
            run_dir,
            session_id=session_id,
            process_started=_agent_process_started(process_started, "integrator"),
        ),
        store.get_agent_session_id("integrator"),
    )
    store.update_agent_session(
        "integrator",
        session_id=integration_result.session_id,
        codex_home=config.integrator_codex_home,
        model=integration_result.model,
        reasoning_effort=integration_result.reasoning_effort,
        last_step="integrated_app",
    )
    store.record_artifact("merged_app", merged_app_dir)
    store.append_event(
        "agent_output",
        "integrator",
        "Integration completed",
        {"path": store.to_relative(merged_app_dir), **_session_event_data(integration_result)},
    )
    store.append_transcript("Integrator Output", integration_result.stdout)
    normalize_windows_command_files(merged_app_dir)
    generated_app_dir = reset_generated_app_from_merged(run_dir, merged_app_dir)
    normalize_windows_command_files(generated_app_dir)
    store.record_artifact("generated_app", generated_app_dir)
    _raise_if_cancelled(store, "Development cancelled")
    return generated_app_dir


def run_mechanical_qa_stage(
    run_dir: Path,
    store: StateStore,
    generated_app_dir: Path,
    *,
    attempt_name: str = "integrated mechanical QA",
    attempt_index: int = 0,
    executable_qa_timeout_seconds: int = 90,
    executable_qa_allow_local_commands: bool = False,
) -> QAResult:
    store.set_status("mechanical_qa_running")
    qa_attempt_dir = run_dir / "qa" / f"attempt_{attempt_index:02d}"
    qa_attempt_dir.mkdir(parents=True, exist_ok=True)
    syntax_result = run_python_syntax_check(
        generated_app_dir,
        qa_attempt_dir / "syntax_report.md",
        attempt_name=f"{attempt_name} syntax check",
        fail_on_missing_python=False,
    )
    executable_result = run_executable_qa(
        generated_app_dir,
        qa_attempt_dir,
        attempt_name=f"{attempt_name} executable probe",
        timeout=executable_qa_timeout_seconds,
        allow_local_commands=executable_qa_allow_local_commands,
    )
    qa_result = combine_mechanical_qa_results(
        syntax_result=syntax_result,
        executable_result=executable_result,
        report_path=run_dir / "qa_report.md",
        attempt_name=attempt_name,
    )
    store.record_artifact("qa_report", qa_result.report_path)
    for index, screenshot_path in enumerate(qa_result.screenshots, start=1):
        store.record_artifact(f"qa_screenshot_{index}", screenshot_path)
    for index, artifact_path in enumerate(qa_result.artifact_paths, start=1):
        store.record_artifact(f"qa_artifact_{index}", artifact_path)
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
    return qa_result


async def run_llm_qa_stage_async(
    run_dir: Path,
    logs_dir: Path,
    store: StateStore,
    config: LocalRunConfig,
    contract_dir: Path,
    generated_app_dir: Path,
    mechanical_result: QAResult,
    *,
    attempt_index: int = 0,
    running_status: str = "llm_qa_running",
    process_started: Callable[[str, CodexProcessHandle], None] | None = None,
) -> QAResult:
    qa_agent_count = max(0, config.qa_agent_count)
    if qa_agent_count <= 0:
        return mechanical_result

    store.set_status(running_status)
    contract_bundle = render_contract_bundle(contract_dir) if contract_dir.exists() else ""
    generated_app_listing = list_workspace_files(generated_app_dir)
    attempt_dir = run_dir / "qa" / f"attempt_{attempt_index:02d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)

    async def run_one(index: int) -> tuple[str, str | None, CodexResult]:
        agent_id = f"qa_{index}"
        codex_home = config.qa_agent_codex_homes[(index - 1) % len(config.qa_agent_codex_homes)] if config.qa_agent_codex_homes else None
        agent = QAAgent(
            agent_id=agent_id,
            codex_home=codex_home,
            logs_dir=logs_dir,
            timeout=config.timeout_seconds,
            model=config.model,
            reasoning_effort=config.reasoning_effort,
        )
        result = await agent.review_result_async(
            config.user_request,
            contract_bundle,
            generated_app_listing,
            mechanical_result.report_markdown,
            mechanical_result.screenshots,
            run_dir,
            session_id=store.get_agent_session_id(agent_id),
            process_started=_agent_process_started(process_started, agent_id),
        )
        return agent_id, codex_home, result

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
                **_session_event_data(result),
            },
        )
        store.append_transcript(f"{agent_id} Review", result.stdout)
        review_sections.append(f"### {agent_id} Review\n\n{result.stdout.strip()}")

    llm_ok = not failed_reviews
    ok = mechanical_result.ok and llm_ok
    llm_error_log = "\n".join(failed_reviews)
    error_log = "\n\n".join(part for part in [mechanical_result.error_log, llm_error_log] if part)
    affected_paths = _merge_unique(
        [
            *mechanical_result.affected_paths,
            *[path for section in review_sections for path in _extract_affected_paths(section)],
        ]
    )
    suspected_owners = _merge_unique(
        [
            *mechanical_result.suspected_owners,
            *[owner for section in review_sections for owner in _extract_suspected_owners(section)],
        ]
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
    qa_result = QAResult(
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
    _record_qa_artifacts(store, qa_result)
    store.append_transcript("QA Report", qa_result.report_markdown)
    store.append_event(
        "qa_completed",
        "qa",
        "LLM QA completed",
        {
            "ok": qa_result.ok,
            "checked_files": [path.as_posix() for path in qa_result.checked_files],
            "executable_status": qa_result.executable_status,
            "executable_app_type": qa_result.executable_app_type,
            "affected_paths": qa_result.affected_paths,
            "suspected_owners": qa_result.suspected_owners,
            "screenshots": [store.to_relative(path) for path in qa_result.screenshots],
        },
    )
    return qa_result


async def run_targeted_fix_stage_async(
    run_dir: Path,
    logs_dir: Path,
    store: StateStore,
    config: LocalRunConfig,
    contract_dir: Path,
    scaffold_dir: Path,
    assignments: list[CodeAgentAssignment],
    qa_result: QAResult,
    *,
    iteration: int,
    process_started: Callable[[str, CodexProcessHandle], None] | None = None,
) -> Path:
    contract_bundle = render_contract_bundle(contract_dir)
    feedback = qa_result.error_log or qa_result.report_markdown
    targets = _resolve_fix_targets(assignments, qa_result)
    store.set_status("fix_running")
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
        result = await _run_code_agent_fix_async(
            config=config,
            contract_bundle=contract_bundle,
            assignment=assignment,
            feedback=feedback,
            iteration=iteration,
            logs_dir=logs_dir,
            session_id=store.get_agent_session_id(assignment.agent_id),
            process_started=_agent_process_started(process_started, assignment.agent_id),
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
            {"path": store.to_relative(output_path), **_session_event_data(result)},
        )
        store.append_transcript(f"{assignment.agent_id} Fix {iteration}", result.stdout)
        normalize_windows_command_files(assignment.workspace_dir)

    if code_targets:
        merged_app_dir = create_merged_app_dir(run_dir)
        copy_tree_contents(scaffold_dir, merged_app_dir)
        merge_seed_report = seed_merged_app_from_owned_paths(assignments, merged_app_dir)
        store.write_artifact(
            f"integration/merge_seed_report_fix_{iteration:02d}.md",
            merge_seed_report,
            artifact_name=f"merge_seed_report_fix_{iteration:02d}",
        )

    assignment_summary = render_assignment_summary(assignments)
    workspace_listing = "\n\n".join(
        [
            f"## {assignment.agent_id}\n\n{list_workspace_files(assignment.workspace_dir)}"
            for assignment in assignments
        ]
    )
    integrator = IntegratorAgent(
        codex_home=config.integrator_codex_home,
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        model=config.model,
        reasoning_effort=config.reasoning_effort,
    )
    repair_result = await _call_codex_with_resume_async(
        lambda session_id: integrator.repair_integration_result_async(
            config.user_request,
            contract_bundle,
            assignment_summary,
            workspace_listing,
            feedback,
            run_dir,
            iteration=iteration,
            session_id=session_id,
            process_started=_agent_process_started(process_started, "integrator"),
        ),
        store.get_agent_session_id("integrator"),
    )
    store.update_agent_session(
        "integrator",
        session_id=repair_result.session_id,
        codex_home=config.integrator_codex_home,
        model=repair_result.model,
        reasoning_effort=repair_result.reasoning_effort,
        last_step=f"fix_{iteration}",
    )
    store.append_event("agent_output", "integrator", "Integrator repair completed", _session_event_data(repair_result))
    store.append_transcript(f"Integrator Repair {iteration}", repair_result.stdout)
    merged_app_dir = run_dir / "integration" / "merged_app"
    normalize_windows_command_files(merged_app_dir)
    generated_app_dir = reset_generated_app_from_merged(run_dir, merged_app_dir)
    normalize_windows_command_files(generated_app_dir)
    store.record_artifact("generated_app", generated_app_dir)
    return generated_app_dir


def build_single_code_assignment(config: LocalRunConfig, generated_app_dir: Path) -> CodeAgentAssignment:
    return CodeAgentAssignment(
        agent_id="code_1",
        codex_home=config.code_agent_codex_homes[0] if config.code_agent_codex_homes else None,
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


def render_single_code_context(final_plan: str, route: Any) -> str:
    return "\n\n".join(
        [
            "# Approved Plan",
            final_plan.strip() or "(missing final plan)",
            "# Routing",
            f"- mode: {getattr(route, 'mode', 'single')}",
            f"- reason: {getattr(route, 'reason', 'Single-code route selected.')}",
            "# App Manifest Requirement",
            (
                "Create `codex_app_manifest.json` in the app root. It must describe safe local "
                "setup, test, smoke, server, or browser checks using JSON array commands, not shell strings. "
                "Prefer checks that need no network and no human input."
            ),
        ]
    )


async def run_single_code_stage_async(
    run_dir: Path,
    logs_dir: Path,
    store: StateStore,
    config: LocalRunConfig,
    final_plan: str,
    route: Any,
    *,
    running_status: str = "code_agent_running",
    process_started: Callable[[str, CodexProcessHandle], None] | None = None,
) -> tuple[Path, CodeAgentAssignment, CodexResult]:
    generated_app_dir = create_generated_app_dir(run_dir)
    outputs_dir = create_agent_outputs_dir(run_dir)
    assignment = build_single_code_assignment(config, generated_app_dir)
    assignment_summary = render_assignment_summary([assignment])

    store.record_artifact("generated_app", generated_app_dir)
    store.record_artifact("agent_outputs", outputs_dir)
    store.write_artifact(
        "agent_outputs/assignment_summary.md",
        assignment_summary,
        artifact_name="assignment_summary",
    )
    store.set_status(running_status)
    store.append_event(
        "code_agents_started",
        "system",
        "Single code agent started",
        {"agents": [assignment.agent_id], "route": getattr(route, "mode", "single")},
    )
    result = await _run_code_agent_assignment_async(
        config=config,
        contract_bundle=render_single_code_context(final_plan, route),
        assignment=assignment,
        logs_dir=logs_dir,
        session_id=store.get_agent_session_id(assignment.agent_id),
        process_started=_agent_process_started(process_started, assignment.agent_id),
    )
    output_path = store.write_artifact(
        "agent_outputs/code_1_summary.md",
        result.stdout,
        artifact_name="code_1_summary",
    )
    store.update_agent_session(
        assignment.agent_id,
        session_id=result.session_id,
        codex_home=assignment.codex_home,
        model=result.model,
        reasoning_effort=result.reasoning_effort,
        last_step="implement_tasks",
    )
    store.append_event(
        "agent_output",
        assignment.agent_id,
        "Code agent completed assigned tasks",
        {"path": store.to_relative(output_path), **_session_event_data(result)},
    )
    store.append_transcript("code_1 Output", result.stdout)
    normalize_windows_command_files(generated_app_dir)
    _raise_if_cancelled(store, "Development cancelled")
    return generated_app_dir, assignment, result


async def run_single_code_fix_stage_async(
    run_dir: Path,
    logs_dir: Path,
    store: StateStore,
    config: LocalRunConfig,
    final_plan: str,
    route: Any,
    assignment: CodeAgentAssignment,
    qa_result: QAResult,
    *,
    iteration: int,
    process_started: Callable[[str, CodexProcessHandle], None] | None = None,
) -> CodexResult:
    store.set_status("fix_running")
    store.append_event(
        "fix_routing",
        "system",
        "Routed QA fix to single code agent",
        {
            "iteration": iteration,
            "targets": [assignment.agent_id],
            "affected_paths": qa_result.affected_paths,
            "suspected_owners": qa_result.suspected_owners,
        },
    )
    result = await _run_code_agent_fix_async(
        config=config,
        contract_bundle=render_single_code_context(final_plan, route),
        assignment=assignment,
        feedback=qa_result.error_log or qa_result.report_markdown,
        iteration=iteration,
        logs_dir=logs_dir,
        session_id=store.get_agent_session_id(assignment.agent_id),
        process_started=_agent_process_started(process_started, assignment.agent_id),
    )
    output_path = store.write_artifact(
        f"agent_outputs/code_1_fix_{iteration:02d}.md",
        result.stdout,
        artifact_name=f"code_1_fix_{iteration:02d}",
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
        {"path": store.to_relative(output_path), **_session_event_data(result)},
    )
    store.append_transcript(f"code_1 Fix {iteration}", result.stdout)
    normalize_windows_command_files(assignment.workspace_dir)
    _raise_if_cancelled(store, "Development cancelled")
    return result


async def _run_code_agent_assignment_async(
    *,
    config: LocalRunConfig,
    contract_bundle: str,
    assignment: CodeAgentAssignment,
    logs_dir: Path,
    session_id: str | None = None,
    process_started: Callable[[CodexProcessHandle], None] | None = None,
) -> CodexResult:
    code_agent = CodeAgent(
        agent_id=assignment.agent_id,
        codex_home=assignment.codex_home,
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        model=config.model,
        reasoning_effort=config.reasoning_effort,
    )
    return await _call_codex_with_resume_async(
        lambda candidate_session_id: code_agent.implement_tasks_result_async(
            config.user_request,
            contract_bundle,
            assignment.to_prompt_json(),
            assignment.workspace_dir,
            session_id=candidate_session_id,
            process_started=process_started,
        ),
        session_id,
    )


async def _run_code_agent_fix_async(
    *,
    config: LocalRunConfig,
    contract_bundle: str,
    assignment: CodeAgentAssignment,
    feedback: str,
    iteration: int,
    logs_dir: Path,
    session_id: str | None = None,
    process_started: Callable[[CodexProcessHandle], None] | None = None,
) -> CodexResult:
    code_agent = CodeAgent(
        agent_id=assignment.agent_id,
        codex_home=assignment.codex_home,
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        model=config.model,
        reasoning_effort=config.reasoning_effort,
    )
    return await _call_codex_with_resume_async(
        lambda candidate_session_id: code_agent.fix_assigned_tasks_result_async(
            config.user_request,
            contract_bundle,
            assignment.to_prompt_json(),
            feedback,
            assignment.workspace_dir,
            iteration=iteration,
            session_id=candidate_session_id,
            process_started=process_started,
        ),
        session_id,
    )


def _run_planner_c_review(
    *,
    config: LocalRunConfig,
    draft: str,
    review: str,
    run_dir: Path,
    logs_dir: Path,
) -> CodexResult:
    prompt = dedent(
        f"""
        You are Planner Agent C in a local multi-agent development workflow.
        Review the current plan only for implementation risk, parallel task
        boundaries, missing acceptance criteria, and likely integration issues.
        Do not rewrite the full plan.

        User request:
        {config.user_request}

        Planner A draft:
        {draft}

        Existing planner review:
        {review}

        Return Markdown starting with "# Planner C Risk Review".
        """
    ).strip()
    return run_codex_result(
        prompt,
        workdir=run_dir,
        codex_home=config.planner_c_codex_home,
        timeout=config.timeout_seconds,
        logs_dir=logs_dir,
        label="planner_c_risk_review",
        sandbox="workspace-write",
        model=config.model,
        reasoning_effort=config.reasoning_effort,
    )


async def _run_planner_c_review_async(
    *,
    config: LocalRunConfig,
    draft: str,
    review: str,
    run_dir: Path,
    logs_dir: Path,
    process_started: Callable[[CodexProcessHandle], None] | None = None,
) -> CodexResult:
    prompt = dedent(
        f"""
        You are Planner Agent C in a local multi-agent development workflow.
        Review the current plan only for implementation risk, parallel task
        boundaries, missing acceptance criteria, and likely integration issues.
        Do not rewrite the full plan.

        User request:
        {config.user_request}

        Planner A draft:
        {draft}

        Existing planner review:
        {review}

        Return Markdown starting with "# Planner C Risk Review".
        """
    ).strip()
    return await run_codex_result_async(
        prompt,
        workdir=run_dir,
        codex_home=config.planner_c_codex_home,
        timeout=config.timeout_seconds,
        logs_dir=logs_dir,
        label="planner_c_risk_review",
        sandbox="workspace-write",
        model=config.model,
        reasoning_effort=config.reasoning_effort,
        process_started=process_started,
    )


def _agent_process_started(
    process_started: Callable[[str, CodexProcessHandle], None] | None,
    agent_id: str,
) -> Callable[[CodexProcessHandle], None] | None:
    if process_started is None:
        return None

    def notify(handle: CodexProcessHandle) -> None:
        process_started(agent_id, handle)

    return notify


def _call_codex_with_resume(func: Callable[[str | None], CodexResult], session_id: str | None) -> CodexResult:
    try:
        return func(session_id)
    except CodexExecutionError:
        if not session_id:
            raise
        return func(None)


async def _call_codex_with_resume_async(
    func: Callable[[str | None], Any],
    session_id: str | None,
) -> CodexResult:
    try:
        return await func(session_id)
    except CodexExecutionError:
        if not session_id:
            raise
        return await func(None)


def _raise_if_planning_cancelled(store: StateStore) -> None:
    _raise_if_cancelled(store, "Planning cancelled")


def _raise_if_cancelled(store: StateStore, message: str) -> None:
    state = store.load()
    control = state.get("control")
    requested_action = control.get("requested_action") if isinstance(control, dict) else None
    if state.get("status") == "cancelled" or requested_action == "cancel":
        raise RuntimeError(message)


def _session_event_data(result: CodexResult) -> dict[str, str | None]:
    return {
        "session_id": result.session_id,
        "resumed_session_id": result.resumed_session_id,
        "model": result.model,
        "reasoning_effort": result.reasoning_effort,
    }


def _record_qa_artifacts(store: StateStore, qa_result: QAResult) -> None:
    store.record_artifact("qa_report", qa_result.report_path)
    for index, screenshot_path in enumerate(qa_result.screenshots, start=1):
        store.record_artifact(f"qa_screenshot_{index}", screenshot_path)
    for index, artifact_path in enumerate(qa_result.artifact_paths, start=1):
        store.record_artifact(f"qa_artifact_{index}", artifact_path)


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
        if not in_section or not stripped.startswith("-"):
            continue
        value = stripped[1:].strip().strip("`")
        if value.lower() in {"none", "n/a", "unknown", ""}:
            continue
        values.append(value.replace("\\", "/"))
    return _merge_unique(values)


def _resolve_fix_targets(assignments: list[CodeAgentAssignment], qa_result: QAResult) -> list[str]:
    targets: list[str] = []
    for owner in qa_result.suspected_owners:
        normalized = owner.strip().lower()
        if normalized == "integrator" or re.fullmatch(r"code_\d+", normalized):
            targets.append(normalized)
    for affected_path in qa_result.affected_paths:
        owner = _owner_for_path(assignments, affected_path)
        if owner:
            targets.append(owner)
    if not targets:
        targets.append("integrator")
    return _merge_unique(targets)


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


def _record_dashboard_config(store: StateStore, config: LocalRunConfig) -> None:
    payload = {
        "source": "streamlit_dashboard",
        "run_mode": config.run_mode,
        "planner_count": config.planner_count,
        "code_agent_count": config.code_agent_count,
        "qa_agent_count": config.qa_agent_count,
        "model": config.model,
        "reasoning_effort": config.reasoning_effort,
        "max_fix_iterations": config.max_fix_iterations,
        "timeout_seconds": config.timeout_seconds,
        "codex_homes": {
            "planner_a": config.planner_a_codex_home,
            "planner_b": config.planner_b_codex_home,
            "planner_c": config.planner_c_codex_home,
            "architect": config.architect_codex_home,
            "scaffold": config.scaffold_codex_home,
            "integrator": config.integrator_codex_home,
            "code_agents": config.code_agent_codex_homes,
            "qa_agents": config.qa_agent_codex_homes,
        },
    }
    state = store.load()
    state["dashboard_config"] = payload
    store.save(state)
    store.append_event("dashboard_config", "dashboard", "Dashboard run configuration saved", _redact_empty(payload))


def _str_env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    return int(value)


def _str_list_env(name: str) -> list[str | None]:
    value = os.environ.get(name, "").strip()
    if not value:
        return []
    return [part.strip() or None for part in value.split(",") if part.strip()]


def _redact_empty(payload: dict) -> dict:
    return json.loads(json.dumps(payload, ensure_ascii=False))
