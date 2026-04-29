"""Run routing decisions for local Codex multi-agent workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


ROUTING_MODES = ("fast", "balanced", "parallel", "manual")


@dataclass(frozen=True)
class RoutingDecision:
    """Concrete pipeline selection for a run."""

    requested_mode: str
    mode: str
    reason: str
    planner_count: int
    code_agent_count: int
    qa_agent_count: int
    pipeline: list[str]
    uses_contract: bool
    uses_scaffold: bool
    uses_integrator: bool
    uses_llm_qa: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "RoutingDecision":
        return RoutingDecision(
            requested_mode=str(payload.get("requested_mode") or payload.get("mode") or "balanced"),
            mode=str(payload.get("mode") or "balanced"),
            reason=str(payload.get("reason") or "Loaded from run state."),
            planner_count=max(1, int(payload.get("planner_count", 2))),
            code_agent_count=max(1, int(payload.get("code_agent_count", 1))),
            qa_agent_count=max(0, int(payload.get("qa_agent_count", 0))),
            pipeline=[str(item) for item in payload.get("pipeline", [])],
            uses_contract=bool(payload.get("uses_contract", False)),
            uses_scaffold=bool(payload.get("uses_scaffold", False)),
            uses_integrator=bool(payload.get("uses_integrator", False)),
            uses_llm_qa=bool(payload.get("uses_llm_qa", False)),
        )


def normalize_routing_mode(value: str | None) -> str:
    mode = (value or "balanced").strip().lower()
    if mode not in ROUTING_MODES:
        allowed = ", ".join(ROUTING_MODES)
        raise ValueError(f"routing mode must be one of: {allowed}")
    return mode


def decide_route(
    user_request: str,
    *,
    requested_mode: str = "balanced",
    max_code_agent_count: int = 2,
    max_qa_agent_count: int = 1,
) -> RoutingDecision:
    """Resolve the user-selected route into a concrete pipeline."""

    requested = normalize_routing_mode(requested_mode)
    max_code = max(1, int(max_code_agent_count))
    max_qa = max(0, int(max_qa_agent_count))

    if requested == "manual":
        if max_code > 1:
            return _parallel_decision(
                requested,
                code_agent_count=max_code,
                qa_agent_count=max_qa,
                reason="Manual mode requested with more than one code agent.",
            )
        return _balanced_decision(
            requested,
            qa_agent_count=max_qa,
            reason="Manual mode requested with one code agent.",
        )

    if requested == "fast":
        return _fast_decision(requested, reason="Fast mode requested.")
    if requested == "balanced":
        return _balanced_decision(requested, qa_agent_count=min(1, max_qa), reason="Balanced mode requested.")
    if requested == "parallel":
        return _parallel_decision(
            requested,
            code_agent_count=max(2, min(max_code, 4)),
            qa_agent_count=min(max_qa, 2),
            reason="Parallel mode requested.",
        )

    return _balanced_decision(requested, qa_agent_count=min(1, max_qa), reason="Balanced mode requested.")


def _fast_decision(requested_mode: str, *, reason: str) -> RoutingDecision:
    return RoutingDecision(
        requested_mode=requested_mode,
        mode="fast",
        reason=reason,
        planner_count=1,
        code_agent_count=1,
        qa_agent_count=0,
        pipeline=["planner_a", "code_1", "mechanical_qa"],
        uses_contract=False,
        uses_scaffold=False,
        uses_integrator=False,
        uses_llm_qa=False,
    )


def _balanced_decision(requested_mode: str, *, qa_agent_count: int, reason: str) -> RoutingDecision:
    qa_count = max(0, qa_agent_count)
    pipeline = ["planner_a", "planner_b", "planner_a_final", "code_1", "mechanical_qa"]
    if qa_count:
        pipeline.append("qa_agent")
    return RoutingDecision(
        requested_mode=requested_mode,
        mode="balanced",
        reason=reason,
        planner_count=2,
        code_agent_count=1,
        qa_agent_count=qa_count,
        pipeline=pipeline,
        uses_contract=False,
        uses_scaffold=False,
        uses_integrator=False,
        uses_llm_qa=qa_count > 0,
    )


def _parallel_decision(
    requested_mode: str,
    *,
    code_agent_count: int,
    qa_agent_count: int,
    reason: str,
) -> RoutingDecision:
    qa_count = max(0, qa_agent_count)
    pipeline = [
        "planner_a",
        "planner_b",
        "planner_a_final",
        "architect_contract",
        "scaffold",
        "code_agents",
        "integrator",
        "mechanical_qa",
    ]
    if qa_count:
        pipeline.append("qa_agent")
    return RoutingDecision(
        requested_mode=requested_mode,
        mode="parallel",
        reason=reason,
        planner_count=2,
        code_agent_count=max(2, code_agent_count),
        qa_agent_count=qa_count,
        pipeline=pipeline,
        uses_contract=True,
        uses_scaffold=True,
        uses_integrator=True,
        uses_llm_qa=qa_count > 0,
    )
