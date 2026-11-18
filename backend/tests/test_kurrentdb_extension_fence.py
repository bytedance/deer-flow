"""Fence-settled outcomes for ambiguous KurrentDB appends (sync and async)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from kurrentdb_fake import FakeKurrentDB
from kurrentdbclient import NewEvent, StreamState
from kurrentdbclient.exceptions import DeadlineExceededError

pytestmark = pytest.mark.bundled_extension

EXTENSION_ROOT = Path(__file__).resolve().parents[2] / "examples/deerflow-extension-kurrentdb"
TIMEOUT = 3.0


@pytest.fixture(autouse=True)
def _extension_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(EXTENSION_ROOT))


def _event(kind: str = "Happened", **data) -> NewEvent:
    return NewEvent(type=kind, data=json.dumps(data).encode())


def _settle(client, stream, *, expected_version, events):
    from deerflow_extension_kurrentdb._fence import settle_append

    return settle_append(client, stream, expected_version=expected_version, own_event_ids={e.id for e in events}, timeout=TIMEOUT)


def _asettle(client, stream, *, expected_version, events):
    from deerflow_extension_kurrentdb._fence import asettle_append

    return asyncio.run(asettle_append(client, stream, expected_version=expected_version, own_event_ids={e.id for e in events}, timeout=TIMEOUT))


@pytest.fixture(params=["sync", "async"])
def settle(request):
    return _settle if request.param == "sync" else _asettle


def _lose(server, client, stream, events, expected, *, after_commit):
    server.fail_next("append_to_stream", DeadlineExceededError("timeout"), after_commit=after_commit)
    with pytest.raises(DeadlineExceededError):
        client.append_to_stream(stream, events=events, current_version=expected)


def test_lost_ack_after_commit_is_committed(settle):
    server = FakeKurrentDB()
    client = server.sync_client()
    client.append_to_stream("s", events=[_event()], current_version=StreamState.NO_STREAM)
    own = [_event(n=1), _event(n=2)]
    _lose(server, client, "s", own, 0, after_commit=True)
    target = client if settle is _settle else server.async_client()
    assert settle(target, "s", expected_version=0, events=own) == "committed"
    assert [e.type for e in client.get_stream("s")] == ["Happened", "Happened", "Happened"]


def test_lost_ack_before_commit_is_not_committed(settle):
    server = FakeKurrentDB()
    client = server.sync_client()
    own = [_event()]
    _lose(server, client, "s", own, StreamState.NO_STREAM, after_commit=False)
    target = client if settle is _settle else server.async_client()
    assert settle(target, "s", expected_version=StreamState.NO_STREAM, events=own) == "not_committed"
    events = client.get_stream("s")
    assert [e.type for e in events] == ["deerflow.Fence"]
    assert "fence" in json.loads(events[0].data)


def test_late_commit_after_fence_cannot_land(settle):
    server = FakeKurrentDB()
    client = server.sync_client()
    client.append_to_stream("s", events=[_event()], current_version=StreamState.NO_STREAM)
    own = [_event(n="late")]
    pending = server.delay_commit("append_to_stream", DeadlineExceededError("timeout"))
    with pytest.raises(DeadlineExceededError):
        client.append_to_stream("s", events=own, current_version=0)
    target = client if settle is _settle else server.async_client()
    assert settle(target, "s", expected_version=0, events=own) == "not_committed"
    pending.release()
    assert pending.committed is False
    assert own[0].id not in {e.id for e in client.get_stream("s")}


def test_other_writer_at_position_is_not_committed(settle):
    server = FakeKurrentDB()
    client = server.sync_client()
    client.append_to_stream("s", events=[_event()], current_version=StreamState.NO_STREAM)
    own = [_event(n="mine")]
    _lose(server, client, "s", own, 0, after_commit=False)
    client.append_to_stream("s", events=[_event(n="theirs")], current_version=0)
    target = client if settle is _settle else server.async_client()
    assert settle(target, "s", expected_version=0, events=own) == "not_committed"
    assert [e.type for e in client.get_stream("s")] == ["Happened", "Happened"]


def test_other_writer_on_missing_stream_reads_position_zero(settle):
    server = FakeKurrentDB()
    client = server.sync_client()
    own = [_event(n="mine")]
    _lose(server, client, "s", own, StreamState.NO_STREAM, after_commit=False)
    client.append_to_stream("s", events=[_event(n="theirs")], current_version=StreamState.NO_STREAM)
    target = client if settle is _settle else server.async_client()
    assert settle(target, "s", expected_version=StreamState.NO_STREAM, events=own) == "not_committed"


def test_fence_failure_raises_ambiguous(settle):
    from deerflow_extension_kurrentdb._fence import AmbiguousAppendError

    server = FakeKurrentDB()
    client = server.sync_client()
    own = [_event()]
    _lose(server, client, "s", own, StreamState.NO_STREAM, after_commit=True)
    server.fail_next("append_to_stream", DeadlineExceededError("fence timeout"))
    target = client if settle is _settle else server.async_client()
    with pytest.raises(AmbiguousAppendError):
        settle(target, "s", expected_version=StreamState.NO_STREAM, events=own)
    assert len(server.calls_to("append_to_stream", "s")) == 2  # original + one fence, no re-append


def test_every_call_passes_timeout(settle):
    server = FakeKurrentDB()
    client = server.sync_client()
    client.append_to_stream("s", events=[_event()], current_version=StreamState.NO_STREAM)
    own = [_event()]
    _lose(server, client, "s", own, 0, after_commit=True)
    target = client if settle is _settle else server.async_client()
    settle(target, "s", expected_version=0, events=own)
    assert [c.kwargs["timeout"] for c in server.calls[-2:]] == [TIMEOUT, TIMEOUT]


def test_truncated_contested_position_is_ambiguous(settle):
    from deerflow_extension_kurrentdb._fence import AmbiguousAppendError

    server = FakeKurrentDB()
    client = server.sync_client()
    client.append_to_stream("s", events=[_event()], current_version=StreamState.NO_STREAM)
    own = [_event(n="mine")]
    _lose(server, client, "s", own, 0, after_commit=True)
    client.append_to_stream("s", events=[_event(n="later")], current_version=1)
    client.set_stream_metadata("s", metadata={"$tb": 2})  # truncate past the contested position 1
    target = client if settle is _settle else server.async_client()
    with pytest.raises(AmbiguousAppendError, match="truncated"):
        settle(target, "s", expected_version=0, events=own)
