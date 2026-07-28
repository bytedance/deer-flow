from __future__ import annotations

import gc
import json
import threading
import weakref
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from deerflow.agents.memory.backends.openviking.client import OpenVikingAuthenticationError, OpenVikingHttpClient, OpenVikingUnavailableError
from deerflow.agents.memory.backends.openviking.config import OpenVikingConfig
from deerflow.agents.memory.backends.openviking.models import (
    OpenVikingCommitResult,
    OpenVikingIdentity,
    OpenVikingMessage,
    OpenVikingSearchHit,
)
from deerflow.agents.memory.backends.openviking.openviking_manager import OpenVikingMemoryManager
from deerflow.agents.memory.manager import _scan_backends, reset_memory_manager


def _backend_config(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "base_url": "http://openviking:1933",
        "storage_path": str(tmp_path),
        "auth_mode": "trusted",
        "account": "deerflow",
        "startup_policy": "warn",
        "retrieval": {"top_k": 4, "max_injection_chars": 1000},
    }
    config.update(overrides)
    return config


def test_config_parses_nested_fields_and_rejects_unknown(tmp_path: Path) -> None:
    config = OpenVikingConfig.from_backend_config(
        _backend_config(
            tmp_path,
            retrieval={"top_k": 7, "score_threshold": 0.4, "max_injection_chars": 2048},
            failure_policy={"read": "raise", "write": "raise"},
        )
    )

    assert config.search_top_k == 7
    assert config.score_threshold == 0.4
    assert config.read_failure_policy == "raise"

    with pytest.raises(ValueError, match="Unknown OpenViking"):
        OpenVikingConfig.from_backend_config(_backend_config(tmp_path, typo=True))


def test_config_rejects_dev_auth_without_explicit_opt_in(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="allow_insecure_dev"):
        OpenVikingConfig.from_backend_config(_backend_config(tmp_path, auth_mode="dev"))


def test_backend_is_discovered_by_registered_name() -> None:
    reset_memory_manager()
    assert _scan_backends()["openviking"] is OpenVikingMemoryManager


def test_http_client_sends_trusted_identity_and_maps_search(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENVIKING_API_KEY", "secret")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v1/search/find":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "result": {
                        "memories": [
                            {
                                "uri": "viking://user/memories/preferences/editor.md",
                                "context_type": "memory",
                                "category": "preferences",
                                "score": 0.91,
                                "abstract": "Uses Vim.",
                                "overview": None,
                            }
                        ],
                        "resources": [],
                        "skills": [],
                        "total": 1,
                    },
                },
            )
        raise AssertionError(f"unexpected path: {request.url.path}")

    config = OpenVikingConfig.from_backend_config(_backend_config(tmp_path))
    client = OpenVikingHttpClient(config, transport=httpx.MockTransport(handler))
    identity = OpenVikingIdentity(account="deerflow", user="df_user")

    hits = client.search(identity, "editor preference", top_k=3)

    assert [hit.abstract for hit in hits] == ["Uses Vim."]
    assert requests[0].headers["X-OpenViking-Account"] == "deerflow"
    assert requests[0].headers["X-OpenViking-User"] == "df_user"
    assert requests[0].headers["X-API-Key"] == "secret"
    assert json.loads(requests[0].content)["target_uri"] == "viking://user/memories"
    assert json.loads(requests[0].content)["context_type"] == "memory"


def test_http_client_maps_authentication_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"status": "error", "error": {"code": "UNAUTHENTICATED", "message": "bad key"}},
        )

    config = OpenVikingConfig.from_backend_config(_backend_config(tmp_path))
    client = OpenVikingHttpClient(config, transport=httpx.MockTransport(handler))

    with pytest.raises(OpenVikingAuthenticationError) as exc_info:
        client.ensure_session(OpenVikingIdentity(account="deerflow", user="df_user"), "session")
    assert exc_info.value.code == "UNAUTHENTICATED"


class _FakeClient:
    def __init__(self) -> None:
        self.ensured: list[tuple[OpenVikingIdentity, str]] = []
        self.added: list[tuple[OpenVikingIdentity, str, list[OpenVikingMessage]]] = []
        self.committed: list[tuple[OpenVikingIdentity, str]] = []
        self.searches: list[tuple[OpenVikingIdentity, str, int, str | None]] = []
        self.closed = False

    def ensure_session(self, identity: OpenVikingIdentity, session_id: str) -> None:
        self.ensured.append((identity, session_id))

    def add_messages(
        self,
        identity: OpenVikingIdentity,
        session_id: str,
        messages: list[OpenVikingMessage],
    ) -> int:
        self.added.append((identity, session_id, messages))
        return len(messages)

    def commit_session(self, identity: OpenVikingIdentity, session_id: str) -> OpenVikingCommitResult:
        self.committed.append((identity, session_id))
        return OpenVikingCommitResult(
            status="accepted",
            task_id="task-1",
            archive_uri="viking://user/sessions/session/history/archive_001",
            archived=True,
        )

    def search(
        self,
        identity: OpenVikingIdentity,
        query: str,
        *,
        top_k: int,
        category: str | None = None,
        session_id: str | None = None,
    ) -> list[OpenVikingSearchHit]:
        self.searches.append((identity, query, top_k, category))
        return [
            OpenVikingSearchHit(
                uri="viking://user/memories/preferences/editor.md",
                context_type="memory",
                category="preferences",
                score=0.9,
                abstract="User prefers concise answers.",
                overview=None,
                match_reason="",
            )
        ]

    def health(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True


def _manager(tmp_path: Path) -> tuple[OpenVikingMemoryManager, _FakeClient]:
    manager = OpenVikingMemoryManager.from_config(_backend_config(tmp_path))
    fake = _FakeClient()
    manager._client = fake  # type: ignore[assignment]
    return manager, fake


def test_manager_filters_messages_commits_and_deduplicates(tmp_path: Path) -> None:
    manager, client = _manager(tmp_path)
    messages = [
        SystemMessage("system"),
        HumanMessage("Remember that I prefer Vim.", id="human-1"),
        AIMessage("", tool_calls=[{"name": "search", "args": {}, "id": "call-1", "type": "tool_call"}]),
        ToolMessage("tool output", tool_call_id="call-1"),
        AIMessage("I will remember that.", id="ai-1"),
    ]

    manager.add("thread-1", messages, user_id="alice", agent_name="research")
    manager.add("thread-1", messages, user_id="alice", agent_name="research")

    assert len(client.added) == 1
    assert [(message.role, message.content) for message in client.added[0][2]] == [
        ("user", "Remember that I prefer Vim."),
        ("assistant", "I will remember that."),
    ]
    assert len(client.committed) == 1
    watermark = next((tmp_path / "openviking" / "sessions").glob("*.json"))
    state = json.loads(watermark.read_text(encoding="utf-8"))
    assert state["last_commit_task_id"] == "task-1"
    assert state["submitted_message_ids"] == state["committed_message_ids"]


def test_manager_does_not_resubmit_messages_after_failed_commit(tmp_path: Path) -> None:
    manager, client = _manager(tmp_path)
    messages = [HumanMessage("hello", id="h1"), AIMessage("hi", id="a1")]
    original_commit = client.commit_session
    commit_attempts = 0

    def fail_once(identity: OpenVikingIdentity, session_id: str) -> OpenVikingCommitResult:
        nonlocal commit_attempts
        commit_attempts += 1
        if commit_attempts == 1:
            raise OpenVikingUnavailableError("session.commit", "temporary failure")
        return original_commit(identity, session_id)

    client.commit_session = fail_once  # type: ignore[method-assign]

    manager.add("thread-1", messages, user_id="alice", agent_name="research")

    watermark = next((tmp_path / "openviking" / "sessions").glob("*.json"))
    failed_state = json.loads(watermark.read_text(encoding="utf-8"))
    assert failed_state["submitted_message_ids"] == ["df_h1", "df_a1"]
    assert failed_state["committed_message_ids"] == []

    manager.add("thread-1", messages, user_id="alice", agent_name="research")

    assert len(client.added) == 1
    assert commit_attempts == 1

    messages.append(HumanMessage("new information", id="h2"))
    manager.add("thread-1", messages, user_id="alice", agent_name="research")

    assert len(client.added) == 2
    assert [message.message_id for message in client.added[1][2]] == ["df_h2"]
    assert commit_attempts == 2
    recovered_state = json.loads(watermark.read_text(encoding="utf-8"))
    assert recovered_state["submitted_message_ids"] == recovered_state["committed_message_ids"]
    assert recovered_state["last_commit_task_id"] == "task-1"


def test_manager_identity_is_stable_and_agent_isolated(tmp_path: Path) -> None:
    manager, client = _manager(tmp_path)
    messages = [HumanMessage("hello", id="h1"), AIMessage("hi", id="a1")]

    manager.add("thread-1", messages, user_id="alice", agent_name="research")
    manager.add("thread-1", messages, user_id="alice", agent_name="coding")

    identities = [entry[0].user for entry in client.added]
    session_ids = [entry[1] for entry in client.added]
    assert identities[0] != identities[1]
    assert session_ids[0] != session_ids[1]
    assert all(value.startswith("df_") for value in identities)


def test_manager_search_and_context_map_remote_results(tmp_path: Path) -> None:
    manager, client = _manager(tmp_path)

    results = manager.search("answer style", user_id="alice", agent_name="research")
    context = manager.get_context("alice", agent_name="research")

    assert results == [
        {
            "id": "viking://user/memories/preferences/editor.md",
            "content": "User prefers concise answers.",
            "category": "preferences",
            "confidence": 0.9,
            "source": "viking://user/memories/preferences/editor.md",
            "score": 0.9,
        }
    ]
    assert context == "- [preferences] User prefers concise answers."
    assert client.searches[1][1] == manager._config.injection_query


def test_manager_rejects_tool_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="middleware"):
        OpenVikingMemoryManager.from_config(_backend_config(tmp_path), mode="tool")


def test_manager_session_locks_do_not_accumulate(tmp_path: Path) -> None:
    manager, _ = _manager(tmp_path)
    lock = manager._session_lock("session-1")
    lock_ref = weakref.ref(lock)

    assert len(manager._session_locks) == 1
    del lock
    gc.collect()

    assert lock_ref() is None
    assert len(manager._session_locks) == 0


@pytest.mark.asyncio
async def test_manager_async_methods_offload_sync_operations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager, _ = _manager(tmp_path)
    event_loop_thread = threading.get_ident()
    worker_threads: list[int] = []

    def fake_add(self: OpenVikingMemoryManager, *args: Any, **kwargs: Any) -> None:
        worker_threads.append(threading.get_ident())

    def fake_get_context(self: OpenVikingMemoryManager, *args: Any, **kwargs: Any) -> str:
        worker_threads.append(threading.get_ident())
        return "context"

    def fake_search(self: OpenVikingMemoryManager, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        worker_threads.append(threading.get_ident())
        return [{"id": "memory-1"}]

    monkeypatch.setattr(OpenVikingMemoryManager, "add", fake_add)
    monkeypatch.setattr(OpenVikingMemoryManager, "get_context", fake_get_context)
    monkeypatch.setattr(OpenVikingMemoryManager, "search", fake_search)

    await manager.aadd("thread-1", [], user_id="alice")
    assert await manager.aget_context("alice") == "context"
    assert await manager.asearch("query", user_id="alice") == [{"id": "memory-1"}]

    assert len(worker_threads) == 3
    assert all(thread_id != event_loop_thread for thread_id in worker_threads)


def test_manager_shutdown_waits_for_in_flight_write(tmp_path: Path) -> None:
    manager, client = _manager(tmp_path)
    write_started = threading.Event()
    release_write = threading.Event()
    original_add = client.add_messages

    def blocking_add(
        identity: OpenVikingIdentity,
        session_id: str,
        messages: list[OpenVikingMessage],
    ) -> int:
        write_started.set()
        assert release_write.wait(2)
        return original_add(identity, session_id, messages)

    client.add_messages = blocking_add  # type: ignore[method-assign]
    write_thread = threading.Thread(
        target=manager.add,
        args=("thread-1", [HumanMessage("hello", id="h1")]),
        kwargs={"user_id": "alice"},
    )
    write_thread.start()
    assert write_started.wait(1)

    assert manager.shutdown_flush(0.01) is False
    assert client.closed is False
    manager.add("thread-2", [HumanMessage("ignored", id="h2")], user_id="alice")
    assert len(client.ensured) == 1

    release_write.set()
    write_thread.join(2)
    assert not write_thread.is_alive()

    assert manager.shutdown_flush(1) is True
    assert client.closed is True
