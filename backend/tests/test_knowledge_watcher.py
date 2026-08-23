from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from app.gateway.knowledge import watcher as watcher_module
from app.gateway.knowledge.watcher import (
    DatasetParsingState,
    KnowledgeEvent,
    KnowledgeWatcher,
    PollResult,
)


def _state(
    *,
    running: int = 0,
    unstart: int = 0,
    cancel: int = 0,
    done: int = 0,
    fail: int = 0,
) -> DatasetParsingState:
    return DatasetParsingState(
        dataset_id="dataset-1",
        unstart_count=unstart,
        running_count=running,
        cancel_count=cancel,
        done_count=done,
        fail_count=fail,
    )


def _result(state: DatasetParsingState, *, watch: float = 3, idle: float = 15) -> PollResult:
    return PollResult(
        datasets=[state],
        watch_interval_seconds=watch,
        idle_interval_seconds=idle,
    )


async def _next_event(stream: AsyncIterator[KnowledgeEvent | None]) -> KnowledgeEvent:
    while True:
        event = await anext(stream)
        if event is not None:
            return event


class _ControlledWait:
    def __init__(self) -> None:
        self.delays: asyncio.Queue[float] = asyncio.Queue()
        self.releases: asyncio.Queue[None] = asyncio.Queue()

    async def __call__(self, wake_event: asyncio.Event, delay: float) -> bool:
        del wake_event
        await self.delays.put(delay)
        await self.releases.get()
        return False


@pytest.mark.anyio
async def test_watcher_never_polls_without_subscribers_even_when_woken() -> None:
    loader = AsyncMock(return_value=_result(_state()))
    watcher = KnowledgeWatcher(loader)

    watcher.wake()
    await asyncio.sleep(0.02)

    loader.assert_not_awaited()
    assert watcher.subscriber_count == 0
    assert watcher.running is False


@pytest.mark.anyio
async def test_multiple_subscribers_share_one_loop_and_last_disconnect_stops_it() -> None:
    loader = AsyncMock(return_value=_result(_state()))
    controlled_wait = _ControlledWait()
    watcher = KnowledgeWatcher(loader, wait_for_wake=controlled_wait)
    first_stream = watcher.subscribe()

    await _next_event(first_stream)
    assert await controlled_wait.delays.get() == 15
    assert loader.await_count == 1

    second_stream = watcher.subscribe()
    replay = await _next_event(second_stream)
    assert replay.data["dataset_id"] == "dataset-1"
    assert watcher.subscriber_count == 2
    assert loader.await_count == 1

    await first_stream.aclose()
    assert watcher.subscriber_count == 1
    assert watcher.running is True

    await second_stream.aclose()
    assert watcher.subscriber_count == 0
    assert watcher.running is False


@pytest.mark.anyio
async def test_watcher_switches_fast_to_idle_and_does_not_stop_at_running_zero() -> None:
    states = iter([_state(running=1), _state(done=1), _state(done=1)])
    loader = AsyncMock(side_effect=lambda: _result(next(states)))
    controlled_wait = _ControlledWait()
    watcher = KnowledgeWatcher(loader, wait_for_wake=controlled_wait)
    stream = watcher.subscribe()

    first = await _next_event(stream)
    assert first.data["running_count"] == 1
    assert await controlled_wait.delays.get() == 3

    await controlled_wait.releases.put(None)
    second = await _next_event(stream)
    assert second.data["running_count"] == 0
    assert await controlled_wait.delays.get() == 15
    assert watcher.running is True

    await controlled_wait.releases.put(None)
    async with asyncio.timeout(1):
        while loader.await_count < 3:
            await asyncio.sleep(0)

    await stream.aclose()
    assert watcher.subscriber_count == 0
    assert watcher.running is False


@pytest.mark.anyio
async def test_wake_interrupts_idle_poll_and_forces_one_fast_interval() -> None:
    loader = AsyncMock(return_value=_result(_state()))
    watcher = KnowledgeWatcher(loader)
    stream = watcher.subscribe()

    await _next_event(stream)
    assert loader.await_count == 1

    watcher.wake()
    async with asyncio.timeout(1):
        while loader.await_count < 2:
            await asyncio.sleep(0)

    assert watcher.last_interval_seconds == 3
    await stream.aclose()


@pytest.mark.anyio
async def test_watcher_generates_progress_completed_and_failed_events() -> None:
    states = iter(
        [
            _state(running=1),
            _state(done=1, fail=1),
        ]
    )
    loader = AsyncMock(side_effect=lambda: _result(next(states)))
    failed_loader = AsyncMock(return_value=[{"id": "document-2", "name": "broken.pdf"}])
    controlled_wait = _ControlledWait()
    watcher = KnowledgeWatcher(
        loader,
        failed_documents_loader=failed_loader,
        wait_for_wake=controlled_wait,
    )
    stream = watcher.subscribe()

    initial = await _next_event(stream)
    assert initial.event == "dataset_parsing_progress"
    assert initial.data == {
        "dataset_id": "dataset-1",
        "unstart_count": 0,
        "running_count": 1,
        "cancel_count": 0,
        "done_count": 0,
        "fail_count": 0,
    }
    assert await controlled_wait.delays.get() == 3

    await controlled_wait.releases.put(None)
    changed = [await _next_event(stream) for _ in range(3)]

    assert [event.event for event in changed] == [
        "dataset_parsing_progress",
        "dataset_parsing_failed",
        "dataset_parsing_completed",
    ]
    assert changed[1].data == {
        "dataset_id": "dataset-1",
        "failed_documents": [{"id": "document-2", "name": "broken.pdf"}],
    }
    assert changed[2].data == {
        "dataset_id": "dataset-1",
        "done_count": 1,
        "fail_count": 1,
    }
    failed_loader.assert_awaited_once_with("dataset-1")

    await stream.aclose()


@pytest.mark.anyio
async def test_default_failed_document_loader_redacts_api_key_from_names(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        enabled=True,
        api_key=SecretStr("ragflow-secret"),
    )
    client = SimpleNamespace(
        list_all_documents=AsyncMock(
            return_value=[
                {"id": "document-1", "name": "failure-ragflow-secret.txt", "run": "FAIL"},
                {"id": "document-2", "name": "ignored.txt", "run": "DONE"},
            ]
        )
    )
    monkeypatch.setattr(watcher_module, "get_app_config", lambda: SimpleNamespace(knowledge_base=settings))
    monkeypatch.setattr(watcher_module, "build_ragflow_client", lambda current: client)

    failed = await watcher_module._load_failed_documents("dataset-1")

    assert failed == [{"id": "document-1", "name": "failure-[REDACTED].txt"}]


@pytest.mark.anyio
async def test_default_snapshot_loader_maps_nested_ragflow_status_and_intervals(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        enabled=True,
        api_key=SecretStr("ragflow-secret"),
        watch_interval_seconds=4,
        idle_interval_seconds=17,
    )
    client = SimpleNamespace(
        list_datasets_with_parsing_status=AsyncMock(
            return_value=[
                {
                    "id": "dataset-1",
                    "parsing_status": {
                        "unstart_count": 5,
                        "running_count": 4,
                        "cancel_count": 3,
                        "done_count": 2,
                        "fail_count": 1,
                    },
                }
            ]
        )
    )
    monkeypatch.setattr(watcher_module, "get_app_config", lambda: SimpleNamespace(knowledge_base=settings))
    monkeypatch.setattr(watcher_module, "build_ragflow_client", lambda current: client)

    result = await watcher_module._load_ragflow_snapshot()

    assert result.watch_interval_seconds == 4
    assert result.idle_interval_seconds == 17
    assert result.datasets == [
        DatasetParsingState(
            dataset_id="dataset-1",
            unstart_count=5,
            running_count=4,
            cancel_count=3,
            done_count=2,
            fail_count=1,
        )
    ]


@pytest.mark.anyio
async def test_polling_error_logs_only_exception_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    loader = AsyncMock(side_effect=RuntimeError("failed with ragflow-secret"))
    controlled_wait = _ControlledWait()
    watcher = KnowledgeWatcher(loader, wait_for_wake=controlled_wait)
    stream = watcher.subscribe()

    assert await anext(stream) is None
    assert "RuntimeError" in caplog.text
    assert "ragflow-secret" not in caplog.text

    await stream.aclose()
