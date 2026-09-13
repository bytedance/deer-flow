"""Request-independent visible transcript pagination for Gateway consumers.

Callers own authentication, thread ownership, and read permission checks. Every
storage query receives the explicit caller identity; this module never derives
access from a model argument or an ambient HTTP request.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deerflow.runtime.events.store.base import RunEventStore
    from deerflow.runtime.runs.manager import RunManager

logger = logging.getLogger(__name__)


async def read_visible_message_page(
    *,
    event_store: RunEventStore,
    run_manager: RunManager,
    thread_id: str,
    user_id: str | None,
    limit: int,
    before_seq: int | None = None,
    message_filter: Callable[[dict[str, Any]], bool] | None = None,
    batch_size: int = 201,
) -> tuple[list[dict[str, Any]], bool]:
    """Read a backward page, filtering before counting rows and looking ahead.

    ``message_filter`` may narrow the HTTP-visible transcript (for example to
    user/assistant text), but cannot admit rows excluded by the shared history rules. The caller
    can continue before the first returned row's ``seq`` when ``has_more`` is true.
    No feedback, duration, or other UI-only enrichment is performed here.
    """
    hidden_run_ids = await default_history_hidden_run_ids(run_manager, thread_id, user_id=user_id)
    return await scan_visible_thread_messages(
        thread_id,
        limit=limit,
        before_seq=before_seq,
        after_seq=None,
        event_store=event_store,
        user_id=user_id,
        hidden_run_ids=hidden_run_ids,
        include_middleware=False,
        include_extra=True,
        batch_size=batch_size,
        message_filter=message_filter,
    )


async def default_history_hidden_run_ids(run_mgr: RunManager, thread_id: str, *, user_id: str | None) -> set[str]:
    superseded_run_ids = await run_mgr.list_successful_regenerate_sources(thread_id, user_id=user_id)
    edit_visibility = await run_mgr.list_edit_replay_visibility(thread_id, user_id=user_id)
    return set(superseded_run_ids) | set(edit_visibility.hidden_source_run_ids) | set(edit_visibility.hidden_attempt_run_ids)


def _message_type(message: Any) -> str | None:
    value = getattr(message, "type", None)
    if value is None and isinstance(message, dict):
        value = message.get("type") or message.get("role")
    if value == "assistant":
        return "ai"
    return str(value) if value else None


def _is_thread_history_hidden_message_row(row: dict[str, Any]) -> bool:
    caller = str((row.get("metadata") or {}).get("caller", ""))
    return caller.startswith("middleware:") or (caller.startswith("subagent:") and _message_type(row.get("content")) == "ai")


async def scan_visible_thread_messages(
    thread_id: str,
    *,
    limit: int,
    before_seq: int | None,
    after_seq: int | None,
    event_store: RunEventStore,
    user_id: str | None,
    hidden_run_ids: set[str],
    include_middleware: bool,
    include_extra: bool,
    batch_size: int,
    message_filter: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Scan raw message rows until ``limit`` visible rows survive filtering."""
    needed = limit + 1 if include_extra else limit

    if after_seq is not None:
        visible: list[dict[str, Any]] = []
        scan_after = after_seq
        while len(visible) < needed:
            raw = await event_store.list_messages(
                thread_id,
                limit=batch_size,
                after_seq=scan_after,
                user_id=user_id,
            )
            if not raw:
                break
            _validate_message_scan_rows(raw, thread_id=thread_id, scan_before=None, scan_after=scan_after)
            reached_before_bound = False
            for row in raw:
                if before_seq is not None and row["seq"] >= before_seq:
                    reached_before_bound = True
                    break
                if (not include_middleware and _is_thread_history_hidden_message_row(row)) or row.get("run_id") in hidden_run_ids or (message_filter is not None and not message_filter(row)):
                    continue
                visible.append(row)
                if len(visible) == needed:
                    break
            next_scan_after = max(row["seq"] for row in raw)
            if next_scan_after <= scan_after:
                _raise_non_advancing_message_scan(thread_id=thread_id, scan_before=None, scan_after=scan_after, next_cursor=next_scan_after, row_count=len(raw))
            scan_after = next_scan_after
            if reached_before_bound or len(raw) < batch_size:
                break
        has_more = len(visible) > limit
        return visible[:limit], has_more

    visible_desc: list[dict[str, Any]] = []
    scan_before = before_seq
    while len(visible_desc) < needed:
        raw = await event_store.list_messages(
            thread_id,
            limit=batch_size,
            before_seq=scan_before,
            user_id=user_id,
        )
        if not raw:
            break
        _validate_message_scan_rows(raw, thread_id=thread_id, scan_before=scan_before, scan_after=None)
        for row in reversed(raw):
            if (not include_middleware and _is_thread_history_hidden_message_row(row)) or row.get("run_id") in hidden_run_ids or (message_filter is not None and not message_filter(row)):
                continue
            visible_desc.append(row)
            if len(visible_desc) == needed:
                break
        next_scan_before = min(row["seq"] for row in raw)
        if scan_before is not None and next_scan_before >= scan_before:
            _raise_non_advancing_message_scan(thread_id=thread_id, scan_before=scan_before, scan_after=None, next_cursor=next_scan_before, row_count=len(raw))
        scan_before = next_scan_before
        if len(raw) < batch_size:
            break
    has_more = len(visible_desc) > limit
    return list(reversed(visible_desc[:limit])), has_more


def _validate_message_scan_rows(
    rows: list[dict[str, Any]],
    *,
    thread_id: str,
    scan_before: int | None,
    scan_after: int | None,
) -> None:
    invalid_seq_rows = [row for row in rows if not isinstance(row.get("seq"), int)]
    if invalid_seq_rows:
        logger.error(
            "Thread message scan found rows without sequence values: thread_id=%s scan_before=%s scan_after=%s row_count=%d invalid_count=%d",
            thread_id,
            scan_before,
            scan_after,
            len(rows),
            len(invalid_seq_rows),
        )
        raise RuntimeError("Run event message rows are missing sequence values")


def _raise_non_advancing_message_scan(
    *,
    thread_id: str,
    scan_before: int | None,
    scan_after: int | None,
    next_cursor: int,
    row_count: int,
) -> None:
    logger.error(
        "Thread message scan cursor did not advance: thread_id=%s scan_before=%s scan_after=%s next_cursor=%s row_count=%d",
        thread_id,
        scan_before,
        scan_after,
        next_cursor,
        row_count,
    )
    raise RuntimeError("Run event message scan did not advance its cursor")
