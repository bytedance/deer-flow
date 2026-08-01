from __future__ import annotations

import copy
import json
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from deerflow.agents.memory.backends.openviking import OpenVikingMemoryManager
from deerflow.agents.memory.backends.openviking.official_config import (
    OfficialOpenVikingConfig,
    is_legacy_openviking_config,
)
from deerflow.agents.memory.backends.openviking.official_manager import (
    OfficialOpenVikingMemoryManager,
)
from deerflow.agents.memory.manager import MemoryManagerError


class _CommitPolicy:
    def __init__(self, *, mode: str):
        self.mode = mode


class _PartialWriteError(RuntimeError):
    def __init__(self, consumed: int, *, commit_pending: bool = False):
        super().__init__("partial")
        self.input_messages_consumed = consumed
        self.commit_pending = commit_pending


class _Client:
    supports_request_actor_peer = True

    def __init__(self, **kwargs: Any):
        self.kwargs = kwargs
        self.initialized = False
        self.initialize_calls = 0
        self.closed = False

    def initialize(self) -> None:
        self.initialize_calls += 1
        self.initialized = True

    def health(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True


class _Recorder:
    def __init__(self, *, client: _Client, commit_policy: _CommitPolicy):
        self.client = client
        self.commit_policy = commit_policy
        self.calls: list[tuple[str, list[Any], str | None, str | None]] = []
        self.flushes: list[str] = []
        self.flush_actor_peers: list[str | None] = []
        self.failures: list[BaseException] = []
        self.closed = False

    def record(self, session_id: str, messages: list[Any], peer_id: str | None = None):
        self.calls.append((session_id, list(messages), peer_id, _ACTOR_PEER.get()))
        if self.failures:
            raise self.failures.pop(0)
        return object()

    def flush(self, session_id: str) -> None:
        self.flushes.append(session_id)
        self.flush_actor_peers.append(_ACTOR_PEER.get())
        if self.failures:
            raise self.failures.pop(0)

    def close(self) -> None:
        self.closed = True


class _Retriever:
    def __init__(self, *, client: _Client, **kwargs: Any):
        self.client = client
        self.kwargs = kwargs
        self.limit = kwargs["limit"]
        self.filter = None
        self.calls: list[tuple[str, str | None, int, Any]] = []
        self.closed = False

    def __copy__(self):
        copied = type(self)(client=self.client, **self.kwargs)
        copied.calls = self.calls
        copied.limit = self.limit
        copied.filter = copy.deepcopy(self.filter)
        return copied

    def invoke(self, query: str) -> list[Document]:
        self.calls.append((query, _ACTOR_PEER.get(), self.limit, self.filter))
        return [
            Document(
                page_content="Prefers concise answers.",
                metadata={
                    "openviking_uri": "viking://user/memories/preferences/style.md",
                    "openviking_category": "preferences",
                    "openviking_score": 0.91,
                },
            )
        ]

    async def aclose(self) -> None:
        self.closed = True


_ACTOR_PEER: ContextVar[str | None] = ContextVar("test_actor_peer", default=None)


@contextmanager
def _use_actor_peer(peer_id: str | None):
    token = _ACTOR_PEER.set(peer_id)
    try:
        yield
    finally:
        _ACTOR_PEER.reset(token)


@pytest.fixture
def official_integration(monkeypatch: pytest.MonkeyPatch):
    import deerflow.agents.memory.backends.openviking.official_manager as module

    monkeypatch.setattr(
        module,
        "_load_official_integration",
        lambda: {
            "SyncHTTPClient": _Client,
            "OpenVikingCommitPolicy": _CommitPolicy,
            "OpenVikingPartialWriteError": _PartialWriteError,
            "OpenVikingRetriever": _Retriever,
            "OpenVikingSessionRecorder": _Recorder,
            "use_actor_peer": _use_actor_peer,
        },
    )


def _config(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "base_url": "http://openviking:1933",
        "storage_path": str(tmp_path),
        "owner_user_id": "alice",
        "startup_policy": "warn",
        "retrieval": {"top_k": 4, "max_injection_chars": 1000},
    }
    config.update(overrides)
    return config


def _manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    **overrides: Any,
) -> OfficialOpenVikingMemoryManager:
    monkeypatch.setenv("OPENVIKING_API_KEY", "user-key")
    manager = OpenVikingMemoryManager.from_config(_config(tmp_path, **overrides))
    assert isinstance(manager, OfficialOpenVikingMemoryManager)
    return manager


def test_official_config_requires_user_key_and_rejects_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENVIKING_API_KEY", raising=False)
    with pytest.raises(ValueError, match="USER API key"):
        OfficialOpenVikingConfig.from_backend_config(_config(tmp_path))

    monkeypatch.setenv("OPENVIKING_API_KEY", "secret")
    parsed = OfficialOpenVikingConfig.from_backend_config(_config(tmp_path))
    assert parsed.owner_user_id == "alice"
    assert "secret" not in repr(parsed)
    with pytest.raises(ValueError, match="Unknown official"):
        OfficialOpenVikingConfig.from_backend_config(_config(tmp_path, typo=True))


def test_official_config_does_not_treat_false_string_as_insecure_http_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENVIKING_API_KEY", "secret")

    with pytest.raises(ValueError, match="plain HTTP"):
        OfficialOpenVikingConfig.from_backend_config(
            _config(
                tmp_path,
                base_url="http://memory.internal:1933",
                allow_insecure_http="false",
            )
        )


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"timeout_seconds": float("nan")}, "timeout_seconds"),
        ({"retrieval": {"score_threshold": float("nan")}}, "score_threshold"),
    ],
)
def test_official_config_rejects_non_finite_numbers(
    overrides: dict[str, Any],
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENVIKING_API_KEY", "secret")

    with pytest.raises(ValueError, match=message):
        OfficialOpenVikingConfig.from_backend_config(_config(tmp_path, **overrides))


@pytest.mark.parametrize("peer_id", ["UPPER", "contains space", "_reserved", "a" * 65])
def test_official_config_rejects_invalid_default_peer_id(
    peer_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENVIKING_API_KEY", "secret")

    with pytest.raises(ValueError, match="default_peer_id"):
        OfficialOpenVikingConfig.from_backend_config(_config(tmp_path, default_peer_id=peer_id))


@pytest.mark.parametrize(
    "legacy_field, value",
    [
        ("auth_mode", "trusted"),
        ("account", "deerflow"),
        ("max_connections", 100),
        ("allow_insecure_dev", True),
    ],
)
def test_legacy_selector_recognizes_custom_http_only_fields(
    legacy_field: str,
    value: Any,
) -> None:
    assert is_legacy_openviking_config({legacy_field: value}) is True


def test_legacy_selector_recognizes_nested_legacy_policy_fields() -> None:
    assert is_legacy_openviking_config({"retrieval": {"injection_query": "profile"}})
    assert is_legacy_openviking_config({"failure_policy": {"write": "log_and_drop"}})
    assert not is_legacy_openviking_config({"failure_policy": {"write": "fail_open"}})


def test_manager_shares_one_official_client_and_uses_query_aware_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)

    assert manager.context_refresh_policy == "turn"
    assert manager._recorder.client is manager._client
    assert manager._retriever.client is manager._client
    assert manager._recorder.commit_policy.mode == "always"
    assert manager._retriever.kwargs["context_types"] == ("memory",)
    assert manager._client.kwargs == {
        "url": "http://openviking:1933",
        "api_key": "user-key",
        "timeout": 30.0,
    }


def test_direct_use_lazily_initializes_shared_client_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)

    assert manager._client.initialized is False
    manager.get_context("alice", query="first")
    manager.add("thread-1", [HumanMessage("hello", id="h1")], user_id="alice")

    assert manager._client.initialized is True
    assert manager._client.initialize_calls == 1


def test_concurrent_direct_use_initializes_shared_client_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    original_initialize = manager._client.initialize
    initialize_started = threading.Event()
    release_initialize = threading.Event()

    def initialize() -> None:
        initialize_started.set()
        assert release_initialize.wait(2)
        original_initialize()

    manager._client.initialize = initialize
    threads = [
        threading.Thread(
            target=manager.get_context,
            args=("alice",),
            kwargs={"query": f"query-{index}"},
        )
        for index in range(4)
    ]
    for thread in threads:
        thread.start()
    assert initialize_started.wait(1)
    release_initialize.set()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()

    assert manager._client.initialize_calls == 1


def test_recall_is_query_aware_peer_scoped_and_user_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)

    context = manager.get_context(
        "alice",
        agent_name="research",
        thread_id="thread-1",
        query="How should you answer?",
    )

    assert context == "- [preferences] Prefers concise answers."
    assert manager._retriever.calls == [("How should you answer?", "research", 4, None)]
    with pytest.raises(MemoryManagerError, match="Refusing to share"):
        manager.get_context("bob", query="private query")


def test_search_uses_openviking_filter_dsl_for_memory_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)

    results = manager.search(
        "style",
        top_k=3,
        user_id="alice",
        agent_name="research",
        category="preferences",
    )

    assert results[0]["category"] == "preferences"
    assert manager._retriever.calls == [
        (
            "style",
            "research",
            3,
            {"op": "must", "field": "category", "conds": ["preferences"]},
        )
    ]


def test_concurrent_recall_keeps_actor_peer_scopes_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    barrier = threading.Barrier(2)
    observed: list[tuple[str, str | None]] = []

    def invoke(query: str) -> list[Document]:
        barrier.wait()
        observed.append((query, _ACTOR_PEER.get()))
        return []

    manager._retriever.invoke = invoke
    threads = [
        threading.Thread(
            target=manager.get_context,
            args=("alice",),
            kwargs={"agent_name": peer, "query": peer},
        )
        for peer in ("research", "review")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()

    assert set(observed) == {
        ("research", "research"),
        ("review", "review"),
    }


def test_warm_honors_warn_and_fail_fast_policies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    warn_manager = _manager(tmp_path / "warn", monkeypatch, startup_policy="warn")
    warn_manager._client.initialize = lambda: (_ for _ in ()).throw(RuntimeError("unavailable"))
    assert warn_manager.warm() is False

    fail_fast_manager = _manager(
        tmp_path / "fail-fast",
        monkeypatch,
        startup_policy="fail_fast",
    )
    fail_fast_manager._client.health = lambda: False
    with pytest.raises(MemoryManagerError, match="unhealthy"):
        fail_fast_manager.warm()


def test_capture_delegates_conversion_and_deduplicates_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    hidden = HumanMessage(
        "internal",
        id="hidden",
        additional_kwargs={"hide_from_ui": True},
    )
    messages = [
        SystemMessage("system", id="s1"),
        HumanMessage("hello", id="h1"),
        hidden,
        AIMessage("hi", id="a1"),
    ]

    manager.add("thread-1", messages, user_id="alice", agent_name="research")
    manager.add("thread-1", messages, user_id="alice", agent_name="research")

    assert len(manager._recorder.calls) == 1
    _, recorded, peer_id, actor_peer = manager._recorder.calls[0]
    assert recorded == [messages[0], messages[1], messages[3]]
    assert peer_id == actor_peer == "research"


def test_capture_cursor_ignores_volatile_model_response_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    first = [
        HumanMessage("hello", id="h1"),
        AIMessage(
            "hi",
            id="a1",
            response_metadata={"usage": {"output_tokens": 7}},
        ),
    ]
    reconstructed = [
        first[0],
        first[1].model_copy(update={"response_metadata": {"usage": {"output_tokens": 8}}}),
    ]

    manager.add("thread-1", first, user_id="alice")
    manager.add("thread-1", reconstructed, user_id="alice")

    assert len(manager._recorder.calls) == 1


def test_capture_rebases_after_compaction_without_replaying_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch, max_seen_message_ids=16)
    messages = [HumanMessage(f"message {index}", id=f"h{index}") for index in range(20)]
    manager.add("thread-1", messages, user_id="alice")

    compacted = [*messages[-8:], HumanMessage("new", id="h20")]
    manager.add("thread-1", compacted, user_id="alice")
    manager.add("thread-1", compacted, user_id="alice")

    assert len(manager._recorder.calls) == 2
    assert manager._recorder.calls[1][1] == [compacted[-1]]


def test_partial_progress_is_persisted_and_only_tail_is_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    messages = [HumanMessage(f"message {index}", id=f"h{index}") for index in range(4)]
    manager._recorder.failures.append(_PartialWriteError(2))

    manager.add("thread-1", messages, user_id="alice")
    manager.add("thread-1", messages, user_id="alice")

    assert [call[1] for call in manager._recorder.calls] == [messages, messages[2:]]


def test_pending_commit_is_retried_without_resubmitting_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    messages = [HumanMessage("hello", id="h1"), AIMessage("hi", id="a1")]
    manager._recorder.failures.append(_PartialWriteError(2, commit_pending=True))

    manager.add("thread-1", messages, user_id="alice")
    assert len(manager._pending_commit_sessions) == 1
    manager.add("thread-1", messages, user_id="alice")

    assert len(manager._recorder.calls) == 1
    assert len(manager._recorder.flushes) == 1
    assert manager._recorder.flush_actor_peers == ["deerflow"]
    assert manager._pending_commit_sessions == {}


def test_successful_sessions_do_not_accumulate_shutdown_tracking_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)

    for index in range(32):
        manager.add(
            f"thread-{index}",
            [HumanMessage(f"message {index}", id=f"h{index}")],
            user_id="alice",
        )

    assert manager._pending_commit_sessions == {}


def test_pending_commit_survives_manager_restart_without_resubmitting_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    messages = [HumanMessage("hello", id="h1"), AIMessage("hi", id="a1")]
    first = _manager(tmp_path, monkeypatch)
    first._recorder.failures.append(_PartialWriteError(2, commit_pending=True))
    first.add("thread-1", messages, user_id="alice")

    restarted = _manager(tmp_path, monkeypatch)
    restarted.add("thread-1", messages, user_id="alice")

    assert restarted._recorder.calls == []
    assert len(restarted._recorder.flushes) == 1


def test_failure_policies_preserve_fail_open_and_fail_closed_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    fail_open = _manager(tmp_path / "open", monkeypatch)
    fail_open._retriever.invoke = lambda _query: (_ for _ in ()).throw(RuntimeError("read failed"))
    fail_open._recorder.failures.append(RuntimeError("write failed"))
    assert fail_open.get_context("alice", query="query") == ""
    fail_open.add(
        "thread-1",
        [HumanMessage("hello", id="h1")],
        user_id="alice",
    )

    fail_closed = _manager(
        tmp_path / "closed",
        monkeypatch,
        failure_policy={"read": "fail_closed", "write": "fail_closed"},
    )
    fail_closed._retriever.invoke = lambda _query: (_ for _ in ()).throw(RuntimeError("read failed"))
    fail_closed._recorder.failures.append(RuntimeError("write failed"))
    with pytest.raises(MemoryManagerError, match="context retrieval failed"):
        fail_closed.get_context("alice", query="query")
    with pytest.raises(MemoryManagerError, match="recording failed"):
        fail_closed.add(
            "thread-1",
            [HumanMessage("hello", id="h1")],
            user_id="alice",
        )


def test_concurrent_same_session_capture_is_serialized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    first = [HumanMessage("first", id="h1")]
    second = [*first, AIMessage("second", id="a1")]
    barrier = threading.Barrier(3)

    def capture(messages: list[Any]) -> None:
        barrier.wait()
        manager.add("thread-1", messages, user_id="alice")

    threads = [
        threading.Thread(target=capture, args=(first,)),
        threading.Thread(target=capture, args=(second,)),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()

    flattened = [message for call in manager._recorder.calls for message in call[1]]
    assert {message.id for message in flattened} == {"h1", "a1"}
    assert len(flattened) == 2


@pytest.mark.asyncio
async def test_async_operations_run_off_the_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    event_loop_thread = threading.get_ident()
    worker_threads: list[int] = []
    original_record = manager._recorder.record
    original_invoke = manager._retriever.invoke

    def record(*args: Any, **kwargs: Any):
        worker_threads.append(threading.get_ident())
        return original_record(*args, **kwargs)

    def invoke(*args: Any, **kwargs: Any):
        worker_threads.append(threading.get_ident())
        return original_invoke(*args, **kwargs)

    manager._recorder.record = record
    manager._retriever.invoke = invoke

    await manager.aadd("thread-1", [HumanMessage("hello", id="h1")], user_id="alice")
    await manager.aget_context("alice", query="query")

    assert len(worker_threads) == 2
    assert all(thread_id != event_loop_thread for thread_id in worker_threads)


def test_close_releases_shared_client_once_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)

    manager.close()
    manager.close()

    assert manager._recorder.closed is True
    assert manager._retriever.closed is True
    assert manager._client.closed is True


def test_shutdown_flush_honors_budget_and_defers_close_until_commit_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    messages = [HumanMessage("hello", id="h1")]
    manager._recorder.failures.append(_PartialWriteError(1, commit_pending=True))
    manager.add("thread-1", messages, user_id="alice")
    flush_started = threading.Event()
    release_flush = threading.Event()
    original_flush = manager._recorder.flush

    def blocking_flush(session_id: str) -> None:
        flush_started.set()
        assert release_flush.wait(2)
        original_flush(session_id)

    manager._recorder.flush = blocking_flush
    started_at = time.monotonic()

    assert manager.shutdown_flush(0.01) is False
    assert time.monotonic() - started_at < 0.25
    # Thread.start() does not guarantee that the target has been scheduled by
    # the time the bounded caller returns.  The contract is that shutdown is
    # non-blocking and the deferred flush starts promptly, not synchronously.
    assert flush_started.wait(0.25)
    manager.close()
    assert manager._client.closed is False

    release_flush.set()
    assert manager._shutdown_flush_thread is not None
    manager._shutdown_flush_thread.join(2)
    assert not manager._shutdown_flush_thread.is_alive()
    assert manager._recorder.flush_actor_peers == ["deerflow"]
    assert manager._client.closed is True


def test_close_does_not_close_client_under_active_write_after_shutdown_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    write_started = threading.Event()
    release_write = threading.Event()
    original_record = manager._recorder.record

    def blocking_record(*args: Any, **kwargs: Any):
        write_started.set()
        assert release_write.wait(2)
        return original_record(*args, **kwargs)

    manager._recorder.record = blocking_record
    writer = threading.Thread(
        target=manager.add,
        args=("thread-1", [HumanMessage("hello", id="h1")]),
        kwargs={"user_id": "alice"},
    )
    writer.start()
    assert write_started.wait(1)

    assert manager.shutdown_flush(0.01) is False
    manager.close()
    assert manager._client.closed is False

    release_write.set()
    writer.join(2)
    assert not writer.is_alive()
    assert manager._client.closed is True


def test_cursor_contains_only_hashes_not_message_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    manager.add(
        "thread-1",
        [HumanMessage("top secret message", id="h1")],
        user_id="alice",
    )

    cursor = next((tmp_path / "openviking" / "official_sessions").glob("*.json"))
    text = cursor.read_text(encoding="utf-8")
    state = json.loads(text)
    assert "top secret message" not in text
    assert state["schema_version"] == 1
