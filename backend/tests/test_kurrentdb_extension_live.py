"""The KurrentDB extension against a real KurrentDB server (opt-in, never in CI).

Run with a server up, for instance::

    docker run -d --rm --name kurrentdb-live-test -p 127.0.0.1:2113:2113 \\
        docker.kurrent.io/kurrent-latest/kurrentdb:latest \\
        --insecure --run-projections=All --start-standard-projections
    KURRENTDB_LIVE_CONNECTION_STRING='kurrentdb://127.0.0.1:2113?tls=false' \\
        uv run --frozen pytest tests/test_kurrentdb_extension_live.py -q

The brief's image is amd64-only and segfaults under qemu on arm64 hosts (also with
``DOTNET_EnableWriteXorExecute=0``); there the suite was run on the arm64 build
``kurrentplatform/kurrentdb:26.2.0-experimental-arm64-10.0-noble`` with the same
flags. Rerun on amd64 with the image above when one is at hand.

Two parts:

- ``test_server_*``: the stream semantics the in-memory fake (``kurrentdb_fake``)
  models, each run against the server **and** the fake, so a divergence fails here.
  The ``test_server_assumes_*`` ones mirror ``test_fake_assumes_*`` in
  ``test_kurrentdb_extension_basics.py``
- ``test_live_*``: extension round trips (memory, run events, ``$tb``, canonical
  emission and cleanup, conditional soft delete) on the server

Every test uses fresh stream names (uuids), including its own deletions index
stream, so reruns against the same server never collide.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from kurrent_agent_schema import EVENT_TYPE_BY_NAME, EVENT_TYPE_NAMES, agent_memory_stream, agent_session_stream, from_json
from kurrentdb_fake import FakeKurrentDB
from kurrentdbclient import AsyncKurrentDBClient, KurrentDBClient, NewEvent, StreamState
from kurrentdbclient.exceptions import NotFoundError, StreamIsDeletedError, WrongCurrentVersionError

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig

CONNECTION_STRING = os.environ.get("KURRENTDB_LIVE_CONNECTION_STRING", "").strip()

pytestmark = [
    pytest.mark.bundled_extension,
    pytest.mark.live,
    pytest.mark.skipif(not CONNECTION_STRING, reason="set KURRENTDB_LIVE_CONNECTION_STRING to run the live KurrentDB suite"),
]

EXTENSION_ROOT = Path(__file__).resolve().parents[2] / "examples/deerflow-extension-kurrentdb"
TIMEOUT = 10.0
AGENT = "__default__"
MAX_TB = 2**63 - 1


def _unique(prefix: str = "live") -> str:
    """A fresh name with no dash, so it is usable as a stream name, user id or thread id."""
    return f"{prefix}{uuid.uuid4().hex}"


@pytest.fixture(autouse=True)
def _extension_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(EXTENSION_ROOT))
    monkeypatch.setenv("KURRENTDB_CONNECTION_STRING", CONNECTION_STRING or "kurrentdb://unset:2113?tls=false")
    monkeypatch.setenv("KURRENTDB_TIMEOUT_SECONDS", str(TIMEOUT))
    monkeypatch.setenv("KURRENTDB_CANONICAL_EVENTS", "on")


@pytest.fixture(autouse=True)
def _own_deletions_index(monkeypatch):
    """Each test gets its own deletions index, so intents of earlier runs are never in play."""
    from deerflow_extension_kurrentdb import deletions

    monkeypatch.setattr(deletions, "DELETIONS_STREAM", f"deerflow.kurrent-deletions.{_unique()}")
    return deletions


def _event(kind: str = "Happened", **data) -> NewEvent:
    return NewEvent(type=kind, data=json.dumps(data).encode())


def _n(events) -> list:
    return [json.loads(event.data)["n"] for event in events]


def _positions(events) -> list[int]:
    return [event.stream_position for event in events]


#: How long a read may lag a stream's recreation (observed: under 10 ms).
SETTLE_SECONDS = 2.0


def _settled(read: Callable[[], Any], until: Callable[[Any], bool] = lambda _value: True) -> Any:
    """``read()`` once it stops raising ``NotFoundError`` and ``until`` holds, within ``SETTLE_SECONDS``.

    Appending to a soft-deleted stream commits the events, then lowers ``$tb`` in a
    separate metadata write, so for a few milliseconds reads may still report the
    stream as deleted (``NotFoundError``, ``get_current_version`` -> ``NO_STREAM``);
    the fake models it only on request (``lag_recreations``). Appends always check the
    real head.
    """
    deadline = time.monotonic() + SETTLE_SECONDS
    while True:
        try:
            value = read()
        except NotFoundError:
            if time.monotonic() > deadline:
                raise
        else:
            if until(value) or time.monotonic() > deadline:
                return value
        time.sleep(0.01)


# --- server semantics: the same checks on the server and on the fake -------------------


@dataclass
class Backend:
    name: str
    client: Any
    async_client: Callable[[], Any]

    def run(self, scenario: Callable[[Any], Awaitable[Any]]) -> Any:
        """Run ``scenario(async_client)`` on a fresh, connected async client."""

        async def main():
            client = self.async_client()
            await client.connect()
            try:
                return await scenario(client)
            finally:
                await client.close()

        return asyncio.run(main())


@pytest.fixture(params=["server", "fake"])
def backend(request):
    if request.param == "fake":
        fake = FakeKurrentDB()
        yield Backend("fake", fake.sync_client(), fake.async_client)
        return
    client = KurrentDBClient(CONNECTION_STRING)
    try:
        yield Backend("server", client, lambda: AsyncKurrentDBClient(CONNECTION_STRING))
    finally:
        client.close()


def test_server_expected_version_conflicts(backend):
    client, s = backend.client, _unique("s")
    with pytest.raises(NotFoundError):
        client.get_stream(s)
    assert client.get_current_version(s) is StreamState.NO_STREAM
    assert client.get_stream_metadata(s) == ({}, StreamState.NO_STREAM)
    for expected in (0, StreamState.EXISTS):
        with pytest.raises(WrongCurrentVersionError) as missing:
            client.append_to_stream(s, events=[_event()], current_version=expected)
        assert (missing.value.stream_name, missing.value.actual_version, missing.value.expected_version) == (s, StreamState.NO_STREAM, expected)

    client.append_to_stream(s, events=[_event(n=0), _event(n=1)], current_version=StreamState.NO_STREAM)
    with pytest.raises(WrongCurrentVersionError) as exists:
        client.append_to_stream(s, events=[_event()], current_version=StreamState.NO_STREAM)
    assert (exists.value.actual_version, exists.value.expected_version) == (1, StreamState.NO_STREAM)
    with pytest.raises(WrongCurrentVersionError) as stale:
        client.append_to_stream(s, events=[_event(), _event()], current_version=0)
    assert (stale.value.stream_name, stale.value.actual_version, stale.value.expected_version) == (s, 1, 0)
    first = client.append_to_stream(s, events=[_event(n=2)], current_version=1)
    second = client.append_to_stream(s, events=[_event(n=3)], current_version=StreamState.ANY)
    third = client.append_to_stream(s, events=[_event(n=4)], current_version=StreamState.EXISTS)
    assert first < second < third
    assert _n(client.get_stream(s)) == [0, 1, 2, 3, 4]  # the rejected two-event batch left nothing
    assert _positions(client.get_stream(s, stream_position=3)) == [3, 4]
    assert _positions(client.get_stream(s, backwards=True, limit=2)) == [4, 3]
    assert _positions(client.get_stream(s, stream_position=2, backwards=True)) == [2, 1, 0]
    assert client.get_current_version(s) == 4


def test_server_same_id_append_is_idempotent(backend):
    client, s = backend.client, _unique("s")
    a, b, c = _event(n="a"), _event(n="b"), _event(n="c")
    client.append_to_stream(s, events=[a, b], current_version=StreamState.NO_STREAM)
    # A retry at its own expected version, or with ANY / EXISTS, writes nothing.
    for expected in (StreamState.NO_STREAM, StreamState.ANY, StreamState.EXISTS):
        client.append_to_stream(s, events=[a, b], current_version=expected)
    client.append_to_stream(s, events=[b], current_version=0)
    client.append_to_stream(s, events=[a], current_version=StreamState.NO_STREAM)
    assert client.get_current_version(s) == 1
    # A different event at the retried position is a conflict (what the fence relies on).
    with pytest.raises(WrongCurrentVersionError):
        client.append_to_stream(s, events=[c], current_version=StreamState.NO_STREAM)
    with pytest.raises(WrongCurrentVersionError):
        client.append_to_stream(s, events=[a], current_version=0)
    # At the head the same ids are new events.
    client.append_to_stream(s, events=[c], current_version=1)
    client.append_to_stream(s, events=[a], current_version=2)
    assert _n(client.get_stream(s)) == ["a", "b", "c", "a"]


def test_server_assumes_partial_retry_is_a_conflict(backend):
    client, s = backend.client, _unique("s")
    a, b = _event(n="a"), _event(n="b")
    client.append_to_stream(s, events=[a, b], current_version=StreamState.NO_STREAM)
    for expected in (StreamState.ANY, StreamState.EXISTS, StreamState.NO_STREAM):
        with pytest.raises(WrongCurrentVersionError) as partial:
            client.append_to_stream(s, events=[a, _event(n="new")], current_version=expected)
        assert partial.value.actual_version == 1
    client.append_to_stream(s, events=[a], current_version=StreamState.ANY)  # an old id anywhere: a retry
    assert client.get_current_version(s) == 1
    client.append_to_stream(s, events=[_event(n="x"), a], current_version=StreamState.ANY)  # only the first id counts
    assert _n(client.get_stream(s)) == ["a", "b", "x", "a"]


def test_server_truncate_before_hides_and_lowering_shows(backend):
    client, s = backend.client, _unique("s")
    client.append_to_stream(s, events=[_event(n=i) for i in range(5)], current_version=StreamState.NO_STREAM)
    with pytest.raises(WrongCurrentVersionError) as conflict:
        client.set_stream_metadata(s, metadata={"$tb": 2}, current_version=0)
    assert (conflict.value.stream_name, conflict.value.actual_version, conflict.value.expected_version) == (f"$${s}", StreamState.NO_STREAM, 0)
    client.set_stream_metadata(s, metadata={"$tb": 2}, current_version=StreamState.NO_STREAM)
    assert client.get_stream_metadata(s) == ({"$tb": 2}, 0)
    with pytest.raises(WrongCurrentVersionError):
        client.set_stream_metadata(s, metadata={"$tb": 3}, current_version=StreamState.NO_STREAM)

    # $tb hides lower positions from every read; positions and the head are unchanged.
    assert _positions(client.get_stream(s)) == [2, 3, 4]
    assert _positions(client.get_stream(s, stream_position=0)) == [2, 3, 4]
    assert _positions(client.get_stream(s, backwards=True)) == [4, 3, 2]
    assert client.get_stream(s, stream_position=1, backwards=True) == ()
    assert _positions(client.read_stream(s, stream_position=0, limit=2)) == [2, 3]
    assert client.get_current_version(s) == 4
    client.append_to_stream(s, events=[_event(n=5)], current_version=4)
    # Metadata writes replace the whole document; lowering $tb shows the events again.
    client.set_stream_metadata(s, metadata={"$tb": 4, "x": "y"}, current_version=0)
    assert client.get_stream_metadata(s) == ({"$tb": 4, "x": "y"}, 1)
    assert _positions(client.get_stream(s)) == [4, 5]
    client.set_stream_metadata(s, metadata={"x": "y"}, current_version=1)
    assert _positions(client.get_stream(s)) == [0, 1, 2, 3, 4, 5]
    # $tb at the maximum reads like a deleted stream.
    client.set_stream_metadata(s, metadata={"$tb": MAX_TB}, current_version=2)
    with pytest.raises(NotFoundError):
        client.get_stream(s)
    assert client.get_current_version(s) is StreamState.NO_STREAM


def test_server_assumes_tb_past_the_last_event_breaks_get_current_version(backend):
    client, s = backend.client, _unique("s")
    client.append_to_stream(s, events=[_event(n=0), _event(n=1)], current_version=StreamState.NO_STREAM)
    client.set_stream_metadata(s, metadata={"$tb": 2})
    assert client.get_stream(s) == () and client.get_stream(s, backwards=True, limit=1) == ()
    assert list(client.read_stream(s, backwards=True)) == []
    # kurrentdbclient reads one event backwards and indexes it without a guard.
    with pytest.raises(StopIteration):
        client.get_current_version(s)

    async def head(async_client):
        return await async_client.get_current_version(s)

    with pytest.raises(IndexError):
        backend.run(head)
    # Appends still check against the real head.
    with pytest.raises(WrongCurrentVersionError) as conflict:
        client.append_to_stream(s, events=[_event(n=9)], current_version=StreamState.NO_STREAM)
    assert conflict.value.actual_version == 1
    client.append_to_stream(s, events=[_event(n=2)], current_version=1)
    assert _n(client.get_stream(s)) == [2]
    assert client.get_current_version(s) == 2


@pytest.mark.parametrize("expected", [StreamState.NO_STREAM, 1, StreamState.ANY], ids=["no_stream", "pre_delete_head", "any"])
def test_server_assumes_soft_deleted_stream_accepts_previous_head_or_any(backend, expected):
    client, s = backend.client, _unique("s")
    client.append_to_stream(s, events=[_event(n=0), _event(n=1)], current_version=StreamState.NO_STREAM)
    with pytest.raises(WrongCurrentVersionError) as stale_delete:
        client.delete_stream(s, current_version=0)
    assert (stale_delete.value.stream_name, stale_delete.value.actual_version, stale_delete.value.expected_version) == (s, 1, 0)
    client.delete_stream(s, current_version=1)
    with pytest.raises(NotFoundError):
        client.get_stream(s)
    assert client.get_current_version(s) is StreamState.NO_STREAM
    with pytest.raises(StreamIsDeletedError):
        client.append_to_stream(s, events=[_event()], current_version=StreamState.EXISTS)
    with pytest.raises(WrongCurrentVersionError) as wrong:
        client.append_to_stream(s, events=[_event()], current_version=5)
    assert (wrong.value.actual_version, wrong.value.expected_version) == (1, 5)  # the pre-delete head, not NO_STREAM

    client.append_to_stream(s, events=[_event(n=2)], current_version=expected)
    assert [(event.stream_position, json.loads(event.data)["n"]) for event in _settled(lambda: client.get_stream(s))] == [(2, 2)]
    assert client.get_current_version(s) == 2
    assert client.get_stream_metadata(s) == ({"$tb": 2}, 1)


def test_server_assumes_soft_delete_writes_max_tb_and_drops_metadata(backend):
    client, s = backend.client, _unique("s")
    client.append_to_stream(s, events=[_event()], current_version=StreamState.NO_STREAM)
    client.set_stream_metadata(s, metadata={"k": "v", "$tb": 0})
    client.delete_stream(s, current_version=0)
    assert client.get_stream_metadata(s) == ({"$tb": MAX_TB}, 1)
    client.append_to_stream(s, events=[_event()], current_version=StreamState.NO_STREAM)
    assert _settled(lambda: client.get_stream_metadata(s), lambda metadata: metadata[1] == 2) == ({"$tb": 1}, 2)


def test_server_assumes_delete_of_missing_stream_raises_not_found(backend):
    client, s = backend.client, _unique("s")
    for expected in (StreamState.ANY, StreamState.NO_STREAM, StreamState.EXISTS, 0):
        with pytest.raises(NotFoundError):
            client.delete_stream(s, current_version=expected)
    assert client.get_stream_metadata(s) == ({}, StreamState.NO_STREAM)


def test_server_assumes_delete_of_soft_deleted_stream_succeeds_again(backend):
    client, s = backend.client, _unique("s")
    client.append_to_stream(s, events=[_event(), _event()], current_version=StreamState.NO_STREAM)
    with pytest.raises(WrongCurrentVersionError) as live:
        client.delete_stream(s, current_version=StreamState.NO_STREAM)
    assert live.value.actual_version == 1
    client.delete_stream(s, current_version=1)
    for expected in (StreamState.ANY, StreamState.NO_STREAM, 1):
        client.delete_stream(s, current_version=expected)
    assert client.get_stream_metadata(s) == ({"$tb": MAX_TB}, 3)
    with pytest.raises(StreamIsDeletedError):
        client.delete_stream(s, current_version=StreamState.EXISTS)
    with pytest.raises(WrongCurrentVersionError) as stale:
        client.delete_stream(s, current_version=5)
    assert (stale.value.actual_version, stale.value.expected_version) == (1, 5)
    with pytest.raises(NotFoundError):
        client.get_stream(s)
    # A stream deleted with EXISTS is deleted like any other.
    other = _unique("s")
    client.append_to_stream(other, events=[_event()], current_version=StreamState.NO_STREAM)
    client.delete_stream(other, current_version=StreamState.EXISTS)
    assert client.get_current_version(other) is StreamState.NO_STREAM


def test_server_recreated_stream_rejects_a_second_recreation(backend):
    """While reads may still see a just-recreated stream as deleted, an append expecting
    NO_STREAM is checked against the real head, so a second writer cannot hide the first."""
    client, s = backend.client, _unique("s")
    client.append_to_stream(s, events=[_event(n=0)], current_version=StreamState.NO_STREAM)
    client.delete_stream(s, current_version=0)
    client.append_to_stream(s, events=[_event(n=1)], current_version=StreamState.NO_STREAM)
    with pytest.raises(WrongCurrentVersionError) as second:
        client.append_to_stream(s, events=[_event(n=2)], current_version=StreamState.NO_STREAM)
    assert second.value.actual_version == 1
    assert _n(_settled(lambda: client.get_stream(s))) == [1]


def test_server_assumes_retry_of_a_deleted_event_writes_nothing(backend):
    client, s = backend.client, _unique("s")
    a, b = _event(n="a"), _event(n="b")
    client.append_to_stream(s, events=[a], current_version=StreamState.NO_STREAM)
    client.delete_stream(s, current_version=0)
    for expected in (StreamState.NO_STREAM, StreamState.ANY):
        client.append_to_stream(s, events=[a], current_version=expected)  # accepted as a retry...
        with pytest.raises(NotFoundError):
            client.get_stream(s)  # ...and the stream stays deleted
    client.append_to_stream(s, events=[b], current_version=StreamState.NO_STREAM)
    with pytest.raises(WrongCurrentVersionError):
        client.append_to_stream(s, events=[b], current_version=StreamState.NO_STREAM)  # position 0 holds a
    client.append_to_stream(s, events=[b], current_version=0)  # its own expected version: a retry
    assert [(event.stream_position, event.id) for event in _settled(lambda: client.get_stream(s))] == [(1, b.id)]
    # At the pre-delete head, the deleted ids are new.
    t = _unique("s")
    client.append_to_stream(t, events=[a], current_version=StreamState.NO_STREAM)
    client.delete_stream(t, current_version=0)
    client.append_to_stream(t, events=[a], current_version=0)
    assert [(event.stream_position, event.id) for event in _settled(lambda: client.get_stream(t))] == [(1, a.id)]


def test_server_read_stream_early_break_and_missing_stream(backend):
    client, s = backend.client, _unique("s")
    client.append_to_stream(s, events=[_event(n=i) for i in range(50)], current_version=StreamState.NO_STREAM)
    with client.read_stream(s, backwards=True, timeout=TIMEOUT) as response:
        assert [next(response).stream_position for _ in range(2)] == [49, 48]
    for event in client.read_stream(s, backwards=True):
        break  # no stop(), no context manager: nothing raises
    assert event.stream_position == 49
    assert _positions(client.read_stream(s, stream_position=1, limit=2)) == [1, 2]
    missing = client.read_stream(_unique("s"))  # the call succeeds; "not found" arrives with the first item
    with pytest.raises(NotFoundError):
        next(missing)

    async def scenario(async_client):
        positions = []
        async with await async_client.read_stream(s, backwards=True) as events:
            async for event in events:
                positions.append(event.stream_position)
                if len(positions) == 3:
                    break
        async for event in await async_client.read_stream(s, backwards=True):
            break
        positions.append(event.stream_position)
        missing = await async_client.read_stream(_unique("s"))
        with pytest.raises(NotFoundError):
            await anext(missing)
        return positions

    assert backend.run(scenario) == [49, 48, 47, 49]


def test_server_fence_settles_and_a_late_commit_loses(backend):
    from deerflow_extension_kurrentdb._fence import FENCE_EVENT_TYPE, asettle_append, settle_append

    client, s = backend.client, _unique("s")
    client.append_to_stream(s, events=[_event(n=0)], current_version=StreamState.NO_STREAM)
    # The original never reached the server: the fence lands at its position...
    late = _event(n="late")
    assert settle_append(client, s, expected_version=0, own_event_ids={late.id}, timeout=TIMEOUT) == "not_committed"
    assert client.get_stream(s)[-1].type == FENCE_EVENT_TYPE
    # ...and the original, arriving late at the same expected version, can never commit.
    with pytest.raises(WrongCurrentVersionError):
        client.append_to_stream(s, events=[late], current_version=0)
    # The original committed (lost ack): the fence is rejected and the position holds it.
    mine = _event(n="mine")
    client.append_to_stream(s, events=[mine], current_version=1)
    assert settle_append(client, s, expected_version=1, own_event_ids={mine.id}, timeout=TIMEOUT) == "committed"
    # Someone else's event took the position: not committed, and the fence was rejected.
    client.append_to_stream(s, events=[_event(n="other")], current_version=2)
    assert settle_append(client, s, expected_version=2, own_event_ids={uuid.uuid4()}, timeout=TIMEOUT) == "not_committed"
    assert [event.type for event in client.get_stream(s)] == ["Happened", FENCE_EVENT_TYPE, "Happened", "Happened"]
    assert client.get_current_version(s) == 3

    async def scenario(async_client):
        fresh = _unique("s")
        lost = _event(n="lost")
        outcome = await asettle_append(async_client, fresh, expected_version=StreamState.NO_STREAM, own_event_ids={lost.id}, timeout=TIMEOUT)
        with pytest.raises(WrongCurrentVersionError):
            await async_client.append_to_stream(fresh, events=[lost], current_version=StreamState.NO_STREAM)
        return outcome

    assert backend.run(scenario) == "not_committed"


# --- extension round trips on the server ----------------------------------------------------


@pytest.fixture
def live_client():
    client = KurrentDBClient(CONNECTION_STRING)
    try:
        yield client
    finally:
        client.close()


def _storage(client, config: DeerMemConfig | None = None):
    from deerflow_extension_kurrentdb.memory import KurrentdbMemoryStorage

    return KurrentdbMemoryStorage(config or DeerMemConfig(), client_factory=lambda: client)


async def _async_client():
    client = AsyncKurrentDBClient(CONNECTION_STRING)
    await client.connect()
    return client


def _store(client):
    from deerflow_extension_kurrentdb.run_events import KurrentRunEventStore

    async def factory():
        return client

    return KurrentRunEventStore({}, client_factory=factory)


def _fact(fact_id: str, content: str) -> dict:
    return {"id": fact_id, "content": content, "category": "preference", "confidence": 0.9, "createdAt": "2026-11-01T00:00:00Z", "source": "manual"}


def _create(storage, *facts, user_id: str, agent: str = AGENT):
    return storage.apply_changes({"upserts": list(facts), "upsertRevisions": {fact["id"]: None for fact in facts}}, user_id=user_id, agent_name=agent)


def _readable(client, stream: str) -> list:
    """The readable events (``[]`` for a missing stream), riding out a recreation's read lag."""
    try:
        return list(_settled(lambda: client.get_stream(stream)))
    except NotFoundError:
        return []


def _tb(client, stream: str) -> int | None:
    return client.get_stream_metadata(stream)[0].get("$tb")


def _decoded(event):
    message = from_json(EVENT_TYPE_BY_NAME[event.type], event.data.decode())
    assert EVENT_TYPE_NAMES[type(message)] == event.type
    assert isinstance(json.loads(event.metadata)["deerflow.origin"], int)
    return message


def _canonical_facts(client, user_id: str) -> list[str]:
    return [_decoded(event).fact for event in _readable(client, agent_memory_stream("deerflow", user_id))]


def _session(client, thread_id: str) -> list[tuple[str, str | None]]:
    return [(event.type, getattr(_decoded(event), "content", None)) for event in _readable(client, agent_session_stream(thread_id))]


def _index_kinds(client, deletions) -> list[str]:
    return [event.type.rsplit(".", 1)[-1] for event in _readable(client, deletions.DELETIONS_STREAM)]


def test_live_memory_save_apply_and_clear_round_trip(live_client, _own_deletions_index):
    from deerflow_extension_kurrentdb._naming import memory_stream

    user = _unique("user")
    storage = _storage(live_client)
    summaries = {"user": {"workContext": {"summary": "Builds DeerFlow", "updatedAt": "2026-11-01T00:00:00Z"}}}
    assert storage.load(AGENT, user_id=user)["revision"] == 0
    assert storage.save(summaries, None, user_id=user, expected_revision=0) is True
    _create(storage, _fact("fact_b", "Prefers Python"), _fact("fact_a", "Uses uv"), user_id=user)
    _create(storage, _fact("other_1", "Another agent's"), user_id=user, agent="researcher")

    cold = _storage(live_client).load(AGENT, user_id=user)
    assert [fact["id"] for fact in cold["facts"]] == ["fact_a", "fact_b"]
    assert cold["user"]["workContext"]["summary"] == "Builds DeerFlow"
    assert cold["revision"] == live_client.get_current_version(memory_stream(user)) + 1

    # An update bumps only that fact's revision.
    updated = dict(next(fact for fact in cold["facts"] if fact["id"] == "fact_a"), content="Uses uv everywhere")
    storage.apply_changes({"upserts": [updated], "upsertRevisions": {"fact_a": updated["revision"]}}, user_id=user, agent_name=AGENT)
    after = _storage(live_client).load(AGENT, user_id=user)
    assert {fact["id"]: (fact["revision"], fact["content"]) for fact in after["facts"]} == {"fact_a": (2, "Uses uv everywhere"), "fact_b": (1, "Prefers Python")}

    # A fact delete is a deletion: a boundary that $tb makes the first readable event.
    storage.apply_changes({"deletes": ["fact_b"]}, user_id=user, agent_name=AGENT)
    readable = _readable(live_client, memory_stream(user))
    assert readable[0].stream_position > 0 and _tb(live_client, memory_stream(user)) == readable[0].stream_position
    assert [fact["id"] for fact in _storage(live_client).load(AGENT, user_id=user)["facts"]] == ["fact_a"]
    assert [fact["id"] for fact in _storage(live_client).load("researcher", user_id=user)["facts"]] == ["other_1"]

    # clear_all empties every agent and the summaries; a cold instance agrees.
    storage.clear_all(user_id=user)
    for agent in (AGENT, "researcher"):
        document = _storage(live_client).load(agent, user_id=user)
        assert document["facts"] == []
    assert _storage(live_client).load(AGENT, user_id=user)["user"]["workContext"]["summary"] == ""
    assert _index_kinds(live_client, _own_deletions_index).count("DeletionDone") == 2
    assert storage.flush_canonical(timeout=TIMEOUT)


@pytest.mark.anyio
async def test_live_run_events_put_list_and_delete_round_trip(live_client, _own_deletions_index):
    from deerflow_extension_kurrentdb._naming import run_events_stream

    thread = _unique("thread")
    client = await _async_client()
    try:
        store = _store(client)
        first = await store.put(thread_id=thread, run_id="r1", event_type="human_message", category="message", content="hello")
        await store.put_batch(
            [
                {"thread_id": thread, "run_id": "r1", "event_type": "ai_message", "category": "message", "content": "hi"},
                {"thread_id": thread, "run_id": "r1", "event_type": "llm_end", "category": "trace", "content": ""},
                {"thread_id": thread, "run_id": "r2", "event_type": "ai_message", "category": "message", "content": "second run"},
            ]
        )
        assert first["seq"] == 1
        cold = _store(client)
        assert [message["content"] for message in await cold.list_messages(thread)] == ["hello", "hi", "second run"]
        assert await cold.count_messages(thread) == 3
        assert [event["event_type"] for event in await cold.list_events(thread, "r1")] == ["human_message", "ai_message", "llm_end"]

        assert await store.delete_by_run(thread, "r1") == 3
        stream = run_events_stream(thread)
        readable = _readable(live_client, stream)
        assert readable[0].stream_position > 0 and _tb(live_client, stream) == readable[0].stream_position
        assert [message["content"] for message in await _store(client).list_messages(thread)] == ["second run"]
        assert (await store.put(thread_id=thread, run_id="r3", event_type="ai_message", category="message", content="after"))["seq"] == 5

        assert await store.delete_by_thread(thread) == 2
        for reader in (store, _store(client)):
            assert await reader.list_messages(thread) == []
            assert await reader.count_messages(thread) == 0
        restarted = _store(client)
        assert (await restarted.put(thread_id=thread, run_id="r4", event_type="ai_message", category="message", content="fresh"))["seq"] == 6
        await store.flush_canonical()
        await restarted.flush_canonical()
        primary_side = [kind for kind in _index_kinds(live_client, _own_deletions_index) if kind.startswith("Deletion")]
        assert primary_side == ["DeletionIntended", "DeletionDone"] * 2
    finally:
        await client.close()


def test_live_canonical_memory_emission_cleanup_and_soft_delete(live_client, _own_deletions_index):
    user = _unique("user")
    canonical = agent_memory_stream("deerflow", user)
    storage = _storage(live_client)
    _create(storage, _fact("f1", "Doomed"), _fact("f2", "Kept"), user_id=user)
    assert storage.flush_canonical(timeout=TIMEOUT)
    assert sorted(_canonical_facts(live_client, user)) == ["Doomed", "Kept"]

    # A fact delete rewrites the canonical stream: survivor copies, then $tb past the originals.
    storage.apply_changes({"deletes": ["f1"]}, user_id=user, agent_name=AGENT)
    assert storage.flush_canonical(timeout=TIMEOUT)
    assert _canonical_facts(live_client, user) == ["Kept"]
    assert _tb(live_client, canonical) == _readable(live_client, canonical)[0].stream_position
    assert "CanonicalCleanupDone" in _index_kinds(live_client, _own_deletions_index)

    # Clearing everything leaves no survivor: the canonical stream is soft-deleted.
    storage.clear_all(user_id=user)
    assert storage.flush_canonical(timeout=TIMEOUT)
    with pytest.raises(NotFoundError):
        live_client.get_stream(canonical)
    assert live_client.get_stream_metadata(canonical)[0] == {"$tb": MAX_TB}

    # A later fact recreates it; nothing from before is readable.
    _create(storage, _fact("f3", "After the clear"), user_id=user)
    assert storage.flush_canonical(timeout=TIMEOUT)
    assert _canonical_facts(live_client, user) == ["After the clear"]
    assert storage.run_canonical_obligations().failed == 0


class _BeforeDelete:
    """A sync client that runs ``hook`` once, right before ``delete_stream`` on ``stream``."""

    def __init__(self, inner, stream: str, hook):
        self._inner, self._stream, self._hook = inner, stream, hook

    def __getattr__(self, name):
        target = getattr(self._inner, name)
        if name != "delete_stream":
            return target

        def call(stream_name, *args, **kwargs):
            if stream_name == self._stream and self._hook is not None:
                hook, self._hook = self._hook, None
                hook()
            return target(stream_name, *args, **kwargs)

        return call


def test_live_conditional_soft_delete_loses_to_a_live_append(live_client, _own_deletions_index):
    user = _unique("user")
    canonical = agent_memory_stream("deerflow", user)
    writer = _storage(live_client)
    _create(writer, _fact("f1", "Doomed"), user_id=user)
    assert writer.flush_canonical(timeout=TIMEOUT)

    def live_append():
        _create(writer, _fact("f2", "Valid, after the clear"), user_id=user)
        assert writer.flush_canonical(timeout=TIMEOUT)

    # The cleanup reads the stream, then a valid fact lands before its conditional soft delete:
    # the delete is rejected (the head moved), the cleanup reselects and keeps the new fact.
    storage = _storage(_BeforeDelete(live_client, canonical, live_append))
    storage.clear_all(user_id=user)
    assert storage.flush_canonical(timeout=TIMEOUT)
    assert _canonical_facts(live_client, user) == ["Valid, after the clear"]
    assert [fact["id"] for fact in _storage(live_client).load(AGENT, user_id=user)["facts"]] == ["f2"]
    assert "CanonicalCleanupDone" in _index_kinds(live_client, _own_deletions_index)


@pytest.mark.anyio
async def test_live_canonical_session_emission_cleanup_and_soft_delete(live_client, _own_deletions_index):
    thread, other = _unique("thread"), _unique("thread")
    client = await _async_client()
    try:
        store = _store(client)
        for content, run_id in (("r1 first", "r1"), ("r2 kept", "r2"), ("r1 again", "r1")):
            await store.put(thread_id=thread, run_id=run_id, event_type="ai_message", category="message", content=content)
        await store.put(thread_id=other, run_id="r1", event_type="ai_message", category="message", content="other thread")
        await store.flush_canonical()
        assert _session(live_client, thread) == [("SessionStarted", None), ("AssistantTextGenerated", "r1 first"), ("AssistantTextGenerated", "r2 kept"), ("AssistantTextGenerated", "r1 again")]

        # A run deletion keeps SessionStarted and the other run's events.
        assert await store.delete_by_run(thread, "r1") == 2
        await store.flush_canonical()
        assert _session(live_client, thread) == [("SessionStarted", None), ("AssistantTextGenerated", "r2 kept")]

        # A thread deletion removes everything: the session stream is soft-deleted; the other thread is untouched.
        assert await store.delete_by_thread(thread) == 1
        await store.flush_canonical()
        with pytest.raises(NotFoundError):
            live_client.get_stream(agent_session_stream(thread))
        assert _session(live_client, other) == [("SessionStarted", None), ("AssistantTextGenerated", "other thread")]

        # The next write recreates the session with a fresh SessionStarted.
        await store.put(thread_id=thread, run_id="r3", event_type="ai_message", category="message", content="new life")
        await store.flush_canonical()
        assert _session(live_client, thread) == [("SessionStarted", None), ("AssistantTextGenerated", "new life")]
        report = await store.run_canonical_obligations()
        assert report.failed == 0
        kinds = _index_kinds(live_client, _own_deletions_index)
        assert kinds.count("DeletionDone") == 2 and kinds.count("CanonicalCleanupDone") == 2
    finally:
        await client.close()


@pytest.mark.anyio
async def test_live_recovery_finishes_an_open_deletion(live_client, _own_deletions_index):
    """A deleter that died right after the boundary committed: a cold store's recovery finishes $tb and DeletionDone."""
    from deerflow_extension_kurrentdb._naming import run_events_stream

    thread = _unique("thread")
    client = await _async_client()
    try:
        store = _store(client)
        await store.put(thread_id=thread, run_id="r1", event_type="ai_message", category="message", content="doomed")
        await store.put(thread_id=thread, run_id="r2", event_type="ai_message", category="message", content="kept")
        stream = run_events_stream(thread)

        # Fail the $tb write (the step after the boundary): the deletion is reported, the intent stays open.
        real_set = client.set_stream_metadata

        async def lost(stream_name, **kwargs):
            raise ConnectionError("deleter died")

        client.set_stream_metadata = lost
        try:
            assert await store.delete_by_run(thread, "r1") == 1
        finally:
            client.set_stream_metadata = real_set
        assert _tb(live_client, stream) is None
        assert "DeletionDone" not in _index_kinds(live_client, _own_deletions_index)
        assert [message["content"] for message in await store.list_messages(thread)] == ["kept"]  # reads fold from the boundary

        recovering = _store(client)
        assert await recovering.recover_deletions() == []
        readable = _readable(live_client, stream)
        assert _tb(live_client, stream) == readable[0].stream_position > 0
        assert [kind for kind in _index_kinds(live_client, _own_deletions_index) if kind.startswith("Deletion")] == ["DeletionIntended", "DeletionDone"]
        await store.flush_canonical()
        await recovering.flush_canonical()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_live_back_to_back_emissions_after_a_thread_deletion_all_land(live_client, _own_deletions_index):
    """Puts right after a thread deletion: the first recreates the session stream, the next ones
    are emitted while reads may still see it deleted; every canonical event must land."""
    thread = _unique("thread")
    client = await _async_client()
    try:
        store = _store(client)
        for round_number in range(3):
            await store.put(thread_id=thread, run_id=f"r{round_number}", event_type="ai_message", category="message", content=f"before {round_number}")
            await store.flush_canonical()
            assert await store.delete_by_thread(thread) == (1 if round_number == 0 else 5)
            await store.flush_canonical()
            with pytest.raises(NotFoundError):
                live_client.get_stream(agent_session_stream(thread))
            texts = [f"after {round_number}.{index}" for index in range(4)]
            for text in texts:
                await store.put(thread_id=thread, run_id=f"a{round_number}", event_type="ai_message", category="message", content=text)
            await store.flush_canonical()
            assert _session(live_client, thread) == [("SessionStarted", None)] + [("AssistantTextGenerated", text) for text in texts]
        assert (await store.run_canonical_obligations()).failed == 0
    finally:
        await client.close()
