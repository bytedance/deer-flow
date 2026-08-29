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

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
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

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        page = pages[calls["n"]]
        calls["n"] += 1
        return page, calls["n"] < len(pages)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert [m["content"] for m in snapshot["messages"]] == [f"m{seq}" for seq in range(1, 9)]


async def test_snapshot_skips_empty_text_messages():
    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        return ([_row(1, {"type": "human", "content": "   "})], False)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert snapshot["messages"] == []


async def test_snapshot_excludes_reasoning_and_tool_content_blocks():
    pages = [
        [
            _row(
                1,
                {
                    "type": "ai",
                    "content": [
                        {"type": "thinking", "text": "private chain of thought"},
                        {"type": "reasoning", "text": "private reasoning"},
                        {"type": "tool_call", "text": "private tool args", "args": {"secret": True}},
                        {"type": "text", "text": "public answer"},
                        {"type": "output_text", "text": "public follow-up"},
                    ],
                },
            ),
            _row(2, {"type": "ai", "content": {"type": "thinking", "text": "top-level private thought"}}),
            _row(3, {"type": "ai", "content": "<think>inline private thought</think>visible answer"}),
        ]
    ]

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        return pages[0], False

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert snapshot["messages"] == [
        {"id": "m1", "role": "assistant", "content": "public answer\npublic follow-up"},
        {"id": "m2", "role": "assistant", "content": "visible answer"},
    ]
    serialized = str(snapshot)
    assert "private" not in serialized


async def test_snapshot_preserves_literal_think_tags_inside_markdown_code():
    visible = "\n".join(
        [
            "Use `<think>text</think>` markers.",
            "```xml",
            "<think>literal fenced example</think>",
            "```",
            "<think>private reasoning</think>Visible answer.",
        ]
    )

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        return [_row(1, {"type": "ai", "content": visible})], False

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    content = snapshot["messages"][0]["content"]
    assert "`<think>text</think>`" in content
    assert "<think>literal fenced example</think>" in content
    assert "private reasoning" not in content
    assert "Visible answer." in content


async def test_snapshot_neutralizes_private_artifact_paths_and_urls():
    private_text = "\n".join(
        [
            "![private image](/mnt/user-data/outputs/secret.svg)",
            "[download](/api/threads/thread-secret/artifacts/mnt/user-data/outputs/report.pdf)",
            "raw path: /mnt/user-data/uploads/private.csv",
            "[encoded](%2Fapi%2Fthreads%2Fthread-secret%2Fartifacts%2Fmnt%2Fuser-data%2Foutputs%2Fencoded.pdf)",
            "[public source](https://example.com/report)",
        ]
    )

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        return [_row(1, {"type": "ai", "content": private_text})], False

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    content = snapshot["messages"][0]["content"]
    assert "/mnt/user-data" not in content
    assert "thread-secret" not in content
    assert "%2Fapi%2Fthreads" not in content
    assert "[private artifact omitted]" in content
    assert "[public source](https://example.com/report)" in content


async def test_snapshot_cap_rejects_instead_of_truncating(caplog):
    """The first public message beyond the cap must fail loudly."""
    pages = [
        [_row(seq, {"type": "human", "content": f"m{seq}"}) for seq in range(2, 12)],
        [_row(1, {"type": "human", "content": "m1"})],
    ]
    calls = {"n": 0}

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        page = pages[calls["n"]]
        calls["n"] += 1
        return page, calls["n"] < len(pages)

    from app.gateway.shares import snapshot as snapshot_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(snapshot_module, "_SNAPSHOT_MAX_MESSAGES", 10)
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        with caplog.at_level(logging.WARNING, logger="app.gateway.shares.snapshot"):
            with pytest.raises(ShareSnapshotTooLarge) as excinfo:
                await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert excinfo.value.cap == 10
    assert excinfo.value.hit == 11
    assert any("refusing partial share" in record.message for record in caplog.records)


async def test_snapshot_rejects_when_terminal_page_pushes_public_count_over_cap():
    """A mixed terminal page may cross the cap even when no older page exists."""

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        return [_row(seq, {"type": "human", "content": f"m{seq}"}) for seq in range(1, 5)], False

    from app.gateway.shares import snapshot as snapshot_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(snapshot_module, "_SNAPSHOT_MAX_MESSAGES", 3)
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        with pytest.raises(ShareSnapshotTooLarge) as excinfo:
            await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert excinfo.value.cap == 3
    assert excinfo.value.hit == 4


async def test_snapshot_at_cap_scans_older_non_public_page_before_deciding():
    """Canonical ``has_more`` can mean only older non-public rows remain."""
    pages = [
        [_row(seq, {"type": "human", "content": f"m{seq}"}) for seq in range(2, 5)],
        [_row(1, {"type": "tool", "content": "tool-only"})],
    ]
    calls = {"n": 0}

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        page = pages[calls["n"]]
        calls["n"] += 1
        return page, calls["n"] < len(pages)

    from app.gateway.shares import snapshot as snapshot_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(snapshot_module, "_SNAPSHOT_MAX_MESSAGES", 3)
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert calls["n"] == 2
    assert [message["content"] for message in snapshot["messages"]] == ["m2", "m3", "m4"]


async def test_tool_heavy_thread_does_not_hit_the_cap_early():
    """The cap counts sanitized public messages, not raw rows: tool output
    and hidden rows must not consume share budget (#4548 review)."""
    tool_row = lambda seq: _row(seq, {"type": "tool", "content": '{"args": 1}'})  # noqa: E731
    pages = [
        [tool_row(seq) for seq in range(201, 401)] + [_row(200, {"type": "human", "content": "hi"})],
        [tool_row(seq) for seq in range(1, 200)] + [_row(0, {"type": "human", "content": "hello"})],
    ]
    calls = {"n": 0}

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
        page = pages[calls["n"]]
        calls["n"] += 1
        return page, calls["n"] < len(pages)

    with pytest.MonkeyPatch.context() as mp:
        # A cap that the 400 raw tool rows would exceed, but the 2 public
        # messages must not.
        mp.setattr("app.gateway.shares.snapshot._SNAPSHOT_MAX_MESSAGES", 100)
        mp.setattr("app.gateway.routers.thread_runs._scan_thread_message_page", fake_scan)
        snapshot = await build_share_snapshot("thread-1", request=object(), user_id="user-1")

    assert [m["content"] for m in snapshot["messages"]] == ["hello", "hi"]


async def test_raw_scan_bound_counts_rows_consumed_inside_canonical_pager():
    """Rows filtered inside the canonical pager still consume raw budget."""

    class FakeEventStore:
        def __init__(self):
            self.rows = [
                {
                    "seq": seq,
                    "run_id": "hidden-run",
                    "content": {"type": "human", "content": f"hidden-{seq}"},
                    "metadata": {},
                }
                for seq in range(1, 6)
            ]
            self.raw_rows_returned = 0

        async def list_messages(self, thread_id, *, limit, before_seq=None, after_seq=None, user_id=None):
            assert after_seq is None
            eligible = [row for row in self.rows if before_seq is None or row["seq"] < before_seq]
            page = eligible[-limit:]
            self.raw_rows_returned += len(page)
            return page

    class FakeRunManager:
        async def list_successful_regenerate_sources(self, thread_id, *, user_id):
            return {"hidden-run"}

        async def list_edit_replay_visibility(self, thread_id, *, user_id):
            return SimpleNamespace(hidden_source_run_ids=set(), hidden_attempt_run_ids=set())

    from app.gateway.routers import thread_runs
    from app.gateway.shares import snapshot as snapshot_module

    event_store = FakeEventStore()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                run_event_store=event_store,
                run_manager=FakeRunManager(),
            )
        )
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(snapshot_module, "_SNAPSHOT_MAX_SCANNED_ROWS", 3)
        mp.setattr(thread_runs, "THREAD_MESSAGE_PAGE_SCAN_BATCH", 2)
        with pytest.raises(ShareSnapshotTooLarge) as excinfo:
            await build_share_snapshot("thread-1", request=request, user_id="user-1")

    assert excinfo.value.cap == 3
    assert excinfo.value.hit == 4
    # One sentinel row beyond the cap proves that older raw history exists;
    # the lower-level scan must stop there instead of walking all five rows.
    assert event_store.raw_rows_returned == 4


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

    async def fake_scan(thread_id, *, limit, before_seq, request, user_id, raw_scan_budget=None):
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


async def test_resolve_share_title_reads_real_thread_meta_display_name():
    from langgraph.store.memory import InMemoryStore

    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    user = SimpleNamespace(id="user-1")
    store = MemoryThreadMetaStore(InMemoryStore())
    await store.create("thread-1", user_id=user.id, display_name="Real conversation title")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(thread_store=store)))

    context_token = set_current_user(user)
    try:
        title = await resolve_share_title("thread-1", request=request)
    finally:
        reset_current_user(context_token)

    assert title == "Real conversation title"


async def test_resolve_share_title_neutralizes_private_artifact_reference():
    private_title = "/api/threads/thread-secret/artifacts/mnt/user-data/outputs/report.pdf"

    class _Store:
        async def get(self, thread_id):
            return {"display_name": private_title}

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(thread_store=_Store())))

    title = await resolve_share_title("thread-1", request=request)

    assert "thread-secret" not in title
    assert "/mnt/user-data" not in title
    assert title == "[private artifact omitted]"
