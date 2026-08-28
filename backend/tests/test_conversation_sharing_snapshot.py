"""Unit tests for the share snapshot builder (#4548).

The builder reuses ``_scan_thread_message_page``; here that canonical scan is
stubbed so the mapping/filters are pinned independently: only visible human/
AI text survives, hidden/control rows are dropped even when the scan let them
through, ids are snapshot-local, and backward pages are flipped to
chronological order.

The stubs mirror the canonical helper's contract exactly (``_scan_visible_
thread_messages`` returns each page ascending by ``seq``; backward pages
arrive newest-page-first) — diverging stubs previously masked a page-order
regression in the builder.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from app.gateway.shares.snapshot import (
    ShareSnapshotTooLarge,
    build_share_snapshot,
    resolve_share_title,
)

pytestmark = pytest.mark.anyio


def _row(seq: int, content: dict) -> dict:
    return {"seq": seq, "run_id": f"run-{seq}", "content": content}


async def test_snapshot_keeps_only_visible_human_and_ai_text():
    # Canonical helper contract: newest backward page first, each page
    # internally ascending by seq.
    pages = [
        [_row(2, {"type": "remove", "content": ""}), _row(3, {"type": "ai", "name": "summary", "content": "summary text"}), _row(4, {"type": "ai", "content": "final answer"})],
        [_row(0, {"type": "ai", "content": "", "additional_kwargs": {"hide_from_ui": True}}), _row(1, {"type": "human", "content": "hello"})],
    ]

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id):
        assert before_seq in (None, 2)  # next cursor is the page's oldest seq
        return (pages[0] if before_seq is None else pages[1]), before_seq is None

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert snapshot["version"] == 1
    assert snapshot["messages"] == [
        {"id": "m1", "role": "user", "content": "hello"},
        {"id": "m2", "role": "assistant", "content": "final answer"},
    ]


async def test_snapshot_preserves_order_across_many_pages():
    """Pages flip order only as wholes; rows inside a page stay ascending."""
    pages = [
        [_row(seq, {"type": "human", "content": f"m{seq}"}) for seq in (7, 8)],
        [_row(seq, {"type": "human", "content": f"m{seq}"}) for seq in (4, 5, 6)],
        [_row(seq, {"type": "human", "content": f"m{seq}"}) for seq in (1, 2, 3)],
    ]
    calls = {"n": 0}

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id):
        page = pages[calls["n"]]
        calls["n"] += 1
        return page, calls["n"] < len(pages)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert [m["content"] for m in snapshot["messages"]] == [f"m{seq}" for seq in range(1, 9)]


async def test_snapshot_skips_empty_text_messages():
    async def fake_scan(thread_id, *, limit, before_seq, request, user_id):
        return ([_row(1, {"type": "human", "content": "   "})], False)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert snapshot["messages"] == []


async def test_snapshot_cap_rejects_instead_of_truncating(caplog):
    """When the cap bites with older rows remaining, creation must fail loudly."""
    page = [_row(seq, {"type": "human", "content": f"m{seq}"}) for seq in range(1, 11)]

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id):
        return (page, True)  # always more available

    from app.gateway.shares import snapshot as snapshot_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(snapshot_module, "_SNAPSHOT_MAX_MESSAGES", 10)
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        with caplog.at_level(logging.WARNING, logger="app.gateway.shares.snapshot"):
            with pytest.raises(ShareSnapshotTooLarge) as excinfo:
                await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert excinfo.value.cap == 10
    assert excinfo.value.scanned_messages == 10
    assert any("refusing partial share" in record.message for record in caplog.records)


async def test_snapshot_exactly_at_cap_with_no_more_rows_shares_completely():
    """At-cap scans with no older rows remaining are complete, not rejected.

    Pins the loop's check order: the ``has_more`` exit must win over the cap
    rejection, or exactly-at-cap conversations would flip from shareable to
    413 on a refactor that swaps the two branches.
    """
    # Canonical helper contract: newest backward page first, each page
    # internally ascending.
    pages = [
        [_row(seq, {"type": "human", "content": f"m{seq}"}) for seq in (5, 6)],
        [_row(seq, {"type": "human", "content": f"m{seq}"}) for seq in (1, 2, 3, 4)],
    ]
    calls = {"n": 0}

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id):
        page = pages[calls["n"]]
        calls["n"] += 1
        return page, calls["n"] < len(pages)

    from app.gateway.shares import snapshot as snapshot_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(snapshot_module, "_SNAPSHOT_MAX_MESSAGES", 6)  # == total rows
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert [m["content"] for m in snapshot["messages"]] == [f"m{seq}" for seq in range(1, 7)]


async def test_resolve_share_title_uses_thread_meta_with_fallback():
    class _Store:
        async def get(self, thread_id, **_kwargs):
            return {"title": "  Project sync  "}

    class _Empty:
        async def get(self, thread_id, **_kwargs):
            return None

    # deps.get_thread_store(request) reads request.app.state.thread_store
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(thread_store=_Store())))
    assert await resolve_share_title("thread-1", request=request) == "Project sync"
    request_empty = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(thread_store=_Empty())))
    assert await resolve_share_title("thread-1", request=request_empty) == "Shared conversation"
