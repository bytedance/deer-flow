"""Tests for the official-package OpenViking memory backend."""

from __future__ import annotations

import copy
import gc
import hashlib
import importlib
import json
import logging
import socket
import sys
import threading
import time
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.openviking.config import OpenVikingConfig
from deerflow.agents.memory.backends.openviking.credentials import (
    OpenVikingCredential,
    OpenVikingCredentialProvider,
    load_credential_provider,
    normalize_resolved_credential,
    validate_provider_path,
)
from deerflow.agents.memory.backends.openviking.openviking_manager import (
    OpenVikingMemoryManager,
    _canonical_peer_id,
    _session_id,
)
from deerflow.agents.memory.manager import (
    MemoryManagerError,
    MemoryReadError,
    _scan_backends,
    reset_memory_manager,
)
from deerflow.agents.middlewares.dynamic_context_middleware import DynamicContextMiddleware


@pytest.fixture(autouse=True)
def isolated_cli_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_path = tmp_path / "ovcli.conf"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("OPENVIKING_CLI_CONFIG_FILE", str(config_path))
    for name in ("OPENVIKING_URL", "OPENVIKING_API_KEY", "OPENVIKING_ACCOUNT", "OPENVIKING_USER", "OPENVIKING_ACTOR_PEER_ID", "OPENVIKING_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)
    return config_path


@pytest.fixture
def openviking_http_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    # This fixture exercises a direct loopback transport, not host proxy routing.
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1,localhost,::1")
    requests: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append({"path": self.path, "headers": {key.lower(): value for key, value in self.headers.items()}})
            self._respond({"status": "ok"})

        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({"path": self.path, "headers": {key.lower(): value for key, value in self.headers.items()}, "payload": payload})
            if self.path in {"/api/v1/search/find", "/api/v1/search/search"}:
                result = {"memories": [{"uri": "viking://user/alice/memories/style.md", "category": "preferences", "overview": "Prefers concise answers.", "score": 0.9}]}
            elif self.path.endswith("/messages/batch"):
                result = {"pending_tokens": 2}
            elif self.path.endswith("/commit"):
                result = {"status": "committed"}
            else:
                self.send_error(404)
                return
            self._respond({"status": "success", "result": result})

        def _respond(self, body: dict[str, Any]) -> None:
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


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


@pytest.mark.parametrize("kind", ["invalid", "legacy"])
@pytest.mark.parametrize("entry", ["after-agent", "async-after-agent", "compaction"])
def test_memory_admission_redacts_call_views_before_openviking_recorder(tmp_path, monkeypatch, official_integration, kind: str, entry: str) -> None:
    import asyncio

    from langchain_core.messages import messages_to_dict
    from langchain_openai.chat_models.base import _convert_dict_to_message
    from langgraph.runtime import Runtime

    from deerflow.agents.memory import summarization_hook
    from deerflow.agents.middlewares import memory_middleware
    from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
    from deerflow.agents.middlewares.summarization_middleware import SummarizationEvent
    from deerflow.config.memory_config import MemoryConfig
    from deerflow.config.pii_redaction_config import PiiRedactionConfig

    config = PiiRedactionConfig(enabled=True, token_secret="openviking-regression-secret")
    raw = {"role": "assistant", "content": "Preparing lookup"}
    call = {"name": "lookup", "arguments": '{"email":"alice@example.com"}' if kind == "legacy" else '{"email":"alice@example.com",'}
    raw.update({"function_call": call} if kind == "legacy" else {"tool_calls": [{"id": "call-1", "type": "function", "function": call}]})
    messages = [HumanMessage("Look up contact"), _convert_dict_to_message(raw), AIMessage("Lookup was not executed")]
    original = messages_to_dict(messages)
    manager = _manager(tmp_path, monkeypatch)
    monkeypatch.setattr(memory_middleware, "get_memory_manager", lambda: manager)
    monkeypatch.setattr(summarization_hook, "get_memory_manager", lambda: manager)
    monkeypatch.setattr(summarization_hook, "get_memory_config", lambda: MemoryConfig(enabled=True))
    runtime = Runtime(context={"thread_id": "thread-1", "user_id": "alice"})
    middleware = MemoryMiddleware(memory_config=MemoryConfig(enabled=True), pii_redaction_config=config)
    try:
        if entry == "after-agent":
            middleware.after_agent({"messages": messages}, runtime)
        elif entry == "async-after-agent":
            asyncio.run(middleware.aafter_agent({"messages": messages}, runtime))
        else:
            event = SummarizationEvent(messages_to_summarize=tuple(messages), preserved_messages=(), thread_id="thread-1", agent_name=None, runtime=runtime)
            summarization_hook.memory_flush_hook(event, pii_redaction_config=config)
        assert len(manager._recorder.calls) == 1
        recorded = manager._recorder.calls[0][1]
        assert len(recorded) == 3
        assert "alice@example.com" not in str(messages_to_dict(recorded))
        if kind == "legacy":
            assert "[EMAIL_" in recorded[1].additional_kwargs["function_call"]["arguments"]
        else:
            assert "[EMAIL_" in recorded[1].invalid_tool_calls[0]["args"]
        assert messages_to_dict(messages) == original
    finally:
        manager.close()


@pytest.mark.parametrize("write_policy", ["log_and_drop", "raise"])
@pytest.mark.parametrize("entry", ["after-agent", "async-after-agent", "compaction"])
def test_another_owner_write_is_refused_and_follows_the_write_policy(tmp_path, monkeypatch, official_integration, caplog, write_policy: str, entry: str) -> None:
    import asyncio

    from langgraph.runtime import Runtime

    from deerflow.agents.memory import summarization_hook
    from deerflow.agents.middlewares import memory_middleware
    from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
    from deerflow.agents.middlewares.summarization_middleware import SummarizationEvent
    from deerflow.config.memory_config import MemoryConfig

    messages = [HumanMessage("remember short replies"), AIMessage("noted")]
    manager = _manager(tmp_path, monkeypatch, failure_policy={"write": write_policy})
    monkeypatch.setattr(memory_middleware, "get_memory_manager", lambda: manager)
    monkeypatch.setattr(memory_middleware, "resolve_runtime_user_id", lambda runtime: "bob")
    monkeypatch.setattr(summarization_hook, "get_memory_manager", lambda: manager)
    monkeypatch.setattr(summarization_hook, "get_memory_config", lambda: MemoryConfig(enabled=True))
    monkeypatch.setattr(summarization_hook, "resolve_runtime_user_id", lambda runtime: "bob")
    runtime = Runtime(context={"thread_id": "thread-1", "user_id": "bob"})
    middleware = MemoryMiddleware(memory_config=MemoryConfig(enabled=True))

    def write() -> None:
        if entry == "after-agent":
            middleware.after_agent({"messages": messages}, runtime)
        elif entry == "async-after-agent":
            asyncio.run(middleware.aafter_agent({"messages": messages}, runtime))
        else:
            event = SummarizationEvent(messages_to_summarize=tuple(messages), preserved_messages=(), thread_id="thread-1", agent_name=None, runtime=runtime)
            summarization_hook.memory_flush_hook(event)

    try:
        with caplog.at_level(logging.ERROR, logger=OpenVikingMemoryManager.__module__):
            if write_policy == "raise":
                with pytest.raises(MemoryManagerError, match="owner_user_id"):
                    write()
            else:
                write()
        assert manager._recorder.calls == []
        assert manager._recorder.flushes == []
        assert not list((tmp_path / "openviking").rglob("*.json"))
        if write_policy == "log_and_drop":
            assert any("'bob'" in record.getMessage() and "Dropping the memory write" in record.getMessage() for record in caplog.records)
            assert "remember short replies" not in caplog.text
    finally:
        manager.close()


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


@pytest.fixture
def unreachable_openviking_url() -> Iterator[str]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved_socket:
        reserved_socket.bind(("127.0.0.1", 0))
        host, port = reserved_socket.getsockname()
        yield f"http://{host}:{port}"


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


@pytest.mark.parametrize(
    ("section", "key", "attr", "default"),
    [
        (None, "timeout_seconds", "timeout_seconds", 30.0),
        (None, "max_seen_message_ids", "max_seen_message_ids", 512),
        ("retrieval", "top_k", "search_top_k", 8),
        ("retrieval", "max_injection_chars", "max_injection_chars", 12_000),
        ("retrieval", "score_threshold", "score_threshold", None),
    ],
)
@pytest.mark.parametrize("unset", [None, "", "   "])
def test_numeric_knob_written_without_a_value_keeps_its_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    section: str | None,
    key: str,
    attr: str,
    default: Any,
    unset: Any,
) -> None:
    """An unquoted ``top_k:`` in YAML parses as unset, not as a broken backend."""
    monkeypatch.setenv("OPENVIKING_API_KEY", "user-key")
    config = _backend_config(tmp_path)
    target = config if section is None else config[section]
    target[key] = unset

    cfg = OpenVikingConfig.from_backend_config(config)

    assert getattr(cfg, attr) == default


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        (None, "timeout_seconds", "soon"),
        (None, "timeout_seconds", [30]),
        (None, "max_seen_message_ids", "many"),
        ("retrieval", "top_k", "four"),
        ("retrieval", "top_k", {"count": 4}),
        ("retrieval", "score_threshold", "high"),
    ],
)
def test_non_numeric_knob_names_the_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    section: str | None,
    key: str,
    value: Any,
) -> None:
    """The report has to say which knob is wrong, not just that a cast failed."""
    monkeypatch.setenv("OPENVIKING_API_KEY", "user-key")
    config = _backend_config(tmp_path)
    target = config if section is None else config[section]
    target[key] = value

    with pytest.raises(ValueError, match=f"OpenViking {key} must be a number"):
        OpenVikingConfig.from_backend_config(config)


def test_backend_is_discovered_by_registered_name() -> None:
    reset_memory_manager()
    assert _scan_backends()["openviking"] is OpenVikingMemoryManager


@pytest.mark.parametrize(
    ("read_policy", "expected"),
    [
        pytest.param("fail_open", False, id="fail_open"),
        pytest.param("raise", True, id="raise"),
    ],
)
def test_read_failure_capability_matches_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    read_policy: str,
    expected: bool,
) -> None:
    manager = _manager(
        tmp_path,
        monkeypatch,
        failure_policy={"read": read_policy},
    )

    assert manager.read_failures_are_fatal is expected


def test_official_loader_uses_standalone_package() -> None:
    from deerflow.agents.memory.backends.openviking.openviking_manager import (
        _load_official_integration,
    )

    integration = _load_official_integration()

    assert integration["OpenVikingSessionRecorder"].__module__.startswith("langchain_openviking")
    assert integration["OpenVikingRetriever"].__module__.startswith("langchain_openviking")


@pytest.mark.parametrize("cli_profile", ["missing", "empty", "foreign", "oidc-env", "ldap-env"])
def test_user_key_connection_uses_owner_key_without_ambient_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_cli_config: Path,
    openviking_http_server: tuple[str, list[dict[str, Any]]],
    cli_profile: str,
) -> None:
    if cli_profile == "missing":
        isolated_cli_config.unlink()
    elif cli_profile == "foreign":
        isolated_cli_config.write_text(json.dumps({"url": "http://unused.invalid", "api_key": "cli-key", "extra_headers": {"X-CLI-Only": "must-not-leak", "X-API-Key": "cli-header-key"}}), encoding="utf-8")
    if cli_profile in {"oidc-env", "ldap-env"}:
        monkeypatch.setenv("OPENVIKING_AUTH_MODE", cli_profile.removesuffix("-env"))
        monkeypatch.setenv("OPENVIKING_OIDC_TOKEN", "foreign-token")
        monkeypatch.setenv("OPENVIKING_USERNAME", "foreign-user")
        monkeypatch.setenv("OPENVIKING_PASSWORD", "foreign-password")
    base_url, requests = openviking_http_server
    manager = _manager(tmp_path, monkeypatch, base_url=base_url, timeout_seconds=1, failure_policy={"read": "raise"})
    try:
        assert manager.warm() is True
        facts = manager.search("response style", top_k=2, user_id="alice")
        assert facts == [{"id": "viking://user/alice/memories/style.md", "content": "Prefers concise answers.", "category": "preferences", "confidence": 0.9, "source": "viking://user/alice/memories/style.md", "score": 0.9}]
        assert [request["path"] for request in requests] == ["/health", "/api/v1/search/find"]
        assert requests[-1]["payload"]["query"] == "response style"
        assert requests[-1]["payload"]["limit"] == 2

        messages = [HumanMessage("remember short replies"), AIMessage("noted")]
        manager.add("thread-1", messages, user_id="alice")
        batch, commit = requests[2:]
        assert batch["path"].endswith("/messages/batch")
        assert commit["path"] == batch["path"].removesuffix("/messages/batch") + "/commit"
        assert [message["role"] for message in batch["payload"]["messages"]] == ["user", "assistant"]
        assert [message["parts"] for message in batch["payload"]["messages"]] == [[{"type": "text", "text": "remember short replies"}], [{"type": "text", "text": "noted"}]]
        assert all(request["headers"]["x-api-key"] == "user-key" for request in requests)
        assert all("x-cli-only" not in request["headers"] for request in requests)
        assert all("authorization" not in request["headers"] for request in requests)
        before = len(requests)
        manager.add("thread-1", messages, user_id="alice")
        assert len(requests) == before
        with pytest.raises(MemoryReadError, match="owner_user_id"):
            manager.search("private data", user_id="another-owner")
        # The default write policy drops the refused write instead of raising.
        manager.add("thread-1", messages, user_id="another-owner")
        assert len(requests) == before
    finally:
        manager.close()


def test_malformed_cli_configuration_is_not_silently_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_cli_config: Path) -> None:
    isolated_cli_config.write_text("{invalid", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid CLI config"):
        _manager(tmp_path, monkeypatch)


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


def _injection_middleware(manager: OpenVikingMemoryManager) -> DynamicContextMiddleware:
    from deerflow.config.app_config import AppConfig
    from deerflow.config.memory_config import MemoryConfig
    from deerflow.config.sandbox_config import SandboxConfig

    config = AppConfig(
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        memory=MemoryConfig(enabled=True, injection_enabled=True, manager_class="openviking", backend_config=manager.backend_config),
    )
    return DynamicContextMiddleware(app_config=config)


def test_unreachable_context_read_raise_aborts_dynamic_context_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unreachable_openviking_url: str,
) -> None:
    manager = _manager(
        tmp_path,
        monkeypatch,
        base_url=unreachable_openviking_url,
        timeout_seconds=0.1,
        failure_policy={"read": "raise"},
    )
    monkeypatch.setattr(
        "deerflow.agents.memory.get_memory_manager",
        lambda: manager,
    )
    monkeypatch.setattr(
        "deerflow.agents.middlewares.dynamic_context_middleware.resolve_runtime_user_id",
        lambda runtime: "alice",
    )
    middleware = _injection_middleware(manager)
    state = {"messages": [HumanMessage("answer this", id="message-1")]}

    with pytest.raises(MemoryReadError) as exc_info:
        middleware.before_agent(state, None)

    assert exc_info.value.__cause__ is not None


def test_strict_scope_mismatch_uses_required_read_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(
        tmp_path,
        monkeypatch,
        failure_policy={"read": "raise"},
    )
    monkeypatch.setattr(
        "deerflow.agents.memory.get_memory_manager",
        lambda: manager,
    )
    monkeypatch.setattr(
        "deerflow.agents.middlewares.dynamic_context_middleware.resolve_runtime_user_id",
        lambda runtime: "bob",
    )
    middleware = _injection_middleware(manager)
    state = {"messages": [HumanMessage("answer this", id="message-1")]}

    with pytest.raises(MemoryReadError, match="owner_user_id 'alice'") as exc_info:
        middleware.before_agent(state, None)
    with pytest.raises(MemoryReadError, match="owner_user_id 'alice'") as search_error:
        manager.search("preferences", user_id="bob", agent_name="research")

    for error in (exc_info.value, search_error.value):
        assert isinstance(error.__cause__, MemoryManagerError)
        assert "owner_user_id 'alice'" in str(error.__cause__)
    assert manager._retriever.calls == []


def test_unreachable_context_read_fail_open_returns_no_injected_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unreachable_openviking_url: str,
) -> None:
    manager = _manager(
        tmp_path,
        monkeypatch,
        base_url=unreachable_openviking_url,
        timeout_seconds=0.1,
        failure_policy={"read": "fail_open"},
    )
    monkeypatch.setattr(
        "deerflow.agents.memory.get_memory_manager",
        lambda: manager,
    )
    monkeypatch.setattr(
        "deerflow.agents.middlewares.dynamic_context_middleware.resolve_runtime_user_id",
        lambda runtime: "alice",
    )
    middleware = _injection_middleware(manager)
    state = {"messages": [HumanMessage("answer this", id="message-1")]}

    assert manager.get_context("alice", agent_name="research") == ""
    update = middleware.before_agent(state, None)
    assert update is not None
    assert all(not str(message.id).endswith("__memory") for message in update["messages"])


@pytest.mark.asyncio
@pytest.mark.parametrize("read_policy", ["raise", "fail_open"])
async def test_unreachable_async_context_read_honors_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unreachable_openviking_url: str,
    read_policy: str,
) -> None:
    manager = _manager(
        tmp_path,
        monkeypatch,
        base_url=unreachable_openviking_url,
        timeout_seconds=0.1,
        failure_policy={"read": read_policy},
    )

    if read_policy == "raise":
        with pytest.raises(MemoryReadError) as exc_info:
            await manager.aget_context("alice", agent_name="research")
        assert exc_info.value.__cause__ is not None
    else:
        assert await manager.aget_context("alice", agent_name="research") == ""


@pytest.mark.asyncio
async def test_unreachable_context_read_raise_aborts_async_dynamic_context_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unreachable_openviking_url: str,
) -> None:
    manager = _manager(
        tmp_path,
        monkeypatch,
        base_url=unreachable_openviking_url,
        timeout_seconds=0.1,
        failure_policy={"read": "raise"},
    )
    monkeypatch.setattr(
        "deerflow.agents.memory.get_memory_manager",
        lambda: manager,
    )
    monkeypatch.setattr(
        "deerflow.agents.middlewares.dynamic_context_middleware.resolve_runtime_user_id",
        lambda runtime: "alice",
    )
    middleware = _injection_middleware(manager)
    state = {"messages": [HumanMessage("answer this", id="message-1")]}

    with pytest.raises(MemoryReadError) as exc_info:
        await middleware.abefore_agent(state, None)

    assert exc_info.value.__cause__ is not None


def test_manager_refuses_to_share_single_user_key_across_deerflow_users(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    strict = _manager(tmp_path / "strict", monkeypatch, failure_policy={"write": "raise"})
    write = {"thread_id": "thread-1", "messages": [HumanMessage("private", id="h1")], "user_id": "bob", "agent_name": "research"}

    with pytest.raises(MemoryManagerError, match="owner_user_id 'alice'"):
        manager.get_context("bob", agent_name="research")
    # The default write policy drops the refused write; `raise` propagates it.
    assert manager.add(**write) is None
    with pytest.raises(MemoryManagerError, match="owner_user_id 'alice'"):
        strict.add(**write)

    assert manager._retriever.calls == []
    assert manager._recorder.calls == []
    assert strict._recorder.calls == []


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
    assert manager._cleanup_done.wait(timeout=2.0)
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


def _multi_user_backend_config(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "base_url": "http://openviking:1933",
        "storage_path": str(tmp_path),
        "startup_policy": "warn",
        "retrieval": {
            "top_k": 4,
            "max_injection_chars": 1_000,
            "injection_query": "profile preferences and prior decisions",
        },
    }
    config.update(overrides)
    return config


def _track_official_integration(monkeypatch: pytest.MonkeyPatch) -> tuple[list[_Recorder], list[_Retriever]]:
    import deerflow.agents.memory.backends.openviking.openviking_manager as module

    recorders: list[_Recorder] = []
    retrievers: list[_Retriever] = []

    class _TrackedRecorder(_Recorder):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            recorders.append(self)

    class _TrackedRetriever(_Retriever):
        def __init__(self, *, client: _Client, **kwargs: Any) -> None:
            super().__init__(client=client, **kwargs)
            retrievers.append(self)

    monkeypatch.setattr(
        module,
        "_load_official_integration",
        lambda: {
            "OpenVikingCommitPolicy": _CommitPolicy,
            "OpenVikingPartialWriteError": _PartialWriteError,
            "OpenVikingRetriever": _TrackedRetriever,
            "OpenVikingSessionRecorder": _TrackedRecorder,
            "use_actor_peer": _use_actor_peer,
        },
    )
    return recorders, retrievers


def test_multi_user_config_validation_pool_masking_and_side_effect_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALICE_OV_KEY", "alice-env-secret-123")
    cfg = OpenVikingConfig.from_backend_config(
        _multi_user_backend_config(
            tmp_path,
            user_credentials={
                "alice": {"api_key_env": "ALICE_OV_KEY", "tenant_id": "acme"},
                "bob": {"api_key": "bob-inline-secret-456"},
            },
            client_pool={"max_clients": 16, "idle_ttl_seconds": 120.5},
        )
    )
    assert cfg.isolation_mode == "multi_user"
    assert cfg.owner_user_id is None
    assert cfg.api_key_env is None
    assert cfg.api_key == ""
    assert cfg.pool_max_clients == 16
    assert cfg.pool_idle_ttl_seconds == 120.5
    assert cfg.user_credentials["alice"].api_key == "alice-env-secret-123"
    assert cfg.user_credentials["alice"].api_key_env == "ALICE_OV_KEY"
    assert cfg.user_credentials["alice"].tenant_id == "acme"
    assert cfg.user_credentials["bob"].api_key == "bob-inline-secret-456"
    assert cfg.user_credentials["bob"].tenant_id is None
    for secret in ("alice-env-secret-123", "bob-inline-secret-456"):
        assert secret not in repr(cfg)
    assert "alice-env-secret-123" not in repr(cfg.user_credentials["alice"])

    # Defaults and explicit null idle_ttl_seconds disabling TTL eviction
    default_pool_cfg = OpenVikingConfig.from_backend_config(_multi_user_backend_config(tmp_path, user_credentials={"alice": {"api_key": "alice-key"}}))
    assert default_pool_cfg.pool_max_clients == 64
    assert default_pool_cfg.pool_idle_ttl_seconds == 900.0

    no_ttl_cfg = OpenVikingConfig.from_backend_config(
        _multi_user_backend_config(
            tmp_path,
            user_credentials={"alice": {"api_key": "alice-key"}},
            client_pool={"idle_ttl_seconds": None},
        )
    )
    assert no_ttl_cfg.pool_idle_ttl_seconds is None

    # Side-effect-free validation: must never import credential_provider
    nonexistent_pkg = "nonexistent_ov_provider_pkg_for_test"
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(AssertionError(f"unexpected import: {name}")),
    )
    provider_cfg = OpenVikingConfig.from_backend_config(
        _multi_user_backend_config(
            tmp_path,
            credential_provider=f"{nonexistent_pkg}.mod:VaultProvider",
            credential_provider_config={"endpoint": "https://vault.internal", "api_key": "vault-secret-999"},
        )
    )
    assert provider_cfg.isolation_mode == "multi_user"
    assert provider_cfg.credential_provider == f"{nonexistent_pkg}.mod:VaultProvider"
    assert "vault-secret-999" not in repr(provider_cfg)
    assert nonexistent_pkg not in sys.modules

    # Also accepted with dot separator and injected provider hook
    dot_cfg = OpenVikingConfig.from_backend_config(_multi_user_backend_config(tmp_path, credential_provider=f"{nonexistent_pkg}.mod.VaultProvider"))
    assert dot_cfg.credential_provider == f"{nonexistent_pkg}.mod.VaultProvider"
    injected_cfg = OpenVikingConfig.from_backend_config(
        _multi_user_backend_config(tmp_path, client_pool={"max_clients": 8}),
        has_injected_credential_provider=True,
    )
    assert injected_cfg.isolation_mode == "multi_user"
    assert injected_cfg.pool_max_clients == 8
    monkeypatch.setenv("OPENVIKING_API_KEY", "single-user-secret")
    single_empty_pool_cfg = OpenVikingConfig.from_backend_config(
        _backend_config(tmp_path, client_pool={}),
    )
    assert single_empty_pool_cfg.isolation_mode == "single_user"
    assert OpenVikingConfig.from_backend_config(_backend_config(tmp_path, client_pool=None)).isolation_mode == "single_user"
    with pytest.raises(ValueError, match="credential_provider_config requires credential_provider"):
        OpenVikingConfig.from_backend_config(
            _multi_user_backend_config(tmp_path, credential_provider_config={"namespace": "prod"}),
            has_injected_credential_provider=True,
        )

    # read_failures_are_fatal_for_config supports multi-user configs without importing provider
    assert (
        OpenVikingMemoryManager.read_failures_are_fatal_for_config(
            _multi_user_backend_config(
                tmp_path,
                credential_provider=f"{nonexistent_pkg}.mod:VaultProvider",
                failure_policy={"read": "fail_open"},
            )
        )
        is False
    )
    assert (
        OpenVikingMemoryManager.read_failures_are_fatal_for_config(
            _multi_user_backend_config(
                tmp_path,
                credential_provider=f"{nonexistent_pkg}.mod:VaultProvider",
                failure_policy={"read": "raise"},
            )
        )
        is True
    )


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"user_credentials": {"alice": {"api_key": "a-key"}}, "owner_user_id": "alice"}, "owner_user_id and api_key_env"),
        ({"user_credentials": {"alice": {"api_key": "a-key"}}, "api_key_env": "ALICE_KEY"}, "owner_user_id and api_key_env"),
        ({"credential_provider": "pkg.mod:Provider", "owner_user_id": "alice"}, "owner_user_id and api_key_env"),
        ({"credential_provider": "pkg.mod:Provider", "api_key_env": "ALICE_KEY"}, "owner_user_id and api_key_env"),
        ({"user_credentials": {}}, "must not be empty"),
        ({"user_credentials": "not-a-dict"}, "user_credentials must be a mapping"),
        ({"user_credentials": {" alice": {"api_key": "a-key"}}}, "non-empty stripped"),
        ({"user_credentials": {"alice\x00": {"api_key": "a-key"}}}, "control characters"),
        ({"user_credentials": {"alice": "a-key"}}, r"user_credentials\.alice must be a mapping"),
        ({"user_credentials": {"alice": {"api_key": "a-key", "api_key_env": "ALICE_KEY"}}}, "exactly one of"),
        ({"user_credentials": {"alice": {"tenant_id": "acme"}}}, "exactly one of"),
        ({"user_credentials": {"alice": {"api_key": "a-key", "unknown": 1}}}, r"user_credentials\.alice\.unknown"),
        ({"user_credentials": {"alice": {"api_key_env": "MISSING_OV_KEY_TEST"}}}, "OpenViking USER API key is missing for user 'alice'; set MISSING_OV_KEY_TEST"),
        ({"user_credentials": {"alice": {"api_key": "dup-secret"}, "bob": {"api_key": "dup-secret"}}}, "must not share the same API key"),
        ({"user_credentials": {"alice": {"api_key": "bad key"}}}, "printable ASCII"),
        ({"user_credentials": {"alice": {"api_key": "bad\r\nkey"}}}, "printable ASCII"),
        ({"user_credentials": {"alice": {"api_key": "a-key", "tenant_id": ""}}}, r"user_credentials\.alice:.*tenant_id must not be empty"),
        ({"user_credentials": {"alice": {"api_key": "a-key", "tenant_id": 123}}}, r"user_credentials\.alice:.*tenant_id must be a string"),
        ({"user_credentials": {"alice": {"api_key": "a-key", "tenant_id": " acme"}}}, r"user_credentials\.alice:.*leading or trailing whitespace"),
        ({"user_credentials": {"alice": {"api_key": "a-key", "tenant_id": "t" * 129}}}, r"user_credentials\.alice:.*at most 128"),
        ({"user_credentials": {"alice": {"api_key": "a-key", "tenant_id": "ac\x00me"}}}, r"user_credentials\.alice:.*control characters"),
        ({"credential_provider": ""}, "must not be empty"),
        ({"credential_provider": "SingleName"}, "expected 'pkg.mod:Attr'"),
        ({"credential_provider": "pkg:mod:Attr"}, "at most one ':'"),
        ({"credential_provider": "pkg.class:Attr"}, "valid Python identifiers"),
        ({"owner_user_id": "alice", "credential_provider_config": {"endpoint": "x"}}, "requires credential_provider"),
        ({"owner_user_id": "alice", "client_pool": {"max_clients": 4}}, "client_pool is only supported in multi-user mode"),
        ({"owner_user_id": "alice", "client_pool": {"idle_ttl_seconds": 30.0}}, "client_pool is only supported in multi-user mode"),
        ({"user_credentials": {"alice": {"api_key": "a-key"}}, "client_pool": {"max_clients": True}}, r"client_pool\.max_clients must be an integer"),
        ({"user_credentials": {"alice": {"api_key": "a-key"}}, "client_pool": {"max_clients": 1.5}}, r"client_pool\.max_clients must be an integer"),
        ({"user_credentials": {"alice": {"api_key": "a-key"}}, "client_pool": {"max_clients": 0}}, "between 1 and 4096"),
        ({"user_credentials": {"alice": {"api_key": "a-key"}}, "client_pool": {"max_clients": 4097}}, "between 1 and 4096"),
        ({"user_credentials": {"alice": {"api_key": "a-key"}}, "client_pool": {"idle_ttl_seconds": False}}, r"client_pool\.idle_ttl_seconds must be a number"),
        ({"user_credentials": {"alice": {"api_key": "a-key"}}, "client_pool": {"idle_ttl_seconds": 0}}, "finite value > 0 or null"),
        ({"user_credentials": {"alice": {"api_key": "a-key"}}, "client_pool": {"idle_ttl_seconds": -5}}, "finite value > 0 or null"),
        ({"user_credentials": {"alice": {"api_key": "a-key"}}, "client_pool": {"idle_ttl_seconds": float("inf")}}, "finite value > 0 or null"),
        ({"user_credentials": {"alice": {"api_key": "a-key"}}, "client_pool": {"idle_ttl_seconds": float("nan")}}, "finite value > 0 or null"),
        ({"user_credentials": {"alice": {"api_key": "a-key"}}, "client_pool": {"idle_ttl_seconds": ""}}, "number or null, got empty str"),
        ({"user_credentials": {"alice": {"api_key": "a-key"}}, "client_pool": {"extra_knob": 1}}, r"client_pool\.extra_knob"),
        ({"user_credentials": {"alice": {"api_key": "a-key"}}, "auth_mode": "trusted"}, "trusted mode is no longer supported"),
    ],
)
def test_multi_user_config_rejects_invalid_inputs_and_never_leaks_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, Any],
    match: str,
) -> None:
    monkeypatch.setenv("ALICE_KEY", "secret-val")
    monkeypatch.delenv("MISSING_OV_KEY_TEST", raising=False)
    cfg = _multi_user_backend_config(tmp_path, **overrides)
    if "owner_user_id" not in overrides and "user_credentials" not in overrides and "credential_provider" not in overrides:
        cfg["owner_user_id"] = "alice"
    if cfg.get("owner_user_id") == "alice" and "api_key_env" not in cfg and "user_credentials" not in cfg and "credential_provider" not in cfg:
        cfg["api_key_env"] = "ALICE_KEY"

    with pytest.raises(ValueError, match=match) as exc_info:
        OpenVikingConfig.from_backend_config(cfg)

    for forbidden in ("dup-secret", "bad key", "bad\r\nkey"):
        assert forbidden not in str(exc_info.value)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        (None, "timeout_seconds", True),
        (None, "max_seen_message_ids", False),
        ("retrieval", "top_k", True),
        ("retrieval", "max_injection_chars", False),
        ("retrieval", "score_threshold", True),
    ],
)
def test_existing_numeric_knobs_reject_booleans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    section: str | None,
    key: str,
    value: bool,
) -> None:
    monkeypatch.setenv("OPENVIKING_API_KEY", "user-key")
    config = _backend_config(tmp_path)
    target = config if section is None else config[section]
    target[key] = value

    with pytest.raises(ValueError, match=f"OpenViking {key} must be a number"):
        OpenVikingConfig.from_backend_config(config)


def test_session_id_tenant_isolation_and_v1_backward_compat() -> None:
    v1_default = _session_id("alice", "research", "thread-1")
    v1_explicit_none = _session_id("alice", "research", "thread-1", tenant_id=None)
    expected_v1 = f"df_{hashlib.sha256(b'deerflow-openviking-adapter-v1\0alice\0research\0thread-1').hexdigest()[:48]}"
    assert v1_default == v1_explicit_none == expected_v1

    acme = _session_id("alice", "research", "thread-1", tenant_id="acme")
    globex = _session_id("alice", "research", "thread-1", tenant_id="globex")
    expected_acme = f"df_{hashlib.sha256(b'deerflow-openviking-adapter-v2\0acme\0alice\0research\0thread-1').hexdigest()[:48]}"
    assert acme == expected_acme
    assert len({v1_default, acme, globex}) == 3
    # Null-byte delimiter separation prevents boundary collisions
    assert _session_id("bc", "research", "thread-1", tenant_id="a") != _session_id("c", "research", "thread-1", tenant_id="ab")


def test_multi_user_real_loopback_http_isolation_and_warm_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_cli_config: Path,
    openviking_http_server: tuple[str, list[dict[str, Any]]],
) -> None:
    monkeypatch.setenv("OPENVIKING_API_KEY", "ambient-key-must-never-leak")
    monkeypatch.setenv("ALICE_ACME_KEY", "alice-acme-secret")
    monkeypatch.setenv("BOB_GLOBEX_KEY", "bob-globex-secret")
    isolated_cli_config.write_text(
        json.dumps(
            {
                "url": "http://unused.invalid",
                "api_key": "cli-key-must-never-leak",
                "extra_headers": {"X-CLI-Only": "must-not-leak", "X-API-Key": "cli-header-key"},
            }
        ),
        encoding="utf-8",
    )

    base_url, requests = openviking_http_server
    manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(
            tmp_path,
            base_url=base_url,
            timeout_seconds=2,
            startup_policy="fail_fast",
            failure_policy={"read": "raise"},
            user_credentials={
                "alice": {"api_key_env": "ALICE_ACME_KEY", "tenant_id": "acme"},
                "bob": {"api_key_env": "BOB_GLOBEX_KEY", "tenant_id": "globex"},
            },
        )
    )
    try:
        assert manager.warm() is True
        assert len(requests) == 1
        assert requests[0]["path"] == "/health"
        assert "x-api-key" not in requests[0]["headers"]
        assert "x-cli-only" not in requests[0]["headers"]
        assert "authorization" not in requests[0]["headers"]

        shared_thread = "shared-thread-1"
        alice_msgs = [HumanMessage("Alice prefers dark mode", id="ah1"), AIMessage("Noted", id="aa1")]
        bob_msgs = [HumanMessage("Bob prefers light mode", id="bh1"), AIMessage("Noted", id="ba1")]

        manager.add(shared_thread, alice_msgs, user_id="alice")
        manager.add(shared_thread, bob_msgs, user_id="bob")

        alice_ctx = manager.get_context("alice", thread_id=shared_thread)
        bob_ctx = manager.get_context("bob", thread_id=shared_thread)
        assert "Prefers concise answers." in alice_ctx
        assert "Prefers concise answers." in bob_ctx

        alice_facts = manager.search("theme", top_k=2, user_id="alice")
        bob_facts = manager.search("theme", top_k=2, user_id="bob")
        assert len(alice_facts) == 1 and len(bob_facts) == 1

        alice_sid = _session_id("alice", "deerflow", shared_thread, tenant_id="acme")
        bob_sid = _session_id("bob", "deerflow", shared_thread, tenant_id="globex")
        assert alice_sid != bob_sid

        alice_reqs = [r for r in requests[1:] if r["headers"].get("x-api-key") == "alice-acme-secret"]
        bob_reqs = [r for r in requests[1:] if r["headers"].get("x-api-key") == "bob-globex-secret"]
        assert len(alice_reqs) == 4  # batch, commit, search/search, search/find
        assert len(bob_reqs) == 4
        assert len(requests) == 1 + 4 + 4

        assert alice_reqs[0]["path"] == f"/api/v1/sessions/{alice_sid}/messages/batch"
        assert alice_reqs[1]["path"] == f"/api/v1/sessions/{alice_sid}/commit"
        assert alice_reqs[2]["path"] == "/api/v1/search/search"
        assert alice_reqs[2]["payload"]["session_id"] == alice_sid
        assert alice_reqs[3]["path"] == "/api/v1/search/find"

        assert bob_reqs[0]["path"] == f"/api/v1/sessions/{bob_sid}/messages/batch"
        assert bob_reqs[1]["path"] == f"/api/v1/sessions/{bob_sid}/commit"
        assert bob_reqs[2]["path"] == "/api/v1/search/search"
        assert bob_reqs[2]["payload"]["session_id"] == bob_sid
        assert bob_reqs[3]["path"] == "/api/v1/search/find"

        for req in requests:
            headers_str = json.dumps(req["headers"])
            for forbidden in ("ambient-key-must-never-leak", "cli-key-must-never-leak", "cli-header-key", "x-cli-only"):
                assert forbidden not in headers_str

        # Isolated capture cursors: repeating alice does not re-send or affect bob
        before = len(requests)
        manager.add(shared_thread, alice_msgs, user_id="alice")
        assert len(requests) == before
        assert manager._state_path(alice_sid).exists()
        assert manager._state_path(bob_sid).exists()
    finally:
        manager.close()


def test_multi_user_warm_honors_startup_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unreachable_openviking_url: str,
) -> None:
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1,localhost,::1")

    state = {"status_code": 503, "body": {"status": "degraded"}}

    class _HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            encoded = json.dumps(state["body"]).encode("utf-8")
            self.send_response(state["status_code"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        health_url = f"http://127.0.0.1:{server.server_port}"
        for bad_state in (
            {"status_code": 503, "body": {"status": "ok"}},
            {"status_code": 200, "body": {"status": "degraded"}},
        ):
            state.update(bad_state)
            strict_mgr = OpenVikingMemoryManager.from_config(
                _multi_user_backend_config(
                    tmp_path,
                    base_url=health_url,
                    startup_policy="fail_fast",
                    user_credentials={"alice": {"api_key": "alice-key"}},
                )
            )
            warn_mgr = OpenVikingMemoryManager.from_config(
                _multi_user_backend_config(
                    tmp_path,
                    base_url=health_url,
                    startup_policy="warn",
                    user_credentials={"alice": {"api_key": "alice-key"}},
                )
            )
            try:
                with pytest.raises(MemoryManagerError, match="unhealthy"):
                    strict_mgr.warm()
                assert warn_mgr.warm() is False
            finally:
                strict_mgr.close()
                warn_mgr.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()

    unreachable_strict = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(
            tmp_path,
            base_url=unreachable_openviking_url,
            timeout_seconds=0.1,
            startup_policy="fail_fast",
            user_credentials={"alice": {"api_key": "alice-key"}},
        )
    )
    unreachable_warn = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(
            tmp_path,
            base_url=unreachable_openviking_url,
            timeout_seconds=0.1,
            startup_policy="warn",
            user_credentials={"alice": {"api_key": "alice-key"}},
        )
    )
    try:
        with pytest.raises(MemoryManagerError, match="startup validation failed"):
            unreachable_strict.warm()
        assert unreachable_warn.warm() is False
    finally:
        unreachable_strict.close()
        unreachable_warn.close()


@pytest.mark.parametrize("write_policy", ["log_and_drop", "raise"])
@pytest.mark.parametrize("read_policy", ["fail_open", "raise"])
@pytest.mark.parametrize("bad_user", [None, "", "   ", "unmapped-user"])
def test_multi_user_fail_closed_for_missing_blank_and_unmapped_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    write_policy: str,
    read_policy: str,
    bad_user: str | None,
) -> None:
    recorders, retrievers = _track_official_integration(monkeypatch)
    manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(
            tmp_path,
            failure_policy={"read": read_policy, "write": write_policy},
            user_credentials={"alice": {"api_key": "alice-secret"}},
        )
    )
    try:
        with caplog.at_level(logging.ERROR, logger=OpenVikingMemoryManager.__module__):
            if write_policy == "raise":
                with pytest.raises(MemoryManagerError):
                    manager.add("thread-1", [HumanMessage("secret", id="h1")], user_id=bad_user)
            else:
                assert manager.add("thread-1", [HumanMessage("secret", id="h1")], user_id=bad_user) is None
                assert any("Dropping the memory write" in record.getMessage() for record in caplog.records)
                assert "secret" not in caplog.text

        expected_read_exc = MemoryReadError if read_policy == "raise" else MemoryManagerError
        with pytest.raises(expected_read_exc) as ctx_exc:
            manager.get_context(bad_user, thread_id="thread-1")
        with pytest.raises(expected_read_exc) as search_exc:
            manager.search("prefs", user_id=bad_user)

        if read_policy == "raise":
            assert isinstance(ctx_exc.value.__cause__, MemoryManagerError)
            assert isinstance(search_exc.value.__cause__, MemoryManagerError)
        assert recorders == []
        assert retrievers == []
        assert not list((tmp_path / "openviking").rglob("*.json"))
    finally:
        manager.close()


@pytest.mark.parametrize(
    "bad_return",
    [
        None,
        12345,
        ["super-secret-list"],
        {"tenant_id": "acme"},
        {"api_key": "super-secret-extra", "extra_field": "super-secret-field"},
        {123: "super-secret-non-str-key"},
        {"api_key": "super-secret-bad-tenant", "tenant_id": 999},
        "super-secret-crlf\r\nX-Injected: evil",
        "super-secret with space",
        {"api_key": "super-secret\nnewline"},
    ],
)
def test_multi_user_fail_closed_on_malformed_or_illegal_provider_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_return: Any,
) -> None:
    recorders, retrievers = _track_official_integration(monkeypatch)
    calls: list[str] = []

    def bad_provider(user_id: str) -> Any:
        calls.append(user_id)
        return bad_return

    manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(tmp_path, failure_policy={"read": "raise", "write": "raise"}),
        credential_provider=bad_provider,
    )
    try:
        with pytest.raises(MemoryManagerError) as add_exc:
            manager.add("thread-1", [HumanMessage("hi", id="h1")], user_id="mallory")
        with pytest.raises(MemoryReadError) as read_exc:
            manager.get_context("mallory")

        assert len(calls) == 2
        for exc in (add_exc.value, read_exc.value):
            assert "super-secret" not in str(exc)
            assert "evil" not in str(exc)
        assert recorders == []
        assert retrievers == []
    finally:
        manager.close()


def test_multi_user_fail_closed_when_provider_raises_never_leaks_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorders, _ = _track_official_integration(monkeypatch)
    invoked = False

    def failing_provider(user_id: str) -> Any:
        nonlocal invoked
        invoked = True
        raise RuntimeError(f"vault failure for {user_id}: sk-vault-secret-999")

    manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(tmp_path, failure_policy={"read": "raise", "write": "raise"}),
        credential_provider=failing_provider,
    )
    drop_manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(tmp_path / "drop", failure_policy={"read": "raise", "write": "log_and_drop"}),
        credential_provider=failing_provider,
    )
    try:
        with pytest.raises(MemoryManagerError, match="RuntimeError") as add_exc:
            manager.add("thread-1", [HumanMessage("hi", id="h1")], user_id="alice")
        assert invoked is True
        assert "sk-vault-secret-999" not in str(add_exc.value)
        assert add_exc.value.__cause__ is None

        with caplog.at_level(logging.ERROR, logger=OpenVikingMemoryManager.__module__):
            assert drop_manager.add("thread-1", [HumanMessage("top-secret-msg", id="h1")], user_id="alice") is None
        assert "sk-vault-secret-999" not in caplog.text
        assert "top-secret-msg" not in caplog.text
        assert any("RuntimeError" in record.getMessage() and "Dropping the memory write" in record.getMessage() for record in caplog.records)

        with pytest.raises(MemoryReadError, match="RuntimeError") as read_exc:
            manager.search("prefs", user_id="alice")
        assert "sk-vault-secret-999" not in str(read_exc.value)
        assert recorders == []
    finally:
        manager.close()
        drop_manager.close()


def test_provider_memory_read_error_respects_configured_read_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deerflow.agents import memory as memory_pkg
    from deerflow.agents.lead_agent.prompt import _get_memory_context
    from deerflow.config.app_config import AppConfig
    from deerflow.config.memory_config import MemoryConfig
    from deerflow.config.sandbox_config import SandboxConfig

    recorders, retrievers = _track_official_integration(monkeypatch)

    def failing_provider(user_id: str) -> Any:
        raise MemoryReadError(f"vault outage for {user_id}: sk-vault-secret-999")

    fail_open_mgr = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(tmp_path / "open", failure_policy={"read": "fail_open"}),
        credential_provider=failing_provider,
    )
    raise_mgr = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(tmp_path / "raise", failure_policy={"read": "raise"}),
        credential_provider=failing_provider,
    )
    try:
        with pytest.raises(MemoryManagerError, match="MemoryReadError") as ctx_exc:
            fail_open_mgr.get_context("alice")
        assert type(ctx_exc.value) is MemoryManagerError
        assert ctx_exc.value.__cause__ is None
        assert "sk-vault-secret-999" not in str(ctx_exc.value)

        with pytest.raises(MemoryManagerError, match="MemoryReadError") as search_exc:
            fail_open_mgr.search("prefs", user_id="alice")
        assert type(search_exc.value) is MemoryManagerError
        assert search_exc.value.__cause__ is None
        assert "sk-vault-secret-999" not in str(search_exc.value)

        fail_open_app_cfg = AppConfig(
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
            memory=MemoryConfig(
                enabled=True,
                injection_enabled=True,
                manager_class="openviking",
                backend_config=fail_open_mgr.backend_config,
            ),
        )
        monkeypatch.setattr(memory_pkg, "get_memory_manager", lambda: fail_open_mgr)
        assert _get_memory_context(app_config=fail_open_app_cfg, user_id="alice") == ""

        with pytest.raises(MemoryReadError) as strict_exc:
            raise_mgr.get_context("alice")
        assert isinstance(strict_exc.value.__cause__, MemoryManagerError)
        assert "sk-vault-secret-999" not in str(strict_exc.value)
        assert "sk-vault-secret-999" not in str(strict_exc.value.__cause__)

        strict_app_cfg = AppConfig(
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
            memory=MemoryConfig(
                enabled=True,
                injection_enabled=True,
                manager_class="openviking",
                backend_config=raise_mgr.backend_config,
            ),
        )
        monkeypatch.setattr(memory_pkg, "get_memory_manager", lambda: raise_mgr)
        with pytest.raises(MemoryReadError):
            _get_memory_context(app_config=strict_app_cfg, user_id="alice")

        assert recorders == []
        assert retrievers == []
    finally:
        fail_open_mgr.close()
        raise_mgr.close()


def test_dynamic_credential_provider_class_callable_and_hook_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorders, _ = _track_official_integration(monkeypatch)
    pkg_dir = tmp_path / "dyn_ov_providers"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "mod.py").write_text(
        "class DictProvider:\n"
        "    def __init__(self, prefix: str, tenant: str | None = None) -> None:\n"
        "        self.prefix = prefix\n"
        "        self.tenant = tenant\n"
        "        self.closed = False\n"
        "    def resolve(self, user_id: str):\n"
        "        return {'api_key': f'{self.prefix}-{user_id}', 'tenant_id': self.tenant}\n"
        "    def close(self) -> None:\n"
        "        self.closed = True\n"
        "\n"
        "def fn_provider(user_id: str):\n"
        "    return f'fn-key-{user_id}'\n"
        "\n"
        "def factory_provider(suffix: str):\n"
        "    return lambda user_id: {'api_key': f'{user_id}-{suffix}'}\n"
        "\n"
        "NOT_CALLABLE = 42\n"
        "\n"
        "class BadProvider:\n"
        "    pass\n"
        "\n"
        "def bad_factory(flag: bool):\n"
        "    return 123\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        validate_provider_path("dyn_ov_providers.mod:DictProvider")
        with pytest.raises(ValueError, match="must resolve to a class or callable"):
            load_credential_provider("dyn_ov_providers.mod:NOT_CALLABLE", {})
        with pytest.raises(ValueError, match="must define a callable 'resolve"):
            load_credential_provider("dyn_ov_providers.mod:BadProvider", {})
        with pytest.raises(ValueError, match="factory"):
            load_credential_provider("dyn_ov_providers.mod:bad_factory", {"flag": True})
        cred = normalize_resolved_credential({"api_key": "norm-key", "tenant_id": "acme"}, user_id="alice")
        assert cred is not None and cred.api_key == "norm-key" and cred.tenant_id == "acme"
        assert normalize_resolved_credential(cred, user_id="alice") is cred
        # 1. Class path with credential_provider_config
        cls_mgr = OpenVikingMemoryManager.from_config(
            _multi_user_backend_config(
                tmp_path,
                credential_provider="dyn_ov_providers.mod:DictProvider",
                credential_provider_config={"prefix": "cls", "tenant": "acme"},
            )
        )
        try:
            assert isinstance(cls_mgr._credential_provider, OpenVikingCredentialProvider)
            cls_mgr.add("t1", [HumanMessage("hi", id="h1")], user_id="alice")
            assert recorders[-1].connection["api_key"] == "cls-alice"
            assert cls_mgr._state_path(_session_id("alice", "deerflow", "t1", tenant_id="acme")).exists()
        finally:
            assert cls_mgr.shutdown_flush(2.0) is True
            assert cls_mgr._credential_provider.closed is True

        # 2. Direct callable path (no config)
        fn_mgr = OpenVikingMemoryManager.from_config(_multi_user_backend_config(tmp_path, credential_provider="dyn_ov_providers.mod.fn_provider"))
        try:
            fn_mgr.search("prefs", user_id="bob")
            assert recorders[-1].connection["api_key"] == "fn-key-bob"
        finally:
            fn_mgr.close()

        # 3. Factory callable path (with config)
        fac_mgr = OpenVikingMemoryManager.from_config(
            _multi_user_backend_config(
                tmp_path,
                credential_provider="dyn_ov_providers.mod:factory_provider",
                credential_provider_config={"suffix": "v2"},
            )
        )
        try:
            fac_mgr.get_context("carol")
            assert recorders[-1].connection["api_key"] == "carol-v2"
        finally:
            fac_mgr.close()

        # 4. Injected host_hooks["credential_provider"]
        hook_mgr = OpenVikingMemoryManager.from_config(
            _multi_user_backend_config(tmp_path),
            credential_provider=lambda uid: OpenVikingCredential(api_key=f"hook-{uid}", tenant_id="t-hook"),
        )
        strict_hook_mgr = OpenVikingMemoryManager.from_config(
            _multi_user_backend_config(tmp_path, failure_policy={"read": "raise"}),
            credential_provider=lambda uid: OpenVikingCredential(api_key=f"hook-{uid}", tenant_id="t-hook"),
        )
        try:
            assert hook_mgr.read_failures_are_fatal is False
            assert strict_hook_mgr.read_failures_are_fatal is True
            hook_mgr.add("t2", [HumanMessage("hi", id="h1")], user_id="dave")
            assert recorders[-1].connection["api_key"] == "hook-dave"
            assert hook_mgr._state_path(_session_id("dave", "deerflow", "t2", tenant_id="t-hook")).exists()
        finally:
            hook_mgr.close()
            strict_hook_mgr.close()

        # Cannot specify both config credential_provider and injected hook
        with pytest.raises(ValueError, match="cannot configure both"):
            OpenVikingMemoryManager.from_config(
                _multi_user_backend_config(tmp_path, credential_provider="dyn_ov_providers.mod:fn_provider"),
                credential_provider=lambda uid: "x",
            )
        with pytest.raises(ValueError, match="injected credential_provider"):
            OpenVikingMemoryManager.from_config(
                _multi_user_backend_config(tmp_path),
                credential_provider="not-callable",
            )
    finally:
        for mod_name in list(sys.modules):
            if mod_name == "dyn_ov_providers" or mod_name.startswith("dyn_ov_providers."):
                monkeypatch.delitem(sys.modules, mod_name, raising=False)


def test_dynamic_provider_key_rotation_revocation_and_cross_identity_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorders, _ = _track_official_integration(monkeypatch)
    keys: dict[str, str | None] = {"alice": "alice-v1", "bob": "bob-v1"}

    class _DynamicProvider:
        def resolve(self, user_id: str) -> str | None:
            return keys.get(user_id)

    manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(tmp_path, failure_policy={"read": "raise", "write": "raise"}),
        credential_provider=_DynamicProvider(),
    )
    try:
        # Initial acquisition
        manager.add("t1", [HumanMessage("m1", id="m1")], user_id="alice")
        assert len(recorders) == 1
        rec_v1 = recorders[0]
        assert rec_v1.connection["api_key"] == "alice-v1"
        assert rec_v1.closed is False

        # Idle key rotation: creates new recorder and immediately closes old idle one
        keys["alice"] = "alice-v2"
        manager.add("t1", [HumanMessage("m1", id="m1"), HumanMessage("m2", id="m2")], user_id="alice")
        assert len(recorders) == 2
        rec_v2 = recorders[1]
        assert rec_v2.connection["api_key"] == "alice-v2"
        assert rec_v1.closed is True
        assert rec_v2.closed is False

        # In-flight key rotation: old recorder stays open until in-flight op finishes
        started = threading.Event()
        release = threading.Event()
        orig_record = rec_v2.record

        def blocked_record(*args: Any, **kwargs: Any) -> object:
            started.set()
            assert release.wait(5.0)
            return orig_record(*args, **kwargs)

        rec_v2.record = blocked_record
        t_inflight = threading.Thread(
            target=manager.add,
            args=("t-inflight", [HumanMessage("slow", id="s1")]),
            kwargs={"user_id": "alice"},
        )
        t_inflight.start()
        assert started.wait(5.0)

        keys["alice"] = "alice-v3"
        manager.search("prefs", user_id="alice")
        assert len(recorders) == 3
        rec_v3 = recorders[2]
        assert rec_v3.connection["api_key"] == "alice-v3"
        assert rec_v2.closed is False

        release.set()
        t_inflight.join(5.0)
        assert not t_inflight.is_alive()
        assert rec_v2.closed is True
        assert rec_v3.closed is False

        # Cross-identity key-reuse rejection in runtime pool
        keys["bob"] = "alice-v3"
        with pytest.raises(MemoryManagerError, match="cannot be shared across distinct DeerFlow scopes"):
            manager.add("t1", [HumanMessage("leak", id="l1")], user_id="bob")
        with pytest.raises(MemoryReadError, match="cannot be shared across distinct DeerFlow scopes"):
            manager.get_context("bob")
        assert len(recorders) == 3
        assert rec_v3.closed is False

        # Revocation retires cached handle immediately and refuses next call
        keys["alice"] = None
        with pytest.raises(MemoryManagerError, match="No OpenViking USER API key"):
            manager.add("t1", [HumanMessage("after revoke", id="r1")], user_id="alice")
        assert rec_v3.closed is True

        # Re-granting later creates a fresh recorder instead of reusing retired one
        keys["alice"] = "alice-v3"
        manager.search("prefs", user_id="alice")
        assert len(recorders) == 4
        assert recorders[3] is not rec_v3
        assert recorders[3].closed is False
    finally:
        manager.close()


def test_client_pool_lru_eviction_and_inflight_refcount_safety(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorders, _ = _track_official_integration(monkeypatch)
    manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(
            tmp_path,
            client_pool={"max_clients": 2},
            user_credentials={
                "alice": {"api_key": "k-alice"},
                "bob": {"api_key": "k-bob"},
                "carol": {"api_key": "k-carol"},
            },
        )
    )
    try:
        manager.search("q", user_id="alice")
        manager.search("q", user_id="bob")
        # Refresh alice so bob becomes LRU
        manager.search("q", user_id="alice")
        rec_alice, rec_bob = recorders
        assert rec_alice.closed is False
        assert rec_bob.closed is False

        # Adding carol evicts idle LRU bob
        manager.search("q", user_id="carol")
        assert len(recorders) == 3
        rec_carol = recorders[2]
        assert rec_bob.closed is True
        assert rec_alice.closed is False
        assert rec_carol.closed is False

        # Now alice is LRU and carol is MRU. Park alice in-flight: idle carol should be evicted first
        started_a = threading.Event()
        release_a = threading.Event()
        orig_a_record = rec_alice.record

        def slow_a(*args: Any, **kwargs: Any) -> object:
            started_a.set()
            assert release_a.wait(5.0)
            return orig_a_record(*args, **kwargs)

        rec_alice.record = slow_a
        t_a = threading.Thread(target=manager.add, args=("t1", [HumanMessage("a", id="a1")]), kwargs={"user_id": "alice"})
        t_a.start()
        assert started_a.wait(5.0)

        manager.search("q", user_id="bob")
        rec_bob_2 = recorders[3]
        assert rec_carol.closed is True
        assert rec_alice.closed is False
        assert rec_bob_2.closed is False

        # Now bob_2 is busy too; carol enters when BOTH pooled entries are busy -> alice (oldest) evicted from pool, close deferred
        started_b = threading.Event()
        release_b = threading.Event()
        orig_b_record = rec_bob_2.record

        def slow_b(*args: Any, **kwargs: Any) -> object:
            started_b.set()
            assert release_b.wait(5.0)
            return orig_b_record(*args, **kwargs)

        rec_bob_2.record = slow_b
        t_b = threading.Thread(target=manager.add, args=("t2", [HumanMessage("b", id="b1")]), kwargs={"user_id": "bob"})
        t_b.start()
        assert started_b.wait(5.0)

        manager.search("q", user_id="carol")
        assert len(recorders) == 5
        # Deferred close: alice was evicted while active_ops == 1, so it MUST still be open
        assert rec_alice.closed is False

        release_a.set()
        release_b.set()
        t_a.join(5.0)
        t_b.join(5.0)
        assert not t_a.is_alive() and not t_b.is_alive()
        assert rec_alice.closed is True
        assert rec_bob_2.closed is False
    finally:
        manager.close()


def test_client_pool_idle_ttl_eviction_and_null_ttl_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorders, _ = _track_official_integration(monkeypatch)
    now = [100.0]

    manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(
            tmp_path,
            client_pool={"max_clients": 4, "idle_ttl_seconds": 30.0},
            user_credentials={
                "alice": {"api_key": "k-alice"},
                "bob": {"api_key": "k-bob"},
            },
        )
    )
    manager._clock = lambda: now[0]
    try:
        manager.search("q", user_id="alice")
        now[0] = 120.0
        manager.search("q", user_id="bob")
        rec_alice, rec_bob = recorders

        # At t=130.0: alice idle 30.0s (>= 30.0 -> evicted), bob idle 10.0s (< 30.0 -> retained)
        now[0] = 130.0
        manager.search("q", user_id="bob")
        assert rec_alice.closed is True
        assert rec_bob.closed is False
        assert len(recorders) == 2

        # Re-acquiring alice builds a fresh recorder
        manager.search("q", user_id="alice")
        assert len(recorders) == 3
        assert recorders[2].closed is False
    finally:
        manager.close()

    # Explicit null disables TTL eviction completely
    recorders2, _ = _track_official_integration(monkeypatch)
    now2 = [0.0]
    no_ttl_mgr = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(
            tmp_path / "no-ttl",
            client_pool={"idle_ttl_seconds": None},
            user_credentials={
                "alice": {"api_key": "k-alice"},
                "bob": {"api_key": "k-bob"},
            },
        )
    )
    no_ttl_mgr._clock = lambda: now2[0]
    try:
        no_ttl_mgr.search("q", user_id="alice")
        now2[0] = 100_000.0
        no_ttl_mgr.search("q", user_id="bob")
        no_ttl_mgr.search("q", user_id="alice")
        assert len(recorders2) == 2
        assert all(not r.closed for r in recorders2)
    finally:
        no_ttl_mgr.close()


def test_client_pool_concurrent_stress_and_shutdown_flush(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorders, _ = _track_official_integration(monkeypatch)
    provider_closed = False

    class _StressProvider:
        def resolve(self, user_id: str) -> dict[str, Any]:
            return {"api_key": f"stress-key-{user_id}", "tenant_id": f"tenant-{user_id}"}

        def close(self) -> None:
            nonlocal provider_closed
            provider_closed = True

    manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(tmp_path, client_pool={"max_clients": 2}),
        credential_provider=_StressProvider(),
    )

    users = ["alice", "bob", "carol", "dave"]
    barrier = threading.Barrier(len(users))
    errors: list[BaseException] = []

    def worker(uid: str) -> None:
        try:
            barrier.wait(5.0)
            for idx in range(5):
                manager.add(f"thread-{idx}", [HumanMessage(f"{uid}-{idx}", id=f"{uid}-{idx}")], user_id=uid)
                ctx = manager.get_context(uid, thread_id=f"thread-{idx}")
                facts = manager.search("prefs", user_id=uid)
                assert "Prefers concise answers." in ctx
                assert len(facts) == 1
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(uid,)) for uid in users]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(10.0)
            assert not t.is_alive()
        assert errors == []
        assert recorders

        for rec in recorders:
            expected_key = rec.connection["api_key"]
            uid = expected_key.removeprefix("stress-key-")
            for sid, _, _, _ in rec.calls:
                assert sid.startswith("df_")
                assert any(sid == _session_id(uid, "deerflow", f"thread-{idx}", tenant_id=f"tenant-{uid}") for idx in range(5))
    finally:
        assert manager.shutdown_flush(5.0) is True

    assert provider_closed is True
    assert all(rec.closed and rec.client.closed for rec in recorders)
    assert len(manager._pool) == 0
    assert manager.shutdown_flush(1.0) is True


def test_multi_user_shutdown_flush_drains_inflight_and_closes_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorders, _ = _track_official_integration(monkeypatch)
    close_calls = 0

    class _ClosableProvider:
        def resolve(self, user_id: str) -> str:
            return f"key-{user_id}"

        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1
            raise RuntimeError("best-effort close")

    manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(tmp_path),
        credential_provider=_ClosableProvider(),
    )
    manager.search("warmup", user_id="bob")
    manager.search("warmup", user_id="alice")
    rec_bob, rec_alice = recorders

    started = threading.Event()
    release = threading.Event()
    orig_record = rec_alice.record

    def blocking_record(*args: Any, **kwargs: Any) -> object:
        started.set()
        assert release.wait(5.0)
        return orig_record(*args, **kwargs)

    rec_alice.record = blocking_record
    writer = threading.Thread(
        target=manager.add,
        args=("thread-1", [HumanMessage("hello", id="h1")]),
        kwargs={"user_id": "alice"},
    )
    writer.start()
    try:
        assert started.wait(5.0)
        assert manager.shutdown_flush(0.0) is False
        assert rec_alice.closed is False
        assert rec_bob.closed is False
        assert close_calls == 0
    finally:
        release.set()
        writer.join(5.0)

    assert not writer.is_alive()
    assert manager._cleanup_done.wait(timeout=2.0)
    assert rec_alice.closed is True
    assert rec_bob.closed is True
    assert close_calls == 1
    assert manager.shutdown_flush(1.0) is True
    assert close_calls == 1


def test_shutdown_flush_drains_admitted_write_pending_credential_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorders, _ = _track_official_integration(monkeypatch)
    resolve_started = threading.Event()
    release_resolve = threading.Event()
    provider_calls: list[str] = []
    close_calls = 0

    class _BlockingProvider:
        def resolve(self, user_id: str) -> str:
            provider_calls.append(user_id)
            if user_id == "alice":
                resolve_started.set()
                assert release_resolve.wait(timeout=5.0)
            return f"key-{user_id}"

        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1

    manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(tmp_path),
        credential_provider=_BlockingProvider(),
    )

    write_errors: list[BaseException] = []
    flush_results: list[bool] = []

    def _write_alice() -> None:
        try:
            manager.add(
                "thread-1",
                [HumanMessage("admitted before shutdown", id="h1")],
                user_id="alice",
            )
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            write_errors.append(exc)

    def _run_shutdown() -> None:
        flush_results.append(manager.shutdown_flush(5.0))

    writer = threading.Thread(target=_write_alice)
    writer.start()
    shutdown_thread = threading.Thread(target=_run_shutdown)
    try:
        assert resolve_started.wait(timeout=5.0)
        shutdown_thread.start()

        deadline = time.monotonic() + 5.0
        while not manager._closed and time.monotonic() < deadline:
            time.sleep(0.01)
        assert manager._closed is True

        manager.add(
            "thread-2",
            [HumanMessage("late", id="h2")],
            user_id="bob",
        )
        assert provider_calls == ["alice"]
    finally:
        release_resolve.set()
        if writer.is_alive():
            writer.join(timeout=5.0)
        if shutdown_thread.is_alive():
            shutdown_thread.join(timeout=5.0)

    assert not writer.is_alive()
    assert not shutdown_thread.is_alive()
    assert write_errors == []
    assert flush_results == [True]
    assert provider_calls == ["alice"]
    assert len(recorders) == 1
    assert len(recorders[0].calls) == 1
    assert recorders[0].closed is True
    assert len(manager._pool) == 0
    assert close_calls == 1
    cursor_path = manager._state_path(_session_id("alice", "deerflow", "thread-1"))
    assert cursor_path.exists()
    assert not manager._state_path(_session_id("bob", "deerflow", "thread-2")).exists()


def test_shutdown_flush_bounds_provider_cleanup_within_timeout_and_closes_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _track_official_integration(monkeypatch)
    close_started = threading.Event()
    release_close = threading.Event()
    close_calls = 0

    class _SlowClosableProvider:
        def resolve(self, user_id: str) -> str:
            return f"key-{user_id}"

        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1
            close_started.set()
            assert release_close.wait(timeout=5.0)

    manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(tmp_path, timeout_seconds=2.0),
        credential_provider=_SlowClosableProvider(),
    )

    try:
        t0 = time.monotonic()
        assert manager.shutdown_flush(0.05) is False
        flush_elapsed = time.monotonic() - t0
        assert flush_elapsed < 1.0
        assert close_started.wait(timeout=1.0)
        assert not release_close.is_set()

        t1 = time.monotonic()
        manager.close()
        close_elapsed = time.monotonic() - t1
        assert close_elapsed < 0.5
        assert close_calls == 1
    finally:
        release_close.set()

    assert manager.shutdown_flush(1.0) is True
    assert close_calls == 1


def test_credential_provider_close_failure_logs_only_exception_class(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _track_official_integration(monkeypatch)

    class _BrokenCloseProvider:
        def resolve(self, user_id: str) -> str:
            return f"key-{user_id}"

        def close(self) -> None:
            raise RuntimeError("postgres://svc:super-secret-dsn@vault.internal:5432/keys")

    manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(tmp_path),
        credential_provider=_BrokenCloseProvider(),
    )

    with caplog.at_level(logging.WARNING, logger=OpenVikingMemoryManager.__module__):
        assert manager.shutdown_flush(1.0) is True

    warnings = [r for r in caplog.records if "Failed to close OpenViking credential provider" in r.getMessage()]
    assert len(warnings) == 1
    assert warnings[0].getMessage() == "Failed to close OpenViking credential provider (RuntimeError)"
    assert warnings[0].exc_info is None
    assert "super-secret-dsn" not in caplog.text
    assert "vault.internal" not in caplog.text


def test_multi_user_lazy_client_init_error_honors_failure_policies_and_sanitizes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import deerflow.agents.memory.backends.openviking.openviking_manager as module
    from deerflow.agents import memory as memory_pkg
    from deerflow.agents.lead_agent.prompt import _get_memory_context
    from deerflow.config.app_config import AppConfig
    from deerflow.config.memory_config import MemoryConfig
    from deerflow.config.sandbox_config import SandboxConfig

    class _ExplodingRecorder:
        def __init__(self, *, url: str, api_key: str, **kwargs: Any) -> None:
            del url, kwargs
            raise RuntimeError(f"handshake failed: {api_key}")

    def _loader() -> dict[str, Any]:
        return {
            "OpenVikingCommitPolicy": _CommitPolicy,
            "OpenVikingPartialWriteError": _PartialWriteError,
            "OpenVikingRetriever": _Retriever,
            "OpenVikingSessionRecorder": _ExplodingRecorder,
            "use_actor_peer": _use_actor_peer,
        }

    monkeypatch.setattr(module, "_load_official_integration", _loader)

    drop_open_mgr = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(
            tmp_path / "open",
            user_credentials={"alice": {"api_key": "ov-alice-super-secret"}},
            failure_policy={"read": "fail_open", "write": "log_and_drop"},
        )
    )
    raise_mgr = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(
            tmp_path / "raise",
            user_credentials={"alice": {"api_key": "ov-alice-super-secret"}},
            failure_policy={"read": "raise", "write": "raise"},
        )
    )
    try:
        with caplog.at_level(logging.ERROR, logger=OpenVikingMemoryManager.__module__):
            assert drop_open_mgr.add("thread-1", [HumanMessage("msg", id="h1")], user_id="alice") is None
        assert any("Failed to initialize OpenViking client for DeerFlow user 'alice' (RuntimeError)" in r.getMessage() and "Dropping the memory write" in r.getMessage() for r in caplog.records)
        assert "ov-alice-super-secret" not in caplog.text

        open_app_cfg = AppConfig(
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
            memory=MemoryConfig(
                enabled=True,
                injection_enabled=True,
                manager_class="openviking",
                backend_config=drop_open_mgr.backend_config,
            ),
        )
        monkeypatch.setattr(memory_pkg, "get_memory_manager", lambda: drop_open_mgr)
        assert _get_memory_context(app_config=open_app_cfg, user_id="alice") == ""

        with pytest.raises(MemoryReadError, match="RuntimeError") as read_exc:
            raise_mgr.get_context("alice")
        assert "ov-alice-super-secret" not in str(read_exc.value)
        assert read_exc.value.__cause__ is not None
        assert "ov-alice-super-secret" not in str(read_exc.value.__cause__)

        with pytest.raises(MemoryManagerError, match="RuntimeError") as write_exc:
            raise_mgr.add("thread-1", [HumanMessage("msg", id="h1")], user_id="alice")
        assert "ov-alice-super-secret" not in str(write_exc.value)
    finally:
        drop_open_mgr.close()
        raise_mgr.close()


def test_gateway_memory_config_response_masks_multi_user_secrets() -> None:
    from app.gateway.routers.memory import MemoryConfigResponse

    parsed = MemoryConfigResponse(
        enabled=True,
        mode="middleware",
        injection_enabled=True,
        shutdown_flush_timeout_seconds=30.0,
        manager_class="openviking",
        backend_config={
            "base_url": "http://127.0.0.1:1933",
            "user_credentials": {
                "alice": {"api_key": "alice-plaintext-secret", "tenant_id": "acme"},
                "bob": {"api_key_env": "BOB_OV_KEY"},
            },
            "credential_provider": "myapp.creds:VaultProvider",
            "credential_provider_config": {
                "endpoint": "https://vault.internal",
                "namespace": "prod",
                "timeout_seconds": 5,
                "api_key": "vault-api-secret",
                "client_secret": "vault-client-secret",
                "token": "vault-bearer-token",
            },
            "client_pool": {
                "max_clients": 32,
                "idle_ttl_seconds": 600,
            },
        },
    )

    assert parsed.backend_config["user_credentials"] == "***"
    assert parsed.backend_config["credential_provider"] == "myapp.creds:VaultProvider"
    provider_cfg = parsed.backend_config["credential_provider_config"]
    assert provider_cfg["endpoint"] == "https://vault.internal"
    assert provider_cfg["namespace"] == "prod"
    assert provider_cfg["timeout_seconds"] == 5
    assert provider_cfg["api_key"] == "***"
    assert provider_cfg["client_secret"] == "***"
    assert provider_cfg["token"] == "***"
    assert parsed.backend_config["client_pool"] == {"max_clients": 32, "idle_ttl_seconds": 600}

    serialized = parsed.model_dump_json()
    for secret in ("alice-plaintext-secret", "BOB_OV_KEY", "vault-api-secret", "vault-client-secret", "vault-bearer-token"):
        assert secret not in serialized


def test_memory_target_uris_supports_home_alias() -> None:
    from deerflow.agents.memory.backends.openviking.session import _memory_target_uris

    assert _memory_target_uris("research") == [
        "viking://user/memories",
        "viking://user/peers/research/memories",
    ]
    assert _memory_target_uris("research", use_home_alias=True) == [
        "viking://~/memories",
        "viking://~/peers/research/memories",
    ]


class _FakeInvalidURIError(Exception):
    code = "INVALID_URI"


def test_get_context_falls_back_to_home_alias_and_caches_for_subsequent_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    import deerflow.agents.memory.backends.openviking.openviking_manager as module

    class _CompatRetriever(_Retriever):
        def invoke(self, query: str) -> list[Document]:
            result = super().invoke(query)
            if self.target_uri[0] == "viking://user/memories":
                raise _FakeInvalidURIError("Invalid URI: viking://user/memories (Use 'viking://~/memories' for the current user)")
            return result

    orig_loader = module._load_official_integration

    def _loader_with_compat() -> dict[str, Any]:
        loaded = orig_loader()
        loaded["OpenVikingRetriever"] = _CompatRetriever
        return loaded

    monkeypatch.setattr(module, "_load_official_integration", _loader_with_compat)
    manager = _manager(tmp_path, monkeypatch, failure_policy={"read": "raise"})

    context = manager.get_context("alice", agent_name="research", thread_id="thread-1")
    assert context == "- [preferences] Prefers concise answers."
    assert [c["target_uri"] for c in manager._retriever.calls] == [
        ["viking://user/memories", "viking://user/peers/research/memories"],
        ["viking://~/memories", "viking://~/peers/research/memories"],
    ]

    # Sticky cache: subsequent get_context and search skip legacy URIs altogether.
    hits = manager.search("concise", user_id="alice", agent_name="research")
    assert len(hits) == 1
    assert manager._retriever.calls[2]["target_uri"] == [
        "viking://~/memories",
        "viking://~/peers/research/memories",
    ]


def test_search_falls_back_to_home_alias_when_first_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
) -> None:
    import deerflow.agents.memory.backends.openviking.openviking_manager as module

    class _CompatRetriever(_Retriever):
        def invoke(self, query: str) -> list[Document]:
            result = super().invoke(query)
            if self.target_uri[0] == "viking://user/memories":
                raise _FakeInvalidURIError("Use 'viking://~/memories'")
            return result

    orig_loader = module._load_official_integration

    def _loader_with_compat() -> dict[str, Any]:
        loaded = orig_loader()
        loaded["OpenVikingRetriever"] = _CompatRetriever
        return loaded

    monkeypatch.setattr(module, "_load_official_integration", _loader_with_compat)
    manager = _manager(tmp_path, monkeypatch, failure_policy={"read": "raise"})

    hits = manager.search("concise", user_id="alice")
    assert len(hits) == 1
    assert [c["target_uri"] for c in manager._retriever.calls] == [
        ["viking://user/memories", "viking://user/peers/deerflow/memories"],
        ["viking://~/memories", "viking://~/peers/deerflow/memories"],
    ]


@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda: _FakeInvalidURIError("Invalid URI: arbitrary syntax error"),
        lambda: RuntimeError("transient connection drop"),
    ],
)
def test_non_home_alias_errors_do_not_retry_or_flip_uri_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_integration: None,
    exc_factory: Any,
) -> None:
    import deerflow.agents.memory.backends.openviking.openviking_manager as module

    class _FailingRetriever(_Retriever):
        def invoke(self, query: str) -> list[Document]:
            super().invoke(query)
            raise exc_factory()

    orig_loader = module._load_official_integration

    def _loader() -> dict[str, Any]:
        loaded = orig_loader()
        loaded["OpenVikingRetriever"] = _FailingRetriever
        return loaded

    monkeypatch.setattr(module, "_load_official_integration", _loader)
    manager = _manager(tmp_path, monkeypatch, failure_policy={"read": "raise"})

    with pytest.raises(MemoryReadError):
        manager.get_context("alice")

    assert len(manager._retriever.calls) == 1
    assert manager._use_home_alias_uris is False


@pytest.mark.parametrize("bad_runtime_uid", [" alice", "alice ", "alice\x00bob", "alice\n", "alice\t"])
def test_multi_user_rejects_untrimmed_or_control_char_runtime_user_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_runtime_uid: str,
) -> None:
    recorders, retrievers = _track_official_integration(monkeypatch)
    provider_calls: list[str] = []

    def provider(uid: str) -> str:
        provider_calls.append(uid)
        return f"key-{uid.strip()}"

    manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(tmp_path, failure_policy={"read": "raise", "write": "raise"}),
        credential_provider=provider,
    )
    try:
        with pytest.raises(MemoryManagerError, match="stripped DeerFlow user_id"):
            manager.add("thread-1", [HumanMessage("hi", id="h1")], user_id=bad_runtime_uid)
        with pytest.raises(MemoryReadError) as ctx_exc:
            manager.get_context(bad_runtime_uid, thread_id="thread-1")
        assert isinstance(ctx_exc.value.__cause__, MemoryManagerError)
        with pytest.raises(MemoryReadError) as search_exc:
            manager.search("prefs", user_id=bad_runtime_uid)
        assert isinstance(search_exc.value.__cause__, MemoryManagerError)

        assert provider_calls == []
        assert recorders == []
        assert retrievers == []
    finally:
        manager.close()


def test_hybrid_mode_rejects_dynamic_reuse_of_uncached_or_evicted_static_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorders, _ = _track_official_integration(monkeypatch)
    dynamic_keys = {
        "bob": {"api_key": "alice-static-secret", "tenant_id": "acme"},
        "carol": {"api_key": "carol-dynamic-secret", "tenant_id": "globex"},
    }
    manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(
            tmp_path,
            failure_policy={"read": "raise", "write": "raise"},
            client_pool={"max_clients": 1},
            user_credentials={"alice": {"api_key": "alice-static-secret", "tenant_id": "acme"}},
        ),
        credential_provider=lambda uid: dynamic_keys.get(uid),
    )
    try:
        # Case A: alice has never been acquired yet (not in _pool or _inflight_entries)
        with pytest.raises(MemoryManagerError, match="cannot be shared across distinct DeerFlow scopes"):
            manager.add("thread-1", [HumanMessage("leak", id="l1")], user_id="bob")
        with pytest.raises(MemoryReadError, match="cannot be shared across distinct DeerFlow scopes"):
            manager.get_context("bob")
        assert recorders == []

        # Case B: alice is acquired and then evicted from the size-1 pool by carol; conflict still catches bob
        manager.search("prefs", user_id="alice")
        assert len(recorders) == 1
        manager.search("prefs", user_id="carol")
        assert len(recorders) == 2
        assert recorders[0].closed is True

        with pytest.raises(MemoryManagerError, match="cannot be shared across distinct DeerFlow scopes"):
            manager.add("thread-1", [HumanMessage("leak2", id="l2")], user_id="bob")
        assert len(recorders) == 2
    finally:
        manager.close()


def test_tenant_reassignment_retires_cached_and_inflight_handles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorders, _ = _track_official_integration(monkeypatch)
    current = {"alice": OpenVikingCredential(api_key="alice-v1", tenant_id="acme")}
    manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(
            tmp_path,
            client_pool={"max_clients": 4, "idle_ttl_seconds": None},
        ),
        credential_provider=lambda uid: current.get(uid),
    )
    try:
        # 1. Idle tenant reassignment closes the old acme handle immediately
        manager.search("prefs", user_id="alice")
        assert len(recorders) == 1
        rec_acme = recorders[0]
        assert rec_acme.closed is False

        current["alice"] = OpenVikingCredential(api_key="alice-v2", tenant_id="globex")
        manager.search("prefs", user_id="alice")
        assert len(recorders) == 2
        rec_globex = recorders[1]
        assert rec_acme.closed is True
        assert rec_globex.closed is False
        assert list(manager._pool) == [("globex", "alice", current["alice"].key_fingerprint)]

        # 2. In-flight entry across tenant reassignment is marked retired in _inflight_entries
        started = threading.Event()
        release = threading.Event()
        orig_record = rec_globex.record

        def blocked_record(*args: Any, **kwargs: Any) -> object:
            started.set()
            assert release.wait(5.0)
            return orig_record(*args, **kwargs)

        rec_globex.record = blocked_record
        t_inflight = threading.Thread(
            target=manager.add,
            args=("t-tenant-rot", [HumanMessage("slow", id="s1")]),
            kwargs={"user_id": "alice"},
        )
        t_inflight.start()
        assert started.wait(5.0)

        # Simulate concurrent eviction/re-entry of an already-in-flight entry before reassignment
        with manager._pool_lock:
            inflight_entry = next(iter(manager._inflight_entries))
            assert inflight_entry.retired is False

        current["alice"] = OpenVikingCredential(api_key="alice-v3", tenant_id="initech")
        manager.search("prefs", user_id="alice")
        assert len(recorders) == 3
        rec_initech = recorders[2]
        assert inflight_entry.retired is True
        assert rec_globex.closed is False

        release.set()
        t_inflight.join(5.0)
        assert not t_inflight.is_alive()
        assert rec_globex.closed is True
        assert rec_initech.closed is False
    finally:
        manager.close()


@pytest.mark.parametrize("bad_agent_name", ["", "   ", "__default__"])
def test_invalid_agent_name_honors_failure_policies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    bad_agent_name: str,
) -> None:
    from deerflow.agents import memory as memory_pkg
    from deerflow.agents.lead_agent.prompt import _get_memory_context
    from deerflow.config.app_config import AppConfig
    from deerflow.config.memory_config import MemoryConfig
    from deerflow.config.sandbox_config import SandboxConfig

    recorders, retrievers = _track_official_integration(monkeypatch)
    monkeypatch.setenv("OPENVIKING_API_KEY", "single-secret")

    single_drop = OpenVikingMemoryManager.from_config(_backend_config(tmp_path / "s-drop", failure_policy={"read": "fail_open", "write": "log_and_drop"}))
    single_raise = OpenVikingMemoryManager.from_config(_backend_config(tmp_path / "s-raise", failure_policy={"read": "raise", "write": "raise"}))
    multi_drop = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(
            tmp_path / "m-drop",
            user_credentials={"alice": {"api_key": "alice-secret"}},
            failure_policy={"read": "fail_open", "write": "log_and_drop"},
        )
    )
    multi_raise = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(
            tmp_path / "m-raise",
            user_credentials={"alice": {"api_key": "alice-secret"}},
            failure_policy={"read": "raise", "write": "raise"},
        )
    )
    try:
        for drop_mgr, raise_mgr in ((single_drop, single_raise), (multi_drop, multi_raise)):
            with caplog.at_level(logging.ERROR, logger=OpenVikingMemoryManager.__module__):
                assert drop_mgr.add("thread-1", [HumanMessage("secret", id="h1")], user_id="alice", agent_name=bad_agent_name) is None
            with pytest.raises(MemoryManagerError, match="Invalid OpenViking peer scope"):
                raise_mgr.add("thread-1", [HumanMessage("secret", id="h1")], user_id="alice", agent_name=bad_agent_name)

            with pytest.raises(MemoryManagerError, match="Invalid OpenViking peer scope"):
                drop_mgr.get_context("alice", agent_name=bad_agent_name)
            with pytest.raises(MemoryReadError, match="Invalid OpenViking peer scope"):
                raise_mgr.get_context("alice", agent_name=bad_agent_name)
            with pytest.raises(MemoryReadError, match="Invalid OpenViking peer scope"):
                raise_mgr.search("prefs", user_id="alice", agent_name=bad_agent_name)

            open_cfg = AppConfig(
                sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
                memory=MemoryConfig(
                    enabled=True,
                    injection_enabled=True,
                    manager_class="openviking",
                    backend_config=drop_mgr.backend_config,
                ),
            )
            monkeypatch.setattr(memory_pkg, "get_memory_manager", lambda m=drop_mgr: m)
            assert _get_memory_context(app_config=open_cfg, user_id="alice", agent_name=bad_agent_name) == ""

            raise_cfg = AppConfig(
                sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
                memory=MemoryConfig(
                    enabled=True,
                    injection_enabled=True,
                    manager_class="openviking",
                    backend_config=raise_mgr.backend_config,
                ),
            )
            monkeypatch.setattr(memory_pkg, "get_memory_manager", lambda m=raise_mgr: m)
            with pytest.raises(MemoryReadError, match="Invalid OpenViking peer scope"):
                _get_memory_context(app_config=raise_cfg, user_id="alice", agent_name=bad_agent_name)

        assert all(rec.calls == [] for rec in recorders)
        assert all(ret.calls == [] for ret in retrievers)
    finally:
        for mgr in (single_drop, single_raise, multi_drop, multi_raise):
            mgr.close()


def test_save_cursor_oserror_honors_write_failure_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _track_official_integration(monkeypatch)
    drop_mgr = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(
            tmp_path / "drop",
            user_credentials={"alice": {"api_key": "alice-secret"}},
            failure_policy={"write": "log_and_drop"},
        )
    )
    raise_mgr = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(
            tmp_path / "raise",
            user_credentials={"alice": {"api_key": "alice-secret"}},
            failure_policy={"write": "raise"},
        )
    )
    try:

        def fail_save(session_id: str, state: dict[str, Any]) -> None:
            del session_id, state
            raise OSError("disk full")

        monkeypatch.setattr(drop_mgr, "_save_cursor", fail_save)
        monkeypatch.setattr(raise_mgr, "_save_cursor", fail_save)

        with caplog.at_level(logging.ERROR, logger=OpenVikingMemoryManager.__module__):
            assert drop_mgr.add("thread-1", [HumanMessage("msg", id="h1")], user_id="alice") is None
        assert any("OpenViking capture cursor persistence failed" in r.getMessage() for r in caplog.records)

        with pytest.raises(MemoryManagerError, match="OpenViking capture cursor persistence failed"):
            raise_mgr.add("thread-1", [HumanMessage("msg", id="h1")], user_id="alice")
    finally:
        drop_mgr.close()
        raise_mgr.close()


def test_constructor_exceptions_sanitize_secrets_and_close_loaded_provider_on_init_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deerflow.agents.memory.backends.openviking.openviking_manager as module

    pkg = tmp_path / "dyn_ov_ctor_err"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(
        "class FailingCtorProvider:\n"
        "    def __init__(self, dsn: str):\n"
        "        raise RuntimeError(f'bad dsn: {dsn}')\n"
        "\n"
        "def failing_factory(token: str):\n"
        "    raise ValueError(f'bad token: {token}')\n"
        "\n"
        "events = []\n"
        "class CleanupTrackerProvider:\n"
        "    def resolve(self, user_id: str):\n"
        "        return 'key-' + user_id\n"
        "    def close(self):\n"
        "        events.append('closed')\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    with pytest.raises(ValueError, match=r"initialization failed \(RuntimeError\)") as cls_exc:
        load_credential_provider("dyn_ov_ctor_err.mod:FailingCtorProvider", {"dsn": "postgres://u:super-secret-dsn@h/db"})
    assert "super-secret-dsn" not in str(cls_exc.value)
    assert cls_exc.value.__cause__ is None

    with pytest.raises(ValueError, match=r"initialization failed \(ValueError\)") as fac_exc:
        load_credential_provider("dyn_ov_ctor_err.mod:failing_factory", {"token": "factory-super-secret"})
    assert "factory-super-secret" not in str(fac_exc.value)
    assert fac_exc.value.__cause__ is None

    # If model_post_init fails after load_credential_provider(), loaded provider must be closed
    monkeypatch.setattr(module, "_load_official_integration", lambda: (_ for _ in ()).throw(ImportError("missing integration")))
    with pytest.raises(ImportError, match="missing integration"):
        OpenVikingMemoryManager.from_config(
            _multi_user_backend_config(
                tmp_path,
                credential_provider="dyn_ov_ctor_err.mod:CleanupTrackerProvider",
            )
        )
    mod = importlib.import_module("dyn_ov_ctor_err.mod")
    assert mod.events == ["closed"]

    # Single-user startup _build_scoped_entry failure must also sanitize API key
    class _ExplodingSingleRecorder:
        def __init__(self, *, url: str, api_key: str, **kwargs: Any) -> None:
            del url, kwargs
            raise RuntimeError(f"boom with {api_key}")

    monkeypatch.setattr(
        module,
        "_load_official_integration",
        lambda: {
            "OpenVikingCommitPolicy": _CommitPolicy,
            "OpenVikingPartialWriteError": _PartialWriteError,
            "OpenVikingRetriever": _Retriever,
            "OpenVikingSessionRecorder": _ExplodingSingleRecorder,
            "use_actor_peer": _use_actor_peer,
        },
    )
    monkeypatch.setenv("OPENVIKING_API_KEY", "single-super-secret")
    with pytest.raises(MemoryManagerError, match=r"Failed to initialize OpenViking client \(RuntimeError\)") as init_exc:
        OpenVikingMemoryManager.from_config(_backend_config(tmp_path))
    assert "single-super-secret" not in str(init_exc.value)
    assert init_exc.value.__cause__ is None


def test_inflight_revocation_defers_close_and_inflight_evicted_key_conflict_rejects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorders, _ = _track_official_integration(monkeypatch)
    keys: dict[str, str | None] = {"alice": "shared-secret", "bob": "bob-secret"}
    manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(
            tmp_path,
            client_pool={"max_clients": 1},
            failure_policy={"read": "raise", "write": "raise"},
        ),
        credential_provider=lambda uid: keys.get(uid),
    )
    try:
        manager.search("warmup", user_id="alice")
        assert len(recorders) == 1
        rec_alice = recorders[0]

        started = threading.Event()
        release = threading.Event()
        orig_record = rec_alice.record

        def blocked_record(*args: Any, **kwargs: Any) -> object:
            started.set()
            assert release.wait(timeout=5.0)
            return orig_record(*args, **kwargs)

        rec_alice.record = blocked_record
        t_inflight = threading.Thread(
            target=manager.add,
            args=("t-revoke", [HumanMessage("slow", id="s1")]),
            kwargs={"user_id": "alice"},
        )
        t_inflight.start()
        try:
            assert started.wait(timeout=5.0)

            # Evict alice from max_clients=1 pool via bob while alice's entry stays in _inflight_entries
            manager.search("warmup", user_id="bob")
            assert len(recorders) == 2
            assert rec_alice.closed is False

            # Another user reusing alice's still-in-flight evicted key must be rejected
            keys["carol"] = "shared-secret"
            with pytest.raises(MemoryManagerError, match="cannot be shared across distinct DeerFlow scopes"):
                manager.add("t-conflict", [HumanMessage("leak", id="c1")], user_id="carol")
            assert len(recorders) == 2

            # Revoke alice while alice's entry is still in-flight -> retired now, closed only after completion
            keys["alice"] = None
            with pytest.raises(MemoryManagerError, match="No OpenViking USER API key"):
                manager.add("t-revoked", [HumanMessage("after revoke", id="r1")], user_id="alice")
            assert rec_alice.closed is False
        finally:
            release.set()
            t_inflight.join(timeout=5.0)

        assert not t_inflight.is_alive()
        assert rec_alice.closed is True
    finally:
        manager.close()


def test_single_user_config_parity_and_multi_user_edge_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENVIKING_API_KEY", "valid-single-key")

    with pytest.raises(ValueError, match="must not embed credentials"):
        OpenVikingConfig.from_backend_config(_backend_config(tmp_path, base_url="http://user:pass@127.0.0.1:1933"))

    for bad_owner in (123, True, "alice\x00bob", "alice\nbob"):
        with pytest.raises(ValueError, match="owner_user_id must be a string without control characters"):
            OpenVikingConfig.from_backend_config(_backend_config(tmp_path, owner_user_id=bad_owner))

    for bad_env in (123, "ENV\x00KEY", "ENV\nKEY"):
        with pytest.raises(ValueError, match="api_key_env must be a string without control characters"):
            OpenVikingConfig.from_backend_config(_backend_config(tmp_path, api_key_env=bad_env))
        with pytest.raises(ValueError, match=r"user_credentials\.alice\.api_key_env must be a non-empty string without control characters"):
            OpenVikingConfig.from_backend_config(_multi_user_backend_config(tmp_path, user_credentials={"alice": {"api_key_env": bad_env}}))

    with pytest.raises(ValueError, match="api_key_env must be a non-empty string without control characters"):
        OpenVikingCredential(api_key="valid-key", api_key_env="OV\nKEY")

    # Duplicate secrets across two different env vars in multi-user mode
    monkeypatch.setenv("ALICE_ENV_KEY", "shared-env-secret")
    monkeypatch.setenv("BOB_ENV_KEY", "shared-env-secret")
    with pytest.raises(ValueError, match="must not share the same API key") as dup_exc:
        OpenVikingConfig.from_backend_config(
            _multi_user_backend_config(
                tmp_path,
                user_credentials={
                    "alice": {"api_key_env": "ALICE_ENV_KEY"},
                    "bob": {"api_key_env": "BOB_ENV_KEY"},
                },
            )
        )
    assert "shared-env-secret" not in str(dup_exc.value)

    # Empty user_credentials paired with credential_provider is valid, and __call__-only provider objects work
    class _CallableOnlyProvider:
        def __call__(self, user_id: str) -> str:
            return f"callable-key-{user_id}"

    cfg = OpenVikingConfig.from_backend_config(
        _multi_user_backend_config(tmp_path, user_credentials={}),
        has_injected_credential_provider=True,
    )
    assert cfg.isolation_mode == "multi_user"
    assert len(cfg.user_credentials) == 0

    recorders, _ = _track_official_integration(monkeypatch)
    mgr = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(tmp_path, user_credentials={}),
        credential_provider=_CallableOnlyProvider(),
    )
    try:
        mgr.search("prefs", user_id="alice")
        assert recorders[-1].connection["api_key"] == "callable-key-alice"
    finally:
        mgr.close()


@pytest.mark.asyncio
async def test_admitted_async_write_does_not_wait_on_slow_provider_cleanup_during_shutdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    recorders, _ = _track_official_integration(monkeypatch)
    resolve_started = threading.Event()
    release_resolve = threading.Event()
    close_started = threading.Event()
    release_close = threading.Event()
    close_calls = 0

    class _SlowCleanupProvider:
        def resolve(self, user_id: str) -> str:
            resolve_started.set()
            assert release_resolve.wait(timeout=5.0)
            return f"key-{user_id}"

        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1
            close_started.set()
            assert release_close.wait(timeout=5.0)

    manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(tmp_path, timeout_seconds=5.0),
        credential_provider=_SlowCleanupProvider(),
    )

    write_task = asyncio.create_task(
        manager.aadd(
            "thread-1",
            [HumanMessage("admitted async write", id="h1")],
            user_id="alice",
        )
    )
    flush_task: asyncio.Task[bool] | None = None
    try:
        assert await asyncio.to_thread(resolve_started.wait, 5.0)

        flush_task = asyncio.create_task(asyncio.to_thread(manager.shutdown_flush, 0.15))
        deadline = time.monotonic() + 5.0
        while not manager._closed and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert manager._closed is True

        release_resolve.set()

        # The last admitted async write must finish immediately after recording its
        # update without blocking on slow provider cleanup (timeout_seconds=5.0).
        await asyncio.wait_for(write_task, timeout=1.0)
        assert len(recorders) == 1
        assert len(recorders[0].calls) == 1
        assert manager._state_path(_session_id("alice", "deerflow", "thread-1")).exists()

        # Shutdown flush owns the bounded cleanup wait and times out on schedule.
        assert await asyncio.wait_for(flush_task, timeout=1.0) is False
        assert await asyncio.to_thread(close_started.wait, 1.0)
        assert recorders[0].closed is True
        assert not release_close.is_set()

        # Follow-up Gateway close() must not block past the already-timed-out flush.
        await asyncio.wait_for(asyncio.to_thread(manager.close), timeout=0.5)
        assert close_calls == 1
    finally:
        release_resolve.set()
        release_close.set()
        if not write_task.done():
            await asyncio.wait_for(write_task, timeout=5.0)
        if flush_task is not None and not flush_task.done():
            await asyncio.wait_for(flush_task, timeout=5.0)

    assert manager.shutdown_flush(1.0) is True
    assert close_calls == 1


@pytest.mark.parametrize("mode", ["single_user", "multi_user"])
def test_shutdown_flush_bounds_slow_recorder_teardown_without_provider_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    recorders, _ = _track_official_integration(monkeypatch)
    monkeypatch.setenv("OPENVIKING_API_KEY", "single-secret")

    if mode == "single_user":
        manager = OpenVikingMemoryManager.from_config(_backend_config(tmp_path, timeout_seconds=2.0))
    else:
        manager = OpenVikingMemoryManager.from_config(
            _multi_user_backend_config(
                tmp_path,
                timeout_seconds=2.0,
                user_credentials={"alice": {"api_key": "alice-secret"}},
            )
        )
        manager.search("warmup", user_id="alice")

    assert len(recorders) == 1
    recorder = recorders[0]
    close_started = threading.Event()
    release_close = threading.Event()
    close_calls = 0
    orig_close = recorder.close

    def slow_close() -> None:
        nonlocal close_calls
        close_calls += 1
        close_started.set()
        assert release_close.wait(timeout=5.0)
        orig_close()

    recorder.close = slow_close

    try:
        t0 = time.monotonic()
        assert manager.shutdown_flush(0.05) is False
        assert time.monotonic() - t0 < 0.5
        assert close_started.wait(timeout=1.0)
        assert not release_close.is_set()

        t1 = time.monotonic()
        manager.close()
        assert time.monotonic() - t1 < 0.5
        assert close_calls == 1
    finally:
        release_close.set()

    assert manager.shutdown_flush(1.0) is True
    assert recorder.closed is True
    assert close_calls == 1


@pytest.mark.asyncio
async def test_admitted_async_write_does_not_wait_on_slow_recorder_teardown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    recorders, _ = _track_official_integration(monkeypatch)
    manager = OpenVikingMemoryManager.from_config(
        _multi_user_backend_config(
            tmp_path,
            timeout_seconds=5.0,
            user_credentials={"alice": {"api_key": "alice-secret"}},
        )
    )
    manager.search("warmup", user_id="alice")
    assert len(recorders) == 1
    recorder = recorders[0]

    record_started = threading.Event()
    release_record = threading.Event()
    close_started = threading.Event()
    release_close = threading.Event()
    close_calls = 0
    orig_record = recorder.record
    orig_close = recorder.close

    def blocked_record(*args: Any, **kwargs: Any) -> object:
        record_started.set()
        assert release_record.wait(timeout=5.0)
        return orig_record(*args, **kwargs)

    def slow_close() -> None:
        nonlocal close_calls
        close_calls += 1
        close_started.set()
        assert release_close.wait(timeout=5.0)
        orig_close()

    recorder.record = blocked_record
    recorder.close = slow_close

    write_task = asyncio.create_task(
        manager.aadd(
            "thread-1",
            [HumanMessage("admitted async write", id="h1")],
            user_id="alice",
        )
    )
    flush_task: asyncio.Task[bool] | None = None
    try:
        assert await asyncio.to_thread(record_started.wait, 5.0)

        flush_task = asyncio.create_task(asyncio.to_thread(manager.shutdown_flush, 0.15))
        deadline = time.monotonic() + 5.0
        while not manager._closed and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert manager._closed is True

        release_record.set()

        # Finishing write starts cleanup worker and returns promptly without waiting on slow recorder.close().
        await asyncio.wait_for(write_task, timeout=1.0)
        assert len(recorder.calls) == 1
        assert manager._state_path(_session_id("alice", "deerflow", "thread-1")).exists()

        # Bounded shutdown_flush returns False on schedule while recorder.close() is still pending.
        assert await asyncio.wait_for(flush_task, timeout=1.0) is False
        assert await asyncio.to_thread(close_started.wait, 1.0)
        assert not release_close.is_set()

        # Follow-up Gateway close() returns promptly without double-closing recorder.
        await asyncio.wait_for(asyncio.to_thread(manager.close), timeout=0.5)
        assert close_calls == 1
    finally:
        release_record.set()
        release_close.set()
        if not write_task.done():
            await asyncio.wait_for(write_task, timeout=5.0)
        if flush_task is not None and not flush_task.done():
            await asyncio.wait_for(flush_task, timeout=5.0)

    assert manager.shutdown_flush(1.0) is True
    assert recorder.closed is True
    assert close_calls == 1


def test_cleanup_worker_start_failure_marks_cleanup_done_and_sanitizes_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import deerflow.agents.memory.backends.openviking.openviking_manager as module

    _track_official_integration(monkeypatch)
    manager = OpenVikingMemoryManager.from_config(_multi_user_backend_config(tmp_path, user_credentials={"alice": {"api_key": "alice-secret"}}))
    manager.search("warmup", user_id="alice")

    class _FailingThread:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs

        def start(self) -> None:
            raise RuntimeError("can't start new thread: secret-stack-info")

    monkeypatch.setattr(module.threading, "Thread", _FailingThread)

    with caplog.at_level(logging.WARNING, logger=OpenVikingMemoryManager.__module__):
        assert manager.shutdown_flush(1.0) is False

    assert manager._cleanup_done.is_set()
    assert manager._cleanup_failed is True
    warnings = [r for r in caplog.records if "Failed to start OpenViking cleanup worker" in r.getMessage()]
    assert len(warnings) == 1
    assert warnings[0].getMessage() == "Failed to start OpenViking cleanup worker (RuntimeError)"
    assert warnings[0].exc_info is None
    assert "secret-stack-info" not in caplog.text
