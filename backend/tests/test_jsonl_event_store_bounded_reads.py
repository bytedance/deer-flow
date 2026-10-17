"""Small JSONL queries must not retain unrelated historical event payloads."""

from __future__ import annotations

import json
import tracemalloc
from pathlib import Path

import pytest

from deerflow.runtime.events.store.jsonl import JsonlRunEventStore


def _record(seq: int, *, run_id: str = "run-a", category: str = "message", message_id: str | None = None, **extra) -> dict:
    return {
        "thread_id": "chat",
        "run_id": run_id,
        "seq": seq,
        "event_type": "llm.ai.response" if category == "message" else "tool.end",
        "category": category,
        "content": {"type": "ai", "id": message_id or f"message-{seq}", "content": f"answer {seq}"},
        "metadata": {},
        **extra,
    }


def _write_run(root: Path, run_id: str, records: list[dict]) -> None:
    path = root / "threads" / "chat" / "runs" / f"{run_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


@pytest.fixture
def long_log(tmp_path):
    path = tmp_path / "threads" / "chat" / "runs" / "run-a.jsonl"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for seq in range(1, 1025):
            stream.write(json.dumps(_record(seq, category="trace", content="x" * 16384)) + "\n")
        for seq in range(1025, 1030):
            stream.write(json.dumps(_record(seq)) + "\n")
    assert path.stat().st_size > 16 * 1024 * 1024
    return JsonlRunEventStore(tmp_path)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "operation",
    [
        "messages",
        "run_messages",
        "events",
        "filtered_events",
        "count",
        "identities",
        "latest_ai",
        "last_visible_ai",
        "idempotent_receipt",
        "delete_run",
        "delete_thread",
    ],
)
async def test_small_queries_have_bounded_peak_allocation(long_log, operation):
    store = long_log
    tracemalloc.start()
    try:
        if operation == "messages":
            assert [r["seq"] for r in await store.list_messages("chat", limit=2)] == [1028, 1029]
        elif operation == "run_messages":
            assert [r["seq"] for r in await store.list_messages_by_run("chat", "run-a", limit=2)] == [1028, 1029]
        elif operation == "events":
            assert [r["seq"] for r in await store.list_events("chat", "run-a", limit=2)] == [1, 2]
        elif operation == "filtered_events":
            assert [r["seq"] for r in await store.list_events("chat", "run-a", event_types=["llm.ai.response"], limit=2)] == [1025, 1026]
        elif operation == "count":
            assert await store.count_messages("chat") == 5
        elif operation == "identities":
            assert await store.get_message_seqs("chat", ["message:message-1029", "message:missing"]) == {"message:message-1029": 1029}
        elif operation == "latest_ai":
            assert await store.find_latest_ai_message_run_ids("chat", {"message-1029", "missing"}) == {"message-1029": "run-a"}
        elif operation == "last_visible_ai":
            assert await store.get_last_visible_ai_seq_by_run("chat", {"run-a", "missing"}) == {"run-a": 1029}
        elif operation == "idempotent_receipt":
            record, created = await store.put_if_absent(thread_id="chat", run_id="run-a", event_type="llm.ai.response", category="message")
            assert not created
            assert record["seq"] == 1025
        elif operation == "delete_run":
            assert await store.delete_by_run("chat", "run-a") == 1029
            assert await store.count_messages("chat") == 0
            assert (await store.put(thread_id="chat", run_id="run-b", event_type="message", category="message"))["seq"] == 1030
        elif operation == "delete_thread":
            assert await store.delete_by_thread("chat") == 1029
            assert await store.count_messages("chat") == 0
            assert (await store.put(thread_id="chat", run_id="run-b", event_type="message", category="message"))["seq"] == 1
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    # Generous headroom for one physical record, executor bookkeeping and two
    # retained results. This is a space bound, not a wall-clock speed assertion.
    assert peak < 2 * 1024 * 1024, f"{operation} retained {peak:,} bytes for a small result"


@pytest.fixture
def unordered_logs(tmp_path):
    # Filename order and physical line order both disagree with seq order;
    # duplicate seqs pin the stable tie-break without comparing dictionaries.
    a = [_record(8), _record(3), _record(5, message_id="a-first"), _record(5, message_id="a-last"), _record(1, category="trace")]
    b = [_record(7, run_id="run-b"), _record(2, run_id="run-b"), _record(5, run_id="run-b", message_id="b-tie")]
    _write_run(tmp_path, "run-a", a)
    _write_run(tmp_path, "run-b", b)
    return JsonlRunEventStore(tmp_path), a, b


@pytest.mark.anyio
@pytest.mark.parametrize("limit", [1, 3, 50, 0, -2])
@pytest.mark.parametrize("before,after", [(None, None), (7, None), (None, 3), (8, 2), (3, 7), (5, 5)])
async def test_pages_match_stable_sort_and_slice_on_unordered_logs(unordered_logs, limit, before, after):
    store, a, b = unordered_logs

    def reference(records):
        matching = [r for r in sorted(records, key=lambda r: r["seq"]) if r["category"] == "message"]
        if before is not None:
            matching = [r for r in matching if r["seq"] < before]
        if after is not None:
            matching = [r for r in matching if r["seq"] > after]
        return matching[:limit] if after is not None else matching[-limit:]

    assert await store.list_messages("chat", limit=limit, before_seq=before, after_seq=after) == reference(a + b)
    assert await store.list_messages_by_run("chat", "run-a", limit=limit, before_seq=before, after_seq=after) == reference(a)


@pytest.mark.anyio
@pytest.mark.parametrize("limit", [1, 2, 10, 0, -1])
@pytest.mark.parametrize("event_types", [None, [], ["llm.ai.response"], ["tool.end", "llm.ai.response"]])
async def test_event_filters_precede_selection(tmp_path, limit, event_types):
    records = [
        _record(9, metadata={"task_id": "target"}),
        _record(1, category="trace", metadata={"task_id": "other"}),
        _record(4, metadata={"task_id": "target"}),
        _record(4, message_id="equal", metadata={"task_id": "target"}),
        _record(3, category="trace", metadata={"task_id": "target"}),
    ]
    _write_run(tmp_path, "run-a", records)
    store = JsonlRunEventStore(tmp_path)
    matching = [r for r in sorted(records, key=lambda r: r["seq"]) if (event_types is None or r["event_type"] in event_types) and r["metadata"]["task_id"] == "target" and r["seq"] > 2]
    assert await store.list_events("chat", "run-a", event_types=event_types, task_id="target", after_seq=2, limit=limit) == matching[:limit]


@pytest.mark.anyio
async def test_scalar_lookups_scan_every_file_and_keep_only_valid_candidates(tmp_path):
    a = [
        _record(20, message_id="target"),
        _record(8, message_id="duplicate"),
        _record(40, message_id="target", run_id=""),  # invalid newest match
        _record(50, category="trace", message_id="target"),
        _record(60, metadata={"caller": "middleware:summary"}),
    ]
    b = [
        _record(30, run_id="run-b", message_id="target"),
        _record(2, run_id="run-b", message_id="duplicate"),
        _record(30, run_id="tie-winner", message_id="target"),
        _record(70, run_id="run-b", content={"type": "human", "id": "target"}),
        _record(1, run_id="run-b", category="trace"),
    ]
    _write_run(tmp_path, "run-a", a)
    _write_run(tmp_path, "run-b", b)
    store = JsonlRunEventStore(tmp_path)
    assert await store.find_latest_ai_message_run_ids("chat", {"target", "duplicate", "missing"}) == {"target": "tie-winner", "duplicate": "run-a"}
    assert await store.get_message_seqs("chat", ["message:target", "message:duplicate", "message:missing"]) == {"message:target": 20, "message:duplicate": 2}
    assert await store.get_last_visible_ai_seq_by_run("chat", {"run-a", "run-b", "missing"}) == {"run-a": 40, "run-b": 70}
    assert await store.count_messages("chat") == 8
    existing, created = await store.put_if_absent(thread_id="chat", run_id="run-a", event_type="llm.ai.response", category="message")
    assert not created and existing["seq"] == 8


@pytest.mark.anyio
async def test_mid_scan_cancellation_keeps_snapshot_fenced(tmp_path, monkeypatch):
    import asyncio
    import threading

    _write_run(tmp_path, "run-a", [_record(1, message_id="target"), _record(2)])
    store = JsonlRunEventStore(tmp_path)
    original = store._iter_records
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()

    def paused(path):
        for index, record in enumerate(original(path)):
            yield record
            if index == 0:
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(5):
                    raise TimeoutError("test did not release snapshot scan")

    monkeypatch.setattr(store, "_iter_records", paused)
    lookup = asyncio.create_task(store.find_latest_ai_message_run_ids("chat", {"target"}))
    writer = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        lookup.cancel("first")
        await asyncio.sleep(0)
        lookup.cancel("second")
        writer = asyncio.create_task(store.put(thread_id="chat", run_id="run-b", event_type="message", category="message"))
        for _ in range(5):
            await asyncio.sleep(0)
        assert not lookup.done()
        assert not writer.done()
        assert not store._run_file("chat", "run-b").exists()
        release.set()
        with pytest.raises(asyncio.CancelledError, match="first"):
            await lookup
        assert (await writer)["seq"] == 3
    finally:
        release.set()
        await asyncio.gather(lookup, *([writer] if writer else []), return_exceptions=True)


@pytest.mark.anyio
async def test_error_after_a_match_does_not_return_partial_lookup(tmp_path, monkeypatch):
    _write_run(tmp_path, "run-a", [_record(1, message_id="target")])
    store = JsonlRunEventStore(tmp_path)
    original = store._iter_records

    def fail_after_record(path):
        yield from original(path)
        raise OSError("disk read failed after matching target")

    monkeypatch.setattr(store, "_iter_records", fail_after_record)
    with pytest.raises(OSError, match="disk read failed"):
        await store.find_latest_ai_message_run_ids("chat", {"target"})
    assert not store._write_locks


@pytest.mark.anyio
@pytest.mark.parametrize("scope", ["thread", "run"])
async def test_latest_page_does_not_retain_older_matching_payloads(tmp_path, scope):
    path = tmp_path / "threads" / "chat" / "runs" / "run-a.jsonl"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for seq in range(1, 1025):
            stream.write(json.dumps(_record(seq, content={"type": "ai", "id": f"m{seq}", "content": "x" * 16384})) + "\n")
    store = JsonlRunEventStore(tmp_path)
    tracemalloc.start()
    try:
        page = await (store.list_messages("chat", limit=2) if scope == "thread" else store.list_messages_by_run("chat", "run-a", limit=2))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert [r["seq"] for r in page] == [1023, 1024]
    assert peak < 2 * 1024 * 1024
