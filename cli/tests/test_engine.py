"""Unit tests for engine.py — session lifecycle, client management, and chat."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deerflow_cli.engine import (
    SESSIONS_DIR,
    ARCHIVE_DIR,
    DeerFlowProductionEngine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_engine_singleton():
    """Destroy the singleton state and stop any active patches between tests."""
    yield
    instance = DeerFlowProductionEngine._instance
    if instance is not None and hasattr(instance, "_patchers"):
        for p in reversed(instance._patchers):
            p.stop()
    DeerFlowProductionEngine._instance = None
    DeerFlowProductionEngine._initialized = False


def _make_engine(mock_store, tmp_path: Path) -> DeerFlowProductionEngine:
    """Construct an engine with SessionStore patched and dirs redirected."""
    mock_store.sessions = {}
    mock_store.session_metrics = {}
    mock_store.save_async = MagicMock()
    mock_store.delete_session_files = MagicMock()
    mock_store.archive_session_files = MagicMock()
    mock_store.shutdown = MagicMock()
    DeerFlowProductionEngine._instance = None
    DeerFlowProductionEngine._initialized = False

    p_store = patch("deerflow_cli.engine.SessionStore", return_value=mock_store)
    p_sessions = patch("deerflow_cli.engine.SESSIONS_DIR", tmp_path / "sessions")
    p_archive = patch("deerflow_cli.engine.ARCHIVE_DIR", tmp_path / "archive")

    p_store.start()
    p_sessions.start()
    p_archive.start()

    engine = DeerFlowProductionEngine()
    engine._patchers = [p_store, p_sessions, p_archive]
    return engine


def _clear_all_sessions(engine: DeerFlowProductionEngine):
    """Remove the default session auto-created by __init__."""
    engine.current_session_id = None
    engine.store.sessions.clear()
    engine.store.session_metrics.clear()
    engine._clients.clear()
    engine._checkpointer_cms.clear()
    engine._checkpointers.clear()


def _prime_session(engine: DeerFlowProductionEngine, sid="s1", title="Test"):
    """Register a session in the store and activate it."""
    engine.store.sessions[sid] = {
        "created_at": time.time(),
        "last_active": time.time(),
        "title": title,
        "last_checkpoint_id": None,
    }
    engine.store.session_metrics[sid] = {"total_tokens": 0, "tool_calls": 0, "turns": 0}
    engine.current_session_id = sid


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    """DeerFlowProductionEngine must behave as a singleton."""

    def test_same_instance_returned(self):
        a = DeerFlowProductionEngine()
        b = DeerFlowProductionEngine()
        assert a is b

    def test_init_guards_against_reinit(self):
        engine = DeerFlowProductionEngine()
        original_store = engine.store
        engine.__init__()
        assert engine.store is original_store


# ---------------------------------------------------------------------------
# _get_or_create_client — per-session client setup
# ---------------------------------------------------------------------------

class TestGetOrCreateClient:
    """Client creation and reuse for session isolation."""

    def test_creates_new_client_for_unknown_session(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")

        client = engine._get_or_create_client("s1")

        assert "s1" in engine._clients
        assert engine._clients["s1"] is client

    def test_reuses_existing_client(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")

        c1 = engine._get_or_create_client("s1")
        c2 = engine._get_or_create_client("s1")

        assert c1 is c2

    def test_each_session_gets_own_client(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")
        _prime_session(engine, "s2")

        c1 = engine._get_or_create_client("s1")
        c2 = engine._get_or_create_client("s2")

        assert c1 is not c2
        assert "s1" in engine._clients
        assert "s2" in engine._clients

    def test_applies_runtime_settings_to_new_client(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")
        engine._runtime_settings["model_name"] = "opus"
        engine._runtime_settings["plan_mode"] = True
        engine._runtime_settings["thinking_enabled"] = False

        client = engine._get_or_create_client("s1")

        assert client._model_name == "opus"
        assert client._plan_mode is True
        assert client._thinking_enabled is False

    def test_does_not_reapply_settings_to_existing_client(self, tmp_path: Path):
        """Settings are only applied on first creation, not on reuse."""
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")

        engine._runtime_settings["model_name"] = "opus"
        c1 = engine._get_or_create_client("s1")

        engine._runtime_settings["model_name"] = "sonnet"
        c2 = engine._get_or_create_client("s1")

        assert c1 is c2
        assert c1._model_name == "opus"


# ---------------------------------------------------------------------------
# client property
# ---------------------------------------------------------------------------

class TestClientProperty:
    """The client property returns the current session's client."""

    def test_returns_none_when_no_current_session(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _clear_all_sessions(engine)
        assert engine.client is None

    def test_returns_client_for_current_session(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")
        engine._get_or_create_client("s1")
        assert engine.client is engine._clients["s1"]

    def test_returns_none_when_session_has_no_client(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        engine.current_session_id = "orphan"
        assert engine.client is None


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

class TestSessionLifecycle:
    """CRUD operations on sessions."""

    def test_create_session_assigns_uuid(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        sid = engine.create_session()
        assert len(sid) == 32
        assert sid in engine.store.sessions

    def test_create_session_with_custom_id(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        sid = engine.create_session(session_id="my-session-42", title="Custom")
        assert sid == "my-session-42"
        assert engine.store.sessions["my-session-42"]["title"] == "Custom"

    def test_create_session_rejects_invalid_id(self, tmp_path: Path):
        """Non-alphanumeric-underscore-dash IDs are replaced with uuid."""
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        sid = engine.create_session(session_id="bad id!")
        assert sid != "bad id!"
        assert len(sid) == 32

    def test_create_session_duplicate_id_returns_same(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        sid = engine.create_session(session_id="dup", title="First")
        sid2 = engine.create_session(session_id="dup", title="Second")
        assert sid == sid2
        assert engine.store.sessions["dup"]["title"] == "First"

    def test_switch_session_success(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")
        _prime_session(engine, "s2")

        result = engine.switch_session("s2")

        assert result is True
        assert engine.current_session_id == "s2"

    def test_switch_session_not_found(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")

        result = engine.switch_session("nonexistent")

        assert result is False
        assert engine.current_session_id == "s1"

    def test_switch_session_updates_last_active(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")
        _prime_session(engine, "s2")
        old_active = engine.store.sessions["s2"]["last_active"]

        engine.switch_session("s2")

        assert engine.store.sessions["s2"]["last_active"] > old_active

    def test_delete_session_removes_everything(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _clear_all_sessions(engine)
        _prime_session(engine, "s1")

        engine._get_or_create_client("s1")

        def _delete(sid):
            engine.store.sessions.pop(sid, None)
        store.delete_session_files.side_effect = _delete

        engine.delete_session("s1")

        assert "s1" not in engine.store.sessions
        assert engine.current_session_id is not None
        assert engine.current_session_id != "s1"
        store.delete_session_files.assert_called_once_with("s1")

    def test_delete_session_not_found(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")

        result = engine.delete_session("nonexistent")

        assert result is False
        assert "s1" in engine.store.sessions

    def test_rename_session_success(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1", "Old")

        result = engine.rename_session("s1", "New Title")

        assert result is True
        assert engine.store.sessions["s1"]["title"] == "New Title"
        store.save_async.assert_called_with("s1")

    def test_rename_session_not_found(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        result = engine.rename_session("ghost", "Nope")
        assert result is False


# ---------------------------------------------------------------------------
# _ensure_current_session
# ---------------------------------------------------------------------------

class TestEnsureCurrentSession:
    """Automatic recovery when current_session_id becomes invalid."""

    def test_falls_back_to_first_session(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _clear_all_sessions(engine)
        _prime_session(engine, "s1")
        _prime_session(engine, "s2")
        engine.current_session_id = "orphan"

        engine._ensure_current_session()

        assert engine.current_session_id == "s1"

    def test_creates_default_when_store_empty(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _clear_all_sessions(engine)
        engine.current_session_id = None

        engine._ensure_current_session()

        assert engine.current_session_id is not None
        assert engine.current_session_id in engine.store.sessions


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class TestChat:
    """Streaming chat and metrics tracking."""

    def test_chat_creates_session_when_none_active(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _clear_all_sessions(engine)
        with patch.object(engine, "create_session", wraps=engine.create_session) as spy:
            list(engine.chat("hello"))
            spy.assert_called_once()

    def test_chat_streams_response_chunks(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")

        from types import SimpleNamespace

        client = engine._get_or_create_client("s1")
        Event = SimpleNamespace
        client.stream.return_value = iter([
            Event(type="messages-tuple", data={"type": "ai", "content": "Hello"}),
            Event(type="messages-tuple", data={"type": "ai", "content": " world"}),
            Event(type="end", data={"usage": {"total_tokens": 50}}),
        ])
        client.get_thread.return_value = {"checkpoints": [{"checkpoint_id": "cp1"}]}

        chunks = list(engine.chat("Hi"))

        assert "Hello" in chunks
        assert " world" in chunks
        assert any("50" in c for c in chunks if isinstance(c, str))

    def test_chat_increments_metrics(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")
        engine.store.session_metrics["s1"]["turns"] = 0
        engine.store.session_metrics["s1"]["total_tokens"] = 0

        from types import SimpleNamespace

        client = engine._get_or_create_client("s1")
        Event = SimpleNamespace
        client.stream.return_value = iter([
            Event(type="messages-tuple", data={"type": "ai", "content": "A"}),
            Event(type="messages-tuple", data={"type": "ai", "content": "B", "tool_calls": [{"id": "t1"}]}),
            Event(type="end", data={"usage": {"total_tokens": 30}}),
        ])
        client.get_thread.return_value = {"checkpoints": [{"checkpoint_id": "cp1"}]}

        list(engine.chat("Q"))

        assert engine.store.session_metrics["s1"]["turns"] == 1
        assert engine.store.session_metrics["s1"]["total_tokens"] == 30
        assert engine.store.session_metrics["s1"]["tool_calls"] == 1

    def test_chat_updates_title_on_first_turn(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1", "New Session")

        from types import SimpleNamespace

        client = engine._get_or_create_client("s1")
        Event = SimpleNamespace
        client.stream.return_value = iter([
            Event(type="messages-tuple", data={"type": "ai", "content": "A long response about weather"}),
            Event(type="end", data={"usage": {"total_tokens": 10}}),
        ])
        client.get_thread.return_value = {"checkpoints": [{"checkpoint_id": "cp1"}]}

        list(engine.chat("What is the weather today?"))

        assert engine.store.sessions["s1"]["title"] == "What is the weather today?"

    def test_chat_does_not_overwrite_custom_title(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1", "My Custom Title")

        from types import SimpleNamespace

        client = engine._get_or_create_client("s1")
        Event = SimpleNamespace
        client.stream.return_value = iter([
            Event(type="messages-tuple", data={"type": "ai", "content": "OK"}),
            Event(type="end", data={"usage": {"total_tokens": 5}}),
        ])
        client.get_thread.return_value = {"checkpoints": [{"checkpoint_id": "cp1"}]}

        list(engine.chat("Another message"))

        assert engine.store.sessions["s1"]["title"] == "My Custom Title"

    def test_runtime_settings_persisted_across_sessions(self, tmp_path: Path):
        """Settings survive across session switches because _runtime_settings
        is applied to each new client."""
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")
        engine._get_or_create_client("s1")

        engine._runtime_settings["model_name"] = "haiku"
        engine._runtime_settings["plan_mode"] = True

        _prime_session(engine, "s2")
        client2 = engine._get_or_create_client("s2")

        assert client2._model_name == "haiku"
        assert client2._plan_mode is True


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

class TestShutdown:
    """Graceful shutdown releases all resources."""

    def test_shutdown_calls_store_shutdown(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        engine.shutdown()
        store.shutdown.assert_called_once()

    def test_shutdown_destroys_all_clients(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")
        _prime_session(engine, "s2")
        engine._get_or_create_client("s1")
        engine._get_or_create_client("s2")

        engine.shutdown()

        assert "s1" not in engine._clients
        assert "s2" not in engine._clients
        assert "s1" not in engine._checkpointer_cms
        assert "s2" not in engine._checkpointer_cms


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------

class TestListing:
    """List sessions (output-only, no return value)."""

    def test_list_sessions(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1", "First")
        _prime_session(engine, "s2", "Second")
        engine.list_sessions()
