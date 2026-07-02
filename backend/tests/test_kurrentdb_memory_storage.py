"""Tests for the event-sourced KurrentDB memory storage prototype (#3796)."""

import pytest
from kurrentdbclient import NewEvent
from kurrentdbclient.exceptions import NotFoundError

from deerflow.agents.memory.storage import MemoryStorage
from deerflow.community.kurrentdb.memory_storage import (
    STREAM_PREFIX,
    KurrentdbMemoryStorage,
)

# NOTE: `import json` and `EVENT_TYPE` are added to this import block in Task 3,
# where they are first used — every task's commit must be ruff-clean (F401).


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
