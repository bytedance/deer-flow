"""Memory retrieval tracing models and persistence helpers."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from deerflow.agents.memory.storage import get_memory_file_path
from deerflow.config.memory_config import get_memory_config
from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)

_trace_write_lock = threading.Lock()


class RetrievalDecisionReason(StrEnum):
    """Stable reasons describing retrieval decisions."""

    SELECTED = "selected"
    BUDGET_EXCEEDED = "budget_exceeded"
    SKIPPED_AFTER_BUDGET_EXCEEDED = "skipped_after_budget_exceeded"
    EMPTY_CONTENT = "empty_content"
    INVALID_TYPE = "invalid_type"


@dataclass(slots=True)
class CandidateFact:
    """Sanitized candidate fact metadata for observability."""

    fact_id: str
    content_preview: str
    category: str
    confidence: float
    layer: str | None
    created_at: str | None


@dataclass(slots=True)
class SelectionResult:
    """Selection decision for a candidate fact."""

    fact_id: str
    included: bool
    reason: RetrievalDecisionReason
    rank_position: int
    token_cost: int
    score_components: dict[str, float]


@dataclass(slots=True)
class RetrievalTrace:
    """Trace payload for a single memory retrieval."""

    trace_id: str
    timestamp: str
    agent_name: str | None
    max_tokens: int
    tokens_used: int
    tokens_remaining: int
    total_candidates: int
    selected_count: int
    dropped_count: int
    candidates: list[CandidateFact]
    selections: list[SelectionResult]
    user_context_included: bool
    history_sections_included: list[str]
    context_tokens: int


@dataclass(slots=True)
class InjectionResult:
    """Formatted injection text plus optional retrieval trace."""

    text: str
    trace: RetrievalTrace | None = None


def build_empty_retrieval_trace(max_tokens: int) -> RetrievalTrace:
    """Create an empty trace ready to be populated by the ranking loop."""
    return RetrievalTrace(
        trace_id=uuid.uuid4().hex,
        timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        agent_name=None,
        max_tokens=max_tokens,
        tokens_used=0,
        tokens_remaining=max_tokens,
        total_candidates=0,
        selected_count=0,
        dropped_count=0,
        candidates=[],
        selections=[],
        user_context_included=False,
        history_sections_included=[],
        context_tokens=0,
    )


def _resolve_trace_path(agent_name: str | None = None) -> Path:
    config = get_memory_config().retrieval_trace
    if config.storage_path:
        custom_path = Path(config.storage_path)
        return custom_path if custom_path.is_absolute() else get_paths().base_dir / custom_path
    return get_memory_file_path(agent_name).with_name("retrieval_traces.jsonl")


def _serialize_trace(trace: RetrievalTrace) -> dict[str, Any]:
    """Convert a RetrievalTrace dataclass tree to a plain dict.

    Uses ``dataclasses.asdict`` directly instead of a json.dumps→json.loads
    round-trip.  StrEnum values are converted to plain strings so the result
    is JSON-serializable without a custom *default* hook.
    """
    data = asdict(trace)
    # asdict preserves StrEnum instances; convert them to plain strings
    # so json.dumps works without a custom default handler.
    for sel in data.get("selections", []):
        reason = sel.get("reason")
        if isinstance(reason, StrEnum):
            sel["reason"] = str(reason)
    return data


def emit_retrieval_trace(
    trace: RetrievalTrace | None,
    *,
    agent_name: str | None = None,
) -> None:
    """Persist a retrieval trace when tracing is enabled."""
    if trace is None:
        return

    config = get_memory_config().retrieval_trace
    if not config.enabled:
        return

    trace.agent_name = agent_name
    payload = _serialize_trace(trace)
    payload_line = json.dumps(payload, ensure_ascii=False) + "\n"
    path = _resolve_trace_path(agent_name)

    try:
        with _trace_write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)

            if path.exists():
                current_size = path.stat().st_size
                if current_size + len(payload_line.encode("utf-8")) > config.max_file_bytes:
                    # Use a timestamped name so previous rotated files are
                    # not silently deleted.  Operators should clean up old
                    # rotated files periodically.
                    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                    rotated_name = f"{path.stem}.{ts}{path.suffix}"
                    rotated_path = path.with_name(rotated_name)
                    path.replace(rotated_path)

            with path.open("a", encoding="utf-8") as file:
                file.write(payload_line)

        logger.debug(
            "Persisted memory retrieval trace trace_id=%s path=%s selected=%d dropped=%d bytes=%d",
            trace.trace_id,
            path,
            trace.selected_count,
            trace.dropped_count,
            len(payload_line.encode("utf-8")),
        )
    except OSError as exc:
        logger.warning("Failed to persist memory retrieval trace to %s: %s", path, exc)
