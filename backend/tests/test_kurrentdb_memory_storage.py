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
