"""Regression anchors: OpenViking async methods must not block the loop."""

from __future__ import annotations

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
