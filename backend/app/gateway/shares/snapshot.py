"""Immutable snapshot builder for read-only conversation sharing (#4548).

Reuses the canonical paged-message path (``_scan_thread_message_page``) and
its visibility helpers rather than adding a second interpretation of thread
history, then converts the result into the narrow public DTO. The design
requires the allowlist here: not every ``hide_from_ui`` message is filtered
by the scan (allowlisted ``ask_clarification`` replies can be persisted), so
the hidden/control filter is applied again on top.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_SNAPSHOT_SCAN_PAGE_SIZE = 200
_SNAPSHOT_MAX_MESSAGES = 2000


async def build_share_snapshot(
    thread_id: str,
    *,
    request: Any,
    user_id: str | None,
) -> dict[str, Any]:
    """Freeze the visible transcript of *thread_id* into a public DTO."""
    from app.gateway.routers.thread_runs import (
        _is_hidden_or_control_message,
        _message_text,
        _message_type,
        _scan_thread_message_page,
    )

    collected: list[dict[str, Any]] = []
    before_seq: int | None = None
    truncated = False
    while True:
        rows, has_more = await _scan_thread_message_page(
            thread_id,
            limit=_SNAPSHOT_SCAN_PAGE_SIZE,
            before_seq=before_seq,
            request=request,
            user_id=user_id,
        )
        if not rows:
            break
        collected.extend(rows)
        if not has_more:
            break
        if len(collected) >= _SNAPSHOT_MAX_MESSAGES:
            # The design freezes the *complete* visible transcript; when the
            # cap bites, the share must not pretend to be complete silently.
            truncated = True
            break
        before_seq = rows[0]["seq"]
    if truncated:
        logger.warning(
            "Share snapshot for thread %s truncated at %d scanned rows (cap %d)",
            thread_id,
            len(collected),
            _SNAPSHOT_MAX_MESSAGES,
        )
    # Backward pages arrive newest-page-first; flip to chronological order.
    collected.reverse()

    messages: list[dict[str, Any]] = []
    for row in collected:
        content = row.get("content")
        message_type = _message_type(content)
        if message_type not in ("human", "ai"):
            continue
        if _is_hidden_or_control_message(content):
            continue
        text = _message_text(content)
        if not text.strip():
            continue
        messages.append(
            {
                # Snapshot-local, monotonic id: the public contract must not
                # leak run-event ids or any store identifiers.
                "id": f"m{len(messages) + 1}",
                "role": "user" if message_type == "human" else "assistant",
                "content": text,
            }
        )

    logger.debug("Share snapshot for thread %s: %d visible messages", thread_id, len(messages))
    return {
        "version": 1,
        "messages": messages,
    }


async def resolve_share_title(thread_id: str, *, request: Any, fallback: str = "Shared conversation") -> str:
    """Best-effort thread title for the share record and public page."""
    from app.gateway.deps import get_thread_store

    try:
        meta = await get_thread_store(request).get(thread_id)
    except Exception:
        logger.warning("Could not read thread meta for share title of %s", thread_id, exc_info=True)
        return fallback
    title = (meta or {}).get("title") if isinstance(meta, dict) else None
    return str(title).strip()[:512] if title and str(title).strip() else fallback
