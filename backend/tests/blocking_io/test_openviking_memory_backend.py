"""Regression anchors: OpenViking async memory methods must not block the loop."""

from __future__ import annotations

import asyncio
import copy
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.openviking import OpenVikingMemoryManager
from deerflow.agents.memory.backends.openviking.models import OpenVikingCommitResult, OpenVikingSearchHit
from deerflow.agents.memory.backends.openviking.official_manager import (
    OfficialOpenVikingMemoryManager,
)
from deerflow.agents.memory.backends.openviking.openviking_manager import (
    LegacyOpenVikingMemoryManager,
)


class _BlockingProbeClient:
    """Perform real file IO so Blockbuster can detect missing async offload."""

    def __init__(self, probe_path: Path):
        self._probe_path = probe_path

    def _probe(self) -> None:
        self._probe_path.write_text("probe", encoding="utf-8")

    def ensure_session(self, identity, session_id) -> None:
        self._probe()

    def add_messages(self, identity, session_id, messages) -> int:
        self._probe()
        return len(messages)

    def commit_session(self, identity, session_id) -> OpenVikingCommitResult:
        self._probe()
        return OpenVikingCommitResult(status="accepted", task_id="task-1", archive_uri=None, archived=True)

    def search(
        self,
        identity,
        query: str,
        *,
        top_k: int,
        category: str | None = None,
        session_id: str | None = None,
    ) -> list[OpenVikingSearchHit]:
        self._probe()
        return [
            OpenVikingSearchHit(
                uri="viking://user/memories/preferences/test.md",
                context_type="memory",
                category="preferences",
                score=0.9,
                abstract="Prefers concise answers.",
                overview=None,
                match_reason="",
            )
        ]

    def close(self) -> None:
        pass


def _manager(tmp_path: Path) -> LegacyOpenVikingMemoryManager:
    manager = OpenVikingMemoryManager.from_config(
        {
            "base_url": "http://openviking:1933",
            "storage_path": str(tmp_path),
            "auth_mode": "trusted",
            "account": "deerflow",
            "startup_policy": "warn",
        }
    )
    assert isinstance(manager, LegacyOpenVikingMemoryManager)
    manager._client = _BlockingProbeClient(tmp_path / "probe.txt")  # type: ignore[assignment]
    return manager


@pytest.mark.asyncio
async def test_async_openviking_operations_do_not_block_event_loop(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    messages: list[Any] = [HumanMessage("hello", id="h1"), AIMessage("hi", id="a1")]

    await manager.aadd("thread-1", messages, user_id="alice")
    assert await manager.aget_context("alice") == "- [preferences] Prefers concise answers."
    assert await manager.asearch("answer style", user_id="alice") == [
        {
            "id": "viking://user/memories/preferences/test.md",
            "content": "Prefers concise answers.",
            "category": "preferences",
            "confidence": 0.9,
            "source": "viking://user/memories/preferences/test.md",
            "score": 0.9,
        }
    ]


class _OfficialProbeClient:
    supports_request_actor_peer = True

    def __init__(self, **kwargs: Any):
        self.kwargs = kwargs

    def initialize(self) -> None:
        pass

    def health(self) -> bool:
        return True

    def close(self) -> None:
        pass


class _OfficialProbeRecorder:
    def __init__(self, *, probe_path: Path, **kwargs: Any):
        self._probe_path = probe_path

    def record(self, session_id: str, messages: list[Any], peer_id: str | None = None):
        self._probe_path.write_text(session_id, encoding="utf-8")
        return object()

    def flush(self, session_id: str) -> None:
        self._probe_path.write_text(session_id, encoding="utf-8")

    def close(self) -> None:
        pass


class _OfficialProbeRetriever:
    def __init__(self, *, probe_path: Path, **kwargs: Any):
        self._probe_path = probe_path
        self.limit = kwargs["limit"]
        self.filter = None

    def invoke(self, query: str) -> list[Document]:
        self._probe_path.write_text(query, encoding="utf-8")
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

    async def aclose(self) -> None:
        pass


class _OfficialProbeCommitPolicy:
    def __init__(self, *, mode: str):
        self.mode = mode


class _OfficialProbePartialWriteError(RuntimeError):
    pass


@pytest.mark.asyncio
async def test_async_official_openviking_operations_do_not_block_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deerflow.agents.memory.backends.openviking.official_manager as module

    probe_path = tmp_path / "official-probe.txt"

    class Recorder(_OfficialProbeRecorder):
        def __init__(self, **kwargs: Any):
            super().__init__(probe_path=probe_path, **kwargs)

    class Retriever(_OfficialProbeRetriever):
        def __init__(self, **kwargs: Any):
            super().__init__(probe_path=probe_path, **kwargs)

        def __copy__(self):
            copied = type(self)(limit=self.limit)
            copied.filter = copy.deepcopy(self.filter)
            return copied

    monkeypatch.setattr(
        module,
        "_load_official_integration",
        lambda: {
            "SyncHTTPClient": _OfficialProbeClient,
            "OpenVikingCommitPolicy": _OfficialProbeCommitPolicy,
            "OpenVikingPartialWriteError": _OfficialProbePartialWriteError,
            "OpenVikingRetriever": Retriever,
            "OpenVikingSessionRecorder": Recorder,
            "use_actor_peer": lambda _peer_id: nullcontext(),
        },
    )
    monkeypatch.setenv("OPENVIKING_API_KEY", "user-key")
    manager = OpenVikingMemoryManager.from_config(
        {
            "base_url": "http://openviking:1933",
            "storage_path": str(tmp_path),
            "owner_user_id": "alice",
            "startup_policy": "warn",
        }
    )
    assert isinstance(manager, OfficialOpenVikingMemoryManager)

    messages: list[Any] = [HumanMessage("hello", id="h1"), AIMessage("hi", id="a1")]
    await manager.aadd("thread-1", messages, user_id="alice")
    assert await manager.aget_context("alice", query="answer style") == "- [preferences] Prefers concise answers."
    assert (await manager.asearch("answer style", user_id="alice"))[0]["content"] == "Prefers concise answers."
    await asyncio.to_thread(manager.close)
