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
  performs one ``append_to_stream`` call followed by a backwards, ID-correlated
  ``get_stream`` read to recover the assigned revision(s) before returning
  the complete record(s) -- an extra round trip versus a client that exposed
  ``current_revision`` directly, acceptable for this POC.
- **Stable per-record event IDs, correlated on read-back (not positional
  zip).** Each record is stamped with a ``_kurrent_event_id`` (uuid4) before
  append and that id becomes the ``NewEvent(id=...)``. The post-append
  read-back pages backwards through the stream collecting
  ``RecordedEvent``s whose ``id`` is in this call's id set, and assigns each
  record the ``stream_position`` of its *own* matched event. This is
  correct even when another writer's append lands on the same thread stream
  between this call's append and its read-back (naive positional zip against
  the tail is not: a concurrent interleaving shifts which physical events
  the backwards slice returns, misattributing seq to the wrong records).
- **Retry-safe by construction.** ``RunJournal`` (``runtime/journal.py``)
  buffers failed ``put_batch`` calls and retries with the *same* record
  dicts (`self._buffer = batch + self._buffer`). Because the id is stamped
  onto the dict once and reused on retry, a retried append after a
  transport failure on the read-back (append already committed, read-back
  or the caller raised) reuses the same event ids. Combined with read-side
  dedup (below), a retry can duplicate physical events on the stream but
  never duplicates what any read path returns.
- **Reads filter in Python.** KurrentDB has no server-side predicate query
  over a stream's events, so ``list_messages`` / ``list_events`` /
  ``list_messages_by_run`` / ``count_messages`` read the whole stream (or a
  bounded backwards slice for the common "latest N" case) and filter by
  category / run_id / event_types / seq bounds in Python. Fine for the POC;
  a production version would want a category/run projection instead. Reads
  always load the full stream per call -- there is no bounded/paginated
  read path for high-volume threads yet.
- **Read-side dedup by event id (keep-first/lowest stream_position).**
  KurrentDB's own same-id idempotence under ``StreamState.ANY`` is
  best-effort only (it is not a strict dedup guarantee across arbitrary
  retry timing) -- do not rely on it. ``_decode_and_filter`` independently
  drops any event whose id was already seen at a lower stream_position, so
  a retried append that physically duplicated events on the stream still
  reads back as a single logical event.
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
  don't rewrite history. Redaction markers consume a seq slot like any
  other event, so seq gaps around a redacted run are expected.
- **A malformed redaction marker raises rather than being silently
  ignored.** Un-redacting a privacy deletion by accident (by treating a
  corrupt marker as "no-op") is the worst failure mode for this feature, so
  a ``run-redacted`` event whose payload cannot be parsed or lacks
  ``run_id`` raises ``KurrentRunEventReadError`` from every read path
  instead of being logged and skipped. Ordinary corrupt non-marker events
  are still skipped-with-a-warning, unchanged.
- **Canonical dual-write (best-effort, messages only).** After a successful
  ``put``/``put_batch``, records with ``category == "message"`` are mapped
  via an exact event-type allowlist to canonical ``kurrent-agent-schema``
  events (``UserMessageReceived`` / ``AssistantTextGenerated``) and appended
  to the canonical ``AgentSession-{thread_id}`` stream (via
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
import uuid
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

# Internal-only key stamped onto record dicts to give each logical event a
# stable identity across retries. Never persisted to the JSON payload and
# never present on returned records -- see ``_append_records``.
_EVENT_ID_KEY = "_kurrent_event_id"

# kurrent-agents canonical session stream builder input; deer-flow's thread_id
# is used directly as the canonical session id.
_canonical_schema_warned = False


class KurrentRunEventReadError(RuntimeError):
    """Raised when a run-redacted marker on the stream cannot be trusted.

    Mirrors ``KurrentdbMemoryReadError``'s philosophy in ``memory_storage.py``:
    an unreadable/corrupt event must never be silently treated as "not
    there". This matters especially for ``run-redacted`` markers -- a
    marker whose payload can't be parsed or lacks ``run_id`` must not be
    skipped, because skipping it would silently un-redact a privacy
    deletion (the redacted run's events would reappear in every read path).
    Ordinary corrupt non-marker events are unaffected by this class and
    remain skip-with-a-warning, since they don't carry deletion semantics.
    """


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

    Notes:
    - Every read (``list_messages``, ``list_events``, ``list_messages_by_run``,
      ``count_messages``) loads the *entire* stream for the thread and
      filters in Python -- there is no bounded/paginated read path, so this
      is not appropriate for very high-volume threads without a future
      projection-based rework.
    - ``run-redacted`` markers (from ``delete_by_run``) consume a seq slot
      like any other event, so seq gaps around a redacted run are expected
      and not a sign of data loss.
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
        """Decode RecordedEvents into records with seq filled in, dropping redacted runs, markers, and duplicates.

        Two independent safety nets are applied before category/run
        filtering happens in the higher-level ``list_*`` methods:

        - **id-based dedup (keep-first / lowest stream_position):** a retry
          after a read-back failure can physically re-append the same
          logical record (see ``_append_records``'s docstring). KurrentDB's
          own same-id idempotence under ``StreamState.ANY`` is best-effort
          only and must not be relied on for correctness, so this method
          independently drops any event whose id was already seen at a
          lower stream_position.
        - **malformed ``run-redacted`` marker -> raise:** a marker that
          can't be parsed or lacks ``run_id`` must never be treated as a
          no-op, since that would silently un-redact a privacy deletion.
          Ordinary corrupt non-marker events are still skipped with a
          warning (unchanged behavior).
        """
        raw: list[tuple[int, dict | None, str]] = []
        redacted_run_ids: set[str] = set()
        seen_event_ids: set[Any] = set()
        for event in recorded:
            seq = event.stream_position + 1
            event_id = getattr(event, "id", None)
            if event_id is not None:
                if event_id in seen_event_ids:
                    # Duplicate physical event from a retried append -- keep
                    # only the first (lowest stream_position) occurrence.
                    continue
                seen_event_ids.add(event_id)
            if event.type == REDACTION_EVENT_TYPE:
                try:
                    marker = json.loads(event.data)
                    run_id = marker["run_id"]
                except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as e:
                    raise KurrentRunEventReadError(f"Malformed {REDACTION_EVENT_TYPE} marker at seq={seq} on stream: {e}") from e
                redacted_run_ids.add(run_id)
                raw.append((seq, None, event.type))
                continue
            try:
                record = json.loads(event.data)
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.warning("Skipping malformed event data at seq=%d (type=%s)", seq, event.type)
                raw.append((seq, None, event.type))
                continue
            record.pop(_EVENT_ID_KEY, None)
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
        """Append a single event; return the complete record with seq assigned.

        Builds a fresh record dict from the keyword args and stamps it with
        a ``_kurrent_event_id`` (uuid4 hex) -- see ``put_batch``'s docstring
        for why this id exists (retry-stability via id-correlated
        read-back). ``put()`` itself has no caller-owned dict to mutate
        across a retry (callers pass plain keyword args, not a shared dict
        object), so there is nothing to preserve here beyond this one call.
        """
        record = self._record_payload(
            thread_id=thread_id,
            run_id=run_id,
            event_type=event_type,
            category=category,
            content=content,
            metadata=metadata,
            created_at=created_at,
        )
        record[_EVENT_ID_KEY] = uuid.uuid4().hex
        results = await self._append_records(thread_id, [record])
        return results[0]

    async def put_batch(self, events: list[dict]) -> list[dict]:
        """Batch-append ``events``; return complete records with seq assigned.

        Deliberately mutates the caller's dicts: each dict in ``events`` is
        stamped with a ``_kurrent_event_id`` key (uuid4 hex) if one is not
        already present. This is the retry-stability mechanism -- when
        ``RunJournal._flush_async`` catches an exception from this method it
        pushes the *same* dict objects back onto its buffer and re-sends
        them on the next flush (`self._buffer = batch + self._buffer`).
        Because the id was already stamped onto those objects, the retried
        append reuses the same event ids instead of minting new ones, which
        is what lets read-side dedup (``_decode_and_filter``) collapse a
        retried append back down to the original logical events.
        """
        if not events:
            return []
        thread_ids = {ev["thread_id"] for ev in events}
        if len(thread_ids) > 1:
            raise ValueError(f"put_batch requires all events to share the same thread_id, got: {sorted(thread_ids)}")
        thread_id = next(iter(thread_ids))
        records = []
        for ev in events:
            event_id = ev.get(_EVENT_ID_KEY)
            if not event_id:
                event_id = uuid.uuid4().hex
                ev[_EVENT_ID_KEY] = event_id
            record = self._record_payload(
                thread_id=ev["thread_id"],
                run_id=ev["run_id"],
                event_type=ev["event_type"],
                category=ev["category"],
                content=ev.get("content", ""),
                metadata=ev.get("metadata"),
                created_at=ev.get("created_at"),
            )
            record[_EVENT_ID_KEY] = event_id
            records.append(record)
        return await self._append_records(thread_id, records)

    async def _append_records(self, thread_id: str, records: list[dict]) -> list[dict]:
        """Append ``records`` (each carrying a stable ``_kurrent_event_id``) in one call.

        Returns complete records (``_kurrent_event_id`` stripped) with seq
        derived from each record's *own* recorded event, correlated by id --
        not by positionally zipping the backwards tail read against
        ``records``. A positional zip is wrong under interleaving: if
        another writer appends to the same thread stream between this
        call's append and its read-back, the backwards slice this call reads
        can contain a mix of this call's events and the other writer's, and
        positional zip would attribute seq from the wrong physical event.
        Correlating by id is correct regardless of what else lands on the
        stream in between.
        """
        from kurrentdbclient import NewEvent, StreamState
        from kurrentdbclient.exceptions import NotFoundError

        client = await self._get_client()
        stream_name = self._stream_name(thread_id)

        record_ids: dict[uuid.UUID, dict] = {}
        new_events = []
        for r in records:
            event_id = uuid.UUID(r[_EVENT_ID_KEY])
            payload = {k: v for k, v in r.items() if k != _EVENT_ID_KEY}
            new_events.append(NewEvent(id=event_id, type=r["event_type"], data=json.dumps(payload, default=str, ensure_ascii=False).encode("utf-8")))
            record_ids[event_id] = r
        await client.append_to_stream(stream_name, events=new_events, current_version=StreamState.ANY, timeout=self._timeout)

        # append_to_stream's return value is a global commit position, not
        # the per-stream revision -- page backwards through the stream,
        # correlating by event id, to recover the revision(s) actually
        # assigned to the events we just wrote. Page size grows with n so
        # small appends still cost one round trip in the common case.
        n = len(records)
        page_size = max(n * 2, 64)
        found: dict[uuid.UUID, Any] = {}
        stream_position: int | None = None
        while len(found) < n:
            try:
                page = await client.get_stream(stream_name, backwards=True, stream_position=stream_position, limit=page_size, timeout=self._timeout)
            except NotFoundError:  # pragma: no cover - defensive, stream must exist right after append
                raise RuntimeError(f"Stream {stream_name!r} not found immediately after append") from None
            if not page:
                break
            for event in page:
                event_id = getattr(event, "id", None)
                if event_id in record_ids and event_id not in found:
                    # Paging runs newest -> oldest, so the first match seen
                    # for a given id is the event *this* append call just
                    # wrote (highest stream_position for that id). If a
                    # prior retry attempt already duplicated this id earlier
                    # in the stream, that older copy is intentionally not
                    # preferred here -- this call reports the position its
                    # own append produced. Read-side dedup
                    # (`_decode_and_filter`, keep-first-by-lowest-position)
                    # is the source of truth for what every other read path
                    # shows once both copies exist on the stream.
                    found[event_id] = event
            oldest_position = page[-1].stream_position
            if oldest_position == 0:
                break
            stream_position = oldest_position - 1

        missing = record_ids.keys() - found.keys()
        if missing:
            raise RuntimeError(f"Stream {stream_name!r}: could not find {len(missing)} of {n} just-appended event(s) by id after paging back to the start of the stream -- this should be impossible")

        results = []
        for event_id, event in sorted(found.items(), key=lambda kv: kv[1].stream_position):
            record = record_ids[event_id]
            complete = {k: v for k, v in record.items() if k != _EVENT_ID_KEY}
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

    # Exact event_type allowlists for canonical mapping -- deliberately NOT a
    # substring/heuristic match (a substring check like `"human" in
    # event_type` would also match e.g. "human_evaluation_flag", which is
    # not a chat message at all). Includes both the real values RunJournal
    # emits for category="message" (`llm.human.input` / `llm.ai.response`;
    # see runtime/journal.py's on_chat_model_start / on_llm_end) and the
    # generic `human_message` / `ai_message` event_type convention used by
    # other RunEventStore callers/tests. `llm.tool.result` (tool output) is
    # intentionally excluded -- it is not user/assistant chat text.
    _USER_MESSAGE_EVENT_TYPES = frozenset({"llm.human.input", "human_message"})
    _ASSISTANT_MESSAGE_EVENT_TYPES = frozenset({"llm.ai.response", "ai_message"})

    @classmethod
    def _map_to_canonical(cls, record: dict) -> Any | None:
        """Map a deer-flow message record to a canonical kurrent-agent-schema event, or None if unmappable."""
        from kurrent_agent_schema import AssistantTextGenerated, UserMessageReceived

        content = record.get("content", "")
        if not isinstance(content, str) or not content:
            return None
        event_type = record.get("event_type", "")
        if event_type in cls._USER_MESSAGE_EVENT_TYPES:
            return UserMessageReceived(content=content)
        if event_type in cls._ASSISTANT_MESSAGE_EVENT_TYPES:
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
