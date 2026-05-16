"""GenUI telemetry and block recovery API endpoints."""

from __future__ import annotations

import logging
import threading
from collections import defaultdict

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from deerflow.agents.genui_persistence import extract_blocks_from_messages, extract_blocks_from_messages_with_metadata, get_persisted_blocks
from deerflow.tools.render_ui_metrics import get_render_ui_metrics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["genui-telemetry"])


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


class TelemetryEvent(BaseModel):
    type: str
    component: str | None = None
    block_id: str | None = None
    callback_id: str | None = None
    duration_ms: float | None = None
    error: str | None = None
    timestamp: float


class TelemetryBatch(BaseModel):
    events: list[TelemetryEvent] = Field(default_factory=list)


class TelemetryMetrics:
    """In-memory telemetry aggregation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.render_count: int = 0
        self.render_error_count: int = 0
        self.interaction_count: int = 0
        self.interaction_error_count: int = 0
        self.render_durations: list[float] = []
        self.errors_by_component: dict[str, int] = defaultdict(int)

    def record(self, event: TelemetryEvent) -> None:
        with self._lock:
            if event.type == "block_render_complete":
                self.render_count += 1
                if event.duration_ms is not None:
                    self.render_durations.append(event.duration_ms)
            elif event.type == "block_render_error":
                self.render_error_count += 1
                if event.component:
                    self.errors_by_component[event.component] += 1
            elif event.type == "interaction_submit":
                self.interaction_count += 1
            elif event.type == "interaction_error":
                self.interaction_error_count += 1

    def summary(self) -> dict:
        with self._lock:
            avg_render = (
                sum(self.render_durations) / len(self.render_durations)
                if self.render_durations
                else 0
            )
            return {
                "render_count": self.render_count,
                "render_error_count": self.render_error_count,
                "interaction_count": self.interaction_count,
                "interaction_error_count": self.interaction_error_count,
                "avg_render_duration_ms": round(avg_render, 2),
                "errors_by_component": dict(self.errors_by_component),
            }


_metrics = TelemetryMetrics()


@router.post("/telemetry/genui")
async def ingest_telemetry(batch: TelemetryBatch) -> dict:
    """Ingest frontend GenUI telemetry events."""
    for event in batch.events:
        _metrics.record(event)
    return {"accepted": len(batch.events)}


@router.get("/telemetry/genui/summary")
async def get_telemetry_summary() -> dict:
    """Get aggregated GenUI telemetry metrics."""
    return _metrics.summary()


@router.get("/telemetry/genui/backend-metrics")
async def get_backend_metrics() -> dict:
    """Get backend-side render_ui tool metrics (invocations, errors, latency)."""
    return get_render_ui_metrics().summary()


# ---------------------------------------------------------------------------
# Block Recovery
# ---------------------------------------------------------------------------


@router.get("/threads/{thread_id}/ui-blocks")
async def get_thread_blocks(thread_id: str, request: Request) -> list[dict]:
    """Retrieve persisted UI blocks for SSE recovery.

    Returns the union of the in-memory store (current turn) and checkpoint
    message extraction (all turns), so recovery always sees the complete
    history even after the in-memory store is cleared at turn boundaries.
    """
    persisted = get_persisted_blocks(thread_id)
    persisted_ids = {b.get("block_id") for b in persisted if b.get("block_id")}

    try:
        from app.gateway.deps import get_run_event_store

        event_store = get_run_event_store(request)
        stored_messages = await event_store.list_messages(thread_id, limit=500)
        raw_messages = [m.get("content", m) if isinstance(m, dict) else m for m in stored_messages]
        from_messages = extract_blocks_from_messages(raw_messages)

        for b in from_messages:
            bid = b.get("block_id")
            if bid and bid not in persisted_ids:
                persisted.append(b)
    except Exception:
        logger.debug("Checkpoint-based block recovery failed for thread %s", thread_id, exc_info=True)

    return persisted


class ExtractBlocksRequest(BaseModel):
    messages: list[dict] = Field(..., description="Messages to extract UI blocks from")


class ExtractBlocksResponse(BaseModel):
    blocks: list[dict]
    blockIdsByMessageKey: dict[str, list[str]]
    duplicatedRawBlockIds: list[str]


@router.post("/threads/{thread_id}/ui-blocks/extract", response_model=ExtractBlocksResponse)
async def extract_thread_blocks(thread_id: str, req: ExtractBlocksRequest) -> ExtractBlocksResponse:
    """Extract and fold UI blocks from historical messages.

    Parses <!--ui_block:...--> markers from message content, applies
    create/update/delete folding with block ID deduplication, enriches
    interactive blocks with their submission status from the InteractionStore,
    and returns folded blocks along with visibility metadata (message-to-block
    mapping and duplicated block IDs).
    """
    result = extract_blocks_from_messages_with_metadata(req.messages)

    # Enrich interactive blocks with submission status from the InteractionStore.
    from deerflow.agents.middlewares.genui_middleware import get_interaction_store

    store = get_interaction_store()
    for block in result["blocks"]:
        if block.get("interactive") and block.get("callback_id"):
            record = store.get(thread_id, block["callback_id"])
            block["interaction_status"] = "submitted" if (record and record.submitted) else "idle"

    return ExtractBlocksResponse(**result)
