"""DeerMem's memory sidecars as one KurrentDB stream per user scope.

The sidecars are what ``FileMemoryStorage`` keeps next to the facts, per agent:
query usage (access heat for capacity scoring), metadata-only capacity-eviction
evidence, and per-thread extraction watermarks. They live in
``_naming.memory_meta_stream(user_id)``, never in the primary memory stream, so a
search hit never moves the user's manifest revision.

Every record carries ``agent``, the ``fact_id`` it is about (usage and eviction
items; watermarks have none) and ``revision``: the primary memory revision it was
written under. A deletion's criteria match records below its exclusive
``cutoff`` (the first primary revision the deletion does not affect), so records
written after a deletion survive it.

Event types (JSON data; every event has ``agent`` and ``revision``):

- ``FactsAccessed``: ``factIds`` and ``at``, the access time. The fold applies
  DeerMem's access-heat decay exactly as the file storage does, so the stream
  holds one small event per search instead of rewritten usage documents
- ``CapacityEvicted``: ``record``, the file storage's eviction-audit entry; the
  fold keeps the newest ``eviction_audit_max_entries``
- ``ExtractionWatermarkSet``: ``threadId`` and ``watermark`` (``None`` drops it);
  the fold keeps the newest ``watermark_max_keys`` threads
- ``MetadataSnapshot`` (agent ``None``): ``state``, every agent's surviving
  records with their revisions. It is the boundary: readers fold from the newest
  one, deletions write one without the removed records, and long histories are
  compacted into one

Sidecars are best-effort, as in the file storage: undecodable or unknown events
are skipped with a warning, never treated as corruption.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import uuid
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.eviction import FactEvictionDecision
from kurrentdbclient import NewEvent

from .._fence import FENCE_EVENT_TYPE

logger = logging.getLogger(__name__)

PREFIX = "deerflow.memory."
FACTS_ACCESSED = f"{PREFIX}FactsAccessed"
CAPACITY_EVICTED = f"{PREFIX}CapacityEvicted"
WATERMARK_SET = f"{PREFIX}ExtractionWatermarkSet"
METADATA_SNAPSHOT = f"{PREFIX}MetadataSnapshot"

EVENT_TYPES = frozenset({FACTS_ACCESSED, CAPACITY_EVICTED, WATERMARK_SET, METADATA_SNAPSHOT})

Criteria = Mapping[str, Any]


def iso_z(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().removesuffix("+00:00") + "Z"


def new_event(event_type: str, data: dict[str, Any]) -> NewEvent:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown sidecar event type {event_type!r}")
    return NewEvent(id=uuid.uuid4(), type=event_type, data=json.dumps(data, ensure_ascii=False).encode("utf-8"), content_type="application/json")


def eviction_record(decision: FactEvictionDecision, *, max_facts: int, now: datetime, shadow_decision: FactEvictionDecision | None) -> dict[str, Any]:
    """The file storage's eviction-audit entry for one capacity decision."""
    record: dict[str, Any] = {
        "occurredAt": iso_z(now),
        "reason": "capacity",
        "policyVersion": decision.policy,
        "maxFacts": max_facts,
        "reservedCorrectionSlots": decision.reserved_correction_slots,
        "evicted": [{"factId": item.fact_id, "category": item.category, "score": item.score, "components": copy.deepcopy(item.components)} for item in decision.evicted],
    }
    if shadow_decision is not None:
        actual_ids = {item.fact_id for item in decision.evicted}
        shadow_ids = {item.fact_id for item in shadow_decision.evicted}
        record["shadow"] = {"policyVersion": shadow_decision.policy, "wouldEvict": sorted(shadow_ids), "disagrees": actual_ids != shadow_ids}
    return record


def matches(criteria: Criteria, *, agent: str, fact_id: str | None, revision: int) -> bool:
    """Whether one record (``fact_id`` ``None`` for a watermark) is removed by a deletion's criteria.

    ``op`` is ``clear_all`` (every record of the scope), ``clear_agent`` (every
    record of ``agent``) or ``delete_facts`` (``agent``'s records about
    ``factIds``; watermarks are kept). An optional int ``cutoff`` exempts records
    written at or above that primary revision.
    """
    cutoff = criteria.get("cutoff")
    if isinstance(cutoff, int) and not isinstance(cutoff, bool) and revision >= cutoff:
        return False
    op = criteria.get("op")
    if op == "clear_all":
        return True
    if criteria.get("agent") != agent:
        return False
    if op == "clear_agent":
        return True
    if op == "delete_facts":
        return fact_id is not None and fact_id in set(criteria.get("factIds") or ())
    return False


def _filter_eviction(record: Any, drop: Callable[[str], bool]) -> dict[str, Any] | None:
    """``record`` without the evicted items ``drop`` names (``clear_fact_metadata``'s rule); ``None`` when nothing is left."""
    if not isinstance(record, dict) or not isinstance(record.get("evicted"), list):
        return None
    event = copy.deepcopy(record)
    event["evicted"] = [item for item in event["evicted"] if isinstance(item, dict) and isinstance(item.get("factId"), str) and not drop(item["factId"])]
    shadow = event.get("shadow")
    if isinstance(shadow, dict):
        would_evict = shadow.get("wouldEvict")
        if not isinstance(would_evict, list):
            event.pop("shadow", None)
        else:
            shadow["wouldEvict"] = [fact_id for fact_id in would_evict if isinstance(fact_id, str) and not drop(fact_id)]
    elif "shadow" in event:
        event.pop("shadow")
    if isinstance(event.get("shadow"), dict):
        actual_ids = {item["factId"] for item in event["evicted"]}
        event["shadow"]["disagrees"] = actual_ids != set(event["shadow"]["wouldEvict"])
    return event if event["evicted"] else None


def _is_watermark(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(part, str) for part in value)


def _revision(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _parse_time(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


class _Agent:
    """One agent's records: usage by fact id, eviction records, watermarks by thread (oldest first)."""

    def __init__(self) -> None:
        self.usage: dict[str, dict[str, Any]] = {}
        self.evictions: list[dict[str, Any]] = []
        self.watermarks: dict[str, dict[str, Any]] = {}

    def empty(self) -> bool:
        return not (self.usage or self.evictions or self.watermarks)


class SidecarState:
    """The fold of one scope's sidecar stream (from its newest snapshot).

    ``log`` keeps the decoded events since that snapshot (the snapshot first), so
    a read under open deletion intents can re-fold them with those intents' records
    dropped.
    """

    def __init__(self, config: DeerMemConfig) -> None:
        self._config = config
        self.agents: dict[str, _Agent] = {}
        self.position: int | None = None
        self.log: list[tuple[str, dict[str, Any]]] = []

    def copy(self) -> SidecarState:
        clone = SidecarState(self._config)
        clone.agents = copy.deepcopy(self.agents)
        clone.position = self.position
        clone.log = list(self.log)
        return clone

    # --- folding ---------------------------------------------------------------

    def apply(self, recorded: Any) -> None:
        """Fold one recorded event; skips fences and (with a warning) bad events."""
        if self.position is not None and recorded.stream_position <= self.position:
            return
        self.position = recorded.stream_position
        if recorded.type == FENCE_EVENT_TYPE:
            return
        if recorded.type not in EVENT_TYPES:
            logger.warning("Ignoring unknown memory sidecar event %r at position %s", recorded.type, recorded.stream_position)
            return
        try:
            data = json.loads(recorded.data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("Ignoring undecodable memory sidecar event at position %s", recorded.stream_position)
            return
        if not isinstance(data, dict):
            logger.warning("Ignoring memory sidecar event without an object payload at position %s", recorded.stream_position)
            return
        if recorded.type == METADATA_SNAPSHOT:
            self.log = []
        self.log.append((recorded.type, data))
        self.apply_data(recorded.type, data)

    def apply_data(self, event_type: str, data: dict[str, Any], intents: Iterable[Criteria] = ()) -> None:
        """Fold one event's data, dropping every record an intent's criteria match."""
        intents = list(intents)
        if event_type == METADATA_SNAPSHOT:
            self._snapshot(data.get("state"), intents)
            return
        agent = data.get("agent")
        if not isinstance(agent, str) or not agent:
            return
        revision = _revision(data.get("revision"))

        def dropped(fact_id: str | None) -> bool:
            return any(matches(criteria, agent=agent, fact_id=fact_id, revision=revision) for criteria in intents)

        if event_type == FACTS_ACCESSED:
            fact_ids = [fact_id for fact_id in data.get("factIds") or () if isinstance(fact_id, str) and fact_id and not dropped(fact_id)]
            if fact_ids:
                self._accessed(agent, fact_ids, data.get("at"), revision)
        elif event_type == CAPACITY_EVICTED:
            record = data.get("record")
            if intents:
                record = _filter_eviction(record, dropped)
            if isinstance(record, dict):
                self._evicted(agent, record, revision)
        elif event_type == WATERMARK_SET:
            thread_id = data.get("threadId")
            if isinstance(thread_id, str) and not dropped(None):
                self._watermark(agent, thread_id, data.get("watermark"), revision)

    def _bucket(self, agent: str) -> _Agent:
        return self.agents.setdefault(agent, _Agent())

    def _accessed(self, agent: str, fact_ids: list[str], at: Any, revision: int) -> None:
        """``FileMemoryStorage.record_fact_accesses``' update, at the recorded access time."""
        try:
            now = _parse_time(at)
        except (TypeError, ValueError):
            return
        usage = self._bucket(agent).usage
        for fact_id in dict.fromkeys(fact_ids):
            previous = usage.get(fact_id) or {}
            try:
                heat = float(previous.get("accessHeat", 0.0))
            except (TypeError, ValueError):
                heat = 0.0
            if not math.isfinite(heat) or heat < 0:
                heat = 0.0
            try:
                elapsed_days = max(0.0, (now - _parse_time(previous.get("lastAccessedAt"))).total_seconds() / 86400)
                heat *= 2 ** (-elapsed_days / self._config.eviction_access_half_life_days)
            except (TypeError, ValueError):
                heat = 0.0
            raw_count = previous.get("accessCount", 0)
            count = raw_count if isinstance(raw_count, int) and not isinstance(raw_count, bool) and raw_count >= 0 else 0
            usage[fact_id] = {"accessHeat": heat + 1.0, "accessCount": count + 1, "lastAccessedAt": iso_z(now), "revision": revision}

    def _evicted(self, agent: str, record: dict[str, Any], revision: int) -> None:
        limit = self._config.eviction_audit_max_entries
        if limit == 0:
            return
        evictions = self._bucket(agent).evictions
        evictions.append({**copy.deepcopy(record), "revision": revision})
        del evictions[:-limit]

    def _watermark(self, agent: str, thread_id: str, watermark: Any, revision: int) -> None:
        watermarks = self._bucket(agent).watermarks
        watermarks.pop(thread_id, None)
        if _is_watermark(watermark):
            watermarks[thread_id] = {"watermark": list(watermark), "revision": revision}
        cap = self._config.watermark_max_keys
        while cap > 0 and len(watermarks) > cap:
            watermarks.pop(next(iter(watermarks)))

    def _snapshot(self, state: Any, intents: list[Criteria]) -> None:
        self.agents = {}
        if not isinstance(state, dict):
            return
        for agent, records in state.items():
            if not isinstance(agent, str) or not agent or not isinstance(records, dict):
                continue
            bucket = _Agent()
            for fact_id, entry in (records.get("usage") or {}).items():
                if isinstance(entry, dict) and not any(matches(c, agent=agent, fact_id=fact_id, revision=_revision(entry.get("revision"))) for c in intents):
                    bucket.usage[fact_id] = copy.deepcopy(entry)
            for record in records.get("evictions") or ():
                if not isinstance(record, dict):
                    continue
                revision = _revision(record.get("revision"))
                if intents:
                    record = _filter_eviction(record, lambda fact_id, revision=revision: any(matches(c, agent=agent, fact_id=fact_id, revision=revision) for c in intents))
                if record is not None:
                    bucket.evictions.append(copy.deepcopy(record))
            for thread_id, entry in (records.get("watermarks") or {}).items():
                if isinstance(entry, dict) and _is_watermark(entry.get("watermark")) and not any(matches(c, agent=agent, fact_id=None, revision=_revision(entry.get("revision"))) for c in intents):
                    bucket.watermarks[thread_id] = copy.deepcopy(entry)
            if not bucket.empty():
                self.agents[agent] = bucket

    # --- derived states ---------------------------------------------------------

    def filtered(self, intents: Iterable[Criteria]) -> SidecarState:
        """This state as if every record the intents' criteria match had never been written."""
        intents = list(intents)
        if not intents:
            return self
        state = SidecarState(self._config)
        state.position = self.position
        for event_type, data in self.log:
            state.apply_data(event_type, data, intents)
        return state

    def without(self, criteria: Criteria) -> SidecarState:
        """The surviving records once ``criteria`` are applied (a deletion's sidecar boundary)."""
        state = SidecarState(self._config)
        state.position = self.position
        state._snapshot(self.snapshot_state(), [criteria])
        return state

    def snapshot_state(self) -> dict[str, Any]:
        return {agent: {"usage": copy.deepcopy(bucket.usage), "evictions": copy.deepcopy(bucket.evictions), "watermarks": copy.deepcopy(bucket.watermarks)} for agent, bucket in sorted(self.agents.items()) if not bucket.empty()}

    # --- reading ---------------------------------------------------------------

    def usage(self, agent: str) -> dict[str, dict[str, Any]]:
        bucket = self.agents.get(agent)
        if bucket is None:
            return {}
        return {fact_id: {key: value for key, value in entry.items() if key != "revision"} for fact_id, entry in bucket.usage.items()}

    def evictions(self, agent: str) -> list[dict[str, Any]]:
        bucket = self.agents.get(agent)
        if bucket is None:
            return []
        return [{key: value for key, value in copy.deepcopy(record).items() if key != "revision"} for record in bucket.evictions]

    def watermark(self, agent: str, thread_id: str) -> list[str] | None:
        bucket = self.agents.get(agent)
        entry = bucket.watermarks.get(thread_id) if bucket is not None else None
        return list(entry["watermark"]) if entry is not None else None
