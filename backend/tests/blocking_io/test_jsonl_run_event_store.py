"""Regression anchor: JsonlRunEventStore async API must not block the loop.

``JsonlRunEventStore`` is the ``run_events.backend == "jsonl"`` implementation.
Its ``async def`` methods perform synchronous filesystem IO (``Path.glob``,
``read_text``, ``open``, ``unlink``) that must be offloaded with
``asyncio.to_thread`` (fixed in #3084). ``put`` runs on every emitted run event,
so any blocking IO here stalls the event loop on the hot path.

#3084 added a mock-based offload assertion in
``tests/test_jsonl_event_store_async_io.py`` that covers ``put`` only. This
anchor complements it by driving the **full** async surface (``put``,
``put_batch``, ``list_messages``, ``list_events``, ``list_messages_by_run``,
``get_last_visible_ai_seq_by_run``, ``count_messages``, ``delete_by_run``,
``delete_by_thread``) under the strict
Blockbuster runtime gate, so any blocking IO reintroduced on the event loop in
any of these methods — not just removal of a specific ``to_thread`` call —
fails CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio


async def test_jsonl_run_event_store_async_api_does_not_block_event_loop(tmp_path: Path) -> None:
    from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

    store = JsonlRunEventStore(base_dir=str(tmp_path))

    # Seed an existing run file so put()'s seq-load globs + reads, and the
    # read/delete paths have files to scan. Test-side IO is invisible to the
    # gate (this module is not in scanned_modules).
    thread_dir = tmp_path / "threads" / "t1" / "runs"
    thread_dir.mkdir(parents=True, exist_ok=True)
    (thread_dir / "r0.jsonl").write_text('{"seq": 1, "category": "message", "run_id": "r0"}\n', encoding="utf-8")

    # writes: put + put_batch
    record = await store.put(thread_id="t1", run_id="r1", event_type="message", category="message", content="hi")
    assert record["seq"] >= 2
    batch = await store.put_batch(
        [
            {"thread_id": "t1", "run_id": "r2", "event_type": "message", "category": "message", "content": "a"},
            {"thread_id": "t1", "run_id": "r2", "event_type": "trace", "category": "trace", "content": "b"},
        ]
    )
    assert len(batch) == 2

    # reads: list_messages / list_events / list_messages_by_run / count_messages.
    # list_events is exercised both without and with the event_types filter so
    # the filter branch runs after _read_run_events' filesystem IO.
    assert isinstance(await store.list_messages("t1"), list)
    assert isinstance(await store.list_events("t1", "r1"), list)
    assert isinstance(await store.list_events("t1", "r1", event_types=["message"]), list)
    assert isinstance(await store.list_messages_by_run("t1", "r2"), list)
    assert isinstance(await store.get_last_visible_ai_seq_by_run("t1", {"r1", "r2"}, user_id="user-1"), dict)
    assert await store.count_messages("t1") >= 1

    # deletes: delete_by_run (single file) then delete_by_thread (remaining)
    assert await store.delete_by_run("t1", "r2") >= 1
    assert await store.delete_by_thread("t1") >= 1
