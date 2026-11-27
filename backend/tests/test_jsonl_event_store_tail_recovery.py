"""Appending after an incomplete JSONL tail must not swallow later events."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from deerflow.runtime.events.store.base import RunEventStoreNotCommittedError
from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

TAILS = {
    "lf": b"\n",
    "crlf": b"\r\n",
    "no-newline": b"",
    "partial-json": b'\n{"seq": 999, "content": "unfinished',
    "partial-utf8": b'\n{"seq": 999, "content": "\xe4\xb8',
}


def _seed(tmp_path, tail):
    path = tmp_path / "threads/t1/runs/r1.jsonl"
    path.parent.mkdir(parents=True)
    record = {
        "thread_id": "t1",
        "run_id": "r1",
        "event_type": "llm.ai.response",
        "category": "message",
        "content": {"type": "ai", "id": "old-message", "content": "你好\u2028world"},
        "metadata": {},
        "seq": 41,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    path.write_bytes(json.dumps(record, ensure_ascii=False).encode("utf-8") + tail)
    return path, record


def _event(run_id="r1", event_type="run.end"):
    return {"thread_id": "t1", "run_id": run_id, "event_type": event_type, "category": "message", "content": "next message"}


@pytest.mark.anyio
@pytest.mark.parametrize("tail", TAILS.values(), ids=TAILS)
@pytest.mark.parametrize("write_method", ["put", "put_batch", "put_if_absent"])
async def test_append_after_incomplete_tail_preserves_history_and_sequence(tmp_path, tail, write_method):
    path, old = _seed(tmp_path, tail)
    original_bytes = path.read_bytes()
    store = JsonlRunEventStore(tmp_path)

    if write_method == "put_batch":
        saved = (await store.put_batch([_event()]))[0]
    elif write_method == "put_if_absent":
        saved, created = await store.put_if_absent(**_event())
        assert created
        after_write = path.read_bytes()
        existing, created_again = await store.put_if_absent(**_event())
        assert not created_again
        assert existing == saved
        assert path.read_bytes() == after_write
    else:
        saved = await store.put(**_event())

    assert saved["seq"] == 42
    assert path.read_bytes().startswith(original_bytes), "recovery must not rewrite or discard existing bytes"
    # The new record needs its own physical line, even after an invalid tail.
    assert json.loads(path.read_bytes().split(b"\n")[-2]) == saved
    assert await store.list_events("t1", "r1") == [old, saved]
    assert await store.list_messages("t1") == [old, saved]
    assert await store.get_message_seqs("t1", ["message:old-message"]) == {"message:old-message": 41}

    restarted = JsonlRunEventStore(tmp_path)
    following = await restarted.put(**_event(event_type="run.following"))
    assert following["seq"] == 43
    assert await restarted.list_events("t1", "r1") == [old, saved, following]


@pytest.mark.anyio
@pytest.mark.parametrize("tail", [TAILS["no-newline"], TAILS["partial-json"], TAILS["partial-utf8"]], ids=["no-newline", "partial-json", "partial-utf8"])
async def test_batch_failure_restores_original_tail_bytes_before_retry(tmp_path, monkeypatch, tail):
    path, old = _seed(tmp_path, tail)
    original_bytes = path.read_bytes()
    new_path = path.with_name("r2.jsonl")
    store = JsonlRunEventStore(tmp_path)
    append = store._append_records

    def fail_second_group(path, records):
        append(path, records)
        if path == new_path:
            raise OSError("second group failed after writing")

    monkeypatch.setattr(store, "_append_records", fail_second_group)
    with pytest.raises(RunEventStoreNotCommittedError, match="second group failed"):
        await store.put_batch([_event(), _event("r2")])

    assert path.read_bytes() == original_bytes
    assert not new_path.exists()
    assert await store.list_messages("t1") == [old]

    monkeypatch.setattr(store, "_append_records", append)
    saved = await store.put_batch([_event(), _event("r2")])
    assert await store.list_messages("t1") == [old, *saved]
    assert saved[0]["seq"] > old["seq"]
    assert saved[1]["seq"] == saved[0]["seq"] + 1


@pytest.mark.anyio
@pytest.mark.parametrize("existing_file", [True, False], ids=["stat-before-append", "stat-during-rollback"])
async def test_batch_stat_failure_preserves_original_file(tmp_path, monkeypatch, existing_file):
    store = JsonlRunEventStore(tmp_path)
    path = store._run_file("t1", "r1")
    if existing_file:
        await store.put(**_event())
    original = path.read_bytes() if existing_file else None
    fail_stat = existing_file
    stat = os.stat
    append = store._append_records

    def unavailable_stat(target, *args, **kwargs):
        if fail_stat and target == path:
            raise OSError("cannot stat the run file")
        return stat(target, *args, **kwargs)

    def fail_after_append(path, records):
        nonlocal fail_stat
        append(path, records)
        fail_stat = True
        raise OSError("append failed")

    with monkeypatch.context() as patch:
        patch.setattr(os, "stat", unavailable_stat)
        # Match Python 3.14, where Path.exists() returns False for any OS error.
        patch.setattr(Path, "exists", os.path.exists)
        patch.setattr(store, "_append_records", fail_after_append)
        with pytest.raises(RunEventStoreNotCommittedError, match="cannot stat" if existing_file else "append failed"):
            await store.put_batch([_event()])

    assert (path.read_bytes() if path.exists() else None) == original


@pytest.mark.anyio
async def test_batch_rollback_restores_run_file_shared_by_two_groups(tmp_path, monkeypatch):
    path, old = _seed(tmp_path, TAILS["lf"])
    original = path.read_bytes()
    store = JsonlRunEventStore(tmp_path)
    run_file = store._run_file
    append = store._append_records

    # Both spellings address the same file on a case-insensitive filesystem.
    monkeypatch.setattr(store, "_run_file", lambda thread_id, run_id: run_file(thread_id, run_id.lower()))

    def fail_second_group(path, records):
        append(path, records)
        if records[0]["run_id"] == "R1":
            raise OSError("second append failed")

    events = [_event("r1"), _event("R1")]
    with monkeypatch.context() as patch:
        patch.setattr(store, "_append_records", fail_second_group)
        with pytest.raises(RunEventStoreNotCommittedError, match="second append failed"):
            await store.put_batch(events)

    assert path.read_bytes() == original
    saved = await store.put_batch(events)
    assert await store.list_messages("t1") == [old, *saved]
