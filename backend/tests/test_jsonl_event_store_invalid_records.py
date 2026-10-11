"""A malformed JSON value must not hide neighboring run events or block writes."""

import json

import pytest

from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

INVALID_RECORDS = {
    "null": None,
    "array": [],
    "string": "record",
    "number": 3,
    "boolean": True,
    "missing-seq": {},
    "null-seq": {"seq": None},
    "string-seq": {"seq": "999"},
    "float-seq": {"seq": 999.5},
    "boolean-seq": {"seq": True},
    "negative-seq": {"seq": -1},
    "array-event-type": {"seq": 999, "event_type": ["ai_message"]},
    "array-metadata": {"seq": 999, "metadata": ["task"]},
    "scalar-metadata": {"seq": 999, "metadata": 1},
}


def _event(seq, event_type="ai_message"):
    return {
        "thread_id": "t1",
        "run_id": "r1",
        "event_type": event_type,
        "category": "message",
        "content": f"message {seq}",
        "metadata": {"task_id": "task"},
        "seq": seq,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def _seed(tmp_path, records):
    path = tmp_path / "threads/t1/runs/r1.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"".join(json.dumps(record).encode("utf-8") + b"\n" for record in records))
    return path


@pytest.mark.anyio
@pytest.mark.parametrize("invalid", INVALID_RECORDS.values(), ids=INVALID_RECORDS)
async def test_reads_skip_invalid_records_without_rewriting_history(tmp_path, invalid):
    first, last = _event(7), _event(41)
    path = _seed(tmp_path, [first, invalid, last])
    original = path.read_bytes()
    store = JsonlRunEventStore(tmp_path)

    assert await store.list_messages("t1") == [first, last]
    assert await store.list_messages("t1", before_seq=41, after_seq=0) == [first]
    assert await store.list_events("t1", "r1") == [first, last]
    assert await store.list_events("t1", "r1", event_types={"ai_message"}) == [first, last]
    assert await store.list_events("t1", "r1", task_id="task", after_seq=7) == [last]
    assert path.read_bytes() == original


@pytest.mark.anyio
@pytest.mark.parametrize("write_method", ["put", "put_batch", "put_if_absent"])
@pytest.mark.parametrize("watermark, next_seq", [(None, 42), (50, 51)])
async def test_reopened_writes_recover_sequence_and_idempotency_past_invalid_records(tmp_path, write_method, watermark, next_seq):
    first, last = _event(7), _event(41)
    path = _seed(tmp_path, [first, *INVALID_RECORDS.values(), last])
    original = path.read_bytes()
    # A deleted run's allocation floor must still take precedence over valid history.
    if watermark is not None:
        (path.parent / ".seq-watermark").write_text(str(watermark), encoding="utf-8")
    store = JsonlRunEventStore(tmp_path)
    event = {"thread_id": "t1", "run_id": "r1", "event_type": "run.end", "category": "lifecycle"}

    if write_method == "put_batch":
        saved = (await store.put_batch([event]))[0]
    elif write_method == "put_if_absent":
        saved, created = await store.put_if_absent(**event)
        assert created
    else:
        saved = await store.put(**event)

    assert saved["seq"] == next_seq
    assert path.read_bytes().startswith(original)
    reopened = JsonlRunEventStore(tmp_path)
    after_write = path.read_bytes()
    existing, created = await reopened.put_if_absent(**event)
    assert not created
    assert existing == saved
    assert path.read_bytes() == after_write
    following = await reopened.put(**{**event, "event_type": "run.following"})
    assert following["seq"] == next_seq + 1
    assert await reopened.list_events("t1", "r1") == [first, last, saved, following]
    assert await reopened.list_messages("t1") == [first, last]


@pytest.mark.anyio
async def test_sparse_legacy_records_keep_optional_fields_and_zero_sequence(tmp_path):
    legacy = {"seq": 0, "category": "message"}
    null_metadata = {"seq": 9, "category": "message", "event_type": None, "metadata": None}
    _seed(tmp_path, [legacy, null_metadata])
    store = JsonlRunEventStore(tmp_path)

    assert await store.list_messages("t1", after_seq=-1) == [legacy, null_metadata]
    assert await store.list_events("t1", "r1", task_id="task") == []
    saved = await store.put(thread_id="t1", run_id="r1", event_type="run.end", category="lifecycle")
    assert saved["seq"] == 10
