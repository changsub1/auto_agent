"""Streamlit local control panel for testing the multi-agent workflow."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from local_dashboard_runner import LocalRunConfig, REASONING_EFFORTS, RUN_MODES, run_local_dashboard_workflow


PROJECT_ROOT = Path(__file__).resolve().parent


def main() -> None:
    st.set_page_config(page_title="Local Run Control Panel", layout="wide")
    st.title("Local Run Control Panel")

    defaults = LocalRunConfig.from_env()
    config = _render_controls(defaults)

    st.divider()
    run_disabled = config.run_mode == "full_run"
    if run_disabled:
        st.warning("full_run은 아직 로컬 대시보드에 연결하지 않았습니다. Discord workflow에서 먼저 사용하세요.")

    if st.button("Run", type="primary", disabled=run_disabled):
        if not config.user_request.strip():
            st.error("user request를 입력하세요.")
        else:
            with st.spinner("Codex agents 실행 중..."):
                try:
                    run_dir = run_local_dashboard_workflow(PROJECT_ROOT, config)
                except Exception as exc:
                    st.exception(exc)
                else:
                    st.session_state["selected_run_id"] = run_dir.name
                    st.success(f"Run created: {run_dir.name}")
                    st.code(str(run_dir))

    st.divider()
    _render_run_browser()


def _render_controls(defaults: LocalRunConfig) -> LocalRunConfig:
    with st.sidebar:
        st.header("Run Settings")
        run_mode = st.selectbox("실행 모드", RUN_MODES, index=RUN_MODES.index(defaults.run_mode))
        planner_count = st.number_input("planner count", min_value=1, max_value=3, value=defaults.planner_count, step=1)
        code_agent_count = st.number_input("code agent count", min_value=1, max_value=6, value=defaults.code_agent_count, step=1)
        qa_agent_count = st.number_input("QA agent count", min_value=0, max_value=2, value=defaults.qa_agent_count, step=1)
        model = _optional_text("model", defaults.model)
        reasoning = st.selectbox(
            "reasoning_effort",
            REASONING_EFFORTS,
            index=REASONING_EFFORTS.index(defaults.reasoning_effort or ""),
        )
        max_fix_iterations = st.number_input(
            "max_fix_iterations",
            min_value=0,
            max_value=5,
            value=defaults.max_fix_iterations,
            step=1,
        )
        timeout_seconds = st.number_input(
            "timeout seconds",
            min_value=60,
            max_value=7200,
            value=defaults.timeout_seconds,
            step=60,
        )
        show_codex_homes = st.checkbox("CODEX_HOME 경로 표시", value=True)

    st.subheader("Request")
    user_request = st.text_area("user request", value=defaults.user_request, height=120)

    st.subheader("Agent CODEX_HOME")
    if show_codex_homes:
        col1, col2, col3 = st.columns(3)
        with col1:
            planner_a_home = _optional_text("Planner A CODEX_HOME", defaults.planner_a_codex_home)
            planner_b_home = _optional_text("Planner B CODEX_HOME", defaults.planner_b_codex_home)
            planner_c_home = _optional_text("Planner C CODEX_HOME", defaults.planner_c_codex_home)
        with col2:
            architect_home = _optional_text("Architect CODEX_HOME", defaults.architect_codex_home)
            scaffold_home = _optional_text("Scaffold CODEX_HOME", defaults.scaffold_codex_home)
            integrator_home = _optional_text("Integrator CODEX_HOME", defaults.integrator_codex_home)
        with col3:
            code_homes = []
            for index in range(1, int(code_agent_count) + 1):
                default_home = _indexed_default(defaults.code_agent_codex_homes, index)
                code_homes.append(_optional_text(f"Code Agent {index} CODEX_HOME", default_home))
            qa_homes = []
            for index in range(1, int(qa_agent_count) + 1):
                default_home = _indexed_default(defaults.qa_agent_codex_homes, index)
                qa_homes.append(_optional_text(f"QA Agent {index} CODEX_HOME", default_home))
    else:
        planner_a_home = defaults.planner_a_codex_home
        planner_b_home = defaults.planner_b_codex_home
        planner_c_home = defaults.planner_c_codex_home
        architect_home = defaults.architect_codex_home
        scaffold_home = defaults.scaffold_codex_home
        integrator_home = defaults.integrator_codex_home
        code_homes = _expand_list(defaults.code_agent_codex_homes, int(code_agent_count))
        qa_homes = _expand_list(defaults.qa_agent_codex_homes, int(qa_agent_count))
        st.info("CODEX_HOME 경로를 숨겼습니다. 값은 환경변수 기본값을 사용합니다.")

    st.caption("auth.json 내용은 읽거나 표시하지 않습니다. CODEX_HOME 경로만 선택값으로 전달합니다.")

    return LocalRunConfig(
        user_request=user_request,
        run_mode=run_mode,
        planner_count=int(planner_count),
        code_agent_count=int(code_agent_count),
        qa_agent_count=int(qa_agent_count),
        planner_a_codex_home=planner_a_home,
        planner_b_codex_home=planner_b_home,
        planner_c_codex_home=planner_c_home,
        architect_codex_home=architect_home,
        scaffold_codex_home=scaffold_home,
        integrator_codex_home=integrator_home,
        code_agent_codex_homes=code_homes,
        qa_agent_codex_homes=qa_homes,
        model=model,
        reasoning_effort=reasoning or None,
        max_fix_iterations=int(max_fix_iterations),
        timeout_seconds=int(timeout_seconds),
    )


def _render_run_browser() -> None:
    st.subheader("Run Artifacts")
    runs = _list_runs()
    if not runs:
        st.info("아직 runs 폴더에 실행 결과가 없습니다.")
        return

    default_run = st.session_state.get("selected_run_id", runs[0])
    if default_run not in runs:
        default_run = runs[0]
    selected_run = st.selectbox("run_id", runs, index=runs.index(default_run))
    st.session_state["selected_run_id"] = selected_run
    run_dir = PROJECT_ROOT / "runs" / selected_run
    st.code(str(run_dir))

    tabs = st.tabs(["state.json", "events.jsonl", "transcript.md", "contract", "qa_report.md"])
    with tabs[0]:
        _show_json_file(run_dir / "state.json")
    with tabs[1]:
        _show_text_file(run_dir / "events.jsonl", language="json")
    with tabs[2]:
        _show_text_file(run_dir / "transcript.md", language="markdown")
    with tabs[3]:
        _show_contract(run_dir / "contract")
    with tabs[4]:
        _show_text_file(run_dir / "qa_report.md", language="markdown")


def _show_json_file(path: Path) -> None:
    if not path.exists():
        st.info(f"{path.name} 없음")
        return
    try:
        st.json(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        _show_text_file(path, language="json")


def _show_text_file(path: Path, *, language: str) -> None:
    if not path.exists():
        st.info(f"{path.name} 없음")
        return
    st.code(path.read_text(encoding="utf-8", errors="replace"), language=language)


def _show_contract(contract_dir: Path) -> None:
    if not contract_dir.exists():
        st.info("contract 폴더 없음")
        return
    files = sorted(path for path in contract_dir.iterdir() if path.is_file())
    if not files:
        st.info("contract 파일 없음")
        return
    selected = st.selectbox("contract file", [path.name for path in files])
    _show_text_file(contract_dir / selected, language="markdown" if selected.endswith(".md") else "json")


def _list_runs() -> list[str]:
    runs_dir = PROJECT_ROOT / "runs"
    if not runs_dir.exists():
        return []
    run_dirs = [path for path in runs_dir.iterdir() if path.is_dir()]
    run_dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [path.name for path in run_dirs]


def _optional_text(label: str, value: str | None) -> str | None:
    raw = st.text_input(label, value=value or "")
    stripped = raw.strip()
    return stripped or None


def _indexed_default(values: list[str | None], index: int) -> str | None:
    if not values:
        return None
    return values[(index - 1) % len(values)]


def _expand_list(values: list[str | None], count: int) -> list[str | None]:
    if count <= 0:
        return []
    if not values:
        return [None for _ in range(count)]
    return [values[index % len(values)] for index in range(count)]


if __name__ == "__main__":
    main()
