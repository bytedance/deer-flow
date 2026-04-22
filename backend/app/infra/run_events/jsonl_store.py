"""JSONL run event store backend owned by app infrastructure."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class JsonlRunEventStore:
    """Append-only JSONL implementation of the runs RunEventStore protocol."""

    def __init__(
        self,
        base_dir: Path | str = ".deer-flow/run-events",
    ) -> None:
        self._base_dir = Path(base_dir)
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def put_batch(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not events:
            return []

        grouped: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            grouped.setdefault(str(event["thread_id"]), []).append(event)

        records_by_thread: dict[str, list[dict[str, Any]]] = {}
        for thread_id, thread_events in grouped.items():
            async with await self._thread_lock(thread_id):
                records_by_thread[thread_id] = self._append_thread_events(thread_id, thread_events)

        indexes = {thread_id: 0 for thread_id in records_by_thread}
        ordered: list[dict[str, Any]] = []
        for event in events:
            thread_id = str(event["thread_id"])
            index = indexes[thread_id]
            ordered.append(records_by_thread[thread_id][index])
            indexes[thread_id] = index + 1
        return ordered

    async def list_messages(
        self,
        thread_id: str,
        *,
        limit: int = 50,
        before_seq: int | None = None,
        after_seq: int | None = None,
    ) -> list[dict[str, Any]]:
        events = [event for event in await self._read_thread_events(thread_id) if event.get("category") == "message"]
        if before_seq is not None:
            events = [event for event in events if int(event["seq"]) < before_seq]
            return events[-limit:]
        if after_seq is not None:
            events = [event for event in events if int(event["seq"]) > after_seq]
            return events[:limit]
        return events[-limit:]

    async def list_events(
        self,
        thread_id: str,
        run_id: str,
        *,
        event_types: list[str] | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        event_type_set = set(event_types or [])
        events = [
            event
            for event in await self._read_thread_events(thread_id)
            if event.get("run_id") == run_id and (not event_type_set or event.get("event_type") in event_type_set)
        ]
        return events[:limit]

    async def list_messages_by_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        limit: int = 50,
        before_seq: int | None = None,
        after_seq: int | None = None,
    ) -> list[dict[str, Any]]:
        events = [
            event
            for event in await self._read_thread_events(thread_id)
            if event.get("run_id") == run_id and event.get("category") == "message"
        ]
        if before_seq is not None:
            events = [event for event in events if int(event["seq"]) < before_seq]
            return events[-limit:]
        if after_seq is not None:
            events = [event for event in events if int(event["seq"]) > after_seq]
            return events[:limit]
        return events[-limit:]

    async def count_messages(self, thread_id: str) -> int:
        return len(await self.list_messages(thread_id, limit=10**9))

    async def delete_by_thread(self, thread_id: str) -> int:
        async with await self._thread_lock(thread_id):
            count = len(self._read_thread_events_sync(thread_id))
            shutil.rmtree(self._thread_dir(thread_id), ignore_errors=True)
        return count

    async def delete_by_run(self, thread_id: str, run_id: str) -> int:
        async with await self._thread_lock(thread_id):
            events = self._read_thread_events_sync(thread_id)
            kept = [event for event in events if event.get("run_id") != run_id]
            deleted = len(events) - len(kept)
            if deleted:
                self._write_thread_events(thread_id, kept)
        return deleted

    async def _thread_lock(self, thread_id: str) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(thread_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[thread_id] = lock
            return lock

    def _append_thread_events(self, thread_id: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        thread_dir = self._thread_dir(thread_id)
        thread_dir.mkdir(parents=True, exist_ok=True)

        seq = self._read_seq(thread_id)
        records: list[dict[str, Any]] = []
        with self._events_path(thread_id).open("a", encoding="utf-8") as file:
            for event in events:
                seq += 1
                record = self._normalize_event(event, seq=seq)
                file.write(json.dumps(record, ensure_ascii=False, default=str))
                file.write("\n")
                records.append(record)
        self._write_seq(thread_id, seq)
        return records

    def _normalize_event(self, event: dict[str, Any], *, seq: int) -> dict[str, Any]:
        created_at = event.get("created_at")
        if isinstance(created_at, datetime):
            created_at_value = created_at.isoformat()
        elif created_at:
            created_at_value = str(created_at)
        else:
            created_at_value = datetime.now(UTC).isoformat()

        return {
            "thread_id": str(event["thread_id"]),
            "run_id": str(event["run_id"]),
            "seq": seq,
            "event_type": str(event["event_type"]),
            "category": str(event["category"]),
            "content": event.get("content", ""),
            "metadata": dict(event.get("metadata") or {}),
            "created_at": created_at_value,
        }

    async def _read_thread_events(self, thread_id: str) -> list[dict[str, Any]]:
        async with await self._thread_lock(thread_id):
            return self._read_thread_events_sync(thread_id)

    def _read_thread_events_sync(self, thread_id: str) -> list[dict[str, Any]]:
        path = self._events_path(thread_id)
        if not path.exists():
            return []

        events: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as file:
            for line in file:
                stripped = line.strip()
                if stripped:
                    events.append(json.loads(stripped))
        return events

    def _write_thread_events(self, thread_id: str, events: Iterable[dict[str, Any]]) -> None:
        thread_dir = self._thread_dir(thread_id)
        thread_dir.mkdir(parents=True, exist_ok=True)
        temp_path = self._events_path(thread_id).with_suffix(".jsonl.tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            for event in events:
                file.write(json.dumps(event, ensure_ascii=False, default=str))
                file.write("\n")
        temp_path.replace(self._events_path(thread_id))

    def _read_seq(self, thread_id: str) -> int:
        path = self._seq_path(thread_id)
        if not path.exists():
            return 0
        try:
            return int(path.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            return 0

    def _write_seq(self, thread_id: str, seq: int) -> None:
        self._seq_path(thread_id).write_text(str(seq), encoding="utf-8")

    def _thread_dir(self, thread_id: str) -> Path:
        return self._base_dir / "threads" / thread_id

    def _events_path(self, thread_id: str) -> Path:
        return self._thread_dir(thread_id) / "events.jsonl"

    def _seq_path(self, thread_id: str) -> Path:
        return self._thread_dir(thread_id) / "seq"
