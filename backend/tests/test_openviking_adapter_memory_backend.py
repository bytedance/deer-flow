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
from deerflow.agents.memory.backends.openviking.adapter import (
    OpenVikingAdapterMemoryManager,
)
from deerflow.agents.memory.backends.openviking.lifecycle import (
    SessionLifecycleStore,
)
from deerflow.agents.memory.backends.openviking.session import (
    _canonical_peer_id,
    _session_id,
)
from deerflow.agents.memory.backends.openviking.settings import (
    OpenVikingAdapterConfig,
    is_legacy_openviking_config,
    is_safe_peer_id,
)
from deerflow.agents.memory.manager import MemoryAuthorizationError, MemoryManagerError


class _CommitPolicy:
    def __init__(self, *, mode: str, pending_token_threshold: int = 8_000):
        self.mode = mode
        self.pending_token_threshold = pending_token_threshold


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
    def __init__(
        self,
        *,
        commit_policy: _CommitPolicy,
        client: _Client | None = None,
        url: str | None = None,
        api_key: str | None = None,
        timeout: float = 60.0,
        auto_initialize: bool = True,
    ):
        self._client = client or _Client(url=url, api_key=api_key, timeout=timeout)
        self._auto_initialize = auto_initialize
        self._owns_client = client is None
        self.commit_policy = commit_policy
        self.calls: list[tuple[str, list[Any], str | None, str | None]] = []
        self.flushes: list[str] = []
        self.flush_actor_peers: list[str | None] = []
        self.failures: list[BaseException] = []
        self.pending_tokens: dict[str, int] = {}
        self.closed = False

    @property
    def client(self) -> _Client:
        if self._auto_initialize and not self._client.initialized:
            self._client.initialize()
        return self._client

    def record(self, session_id: str, messages: list[Any], peer_id: str | None = None):
        self.calls.append((session_id, list(messages), peer_id, _ACTOR_PEER.get()))
        if self.failures:
            raise self.failures.pop(0)
        self.pending_tokens[session_id] = self.pending_tokens.get(session_id, 0) + len(messages) * 1_000
        if self.commit_policy.mode == "always" or (self.commit_policy.mode == "pending_tokens" and self.pending_tokens[session_id] >= self.commit_policy.pending_token_threshold):
            self.flush(session_id)
        return object()

    def flush(self, session_id: str) -> None:
        self.flushes.append(session_id)
        self.flush_actor_peers.append(_ACTOR_PEER.get())
        if self.failures:
            raise self.failures.pop(0)
        self.pending_tokens[session_id] = 0

    def close(self) -> None:
        self.closed = True
        if self._owns_client:
            self._client.close()


class _Retriever:
    def __init__(self, *, client: _Client, **kwargs: Any):
        self.client = client
        self.kwargs = kwargs
        self.limit = kwargs["limit"]
        self.filter = None
        self.session_id = kwargs.get("session_id")
        self.target_uri = kwargs.get("target_uri", "")
        self.search_mode = kwargs.get("search_mode", "search")
        self.calls: list[tuple[str, str | None, int, Any]] = []
        self.session_ids: list[str | None] = []
        self.target_uris: list[str | list[str]] = []
        self.search_modes: list[str] = []
        self.closed = False

    def __copy__(self):
        copied = type(self)(client=self.client, **self.kwargs)
        copied.calls = self.calls
        copied.session_ids = self.session_ids
        copied.target_uris = self.target_uris
        copied.search_modes = self.search_modes
        copied.limit = self.limit
        copied.filter = copy.deepcopy(self.filter)
        copied.session_id = self.session_id
        copied.target_uri = copy.deepcopy(self.target_uri)
        copied.search_mode = self.search_mode
        if "invoke" in self.__dict__:
            copied.invoke = self.__dict__["invoke"]
        return copied

    def invoke(self, query: str) -> list[Document]:
        self.calls.append((query, _ACTOR_PEER.get(), self.limit, self.filter))
        self.session_ids.append(self.session_id)
        self.target_uris.append(copy.deepcopy(self.target_uri))
        self.search_modes.append(self.search_mode)
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
    import deerflow.agents.memory.backends.openviking.adapter as module

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


def test_official_loader_uses_standalone_package() -> None:
    from deerflow.agents.memory.backends.openviking.adapter import (
        _load_official_integration,
    )

    integration = _load_official_integration()

    assert integration["OpenVikingSessionRecorder"].__module__.startswith("langchain_openviking")
    assert integration["OpenVikingRetriever"].__module__.startswith("langchain_openviking")
    assert integration["use_actor_peer"].__module__ == "langchain_openviking.actor_peer"


def test_published_adapter_manager_delegates_client_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENVIKING_API_KEY", "user-key")

    manager = OpenVikingMemoryManager.from_config(_config(tmp_path, base_url="http://127.0.0.1:9"))

    assert isinstance(manager, OpenVikingAdapterMemoryManager)
    manager.close()
    assert manager._resources_closed is True


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
) -> OpenVikingAdapterMemoryManager:
    monkeypatch.setenv("OPENVIKING_API_KEY", "user-key")
    config = _config(tmp_path, **overrides)
    if "commit" not in overrides:
        config["commit"] = {"idle_flush_seconds": 0}
    manager = OpenVikingMemoryManager.from_config(config)
    assert isinstance(manager, OpenVikingAdapterMemoryManager)
    return manager


def test_official_config_requires_user_key_and_rejects_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENVIKING_API_KEY", raising=False)
    with pytest.raises(ValueError, match="USER API key"):
        OpenVikingAdapterConfig.from_backend_config(_config(tmp_path))

    monkeypatch.setenv("OPENVIKING_API_KEY", "secret")
    parsed = OpenVikingAdapterConfig.from_backend_config(_config(tmp_path))
    assert parsed.owner_user_id == "alice"
    assert parsed.commit_mode == "pending_tokens"
    assert parsed.pending_token_threshold == 8_000
    assert parsed.idle_flush_seconds == 1_800
    assert "secret" not in repr(parsed)
    with pytest.raises(ValueError, match="Unknown OpenViking"):
        OpenVikingAdapterConfig.from_backend_config(_config(tmp_path, typo=True))


def test_official_config_does_not_treat_false_string_as_insecure_http_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENVIKING_API_KEY", "secret")

    with pytest.raises(ValueError, match="plain HTTP"):
        OpenVikingAdapterConfig.from_backend_config(
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
        OpenVikingAdapterConfig.from_backend_config(_config(tmp_path, **overrides))


@pytest.mark.parametrize("peer_id", ["UPPER", "contains space", "_reserved", "a" * 65])
def test_official_config_rejects_invalid_default_peer_id(
    peer_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENVIKING_API_KEY", "secret")

    with pytest.raises(ValueError, match="default_peer_id"):
        OpenVikingAdapterConfig.from_backend_config(_config(tmp_path, default_peer_id=peer_id))


def test_official_config_rejects_generated_peer_namespace_as_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENVIKING_API_KEY", "secret")

    with pytest.raises(
        ValueError,
        match="default_peer_id must not start with the reserved prefix 'df-agent-'",
    ):
        OpenVikingAdapterConfig.from_backend_config(
            _config(tmp_path, default_peer_id="df-agent-custom"),
        )


def test_official_config_accepts_custom_default_peer_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENVIKING_API_KEY", "secret")

    config = OpenVikingAdapterConfig.from_backend_config(
        _config(tmp_path, default_peer_id="assistant"),
    )

    assert config.default_peer_id == "assistant"


def test_commit_config_is_validated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENVIKING_API_KEY", "secret")

    parsed = OpenVikingAdapterConfig.from_backend_config(
        _config(
            tmp_path,
            commit={
                "mode": "pending_tokens",
                "pending_token_threshold": 12_000,
                "idle_flush_seconds": 90,
            },
        )
    )
    assert parsed.commit_mode == "pending_tokens"
    assert parsed.pending_token_threshold == 12_000
    assert parsed.idle_flush_seconds == 90

    for commit, message in (
        ({"mode": "sometimes"}, "commit.mode"),
        ({"pending_token_threshold": 0}, "pending_token_threshold"),
        ({"idle_flush_seconds": float("nan")}, "idle_flush_seconds"),
        ({"unknown": True}, "commit.unknown"),
    ):
        with pytest.raises(ValueError, match=message):
            OpenVikingAdapterConfig.from_backend_config(
                _config(tmp_path, commit=commit),
            )


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
    assert manager._recorder.commit_policy.mode == "pending_tokens"
    assert manager._recorder.commit_policy.pending_token_threshold == 8_000
    assert manager._retriever.kwargs["context_types"] == ("memory",)
    assert manager._client.kwargs == {
        "url": "http://openviking:1933",
        "api_key": "user-key",
        "timeout": 30.0,
    }


def test_official_recorder_initializes_shared_client_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)

    assert manager._client.initialized is True
    assert manager._client.initialize_calls == 1
    manager.get_context("alice", query="first")
    manager.add("thread-1", [HumanMessage("hello", id="h1")], user_id="alice")

    assert manager._client.initialize_calls == 1


@pytest.mark.parametrize("agent_name", ["research", "Agent-A", "a" * 64])
def test_canonical_peer_id_preserves_existing_safe_mapping(agent_name: str) -> None:
    expected = agent_name.lower()

    assert _canonical_peer_id(agent_name, "deerflow") == expected


@pytest.mark.parametrize("agent_name", ["-research", "a" * 65])
def test_canonical_peer_id_maps_deerflow_only_names_to_stable_safe_fallback(
    agent_name: str,
) -> None:
    first = _canonical_peer_id(agent_name, "deerflow")
    second = _canonical_peer_id(agent_name, "deerflow")

    assert first == second
    assert first.startswith("df-agent-")
    assert is_safe_peer_id(first)


def test_canonical_peer_id_fallback_is_collision_resistant() -> None:
    assert _canonical_peer_id("-research", "deerflow") != _canonical_peer_id(
        "research",
        "deerflow",
    )


def test_canonical_peer_id_reserves_default_peer_for_unnamed_agent() -> None:
    first = _canonical_peer_id("deerflow", "deerflow")
    second = _canonical_peer_id("DeerFlow", "deerflow")

    assert first == second
    assert first.startswith("df-agent-")
    assert first != _canonical_peer_id(None, "deerflow")


def test_canonical_peer_id_reserves_custom_default_peer() -> None:
    mapped = _canonical_peer_id("assistant", "assistant")

    assert mapped.startswith("df-agent-")
    assert mapped != _canonical_peer_id(None, "assistant")


def test_canonical_peer_id_reserves_generated_peer_namespace() -> None:
    generated = _canonical_peer_id("-agent", "deerflow")
    remapped = _canonical_peer_id(generated, "deerflow")

    assert remapped.startswith("df-agent-")
    assert remapped != generated
    assert remapped == _canonical_peer_id(generated, "deerflow")


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
    assert manager._retriever.session_ids == [_session_id("alice", "research", "thread-1")]
    assert manager._retriever.target_uris == [
        [
            "viking://user/memories",
            "viking://user/peers/research/memories",
        ]
    ]
    assert manager._retriever.session_id is None
    assert manager._retriever.target_uri == ""
    with pytest.raises(MemoryAuthorizationError, match="Refusing to share"):
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
    assert manager._retriever.target_uris == [
        [
            "viking://user/memories",
            "viking://user/peers/research/memories",
        ]
    ]


def test_concurrent_recall_keeps_actor_peer_scopes_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    barrier = threading.Barrier(2)
    observed: list[tuple[str, str | None, str | None, tuple[str, ...]]] = []

    def invoke(retriever: _Retriever, query: str) -> list[Document]:
        barrier.wait()
        observed.append(
            (
                query,
                _ACTOR_PEER.get(),
                retriever.session_id,
                tuple(retriever.target_uri),
            )
        )
        return []

    monkeypatch.setattr(_Retriever, "invoke", invoke)
    threads = [
        threading.Thread(
            target=manager.get_context,
            args=("alice",),
            kwargs={"agent_name": peer, "thread_id": thread_id, "query": peer},
        )
        for peer, thread_id in (("research", "thread-a"), ("review", "thread-b"))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()

    assert set(observed) == {
        (
            "research",
            "research",
            _session_id("alice", "research", "thread-a"),
            (
                "viking://user/memories",
                "viking://user/peers/research/memories",
            ),
        ),
        (
            "review",
            "review",
            _session_id("alice", "review", "thread-b"),
            (
                "viking://user/memories",
                "viking://user/peers/review/memories",
            ),
        ),
    }


def test_warm_honors_warn_and_fail_fast_policies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    warn_manager = _manager(tmp_path / "warn", monkeypatch, startup_policy="warn")
    warn_manager._client.health = lambda: (_ for _ in ()).throw(RuntimeError("unavailable"))
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
    session_id = _session_id("alice", "deerflow", "thread-1")
    assert manager._load_cursor(session_id)["commit_pending"] is True
    manager.add("thread-1", messages, user_id="alice")

    assert len(manager._recorder.calls) == 1
    assert len(manager._recorder.flushes) == 1
    assert manager._recorder.flush_actor_peers == ["deerflow"]
    assert manager._load_cursor(session_id)["commit_pending"] is False


def test_successful_sessions_do_not_become_shutdown_commit_candidates(
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

    assert manager._shutdown_commit_candidates(time.time()) == ()


def test_threshold_policy_commits_without_rotating_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(
        tmp_path,
        monkeypatch,
        commit={
            "mode": "pending_tokens",
            "pending_token_threshold": 2_000,
            "idle_flush_seconds": 0,
        },
    )
    messages = [HumanMessage("hello", id="h1"), AIMessage("hi", id="a1")]

    manager.add("thread-1", messages, user_id="alice")

    session_id = _session_id("alice", "deerflow", "thread-1")
    assert [call[0] for call in manager._recorder.calls] == [session_id]
    assert manager._recorder.flushes == [session_id]


def test_compaction_capture_forces_flush_without_duplicate_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(
        tmp_path,
        monkeypatch,
        commit={"mode": "pending_tokens", "idle_flush_seconds": 0},
    )
    messages = [HumanMessage("hello", id="h1"), AIMessage("hi", id="a1")]

    manager.add("thread-1", messages, user_id="alice")
    manager.add_nowait("thread-1", messages, user_id="alice")

    session_id = _session_id("alice", "deerflow", "thread-1")
    assert len(manager._recorder.calls) == 1
    assert manager._recorder.flushes == [session_id]


def test_idle_deadline_is_reset_by_later_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(
        tmp_path,
        monkeypatch,
        commit={"mode": "pending_tokens", "idle_flush_seconds": 60},
    )
    first = [HumanMessage("hello", id="h1")]
    second = [*first, AIMessage("hi", id="a1")]

    manager.add("thread-1", first, user_id="alice")
    session_id = _session_id("alice", "deerflow", "thread-1")
    first_deadline = manager._load_cursor(session_id)["idle_due_at"]
    manager.add("thread-1", second, user_id="alice")
    second_deadline = manager._load_cursor(session_id)["idle_due_at"]

    assert second_deadline >= first_deadline
    assert (
        manager._process_idle_deadline(
            session_id,
            "deerflow",
            first_deadline,
            now=first_deadline,
        )
        is False
    )
    assert manager._recorder.flushes == []


def test_idle_worker_commits_once_after_inactivity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(
        tmp_path,
        monkeypatch,
        commit={"mode": "pending_tokens", "idle_flush_seconds": 0.05},
    )
    manager.add("thread-1", [HumanMessage("hello", id="h1")], user_id="alice")
    session_id = _session_id("alice", "deerflow", "thread-1")

    deadline = time.monotonic() + 2
    while not manager._recorder.flushes and time.monotonic() < deadline:
        time.sleep(0.01)

    assert manager._recorder.flushes == [session_id]
    assert manager._load_cursor(session_id)["idle_due_at"] is None
    time.sleep(0.1)
    assert manager._recorder.flushes == [session_id]
    manager.close()


def test_compaction_flush_failure_is_retried_without_duplicate_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(
        tmp_path,
        monkeypatch,
        commit={"mode": "pending_tokens", "idle_flush_seconds": 0},
    )
    messages = [HumanMessage("hello", id="h1"), AIMessage("hi", id="a1")]
    manager.add("thread-1", messages, user_id="alice")
    manager._recorder.failures.append(RuntimeError("commit failed"))

    manager.add_nowait("thread-1", messages, user_id="alice")
    manager.add("thread-1", messages, user_id="alice")

    assert len(manager._recorder.calls) == 1
    assert len(manager._recorder.flushes) == 2
    session_id = _session_id("alice", "deerflow", "thread-1")
    assert manager._load_cursor(session_id)["commit_pending"] is False


def test_idle_commit_is_restored_after_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    commit = {"mode": "pending_tokens", "idle_flush_seconds": 60}
    first = _manager(tmp_path, monkeypatch, commit=commit)
    first.add("thread-1", [HumanMessage("hello", id="h1")], user_id="alice")
    session_id = _session_id("alice", "deerflow", "thread-1")
    state = first._load_cursor(session_id)
    first._save_cursor(session_id, {**state, "idle_due_at": time.time() - 1})
    first.close()

    restarted = _manager(tmp_path, monkeypatch, commit=commit)

    deadline = time.monotonic() + 2
    while not restarted._recorder.flushes and time.monotonic() < deadline:
        time.sleep(0.01)
    assert restarted._recorder.flushes == [session_id]
    assert restarted._recorder.flush_actor_peers == ["deerflow"]
    assert restarted._load_cursor(session_id)["idle_due_at"] is None
    restarted.close()


def test_shutdown_does_not_commit_future_idle_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(
        tmp_path,
        monkeypatch,
        commit={"mode": "pending_tokens", "idle_flush_seconds": 60},
    )
    manager.add("thread-1", [HumanMessage("hello", id="h1")], user_id="alice")

    assert manager.shutdown_flush(1) is True
    assert manager._recorder.flushes == []
    manager.close()


def test_shutdown_flushes_idle_deadline_that_is_already_due(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(
        tmp_path,
        monkeypatch,
        commit={"mode": "pending_tokens", "idle_flush_seconds": 60},
    )
    manager.add("thread-1", [HumanMessage("hello", id="h1")], user_id="alice")
    session_id = _session_id("alice", "deerflow", "thread-1")
    manager._stop_idle_worker()
    state = manager._load_cursor(session_id)
    manager._save_cursor(session_id, {**state, "idle_due_at": time.time() - 1})

    assert manager.shutdown_flush(1) is True
    assert manager._recorder.flushes == [session_id]
    assert manager._load_cursor(session_id)["idle_due_at"] is None
    manager.close()


def test_shutdown_worker_completes_when_a_candidate_cursor_becomes_unreadable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    session_id = _session_id("alice", "deerflow", "thread-1")
    monkeypatch.setattr(
        type(manager),
        "_shutdown_commit_candidates",
        lambda self, now: ((session_id, "deerflow"),),
    )
    monkeypatch.setattr(
        type(manager),
        "_load_cursor",
        lambda self, candidate: (_ for _ in ()).throw(MemoryManagerError(f"unreadable {candidate}")),
    )

    assert manager.shutdown_flush(1) is False
    assert manager._shutdown_flush_done.is_set()
    manager.close()
    assert manager._recorder.closed is True


def test_close_stops_idle_worker_without_committing_future_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(
        tmp_path,
        monkeypatch,
        commit={"mode": "pending_tokens", "idle_flush_seconds": 60},
    )
    manager.add("thread-1", [HumanMessage("hello", id="h1")], user_id="alice")

    manager.close()
    worker = manager._session_lifecycle.worker_thread
    assert worker is not None
    worker.join(1)

    assert not worker.is_alive()
    assert manager._recorder.flushes == []


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
    assert manager._retriever.closed is False
    assert manager._client.closed is True


@pytest.mark.asyncio
async def test_close_is_safe_when_called_from_a_running_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)

    manager.close()

    assert manager._recorder.closed is True
    assert manager._retriever.closed is False
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


def test_cursor_contains_no_message_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(
        tmp_path,
        monkeypatch,
        commit={"mode": "pending_tokens", "idle_flush_seconds": 60},
    )
    manager.add(
        "thread-1",
        [HumanMessage("top secret message", id="h1")],
        user_id="alice",
    )

    cursor = next((tmp_path / "openviking" / "official_sessions").glob("*.json"))
    text = cursor.read_text(encoding="utf-8")
    state = json.loads(text)
    assert "top secret message" not in text
    assert state["schema_version"] == 2
    assert state["peer_id"] == "deerflow"
    assert state["idle_due_at"] is not None
    manager.close()


def test_corrupt_cursor_fails_closed_before_remote_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    manager._ensure_lifecycle_restored()
    session_id = _session_id("alice", "deerflow", "thread-1")
    cursor = tmp_path / "openviking" / "official_sessions" / f"{session_id}.json"
    cursor.parent.mkdir(parents=True, exist_ok=True)
    cursor.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(MemoryManagerError, match="refusing unsafe replay"):
        manager.add(
            "thread-1",
            [HumanMessage("must not be replayed", id="h1")],
            user_id="alice",
        )

    assert manager._recorder.calls == []
    manager.close()


def test_idle_scheduler_survives_one_callback_failure(tmp_path: Path) -> None:
    completed = threading.Event()
    calls: list[str] = []

    def callback(session_id: str, peer_id: str, due_at: float) -> None:
        del peer_id, due_at
        calls.append(session_id)
        if session_id == "broken":
            raise RuntimeError("boom")
        completed.set()

    store = SessionLifecycleStore(tmp_path, callback)
    now = time.time()
    store.schedule("broken", "peer", now)
    store.schedule("healthy", "peer", now + 0.05)

    assert completed.wait(1)
    assert calls == ["broken", "healthy"]
    store.stop()
