"""Map DeerFlow commits to kurrent-agents canonical events (``kurrent-agent-schema`` 0.5).

Pure functions, no I/O. Payloads are schema messages only, serialized with the
schema's own ``to_json``; DeerFlow identities ride in the KurrentDB event
**metadata** (JSON, outside the payload), so the payload stays canonical:

- every event: ``$schema_version`` (the schema package's documented stamp, ruling
  R15) and ``schema_version`` (July's key), both ``SCHEMA_VERSION``, and ``deerflow.origin``, the
  primary position the event came from: the memory revision of the commit that
  produced it, or the run event's ``seq``. A deletion's exclusive ``cutoff`` is
  compared with it
- memory: ``deerflow.fact_id``, ``deerflow.fact_revision`` (with the fact id, the
  dedupe identity of a fact version) and ``deerflow.agent``
- sessions: ``deerflow.run_id``, ``deerflow.seq``, ``deerflow.event_type`` and
  ``deerflow.metadata``, the run event's metadata redacted with the rules the run
  evidence reader applies (``redact_metadata_secrets``)

Event ids are deterministic (uuid5 of the DeerFlow identity plus the origin), so a
re-emitted commit carries the same ids and consumers can dedupe; a fact deleted
and recreated with the same id and revision gets a new id, because its origin differs.

Memory: ``FactRetained`` for every created or updated fact (0.5 has no revise or
forget event). The global scope (``user_id=None``) has no canonical stream: the
schema's memory stream is per user, so nothing is emitted for it.

Sessions (``agent_session_stream(thread_id)``, one canonical session per thread,
ruling R16):

- ``SessionStarted`` (``session_started``) is written only when an emission creates
  the session stream (first emission, or the first after a thread deletion
  soft-deleted it), with ``user_id`` = the record owner. Its metadata has
  ``deerflow.seq``/``deerflow.origin`` of the first record it precedes and no
  ``deerflow.run_id``, so a run deletion never removes it and a thread deletion does
- ``run.start`` / ``run.end`` / ``run.error`` map to nothing (no per-run session events)
- user message (``llm.human.input``, ``human_message``) -> ``UserMessageReceived``
- assistant message (``llm.ai.response``, ``ai_message``) -> ``AssistantToolCallsGenerated``
  when it calls tools, else ``AssistantTextGenerated`` when it has text; middleware
  callers (not user-visible) are skipped
- tool result (``llm.tool.result``, ``tool_message``) -> ``ToolResultReceived``
- everything else (traces, errors, context) is not mapped
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, NamedTuple

from deerflow.runtime.secret_context import redact_metadata_secrets
from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp
from kurrent_agent_schema import (
    EVENT_TYPE_NAMES,
    SCHEMA_VERSION,
    AssistantTextGenerated,
    AssistantToolCallsGenerated,
    FactRetained,
    SessionStarted,
    ToolCallInfo,
    ToolResultReceived,
    UserMessageReceived,
    agent_memory_stream,
    agent_session_stream,
    to_json,
)
from kurrentdbclient import NewEvent

APP_NAME = "deerflow"

SCHEMA_VERSION_KEY = "schema_version"
SCHEMA_VERSION_STAMP = "$schema_version"
ORIGIN = "deerflow.origin"
FACT_ID = "deerflow.fact_id"
FACT_REVISION = "deerflow.fact_revision"
AGENT = "deerflow.agent"
RUN_ID = "deerflow.run_id"
SEQ = "deerflow.seq"
EVENT_TYPE = "deerflow.event_type"
RECORD_METADATA = "deerflow.metadata"
#: Set by canonical cleanup on the copies it re-appends (Task 13).
INTENT_ID = "deerflow.intent_id"

_NAMESPACE = uuid.UUID("6f1d2c1e-6b0a-5c55-9d1e-6b8a3f1e2d40")

_USER_MESSAGE_TYPES = frozenset({"llm.human.input", "human_message"})
_ASSISTANT_MESSAGE_TYPES = frozenset({"llm.ai.response", "ai_message"})
_TOOL_RESULT_TYPES = frozenset({"llm.tool.result", "tool_message"})


class CanonicalEvent(NamedTuple):
    message: Message
    metadata: dict[str, Any]
    event_id: uuid.UUID

    @property
    def type(self) -> str:
        return EVENT_TYPE_NAMES[type(self.message)]

    def new_event(self) -> NewEvent:
        return NewEvent(
            id=self.event_id,
            type=self.type,
            data=to_json(self.message).encode("utf-8"),
            metadata=json.dumps(self.metadata, ensure_ascii=False, default=str).encode("utf-8"),
            content_type="application/json",
        )


# --- streams -------------------------------------------------------------------


def memory_stream(user_id: str | None) -> str | None:
    """The canonical memory stream of a user scope; ``None`` for the global scope (the schema has none)."""
    return None if user_id is None else agent_memory_stream(APP_NAME, user_id)


def session_stream(thread_id: str) -> str:
    return agent_session_stream(thread_id)


# --- deletion criteria -----------------------------------------------------------


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def matches(op: str, criteria: Mapping[str, Any], metadata: Mapping[str, Any]) -> bool:
    """Whether a deletion (``op`` + its intent ``criteria``) covers a canonical event, by its metadata.

    Only events whose ``deerflow.origin`` is below the intent's exclusive ``cutoff``
    are covered, so anything committed after the deletion always survives.
    """
    origin, cutoff = _int(metadata.get(ORIGIN)), _int(criteria.get("cutoff"))
    if origin is None or cutoff is None or origin >= cutoff:
        return False
    if op == "delete_facts":
        return metadata.get(AGENT) == criteria.get("agent") and metadata.get(FACT_ID) in (criteria.get("factIds") or ())
    if op == "clear_agent":
        return FACT_ID in metadata and metadata.get(AGENT) == criteria.get("agent")
    if op == "clear_all":
        return FACT_ID in metadata
    if op == "delete_run":
        return metadata.get(RUN_ID) == criteria.get("run_id")
    if op == "delete_thread":
        return SEQ in metadata
    return False


def matches_intent(intent: Any, metadata: Mapping[str, Any]) -> bool:
    return matches(intent.op, intent.criteria, metadata)


# --- helpers ---------------------------------------------------------------------


def _timestamp(raw: Any) -> Timestamp | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    stamp = Timestamp()
    stamp.FromDatetime(moment.astimezone(UTC))
    return stamp


def _now() -> Timestamp:
    stamp = Timestamp()
    stamp.FromDatetime(datetime.now(UTC))
    return stamp


def _event_id(*parts: Any) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, "\x1f".join("" if part is None else str(part) for part in parts))


def _text(content: Any) -> str:
    """The text of a message's content: a string, or the text blocks of a content list."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping) and block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return ""


def _versions() -> dict[str, int]:
    return {SCHEMA_VERSION_STAMP: SCHEMA_VERSION, SCHEMA_VERSION_KEY: SCHEMA_VERSION}


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


# --- memory ----------------------------------------------------------------------


def _upserted(change_set_result: Any) -> list[Mapping[str, Any]]:
    if isinstance(change_set_result, Mapping):
        facts = change_set_result.get("upsertedFacts") or ()
    elif hasattr(change_set_result, "upserted"):
        facts = change_set_result.upserted
    else:
        facts = change_set_result or ()
    return [fact for fact in facts if isinstance(fact, Mapping)]


def memory_events(change_set_result: Any, *, user_id: str | None, agent: str | None, origin: int) -> list[CanonicalEvent]:
    """``FactRetained`` for every fact a commit created or updated.

    ``change_set_result`` is an ``apply_changes`` result (``upsertedFacts``), a
    ``changes.Plan`` (``upserted``) or a list of facts; ``origin`` is the memory
    revision the commit produced. Empty for the global scope.
    """
    if user_id is None or agent is None:
        return []
    events = []
    for fact in _upserted(change_set_result):
        content = fact.get("content")
        if not isinstance(content, str) or not content:
            continue
        fact_id, revision = str(fact.get("id")), fact.get("revision")
        retained_at = _timestamp(fact.get("updatedAt")) or _timestamp(fact.get("createdAt")) or _now()
        metadata = {**_versions(), ORIGIN: origin, FACT_ID: fact_id, FACT_REVISION: revision, AGENT: agent}
        events.append(CanonicalEvent(FactRetained(fact=content, retained_at=retained_at), metadata, _event_id("memory", user_id, agent, fact_id, revision, origin)))
    return events


# --- sessions --------------------------------------------------------------------


def _message_fields(record: Mapping[str, Any], content: Mapping[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if isinstance(content.get("id"), str):
        fields["message_id"] = content["id"]
    if isinstance(content.get("name"), str):
        fields["author_name"] = content["name"]
    stamp = _timestamp(record.get("created_at"))
    if stamp is not None:
        fields["created_at"] = stamp
        fields["timestamp"] = stamp
    return fields


def _session_message(record: Mapping[str, Any]) -> Message | None:
    event_type = record.get("event_type")
    metadata = record.get("metadata") if isinstance(record.get("metadata"), Mapping) else {}
    raw = record.get("content")
    content: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {"content": raw}
    if record.get("category") != "message":
        return None
    text = _text(content.get("content"))
    if event_type in _USER_MESSAGE_TYPES:
        return UserMessageReceived(content=text, **_message_fields(record, content)) if text else None
    if event_type in _ASSISTANT_MESSAGE_TYPES:
        if str(metadata.get("caller", "")).startswith("middleware:"):
            return None
        tool_calls = [call for call in content.get("tool_calls") or () if isinstance(call, Mapping)]
        if tool_calls:
            infos = []
            for call in tool_calls:
                info = ToolCallInfo(call_id=str(call.get("id") or ""), tool_name=str(call.get("name") or ""))
                if isinstance(call.get("args"), Mapping):
                    info.arguments.update(_json_safe(call["args"]))
                infos.append(info)
            return AssistantToolCallsGenerated(tool_calls=infos, content=text, **_message_fields(record, content))
        return AssistantTextGenerated(content=text, **_message_fields(record, content)) if text else None
    if event_type in _TOOL_RESULT_TYPES:
        return ToolResultReceived(call_id=str(content.get("tool_call_id") or ""), tool_name=str(content.get("name") or ""), result=text, **_message_fields(record, content))
    return None


def session_events(records: Iterable[Mapping[str, Any]]) -> list[CanonicalEvent]:
    """The canonical session events of committed run-event records (records that do not map are skipped)."""
    events = []
    for record in records:
        message = _session_message(record)
        if message is None:
            continue
        seq, run_id = record.get("seq"), record.get("run_id")
        redacted = redact_metadata_secrets(record.get("metadata"))
        metadata = {
            **_versions(),
            ORIGIN: seq,
            RUN_ID: run_id,
            SEQ: seq,
            EVENT_TYPE: record.get("event_type"),
            RECORD_METADATA: _json_safe(redacted) if isinstance(redacted, Mapping) else {},
        }
        events.append(CanonicalEvent(message, metadata, _event_id("session", record.get("thread_id"), run_id, seq)))
    return events


def session_started(first: Mapping[str, Any], *, user_id: str | None) -> CanonicalEvent:
    """The ``SessionStarted`` that opens a session stream, ahead of the committed record ``first``."""
    fields: dict[str, Any] = {"app_name": APP_NAME}
    if user_id:
        fields["user_id"] = user_id
    stamp = _timestamp(first.get("created_at"))
    if stamp is not None:
        fields["timestamp"] = stamp
    seq = first.get("seq")
    metadata = {**_versions(), ORIGIN: seq, SEQ: seq, EVENT_TYPE: "session.start"}
    return CanonicalEvent(SessionStarted(**fields), metadata, _event_id("session-start", first.get("thread_id"), seq))
