"""Regression anchors: OpenViking async methods must not block the loop."""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.openviking.openviking_manager import (
    OpenVikingMemoryManager,
)


class _CommitPolicy:
    def __init__(self, *, mode: str):
        self.mode = mode


class _Client:
    supports_request_actor_peer = True

    def health(self) -> bool:
        return True

    def close(self) -> None:
        pass


class _BlockingRecorder:
    def __init__(self, *, commit_policy: Any, **kwargs: Any):
        del kwargs
        self.commit_policy = commit_policy
        self.client = _Client()
        self.probe_path: Path | None = None

    def record(
        self,
        session_id: str,
        messages: list[Any],
        peer_id: str | None = None,
    ) -> None:
        del session_id, messages, peer_id
        assert self.probe_path is not None
        self.probe_path.write_text("record", encoding="utf-8")

    def flush(self, session_id: str) -> None:
        del session_id

    def close(self) -> None:
        pass


class _BlockingRetriever:
    def __init__(self, *, client: Any, **kwargs: Any):
        del client
        self.__dict__.update(kwargs)
        self.filter = None
        self.target_uri = ""
        self.session_id = None
        self.probe_path: Path | None = None

    def __copy__(self) -> _BlockingRetriever:
        copied = type(self)(client=None)
        copied.__dict__.update(self.__dict__)
        return copied

    def invoke(self, query: str) -> list[Document]:
        del query
        assert self.probe_path is not None
        self.probe_path.write_text("retrieve", encoding="utf-8")
        return [
            Document(
                page_content="Prefers concise answers.",
                metadata={
                    "openviking_uri": ("viking://user/memories/preferences/test.md"),
                    "openviking_category": "preferences",
                    "openviking_score": 0.9,
                },
            )
        ]


def _manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> OpenVikingMemoryManager:
    import deerflow.agents.memory.backends.openviking.openviking_manager as module

    monkeypatch.setenv("OPENVIKING_API_KEY", "user-key")
    monkeypatch.setattr(
        module,
        "_load_official_integration",
        lambda: {
            "OpenVikingCommitPolicy": _CommitPolicy,
            "OpenVikingPartialWriteError": RuntimeError,
            "OpenVikingRetriever": _BlockingRetriever,
            "OpenVikingSessionRecorder": _BlockingRecorder,
            "use_actor_peer": lambda peer_id: nullcontext(),
        },
    )
    manager = OpenVikingMemoryManager.from_config(
        {
            "base_url": "http://openviking:1933",
            "storage_path": str(tmp_path),
            "owner_user_id": "alice",
            "startup_policy": "warn",
        }
    )
    manager._recorder.probe_path = tmp_path / "record.txt"
    manager._retriever.probe_path = tmp_path / "retrieve.txt"
    return manager


@pytest.mark.asyncio
async def test_async_openviking_operations_do_not_block_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    messages: list[Any] = [
        HumanMessage("hello", id="h1"),
        AIMessage("hi", id="a1"),
    ]

    await manager.aadd(
        "thread-1",
        messages,
        user_id="alice",
    )
    assert await manager.aget_context("alice") == ("- [preferences] Prefers concise answers.")
    assert await manager.asearch(
        "answer style",
        user_id="alice",
    ) == [
        {
            "id": "viking://user/memories/preferences/test.md",
            "content": "Prefers concise answers.",
            "category": "preferences",
            "confidence": 0.9,
            "source": "viking://user/memories/preferences/test.md",
            "score": 0.9,
        }
    ]


@pytest.mark.asyncio
async def test_multi_user_async_openviking_operations_and_eviction_do_not_block_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deerflow.agents.memory.backends.openviking.openviking_manager as module

    probe_dir = tmp_path / "probes"
    probe_dir.mkdir()
    creds_path = tmp_path / "credentials.json"
    creds_path.write_text(
        json.dumps(
            {
                "alice": {"api_key": "alice-key", "tenant_id": "acme"},
                "bob": {"api_key": "bob-key", "tenant_id": "globex"},
            }
        ),
        encoding="utf-8",
    )

    events: list[tuple[str, str, int]] = []
    close_files: list[Path] = []
    lock = threading.Lock()

    def _record_event(kind: str, label: str) -> int:
        idx_holder: int
        with lock:
            events.append((kind, label, threading.get_ident()))
            idx_holder = len(events)
        return idx_holder

    class _FileCredentialProvider:
        def resolve(self, user_id: str) -> dict[str, Any] | None:
            _record_event("resolve", user_id)
            data = json.loads(creds_path.read_text(encoding="utf-8"))
            return data.get(user_id)

    class _MultiUserClient(_Client):
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

    class _MultiUserBlockingRecorder:
        def __init__(self, *, commit_policy: Any, api_key: str, **kwargs: Any):
            del kwargs
            self.commit_policy = commit_policy
            self.api_key = api_key
            self.client = _MultiUserClient(api_key)
            idx = _record_event("init", api_key)
            (probe_dir / f"init-{api_key}-{idx}.txt").write_text("init", encoding="utf-8")

        def record(
            self,
            session_id: str,
            messages: list[Any],
            peer_id: str | None = None,
        ) -> None:
            del session_id, messages, peer_id
            idx = _record_event("record", self.api_key)
            (probe_dir / f"record-{self.api_key}-{idx}.txt").write_text("record", encoding="utf-8")

        def flush(self, session_id: str) -> None:
            del session_id

        def close(self) -> None:
            idx = _record_event("close", self.api_key)
            path = probe_dir / f"close-{self.api_key}-{idx}.txt"
            path.write_text("close", encoding="utf-8")
            close_files.append(path)

    class _MultiUserBlockingRetriever(_BlockingRetriever):
        def __init__(self, *, client: Any, **kwargs: Any):
            super().__init__(client=client, **kwargs)
            self._api_key = getattr(client, "api_key", "")

        def __copy__(self) -> _MultiUserBlockingRetriever:
            copied = type(self)(client=None)
            copied.__dict__.update(self.__dict__)
            return copied

        def invoke(self, query: str) -> list[Document]:
            del query
            idx = _record_event("retrieve", self._api_key)
            (probe_dir / f"retrieve-{self._api_key}-{idx}.txt").write_text("retrieve", encoding="utf-8")
            return [
                Document(
                    page_content="Prefers concise answers.",
                    metadata={
                        "openviking_uri": "viking://user/memories/preferences/test.md",
                        "openviking_category": "preferences",
                        "openviking_score": 0.9,
                    },
                )
            ]

    monkeypatch.setattr(
        module,
        "_load_official_integration",
        lambda: {
            "OpenVikingCommitPolicy": _CommitPolicy,
            "OpenVikingPartialWriteError": RuntimeError,
            "OpenVikingRetriever": _MultiUserBlockingRetriever,
            "OpenVikingSessionRecorder": _MultiUserBlockingRecorder,
            "use_actor_peer": lambda peer_id: nullcontext(),
        },
    )

    manager = OpenVikingMemoryManager.from_config(
        {
            "base_url": "http://openviking:1933",
            "storage_path": str(tmp_path),
            "startup_policy": "warn",
            "failure_policy": {"read": "raise", "write": "raise"},
            "client_pool": {"max_clients": 1},
        },
        credential_provider=_FileCredentialProvider(),
    )

    event_loop_thread = threading.get_ident()
    messages: list[Any] = [HumanMessage("hello", id="h1"), AIMessage("hi", id="a1")]
    try:
        await manager.aadd("thread-1", messages, user_id="alice")
        context = await manager.aget_context("bob", thread_id="thread-1")
        results = await manager.asearch("answer style", user_id="alice")

        assert context == "- [preferences] Prefers concise answers."
        assert results == [
            {
                "id": "viking://user/memories/preferences/test.md",
                "content": "Prefers concise answers.",
                "category": "preferences",
                "confidence": 0.9,
                "source": "viking://user/memories/preferences/test.md",
                "score": 0.9,
            }
        ]
        eviction_closes = [(label, tid) for kind, label, tid in events if kind == "close"]
        assert [label for label, _ in eviction_closes] == ["alice-key", "bob-key"]
        assert len(close_files) == 2
        assert all(path.exists() for path in close_files)
        assert {kind for kind, _, _ in events} == {"resolve", "init", "record", "retrieve", "close"}
        assert all(tid != event_loop_thread for _, _, tid in events)
        assert list((tmp_path / "openviking" / "sessions").glob("*.json"))
    finally:
        await asyncio.to_thread(manager.close)
