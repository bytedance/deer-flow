"""KurrentDB extension scaffold: stream naming, settings, install and the in-memory fake.

The fake (``kurrentdb_fake.FakeKurrentDB``) backs every later KurrentDB suite, so
its semantics are pinned here. Tests named ``test_fake_assumes_*`` encode
behaviour inferred from KurrentDB docs; the live suite confirms them.
"""

from __future__ import annotations

import asyncio
import json
import urllib.parse
import uuid
from pathlib import Path

import pytest
from kurrentdb_fake import FakeKurrentDB
from kurrentdbclient import NewEvent, RecordedEvent, StreamState
from kurrentdbclient.exceptions import DeadlineExceededError, NotFoundError, WrongCurrentVersionError

from deerflow.extensions.registry import ExtensionRegistry

pytestmark = pytest.mark.bundled_extension

EXTENSION_ROOT = Path(__file__).resolve().parents[2] / "examples/deerflow-extension-kurrentdb"


@pytest.fixture(autouse=True)
def _extension_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(EXTENSION_ROOT))


def _event(kind: str = "Happened", **data) -> NewEvent:
    return NewEvent(type=kind, data=json.dumps(data).encode())


# --- stream naming -----------------------------------------------------------


def test_enc_is_injective_and_has_no_dash():
    from deerflow_extension_kurrentdb._naming import enc

    samples = ["a-b", "a%2Db", "a%b", "a b", "a/b", "a.b", "a_b", "ab", "", "None", "global", "user.x", "ü", "ü", "用户", "%", "%25", "a-", "-"]
    encoded = [enc(raw) for raw in samples]
    assert len(set(encoded)) == len(samples), "enc must be injective"
    for raw, out in zip(samples, encoded, strict=True):
        assert "-" not in out
        assert all(ch.isascii() and (ch.isalnum() or ch in "_%") for ch in out), out
        # Percent-decoding recovers the original, which is what injectivity rests on.
        assert urllib.parse.unquote(out, errors="strict") == raw
    assert enc("a-b") == "a%2Db"
    assert enc("a%2Db") == "a%252Db"
    assert enc("ü") == "%C3%BC"
    assert enc("A_z9") == "A_z9"
    assert enc("a.b") == "a%2Eb"


def test_global_and_user_streams_disjoint():
    from deerflow_extension_kurrentdb._naming import DELETIONS_STREAM, memory_meta_stream, memory_stream, run_events_stream

    assert memory_stream(None) == "deerflow.memory-global"
    assert memory_meta_stream(None) == "deerflow.memory-meta-global"
    assert memory_stream("alice") == "deerflow.memory-user.alice"
    assert memory_meta_stream("alice") == "deerflow.memory-meta-user.alice"
    assert run_events_stream("t-1") == "deerflow.run-events-t%2D1"
    assert DELETIONS_STREAM == "deerflow.kurrent-deletions"

    ids = ["global", "None", "", "a-b", "a%2Db", "user.x", "meta-global", "用户", "a b"]
    names = [memory_stream(None), memory_meta_stream(None), DELETIONS_STREAM]
    names += [memory_stream(i) for i in ids] + [memory_meta_stream(i) for i in ids] + [run_events_stream(i) for i in ids]
    assert len(set(names)) == len(names)
    # The KurrentDB category is everything before the first dash; each family keeps its own.
    categories = {name: name.split("-", 1)[0] for name in names}
    assert {categories[memory_stream(i)] for i in [None, *ids]} == {"deerflow.memory"}
    assert {categories[memory_meta_stream(i)] for i in [None, *ids]} == {"deerflow.memory"}
    assert {categories[run_events_stream(i)] for i in ids} == {"deerflow.run"}
    # Fixed prefixes carry every dash; encoded ids add none.
    for user_id in ids:
        assert memory_stream(user_id).count("-") == 1
        assert memory_meta_stream(user_id).count("-") == 2
        assert run_events_stream(user_id).count("-") == 2
    assert not any(name.startswith("$") for name in names)


# --- settings ----------------------------------------------------------------


def test_settings_validation(monkeypatch):
    from deerflow_extension_kurrentdb._settings import KurrentSettings, load_settings

    for name in ("KURRENTDB_CONNECTION_STRING", "KURRENTDB_TIMEOUT_SECONDS", "KURRENTDB_CANONICAL_EVENTS"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValueError, match="KURRENTDB_CONNECTION_STRING"):
        load_settings()
    monkeypatch.setenv("KURRENTDB_CONNECTION_STRING", "   ")
    with pytest.raises(ValueError, match="KURRENTDB_CONNECTION_STRING"):
        load_settings()

    monkeypatch.setenv("KURRENTDB_CONNECTION_STRING", "kurrentdb://localhost:2113?tls=false")
    assert load_settings() == KurrentSettings(connection_string="kurrentdb://localhost:2113?tls=false", timeout=10.0, canonical_events=False)

    for bad in ("0", "-1", "nan", "inf", "-inf", "abc", ""):
        monkeypatch.setenv("KURRENTDB_TIMEOUT_SECONDS", bad)
        with pytest.raises(ValueError, match="KURRENTDB_TIMEOUT_SECONDS"):
            load_settings()
    monkeypatch.setenv("KURRENTDB_TIMEOUT_SECONDS", "2.5")
    assert load_settings().timeout == 2.5

    for on in ("1", "true", "TRUE", "yes", "on", " On "):
        monkeypatch.setenv("KURRENTDB_CANONICAL_EVENTS", on)
        assert load_settings().canonical_events is True
    for off in ("0", "false", "no", "off", "", "maybe"):
        monkeypatch.setenv("KURRENTDB_CANONICAL_EVENTS", off)
        assert load_settings().canonical_events is False


# --- install -----------------------------------------------------------------


def test_install_registers_store_and_service():
    import deerflow_extension_kurrentdb
    from deerflow_extension_kurrentdb import install

    registry = ExtensionRegistry()
    with registry.attributed_to("kurrentdb"):
        install(registry, {})
    built = registry.build()
    assert [(owner, name) for owner, (name, _factory) in built.run_event_store_factories] == [("kurrentdb", "kurrent")]
    # Ledger ruling R1: the recovery service is registered in Task 13.
    assert callable(built.run_event_store_factories[0][1][1])
    assert deerflow_extension_kurrentdb.install is install

    class _Refusing:
        def run_event_store(self, name, factory):
            return False

    with pytest.raises(RuntimeError, match="run-event store"):
        install(_Refusing(), {})


def test_install_does_not_import_the_store_or_connect():
    import sys

    from deerflow_extension_kurrentdb import install

    sys.modules.pop("deerflow_extension_kurrentdb.run_events", None)
    registry = ExtensionRegistry()
    with registry.attributed_to("kurrentdb"):
        install(registry, {})
    assert "deerflow_extension_kurrentdb.run_events" not in sys.modules


# --- client factories ----------------------------------------------------------


def test_client_factories_are_lazy_and_memoized(monkeypatch):
    from deerflow_extension_kurrentdb import _client
    from deerflow_extension_kurrentdb._settings import KurrentSettings

    created = []

    class _Sync:
        def __init__(self, uri):
            created.append(("sync", uri))

    class _Async:
        def __init__(self, uri):
            created.append(("async", uri))
            self.connected = 0

        async def connect(self):
            self.connected += 1

    monkeypatch.setattr(_client, "KurrentDBClient", _Sync)
    monkeypatch.setattr(_client, "AsyncKurrentDBClient", _Async)
    _client.reset_clients()
    settings = KurrentSettings(connection_string="kurrentdb://h:2113?tls=false", timeout=1.0, canonical_events=False)
    other = KurrentSettings(connection_string="kurrentdb://other:2113?tls=false", timeout=1.0, canonical_events=False)

    get_sync = _client.sync_client_factory(settings)
    get_async = _client.async_client_factory(settings)
    assert created == []
    assert get_sync() is get_sync() is _client.sync_client_factory(settings)()
    assert _client.sync_client_factory(other)() is not get_sync()

    async def _both():
        first = await get_async()
        second = await _client.async_client_factory(settings)()
        return first, second

    first, second = asyncio.run(_both())
    assert first is second and first.connected == 1
    assert created == [("sync", settings.connection_string), ("sync", other.connection_string), ("async", settings.connection_string)]
    _client.reset_clients()


# --- the fake ----------------------------------------------------------------


def test_fake_clients_mirror_real_signatures():
    import inspect

    from kurrentdb_fake import FakeAsyncClient, FakeSyncClient
    from kurrentdbclient import AsyncKurrentDBClient, KurrentDBClient

    methods = ["append_to_stream", "get_stream", "get_current_version", "delete_stream", "get_stream_metadata", "set_stream_metadata"]
    for fake, real in ((FakeSyncClient, KurrentDBClient), (FakeAsyncClient, AsyncKurrentDBClient)):
        for name in methods:
            real_params = [(p.name, p.kind, p.default) for p in inspect.signature(getattr(real, name)).parameters.values() if p.name != "self"]
            fake_params = [(p.name, p.kind, p.default) for p in inspect.signature(getattr(fake, name)).parameters.values() if p.name != "self"]
            # The real sync append marks stream_name positional-only; keyword use is the shared subset.
            assert [(n, d) for n, _, d in fake_params] == [(n, d) for n, _, d in real_params], (fake.__name__, name)
            assert inspect.iscoroutinefunction(getattr(fake, name)) is inspect.iscoroutinefunction(getattr(real, name))


def test_fake_append_expected_version_conflict():
    server = FakeKurrentDB()
    client = server.sync_client()

    with pytest.raises(NotFoundError):
        client.get_stream("s")
    assert client.get_current_version("s") is StreamState.NO_STREAM
    with pytest.raises(WrongCurrentVersionError) as missing:
        client.append_to_stream("s", events=[_event()], current_version=0)
    assert (missing.value.stream_name, missing.value.actual_version, missing.value.expected_version) == ("s", StreamState.NO_STREAM, 0)
    with pytest.raises(WrongCurrentVersionError):
        client.append_to_stream("s", events=[_event()], current_version=StreamState.EXISTS)

    first = client.append_to_stream("s", events=[_event(n=0), _event(n=1)], current_version=StreamState.NO_STREAM)
    assert client.get_current_version("s") == 1
    with pytest.raises(WrongCurrentVersionError) as exists:
        client.append_to_stream("s", events=[_event()], current_version=StreamState.NO_STREAM)
    assert (exists.value.stream_name, exists.value.actual_version, exists.value.expected_version) == ("s", 1, StreamState.NO_STREAM)
    with pytest.raises(WrongCurrentVersionError) as stale:
        client.append_to_stream("s", events=_event(), current_version=0)
    assert (stale.value.actual_version, stale.value.expected_version) == (1, 0)
    second = client.append_to_stream("s", events=_event(n=2), current_version=1)
    third = client.append_to_stream("s", events=[_event(n=3)], current_version=StreamState.ANY)
    fourth = client.append_to_stream("s", events=[_event(n=4)], current_version=StreamState.EXISTS)
    assert first < second < third < fourth

    recorded = client.get_stream("s")
    assert all(isinstance(e, RecordedEvent) for e in recorded)
    assert [e.stream_position for e in recorded] == [0, 1, 2, 3, 4]
    assert [json.loads(e.data)["n"] for e in recorded] == [0, 1, 2, 3, 4]
    assert recorded[-1].commit_position == fourth and recorded[-1].stream_name == "s"
    assert [e.stream_position for e in client.get_stream("s", stream_position=3)] == [3, 4]
    assert [e.stream_position for e in client.get_stream("s", backwards=True, limit=2)] == [4, 3]
    assert [e.stream_position for e in client.get_stream("s", stream_position=2, backwards=True)] == [2, 1, 0]

    # An append is atomic: a conflicting batch leaves nothing behind.
    with pytest.raises(WrongCurrentVersionError):
        client.append_to_stream("s", events=[_event(), _event()], current_version=2)
    assert client.get_current_version("s") == 4


def test_fake_same_id_append_is_idempotent():
    server = FakeKurrentDB()
    client = server.sync_client()
    a, b = _event(n=1), _event(n=2)
    position = client.append_to_stream("s", events=[a, b], current_version=StreamState.NO_STREAM)
    # A retry of the same events at the same expected version succeeds without writing twice.
    assert client.append_to_stream("s", events=[a, b], current_version=StreamState.NO_STREAM) == position
    assert client.append_to_stream("s", events=[a, b], current_version=StreamState.ANY) == position
    assert client.get_current_version("s") == 1
    # A different event at that position is a conflict, which is what the fence relies on.
    with pytest.raises(WrongCurrentVersionError):
        client.append_to_stream("s", events=[_event()], current_version=StreamState.NO_STREAM)


def test_fake_truncate_and_soft_delete_semantics():
    server = FakeKurrentDB()
    client = server.sync_client()
    client.append_to_stream("s", events=[_event(n=i) for i in range(5)], current_version=StreamState.NO_STREAM)

    assert client.get_stream_metadata("s") == ({}, StreamState.NO_STREAM)
    with pytest.raises(WrongCurrentVersionError) as meta:
        client.set_stream_metadata("s", metadata={"$tb": 2}, current_version=0)
    assert (meta.value.stream_name, meta.value.actual_version, meta.value.expected_version) == ("$$s", StreamState.NO_STREAM, 0)
    client.set_stream_metadata("s", metadata={"$tb": 2}, current_version=StreamState.NO_STREAM)
    assert client.get_stream_metadata("s") == ({"$tb": 2}, 0)
    with pytest.raises(WrongCurrentVersionError):
        client.set_stream_metadata("s", metadata={"$tb": 3}, current_version=StreamState.NO_STREAM)

    # $tb hides events below it from every named-stream read; positions are unchanged.
    assert [e.stream_position for e in client.get_stream("s")] == [2, 3, 4]
    assert [e.stream_position for e in client.get_stream("s", stream_position=0)] == [2, 3, 4]
    assert [e.stream_position for e in client.get_stream("s", backwards=True)] == [4, 3, 2]
    assert client.get_stream("s", stream_position=1, backwards=True) == ()
    assert client.get_current_version("s") == 4
    client.append_to_stream("s", events=[_event(n=5)], current_version=4)
    assert [e.stream_position for e in client.get_stream("s")] == [2, 3, 4, 5]
    # Metadata writes replace the whole document, like the real client.
    client.set_stream_metadata("s", metadata={"$tb": 4, "x": "y"}, current_version=0)
    assert client.get_stream_metadata("s") == ({"$tb": 4, "x": "y"}, 1)
    assert [e.stream_position for e in client.get_stream("s")] == [4, 5]

    # Soft delete: conditional on the head; then the stream reads as missing.
    with pytest.raises(WrongCurrentVersionError) as stale_delete:
        client.delete_stream("s", current_version=4)
    assert (stale_delete.value.stream_name, stale_delete.value.actual_version, stale_delete.value.expected_version) == ("s", 5, 4)
    client.delete_stream("s", current_version=5)
    with pytest.raises(NotFoundError):
        client.get_stream("s")
    # A conditional delete of a deleted or missing stream is NotFound: the real client maps actual version -1 to it.
    for expected in (5, StreamState.EXISTS):
        with pytest.raises(NotFoundError):
            client.delete_stream("s", current_version=expected)
    with pytest.raises(NotFoundError):
        client.delete_stream("never", current_version=0)
    assert client.get_current_version("s") is StreamState.NO_STREAM

    # Appending recreates it: revisions continue and nothing from before the delete is readable.
    client.append_to_stream("s", events=[_event(n=6)], current_version=StreamState.NO_STREAM)
    recorded = client.get_stream("s")
    assert [(e.stream_position, json.loads(e.data)["n"]) for e in recorded] == [(6, 6)]
    assert client.get_current_version("s") == 6
    assert client.get_stream_metadata("s")[0]["$tb"] == 6
    assert client.get_stream_metadata("s")[0]["x"] == "y"


def test_fake_assumes_soft_deleted_stream_accepts_previous_head_or_any():
    """Assumption (kurrentdbclient's get_current_version comment): after a soft delete,
    both NO_STREAM and the pre-delete head are valid expected versions, as is ANY.
    Confirm against a live server in the live suite."""
    for expected in (StreamState.NO_STREAM, 1, StreamState.ANY):
        server = FakeKurrentDB()
        client = server.sync_client()
        client.append_to_stream("s", events=[_event(), _event()], current_version=StreamState.NO_STREAM)
        client.delete_stream("s", current_version=1)
        client.append_to_stream("s", events=[_event()], current_version=expected)
        assert [e.stream_position for e in client.get_stream("s")] == [2]
    server = FakeKurrentDB()
    client = server.sync_client()
    client.append_to_stream("s", events=[_event()], current_version=StreamState.NO_STREAM)
    client.delete_stream("s", current_version=0)
    for bad in (StreamState.EXISTS, 5):
        with pytest.raises(WrongCurrentVersionError):
            client.append_to_stream("s", events=[_event()], current_version=bad)


def test_fake_assumes_soft_delete_writes_max_tb_and_keeps_metadata():
    """Assumption: a soft delete sets ``$tb`` to the maximum int64 (keeping other keys)
    and bumps the metadata version; the next append lowers it to the first new event."""
    server = FakeKurrentDB()
    client = server.sync_client()
    client.append_to_stream("s", events=[_event()], current_version=StreamState.NO_STREAM)
    client.set_stream_metadata("s", metadata={"k": "v"})
    client.delete_stream("s", current_version=0)
    metadata, version = client.get_stream_metadata("s")
    assert metadata == {"k": "v", "$tb": 2**63 - 1} and version == 1


def test_fake_assumes_unconditional_delete_of_missing_stream_is_a_no_op():
    """Assumption: ``delete_stream`` on a missing or soft-deleted stream with ``ANY``
    or ``NO_STREAM`` succeeds without writing anything. Confirm in the live suite."""
    server = FakeKurrentDB()
    client = server.sync_client()
    for expected in (StreamState.ANY, StreamState.NO_STREAM):
        client.delete_stream("never", current_version=expected)
    assert client.get_stream_metadata("never") == ({}, StreamState.NO_STREAM)
    client.append_to_stream("s", events=[_event()], current_version=StreamState.NO_STREAM)
    client.delete_stream("s", current_version=0)
    deleted_metadata = client.get_stream_metadata("s")
    for expected in (StreamState.ANY, StreamState.NO_STREAM):
        client.delete_stream("s", current_version=expected)
    assert client.get_stream_metadata("s") == deleted_metadata


def test_fake_failure_injection_lost_ack_and_late_commit():
    server = FakeKurrentDB()
    client = server.sync_client()
    client.append_to_stream("s", events=[_event()], current_version=StreamState.NO_STREAM)

    # Lost ack before commit: nothing lands.
    server.fail_next("append_to_stream", DeadlineExceededError("timeout"))
    with pytest.raises(DeadlineExceededError):
        client.append_to_stream("s", events=[_event()], current_version=0)
    assert client.get_current_version("s") == 0

    # Lost ack after commit: the write lands, the caller sees an error.
    lost = _event(n="lost")
    server.fail_next("append_to_stream", DeadlineExceededError("timeout"), after_commit=True)
    with pytest.raises(DeadlineExceededError):
        client.append_to_stream("s", events=[lost], current_version=0)
    assert client.get_stream("s")[-1].id == lost.id

    # Late commit losing to a fence: the delayed write only ever commits at its expected version.
    late = _event(n="late")
    pending = server.delay_commit("append_to_stream", DeadlineExceededError("timeout"))
    with pytest.raises(DeadlineExceededError):
        client.append_to_stream("s", events=[late], current_version=1)
    assert client.get_current_version("s") == 1
    fence = _event("Fence")
    client.append_to_stream("s", events=[fence], current_version=1)
    pending.release()
    assert pending.committed is False and isinstance(pending.error, WrongCurrentVersionError)
    assert [e.id for e in client.get_stream("s")][-1] == fence.id

    # Late commit winning: released before anyone else writes, it lands.
    late2 = _event(n="late2")
    pending = server.delay_commit("append_to_stream", DeadlineExceededError("timeout"))
    with pytest.raises(DeadlineExceededError):
        client.append_to_stream("s", events=[late2], current_version=2)
    pending.release()
    assert pending.committed is True
    assert client.get_stream("s")[-1].id == late2.id

    # Failures target one method and are consumed once.
    server.fail_next("get_stream", NotFoundError("boom"))
    assert client.get_current_version("s") == 3
    with pytest.raises(NotFoundError):
        client.get_stream("s")
    assert client.get_stream("s")

    # An unreachable server fails every call until cleared.
    server.set_unavailable(DeadlineExceededError("down"))
    with pytest.raises(DeadlineExceededError):
        client.get_current_version("s")
    server.set_unavailable(None)
    assert client.get_current_version("s") == 3
    assert ("get_current_version", "s") in [(call.method, call.stream_name) for call in server.calls]


def test_fake_async_client_shares_the_server():
    server = FakeKurrentDB()
    sync_client = server.sync_client()
    async_client = server.async_client()

    async def _scenario():
        await async_client.connect()
        await async_client.append_to_stream("s", events=[_event(n=1)], current_version=StreamState.NO_STREAM)
        server.fail_next("append_to_stream", WrongCurrentVersionError("x"))
        with pytest.raises(WrongCurrentVersionError):
            await async_client.append_to_stream("s", events=[_event()], current_version=0)
        await async_client.set_stream_metadata("s", metadata={"$tb": 0}, current_version=StreamState.NO_STREAM)
        return await async_client.get_stream("s"), await async_client.get_current_version("s"), await async_client.get_stream_metadata("s")

    events, version, metadata = asyncio.run(_scenario())
    assert [json.loads(e.data)["n"] for e in events] == [1]
    assert version == 0 and metadata == ({"$tb": 0}, 0)
    assert sync_client.get_current_version("s") == 0
    assert isinstance(events[0].id, uuid.UUID)
