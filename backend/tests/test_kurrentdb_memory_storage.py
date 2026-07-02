"""Tests for the event-sourced KurrentDB memory storage prototype (#3796)."""

import json

import pytest
from kurrentdbclient import NewEvent
from kurrentdbclient.exceptions import NotFoundError

from deerflow.agents.memory.storage import MemoryStorage
from deerflow.community.kurrentdb.memory_storage import (
    EVENT_TYPE,
    STREAM_PREFIX,
    KurrentdbMemoryStorage,
)


class FakeKurrentDBClient:
    """In-memory stand-in for kurrentdbclient.KurrentDBClient (unit tests only)."""

    def __init__(self):
        self.streams: dict[str, list[NewEvent]] = {}
        self.append_calls: list[dict] = []
        self.get_stream_calls: list[dict] = []

    def append_to_stream(self, stream_name, *, events, current_version):
        new_events = [events] if isinstance(events, NewEvent) else list(events)
        self.append_calls.append({"stream_name": stream_name, "events": new_events, "current_version": current_version})
        self.streams.setdefault(stream_name, []).extend(new_events)
        return len(self.streams[stream_name]) - 1

    def get_stream(self, stream_name, *, backwards=False, limit=2**63 - 1, **kwargs):
        self.get_stream_calls.append({"stream_name": stream_name, "backwards": backwards, "limit": limit})
        if stream_name not in self.streams:
            raise NotFoundError(stream_name)
        events = list(self.streams[stream_name])
        if backwards:
            events.reverse()
        return tuple(events[:limit])


@pytest.fixture
def fake_client():
    return FakeKurrentDBClient()


@pytest.fixture
def storage(fake_client):
    return KurrentdbMemoryStorage(client_factory=lambda: fake_client)


class TestConstruction:
    def test_is_a_memory_storage(self, storage):
        assert isinstance(storage, MemoryStorage)

    def test_missing_connection_string_raises(self, monkeypatch):
        monkeypatch.delenv("KURRENTDB_CONNECTION_STRING", raising=False)
        with pytest.raises(RuntimeError, match="KURRENTDB_CONNECTION_STRING"):
            KurrentdbMemoryStorage()

    def test_env_connection_string_accepted_without_connecting(self, monkeypatch):
        monkeypatch.setenv("KURRENTDB_CONNECTION_STRING", "kurrentdb://localhost:2113?tls=false")
        # Must not raise and must not touch the network (client is lazy).
        KurrentdbMemoryStorage()


class TestStreamName:
    def test_global_stream(self):
        assert KurrentdbMemoryStorage._stream_name() == f"{STREAM_PREFIX}-_global"

    def test_user_stream(self):
        assert KurrentdbMemoryStorage._stream_name(user_id="alice") == f"{STREAM_PREFIX}-alice"

    def test_user_agent_stream(self):
        assert KurrentdbMemoryStorage._stream_name("my-agent", user_id="alice") == f"{STREAM_PREFIX}-alice.agent.my-agent"

    @pytest.mark.parametrize("invalid_name", ["", "../etc/passwd", "agent/name", "agent name", "agent_name"])
    def test_invalid_agent_name_raises(self, invalid_name):
        with pytest.raises(ValueError, match="Invalid agent name|Agent name must be a non-empty string"):
            KurrentdbMemoryStorage._stream_name(invalid_name, user_id="alice")

    @pytest.mark.parametrize("invalid_user_id", ["../etc", "_global"])
    def test_invalid_user_id_raises(self, invalid_user_id):
        with pytest.raises(ValueError, match="Invalid user id"):
            KurrentdbMemoryStorage._stream_name(user_id=invalid_user_id)


class TestSave:
    def test_appends_memory_updated_event(self, storage, fake_client):
        memory = {"version": "1.0", "facts": [{"id": "f1", "content": "prefers uv"}]}

        assert storage.save(memory, user_id="alice") is True

        assert len(fake_client.append_calls) == 1
        call = fake_client.append_calls[0]
        assert call["stream_name"] == f"{STREAM_PREFIX}-alice"
        event = call["events"][0]
        assert event.type == EVENT_TYPE
        stored = json.loads(event.data)
        assert stored["facts"] == memory["facts"]
        assert stored["lastUpdated"]  # stamped on save, mirrors FileMemoryStorage
        metadata = json.loads(event.metadata)
        assert metadata == {"user_id": "alice", "agent_name": None, "source": "deerflow-memory", "schema": "v0"}

    def test_save_does_not_mutate_caller_dict(self, storage):
        memory = {"version": "1.0", "facts": []}
        storage.save(memory, user_id="alice")
        assert "lastUpdated" not in memory

    def test_save_failure_returns_false(self, fake_client):
        def broken_append(*args, **kwargs):
            raise ConnectionError("kurrentdb down")

        fake_client.append_to_stream = broken_append
        storage = KurrentdbMemoryStorage(client_factory=lambda: fake_client)
        assert storage.save({"version": "1.0"}, user_id="alice") is False

    def test_save_invalid_agent_name_raises(self, storage):
        with pytest.raises(ValueError, match="Invalid agent name"):
            storage.save({"version": "1.0"}, "bad/agent", user_id="alice")


class TestLoadReload:
    def test_load_missing_stream_returns_empty_memory(self, storage):
        memory = storage.load(user_id="alice")
        assert memory["version"] == "1.0"
        assert memory["facts"] == []

    def test_load_reads_newest_event_backwards(self, storage, fake_client):
        storage.save({"version": "1.0", "facts": [{"id": "f1"}]}, user_id="alice")
        storage.save({"version": "1.0", "facts": [{"id": "f1"}, {"id": "f2"}]}, user_id="alice")

        # Fresh instance sharing the same client: no warm cache, must read from KurrentDB.
        fresh = KurrentdbMemoryStorage(client_factory=lambda: fake_client)
        memory = fresh.load(user_id="alice")

        assert [f["id"] for f in memory["facts"]] == ["f1", "f2"]
        assert fake_client.get_stream_calls[-1] == {"stream_name": f"{STREAM_PREFIX}-alice", "backwards": True, "limit": 1}

    def test_load_is_cache_first_after_save(self, storage, fake_client):
        storage.save({"version": "1.0", "facts": []}, user_id="alice")
        storage.load(user_id="alice")
        assert fake_client.get_stream_calls == []  # served from cache, no read

    def test_reload_picks_up_external_append(self, storage, fake_client):
        storage.save({"version": "1.0", "facts": []}, user_id="alice")
        # Another writer (e.g. second gateway) appends a newer snapshot.
        other = KurrentdbMemoryStorage(client_factory=lambda: fake_client)
        other.save({"version": "1.0", "facts": [{"id": "external"}]}, user_id="alice")

        assert storage.load(user_id="alice")["facts"] == []  # stale cache
        assert storage.reload(user_id="alice")["facts"] == [{"id": "external"}]
        assert storage.load(user_id="alice")["facts"] == [{"id": "external"}]  # cache refreshed

    def test_load_transport_error_returns_empty_and_does_not_cache(self, fake_client):
        calls = {"n": 0}
        real_get_stream = fake_client.get_stream

        def flaky_get_stream(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("kurrentdb down")
            return real_get_stream(*args, **kwargs)

        fake_client.get_stream = flaky_get_stream
        writer = KurrentdbMemoryStorage(client_factory=lambda: fake_client)
        writer.save({"version": "1.0", "facts": [{"id": "f1"}]}, user_id="alice")

        reader = KurrentdbMemoryStorage(client_factory=lambda: fake_client)
        assert reader.load(user_id="alice")["facts"] == []  # error -> empty
        assert reader.load(user_id="alice")["facts"] == [{"id": "f1"}]  # retried, not cached-empty

    def test_corrupt_event_returns_empty_without_caching(self, fake_client):
        fake_client.streams[f"{STREAM_PREFIX}-alice"] = [NewEvent(type=EVENT_TYPE, data=b"not json")]
        storage = KurrentdbMemoryStorage(client_factory=lambda: fake_client)
        assert storage.load(user_id="alice")["facts"] == []

    def test_agent_scoped_round_trip(self, storage, fake_client):
        memory = {"version": "1.0", "facts": [{"id": "f1", "content": "prefers uv"}]}

        assert storage.save(memory, "my-agent", user_id="alice") is True

        # Fresh instance sharing the same client: no warm cache, must read from KurrentDB.
        fresh = KurrentdbMemoryStorage(client_factory=lambda: fake_client)
        loaded = fresh.load("my-agent", user_id="alice")

        assert loaded["facts"] == memory["facts"]
        assert fake_client.get_stream_calls[-1]["stream_name"] == f"{STREAM_PREFIX}-alice.agent.my-agent"

    def test_global_stream_round_trip(self, storage, fake_client):
        memory = {"version": "1.0", "facts": [{"id": "f1", "content": "global fact"}]}

        assert storage.save(memory, user_id=None) is True

        fresh = KurrentdbMemoryStorage(client_factory=lambda: fake_client)
        loaded = fresh.load(user_id=None)

        assert loaded["facts"] == memory["facts"]
        assert fake_client.get_stream_calls[-1]["stream_name"] == f"{STREAM_PREFIX}-_global"

    def test_wrong_event_type_returns_empty_and_does_not_cache(self, fake_client):
        fake_client.streams[f"{STREAM_PREFIX}-alice"] = [NewEvent(type="SomethingElse", data=b"{}")]
        storage = KurrentdbMemoryStorage(client_factory=lambda: fake_client)

        assert storage.load(user_id="alice")["facts"] == []
        # Not cached as empty: appending a proper event afterward is picked up on retry.
        fake_client.streams[f"{STREAM_PREFIX}-alice"].append(NewEvent(type=EVENT_TYPE, data=json.dumps({"version": "1.0", "facts": [{"id": "f1"}]}).encode("utf-8")))
        assert storage.load(user_id="alice")["facts"] == [{"id": "f1"}]

    def test_non_serializable_save_raises_and_does_not_append(self, storage, fake_client):
        with pytest.raises(TypeError):
            storage.save({"bad": object()}, user_id="alice")
        assert fake_client.append_calls == []


class TestGetMemoryStorageIntegration:
    STORAGE_CLASS_PATH = "deerflow.community.kurrentdb.memory_storage.KurrentdbMemoryStorage"

    @pytest.fixture(autouse=True)
    def reset_storage_singleton(self):
        import deerflow.agents.memory.storage as storage_module

        storage_module._storage_instance = None
        yield
        storage_module._storage_instance = None

    def _patch_config(self, monkeypatch):
        from unittest.mock import patch

        from deerflow.config.memory_config import MemoryConfig

        return patch(
            "deerflow.agents.memory.storage.get_memory_config",
            return_value=MemoryConfig(storage_class=self.STORAGE_CLASS_PATH),
        )

    def test_reflection_loads_kurrentdb_storage(self, monkeypatch):
        from deerflow.agents.memory.storage import get_memory_storage

        monkeypatch.setenv("KURRENTDB_CONNECTION_STRING", "kurrentdb://localhost:2113?tls=false")
        with self._patch_config(monkeypatch):
            assert isinstance(get_memory_storage(), KurrentdbMemoryStorage)

    def test_missing_env_falls_back_to_file_storage(self, monkeypatch):
        from deerflow.agents.memory.storage import FileMemoryStorage, get_memory_storage

        monkeypatch.delenv("KURRENTDB_CONNECTION_STRING", raising=False)
        with self._patch_config(monkeypatch):
            assert isinstance(get_memory_storage(), FileMemoryStorage)
