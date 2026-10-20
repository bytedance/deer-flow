"""Enumerate the threads a checkpointer holds, in checkpoint write order.

LangGraph has no thread-listing API, and ``BaseCheckpointSaver.list(None)``
walks every checkpoint of every thread: a listing built on it either loads whole
histories or, given ``limit``, counts checkpoints instead of threads.

Order follows ``checkpoint_id``. Savers mint time-ordered UUID6 ids, and
LangGraph itself defines a thread's latest checkpoint as its largest id.
``checkpoint["ts"]`` is not a recency signal: a goal write copies the previous
checkpoint's ``ts`` under a fresh id. Discovery does not assume any particular
first checkpoint either — a Gateway branch is seeded by ``update_state``
(``step`` 0), not by an input checkpoint (``step`` -1).

The SQLite and Postgres savers answer from their primary-key index
``(thread_id, checkpoint_ns, checkpoint_id)``, one row per thread. Any other
saver falls back to a single ``list(None)`` walk: equally correct, only slower.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from langgraph.checkpoint.sqlite import SqliteSaver

from deerflow.runtime.checkpointer.cached_saver import CachedHistorySaver

try:  # optional extra: deerflow-harness[postgres]
    from langgraph.checkpoint.postgres import PostgresSaver
except ImportError:  # pragma: no cover - exercised only without the extra
    PostgresSaver = None

ThreadSpanOrder = Literal["first", "latest"]

_ORDER_COLUMNS: dict[str, str] = {"first": "first_checkpoint_id", "latest": "latest_checkpoint_id"}

_SPANS_SQL = """
    SELECT thread_id, MIN(checkpoint_id) AS first_checkpoint_id, MAX(checkpoint_id) AS latest_checkpoint_id
    FROM checkpoints
    WHERE checkpoint_ns = ''
    GROUP BY thread_id
    ORDER BY {order_column} DESC, thread_id
"""


@dataclass(frozen=True)
class ThreadSpan:
    """A thread's first and latest root-namespace checkpoint ids."""

    thread_id: str
    first_checkpoint_id: str
    latest_checkpoint_id: str


def list_thread_spans(checkpointer: Any, *, order_by: ThreadSpanOrder, limit: int | None = None) -> list[ThreadSpan]:
    """Return up to *limit* threads, newest first by their first or latest checkpoint."""
    if order_by not in _ORDER_COLUMNS:
        raise ValueError(f"order_by must be 'first' or 'latest', got {order_by!r}")
    if limit is not None and limit <= 0:
        return []
    # The delta-history cache wraps the saver but never owns which threads exist.
    saver = checkpointer._inner if isinstance(checkpointer, CachedHistorySaver) else checkpointer
    sql = _SPANS_SQL.format(order_column=_ORDER_COLUMNS[order_by])
    if isinstance(saver, SqliteSaver):
        params: tuple = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        with saver.cursor(transaction=False) as cur:
            cur.execute(sql, params)
            return [ThreadSpan(*row) for row in cur.fetchall()]
    if PostgresSaver is not None and isinstance(saver, PostgresSaver):
        params = ()
        if limit is not None:
            sql += " LIMIT %s"
            params = (limit,)
        with saver._cursor() as cur:
            cur.execute(sql, params)
            return [ThreadSpan(row["thread_id"], row["first_checkpoint_id"], row["latest_checkpoint_id"]) for row in cur.fetchall()]
    return _scan_thread_spans(checkpointer, order_by=order_by, limit=limit)


def _scan_thread_spans(checkpointer: Any, *, order_by: ThreadSpanOrder, limit: int | None) -> list[ThreadSpan]:
    bounds: dict[str, tuple[str, str]] = {}
    for cp in checkpointer.list(None):
        cfg = cp.config.get("configurable", {})
        thread_id = cfg.get("thread_id")
        checkpoint_id = cfg.get("checkpoint_id")
        # Subgraph namespaces keep their own checkpoints; only the root namespace describes the thread.
        if not thread_id or not checkpoint_id or cfg.get("checkpoint_ns"):
            continue
        first, latest = bounds.get(thread_id, (checkpoint_id, checkpoint_id))
        bounds[thread_id] = (min(first, checkpoint_id), max(latest, checkpoint_id))
    spans = [ThreadSpan(thread_id, first, latest) for thread_id, (first, latest) in bounds.items()]
    spans.sort(key=lambda span: span.thread_id)
    spans.sort(key=lambda span: getattr(span, _ORDER_COLUMNS[order_by]), reverse=True)
    return spans if limit is None else spans[:limit]
