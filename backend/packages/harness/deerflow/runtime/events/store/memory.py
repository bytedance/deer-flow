"""In-memory RunEventStore. Used when run_events.backend=memory (default) and in tests.

Thread-safe for single-process async usage (no threading locks needed
since all mutations happen within the same event loop).
"""

from __future__ import annotations

from datetime import UTC, datetime

from deerflow.runtime.events.store.base import RunEventStore


class MemoryRunEventStore(RunEventStore):
    def __init__(self) -> None:
        self._events: dict[str, list[dict]] = {}  # thread_id -> sorted event list
        self._seq_counters: dict[str, int] = {}  # thread_id -> last assigned seq

    def _next_seq(self, thread_id: str) -> int:
        current = self._seq_counters.get(thread_id, 0)
        next_val = current + 1
        self._seq_counters[thread_id] = next_val
        return next_val

    def _put_one(
        self,
        *,
        thread_id: str,
        run_id: str,
        event_type: str,
        category: str,
        content: str | dict = "",
        metadata: dict | None = None,
        created_at: str | None = None,
    ) -> dict:
        seq = self._next_seq(thread_id)
        record = {
            "thread_id": thread_id,
            "run_id": run_id,
            "event_type": event_type,
            "category": category,
            "content": content,
            "metadata": metadata or {},
            "seq": seq,
            "created_at": created_at or datetime.now(UTC).isoformat(),
        }
        self._events.setdefault(thread_id, []).append(record)
        return record

    async def put(
        self,
        *,
        thread_id,
        run_id,
        event_type,
        category,
        content="",
        metadata=None,
        created_at=None,
    ):
        return self._put_one(
            thread_id=thread_id,
            run_id=run_id,
            event_type=event_type,
            category=category,
            content=content,
            metadata=metadata,
            created_at=created_at,
        )

    async def put_batch(self, events):
        results = []
        for ev in events:
            record = self._put_one(**ev)
            results.append(record)
        return results

    async def list_messages(self, thread_id, *, limit=50, before_seq=None, after_seq=None):
        all_events = self._events.get(thread_id, [])
        messages = [e for e in all_events if e["category"] == "message"]

        if before_seq is not None:
            messages = [e for e in messages if e["seq"] < before_seq]
            # Take the last `limit` records
            return messages[-limit:]
        elif after_seq is not None:
            messages = [e for e in messages if e["seq"] > after_seq]
            return messages[:limit]
        else:
            # Return the latest `limit` records, ascending
            return messages[-limit:]

    async def list_events(self, thread_id, run_id, *, event_types=None, limit=500):
        all_events = self._events.get(thread_id, [])
        filtered = [e for e in all_events if e["run_id"] == run_id]
        if event_types is not None:
            filtered = [e for e in filtered if e["event_type"] in event_types]
        return filtered[:limit]

    async def list_messages_by_run(self, thread_id, run_id, *, limit=50, before_seq=None, after_seq=None):
        all_events = self._events.get(thread_id, [])
        filtered = [e for e in all_events if e["run_id"] == run_id and e["category"] == "message"]
        if before_seq is not None:
            filtered = [e for e in filtered if e["seq"] < before_seq]
        if after_seq is not None:
            filtered = [e for e in filtered if e["seq"] > after_seq]
        if after_seq is not None:
            return filtered[:limit]
        else:
            return filtered[-limit:] if len(filtered) > limit else filtered

    async def count_messages(self, thread_id):
        all_events = self._events.get(thread_id, [])
        return sum(1 for e in all_events if e["category"] == "message")

    async def delete_by_thread(self, thread_id):
        events = self._events.pop(thread_id, [])
        self._seq_counters.pop(thread_id, None)
        return len(events)

    async def delete_by_run(self, thread_id, run_id):
        all_events = self._events.get(thread_id, [])
        if not all_events:
            return 0
        remaining = [e for e in all_events if e["run_id"] != run_id]
        removed = len(all_events) - len(remaining)
        self._events[thread_id] = remaining
        return removed
