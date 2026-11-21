"""Fold a memory stream's events into the state DeerMem reads.

``MemoryState`` is the whole user scope: global summaries plus every agent's facts,
and the stream position folded so far (``revision`` = position + 1, 0 when nothing
was folded). Fence events advance the position and change nothing else. Unknown
event types and payloads that break the invariants raise
``MemoryStorageCorruption``, as does data that is not JSON: both are persistent
bad state, not a transient read failure.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from deerflow.agents.memory.backends.deermem.deermem.core.storage import DOCUMENT_VERSION, MemoryStorageCorruption, create_empty_memory, normalize_memory_data

from .._fence import FENCE_EVENT_TYPE
from . import events


def _empty_sections() -> tuple[dict[str, Any], dict[str, Any]]:
    empty = create_empty_memory()
    return empty["user"], empty["history"]


def decode(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MemoryStorageCorruption(f"Undecodable memory event data: {exc}") from exc


class MemoryState:
    def __init__(self) -> None:
        self.user, self.history = _empty_sections()
        self.facts: dict[str, dict[str, dict[str, Any]]] = {}
        self.last_updated: str | None = None
        self.position: int | None = None

    @property
    def revision(self) -> int:
        return 0 if self.position is None else self.position + 1

    def copy(self) -> MemoryState:
        return copy.deepcopy(self)

    def agent_facts(self, agent_name: str) -> dict[str, dict[str, Any]]:
        return self.facts.get(agent_name, {})

    # --- folding ---------------------------------------------------------------

    def apply(self, recorded: Any) -> None:
        """Fold one recorded event (``type``, ``data``, ``stream_position``)."""
        if self.position is not None and recorded.stream_position <= self.position:
            return
        if recorded.type != FENCE_EVENT_TYPE:
            data = decode(recorded.data)
            self.apply_data(recorded.type, data, where=f"position {recorded.stream_position}")
        self.position = recorded.stream_position

    def apply_data(self, event_type: str, data: Any, *, where: str = "") -> None:
        if event_type not in events.EVENT_TYPES:
            raise MemoryStorageCorruption(f"Unknown memory event type {event_type!r} at {where}")
        if not isinstance(data, dict) or not isinstance(data.get("id"), str) or "agent" not in data:
            raise MemoryStorageCorruption(f"{event_type} at {where} lacks its change-set id or agent")
        agent = data["agent"]
        if agent is not None and (not isinstance(agent, str) or not agent):
            raise MemoryStorageCorruption(f"{event_type} at {where} has an invalid agent {agent!r}")
        if event_type == events.SUMMARIES_UPDATED:
            self._summaries(data, agent, where)
        elif event_type == events.FACT_UPSERTED:
            self._upsert(data, agent, where)
        elif event_type == events.FACT_DELETED:
            self._delete(data, agent, where)
        elif event_type == events.MEMORY_CLEARED:
            self._clear(agent)
        else:
            self._snapshot(data, where)
        at = data.get("at")
        if isinstance(at, str):
            self.last_updated = at

    @staticmethod
    def _require_agent(event_type: str, agent: str | None, where: str) -> str:
        if agent is None:
            raise MemoryStorageCorruption(f"{event_type} at {where} must name an agent bucket")
        return agent

    @staticmethod
    def _sections(value: Any, label: str, where: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise MemoryStorageCorruption(f"{label} at {where} must be an object")
        return copy.deepcopy(value)

    def _summaries(self, data: dict[str, Any], agent: str | None, where: str) -> None:
        if agent is not None:
            raise MemoryStorageCorruption(f"SummariesUpdated at {where} must belong to the global part")
        self.user = self._sections(data.get("user"), "summaries.user", where)
        self.history = self._sections(data.get("history"), "summaries.history", where)

    @staticmethod
    def _valid_fact(fact: Any, where: str) -> dict[str, Any]:
        if not isinstance(fact, dict) or not isinstance(fact.get("id"), str) or not fact["id"]:
            raise MemoryStorageCorruption(f"Fact at {where} lacks an id")
        revision = fact.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise MemoryStorageCorruption(f"Fact {fact['id']!r} at {where} has an invalid revision")
        return copy.deepcopy(fact)

    def _upsert(self, data: dict[str, Any], agent: str | None, where: str) -> None:
        bucket = self._require_agent(events.FACT_UPSERTED, agent, where)
        fact = self._valid_fact(data.get("fact"), where)
        self.facts.setdefault(bucket, {})[fact["id"]] = fact

    def _delete(self, data: dict[str, Any], agent: str | None, where: str) -> None:
        bucket = self._require_agent(events.FACT_DELETED, agent, where)
        fact_id = data.get("factId")
        if not isinstance(fact_id, str) or not fact_id:
            raise MemoryStorageCorruption(f"FactDeleted at {where} lacks a fact id")
        facts = self.facts.get(bucket, {})
        facts.pop(fact_id, None)
        if not facts:
            self.facts.pop(bucket, None)

    def _clear(self, agent: str | None) -> None:
        if agent is None:
            self.user, self.history = _empty_sections()
            self.facts = {}
        else:
            self.facts.pop(agent, None)

    def _fact_map(self, facts: Any, where: str) -> dict[str, dict[str, Any]]:
        if not isinstance(facts, list):
            raise MemoryStorageCorruption(f"Fact list at {where} must be a list")
        result: dict[str, dict[str, Any]] = {}
        for value in facts:
            fact = self._valid_fact(value, where)
            if fact["id"] in result:
                raise MemoryStorageCorruption(f"Duplicate fact {fact['id']!r} at {where}")
            result[fact["id"]] = fact
        return result

    def _snapshot(self, data: dict[str, Any], where: str) -> None:
        state = self._sections(data.get("state"), "MemorySnapshot.state", where)
        buckets = state.get("facts", {})
        if not isinstance(buckets, dict):
            raise MemoryStorageCorruption(f"MemorySnapshot.state.facts at {where} must map agents to fact lists")
        facts = {}
        for bucket, values in buckets.items():
            if not isinstance(bucket, str) or not bucket:
                raise MemoryStorageCorruption(f"MemorySnapshot at {where} has an invalid agent {bucket!r}")
            if mapped := self._fact_map(values, where):
                facts[bucket] = mapped
        self.user = self._sections(state.get("user", {}), "MemorySnapshot.state.user", where)
        self.history = self._sections(state.get("history", {}), "MemorySnapshot.state.history", where)
        self.facts = facts
        if isinstance(state.get("lastUpdated"), str):
            self.last_updated = state["lastUpdated"]

    # --- reading ---------------------------------------------------------------

    def snapshot_state(self) -> dict[str, Any]:
        """The whole scope as a ``MemorySnapshot`` payload's ``state`` (facts sorted by id)."""
        return {
            "user": copy.deepcopy(self.user),
            "history": copy.deepcopy(self.history),
            "facts": {agent: [copy.deepcopy(facts[fact_id]) for fact_id in sorted(facts)] for agent, facts in sorted(self.facts.items())},
            "lastUpdated": self.last_updated,
        }

    def to_document(self, agent_name: str | None) -> dict[str, Any]:
        """DeerMem's document shape: the summaries plus one agent's facts (none for ``None``)."""
        if self.position is None:
            document = create_empty_memory()
        else:
            document = {"version": DOCUMENT_VERSION, "revision": self.revision, "lastUpdated": self.last_updated or ""}
        view = normalize_memory_data({"user": self.user, "history": self.history, "facts": []})
        document["user"] = view["user"]
        document["history"] = view["history"]
        facts = self.agent_facts(agent_name) if agent_name is not None else {}
        document["facts"] = [copy.deepcopy(facts[fact_id]) for fact_id in sorted(facts)]
        return document
