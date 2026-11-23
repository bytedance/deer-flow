"""Regression anchor: ``/threads/{id}/token-usage`` must read the live config off the loop.

``build_context_usage`` resolves the model capacity for its payload through
``app.gateway.deps.get_config``, which routes to ``get_app_config()``. That
loader revalidates on every call — it stats and hashes the whole
``config.yaml``, then does the same for ``extensions_config.json`` (see
**Config Caching** in ``deerflow/config/AGENTS.md``) — and reparses both after
an edit. ``GET /threads/{thread_id}/token-usage`` builds this payload on every
request, while runs, streams and other threads share the same Gateway loop, so
a view requested just after a config edit made that request stall the loop for
the whole reload. The token count a few lines below the read was already
offloaded with ``asyncio.to_thread``; the config read now joins it.

Each anchor performs a real filesystem read and asserts the capacity that only
the bytes on disk can produce, so it cannot pass because the read was stubbed
away, and it records the calling thread so a dropped wrapper is attributed.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from blockbuster import BlockingError
from fastapi import HTTPException
from langchain_core.messages import HumanMessage

from app.gateway import context_usage

pytestmark = pytest.mark.asyncio

_CAPACITY_ON_DISK = 4096
_CONFIG_TEXT = f"model: disk-model\ntoken_capacity: {_CAPACITY_ON_DISK}\n"


class _RecordingConfigLoader:
    """``get_config`` stand-in that reads from disk, and remembers where it ran."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls = 0
        self.on_loop_thread = False

    def __call__(self) -> SimpleNamespace:
        self.calls += 1
        self.on_loop_thread = threading.current_thread() is threading.main_thread()
        name, capacity = self.path.read_text(encoding="utf-8").splitlines()
        model_name = name.split(":", 1)[1].strip()
        return SimpleNamespace(
            models=[SimpleNamespace(name=model_name)],
            get_model_config=lambda requested: SimpleNamespace(context_window=int(capacity.split(":", 1)[1])) if requested == model_name else None,
        )


class _Accessor:
    async def aget(self, config: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(values={"messages": [HumanMessage(content="context window probe")]})


async def _stub_accessor_builder(request, *, thread_id: str):
    return _Accessor(), {"configurable": {"thread_id": thread_id}}


class _RunStore:
    async def list_by_thread(self, thread_id: str, *, limit: int = 1, user_id: str | None = None):
        return [{"model_name": "disk-model"}]


def _write_capacity_file(path: Path) -> Path:
    path.write_text(_CONFIG_TEXT, encoding="utf-8")
    return path


@pytest_asyncio.fixture
async def loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[_RecordingConfigLoader]:
    # The strict gate wraps setup as well as the call, so the fixture's own
    # write goes through a worker.
    config_file = await asyncio.to_thread(_write_capacity_file, tmp_path / "capacity.yaml")
    recorder = _RecordingConfigLoader(config_file)
    monkeypatch.setattr(context_usage, "get_config", recorder)
    monkeypatch.setattr(context_usage, "build_thread_checkpoint_state_accessor", _stub_accessor_builder)
    yield recorder
    await asyncio.to_thread(config_file.unlink)


async def test_build_context_usage_reads_capacity_off_the_loop(loader: _RecordingConfigLoader) -> None:
    payload = await context_usage.build_context_usage(SimpleNamespace(), "thread-1", _RunStore())

    assert payload is not None
    # The capacity only the file on disk can produce: the read was not stubbed away.
    assert payload["max_context_tokens"] == _CAPACITY_ON_DISK
    assert payload["token_count"] > 0
    assert payload["percentage"] == pytest.approx(round(payload["token_count"] / _CAPACITY_ON_DISK * 100, 1))
    assert loader.calls == 1
    assert not loader.on_loop_thread, "the live config read ran on the event loop thread"


async def test_offloaded_read_still_reports_an_unavailable_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Control: moving the read to a worker must not turn a 503 into a payload."""

    def raise_unavailable() -> SimpleNamespace:
        raise HTTPException(status_code=503, detail="Configuration not available")

    monkeypatch.setattr(context_usage, "get_config", raise_unavailable)
    monkeypatch.setattr(context_usage, "build_thread_checkpoint_state_accessor", _stub_accessor_builder)

    assert await context_usage.build_context_usage(SimpleNamespace(), "thread-1", _RunStore()) is None


async def test_inline_config_read_actually_trips_the_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Meta-check: the gate is live around this module, so the anchor above is not vacuous.

    The strict gate only trips when the blocking read sits under an ``app`` or
    ``deerflow`` frame, so this calls the loader ``deps.get_config`` routes to.
    That accessor maps every failure to 503, which would hide the
    ``BlockingError``, hence the loader itself.
    """
    from deerflow.config.app_config import get_app_config, reset_app_config

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(tmp_path / "capacity.yaml"))
    await asyncio.to_thread(reset_app_config)
    try:
        with pytest.raises(BlockingError):
            get_app_config()
    finally:
        await asyncio.to_thread(reset_app_config)
