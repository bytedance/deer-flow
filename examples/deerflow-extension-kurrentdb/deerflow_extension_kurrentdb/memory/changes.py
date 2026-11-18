"""Plan DeerMem writes against a folded ``MemoryState`` as memory-stream deltas.

Every write (``save``, ``apply_changes``, ``clear_all``) becomes a ``Plan``: the
delta events of one change set, the facts it upserts and the fact ids it removes.
Planning only reads the state; it validates input and per-fact revisions the way
``FileMemoryStorage._commit_changes_locked`` does and raises before anything is
written, so a change set is never partly applied.

A plan that removes facts or clears a scope carries ``criteria`` (what is removed,
in the deletion-intent vocabulary of the design: ``delete_facts`` or ``clear_all``).
The storage writes such a plan as a ``MemorySnapshot`` boundary, never as plain
deltas, so deleted content does not stay in the readable stream.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from typing import Any

from deerflow.agents.memory.backends.deermem.deermem.core.storage import MemoryFactRevisionConflict, _normalize_fact, create_empty_memory, normalize_memory_data

from . import events
from .fold import MemoryState

Change = tuple[str, dict[str, Any]]


@dataclass
class Plan:
    changes: list[Change]
    upserted: list[dict[str, Any]]
    deleted: list[str]
    criteria: dict[str, Any] | None = None


@dataclass
class ChangeSet:
    """A validated ``apply_changes`` change set; fact ids are fixed once, so retries reuse them."""

    upserts: list[dict[str, Any]]
    upsert_revisions: dict[str, int | None]
    deletes: list[str]
    delete_revisions: dict[str, Any] | None
    summaries: Any

    @property
    def has_fact_changes(self) -> bool:
        return bool(self.upserts or self.deletes)

    @property
    def rebase_safe(self) -> bool:
        """As in the file storage: only fact changes whose every target revision is pinned rebase."""
        deletes_pinned = not self.deletes or (isinstance(self.delete_revisions, dict) and all(fact_id in self.delete_revisions for fact_id in self.deletes))
        return self.has_fact_changes and self.summaries is None and deletes_pinned


def parse_change_set(change_set: Any, *, agent_name: str | None) -> ChangeSet:
    if not isinstance(change_set, dict):
        raise ValueError("change_set must be an object")
    upserts = copy.deepcopy(change_set.get("upserts", []))
    deletes = change_set.get("deletes", [])
    delete_revisions = change_set.get("deleteRevisions")
    upsert_revisions = change_set.get("upsertRevisions")
    if not isinstance(upserts, list) or not isinstance(deletes, list):
        raise ValueError("change_set.upserts and change_set.deletes must be lists")
    if delete_revisions is not None and not isinstance(delete_revisions, dict):
        raise ValueError("change_set.deleteRevisions must be an object")
    if upsert_revisions is not None and not isinstance(upsert_revisions, dict):
        raise ValueError("change_set.upsertRevisions must be an object")
    if (upserts or deletes) and agent_name is None:
        raise ValueError("agent_name is required for fact repository changes")
    expected_revisions: dict[str, int | None] = {}
    for incoming in upserts:
        if not isinstance(incoming, dict):
            raise ValueError("change_set.upserts must contain fact objects")
        incoming["id"] = str(incoming.get("id") or f"fact_{uuid.uuid4().hex}")
        if isinstance(upsert_revisions, dict) and incoming["id"] in upsert_revisions:
            expected = upsert_revisions[incoming["id"]]
        else:
            expected = incoming.get("revision") if "revision" in incoming else None
        if expected is not None and (isinstance(expected, bool) or not isinstance(expected, int) or expected < 1):
            raise ValueError("change_set.upsertRevisions values must be null or integers >= 1")
        expected_revisions[incoming["id"]] = expected
    return ChangeSet(
        upserts=upserts,
        upsert_revisions=expected_revisions,
        deletes=[str(fact_id) for fact_id in deletes],
        delete_revisions=copy.deepcopy(delete_revisions),
        summaries=copy.deepcopy(change_set.get("summaries")),
    )


def _merged_summaries(state: MemoryState, summaries: Any) -> list[Change]:
    """A ``SummariesUpdated`` change when merging ``summaries`` per section changes them."""
    if summaries is None:
        return []
    if not isinstance(summaries, dict):
        raise ValueError("summaries must be an object")
    user, history = copy.deepcopy(state.user), copy.deepcopy(state.history)
    for name, section in (("user", user), ("history", history)):
        if name in summaries:
            if not isinstance(summaries[name], dict):
                raise ValueError(f"summaries.{name} must be an object")
            section.update(copy.deepcopy(summaries[name]))
    if user == state.user and history == state.history:
        return []
    return [(events.SUMMARIES_UPDATED, {"agent": None, "user": user, "history": history})]


def _deletion(agent_name: str, removed: list[str]) -> dict[str, Any] | None:
    return {"op": "delete_facts", "agent": agent_name, "factIds": list(removed)} if removed else None


def plan_change_set(state: MemoryState, change_set: ChangeSet, *, agent_name: str | None, user_id: str | None) -> Plan:
    """The plan of one ``apply_changes`` call; raises ``MemoryFactRevisionConflict`` before any write."""
    existing_facts = state.agent_facts(agent_name) if agent_name is not None else {}
    scope = {"userId": user_id, "agentName": agent_name}
    prepared: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for incoming in change_set.upserts:
        fact_id = incoming["id"]
        if fact_id in seen:
            raise ValueError(f"Duplicate fact id {fact_id!r} in upserts")
        seen.add(fact_id)
        existing = existing_facts.get(fact_id)
        expected = change_set.upsert_revisions.get(fact_id)
        if expected is None and existing is not None:
            raise MemoryFactRevisionConflict(f"Fact {fact_id!r} must not already exist")
        if expected is not None and (None if existing is None else existing.get("revision")) != expected:
            raise MemoryFactRevisionConflict(f"Expected fact {fact_id!r} revision {expected}, found {None if existing is None else existing.get('revision')}")
        normalized = _normalize_fact(copy.deepcopy(incoming), scope=scope, existing=existing)
        if existing != normalized:
            prepared[fact_id] = normalized

    if len(change_set.deletes) != len(set(change_set.deletes)):
        raise ValueError("Duplicate fact ids are not allowed in deletes")
    removed: list[str] = []
    for fact_id in change_set.deletes:
        if fact_id in prepared:
            raise ValueError(f"Fact {fact_id!r} cannot be upserted and deleted together")
        existing = existing_facts.get(fact_id)
        if existing is None:
            continue
        revisions = change_set.delete_revisions
        if revisions and fact_id in revisions and revisions[fact_id] != existing.get("revision"):
            raise MemoryFactRevisionConflict(f"Expected fact {fact_id!r} revision {revisions[fact_id]}, found {existing.get('revision')}")
        removed.append(fact_id)

    changes: list[Change] = [(events.FACT_UPSERTED, {"agent": agent_name, "fact": fact}) for fact in prepared.values()]
    changes += [(events.FACT_DELETED, {"agent": agent_name, "factId": fact_id, "revision": existing_facts[fact_id].get("revision")}) for fact_id in removed]
    changes += _merged_summaries(state, change_set.summaries)
    return Plan(changes, list(prepared.values()), removed, _deletion(agent_name, removed) if agent_name is not None else None)


def plan_save(state: MemoryState, memory_data: dict[str, Any], facts_raw: list[dict[str, Any]], *, agent_name: str | None, user_id: str | None) -> Plan:
    """A full-replacement ``save``: summaries on the global scope, else the agent's whole fact list."""
    if agent_name is None:
        sections = {name: memory_data.get(name, {}) for name in ("user", "history")}
        return Plan(_merged_summaries(state, sections), [], [])
    ids = [str(fact.get("id") or "") for fact in facts_raw]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate fact ids are not allowed")
    scope = {"userId": user_id, "agentName": agent_name}
    existing = state.agent_facts(agent_name)
    changes: list[Change] = []
    upserted: list[dict[str, Any]] = []
    for candidate in facts_raw:
        candidate["id"] = str(candidate.get("id") or f"fact_{uuid.uuid4().hex}")
        normalized = _normalize_fact(candidate, scope=scope, existing=existing.get(candidate["id"]))
        if existing.get(normalized["id"]) != normalized:
            changes.append((events.FACT_UPSERTED, {"agent": agent_name, "fact": normalized}))
            upserted.append(normalized)
    removed = sorted(set(existing) - set(ids))
    changes += [(events.FACT_DELETED, {"agent": agent_name, "factId": fact_id, "revision": existing[fact_id].get("revision")}) for fact_id in removed]
    return Plan(changes, upserted, removed, _deletion(agent_name, removed))


def plan_clear_all(state: MemoryState) -> Plan:
    """Clear the scope's summaries and every agent's facts; a no-op when it is already empty."""
    empty = create_empty_memory()
    view = normalize_memory_data({"user": state.user, "history": state.history, "facts": []})
    if not state.facts and view["user"] == empty["user"] and view["history"] == empty["history"]:
        return Plan([], [], [])
    removed = sorted(fact_id for facts in state.facts.values() for fact_id in facts)
    return Plan([(events.MEMORY_CLEARED, {"agent": None})], [], removed, {"op": "clear_all", "agents": sorted(state.facts)})
