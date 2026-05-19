"""RAG decision event dataclass.

A ``RagDecisionEvent`` is the single source of truth for *what the RAG
subsystem did* on a given turn. Both the RagMiddleware (auto-inject
path) and the ``search_knowledge_base`` tool (LLM-explicit path) emit
one of these per call so the frontend "RAG transparency" panel and the
post-hoc audit pipeline can show users why they did or did not get a
chunk.

The shape is intentionally small and JSON-friendly: it goes onto
``AIMessage.additional_kwargs`` (under ``KB_DECISION_KEY``) and into
SSE payloads without further conversion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

KB_DECISION_KEY = "knowledge_base_decision"

DecisionOutcome = Literal[
    "injected",      # chunks added to context
    "skipped",       # RAG ran but produced nothing useful
    "blocked",       # access denied (no auth, missing tenant)
    "failed",        # exception during retrieval
    "disabled",      # RAG subsystem off
]


@dataclass(slots=True)
class RagDecisionEvent:
    """One decision the RAG subsystem made on this turn."""

    outcome: DecisionOutcome
    reason: str
    source: Literal["middleware", "tool"]
    query: str = ""
    selected_kb_ids: list[str] = field(default_factory=list)
    accessible_kb_ids: list[str] = field(default_factory=list)
    chunks_returned: int = 0
    chunks_injected: int = 0
    score_strategy: str | None = None
    timed_out_kb_ids: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["KB_DECISION_KEY", "DecisionOutcome", "RagDecisionEvent"]
