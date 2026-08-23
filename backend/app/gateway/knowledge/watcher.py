"""Subscriber-driven, process-local polling for RAGFlow parsing progress."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from deerflow.config import get_app_config

from . import build_ragflow_client, ragflow_api_key

logger = logging.getLogger(__name__)

_DEFAULT_WATCH_INTERVAL_SECONDS = 3.0
_DEFAULT_IDLE_INTERVAL_SECONDS = 15.0
_SUBSCRIBER_QUEUE_SIZE = 512


@dataclass(frozen=True, slots=True)
class DatasetParsingState:
    dataset_id: str
    unstart_count: int
    running_count: int
    cancel_count: int
    done_count: int
    fail_count: int

    def progress_payload(self) -> dict[str, int | str]:
        return {
            "dataset_id": self.dataset_id,
            "unstart_count": self.unstart_count,
            "running_count": self.running_count,
            "cancel_count": self.cancel_count,
            "done_count": self.done_count,
            "fail_count": self.fail_count,
        }

    @property
    def terminal_count(self) -> int:
        return self.cancel_count + self.done_count + self.fail_count


@dataclass(frozen=True, slots=True)
class PollResult:
    datasets: list[DatasetParsingState]
    watch_interval_seconds: float
    idle_interval_seconds: float


@dataclass(frozen=True, slots=True)
class KnowledgeEvent:
    event: str
    data: dict[str, Any]

    def to_sse(self) -> str:
        payload = json.dumps(self.data, ensure_ascii=False, separators=(",", ":"))
        return f"event: {self.event}\ndata: {payload}\n\n"


SnapshotLoader = Callable[[], Awaitable[PollResult]]
FailedDocumentsLoader = Callable[[str], Awaitable[list[dict[str, str]]]]
WaitForWake = Callable[[asyncio.Event, float], Awaitable[bool]]


def _status_count(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _dataset_states(datasets: list[dict[str, Any]]) -> list[DatasetParsingState]:
    states: list[DatasetParsingState] = []
    for dataset in datasets:
        dataset_id = dataset.get("id")
        if not isinstance(dataset_id, str) or not dataset_id:
            continue
        raw_status = dataset.get("parsing_status")
        status = raw_status if isinstance(raw_status, dict) else dataset
        states.append(
            DatasetParsingState(
                dataset_id=dataset_id,
                unstart_count=_status_count(status.get("unstart_count")),
                running_count=_status_count(status.get("running_count")),
                cancel_count=_status_count(status.get("cancel_count")),
                done_count=_status_count(status.get("done_count")),
                fail_count=_status_count(status.get("fail_count")),
            )
        )
    return states


async def _load_ragflow_snapshot() -> PollResult:
    settings = get_app_config().knowledge_base
    if not settings.enabled or ragflow_api_key(settings) is None:
        raise RuntimeError("RAGFlow knowledge integration is unavailable")
    datasets = await build_ragflow_client(settings).list_datasets_with_parsing_status()
    return PollResult(
        datasets=_dataset_states(datasets),
        watch_interval_seconds=float(settings.watch_interval_seconds),
        idle_interval_seconds=float(settings.idle_interval_seconds),
    )


async def _load_failed_documents(dataset_id: str) -> list[dict[str, str]]:
    settings = get_app_config().knowledge_base
    api_key = ragflow_api_key(settings)
    if not settings.enabled or api_key is None:
        raise RuntimeError("RAGFlow knowledge integration is unavailable")
    documents = await build_ragflow_client(settings).list_all_documents(dataset_id)
    failed: list[dict[str, str]] = []
    for document in documents:
        run_status = str(document.get("run", "")).upper()
        if run_status not in {"FAIL", "4"}:
            continue
        document_id = document.get("id")
        name = document.get("name")
        if not isinstance(document_id, str) or not document_id:
            continue
        item = {"id": document_id}
        if isinstance(name, str) and name:
            item["name"] = name.replace(api_key, "[REDACTED]")
        failed.append(item)
    return failed


async def _default_wait_for_wake(wake_event: asyncio.Event, delay: float) -> bool:
    try:
        await asyncio.wait_for(wake_event.wait(), timeout=delay)
    except TimeoutError:
        return False
    return True


class KnowledgeWatcher:
    """Fan one RAGFlow polling loop out to all local SSE subscribers."""

    def __init__(
        self,
        snapshot_loader: SnapshotLoader,
        *,
        failed_documents_loader: FailedDocumentsLoader | None = None,
        wait_for_wake: WaitForWake | None = None,
    ) -> None:
        self._snapshot_loader = snapshot_loader
        self._failed_documents_loader = failed_documents_loader
        self._wait_for_wake = wait_for_wake or _default_wait_for_wake
        self._subscribers: set[asyncio.Queue[KnowledgeEvent | None]] = set()
        self._snapshot: dict[str, DatasetParsingState] = {}
        self._failed_documents: dict[str, list[dict[str, str]]] = {}
        self._task: asyncio.Task[None] | None = None
        self._wake_event: asyncio.Event | None = None
        self._force_fast = False
        self._has_running = False
        self._watch_interval_seconds = _DEFAULT_WATCH_INTERVAL_SECONDS
        self._idle_interval_seconds = _DEFAULT_IDLE_INTERVAL_SECONDS
        self.last_interval_seconds: float | None = None

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def wake(self) -> None:
        """Interrupt an idle wait and force at least one fast interval."""
        self._force_fast = True
        if self._wake_event is not None:
            self._wake_event.set()

    async def subscribe(self) -> AsyncIterator[KnowledgeEvent | None]:
        """Subscribe to current and future states until the client disconnects."""
        queue: asyncio.Queue[KnowledgeEvent | None] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_SIZE)
        self._subscribers.add(queue)
        for dataset_id in sorted(self._snapshot):
            state = self._snapshot[dataset_id]
            self._enqueue(queue, KnowledgeEvent("dataset_parsing_progress", state.progress_payload()))
            failed_documents = self._failed_documents.get(dataset_id)
            if state.fail_count > 0 and failed_documents is not None:
                self._enqueue(
                    queue,
                    KnowledgeEvent(
                        "dataset_parsing_failed",
                        {"dataset_id": dataset_id, "failed_documents": failed_documents},
                    ),
                )
        self._ensure_polling()

        try:
            while True:
                yield await queue.get()
        finally:
            await self._unsubscribe(queue)

    def _ensure_polling(self) -> None:
        if self.running:
            return
        self._wake_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="ragflow-knowledge-watcher")

    async def _unsubscribe(self, queue: asyncio.Queue[KnowledgeEvent | None]) -> None:
        self._subscribers.discard(queue)
        if self._subscribers:
            return
        task = self._task
        self._task = None
        self._wake_event = None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    @staticmethod
    def _enqueue(queue: asyncio.Queue[KnowledgeEvent | None], event: KnowledgeEvent | None) -> None:
        if queue.full():
            with suppress(asyncio.QueueEmpty):
                queue.get_nowait()
        with suppress(asyncio.QueueFull):
            queue.put_nowait(event)

    def _broadcast(self, event: KnowledgeEvent | None) -> None:
        for queue in tuple(self._subscribers):
            self._enqueue(queue, event)

    async def _apply_result(self, result: PollResult) -> None:
        current = {state.dataset_id: state for state in result.datasets}
        for dataset_id in sorted(current):
            state = current[dataset_id]
            previous = self._snapshot.get(dataset_id)
            if previous == state:
                continue

            self._broadcast(KnowledgeEvent("dataset_parsing_progress", state.progress_payload()))

            failure_increased = state.fail_count > (previous.fail_count if previous is not None else 0)
            if failure_increased:
                failed_documents: list[dict[str, str]] = []
                if self._failed_documents_loader is not None:
                    try:
                        failed_documents = await self._failed_documents_loader(dataset_id)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.warning("RAGFlow failed-document detail polling failed (%s)", type(exc).__name__)
                self._failed_documents[dataset_id] = failed_documents
                self._broadcast(
                    KnowledgeEvent(
                        "dataset_parsing_failed",
                        {"dataset_id": dataset_id, "failed_documents": failed_documents},
                    )
                )
            elif state.fail_count == 0:
                self._failed_documents.pop(dataset_id, None)

            terminal_increased = previous is not None and state.terminal_count > previous.terminal_count
            parsing_completed = previous is not None and state.running_count == 0 and (previous.running_count > 0 or terminal_increased)
            if parsing_completed:
                self._broadcast(
                    KnowledgeEvent(
                        "dataset_parsing_completed",
                        {
                            "dataset_id": dataset_id,
                            "done_count": state.done_count,
                            "fail_count": state.fail_count,
                        },
                    )
                )

        removed_ids = self._snapshot.keys() - current.keys()
        for dataset_id in removed_ids:
            self._failed_documents.pop(dataset_id, None)
        self._snapshot = current
        self._has_running = any(state.running_count > 0 for state in current.values())

    async def _run(self) -> None:
        current_task = asyncio.current_task()
        try:
            while self._subscribers:
                wake_event = self._wake_event
                if wake_event is None:
                    return
                wake_event.clear()

                try:
                    result = await self._snapshot_loader()
                    self._watch_interval_seconds = max(0.001, float(result.watch_interval_seconds))
                    self._idle_interval_seconds = max(0.001, float(result.idle_interval_seconds))
                    await self._apply_result(result)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("RAGFlow parsing-status polling failed (%s)", type(exc).__name__)

                self._broadcast(None)
                force_fast = self._force_fast
                delay = self._watch_interval_seconds if self._has_running or force_fast else self._idle_interval_seconds
                self.last_interval_seconds = delay
                woken = await self._wait_for_wake(wake_event, delay)
                if force_fast and not woken:
                    self._force_fast = False
        finally:
            if self._task is current_task:
                self._task = None


_watcher = KnowledgeWatcher(
    _load_ragflow_snapshot,
    failed_documents_loader=_load_failed_documents,
)


def get_knowledge_watcher() -> KnowledgeWatcher:
    """Return the one process-local parsing watcher."""
    return _watcher


__all__ = [
    "DatasetParsingState",
    "KnowledgeEvent",
    "KnowledgeWatcher",
    "PollResult",
    "get_knowledge_watcher",
]
