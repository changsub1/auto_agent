"""Local non-Discord run helpers for the Streamlit dashboard."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

from agents import ArchitectAgent, PlannerAgentA, PlannerAgentB, ScaffoldAgent
from codex_runner import CodexResult, run_codex_result
from parallel_workflow import create_contract_dir, create_scaffold_dir, normalize_contract_bundle, render_contract_bundle
from state_store import StateStore
from workspace_manager import create_logs_dir, create_run_dir, normalize_windows_command_files, save_text


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
            qa_agent_count=0,
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
    )
    _record_dashboard_config(store, config)

    plan_artifacts = _run_planning(run_dir, logs_dir, store, config)
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


def _run_planning(
    run_dir: Path,
    logs_dir: Path,
    store: StateStore,
    config: LocalRunConfig,
) -> dict[str, str]:
    store.set_status("dashboard_planning_running")
    planner_a = PlannerAgentA(
        codex_home=config.planner_a_codex_home,
        logs_dir=logs_dir,
        timeout=config.timeout_seconds,
        model=config.model,
        reasoning_effort=config.reasoning_effort,
    )
    draft_result = planner_a.create_initial_plan(config.user_request, run_dir)
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

    review_text = "(planner review skipped because planner_count is 1)"
    if config.planner_count >= 2:
        planner_b = PlannerAgentB(
            codex_home=config.planner_b_codex_home,
            logs_dir=logs_dir,
            timeout=config.timeout_seconds,
            model=config.model,
            reasoning_effort=config.reasoning_effort,
        )
        review_result = planner_b.review_plan(config.user_request, draft_result.stdout, run_dir)
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

    if config.planner_count >= 2:
        final_result = planner_a.revise_final_plan(
            config.user_request,
            draft_result.stdout,
            review_text,
            run_dir,
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
    result = architect.create_contract_bundle_result(
        config.user_request,
        plan_artifacts["planner_a_draft"],
        plan_artifacts["planner_review"],
        plan_artifacts["final_plan"],
        contract_dir,
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
    result = scaffold.create_scaffold_result(
        config.user_request,
        render_contract_bundle(contract_dir),
        scaffold_dir,
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
