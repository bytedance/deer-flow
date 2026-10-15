"""Regression anchors: Honcho async methods must not block the loop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.honcho.honcho_manager import HonchoMemoryManager


class _BlockingFakeClient:
    """Every method does real blocking file IO — trips Blockbuster if run on the loop."""

    def __init__(self, probe_dir: Path):
        self._probe = probe_dir / "probe.txt"

    def _block(self) -> None:
        self._probe.write_text("blocked io")

    def get_or_create_peer(self, ws: str, pid: str) -> None:
        self._block()

    def get_or_create_session(self, ws: str, sid: str) -> None:
        self._block()

    def set_session_peers(self, ws: str, sid: str, pids: list[str]) -> None:
        self._block()

    def add_messages(self, ws: str, sid: str, msgs: list[Any]) -> None:
        self._block()

    def working_representation(self, ws: str, pid: str, *, max_conclusions: int = 25) -> str:
        self._block()
        return "rep"

    def search(self, ws: str, query: str, *, limit: int = 5) -> list[Any]:
        self._block()
        return []

    def close(self) -> None:
        pass


def _manager(tmp_path: Path) -> HonchoMemoryManager:
    mgr = HonchoMemoryManager.from_config({"base_url": "http://honcho.test"})
    mgr._client = _BlockingFakeClient(tmp_path)
    return mgr


@pytest.mark.asyncio
async def test_async_honcho_operations_do_not_block_event_loop(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    messages: list[Any] = [
        HumanMessage("hello", id="h1"),
        AIMessage("hi", id="a1"),
    ]

    await manager.aadd(
        "thread-1",
        messages,
        user_id="alice",
    )
    assert await manager.aget_context("alice") is not None
    assert (
        await manager.asearch(
            "query",
            user_id="alice",
        )
        == []
    )
