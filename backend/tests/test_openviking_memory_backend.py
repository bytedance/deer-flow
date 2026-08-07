"""Tests for the official-package OpenViking memory backend."""

from __future__ import annotations

import copy
import gc
import json
import threading
import weakref
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.openviking.config import OpenVikingConfig
from deerflow.agents.memory.backends.openviking.openviking_manager import (
    OpenVikingMemoryManager,
    _canonical_peer_id,
    _session_id,
)
from deerflow.agents.memory.manager import (
    MemoryManagerError,
    _scan_backends,
    reset_memory_manager,
)


class _CommitPolicy:
    def __init__(self, *, mode: str, pending_token_threshold: int = 8_000):
        self.mode = mode
        self.pending_token_threshold = pending_token_threshold


class _PartialWriteError(RuntimeError):
    def __init__(
        self,
        consumed: int,
        *,
        commit_pending: bool = False,
    ) -> None:
        super().__init__("partial")
        self.input_messages_consumed = consumed
        self.commit_pending = commit_pending


class _Client:
    supports_request_actor_peer = True

    def __init__(self, **kwargs: Any):
        self.kwargs = kwargs
        self.closed = False
        self.healthy = True

    def health(self) -> bool:
        return self.healthy

    def close(self) -> None:
        self.closed = True


class _Recorder:
    def __init__(
        self,
        *,
        commit_policy: _CommitPolicy,
        url: str,
        api_key: str,
        timeout: float,
        extra_headers: dict[str, str],
    ) -> None:
        self.commit_policy = commit_policy
        self.connection = {
            "url": url,
            "api_key": api_key,
            "timeout": timeout,
            "extra_headers": extra_headers,
        }
        self._client = _Client(**self.connection)
        self.calls: list[tuple[str, list[Any], str | None, str | None]] = []
        self.flushes: list[tuple[str, str | None]] = []
        self.failures: list[BaseException] = []
        self.closed = False

    @property
    def client(self) -> _Client:
        return self._client

    def record(
        self,
        session_id: str,
        messages: list[Any],
        peer_id: str | None = None,
    ) -> object:
        self.calls.append((session_id, list(messages), peer_id, _ACTOR_PEER.get()))
        if self.failures:
            raise self.failures.pop(0)
        return object()

    def flush(self, session_id: str) -> None:
        self.flushes.append((session_id, _ACTOR_PEER.get()))
        if self.failures:
            raise self.failures.pop(0)

    def close(self) -> None:
        self.closed = True
        self._client.close()


class _Retriever:
    def __init__(self, *, client: _Client, **kwargs: Any):
        self.client = client
        self.kwargs = kwargs
        self.limit = kwargs["limit"]
        self.filter = None
        self.session_id = kwargs.get("session_id")
        self.target_uri = kwargs.get("target_uri", "")
        self.calls: list[dict[str, Any]] = []

    def __copy__(self) -> _Retriever:
        copied = type(self)(client=self.client, **self.kwargs)
        copied.calls = self.calls
        copied.limit = self.limit
        copied.filter = copy.deepcopy(self.filter)
        copied.session_id = self.session_id
        copied.target_uri = copy.deepcopy(self.target_uri)
        return copied

    def invoke(self, query: str) -> list[Document]:
        self.calls.append(
            {
                "query": query,
                "actor_peer": _ACTOR_PEER.get(),
                "limit": self.limit,
                "filter": copy.deepcopy(self.filter),
                "session_id": self.session_id,
                "target_uri": copy.deepcopy(self.target_uri),
                "search_mode": getattr(self, "search_mode", "find"),
            }
        )
        return [
            Document(
                page_content="Prefers concise answers.",
                metadata={
                    "openviking_uri": ("viking://user/memories/preferences/style.md"),
                    "openviking_category": "preferences",
                    "openviking_score": 0.91,
                },
            )
        ]


_ACTOR_PEER: ContextVar[str | None] = ContextVar(
    "test_actor_peer",
    default=None,
)


@contextmanager
def _use_actor_peer(peer_id: str | None):
    token = _ACTOR_PEER.set(peer_id)
    try:
        yield
    finally:
        _ACTOR_PEER.reset(token)


@pytest.fixture
def official_integration(monkeypatch: pytest.MonkeyPatch) -> None:
    import deerflow.agents.memory.backends.openviking.openviking_manager as module

    monkeypatch.setattr(
        module,
        "_load_official_integration",
        lambda: {
            "OpenVikingCommitPolicy": _CommitPolicy,
            "OpenVikingPartialWriteError": _PartialWriteError,
            "OpenVikingRetriever": _Retriever,
            "OpenVikingSessionRecorder": _Recorder,
            "use_actor_peer": _use_actor_peer,
        },
    )


def _backend_config(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "base_url": "http://openviking:1933",
        "storage_path": str(tmp_path),
        "owner_user_id": "alice",
        "startup_policy": "warn",
        "retrieval": {
            "top_k": 4,
            "max_injection_chars": 1_000,
            "injection_query": "profile preferences and prior decisions",
        },
    }
    config.update(overrides)
    return config


def _manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    **overrides: Any,
) -> OpenVikingMemoryManager:
    monkeypatch.setenv("OPENVIKING_API_KEY", "user-key")
    return OpenVikingMemoryManager.from_config(_backend_config(tmp_path, **overrides))


def test_config_uses_single_user_key_and_rejects_legacy_trusted_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENVIKING_API_KEY", raising=False)
    with pytest.raises(ValueError, match="USER API key"):
        OpenVikingConfig.from_backend_config(_backend_config(tmp_path))

    monkeypatch.setenv("OPENVIKING_API_KEY", "secret")
    config = OpenVikingConfig.from_backend_config(_backend_config(tmp_path))

    assert config.owner_user_id == "alice"
    assert config.content_mode == "overview"
    assert config.injection_query == "profile preferences and prior decisions"
    assert "secret" not in repr(config)

    with pytest.raises(ValueError, match="trusted mode is no longer supported"):
        OpenVikingConfig.from_backend_config(_backend_config(tmp_path, auth_mode="trusted"))
    with pytest.raises(ValueError, match="Unknown OpenViking"):
        OpenVikingConfig.from_backend_config(_backend_config(tmp_path, typo=True))
    with pytest.raises(ValueError, match="reserved prefix"):
        OpenVikingConfig.from_backend_config(_backend_config(tmp_path, default_peer_id="df-agent-default"))
    with pytest.raises(ValueError, match="custom HTTP client fields"):
        OpenVikingConfig.from_backend_config(_backend_config(tmp_path, max_connections=10))


def test_backend_is_discovered_by_registered_name() -> None:
    reset_memory_manager()
    assert _scan_backends()["openviking"] is OpenVikingMemoryManager


def test_official_loader_uses_standalone_package() -> None:
    from deerflow.agents.memory.backends.openviking.openviking_manager import (
        _load_official_integration,
    )

    integration = _load_official_integration()

    assert integration["OpenVikingSessionRecorder"].__module__.startswith("langchain_openviking")
    assert integration["OpenVikingRetriever"].__module__.startswith("langchain_openviking")


def test_manager_uses_official_recorder_retriever_and_commit_always(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)

    assert manager._recorder.commit_policy.mode == "always"
    assert manager._retriever.client is manager._recorder.client
    assert manager._retriever.kwargs["content_mode"] == "overview"
    assert manager._recorder.connection == {
        "url": "http://openviking:1933",
        "api_key": "user-key",
        "timeout": 30.0,
        "extra_headers": {},
    }


def test_context_preserves_existing_fixed_query_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)

    context = manager.get_context(
        "alice",
        agent_name="research",
        thread_id="thread-1",
    )

    assert context == "- [preferences] Prefers concise answers."
    assert manager._retriever.calls == [
        {
            "query": "profile preferences and prior decisions",
            "actor_peer": "research",
            "limit": 4,
            "filter": None,
            "session_id": _session_id("alice", "research", "thread-1"),
            "target_uri": [
                "viking://user/memories",
                "viking://user/peers/research/memories",
            ],
            "search_mode": "search",
        }
    ]


def test_context_without_thread_uses_existing_find_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)

    context = manager.get_context(
        "alice",
        agent_name="research",
    )

    assert context == "- [preferences] Prefers concise answers."
    assert manager._retriever.calls == [
        {
            "query": "profile preferences and prior decisions",
            "actor_peer": "research",
            "limit": 4,
            "filter": None,
            "session_id": None,
            "target_uri": [
                "viking://user/memories",
                "viking://user/peers/research/memories",
            ],
            "search_mode": "find",
        }
    ]


def test_manager_refuses_to_share_single_user_key_across_deerflow_users(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)

    with pytest.raises(MemoryManagerError, match="owner_user_id 'alice'"):
        manager.get_context("bob", agent_name="research")
    with pytest.raises(MemoryManagerError, match="owner_user_id 'alice'"):
        manager.add(
            "thread-1",
            [HumanMessage("private", id="h1")],
            user_id="bob",
            agent_name="research",
        )

    assert manager._retriever.calls == []
    assert manager._recorder.calls == []


def test_manager_records_only_unseen_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    messages = [
        HumanMessage("Remember Vim.", id="h1"),
        AIMessage("I will remember.", id="a1"),
    ]

    manager.add(
        "thread-1",
        messages,
        user_id="alice",
        agent_name="research",
    )
    manager.add(
        "thread-1",
        messages,
        user_id="alice",
        agent_name="research",
    )
    messages.append(HumanMessage("Also concise.", id="h2"))
    manager.add(
        "thread-1",
        messages,
        user_id="alice",
        agent_name="research",
    )

    assert len(manager._recorder.calls) == 2
    assert manager._recorder.calls[0][1] == messages[:2]
    assert manager._recorder.calls[1][1] == messages[2:]
    assert all(call[2:] == ("research", "research") for call in manager._recorder.calls)


def test_partial_write_progress_is_not_resubmitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    messages = [
        HumanMessage("one", id="h1"),
        AIMessage("two", id="a1"),
        HumanMessage("three", id="h2"),
    ]
    manager._recorder.failures.append(_PartialWriteError(2))

    manager.add(
        "thread-1",
        messages,
        user_id="alice",
        agent_name="research",
    )
    manager.add(
        "thread-1",
        messages,
        user_id="alice",
        agent_name="research",
    )

    assert manager._recorder.calls[0][1] == messages
    assert manager._recorder.calls[1][1] == messages[2:]


def test_pending_commit_is_retried_without_resubmitting_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    messages = [HumanMessage("one", id="h1"), AIMessage("two", id="a1")]
    manager._recorder.failures.append(_PartialWriteError(len(messages), commit_pending=True))

    manager.add(
        "thread-1",
        messages,
        user_id="alice",
        agent_name="research",
    )
    manager.add(
        "thread-1",
        messages,
        user_id="alice",
        agent_name="research",
    )

    session_id = _session_id("alice", "research", "thread-1")
    assert manager._recorder.flushes == [(session_id, "research")]
    assert len(manager._recorder.calls) == 1


def test_search_maps_documents_without_custom_http_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)

    results = manager.search(
        "answer style",
        top_k=3,
        user_id="alice",
        agent_name="research",
        category="preferences",
    )

    assert results == [
        {
            "id": "viking://user/memories/preferences/style.md",
            "content": "Prefers concise answers.",
            "category": "preferences",
            "confidence": 0.91,
            "source": "viking://user/memories/preferences/style.md",
            "score": 0.91,
        }
    ]
    assert manager._retriever.calls[0]["filter"] == {
        "op": "must",
        "field": "category",
        "conds": ["preferences"],
    }
    assert manager._retriever.calls[0]["search_mode"] == "find"


def test_capture_keeps_tool_history_but_drops_hidden_injected_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    messages = [
        HumanMessage("question", id="h1"),
        AIMessage(
            "",
            id="a-tool",
            tool_calls=[
                {
                    "name": "search",
                    "args": {"query": "OpenViking"},
                    "id": "call-1",
                    "type": "tool_call",
                }
            ],
        ),
        HumanMessage(
            "injected memory",
            id="hidden",
            additional_kwargs={"hide_from_ui": True},
        ),
        AIMessage("answer", id="a1"),
    ]

    manager.add(
        "thread-1",
        messages,
        user_id="alice",
        agent_name="research",
    )

    assert manager._recorder.calls[0][1] == [
        messages[0],
        messages[1],
        messages[3],
    ]


def test_compacted_history_rebases_without_replaying_known_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(
        tmp_path,
        monkeypatch,
        max_seen_message_ids=16,
    )
    messages = [HumanMessage(f"message {index}", id=f"h{index}") for index in range(20)]
    manager.add(
        "thread-1",
        messages,
        user_id="alice",
        agent_name="research",
    )
    compacted = [
        *messages[-8:],
        HumanMessage("new", id="h20"),
    ]

    manager.add(
        "thread-1",
        compacted,
        user_id="alice",
        agent_name="research",
    )

    assert manager._recorder.calls[1][1] == [compacted[-1]]


def test_failed_write_does_not_advance_capture_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    manager._recorder.failures.append(RuntimeError("unavailable"))
    messages = [HumanMessage("retry me", id="h1")]

    manager.add(
        "thread-1",
        messages,
        user_id="alice",
        agent_name="research",
    )
    manager.add(
        "thread-1",
        messages,
        user_id="alice",
        agent_name="research",
    )

    assert [call[1] for call in manager._recorder.calls] == [
        messages,
        messages,
    ]


def test_corrupt_cursor_fails_closed_instead_of_replaying_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    session_id = _session_id("alice", "research", "thread-1")
    cursor = manager._state_path(session_id)
    cursor.parent.mkdir(parents=True)
    cursor.write_text("not-json", encoding="utf-8")

    with pytest.raises(MemoryManagerError, match="refusing unsafe replay"):
        manager.add(
            "thread-1",
            [HumanMessage("private", id="h1")],
            user_id="alice",
            agent_name="research",
        )

    assert manager._recorder.calls == []


def test_peer_mapping_is_stable_and_namespaces_are_disjoint() -> None:
    assert _canonical_peer_id(None, "deerflow") == "deerflow"
    assert _canonical_peer_id("Research", "deerflow") == "research"
    assert _canonical_peer_id("deerflow", "deerflow").startswith("df-agent-")
    assert _canonical_peer_id("-research", "deerflow").startswith("df-agent-")
    assert _canonical_peer_id("df-agent-custom", "deerflow").startswith("df-agent-")
    assert (
        len(
            {
                _canonical_peer_id(None, "deerflow"),
                _canonical_peer_id("deerflow", "deerflow"),
                _canonical_peer_id("-research", "deerflow"),
                _canonical_peer_id("df-agent-custom", "deerflow"),
            }
        )
        == 4
    )


def test_session_locks_do_not_accumulate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    lock = manager._session_lock("session-1")
    lock_ref = weakref.ref(lock)

    assert len(manager._session_locks) == 1
    del lock
    gc.collect()

    assert lock_ref() is None
    assert len(manager._session_locks) == 0


def test_shutdown_uses_existing_manager_lifecycle_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)

    assert manager.shutdown_flush(1.0) is True
    assert manager._recorder.closed is True
    assert manager._recorder.client.closed is True
    assert manager.shutdown_flush(1.0) is True


def test_shutdown_timeout_closes_resources_after_active_write_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    started = threading.Event()
    release = threading.Event()
    original_record = manager._recorder.record

    def blocking_record(*args: Any, **kwargs: Any) -> object:
        started.set()
        assert release.wait(2.0)
        return original_record(*args, **kwargs)

    manager._recorder.record = blocking_record
    writer = threading.Thread(
        target=manager.add,
        args=("thread-1", [HumanMessage("hello", id="h1")]),
        kwargs={"user_id": "alice", "agent_name": "research"},
    )
    writer.start()
    assert started.wait(1.0)

    assert manager.shutdown_flush(0.0) is False
    assert manager._recorder.closed is False

    release.set()
    writer.join(2.0)

    assert not writer.is_alive()
    assert manager._recorder.closed is True
    assert manager._recorder.client.closed is True
    assert manager.shutdown_flush(1.0) is True


@pytest.mark.asyncio
async def test_async_operations_run_off_the_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    event_loop_thread = threading.get_ident()
    worker_threads: list[int] = []
    original_add = OpenVikingMemoryManager.add

    def recording_add(
        self: OpenVikingMemoryManager,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        worker_threads.append(threading.get_ident())
        original_add(self, *args, **kwargs)

    monkeypatch.setattr(OpenVikingMemoryManager, "add", recording_add)

    await manager.aadd(
        "thread-1",
        [HumanMessage("hello", id="h1")],
        user_id="alice",
        agent_name="research",
    )

    assert worker_threads
    assert worker_threads[0] != event_loop_thread


def test_capture_cursor_contains_no_message_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)

    manager.add(
        "thread-1",
        [HumanMessage("very private text", id="h1")],
        user_id="alice",
        agent_name="research",
    )

    cursor = next((tmp_path / "openviking" / "sessions").glob("*.json"))
    serialized = cursor.read_text(encoding="utf-8")
    state = json.loads(serialized)

    assert "very private text" not in serialized
    assert state["submitted_prefix_count"] == 1
