from __future__ import annotations

import threading
from typing import Any

from src.agents.title.updater import TitleGenerationTask, TitleGenerationUpdater


class TitleGenerationQueue:
    def __init__(self):
        self._updater = TitleGenerationUpdater()
        self._lock = threading.Lock()
        self._pending: set[str] = set()

    def add(self, thread_id: str, messages: list[Any]) -> None:
        with self._lock:
            if thread_id in self._pending:
                return
            self._pending.add(thread_id)

        worker = threading.Thread(target=self._process, args=(thread_id, messages), daemon=True)
        worker.start()

    def _process(self, thread_id: str, messages: list[Any]) -> None:
        try:
            self._updater.process(TitleGenerationTask(thread_id=thread_id, messages=messages))
        except Exception as e:
            print(f"Async title worker failed for thread {thread_id}: {e}")
        finally:
            with self._lock:
                self._pending.discard(thread_id)

    def clear(self) -> None:
        with self._lock:
            self._pending.clear()

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)


_title_queue: TitleGenerationQueue | None = None
_title_queue_lock = threading.Lock()


def get_title_queue() -> TitleGenerationQueue:
    global _title_queue
    with _title_queue_lock:
        if _title_queue is None:
            _title_queue = TitleGenerationQueue()
        return _title_queue


def reset_title_queue() -> None:
    global _title_queue
    with _title_queue_lock:
        if _title_queue is not None:
            _title_queue.clear()
        _title_queue = None
