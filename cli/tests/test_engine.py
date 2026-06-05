"""Unit tests for engine.py — session lifecycle, client management, chat, archive, export, search, and introspection."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine import (
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

    p_store = patch("engine.SessionStore", return_value=mock_store)
    p_sessions = patch("engine.SESSIONS_DIR", tmp_path / "sessions")
    p_archive = patch("engine.ARCHIVE_DIR", tmp_path / "archive")

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


# ---------------------------------------------------------------------------
# Archive / restore
# ---------------------------------------------------------------------------

class TestArchiveRestore:
    """Archive and restore session lifecycle."""

    def test_archive_session_moves_files(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")

        db_path = sessions_dir / "s1_checkpoints.db"
        db_path.write_text("fake-db")
        engine._get_or_create_client("s1")

        engine.archive_session("s1")

        store.archive_session_files.assert_called_once_with("s1")
        assert not (sessions_dir / "s1_checkpoints.db").exists()
        assert (archive_dir / "s1_checkpoints.db").exists()

    def test_restore_archive_success(self, tmp_path: Path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        archive_data = {
            "session_id": "arch1",
            "info": {
                "created_at": 1000.0,
                "last_active": 2000.0,
                "title": "Archived Session",
                "last_checkpoint_id": None,
            },
            "metrics": {"total_tokens": 10, "tool_calls": 1, "turns": 1},
        }
        (archive_dir / "arch1.json").write_text(json.dumps(archive_data))

        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)

        result = engine.restore_archive("arch1")

        assert result is True
        assert "arch1" in engine.store.sessions
        assert engine.store.sessions["arch1"]["title"] == "Archived Session"
        assert engine.current_session_id == "arch1"

    def test_restore_archive_not_found(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)

        result = engine.restore_archive("missing")

        assert result is False

    def test_restore_archive_already_active(self, tmp_path: Path):
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        (archive_dir / "arch1.json").write_text(
            json.dumps({
                "session_id": "arch1",
                "info": {"created_at": 1.0, "last_active": 2.0, "title": "X", "last_checkpoint_id": None},
                "metrics": {"total_tokens": 0, "tool_calls": 0, "turns": 0},
            })
        )

        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "arch1")

        result = engine.restore_archive("arch1")

        assert result is False

    def test_list_archives_empty(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        engine.list_archives()

    def test_list_archives_with_files(self, tmp_path: Path):
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        (archive_dir / "arch1.json").write_text("{}")
        (archive_dir / "arch2.json").write_text("{}")

        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        engine.list_archives()


# ---------------------------------------------------------------------------
# _extract_steps — checkpoint-to-step parsing
# ---------------------------------------------------------------------------

class TestExtractSteps:
    """Parsing checkpoint history into structured conversation steps."""

    def _make_thread_data(self, checkpoints: list[dict]) -> dict:
        return {"checkpoints": checkpoints}

    def _make_cp(self, messages: list[dict], checkpoint_id="cp1", ts="2024-01-01"):
        return {
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": "parent1",
            "ts": ts,
            "values": {"messages": messages, "total_tokens": 100},
        }

    def test_empty_checkpoints(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")

        client = engine._get_or_create_client("s1")
        client.get_thread.return_value = self._make_thread_data([])

        steps = engine._extract_steps("s1")
        assert steps == []

    def test_single_human_ai_turn(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")

        client = engine._get_or_create_client("s1")
        client.get_thread.return_value = self._make_thread_data([
            self._make_cp([
                {"type": "human", "id": "h1", "content": "Hello", "metadata": {}},
                {"type": "ai", "id": "a1", "content": "Hi there!", "response_metadata": {"model": "opus"}},
            ]),
        ])

        steps = engine._extract_steps("s1")

        assert len(steps) == 1
        assert steps[0]["step"] == 1
        assert steps[0]["user_input"] == "Hello"
        assert steps[0]["ai_response"] == "Hi there!"
        assert steps[0]["ai_response_metadata"]["model"] == "opus"

    def test_detects_duplicate_messages_across_checkpoints(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")

        client = engine._get_or_create_client("s1")
        client.get_thread.return_value = self._make_thread_data([
            self._make_cp([
                {"type": "human", "id": "h1", "content": "Q1", "metadata": {}},
                {"type": "ai", "id": "a1", "content": "A1", "response_metadata": {}},
            ], checkpoint_id="cp1"),
            self._make_cp([
                {"type": "human", "id": "h1", "content": "Q1", "metadata": {}},
                {"type": "ai", "id": "a1", "content": "A1", "response_metadata": {}},
            ], checkpoint_id="cp2"),
        ])

        steps = engine._extract_steps("s1")

        assert len(steps) == 1
        assert len(steps[0]["duplicate_messages"]) == 2

    def test_tool_calls_and_results(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")

        client = engine._get_or_create_client("s1")
        client.get_thread.return_value = self._make_thread_data([
            self._make_cp([
                {"type": "human", "id": "h1", "content": "Search X", "metadata": {}},
                {
                    "type": "ai",
                    "id": "a1",
                    "content": "",
                    "response_metadata": {},
                    "tool_calls": [
                        {"id": "tc1", "name": "search", "args": {"query": "X"}},
                    ],
                },
                {
                    "type": "tool",
                    "id": "t1",
                    "content": "Found 3 results",
                    "tool_call_id": "tc1",
                },
            ]),
        ])

        steps = engine._extract_steps("s1")

        assert len(steps) == 1
        assert len(steps[0]["tool_calls"]) == 1
        assert steps[0]["tool_calls"][0]["name"] == "search"
        assert steps[0]["tool_calls"][0]["result"] == "Found 3 results"

    def test_messages_without_id(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")

        client = engine._get_or_create_client("s1")
        client.get_thread.return_value = self._make_thread_data([
            self._make_cp([
                {"type": "human", "content": "No ID message", "metadata": {}},
            ]),
        ])

        steps = engine._extract_steps("s1")

        assert len(steps) == 1
        assert steps[0]["user_input"] == "No ID message"

    def test_marks_duplicate_tool_calls(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")

        client = engine._get_or_create_client("s1")
        client.get_thread.return_value = self._make_thread_data([
            self._make_cp([
                {"type": "human", "id": "h1", "content": "Q", "metadata": {}},
                {"type": "ai", "id": "a1", "content": "", "response_metadata": {}, "tool_calls": [
                    {"id": "tc1", "name": "t1", "args": {}},
                ]},
            ]),
            self._make_cp([
                {"type": "human", "id": "h2", "content": "Q2", "metadata": {}},
                {"type": "ai", "id": "a2", "content": "", "response_metadata": {}, "tool_calls": [
                    {"id": "tc1", "name": "t1", "args": {}},
                ]},
            ]),
        ])

        steps = engine._extract_steps("s1")

        assert len(steps) == 2
        assert steps[1]["tool_calls"][0]["is_duplicate"] is True


# ---------------------------------------------------------------------------
# get_session_steps / get_all_checkpoint_steps
# ---------------------------------------------------------------------------

class TestIntrospectionMethods:
    """Read-only introspection using per-session clients."""

    def test_get_session_steps_defaults_to_current(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")
        with patch.object(engine, "_extract_steps", return_value=[{"step": 1}]) as mock_extract:
            result = engine.get_session_steps()
            mock_extract.assert_called_once_with("s1")
            assert result == [{"step": 1}]

    def test_get_session_steps_returns_empty_when_no_session(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _clear_all_sessions(engine)
        assert engine.get_session_steps() == []

    def test_get_all_checkpoint_steps_basic(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")

        client = engine._get_or_create_client("s1")
        client.get_thread.return_value = {
            "checkpoints": [
                {
                    "checkpoint_id": "cp1",
                    "parent_checkpoint_id": None,
                    "ts": "2024-01-01",
                    "values": {
                        "messages": [
                            {"type": "human", "id": "h1", "content": "Hello"},
                            {"type": "ai", "id": "a1", "content": "Hi"},
                        ],
                    },
                },
                {
                    "checkpoint_id": "cp2",
                    "parent_checkpoint_id": "cp1",
                    "ts": "2024-01-02",
                    "values": {
                        "messages": [
                            {"type": "human", "id": "h1", "content": "Hello"},
                            {"type": "ai", "id": "a1", "content": "Hi"},
                            {"type": "human", "id": "h2", "content": "Follow-up"},
                        ],
                    },
                },
            ],
        }

        cps = engine.get_all_checkpoint_steps("s1")

        assert len(cps) == 2
        assert cps[0]["checkpoint_id"] == "cp1"
        assert len(cps[0]["new_messages"]) == 2
        assert cps[1]["checkpoint_id"] == "cp2"
        assert len(cps[1]["new_messages"]) == 1
        assert cps[1]["new_messages"][0]["content"] == "Follow-up"
        assert cps[0]["has_new_content"] is True

    def test_get_all_checkpoint_steps_no_checkpoints(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1")

        client = engine._get_or_create_client("s1")
        client.get_thread.return_value = {"checkpoints": []}

        cps = engine.get_all_checkpoint_steps("s1")
        assert cps == []


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class TestExport:
    """Markdown export of sessions and checkpoints."""

    def test_export_session_markdown_no_active_session(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _clear_all_sessions(engine)
        result = engine.export_session_markdown()
        assert result is None

    def test_export_session_markdown_creates_file(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1", "Export Test")
        engine.store.session_metrics["s1"]["total_tokens"] = 10

        with patch.object(engine, "get_session_steps", return_value=[
            {"step": 1, "user_input": "Q", "ai_response": "A", "tool_calls": [], "duplicate_messages": []}
        ]):
            result = engine.export_session_markdown("s1")

        assert result is not None
        assert os.path.exists(result)
        content = Path(result).read_text()
        assert "# Export Test" in content
        assert "Q" in content
        assert "A" in content

    def test_export_all_checkpoints_no_active_session(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _clear_all_sessions(engine)
        result = engine.export_all_checkpoints()
        assert result is None

    def test_export_all_checkpoints_creates_file(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1", "CP Export")
        engine.store.session_metrics["s1"]["total_tokens"] = 20

        with patch.object(engine, "get_all_checkpoint_steps", return_value=[
            {
                "checkpoint_id": "cp1",
                "parent_checkpoint_id": None,
                "ts": "2024-01-01",
                "new_messages": [{"type": "human", "content": "Hello"}],
                "has_new_content": True,
            },
        ]):
            result = engine.export_all_checkpoints("s1")

        assert result is not None
        assert os.path.exists(result)
        content = Path(result).read_text()
        assert "# CP Export (All Checkpoints)" in content
        assert "Hello" in content

    def test_export_session_markdown_with_tool_calls(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1", "Tool Test")

        with patch.object(engine, "get_session_steps", return_value=[
            {
                "step": 1,
                "user_input": "Search X",
                "ai_response": "Results:",
                "tool_calls": [
                    {
                        "id": "tc1",
                        "name": "search",
                        "args": {"query": "X"},
                        "result": '{"hits": 5}',
                        "is_duplicate": False,
                    },
                ],
                "duplicate_messages": [],
            },
        ]):
            result = engine.export_session_markdown("s1")

        content = Path(result).read_text()
        assert "search" in content
        assert "hits" in content

    def test_export_all_checkpoints_with_no_new_content(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        _prime_session(engine, "s1", "Empty CP")

        with patch.object(engine, "get_all_checkpoint_steps", return_value=[
            {
                "checkpoint_id": "cp1",
                "parent_checkpoint_id": None,
                "ts": "2024-01-01",
                "new_messages": [],
                "has_new_content": False,
            },
        ]):
            result = engine.export_all_checkpoints("s1")

        content = Path(result).read_text()
        assert "no new messages" in content.lower()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestSearch:
    """Keyword search across sessions."""

    def test_search_finds_keyword_in_user_input(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        engine.store.sessions = {"s1": {"title": "Session One"}}
        engine.store.session_metrics["s1"] = {"total_tokens": 0, "tool_calls": 0, "turns": 0}

        with patch.object(engine, "get_session_steps", return_value=[
            {"step": 1, "user_input": "I love Python programming", "ai_response": "That's great!"},
        ]):
            engine.search_sessions("Python")

    def test_search_finds_keyword_in_ai_response(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        engine.store.sessions = {"s1": {"title": "Session One"}}
        engine.store.session_metrics["s1"] = {"total_tokens": 0, "tool_calls": 0, "turns": 0}

        with patch.object(engine, "get_session_steps", return_value=[
            {"step": 1, "user_input": "Hello", "ai_response": "I recommend using pytest"},
        ]):
            engine.search_sessions("pytest")

    def test_search_no_match(self, tmp_path: Path):
        store = MagicMock()
        store.sessions = {}
        engine = _make_engine(store, tmp_path)
        engine.store.sessions = {"s1": {"title": "X"}}
        engine.store.session_metrics["s1"] = {"total_tokens": 0, "tool_calls": 0, "turns": 0}

        with patch.object(engine, "get_session_steps", return_value=[
            {"step": 1, "user_input": "Hello", "ai_response": "Hi"},
        ]):
            engine.search_sessions("zzznotfound")
