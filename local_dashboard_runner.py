"""Local non-Discord run helpers for the Streamlit dashboard."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Any, Callable

import asyncio
import re

from agents import ArchitectAgent, CodeAgent, IntegratorAgent, PlannerAgentA, PlannerAgentB, QAAgent, ScaffoldAgent
from codex_runner import CodexExecutionError, CodexProcessHandle, CodexResult, run_codex_result, run_codex_result_async
from executable_qa import run_executable_qa
from prompt_templates import load_agent_system_prompt
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


def _debug_artifacts_enabled() -> bool:
    value = os.environ.get("ORCHESTRA_DEBUG_ARTIFACTS", "")
    return value.strip().lower() in {"1", "true", "yes", "on", "debug"}


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
    agent_configs: dict[str, dict[str, object]]
    prompt_overrides: dict[str, dict[str, str]]
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
            agent_configs={},
            prompt_overrides={},
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
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        system_prompt=_agent_system_prompt(config, "planner_a"),
        reference_markdown=_agent_skill_markdown(config, "planner_a"),
        **_agent_run_kwargs(config, "planner_a", config.planner_a_codex_home),
    )
    draft_result = _call_codex_with_resume(
        lambda session_id: planner_a.create_initial_plan(planning_request, run_dir, session_id=session_id),
        store.get_agent_session_id("planner_a"),
    )
    _snapshot_final_prompts_from_logs(store)
    draft_path = store.write_artifact(
        "planning/01_planner_a_draft.md",
        draft_result.stdout,
        artifact_name="planner_a_draft",
    )
    store.update_agent_session(
        "planner_a",
        session_id=draft_result.session_id,
        codex_home=_agent_codex_home(config, "planner_a", config.planner_a_codex_home),
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
            logs_dir=logs_dir,
            timeout=config.timeout_seconds,
            system_prompt=_agent_system_prompt(config, "planner_b"),
            reference_markdown=_agent_skill_markdown(config, "planner_b"),
            **_agent_run_kwargs(config, "planner_b", config.planner_b_codex_home),
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
        _snapshot_final_prompts_from_logs(store)
        review_text = review_result.stdout
        review_path = store.write_artifact(
            "planning/02_planner_b_review.md",
            review_text,
            artifact_name="planner_b_review",
        )
        store.update_agent_session(
            "planner_b",
            session_id=review_result.session_id,
            codex_home=_agent_codex_home(config, "planner_b", config.planner_b_codex_home),
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
        _snapshot_final_prompts_from_logs(store)
        planner_c_path = store.write_artifact(
            "planning/02b_planner_c_risk_review.md",
            planner_c_result.stdout,
            artifact_name="planner_c_review",
        )
        store.update_agent_session(
            "planner_c",
            session_id=planner_c_result.session_id,
            codex_home=_agent_codex_home(config, "planner_c", config.planner_c_codex_home),
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
        _snapshot_final_prompts_from_logs(store)
        final_text = final_result.stdout
        store.update_agent_session(
            "planner_a",
            session_id=final_result.session_id,
            codex_home=_agent_codex_home(config, "planner_a", config.planner_a_codex_home),
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
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        system_prompt=_agent_system_prompt(config, "planner_a"),
        reference_markdown=_agent_skill_markdown(config, "planner_a"),
        **_agent_run_kwargs(config, "planner_a", config.planner_a_codex_home),
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
    _snapshot_final_prompts_from_logs(store)
    draft_path = store.write_artifact(
        "planning/01_planner_a_draft.md",
        draft_result.stdout,
        artifact_name="planner_a_draft",
    )
    store.update_agent_session(
        "planner_a",
        session_id=draft_result.session_id,
        codex_home=_agent_codex_home(config, "planner_a", config.planner_a_codex_home),
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
            logs_dir=logs_dir,
            timeout=config.timeout_seconds,
            system_prompt=_agent_system_prompt(config, "planner_b"),
            reference_markdown=_agent_skill_markdown(config, "planner_b"),
            **_agent_run_kwargs(config, "planner_b", config.planner_b_codex_home),
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
        _snapshot_final_prompts_from_logs(store)
        review_text = review_result.stdout
        review_path = store.write_artifact(
            "planning/02_planner_b_review.md",
            review_text,
            artifact_name="planner_b_review",
        )
        store.update_agent_session(
            "planner_b",
            session_id=review_result.session_id,
            codex_home=_agent_codex_home(config, "planner_b", config.planner_b_codex_home),
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
        _snapshot_final_prompts_from_logs(store)
        planner_c_path = store.write_artifact(
            "planning/02b_planner_c_risk_review.md",
            planner_c_result.stdout,
            artifact_name="planner_c_review",
        )
        store.update_agent_session(
            "planner_c",
            session_id=planner_c_result.session_id,
            codex_home=_agent_codex_home(config, "planner_c", config.planner_c_codex_home),
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
        _snapshot_final_prompts_from_logs(store)
        final_text = final_result.stdout
        store.update_agent_session(
            "planner_a",
            session_id=final_result.session_id,
            codex_home=_agent_codex_home(config, "planner_a", config.planner_a_codex_home),
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
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        system_prompt=_agent_system_prompt(config, "architect"),
        reference_markdown=_agent_skill_markdown(config, "architect"),
        **_agent_run_kwargs(config, "architect", config.architect_codex_home),
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
    _snapshot_final_prompts_from_logs(store)
    contract_paths = normalize_contract_bundle(contract_dir, config.user_request, plan_artifacts["final_plan"])
    store.record_artifact("contract_dir", contract_dir)
    for path in contract_paths:
        store.record_artifact(f"contract_{path.stem}", path)
    store.update_agent_session(
        "architect",
        session_id=result.session_id,
        codex_home=_agent_codex_home(config, "architect", config.architect_codex_home),
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
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        system_prompt=_agent_system_prompt(config, "architect"),
        reference_markdown=_agent_skill_markdown(config, "architect"),
        **_agent_run_kwargs(config, "architect", config.architect_codex_home),
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
    _snapshot_final_prompts_from_logs(store)
    contract_paths = normalize_contract_bundle(contract_dir, config.user_request, plan_artifacts["final_plan"])
    store.record_artifact("contract_dir", contract_dir)
    for path in contract_paths:
        store.record_artifact(f"contract_{path.stem}", path)
    store.update_agent_session(
        "architect",
        session_id=result.session_id,
        codex_home=_agent_codex_home(config, "architect", config.architect_codex_home),
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
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        system_prompt=_agent_system_prompt(config, "scaffold"),
        reference_markdown=_agent_skill_markdown(config, "scaffold"),
        **_agent_run_kwargs(config, "scaffold", config.scaffold_codex_home),
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
    _snapshot_final_prompts_from_logs(store)
    store.update_agent_session(
        "scaffold",
        session_id=result.session_id,
        codex_home=_agent_codex_home(config, "scaffold", config.scaffold_codex_home),
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
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        system_prompt=_agent_system_prompt(config, "scaffold"),
        reference_markdown=_agent_skill_markdown(config, "scaffold"),
        **_agent_run_kwargs(config, "scaffold", config.scaffold_codex_home),
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
    _snapshot_final_prompts_from_logs(store)
    store.update_agent_session(
        "scaffold",
        session_id=result.session_id,
        codex_home=_agent_codex_home(config, "scaffold", config.scaffold_codex_home),
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
    for assignment in assignments:
        _copy_run_inputs_to_workspace(run_dir, assignment.workspace_dir)
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
    _snapshot_final_prompts_from_logs(store)
    for assignment, code_result in zip(assignments, code_results, strict=True):
        output_path = store.write_artifact(
            f"agent_outputs/{assignment.agent_id}_summary.md",
            code_result.stdout,
            artifact_name=f"{assignment.agent_id}_summary",
        )
        store.update_agent_session(
            assignment.agent_id,
            session_id=code_result.session_id,
            codex_home=_agent_codex_home(config, assignment.agent_id, assignment.codex_home),
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
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        system_prompt=_agent_system_prompt(config, "integrator"),
        reference_markdown=_agent_skill_markdown(config, "integrator"),
        **_agent_run_kwargs(config, "integrator", config.integrator_codex_home),
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
    _snapshot_final_prompts_from_logs(store)
    store.update_agent_session(
        "integrator",
        session_id=integration_result.session_id,
        codex_home=_agent_codex_home(config, "integrator", config.integrator_codex_home),
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
    _copy_run_inputs_to_workspace(run_dir, generated_app_dir)
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
            "artifact_paths": [store.to_relative(path) for path in qa_result.artifact_paths],
            "report_path": store.to_relative(qa_result.report_path),
        },
    )
    return qa_result


async def run_llm_qa_scenario_plan_stage_async(
    run_dir: Path,
    logs_dir: Path,
    store: StateStore,
    config: LocalRunConfig,
    contract_dir: Path,
    generated_app_dir: Path,
    *,
    attempt_index: int = 0,
    process_started: Callable[[str, CodexProcessHandle], None] | None = None,
) -> Path | None:
    qa_agent_count = max(0, config.qa_agent_count)
    if qa_agent_count <= 0:
        return None

    store.set_status("llm_qa_planning")
    contract_bundle = render_contract_bundle(contract_dir) if contract_dir.exists() else ""
    generated_app_listing = list_workspace_files(generated_app_dir)
    attempt_dir = run_dir / "qa" / f"attempt_{attempt_index:02d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)

    agent_id = "qa_1"
    codex_home = config.qa_agent_codex_homes[0] if config.qa_agent_codex_homes else None
    agent = QAAgent(
        agent_id=agent_id,
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        system_prompt=_agent_system_prompt(config, agent_id),
        reference_markdown=_agent_skill_markdown(config, agent_id),
        **_agent_run_kwargs(config, agent_id, codex_home),
    )
    result = await agent.plan_scenarios_async(
        config.user_request,
        contract_bundle,
        generated_app_listing,
        run_dir,
        session_id=store.get_agent_session_id(agent_id),
        process_started=_agent_process_started(process_started, agent_id),
    )
    _snapshot_final_prompts_from_logs(store)

    plan_path = store.write_artifact(
        f"qa/attempt_{attempt_index:02d}/{agent_id}_scenario_plan.md",
        result.stdout,
        artifact_name=f"{agent_id}_scenario_plan",
    )
    store.update_agent_session(
        agent_id,
        session_id=result.session_id,
        codex_home=_agent_codex_home(config, agent_id, codex_home),
        model=result.model,
        reasoning_effort=result.reasoning_effort,
        last_step=f"scenario_plan_attempt_{attempt_index}",
    )

    scenario_payload, parse_error = _extract_json_object(result.stdout)
    scenario_path: Path | None = None
    event_data: dict[str, Any] = {
        "path": store.to_relative(plan_path),
        **_session_event_data(result),
    }
    if scenario_payload is None:
        error_path = store.write_artifact(
            f"qa/attempt_{attempt_index:02d}/qa_scenario_plan_error.md",
            f"# QA Scenario Plan Error\n\n{parse_error or 'No JSON object found.'}\n",
            artifact_name=f"qa_scenario_plan_error_{attempt_index:02d}",
        )
        event_data.update({"scenario_status": "invalid", "error_path": store.to_relative(error_path)})
    else:
        scenario_path = store.write_artifact(
            f"qa/attempt_{attempt_index:02d}/qa_scenarios.json",
            json.dumps(scenario_payload, ensure_ascii=False, indent=2) + "\n",
            artifact_name=f"qa_scenarios_{attempt_index:02d}",
        )
        event_data.update({"scenario_status": "ready", "scenario_path": store.to_relative(scenario_path)})

    store.append_event(
        "agent_output",
        agent_id,
        "QA Agent scenario plan completed",
        event_data,
    )
    store.append_transcript(f"{agent_id} Scenario Plan", result.stdout)
    return scenario_path


async def run_llm_qa_stage_async(
    run_dir: Path,
    logs_dir: Path,
    store: StateStore,
    config: LocalRunConfig,
    contract_dir: Path,
    generated_app_dir: Path,
    mechanical_result: QAResult | None = None,
    *,
    attempt_index: int = 0,
    running_status: str = "llm_qa_running",
    process_started: Callable[[str, CodexProcessHandle], None] | None = None,
) -> QAResult:
    if mechanical_result is None:
        mechanical_result = make_agentic_qa_baseline_result(
            run_dir,
            generated_app_dir,
            attempt_index=attempt_index,
        )

    qa_agent_count = max(0, config.qa_agent_count)
    if qa_agent_count <= 0:
        return mechanical_result

    store.set_status(running_status)
    contract_bundle = render_contract_bundle(contract_dir) if contract_dir.exists() else ""
    generated_app_listing = list_workspace_files(generated_app_dir)
    attempt_dir = run_dir / "qa" / f"attempt_{attempt_index:02d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)

    async def run_one(index: int) -> dict[str, Any]:
        agent_id = f"qa_{index}"
        codex_home = config.qa_agent_codex_homes[(index - 1) % len(config.qa_agent_codex_homes)] if config.qa_agent_codex_homes else None
        workspace_dir = _prepare_qa_workspace(
            run_dir=run_dir,
            attempt_dir=attempt_dir,
            generated_app_dir=generated_app_dir,
            agent_id=agent_id,
            user_request=config.user_request,
            contract_bundle=contract_bundle,
            generated_app_listing=generated_app_listing,
            mechanical_qa_report=mechanical_result.report_markdown,
        )
        agent = QAAgent(
            agent_id=agent_id,
            logs_dir=logs_dir,
            timeout=config.timeout_seconds,
            system_prompt=_agent_system_prompt(config, agent_id),
            reference_markdown=_agent_skill_markdown(config, agent_id),
            **_agent_run_kwargs(config, agent_id, codex_home),
        )
        agent_error = ""
        try:
            result = await agent.run_workspace_qa_async(
                config.user_request,
                contract_bundle,
                generated_app_listing,
                mechanical_result.report_markdown,
                workspace_dir,
                session_id=store.get_agent_session_id(agent_id),
                process_started=_agent_process_started(process_started, agent_id),
                image_paths=mechanical_result.screenshots,
            )
            host_browser_evidence = await asyncio.to_thread(
                _run_host_browser_evidence,
                workspace_dir,
                mechanical_result=mechanical_result,
            )
            if host_browser_evidence.get("ran"):
                followup_result = await agent.run_workspace_qa_followup_async(
                    workspace_dir,
                    json.dumps(host_browser_evidence, ensure_ascii=False, indent=2),
                    session_id=result.session_id or store.get_agent_session_id(agent_id),
                    process_started=_agent_process_started(process_started, agent_id),
                    image_paths=[
                        Path(path)
                        for path in host_browser_evidence.get("screenshot_paths", [])
                        if isinstance(path, str)
                    ],
                )
                result = _combine_codex_results(
                    result,
                    followup_result,
                    separator="## Host Browser Evidence Follow-up",
                )
        except CodexExecutionError as exc:
            agent_error = str(exc)
            _write_workspace_fallback_verdict(
                workspace_dir,
                status="FAIL",
                summary=f"QA workspace agent failed before producing a usable verdict: {exc}",
            )
            result = CodexResult(
                stdout=exc.stdout or f"QA_STATUS: FAIL\n\n{exc}",
                stderr=exc.stderr,
                returncode=exc.returncode or 1,
                session_id=store.get_agent_session_id(agent_id),
                resumed_session_id=store.get_agent_session_id(agent_id),
                model=_agent_model(config, agent_id),
                reasoning_effort=_agent_reasoning_effort(config, agent_id),
                effective_approval=None,
                effective_sandbox=None,
            )
        return {
            "agent_id": agent_id,
            "codex_home": codex_home,
            "workspace_dir": workspace_dir,
            "result": result,
            "agent_error": agent_error,
        }

    reviews = await asyncio.gather(*[run_one(index) for index in range(1, qa_agent_count + 1)])
    _snapshot_final_prompts_from_logs(store)
    review_sections: list[str] = []
    failed_reviews: list[str] = []
    fix_feedback_sections: list[str] = []
    artifact_paths = list(mechanical_result.artifact_paths)
    screenshots = list(mechanical_result.screenshots)
    affected_paths = list(mechanical_result.affected_paths)
    suspected_owners = list(mechanical_result.suspected_owners)

    for review in reviews:
        agent_id = str(review["agent_id"])
        codex_home = review["codex_home"]
        result = review["result"]
        workspace_dir = Path(review["workspace_dir"])
        agent_error = str(review.get("agent_error") or "")

        output_path = run_dir / "qa" / f"attempt_{attempt_index:02d}" / f"{agent_id}_workspace_qa.md"
        _write_text(output_path, result.stdout or agent_error or "QA workspace agent produced no stdout.")
        verdict, verdict_path, verdict_error = _load_or_create_workspace_verdict(workspace_dir)
        workspace_screenshots = _collect_qa_workspace_screenshots(workspace_dir)
        hard_policy_errors = _workspace_hard_policy_errors(
            verdict=verdict,
            workspace_dir=workspace_dir,
            mechanical_result=mechanical_result,
            screenshots=[*screenshots, *workspace_screenshots],
        )
        if hard_policy_errors and _workspace_verdict_status(verdict) == "PASS":
            _downgrade_workspace_verdict(verdict_path, verdict, hard_policy_errors)
            verdict, _, verdict_error = _load_or_create_workspace_verdict(workspace_dir)

        status = _workspace_verdict_status(verdict)
        findings_path = workspace_dir / "evidence" / "qa_findings.md"
        command_log_path = workspace_dir / "evidence" / "command_log.jsonl"
        scratch_cleanup = _cleanup_qa_scratch(workspace_dir)
        pruned_debug_artifacts = _prune_qa_workspace_debug_artifacts(workspace_dir)
        manifest_path = _write_qa_evidence_manifest(
            workspace_dir=workspace_dir,
            agent_id=agent_id,
            verdict=verdict,
            verdict_path=verdict_path,
            findings_path=findings_path,
            command_log_path=command_log_path,
            screenshots=workspace_screenshots,
            mechanical_result=mechanical_result,
            status=status,
            verdict_error=verdict_error,
            hard_policy_errors=hard_policy_errors,
            scratch_cleanup=scratch_cleanup,
            pruned_debug_artifacts=pruned_debug_artifacts,
        )
        workspace_artifacts = _collect_qa_workspace_artifacts(workspace_dir)
        if status != "PASS":
            failed_reviews.append(f"{agent_id}: {status}")
        if hard_policy_errors:
            failed_reviews.extend(f"{agent_id}: hard policy - {error}" for error in hard_policy_errors)
        if verdict_error:
            failed_reviews.append(f"{agent_id}: verdict error - {verdict_error}")
        if status != "PASS" or hard_policy_errors or verdict_error:
            fix_feedback_sections.append(
                _workspace_fix_feedback_section(
                    agent_id=agent_id,
                    workspace_dir=workspace_dir,
                    verdict=verdict,
                    verdict_path=verdict_path,
                    findings_path=findings_path,
                    verdict_error=verdict_error,
                    hard_policy_errors=hard_policy_errors,
                )
            )

        artifact_paths.extend(workspace_artifacts)
        screenshots.extend(workspace_screenshots)
        affected_paths = _merge_unique(
            [
                *affected_paths,
                *_workspace_verdict_list(verdict, "affected_paths"),
                *_extract_affected_paths(result.stdout),
            ]
        )
        suspected_owners = _merge_unique(
            [
                *suspected_owners,
                *_workspace_verdict_list(verdict, "suspected_owners"),
                *_extract_suspected_owners(result.stdout),
            ]
        )
        store.update_agent_session(
            agent_id,
            session_id=result.session_id,
            codex_home=_agent_codex_home(config, agent_id, codex_home),
            model=result.model,
            reasoning_effort=result.reasoning_effort,
            last_step=f"workspace_qa_attempt_{attempt_index}",
        )
        primary_event_path = findings_path if findings_path.exists() else manifest_path
        store.append_event(
            "agent_output",
            agent_id,
            "QA Workspace Agent completed",
            {
                "path": store.to_relative(primary_event_path),
                "agent_output_path": store.to_relative(output_path),
                "workspace_path": store.to_relative(workspace_dir),
                "evidence_manifest_path": store.to_relative(manifest_path),
                "verdict_path": store.to_relative(verdict_path),
                "findings_path": store.to_relative(findings_path) if findings_path.exists() else None,
                "command_log_path": store.to_relative(command_log_path) if command_log_path.exists() else None,
                "scratch_cleanup_removed": len(scratch_cleanup.get("removed", [])),
                "scratch_cleanup_errors": scratch_cleanup.get("errors", []),
                "debug_artifacts_pruned": pruned_debug_artifacts,
                "qa_status": status,
                "verdict_error": verdict_error,
                "hard_policy_errors": hard_policy_errors,
                "affected_paths": _workspace_verdict_list(verdict, "affected_paths"),
                "suspected_owners": _workspace_verdict_list(verdict, "suspected_owners"),
                "screenshots": [store.to_relative(path) for path in workspace_screenshots],
                "artifact_paths": [store.to_relative(path) for path in workspace_artifacts],
                **_session_event_data(result),
            },
        )
        store.append_transcript(f"{agent_id} Workspace QA", result.stdout or agent_error)
        review_sections.append(
            _workspace_review_section(
                agent_id=agent_id,
                workspace_dir=workspace_dir,
                verdict=verdict,
                verdict_path=verdict_path,
                verdict_error=verdict_error,
                hard_policy_errors=hard_policy_errors,
                agent_output=result.stdout,
                agent_error=agent_error,
            )
        )

    llm_ok = not failed_reviews
    ok = mechanical_result.ok and llm_ok
    llm_error_log = "\n\n".join(
        part
        for part in [
            "\n".join(failed_reviews),
            "\n\n".join(section for section in fix_feedback_sections if section.strip()),
        ]
        if part.strip()
    )
    error_log = "\n\n".join(part for part in [mechanical_result.error_log, llm_error_log] if part)
    status = "PASS" if ok else "FAIL"
    report = "\n".join(
        [
            mechanical_result.report_markdown.strip(),
            "",
            "## Codex QA Workspace Agent Reviews",
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
        screenshots=screenshots,
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
            "artifact_paths": [store.to_relative(path) for path in qa_result.artifact_paths],
            "report_path": store.to_relative(qa_result.report_path),
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
        _snapshot_final_prompts_from_logs(store)
        output_path = store.write_artifact(
            f"agent_outputs/{assignment.agent_id}_fix_{iteration:02d}.md",
            result.stdout,
            artifact_name=f"{assignment.agent_id}_fix_{iteration:02d}",
        )
        store.update_agent_session(
            assignment.agent_id,
            session_id=result.session_id,
            codex_home=_agent_codex_home(config, assignment.agent_id, assignment.codex_home),
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
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        system_prompt=_agent_system_prompt(config, "integrator"),
        reference_markdown=_agent_skill_markdown(config, "integrator"),
        **_agent_run_kwargs(config, "integrator", config.integrator_codex_home),
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
    _snapshot_final_prompts_from_logs(store)
    store.update_agent_session(
        "integrator",
        session_id=repair_result.session_id,
        codex_home=_agent_codex_home(config, "integrator", config.integrator_codex_home),
        model=repair_result.model,
        reasoning_effort=repair_result.reasoning_effort,
        last_step=f"fix_{iteration}",
    )
    store.append_event("agent_output", "integrator", "Integrator repair completed", _session_event_data(repair_result))
    store.append_transcript(f"Integrator Repair {iteration}", repair_result.stdout)
    merged_app_dir = run_dir / "integration" / "merged_app"
    normalize_windows_command_files(merged_app_dir)
    generated_app_dir = reset_generated_app_from_merged(run_dir, merged_app_dir)
    _copy_run_inputs_to_workspace(run_dir, generated_app_dir)
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
                "title": "Build runnable app",
                "summary": "Implement the complete local app in generated_app.",
                "dependencies": [],
                "owned_paths": ["."],
                "allowed_shared_paths": [],
                "forbidden_paths": ["contract/", "runs/", "agent_workspaces/", "integration/"],
                "interfaces": [
                    "Complete runnable app.",
                    "README.md with setup, run, and test notes.",
                    "codex_app_manifest.json with one safe local check.",
                ],
                "acceptance_criteria": [
                    "Satisfies the original request using source-file evidence.",
                    "Planner brief is guidance; improve on it when the data supports a better result.",
                    "Local QA can check it without human input when practical.",
                ],
            }
        ],
    )


def render_single_code_context(final_plan: str, route: Any) -> str:
    code_brief = extract_code_brief_from_plan(final_plan)
    return "\n\n".join(
        [
            "# Planner Brief",
            (
                "Use this as guidance, not as an approved specification. Re-check local inputs "
                "yourself and improve on the brief when source evidence supports a better result."
            ),
            code_brief or "(missing final plan)",
            "# Route Context",
            f"- mode: {getattr(route, 'mode', 'single')}",
        ]
    )


def extract_code_brief_from_plan(final_plan: str) -> str:
    """Return the Code Brief section when present, otherwise the full plan."""

    text = final_plan.strip()
    if not text:
        return ""

    headings = list(re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", text))
    for index, match in enumerate(headings):
        title = match.group(2).strip().lower()
        if title != "code brief":
            continue

        level = len(match.group(1))
        end = len(text)
        for next_match in headings[index + 1 :]:
            if len(next_match.group(1)) <= level:
                end = next_match.start()
                break
        return text[match.start() : end].strip()

    return text


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
    _copy_run_inputs_to_workspace(run_dir, generated_app_dir)
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
    _snapshot_final_prompts_from_logs(store)
    output_path = store.write_artifact(
        "agent_outputs/code_1_summary.md",
        result.stdout,
        artifact_name="code_1_summary",
    )
    store.update_agent_session(
        assignment.agent_id,
        session_id=result.session_id,
        codex_home=_agent_codex_home(config, assignment.agent_id, assignment.codex_home),
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
    _snapshot_final_prompts_from_logs(store)
    output_path = store.write_artifact(
        f"agent_outputs/code_1_fix_{iteration:02d}.md",
        result.stdout,
        artifact_name=f"code_1_fix_{iteration:02d}",
    )
    store.update_agent_session(
        assignment.agent_id,
        session_id=result.session_id,
        codex_home=_agent_codex_home(config, assignment.agent_id, assignment.codex_home),
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
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        system_prompt=_agent_system_prompt(config, assignment.agent_id),
        reference_markdown=_agent_skill_markdown(config, assignment.agent_id),
        **_agent_run_kwargs(config, assignment.agent_id, assignment.codex_home),
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
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        system_prompt=_agent_system_prompt(config, assignment.agent_id),
        reference_markdown=_agent_skill_markdown(config, assignment.agent_id),
        **_agent_run_kwargs(config, assignment.agent_id, assignment.codex_home),
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
        {_agent_system_prompt(config, "planner_c")}

        Review the current plan only for implementation risk, parallel task
        boundaries, missing acceptance criteria, and likely integration issues.
        Do not rewrite the full plan.

        {_agent_skill_reference_block(config, "planner_c")}

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
        timeout=config.timeout_seconds,
        logs_dir=logs_dir,
        label="planner_c_risk_review",
        sandbox="workspace-write",
        **_agent_run_kwargs(config, "planner_c", config.planner_c_codex_home),
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
        {_agent_system_prompt(config, "planner_c")}

        Review the current plan only for implementation risk, parallel task
        boundaries, missing acceptance criteria, and likely integration issues.
        Do not rewrite the full plan.

        {_agent_skill_reference_block(config, "planner_c")}

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
        timeout=config.timeout_seconds,
        logs_dir=logs_dir,
        label="planner_c_risk_review",
        sandbox="workspace-write",
        **_agent_run_kwargs(config, "planner_c", config.planner_c_codex_home),
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


def _snapshot_final_prompts_from_logs(store: StateStore) -> dict[str, str]:
    if not _debug_artifacts_enabled():
        return {}

    logs_dir = store.run_dir / "logs"
    if not logs_dir.exists():
        return {}

    state = store.load()
    snapshots = state.setdefault("final_prompt_snapshots", {})
    artifacts = state.setdefault("artifacts", {})
    added: dict[str, str] = {}
    prompt_dir = store.run_dir / "prompts" / "final"
    prompt_dir.mkdir(parents=True, exist_ok=True)

    for prompt_path in sorted(logs_dir.glob("*_prompt.txt")):
        source_rel = store.to_relative(prompt_path)
        if source_rel in snapshots:
            continue
        try:
            prompt_text = prompt_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        prompt_stem = prompt_path.stem
        if prompt_stem.endswith("_prompt"):
            prompt_stem = prompt_stem[: -len("_prompt")]
        final_prompt_path = prompt_dir / f"{prompt_stem}_final_prompt.md"
        final_prompt_path.write_text(prompt_text.rstrip() + "\n", encoding="utf-8")
        final_rel = store.to_relative(final_prompt_path)
        snapshots[source_rel] = {
            "source_log": source_rel,
            "path": final_rel,
        }
        artifacts[f"final_prompt_{_safe_artifact_key(prompt_stem)}"] = final_rel
        added[source_rel] = final_rel

    if added:
        store.save(state)
        store.append_event(
            "final_prompts_saved",
            "system",
            "Final prompt snapshots saved",
            {"count": len(added), "paths": list(added.values())},
        )
    return added


def _safe_artifact_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._-")[:120] or "prompt"


def _agent_run_kwargs(config: LocalRunConfig, agent_id: str, codex_home: str | None) -> dict[str, str | None]:
    return {
        "codex_home": _agent_codex_home(config, agent_id, codex_home),
        "model": _agent_model(config, agent_id),
        "reasoning_effort": _agent_reasoning_effort(config, agent_id),
    }


def _agent_prompt_config(config: LocalRunConfig, agent_id: str) -> dict[str, object]:
    prompt_config = config.prompt_overrides.get(agent_id)
    if not isinstance(prompt_config, dict):
        prompt_config = config.prompt_overrides.get(_agent_role_key(agent_id), {})
    return prompt_config if isinstance(prompt_config, dict) else {}


def _agent_system_prompt(config: LocalRunConfig, agent_id: str) -> str:
    prompt_config = _agent_prompt_config(config, agent_id)
    return _config_str(prompt_config.get("system_prompt")) or load_agent_system_prompt(agent_id=agent_id)


def _agent_skill_markdown(config: LocalRunConfig, agent_id: str) -> str | None:
    prompt_config = _agent_prompt_config(config, agent_id)
    return _config_str(prompt_config.get("skill_markdown"))


def _agent_skill_reference_block(config: LocalRunConfig, agent_id: str) -> str:
    skill_markdown = _agent_skill_markdown(config, agent_id)
    if not skill_markdown:
        return ""
    return dedent(
        f"""
        Additional role reference guidance:
        {skill_markdown}

        Treat the role reference as advisory. The current task instructions,
        file ownership rules, and safety constraints take precedence.
        """
    ).strip()


def _agent_role_key(agent_id: str) -> str:
    if agent_id.startswith("code_"):
        return "code_agent"
    if agent_id.startswith("qa_"):
        return "qa_agent"
    return agent_id


def _agent_codex_home(config: LocalRunConfig, agent_id: str, fallback: str | None) -> str | None:
    agent_config = _agent_config(config, agent_id)
    return _config_str(agent_config.get("codex_home")) or fallback


def _agent_model(config: LocalRunConfig, agent_id: str) -> str | None:
    agent_config = _agent_config(config, agent_id)
    return _config_str(agent_config.get("model")) or config.model


def _agent_reasoning_effort(config: LocalRunConfig, agent_id: str) -> str | None:
    agent_config = _agent_config(config, agent_id)
    return _config_str(agent_config.get("reasoning_effort")) or config.reasoning_effort


def _agent_config(config: LocalRunConfig, agent_id: str) -> dict[str, object]:
    agent_config = config.agent_configs.get(agent_id) if isinstance(config.agent_configs, dict) else None
    if not isinstance(agent_config, dict):
        agent_config = {}
    provider = str(agent_config.get("provider") or "codex").lower()
    if provider not in {"codex", "local", "manual"}:
        raise ValueError(f"Unsupported provider for {agent_id}: {provider}")
    if provider not in {"codex"}:
        raise ValueError(f"Provider {provider} is not executable for {agent_id} yet.")
    return agent_config


def _config_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def make_agentic_qa_baseline_result(run_dir: Path, generated_app_dir: Path, *, attempt_index: int = 0) -> QAResult:
    """Create a neutral QA baseline when deterministic mechanical QA is intentionally skipped."""

    report_path = Path(run_dir) / "qa_report.md"
    app_type = _guess_generated_app_type(generated_app_dir)
    report = "\n".join(
        [
            "# Agentic QA",
            "",
            "Deterministic mechanical QA was skipped for this run.",
            "The Codex QA Workspace Agent is responsible for selecting safe probes,",
            "running local checks, collecting evidence, and writing the final verdict.",
            "",
            f"- Attempt: {attempt_index}",
            f"- Generated app: `{generated_app_dir}`",
            f"- Detected app type: `{app_type}`",
            f"- Status before QA Agent verdict: PENDING",
            "",
        ]
    )
    report_path.write_text(report if report.endswith("\n") else f"{report}\n", encoding="utf-8")
    return QAResult(
        ok=True,
        checked_files=[],
        error_log="",
        report_path=report_path,
        report_markdown=report,
        screenshots=[],
        artifact_paths=[],
        executable_status="SKIPPED",
        executable_app_type=app_type,
    )


def _guess_generated_app_type(generated_app_dir: Path) -> str:
    app_dir = Path(generated_app_dir)
    manifest_path = app_dir / "codex_app_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
            app_type = str(manifest.get("app_type") or "").strip()
            if app_type:
                return app_type
        except (OSError, json.JSONDecodeError):
            pass
    if (app_dir / "index.html").exists() or any(app_dir.glob("**/index.html")):
        return "static_html"
    package_json = app_dir / "package.json"
    if package_json.exists():
        return "web"
    requirements = (app_dir / "requirements.txt").read_text(encoding="utf-8", errors="replace").lower() if (app_dir / "requirements.txt").exists() else ""
    py_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace").lower()
        for path in sorted(app_dir.glob("*.py"))[:5]
    )
    if "streamlit" in requirements or "import streamlit" in py_text:
        return "streamlit"
    if any(token in py_text for token in ["tkinter", "pyqt", "pyside", "kivy"]):
        return "desktop_gui"
    if list(app_dir.glob("*.py")):
        return "python"
    return "unknown"


def _copy_run_inputs_to_workspace(run_dir: Path, workspace_dir: Path) -> Path | None:
    source_dir = Path(run_dir) / "inputs"
    if not source_dir.exists() or not source_dir.is_dir():
        return None
    target_dir = Path(workspace_dir) / "inputs"
    source_resolved = source_dir.resolve()
    target_resolved = target_dir.resolve()
    workspace_resolved = Path(workspace_dir).resolve()
    if source_resolved == target_resolved:
        return target_dir
    try:
        target_resolved.relative_to(workspace_resolved)
    except ValueError as exc:
        raise ValueError(f"Refusing to copy run inputs outside workspace: {target_dir}") from exc
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(
        source_dir,
        target_dir,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return target_dir


def _prepare_qa_workspace(
    *,
    run_dir: Path,
    attempt_dir: Path,
    generated_app_dir: Path,
    agent_id: str,
    user_request: str,
    contract_bundle: str,
    generated_app_listing: str,
    mechanical_qa_report: str,
) -> Path:
    workspace_name = "qa_workspace" if agent_id == "qa_1" else f"qa_workspace_{agent_id}"
    workspace_dir = attempt_dir / workspace_name
    _reset_child_directory(run_dir, workspace_dir)

    app_copy_dir = workspace_dir / "app"
    evidence_dir = workspace_dir / "evidence"
    screenshots_dir = workspace_dir / "screenshots"
    scratch_dir = workspace_dir / "scratch"
    context_dir = workspace_dir / "context"
    for path in [evidence_dir, screenshots_dir, scratch_dir, context_dir]:
        path.mkdir(parents=True, exist_ok=True)

    shutil.copytree(
        generated_app_dir,
        app_copy_dir,
        ignore=shutil.ignore_patterns(".git", ".venv", "node_modules", "__pycache__"),
    )
    _copy_run_inputs_to_workspace(run_dir, workspace_dir)

    _write_text(context_dir / "user_request.md", user_request)
    _write_text(context_dir / "contract_bundle.md", contract_bundle or "(no contract bundle)")
    _write_text(context_dir / "generated_app_listing.txt", generated_app_listing or "(no generated app listing)")
    _write_text(context_dir / "qa_baseline_report.md", mechanical_qa_report or "(no QA baseline report)")
    _write_text(context_dir / "mechanical_qa_report.md", mechanical_qa_report or "(no mechanical QA report)")
    _copy_qa_tools(run_dir, workspace_dir)
    _write_text(
        workspace_dir / "README_QA_WORKSPACE.md",
        "\n".join(
            [
                "# QA Workspace",
                "",
                "This directory is the QA Agent's isolated working area.",
                "",
                "- Inspect `app/` as the generated app under test.",
                "- If present, inspect `inputs/` as the read-only copy of files the user attached to the run.",
                "- The app under test may also contain `app/inputs/` when the code stage received attached files.",
                "- Use `qa_tools/` for safe evidence-producing probes instead of ad-hoc global automation.",
                "- On Windows, prefer `qa_tools\\*.cmd` launchers so probes use Orchestra's Python environment.",
                "- Before reading files, use `qa_tools\\file_probe.cmd` to record size, bounded preview, and targeted contains checks.",
                "- Treat files over 128 KB as large. Do not paste full source, logs, JSON, bundles, stdout, or stderr into findings.",
                "- Avoid dependency/build/cache folders unless directly relevant: node_modules, .venv, dist, build, .next, .git, __pycache__.",
                "- Use `qa_tools\\command_probe.cmd --max-output-chars ...` for commands that may print large output.",
                "- Write probes, notes, logs, and verdict files under `evidence/`.",
                "- Required evidence files: `evidence/verdict.json`, `evidence/qa_findings.md`, and `evidence/command_log.jsonl`.",
                "- Orchestra will generate `evidence/evidence_manifest.json`; do not duplicate large stdout/stderr content in findings.",
                "- Write screenshots under `screenshots/`.",
                "- Use `scratch/` for temporary experiments.",
                "- Browser profiles/cache/crashpad files under `scratch/` are cleaned automatically after QA.",
                "- Do not write outside this QA workspace.",
                "",
            ]
        ),
    )
    _append_jsonl(
        evidence_dir / "command_log.jsonl",
        {
            "event": "workspace_prepared",
            "cwd": ".",
            "purpose": "QA workspace initialized with generated app copy and context files.",
            "exit_code": 0,
        },
    )
    return workspace_dir


def _copy_qa_tools(run_dir: Path, workspace_dir: Path) -> None:
    project_root = Path(run_dir).parent.parent
    tools_source = project_root / "qa_tools"
    tools_target = Path(workspace_dir) / "qa_tools"
    if tools_target.exists():
        shutil.rmtree(tools_target)
    if tools_source.exists():
        shutil.copytree(
            tools_source,
            tools_target,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        _write_qa_tool_launchers(project_root, tools_target)
        return
    tools_target.mkdir(parents=True, exist_ok=True)
    _write_text(
        tools_target / "README.md",
        "# QA Tools\n\nNo project qa_tools directory was found. Use safe local commands and record evidence manually.\n",
    )


def _write_qa_tool_launchers(project_root: Path, tools_target: Path) -> None:
    python_path = _qa_tools_python_path(project_root)
    for tool_name in ["command_probe", "file_probe", "browser_probe"]:
        script_path = tools_target / f"{tool_name}.py"
        if not script_path.exists():
            continue
        _write_text(
            tools_target / f"{tool_name}.cmd",
            "\n".join(
                [
                    "@echo off",
                    "setlocal",
                    "set PYTHONUTF8=1",
                    "set PYTHONIOENCODING=utf-8",
                    f'"{python_path}" "%~dp0{tool_name}.py" %*',
                    "",
                ]
            ),
        )


def _qa_tools_python_path(project_root: Path) -> str:
    candidates: list[Path] = []
    env_python = os.environ.get("ORCHESTRA_PYTHON")
    if env_python:
        candidates.append(Path(env_python))
    candidates.append(Path(project_root) / ".venv" / "Scripts" / "python.exe")
    candidates.append(Path(sys.executable))
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _reset_child_directory(root_dir: Path, target_dir: Path) -> None:
    root = Path(root_dir).resolve()
    target = Path(target_dir).resolve()
    if root != target and root not in target.parents:
        raise ValueError(f"Refusing to clear directory outside run root: {target_dir}")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8", errors="replace")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _write_workspace_fallback_verdict(workspace_dir: Path, *, status: str, summary: str) -> Path:
    evidence_dir = workspace_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    findings_path = evidence_dir / "qa_findings.md"
    verdict_path = evidence_dir / "verdict.json"
    command_log_path = evidence_dir / "command_log.jsonl"
    if not command_log_path.exists():
        _append_jsonl(
            command_log_path,
            {
                "event": "fallback_verdict",
                "cwd": ".",
                "purpose": "Fallback verdict generated by Orchestra because QA Agent evidence was incomplete.",
                "exit_code": 0,
            },
        )
    if not findings_path.exists():
        _write_text(
            findings_path,
            "\n".join(
                [
                    "# QA Findings",
                    "",
                    summary,
                    "",
                    "No autonomous QA evidence was produced beyond the fallback verdict.",
                    "",
                ]
            ),
        )
    verdict = {
        "status": status,
        "summary": summary,
        "findings": [summary],
        "evidence": ["evidence/qa_findings.md", "evidence/command_log.jsonl"],
        "affected_paths": ["unknown"],
        "suspected_owners": ["unknown"],
    }
    verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return verdict_path


def _load_or_create_workspace_verdict(workspace_dir: Path) -> tuple[dict[str, Any], Path, str | None]:
    verdict_path = workspace_dir / "evidence" / "verdict.json"
    if not verdict_path.exists():
        _write_workspace_fallback_verdict(
            workspace_dir,
            status="FAIL",
            summary="QA workspace agent did not create evidence/verdict.json.",
        )
        return json.loads(verdict_path.read_text(encoding="utf-8")), verdict_path, "missing verdict.json"
    try:
        payload = json.loads(verdict_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _write_workspace_fallback_verdict(
            workspace_dir,
            status="FAIL",
            summary=f"QA workspace agent wrote invalid evidence/verdict.json: {exc}",
        )
        return json.loads(verdict_path.read_text(encoding="utf-8")), verdict_path, f"invalid verdict.json: {exc}"
    if not isinstance(payload, dict):
        _write_workspace_fallback_verdict(
            workspace_dir,
            status="FAIL",
            summary="QA workspace agent wrote a non-object evidence/verdict.json.",
        )
        return json.loads(verdict_path.read_text(encoding="utf-8")), verdict_path, "verdict.json root is not an object"
    if _workspace_verdict_status(payload) == "UNKNOWN":
        payload["status"] = "FAIL"
        payload.setdefault("summary", "QA workspace verdict status was missing or invalid.")
        findings = payload.get("findings")
        if not isinstance(findings, list):
            findings = []
        findings.append("verdict.json status must be PASS, FAIL, INCONCLUSIVE, or UNSUPPORTED.")
        payload["findings"] = findings
        verdict_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload, verdict_path, "invalid verdict status"
    return payload, verdict_path, None


def _workspace_verdict_status(verdict: dict[str, Any]) -> str:
    status = str(verdict.get("status") or "").strip().upper()
    if status in {"PASS", "FAIL", "INCONCLUSIVE", "UNSUPPORTED"}:
        return status
    return "UNKNOWN"


def _workspace_verdict_list(verdict: dict[str, Any], key: str) -> list[str]:
    raw = verdict.get(key)
    if isinstance(raw, str):
        raw_values: list[object] = [raw]
    elif isinstance(raw, list):
        raw_values = raw
    else:
        raw_values = []
    values: list[str] = []
    for value in raw_values:
        text = str(value).strip().strip("`")
        if not text or text.lower() in {"none", "n/a", "null"}:
            continue
        values.append(text)
    return values


def _workspace_fix_feedback_section(
    *,
    agent_id: str,
    workspace_dir: Path,
    verdict: dict[str, Any],
    verdict_path: Path,
    findings_path: Path,
    verdict_error: str | None,
    hard_policy_errors: list[str],
) -> str:
    lines = [
        f"# QA Feedback For Fix: {agent_id}",
        f"- Verdict status: {_workspace_verdict_status(verdict)}",
        f"- Verdict path: {_workspace_relative(workspace_dir, verdict_path)}",
    ]
    summary = str(verdict.get("summary") or "").strip()
    if summary:
        lines.extend(["", "## Verdict Summary", _short_text(summary, max_chars=1200)])

    findings = _workspace_verdict_list(verdict, "findings")
    if findings:
        lines.extend(["", "## Findings"])
        lines.extend(f"- {finding}" for finding in findings[:8])

    affected_paths = _workspace_verdict_list(verdict, "affected_paths")
    if affected_paths:
        lines.extend(["", "## Affected Paths"])
        lines.extend(f"- {path}" for path in affected_paths[:12])

    suspected_owners = _workspace_verdict_list(verdict, "suspected_owners")
    if suspected_owners:
        lines.extend(["", "## Suspected Owners"])
        lines.extend(f"- {owner}" for owner in suspected_owners[:8])

    evidence = _workspace_verdict_list(verdict, "evidence")
    if evidence:
        lines.extend(["", "## Evidence"])
        lines.extend(f"- {item}" for item in evidence[:12])

    if hard_policy_errors:
        lines.extend(["", "## Hard Policy Errors"])
        lines.extend(f"- {error}" for error in hard_policy_errors)

    if verdict_error:
        lines.extend(["", "## Verdict Parse Error", verdict_error])

    if findings_path.exists():
        try:
            findings_text = findings_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            findings_text = ""
        if findings_text:
            lines.extend(
                [
                    "",
                    f"## QA Findings Detail ({_workspace_relative(workspace_dir, findings_path)})",
                    _short_text(findings_text, max_chars=3500),
                ]
            )

    return "\n".join(lines).strip()


def _collect_qa_workspace_screenshots(workspace_dir: Path) -> list[Path]:
    patterns = ["*.png", "*.jpg", "*.jpeg", "*.webp"]
    screenshots: list[Path] = []
    for root in [workspace_dir / "screenshots", workspace_dir / "evidence"]:
        if not root.exists():
            continue
        for pattern in patterns:
            screenshots.extend(path for path in root.rglob(pattern) if path.is_file())
    return _unique_paths(screenshots)


def _collect_qa_workspace_artifacts(workspace_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for relative_path in [
        "evidence/evidence_manifest.json",
        "evidence/verdict.json",
        "evidence/qa_findings.md",
        "evidence/command_log.jsonl",
        "evidence/host_browser_evidence.json",
    ]:
        path = workspace_dir / relative_path
        if path.exists() and path.is_file():
            paths.append(path)
    browser_dir = workspace_dir / "evidence" / "browser"
    if _debug_artifacts_enabled() and browser_dir.exists():
        for pattern in ["*_result.json", "*_console.json"]:
            paths.extend(path for path in browser_dir.rglob(pattern) if path.is_file())
    return _unique_paths(paths)


def _prune_qa_workspace_debug_artifacts(workspace_dir: Path) -> list[str]:
    if _debug_artifacts_enabled():
        return []

    targets = [
        workspace_dir / "qa_tools",
        workspace_dir / "scratch",
        workspace_dir / "context",
        workspace_dir / "app",
        workspace_dir / "inputs",
        workspace_dir / "README_QA_WORKSPACE.md",
        workspace_dir / "evidence" / "files",
        workspace_dir / "evidence" / "commands",
        workspace_dir / "evidence" / "browser",
    ]
    removed: list[str] = []
    for target in targets:
        if not target.exists():
            continue
        relative_path = _workspace_relative(workspace_dir, target)
        try:
            _remove_workspace_child(workspace_dir, target)
        except OSError:
            continue
        removed.append(relative_path)
    return removed


def _cleanup_qa_scratch(workspace_dir: Path) -> dict[str, Any]:
    scratch_dir = workspace_dir / "scratch"
    summary: dict[str, Any] = {
        "version": 1,
        "removed": [],
        "errors": [],
    }
    if not scratch_dir.exists():
        _write_text(workspace_dir / "evidence" / "scratch_cleanup.json", json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    candidates: list[Path] = []
    for pattern in [
        "chrome-profile*",
        "chromium-profile*",
        "playwright-profile*",
        "browser-profile*",
        "tmp-playwright*",
        "*Crashpad*",
        "crashpad*",
    ]:
        candidates.extend(path for path in scratch_dir.glob(pattern))
        candidates.extend(path for path in scratch_dir.rglob(pattern))

    transient_dir_names = {
        "cache",
        "code cache",
        "gpucache",
        "shadercache",
        "dawncache",
        "blob_storage",
        "browsermetrics",
    }
    candidates.extend(
        path
        for path in scratch_dir.rglob("*")
        if path.is_dir() and path.name.strip().lower() in transient_dir_names
    )

    for path in sorted(_unique_paths(candidates), key=lambda item: len(item.parts), reverse=True):
        if not path.exists():
            continue
        try:
            _remove_workspace_child(workspace_dir, path)
            summary["removed"].append(_workspace_relative(workspace_dir, path))
        except OSError as exc:
            summary["errors"].append(
                {
                    "path": _workspace_relative(workspace_dir, path),
                    "error": str(exc),
                }
            )

    _write_text(workspace_dir / "evidence" / "scratch_cleanup.json", json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def _remove_workspace_child(workspace_dir: Path, target_path: Path) -> None:
    root = Path(workspace_dir).resolve()
    target = Path(target_path).resolve()
    if root != target and root not in target.parents:
        raise OSError(f"Refusing to remove path outside QA workspace: {target_path}")
    if target == root:
        raise OSError("Refusing to remove the QA workspace root.")
    if target.is_dir():
        shutil.rmtree(target)
        return
    if target.exists():
        target.unlink()


def _write_qa_evidence_manifest(
    *,
    workspace_dir: Path,
    agent_id: str,
    verdict: dict[str, Any],
    verdict_path: Path,
    findings_path: Path,
    command_log_path: Path,
    screenshots: list[Path],
    mechanical_result: QAResult,
    status: str,
    verdict_error: str | None,
    hard_policy_errors: list[str],
    scratch_cleanup: dict[str, Any],
    pruned_debug_artifacts: list[str],
) -> Path:
    evidence_dir = workspace_dir / "evidence"
    manifest_path = evidence_dir / "evidence_manifest.json"
    browser_summary_path = evidence_dir / "host_browser_evidence.json"
    browser_summary = _read_json_file(browser_summary_path)
    payload = {
        "version": 1,
        "agent_id": agent_id,
        "status": status,
        "ok": status == "PASS" and not verdict_error and not hard_policy_errors,
        "summary": str(verdict.get("summary") or ""),
        "executable_status": mechanical_result.executable_status,
        "executable_app_type": mechanical_result.executable_app_type,
        "verdict": {
            "path": _workspace_relative(workspace_dir, verdict_path),
            "status": status,
            "error": verdict_error,
            "findings": _workspace_verdict_list(verdict, "findings"),
            "affected_paths": _workspace_verdict_list(verdict, "affected_paths"),
            "suspected_owners": _workspace_verdict_list(verdict, "suspected_owners"),
        },
        "core_evidence": [
            _manifest_file_entry(workspace_dir, verdict_path, kind="verdict"),
            _manifest_file_entry(workspace_dir, findings_path, kind="findings"),
            _manifest_file_entry(workspace_dir, command_log_path, kind="command_log"),
        ],
        "screenshots": [
            _manifest_file_entry(workspace_dir, screenshot_path, kind="screenshot")
            for screenshot_path in screenshots
            if screenshot_path.exists() and screenshot_path.is_file()
        ],
        "browser_evidence": {
            "summary_path": _workspace_relative(workspace_dir, browser_summary_path) if browser_summary_path.exists() else None,
            "status": browser_summary.get("status"),
            "reason": browser_summary.get("reason"),
            "ran": browser_summary.get("ran"),
            "result_paths": browser_summary.get("result_paths") if isinstance(browser_summary.get("result_paths"), list) else [],
            "screenshot_paths": [
                _workspace_relative(workspace_dir, Path(path))
                for path in browser_summary.get("screenshot_paths", [])
                if isinstance(path, str)
            ]
            if isinstance(browser_summary.get("screenshot_paths"), list)
            else [],
        },
        "hard_policy_errors": hard_policy_errors,
        "scratch_cleanup": {
            "path": "evidence/scratch_cleanup.json",
            "removed_count": len(scratch_cleanup.get("removed", [])),
            "errors": scratch_cleanup.get("errors") if isinstance(scratch_cleanup.get("errors"), list) else [],
        },
        "artifact_mode": {
            "debug_artifacts_enabled": _debug_artifacts_enabled(),
            "pruned_debug_artifacts": pruned_debug_artifacts,
        },
        "notes": [
            "Manifest is generated by Orchestra after QA Agent execution.",
            "Normal mode keeps only presentation-friendly QA evidence. Set ORCHESTRA_DEBUG_ARTIFACTS=1 to retain copied apps, tools, scratch files, and probe internals.",
        ],
    }
    payload["core_evidence"] = [entry for entry in payload["core_evidence"] if entry is not None]
    _write_text(manifest_path, json.dumps(payload, ensure_ascii=False, indent=2))
    return manifest_path


def _manifest_file_entry(workspace_dir: Path, path: Path, *, kind: str) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    stat = path.stat()
    return {
        "kind": kind,
        "path": _workspace_relative(workspace_dir, path),
        "size_bytes": stat.st_size,
    }


def _run_host_browser_evidence(workspace_dir: Path, *, mechanical_result: QAResult) -> dict[str, Any]:
    summary_path = workspace_dir / "evidence" / "host_browser_evidence.json"
    command_log_path = workspace_dir / "evidence" / "command_log.jsonl"
    summary: dict[str, Any] = {
        "version": 1,
        "tool": "host_browser_runner",
        "ran": False,
        "status": "SKIPPED",
        "reason": "",
        "result_paths": [],
        "screenshot_paths": [],
        "runs": [],
    }
    if _collect_qa_workspace_screenshots(workspace_dir):
        summary["reason"] = "workspace already contains screenshot evidence"
        _write_text(summary_path, json.dumps(summary, ensure_ascii=False, indent=2))
        return summary
    if not _workspace_needs_host_browser(workspace_dir, mechanical_result):
        summary["reason"] = f"app type does not require host browser evidence: {mechanical_result.executable_app_type or 'unknown'}"
        _write_text(summary_path, json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    entry = _host_browser_entry(workspace_dir)
    if not entry:
        summary["status"] = "UNSUPPORTED"
        summary["reason"] = "no browser entrypoint found under qa_workspace/app"
        _write_text(summary_path, json.dumps(summary, ensure_ascii=False, indent=2))
        _append_jsonl(command_log_path, summary)
        return summary

    action_files = _host_browser_action_files(workspace_dir)
    targets: list[Path | None] = action_files[:3] or [None]
    probe_command = _host_browser_probe_base_command(workspace_dir)
    if not probe_command:
        summary["status"] = "UNSUPPORTED"
        summary["reason"] = "trusted project browser_probe tool was not available"
        _write_text(summary_path, json.dumps(summary, ensure_ascii=False, indent=2))
        _append_jsonl(command_log_path, summary)
        return summary

    probe_env = _utf8_subprocess_env()
    probe_env["ORCHESTRA_QA_WORKSPACE_ROOT"] = str(workspace_dir.resolve())
    summary["ran"] = True
    summary["status"] = "PASS"
    for index, action_file in enumerate(targets, start=1):
        name = _host_browser_evidence_name(action_file, index)
        command = [
            *probe_command,
            "--name",
            name,
            "--entry",
            entry,
        ]
        if action_file is not None:
            command.extend(["--action-file", _workspace_relative(workspace_dir, action_file)])
        try:
            completed = subprocess.run(
                command,
                cwd=str(workspace_dir),
                env=probe_env,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            completed = subprocess.CompletedProcess(
                command,
                1,
                _coerce_subprocess_text(exc.stdout),
                _coerce_subprocess_text(exc.stderr) or str(exc),
            )
        except OSError as exc:
            completed = subprocess.CompletedProcess(command, 1, "", str(exc))
        result_path = workspace_dir / "evidence" / "browser" / f"{name}_result.json"
        payload = _read_json_file(result_path)
        status = str(payload.get("status") or ("PASS" if completed.returncode == 0 else "FAIL"))
        screenshots = [
            str((workspace_dir / str(path)).resolve())
            for path in payload.get("screenshots", [])
            if isinstance(path, str)
        ]
        run_record = {
            "name": name,
            "action_file": _workspace_relative(workspace_dir, action_file) if action_file is not None else None,
            "entry": entry,
            "status": status,
            "returncode": completed.returncode,
            "result_path": _workspace_relative(workspace_dir, result_path) if result_path.exists() else None,
            "screenshots": [_workspace_relative(workspace_dir, Path(path)) for path in screenshots],
            "stdout_preview": _short_text(completed.stdout),
            "stderr_preview": _short_text(completed.stderr),
        }
        summary["runs"].append(run_record)
        if result_path.exists():
            summary["result_paths"].append(_workspace_relative(workspace_dir, result_path))
        summary["screenshot_paths"].extend(screenshots)
        if status != "PASS":
            summary["status"] = "FAIL"

    summary["screenshot_paths"] = _dedupe_strings(summary["screenshot_paths"])
    if not summary["screenshot_paths"] and summary["status"] == "PASS":
        summary["status"] = "INCONCLUSIVE"
        summary["reason"] = "host browser runner completed without screenshot files"
    else:
        summary["reason"] = "host browser runner collected browser evidence outside Codex sandbox"
    _write_text(summary_path, json.dumps(summary, ensure_ascii=False, indent=2))
    _append_jsonl(command_log_path, {**summary, "summary_path": _workspace_relative(workspace_dir, summary_path)})
    return summary


def _workspace_needs_host_browser(workspace_dir: Path, mechanical_result: QAResult) -> bool:
    app_type = (mechanical_result.executable_app_type or "").strip().lower()
    if app_type in {"static_html", "browser", "web", "spa"}:
        return True
    return (workspace_dir / "app" / "index.html").exists()


def _host_browser_entry(workspace_dir: Path) -> str:
    candidates = [
        workspace_dir / "app" / "index.html",
        workspace_dir / "app" / "dist" / "index.html",
        workspace_dir / "app" / "public" / "index.html",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return _workspace_relative(workspace_dir, candidate)
    return ""


def _host_browser_action_files(workspace_dir: Path) -> list[Path]:
    scratch_dir = workspace_dir / "scratch"
    if not scratch_dir.exists():
        return []
    preferred = [
        scratch_dir / "browser_actions.json",
        scratch_dir / "slingshot_actions.json",
    ]
    action_files: list[Path] = [path for path in preferred if path.exists() and path.is_file()]
    action_files.extend(path for path in sorted(scratch_dir.glob("*actions*.json")) if path.is_file())
    return _unique_paths(action_files)


def _host_browser_probe_base_command(workspace_dir: Path) -> list[str]:
    script = Path(__file__).resolve().parent / "qa_tools" / "browser_probe.py"
    if script.exists():
        return [sys.executable, str(script)]
    return []


def _host_browser_evidence_name(action_file: Path | None, index: int) -> str:
    if action_file is None:
        return "host-browser"
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", action_file.stem).strip("-")
    return f"host-{stem or f'browser-{index:02d}'}"


def _workspace_relative(workspace_dir: Path, path: Path | str) -> str:
    target = Path(path)
    if not target.is_absolute():
        return target.as_posix()
    try:
        return target.relative_to(workspace_dir).as_posix()
    except ValueError:
        return str(target)


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _short_text(value: str, *, max_chars: int = 2000) -> str:
    text = value.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n[truncated]"


def _coerce_subprocess_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _combine_codex_results(first: CodexResult, second: CodexResult, *, separator: str) -> CodexResult:
    stdout = "\n\n".join(part for part in [first.stdout.strip(), separator, second.stdout.strip()] if part)
    stderr = "\n\n".join(part for part in [first.stderr.strip(), second.stderr.strip()] if part)
    return CodexResult(
        stdout=stdout,
        stderr=stderr,
        returncode=second.returncode,
        session_id=second.session_id or first.session_id,
        resumed_session_id=second.resumed_session_id or first.resumed_session_id,
        model=second.model or first.model,
        reasoning_effort=second.reasoning_effort or first.reasoning_effort,
        effective_approval=second.effective_approval or first.effective_approval,
        effective_sandbox=second.effective_sandbox or first.effective_sandbox,
    )


def _utf8_subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("LANG", "C.UTF-8")
    return env


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _workspace_hard_policy_errors(
    *,
    verdict: dict[str, Any],
    workspace_dir: Path,
    mechanical_result: QAResult,
    screenshots: list[Path],
) -> list[str]:
    if _workspace_verdict_status(verdict) != "PASS":
        return []
    errors: list[str] = []
    findings_path = workspace_dir / "evidence" / "qa_findings.md"
    command_log_path = workspace_dir / "evidence" / "command_log.jsonl"
    if not findings_path.exists():
        errors.append("PASS is not allowed without evidence/qa_findings.md.")
    if not command_log_path.exists() or command_log_path.stat().st_size == 0:
        errors.append("PASS is not allowed without evidence/command_log.jsonl.")
    elif not _command_log_has_qa_probe(command_log_path):
        errors.append("PASS is not allowed without at least one intentional QA probe in command_log.jsonl.")
    if _is_visual_qa_app(mechanical_result.executable_app_type) and not screenshots:
        errors.append("PASS is not allowed for a visual/browser app without screenshot evidence.")
    return errors


def _command_log_has_qa_probe(command_log_path: Path) -> bool:
    try:
        lines = command_log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    ignored_events = {"workspace_prepared", "fallback_verdict"}
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return True
        event = str(payload.get("event") or "").strip()
        tool = str(payload.get("tool") or "").strip()
        command = payload.get("command")
        if tool or command or event not in ignored_events:
            return True
    return False


def _is_visual_qa_app(app_type: str | None) -> bool:
    text = (app_type or "").lower()
    return any(token in text for token in ["browser", "html", "web", "static", "streamlit", "frontend", "game"])


def _downgrade_workspace_verdict(verdict_path: Path, verdict: dict[str, Any], hard_policy_errors: list[str]) -> None:
    verdict["status"] = "FAIL"
    previous_summary = str(verdict.get("summary") or "").strip()
    verdict["summary"] = (
        "Hard QA policy downgraded this verdict from PASS to FAIL because required evidence was missing."
        + (f" Previous summary: {previous_summary}" if previous_summary else "")
    )
    findings = verdict.get("findings")
    if not isinstance(findings, list):
        findings = []
    findings.extend(hard_policy_errors)
    verdict["findings"] = findings
    evidence = verdict.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    evidence.append("Hard policy checks in Orchestra QA stage")
    verdict["evidence"] = evidence
    verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _workspace_review_section(
    *,
    agent_id: str,
    workspace_dir: Path,
    verdict: dict[str, Any],
    verdict_path: Path,
    verdict_error: str | None,
    hard_policy_errors: list[str],
    agent_output: str,
    agent_error: str,
) -> str:
    hard_policy_text = "\n".join(f"- {error}" for error in hard_policy_errors) or "- None"
    output = _truncate_text(agent_output or agent_error or "(no agent output)", max_chars=6000)
    return "\n".join(
        [
            f"### {agent_id} Workspace QA",
            "",
            f"- Workspace: `{workspace_dir}`",
            f"- Verdict path: `{verdict_path}`",
            f"- Verdict status: {_workspace_verdict_status(verdict)}",
            f"- Verdict parse error: {verdict_error or 'None'}",
            "- Hard policy errors:",
            hard_policy_text,
            "",
            "#### Verdict JSON",
            "",
            "```json",
            json.dumps(verdict, ensure_ascii=False, indent=2),
            "```",
            "",
            "#### Agent Output",
            "",
            "```text",
            output,
            "```",
            "",
        ]
    )


def _truncate_text(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 20)].rstrip() + "\n... truncated"


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


def _extract_json_object(output: str) -> tuple[dict[str, Any] | None, str | None]:
    text = output.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    first = text.find("{")
    last = text.rfind("}")
    if first < 0 or last <= first:
        return None, "No JSON object found in QA scenario plan output."
    candidate = text[first : last + 1]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON in QA scenario plan output: {exc}"
    if not isinstance(payload, dict):
        return None, "QA scenario plan root must be a JSON object."
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        return None, "QA scenario plan must contain a non-empty scenarios array."
    return payload, None


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
