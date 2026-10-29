"""The in-memory event backend must behave like durable snapshot storage."""

import pytest

from deerflow.runtime.events.store.memory import MemoryRunEventStore


@pytest.mark.asyncio
@pytest.mark.parametrize("writer", ["put", "put_batch", "put_if_absent"])
async def test_persisted_events_do_not_alias_writer_inputs_or_receipts(writer):
    store = MemoryRunEventStore()
    payload = {"parts": [{"text": "original"}]}
    metadata = {"audit": {"labels": ["original"]}}
    event = {
        "thread_id": "thread",
        "run_id": "run",
        "event_type": "llm.ai.response",
        "category": "message",
        "content": payload,
        "metadata": metadata,
    }

    if writer == "put":
        receipt = await store.put(**event)
    elif writer == "put_batch":
        receipt = (await store.put_batch([event]))[0]
    else:
        receipt, created = await store.put_if_absent(**event)
        assert created

    payload["parts"][0]["text"] = "changed by writer"
    metadata["audit"]["labels"].append("changed by writer")
    receipt["content"]["parts"][0]["text"] = "changed by receipt"
    receipt["metadata"]["audit"]["labels"].append("changed by receipt")

    stored = (await store.list_events("thread", "run"))[0]
    assert stored["content"] == {"parts": [{"text": "original"}]}
    assert stored["metadata"] == {"audit": {"labels": ["original"]}}


@pytest.mark.parametrize(
    ("reader", "cursor"),
    [
        pytest.param("list_events", {}, id="list-events-latest"),
        pytest.param("list_events", {"after_seq": 1, "limit": 1}, id="list-events-after-seq"),
        pytest.param("list_messages", {}, id="list-messages-latest"),
        pytest.param("list_messages", {"before_seq": 3, "limit": 1}, id="list-messages-before-seq"),
        pytest.param("list_messages", {"after_seq": 1, "limit": 1}, id="list-messages-after-seq"),
        pytest.param("list_messages_by_run", {}, id="list-messages-by-run-latest"),
        pytest.param("list_messages_by_run", {"before_seq": 3, "limit": 1}, id="list-messages-by-run-before-seq"),
        pytest.param("list_messages_by_run", {"after_seq": 1, "limit": 1}, id="list-messages-by-run-after-seq"),
    ],
)
@pytest.mark.asyncio
async def test_reader_results_are_detached_snapshots(reader, cursor):
    store = MemoryRunEventStore()
    for seq in range(1, 4):
        await store.put(
            thread_id="thread",
            run_id="run",
            event_type="llm.ai.response",
            category="message",
            content={"parts": [f"saved-{seq}"]},
            metadata={"audit": {"tags": [f"saved-{seq}"]}},
        )

    if reader == "list_events":
        results = await store.list_events("thread", "run", **cursor)
    elif reader == "list_messages":
        results = await store.list_messages("thread", **cursor)
    else:
        results = await store.list_messages_by_run("thread", "run", **cursor)

    assert results
    results[0]["content"]["parts"].append("changed by reader")
    results[0]["metadata"]["audit"]["tags"].append("changed by reader")
    results[0]["seq"] = -1

    stored = await store.list_events("thread", "run")
    assert [event["seq"] for event in stored] == [1, 2, 3]
    for event in stored:
        seq = event["seq"]
        assert event["content"] == {"parts": [f"saved-{seq}"]}
        assert event["metadata"] == {"audit": {"tags": [f"saved-{seq}"]}}

    assert [event["seq"] for event in await store.list_messages("thread")] == [1, 2, 3]
    assert [event["seq"] for event in await store.list_messages_by_run("thread", "run")] == [1, 2, 3]


@pytest.mark.asyncio
async def test_put_if_absent_existing_receipt_is_not_the_stored_event():
    store = MemoryRunEventStore()
    await store.put(
        thread_id="thread",
        run_id="run",
        event_type="run.end",
        category="lifecycle",
        content={"status": "success"},
        metadata={"audit": {"source": "worker"}},
    )
    existing, created = await store.put_if_absent(thread_id="thread", run_id="run", event_type="run.end", category="lifecycle")
    assert not created
    existing["metadata"]["audit"]["source"] = "modified"
    existing["content"]["status"] = "error"

    saved = (await store.list_events("thread", "run"))[0]
    assert saved["content"] == {"status": "success"}
    assert saved["metadata"] == {"audit": {"source": "worker"}}
