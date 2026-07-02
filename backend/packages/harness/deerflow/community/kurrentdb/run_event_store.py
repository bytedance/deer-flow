"""Run-event storage backed by KurrentDB streams (deer-flow discussion for #3910).

Prototype counterpart to ``memory_storage.py``: instead of an in-memory dict
(``MemoryRunEventStore``), a JSONL file (``JsonlRunEventStore``), or a SQL
table (``DbRunEventStore``), every run event (messages + execution traces) is
appended to a per-thread KurrentDB stream ``deerflow.runs-{thread_id}``
(category ``deerflow.runs``). The full event history is therefore an
ordinary KurrentDB stream, inspectable in the Admin UI / MCP server exactly
like the memory streams.

Design notes (see the ``RunEventStore`` ABC for the behavioral contract):

- **seq is derived from stream revision, not from the append call's return
  value.** ``AsyncKurrentDBClient.append_to_stream`` returns a *global commit
  position* (``BatchAppendResp.success.position.commit_position``), not the
  per-stream revision -- confirmed by reading the installed
  ``kurrentdbclient`` source. The per-stream revision the protocol actually
  computes (``current_revision``) is not surfaced by the client's public
  API. So each event is stored WITHOUT a ``seq`` field in its JSON payload;
  ``seq`` is reconstructed on every read from each ``RecordedEvent``'s
  ``stream_position`` (0-indexed) as ``stream_position + 1``. ``put()``
  performs one ``append_to_stream`` call followed by one ``get_stream``
  call (backwards, small limit) to recover the assigned revision(s) before
  returning the complete record(s) -- an extra round trip versus a client
  that exposed ``current_revision`` directly, acceptable for this POC.
- **Reads filter in Python.** KurrentDB has no server-side predicate query
  over a stream's events, so ``list_messages`` / ``list_events`` /
  ``list_messages_by_run`` / ``count_messages`` read the whole stream (or a
  bounded backwards slice for the common "latest N" case) and filter by
  category / run_id / event_types / seq bounds in Python. Fine for the POC;
  a production version would want a category/run projection instead.
- **delete_by_thread is a real (soft) stream delete** via
  ``delete_stream(current_version=StreamState.ANY)``. The event count is
  read before deleting so the return value matches the ABC contract.
- **delete_by_run is event-native: an immutable log cannot un-append.**
  Instead of deleting anything, a ``run-redacted`` marker event carrying
  ``{"run_id": ...}`` is appended to the same stream. Every read path folds
  the set of redacted run ids first and filters out both that run's events
  and the markers themselves, so redaction is observably a deletion from
  every read path even though the underlying log is untouched. This mirrors
  how an event-sourced system actually handles "delete a run": tombstone,
  don't rewrite history.
- **Canonical dual-write (best-effort, messages only).** After a successful
  ``put``/``put_batch``, records with ``category == "message"`` are
  heuristically mapped to canonical ``kurrent-agent-schema`` events
  (``UserMessageReceived`` / ``AssistantTextGenerated``) and appended to the
  canonical ``AgentSession-{thread_id}`` stream (via
  ``agent_session_stream``), mirroring ``memory_storage.py``'s canonical
  ``FactRetained`` dual-write. Any failure (missing optional dependency,
  transport error, unmappable event) is logged and swallowed -- it never
  affects the primary write's return value or raises.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from deerflow.community.kurrentdb._config import resolve_timeout_seconds
from deerflow.runtime.events.store.base import RunEventStore

logger = logging.getLogger(__name__)

STREAM_PREFIX = "deerflow.runs"
REDACTION_EVENT_TYPE = "run-redacted"
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
DEFAULT_TIMEOUT_SECONDS = 10.0

# kurrent-agents canonical session stream builder input; deer-flow's thread_id
# is used directly as the canonical session id.
_canonical_schema_warned = False


def _make_default_client(connection_string: str) -> Any:
    from kurrentdbclient import AsyncKurrentDBClient

    return AsyncKurrentDBClient(uri=connection_string)


def _validate_id(value: str, label: str) -> str:
    if not value or not _ID_PATTERN.match(value):
        raise ValueError(f"Invalid {label} {value!r}: only alphanumeric characters, hyphens, and underscores are allowed.")
    return value


class KurrentRunEventStore(RunEventStore):
    """RunEventStore backed by one KurrentDB stream per thread.

    Optional integration: requires the ``kurrentdbclient`` package (the
    ``deerflow-harness[kurrentdb]`` extra) and the
    ``KURRENTDB_CONNECTION_STRING`` environment variable, matching
    ``KurrentdbMemoryStorage``.
    """

    def __init__(self, client_factory: Callable[[], Any] | None = None):
        if client_factory is None:
            connection_string = os.environ.get("KURRENTDB_CONNECTION_STRING", "").strip()
            if not connection_string:
                raise RuntimeError("KurrentRunEventStore requires the KURRENTDB_CONNECTION_STRING environment variable (e.g. kurrentdb://localhost:2113?tls=false)")
            client_factory = functools.partial(_make_default_client, connection_string)
        self._client_factory = client_factory
        # Client creation (and the connect() call) is lazy: __init__ never
        # touches the network, matching KurrentdbMemoryStorage and keeping
        # make_run_event_store() side-effect free.
        self._client: Any | None = None
        self._connected = False
        self._timeout = resolve_timeout_seconds("KURRENTDB_RUN_EVENTS_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)

    @staticmethod
    def _stream_name(thread_id: str) -> str:
        _validate_id(thread_id, "thread_id")
        return f"{STREAM_PREFIX}-{thread_id}"

    async def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        if not self._connected:
            await self._client.connect()
            self._connected = True
        return self._client

    # -- low-level stream access -------------------------------------------------

    async def _read_all(self, thread_id: str) -> list[dict]:
        """Read every live (non-redacted) event on the thread's stream, seq ascending.

        Returns ``[]`` when the stream does not exist -- a legitimate empty
        answer, not an error. Transport errors propagate to the caller.
        """
        from kurrentdbclient.exceptions import NotFoundError

        client = await self._get_client()
        stream_name = self._stream_name(thread_id)
        try:
            recorded = await client.get_stream(stream_name, timeout=self._timeout)
        except NotFoundError:
            return []
        return self._decode_and_filter(recorded)

    def _decode_and_filter(self, recorded: tuple[Any, ...]) -> list[dict]:
        """Decode RecordedEvents into records with seq filled in, dropping redacted runs and markers."""
        raw: list[tuple[int, dict | None, str]] = []
        redacted_run_ids: set[str] = set()
        for event in recorded:
            seq = event.stream_position + 1
            if event.type == REDACTION_EVENT_TYPE:
                try:
                    marker = json.loads(event.data)
                    redacted_run_ids.add(marker["run_id"])
                except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError):
                    logger.warning("Skipping malformed %s marker at seq=%d on stream", REDACTION_EVENT_TYPE, seq)
                raw.append((seq, None, event.type))
                continue
            try:
                record = json.loads(event.data)
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.warning("Skipping malformed event data at seq=%d (type=%s)", seq, event.type)
                raw.append((seq, None, event.type))
                continue
            record["seq"] = seq
            record["event_type"] = event.type
            raw.append((seq, record, event.type))

        results = []
        for seq, record, _event_type in raw:
            if record is None:
                continue
            if record.get("run_id") in redacted_run_ids:
                continue
            results.append(record)
        results.sort(key=lambda r: r["seq"])
        return results

    # -- put / put_batch -----------------------------------------------------

    @staticmethod
    def _record_payload(*, thread_id, run_id, event_type, category, content, metadata, created_at) -> dict:
        return {
            "thread_id": thread_id,
            "run_id": run_id,
            "event_type": event_type,
            "category": category,
            "content": content,
            "metadata": metadata or {},
            "created_at": created_at or datetime.now(UTC).isoformat(),
        }

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
        record = self._record_payload(
            thread_id=thread_id,
            run_id=run_id,
            event_type=event_type,
            category=category,
            content=content,
            metadata=metadata,
            created_at=created_at,
        )
        results = await self._append_records(thread_id, [record])
        return results[0]

    async def put_batch(self, events: list[dict]) -> list[dict]:
        if not events:
            return []
        thread_ids = {ev["thread_id"] for ev in events}
        if len(thread_ids) > 1:
            raise ValueError(f"put_batch requires all events to share the same thread_id, got: {sorted(thread_ids)}")
        thread_id = next(iter(thread_ids))
        records = [
            self._record_payload(
                thread_id=ev["thread_id"],
                run_id=ev["run_id"],
                event_type=ev["event_type"],
                category=ev["category"],
                content=ev.get("content", ""),
                metadata=ev.get("metadata"),
                created_at=ev.get("created_at"),
            )
            for ev in events
        ]
        return await self._append_records(thread_id, records)

    async def _append_records(self, thread_id: str, records: list[dict]) -> list[dict]:
        """Append ``records`` (without seq) in one call; return complete records with seq derived from stream revision."""
        from kurrentdbclient import NewEvent, StreamState
        from kurrentdbclient.exceptions import NotFoundError

        client = await self._get_client()
        stream_name = self._stream_name(thread_id)
        new_events = [NewEvent(type=r["event_type"], data=json.dumps(r, default=str, ensure_ascii=False).encode("utf-8")) for r in records]
        await client.append_to_stream(stream_name, events=new_events, current_version=StreamState.ANY, timeout=self._timeout)

        # append_to_stream's return value is a global commit position, not
        # the per-stream revision -- read the tail back to recover the
        # revision(s) actually assigned to the events we just wrote.
        n = len(records)
        try:
            tail = await client.get_stream(stream_name, backwards=True, limit=n, timeout=self._timeout)
        except NotFoundError:  # pragma: no cover - defensive, stream must exist right after append
            raise RuntimeError(f"Stream {stream_name!r} not found immediately after append") from None
        tail_ascending = list(reversed(tail))[-n:]
        results = []
        for record, event in zip(records, tail_ascending, strict=True):
            complete = dict(record)
            complete["seq"] = event.stream_position + 1
            results.append(complete)

        await self._emit_canonical_events(thread_id, results)
        return results

    # -- reads -----------------------------------------------------------------

    async def list_messages(self, thread_id, *, limit=50, before_seq=None, after_seq=None):
        events = await self._read_all(thread_id)
        messages = [e for e in events if e["category"] == "message"]
        return self._paginate(messages, limit=limit, before_seq=before_seq, after_seq=after_seq)

    async def list_events(self, thread_id, run_id, *, event_types=None, limit=500):
        events = await self._read_all(thread_id)
        run_events = [e for e in events if e["run_id"] == run_id]
        if event_types is not None:
            run_events = [e for e in run_events if e["event_type"] in event_types]
        return run_events[:limit]

    async def list_messages_by_run(self, thread_id, run_id, *, limit=50, before_seq=None, after_seq=None):
        events = await self._read_all(thread_id)
        messages = [e for e in events if e["run_id"] == run_id and e["category"] == "message"]
        return self._paginate(messages, limit=limit, before_seq=before_seq, after_seq=after_seq)

    @staticmethod
    def _paginate(messages: list[dict], *, limit: int, before_seq: int | None, after_seq: int | None) -> list[dict]:
        if before_seq is not None:
            window = [m for m in messages if m["seq"] < before_seq]
            return window[-limit:]
        elif after_seq is not None:
            window = [m for m in messages if m["seq"] > after_seq]
            return window[:limit]
        else:
            return messages[-limit:]

    async def count_messages(self, thread_id):
        events = await self._read_all(thread_id)
        return sum(1 for e in events if e["category"] == "message")

    # -- deletes -----------------------------------------------------------------

    async def delete_by_thread(self, thread_id):
        from kurrentdbclient import StreamState
        from kurrentdbclient.exceptions import NotFoundError

        client = await self._get_client()
        stream_name = self._stream_name(thread_id)
        try:
            existing = await client.get_stream(stream_name, timeout=self._timeout)
        except NotFoundError:
            return 0
        count = len(existing)
        await client.delete_stream(stream_name, current_version=StreamState.ANY, timeout=self._timeout)
        return count

    async def delete_by_run(self, thread_id, run_id):
        events = await self._read_all(thread_id)
        run_events = [e for e in events if e["run_id"] == run_id]
        if not run_events:
            return 0

        from kurrentdbclient import NewEvent, StreamState

        client = await self._get_client()
        stream_name = self._stream_name(thread_id)
        marker = NewEvent(type=REDACTION_EVENT_TYPE, data=json.dumps({"run_id": run_id}).encode("utf-8"))
        await client.append_to_stream(stream_name, events=marker, current_version=StreamState.ANY, timeout=self._timeout)
        return len(run_events)

    # -- canonical dual-write (best-effort, messages only) ------------------

    async def _emit_canonical_events(self, thread_id: str, records: list[dict]) -> None:
        message_records = [r for r in records if r["category"] == "message"]
        if not message_records:
            return
        try:
            await self._append_canonical_message_events(thread_id, message_records)
        except Exception as e:
            logger.warning("Best-effort canonical kurrent-agents session event emission failed: %s", e)

    @staticmethod
    def _map_to_canonical(record: dict) -> Any | None:
        """Map a deer-flow message record to a canonical kurrent-agent-schema event, or None if unmappable."""
        from kurrent_agent_schema import AssistantTextGenerated, UserMessageReceived

        content = record.get("content", "")
        if not isinstance(content, str) or not content:
            return None
        event_type = record.get("event_type", "")
        if "human" in event_type or "user" in event_type:
            return UserMessageReceived(content=content)
        if "ai" in event_type or "assistant" in event_type:
            return AssistantTextGenerated(content=content)
        return None

    async def _append_canonical_message_events(self, thread_id: str, message_records: list[dict]) -> None:
        global _canonical_schema_warned
        try:
            from kurrent_agent_schema import EVENT_TYPE_NAMES, SCHEMA_VERSION, agent_session_stream, to_json
        except ImportError as e:
            if not _canonical_schema_warned:
                logger.warning("kurrent_agent_schema is not installed; skipping canonical session event emission (install the deerflow-harness[kurrentdb] extra): %s", e)
                _canonical_schema_warned = True
            return
        from kurrentdbclient import NewEvent, StreamState

        canonical_events = []
        for record in message_records:
            canonical = self._map_to_canonical(record)
            if canonical is None:
                continue
            event_type_name = EVENT_TYPE_NAMES[type(canonical)]
            canonical_events.append(
                NewEvent(
                    type=event_type_name,
                    data=to_json(canonical).encode("utf-8"),
                    metadata=json.dumps({"schema_version": SCHEMA_VERSION}, ensure_ascii=False).encode("utf-8"),
                )
            )
        if not canonical_events:
            return
        client = await self._get_client()
        canonical_stream = agent_session_stream(thread_id)
        await client.append_to_stream(canonical_stream, events=canonical_events, current_version=StreamState.ANY, timeout=self._timeout)
        logger.info("Emitted %d canonical session event(s) to %s", len(canonical_events), canonical_stream)
