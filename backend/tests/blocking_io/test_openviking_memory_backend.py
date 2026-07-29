"""Regression anchors: OpenViking async memory methods must not block the loop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.openviking.models import OpenVikingCommitResult, OpenVikingSearchHit
from deerflow.agents.memory.backends.openviking.openviking_manager import OpenVikingMemoryManager


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


def _manager(tmp_path: Path) -> OpenVikingMemoryManager:
    manager = OpenVikingMemoryManager.from_config(
        {
            "base_url": "http://openviking:1933",
            "storage_path": str(tmp_path),
            "auth_mode": "trusted",
            "account": "deerflow",
            "startup_policy": "warn",
        }
    )
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
