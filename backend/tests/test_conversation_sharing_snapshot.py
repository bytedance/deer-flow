"""Unit tests for the share snapshot builder (#4548).

The builder reuses ``_scan_thread_message_page``; here that canonical scan is
stubbed so the mapping/filters are pinned independently: only visible human/
AI text survives, hidden/control rows are dropped even when the scan let them
through, ids are snapshot-local, and backward pages are flipped to
chronological order.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.gateway.shares.snapshot import build_share_snapshot, resolve_share_title

pytestmark = pytest.mark.anyio


def _row(seq: int, content: dict) -> dict:
    return {"seq": seq, "run_id": f"run-{seq}", "content": content}


async def test_snapshot_keeps_only_visible_human_and_ai_text():
    pages = [
        # Newest backward page (page arrives ascending within itself).
        [
            _row(4, {"type": "ai", "content": "final answer"}),
            _row(3, {"type": "ai", "name": "summary", "content": "summary text"}),
            _row(2, {"type": "remove", "content": ""}),
        ],
        # Older backward page.
        [
            _row(1, {"type": "human", "content": "hello"}),
            _row(0, {"type": "ai", "content": "", "additional_kwargs": {"hide_from_ui": True}}),
        ],
    ]

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id):
        assert before_seq in (None, 4)  # second page continues from the first row's seq
        return (pages[0] if before_seq is None else pages[1]), before_seq is None

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert snapshot["version"] == 1
    assert snapshot["messages"] == [
        {"id": "m1", "role": "user", "content": "hello"},
        {"id": "m2", "role": "assistant", "content": "final answer"},
    ]


async def test_snapshot_skips_empty_text_messages():
    async def fake_scan(thread_id, *, limit, before_seq, request, user_id):
        return ([_row(1, {"type": "human", "content": "   "})], False)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert snapshot["messages"] == []


async def test_snapshot_cap_is_truncated_loudly(caplog):
    """When the message cap bites, the share must not pretend completeness silently."""
    page = [_row(seq, {"type": "human", "content": f"m{seq}"}) for seq in range(1, 11)]

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id):
        return (page, True)  # always more available

    import logging

    from app.gateway.shares import snapshot as snapshot_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(snapshot_module, "_SNAPSHOT_MAX_MESSAGES", 10)
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        with caplog.at_level(logging.WARNING, logger="app.gateway.shares.snapshot"):
            snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert len(snapshot["messages"]) == 10
    assert any("truncated" in record.message for record in caplog.records)


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
