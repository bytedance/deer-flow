"""LangGraph-based blackboard orchestration for non-linear research workflows."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from src.research_writing.evidence_store import EvidenceUnit
from src.research_writing.project_state import ResearchProject, SectionDraft

AgentRole = Literal["data-scientist", "experiment-designer", "writer-agent"]
PostKind = Literal["observation", "challenge", "proposal", "draft", "decision", "memory"]
GraphRoute = Literal["loop", "finish"]


class BlackboardPost(TypedDict):
    post_id: str
    round: int
    agent: AgentRole
    kind: PostKind
    content: str
    references: list[str]
    created_at: str
    metadata: dict[str, Any]


class AgenticGraphState(TypedDict, total=False):
    project_id: str
    section_id: str | None
    max_rounds: int
    current_round: int
    evidence_count: int
    citation_count: int
    section_text: str
    project_questions: list[str]
    blackboard: list[BlackboardPost]
    route_trace: list[str]
    open_gaps: list[str]
    proposed_actions: list[str]
    final_draft: str
    request_more_data: bool
    reroute_count: int
    historical_failed_attempts: list[dict[str, Any]]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _dedup(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = str(raw).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _append_route(routes: list[str], node_name: str) -> list[str]:
    return [*routes, node_name]


def _post_id(round_idx: int, agent: AgentRole, serial: int) -> str:
    normalized_agent = agent.replace("-", "_")
    return f"r{round_idx}_{normalized_agent}_{serial}"


def _append_post(
    *,
    blackboard: list[BlackboardPost],
    round_idx: int,
    agent: AgentRole,
    kind: PostKind,
    content: str,
    references: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    serial = len(blackboard) + 1
    blackboard.append(
        {
            "post_id": _post_id(round_idx, agent, serial),
            "round": round_idx,
            "agent": agent,
            "kind": kind,
            "content": content.strip(),
            "references": [str(item).strip() for item in (references or []) if str(item).strip()],
            "created_at": _now_iso(),
            "metadata": metadata or {},
        }
    )


def _historical_failure_hint(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return ""
    top = entries[0]
    summary = str(top.get("summary") or "").strip()
    if not summary:
        return ""
    status = str(top.get("validation_status") or "failed").strip().lower()
    hypothesis_id = str(top.get("hypothesis_id") or "unknown").strip() or "unknown"
    return f"Historical {status} attempt ({hypothesis_id}): {summary}"


def _project_context_hint(state: AgenticGraphState) -> str:
    questions = [str(item).strip() for item in state.get("project_questions", []) if str(item).strip()]
    if not questions:
        return ""
    return f"Research focus: {questions[0]}"


def _data_scientist_node(state: AgenticGraphState) -> dict[str, Any]:
    round_idx = int(state.get("current_round", 1))
    evidence_count = int(state.get("evidence_count", 0))
    citation_count = int(state.get("citation_count", 0))
    section_text = str(state.get("section_text") or "").strip()
    blackboard = [*state.get("blackboard", [])]
    existing_gaps = [str(item).strip() for item in state.get("open_gaps", []) if str(item).strip()]
    gaps: list[str] = []

    if evidence_count < 2:
        gaps.append("Structured evidence is sparse; Discussion claims should be downgraded until more raw analysis is available.")
    if citation_count < 2:
        gaps.append("Literature triangulation is weak; at least one independent citation cluster should be added.")
    if section_text and len(section_text.split()) < 45:
        gaps.append("Current section draft is too short to support robust interpretation continuity.")

    failure_hint = _historical_failure_hint(state.get("historical_failed_attempts", []))
    if failure_hint:
        _append_post(
            blackboard=blackboard,
            round_idx=round_idx,
            agent="data-scientist",
            kind="memory",
            content=failure_hint,
        )
        gaps.append("Historical failed attempts indicate signal/noise ambiguity; re-validation is required before strong claims.")

    focus_hint = _project_context_hint(state)
    if gaps:
        _append_post(
            blackboard=blackboard,
            round_idx=round_idx,
            agent="data-scientist",
            kind="observation",
            content=f"Data audit detected {len(gaps)} blocking gap(s). {focus_hint}".strip(),
            metadata={"evidence_count": evidence_count, "citation_count": citation_count},
        )
        _append_post(
            blackboard=blackboard,
            round_idx=round_idx,
            agent="data-scientist",
            kind="challenge",
            content=" | ".join(gaps[:3]),
        )
    else:
        _append_post(
            blackboard=blackboard,
            round_idx=round_idx,
            agent="data-scientist",
            kind="observation",
            content="Data audit reached a pass threshold; no blocking evidence gap remains.",
            metadata={"evidence_count": evidence_count, "citation_count": citation_count},
        )

    return {
        "blackboard": blackboard,
        "open_gaps": _dedup([*existing_gaps, *gaps]),
        "route_trace": _append_route(state.get("route_trace", []), "data-scientist"),
    }


def _experiment_designer_node(state: AgenticGraphState) -> dict[str, Any]:
    round_idx = int(state.get("current_round", 1))
    gaps = [str(item).strip() for item in state.get("open_gaps", []) if str(item).strip()]
    blackboard = [*state.get("blackboard", [])]

    if not gaps:
        actions = ["No extra experiment required. Preserve reproducibility checklist and continue writing."]
        _append_post(
            blackboard=blackboard,
            round_idx=round_idx,
            agent="experiment-designer",
            kind="proposal",
            content=actions[0],
        )
    else:
        actions = []
        for idx, gap in enumerate(gaps[:3], start=1):
            action = (
                f"E{idx}: Design a validation package for gap '{gap}'. "
                "Include power assumptions, control/ablation setup, and stop/go criteria."
            )
            actions.append(action)
        _append_post(
            blackboard=blackboard,
            round_idx=round_idx,
            agent="experiment-designer",
            kind="proposal",
            content="\n".join(f"- {item}" for item in actions),
        )

    return {
        "blackboard": blackboard,
        "proposed_actions": actions,
        "route_trace": _append_route(state.get("route_trace", []), "experiment-designer"),
    }


def _writer_node(state: AgenticGraphState) -> dict[str, Any]:
    round_idx = int(state.get("current_round", 1))
    max_rounds = max(1, int(state.get("max_rounds", 3)))
    gaps = [str(item).strip() for item in state.get("open_gaps", []) if str(item).strip()]
    actions = [str(item).strip() for item in state.get("proposed_actions", []) if str(item).strip()]
    blackboard = [*state.get("blackboard", [])]

    if gaps:
        next_actions = "; ".join(actions[:3]) if actions else "No concrete action list was produced"
        draft = (
            "Discussion draft (conservative): current evidence does not justify a definitive mechanistic conclusion. "
            f"Priority validation actions: {next_actions}."
        )
        request_more_data = round_idx < max_rounds
        if request_more_data:
            decision = "Writer requests another evidence loop (non-linear reroute to Data Scientist)."
        else:
            decision = "Writer stops rerouting due to round cap and keeps a risk-conservative conclusion."
    else:
        draft = (
            "Discussion draft: evidence and literature now align on the leading mechanism. "
            "Claims can remain cautious but no additional blocking reroute is required."
        )
        request_more_data = False
        decision = "Writer converges and finalizes the current section narrative."

    _append_post(
        blackboard=blackboard,
        round_idx=round_idx,
        agent="writer-agent",
        kind="draft",
        content=draft,
    )
    _append_post(
        blackboard=blackboard,
        round_idx=round_idx,
        agent="writer-agent",
        kind="decision",
        content=decision,
        metadata={"request_more_data": request_more_data, "gap_count": len(gaps)},
    )

    return {
        "blackboard": blackboard,
        "final_draft": draft,
        "request_more_data": request_more_data,
        "current_round": round_idx + 1 if request_more_data else round_idx,
        "reroute_count": int(state.get("reroute_count", 0)) + (1 if request_more_data else 0),
        "route_trace": _append_route(state.get("route_trace", []), "writer-agent"),
        "open_gaps": gaps if request_more_data else [],
    }


def _writer_route(state: AgenticGraphState) -> GraphRoute:
    if bool(state.get("request_more_data")) and int(state.get("current_round", 1)) <= max(1, int(state.get("max_rounds", 3))):
        return "loop"
    return "finish"


def _compile_graph():
    builder = StateGraph(AgenticGraphState)
    builder.add_node("data_scientist", _data_scientist_node)
    builder.add_node("experiment_designer", _experiment_designer_node)
    builder.add_node("writer", _writer_node)
    builder.add_edge(START, "data_scientist")
    builder.add_edge("data_scientist", "experiment_designer")
    builder.add_edge("experiment_designer", "writer")
    builder.add_conditional_edges(
        "writer",
        _writer_route,
        {
            "loop": "data_scientist",
            "finish": END,
        },
    )
    return builder.compile()


_GRAPH = _compile_graph()


def run_agentic_blackboard_graph(
    *,
    project: ResearchProject,
    section: SectionDraft | None,
    evidence_units: list[EvidenceUnit],
    historical_failed_attempts: list[dict[str, Any]] | None = None,
    max_rounds: int = 3,
    seed_idea: str | None = None,
) -> dict[str, Any]:
    """Run the non-linear graph and return full blackboard trace."""

    citation_ids: set[str] = set()
    for unit in evidence_units:
        citation_ids.update([str(item).strip() for item in unit.citation_ids if str(item).strip()])

    state: AgenticGraphState = {
        "project_id": project.project_id,
        "section_id": section.section_id if section else None,
        "max_rounds": max(1, max_rounds),
        "current_round": 1,
        "evidence_count": len(evidence_units),
        "citation_count": len(citation_ids),
        "section_text": section.content if section else "",
        "project_questions": [str(item).strip() for item in project.research_questions if str(item).strip()],
        "blackboard": [],
        "route_trace": [],
        "open_gaps": [],
        "proposed_actions": [],
        "final_draft": "",
        "request_more_data": False,
        "reroute_count": 0,
        "historical_failed_attempts": [item for item in (historical_failed_attempts or []) if isinstance(item, dict)][:3],
    }

    final_state = _GRAPH.invoke(state)
    blackboard = [item for item in final_state.get("blackboard", []) if isinstance(item, dict)]
    decision_posts = [item for item in blackboard if str(item.get("agent") or "") == "writer-agent" and str(item.get("kind") or "") == "decision"]
    rounds_executed = len(decision_posts)

    return {
        "orchestrator_version": "deerflow.agentic_graph.v1",
        "project_id": project.project_id,
        "section_id": section.section_id if section else None,
        "seed_idea": str(seed_idea).strip() if seed_idea else None,
        "max_rounds": max(1, max_rounds),
        "rounds_executed": rounds_executed,
        "reroute_count": int(final_state.get("reroute_count", 0)),
        "converged": len(final_state.get("open_gaps", [])) == 0,
        "open_gaps": [str(item).strip() for item in final_state.get("open_gaps", []) if str(item).strip()],
        "proposed_actions": [str(item).strip() for item in final_state.get("proposed_actions", []) if str(item).strip()],
        "final_writer_draft": str(final_state.get("final_draft") or ""),
        "route_trace": [str(item).strip() for item in final_state.get("route_trace", []) if str(item).strip()],
        "blackboard": blackboard,
        "historical_failed_attempts": [item for item in state.get("historical_failed_attempts", []) if isinstance(item, dict)],
        "agents": ["data-scientist", "experiment-designer", "writer-agent"],
    }

