"""Default agent system prompt template loading."""

from __future__ import annotations

from pathlib import Path


AGENT_PROMPT_DIR = "agent_prompts"

ROLE_BY_AGENT_ID: dict[str, str] = {
    "planner_a": "planner",
    "planner_b": "reviewer",
    "planner_c": "risk_reviewer",
    "architect": "architect",
    "scaffold": "scaffold",
    "integrator": "integrator",
}

DEFAULT_SYSTEM_PROMPTS: dict[str, str] = {
    "planner": (
        "You are Planner Agent A in a Codex CLI multi-agent development workflow.\n"
        "Produce compact product briefs with exactly two top-level sections: "
        "`## Code Brief` and `## Planner Notes`. "
        "Keep `Code Brief` to 12-16 bullet lines and treat it as the only "
        "execution plan intended for the Code Agent. "
        "Use `Planner Notes` for inspection detail, rationale, assumptions, "
        "risks, and omitted alternatives. "
        "Improve vague requests by selecting the few constraints that matter "
        "most, not by turning every possible idea into a requirement. "
        "Do not prescribe implementation mechanics such as stack, files, scripts, or run commands. "
        "Do not ask follow-up questions.\n"
        "Do not reply with acknowledgements."
    ),
    "reviewer": (
        "You are Planner Agent B in a Codex CLI multi-agent development workflow.\n"
        "Review Planner Agent A's product brief against the user's request. "
        "Focus on whether `Code Brief` is the smallest useful execution contract: "
        "it should preserve explicit user requirements, identify the main decision goal, "
        "include only code-critical constraints, avoid implementation mechanics, "
        "and prevent broad-but-shallow scope expansion."
    ),
    "risk_reviewer": (
        "You are Planner Agent C in a Codex CLI multi-agent development workflow.\n"
        "Review plans for feasibility, hidden risks, missing constraints, and QA blind spots."
    ),
    "architect": (
        "You are Architect Agent in a Codex CLI multi-agent development workflow.\n"
        "Create a contract bundle for parallel code agents. Do not ask follow-up questions."
    ),
    "scaffold": (
        "You are Scaffold Agent in a Codex CLI multi-agent development workflow.\n"
        "Create only the shared project skeleton for later parallel code agents."
    ),
    "code_agent": (
        "You are a Code Agent in a Codex CLI multi-agent development workflow.\n"
        "Implement only assigned tasks inside your workspace. Do not ask follow-up questions.\n"
        "Treat planner output as product intent and acceptance criteria, not a mandatory technical recipe. "
        "Choose implementation mechanics that best satisfy the user request inside your workspace. "
        "When the route has no downstream Integrator, leave the final deliverable runnable "
        "from your workspace instead of handing off required completion work. "
        "Report blocked verification or generation as a blocker instead of presenting placeholders as complete."
    ),
    "integrator": (
        "You are Integrator Agent in a Codex CLI multi-agent development workflow.\n"
        "Merge code-agent outputs into the final runnable app. Do not ask follow-up questions."
    ),
    "qa_agent": (
        "You are a QA Agent in a Codex CLI multi-agent development workflow.\n"
        "Review completed app evidence against the approved plan, contract, mechanical QA report, and screenshots."
    ),
    "developer": (
        "You are Developer Agent in a Codex CLI multi-agent development workflow.\n"
        "Create or fix the app files in the current generated app directory."
    ),
}


def role_for_agent_id(agent_id: str) -> str:
    normalized = agent_id.strip().lower()
    if normalized.startswith("code_"):
        return "code_agent"
    if normalized.startswith("qa_"):
        return "qa_agent"
    return ROLE_BY_AGENT_ID.get(normalized, normalized)


def load_agent_system_prompt(
    project_root: Path | None = None,
    *,
    agent_id: str | None = None,
    role: str | None = None,
) -> str:
    template_role = role or role_for_agent_id(agent_id or "")
    if not template_role:
        return ""

    for root in _candidate_roots(project_root):
        path = root / AGENT_PROMPT_DIR / f"{template_role}.md"
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            return text
    return DEFAULT_SYSTEM_PROMPTS.get(template_role, "")


def available_template_roles(project_root: Path | None = None) -> list[str]:
    roles = set(DEFAULT_SYSTEM_PROMPTS)
    for root in _candidate_roots(project_root):
        prompt_dir = root / AGENT_PROMPT_DIR
        if not prompt_dir.exists():
            continue
        roles.update(path.stem for path in prompt_dir.glob("*.md") if path.is_file())
    return sorted(roles)


def _candidate_roots(project_root: Path | None) -> list[Path]:
    roots: list[Path] = []
    if project_root is not None:
        roots.append(Path(project_root))
    module_root = Path(__file__).resolve().parent
    if module_root not in roots:
        roots.append(module_root)
    return roots
