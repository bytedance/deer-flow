"""Thread message cursors bound one exclusive window before applying the limit."""

import pytest

from deerflow.runtime.events.store.memory import MemoryRunEventStore


@pytest.fixture(params=["memory", "jsonl", "sqlite"])
async def window_store(request, tmp_path):
    if request.param == "memory":
        yield MemoryRunEventStore()
    elif request.param == "jsonl":
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

        yield JsonlRunEventStore(base_dir=tmp_path)
    else:
        from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
        from deerflow.runtime.events.store.db import DbRunEventStore

        await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'events.db'}", sqlite_dir=str(tmp_path))
        try:
            yield DbRunEventStore(get_session_factory())
        finally:
            await close_engine()


@pytest.fixture
async def populated_window_store(window_store):
    # Message seqs are 1, 3, 5, 7, 9 across two runs; trace rows fill the gaps.
    for i in range(1, 10):
        await window_store.put(
            thread_id="t1",
            run_id="r1" if i < 5 else "r2",
            event_type="llm.ai.response" if i % 2 else "llm.start",
            category="message" if i % 2 else "trace",
            content={"type": "ai", "id": f"m{i}", "content": f"message {i}"},
        )
    await window_store.put(thread_id="other", run_id="r1", event_type="llm.ai.response", category="message", content="other thread")
    return window_store


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("after_seq", "before_seq", "expected"),
    [(1, 9, [3, 5]), (3, 7, [5]), (4, 8, [5, 7]), (7, 7, []), (9, 3, []), (5, 6, []), (9, 20, [])],
)
async def test_thread_message_window_applies_both_exclusive_cursors(populated_window_store, after_seq, before_seq, expected):
    rows = await populated_window_store.list_messages("t1", after_seq=after_seq, before_seq=before_seq, limit=2)

    assert [row["seq"] for row in rows] == expected
    assert [row["content"]["id"] for row in rows] == [f"m{seq}" for seq in expected]


@pytest.mark.anyio
async def test_forward_pages_keep_a_fixed_upper_bound(populated_window_store):
    pages = []
    after_seq = 1
    for _ in range(4):
        rows = await populated_window_store.list_messages("t1", after_seq=after_seq, before_seq=9, limit=2)
        pages.append([row["seq"] for row in rows])
        if not rows:
            break
        after_seq = rows[-1]["seq"]

    assert pages == [[3, 5], [7], []]


@pytest.mark.anyio
@pytest.mark.parametrize(("cursors", "expected"), [({}, [7, 9]), ({"before_seq": 7}, [3, 5]), ({"after_seq": 3}, [5, 7])])
async def test_single_cursor_and_latest_pages_are_unchanged(populated_window_store, cursors, expected):
    rows = await populated_window_store.list_messages("t1", limit=2, **cursors)

    assert [row["seq"] for row in rows] == expected
