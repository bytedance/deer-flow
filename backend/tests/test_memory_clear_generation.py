"""Durable clear-generation fence: extraction must not restore facts after clear."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.storage import (
    FileMemoryStorage,
    MemoryClearGenerationConflict,
    MemoryManifestRevisionConflict,
    create_empty_memory,
    is_stale_clear_generation,
    scope_clear_generation,
)
from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater

_FACT_ID = "fact_01HZZZZZZZZZZZZZZZZZZZZZZZ"
_DURABLE_USER_FACT = {
    "scope": "user",
    "durability": "durable",
    "authority": "descriptive",
}


def _memory_with_fact(content: str = "User likes Python") -> dict:
    memory = create_empty_memory()
    memory["facts"] = [
        {
            "id": _FACT_ID,
            "content": content,
            "category": "preference",
            "topics": ["python"],
            "confidence": 0.95,
            "createdAt": "2026-07-17T00:00:00Z",
            "source": {"type": "manual", "threadId": "thread-1"},
            "revision": 1,
        }
    ]
    return memory


def _extraction_json(content: str) -> str:
    return json.dumps(
        {
            "user": {},
            "history": {},
            "newFacts": [
                {
                    "content": content,
                    "category": "preference",
                    "confidence": 0.9,
                    **_DURABLE_USER_FACT,
                }
            ],
            "factsToRemove": [],
        }
    )


def _conversation() -> list[MagicMock]:
    human = MagicMock()
    human.type = "human"
    human.content = "Remember that I like Python."
    ai = MagicMock()
    ai.type = "ai"
    ai.content = "Got it."
    ai.tool_calls = []
    return [human, ai]


def _queue_conversation(*, human: str = "Remember that I like Python.", ai: str = "I'll keep that preference in mind.") -> list:
    return [HumanMessage(content=human), AIMessage(content=ai)]


def _updater(storage: FileMemoryStorage, invoke) -> MemoryUpdater:
    model = MagicMock()
    model.invoke = MagicMock(side_effect=invoke)
    return MemoryUpdater(storage._config, storage, model)


def _manager(tmp_path: Path, host_llm: MagicMock | None = None) -> DeerMem:
    return DeerMem(
        backend_config={
            "storage_path": str(tmp_path),
            "fact_confidence_threshold": 0.7,
            "max_facts": 100,
            "debounce_seconds": 30,
            "token_counting": "char",
            "host_llm": host_llm if host_llm is not None else MagicMock(),
        }
    )


def _stop_debounce(manager: DeerMem) -> None:
    timer = manager._queue._timer
    if timer is not None:
        timer.cancel()
        manager._queue._timer = None


def test_stale_clear_generation_is_raised_instead_of_revision_conflict(tmp_path: Path) -> None:
    storage = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)))
    assert storage.save(_memory_with_fact(), "agent-a", user_id="alice")
    loaded = storage.load("agent-a", user_id="alice")
    old_revision = int(loaded["revision"] or 0)
    old_generation = scope_clear_generation(loaded, "agent-a")

    storage.apply_changes(
        {"deletes": [_FACT_ID], "deleteRevisions": {_FACT_ID: 1}},
        agent_name="agent-a",
        user_id="alice",
        expected_manifest_revision=old_revision,
        bump_clear_generation="agent",
    )

    restored = copy.deepcopy(_memory_with_fact("restored after clear")["facts"][0])
    restored["id"] = "fact_restored"
    with pytest.raises(MemoryClearGenerationConflict):
        storage.apply_changes(
            {"upserts": [restored], "upsertRevisions": {"fact_restored": None}},
            agent_name="agent-a",
            user_id="alice",
            expected_manifest_revision=old_revision,
            expected_clear_generation=old_generation,
        )

    assert storage.load("agent-a", user_id="alice")["facts"] == []


def test_empty_scoped_clear_still_bumps_agent_generation(tmp_path: Path) -> None:
    storage = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)))
    storage.apply_changes(
        {"deletes": [], "deleteRevisions": {}},
        agent_name="agent-a",
        user_id="alice",
        expected_manifest_revision=0,
        bump_clear_generation="agent",
    )
    path = storage._get_memory_file_path("agent-a", user_id="alice")
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["agentClearGenerations"]["agent-a"] == 1
    assert "clearGeneration" not in persisted


def test_scoped_clear_does_not_fence_another_agent(tmp_path: Path) -> None:
    storage = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)))
    assert storage.save(_memory_with_fact("A"), "agent-a", user_id="alice")
    other = copy.deepcopy(_memory_with_fact("B")["facts"][0])
    other["id"] = "fact_agent_b"
    assert storage.save(_memory_with_fact("B") | {"facts": [other]}, "agent-b", user_id="alice")

    loaded_a = storage.load("agent-a", user_id="alice")
    storage.apply_changes(
        {"deletes": [_FACT_ID], "deleteRevisions": {_FACT_ID: 1}},
        agent_name="agent-a",
        user_id="alice",
        expected_manifest_revision=int(loaded_a["revision"] or 0),
        bump_clear_generation="agent",
    )

    loaded_b = storage.load("agent-b", user_id="alice")
    extra = copy.deepcopy(_memory_with_fact("B extra")["facts"][0])
    extra["id"] = "fact_b_extra"
    storage.apply_changes(
        {"upserts": [extra], "upsertRevisions": {"fact_b_extra": None}},
        agent_name="agent-b",
        user_id="alice",
        expected_manifest_revision=int(loaded_b["revision"] or 0),
        expected_clear_generation=scope_clear_generation(loaded_b, "agent-b"),
    )
    assert {fact["id"] for fact in storage.load("agent-b", user_id="alice")["facts"]} == {"fact_agent_b", "fact_b_extra"}
    assert storage.load("agent-a", user_id="alice")["facts"] == []


def test_user_wide_clear_fences_every_agent(tmp_path: Path) -> None:
    storage = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)))
    assert storage.save(_memory_with_fact(), "agent-a", user_id="alice")
    loaded = storage.load("agent-a", user_id="alice")
    old_generation = scope_clear_generation(loaded, "agent-a")

    storage.clear_all(user_id="alice")

    restored = copy.deepcopy(_memory_with_fact("restored")["facts"][0])
    restored["id"] = "fact_restored"
    with pytest.raises(MemoryClearGenerationConflict):
        storage.apply_changes(
            {"upserts": [restored], "upsertRevisions": {"fact_restored": None}},
            agent_name="agent-a",
            user_id="alice",
            expected_manifest_revision=int(loaded["revision"] or 0),
            expected_clear_generation=old_generation,
        )
    path = storage._get_memory_file_path(user_id="alice")
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["clearGeneration"] == 1
    assert storage.load("agent-a", user_id="alice")["facts"] == []


def test_revision_conflict_without_clear_is_still_a_manifest_conflict(tmp_path: Path) -> None:
    storage = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)))
    assert storage.save(_memory_with_fact(), "agent-a", user_id="alice")
    loaded = storage.load("agent-a", user_id="alice")
    extra = copy.deepcopy(_memory_with_fact("concurrent")["facts"][0])
    extra["id"] = "fact_concurrent"
    storage.apply_changes(
        {"upserts": [extra], "upsertRevisions": {"fact_concurrent": None}},
        agent_name="agent-a",
        user_id="alice",
        expected_manifest_revision=int(loaded["revision"] or 0),
        expected_clear_generation=scope_clear_generation(loaded, "agent-a"),
    )
    with pytest.raises(MemoryManifestRevisionConflict):
        storage.apply_changes(
            {"upserts": [], "deletes": []},
            agent_name="agent-a",
            user_id="alice",
            expected_manifest_revision=int(loaded["revision"] or 0),
            expected_clear_generation=scope_clear_generation(loaded, "agent-a"),
        )


def test_in_flight_extraction_does_not_restore_facts_after_cross_worker_clear(tmp_path: Path) -> None:
    config = DeerMemConfig(storage_path=str(tmp_path), fact_confidence_threshold=0.7, max_facts=100)
    storage = FileMemoryStorage(config)
    assert storage.save(_memory_with_fact("User likes Python"), "researcher", user_id="alice")
    other = DeerMem(backend_config={"storage_path": str(tmp_path)})

    def invoke_and_clear(prompt, config=None):
        other.clear_memory(agent_name="researcher", user_id="alice")
        response = MagicMock()
        response.content = _extraction_json("User likes Python")
        return response

    updater = _updater(storage, invoke_and_clear)
    result = updater.update_memory(_conversation(), thread_id="thread-1", agent_name="researcher", user_id="alice")

    fresh = FileMemoryStorage(config).load("researcher", user_id="alice")
    assert result is False
    assert fresh["facts"] == []


def test_scoped_clear_does_not_abort_other_agent_extraction(tmp_path: Path) -> None:
    config = DeerMemConfig(storage_path=str(tmp_path), fact_confidence_threshold=0.7, max_facts=100)
    storage = FileMemoryStorage(config)
    assert storage.save(_memory_with_fact("A likes Python"), "researcher", user_id="alice")
    planner_fact = copy.deepcopy(_memory_with_fact("B likes Rust")["facts"][0])
    planner_fact["id"] = "fact_planner"
    assert storage.save(_memory_with_fact() | {"facts": [planner_fact]}, "planner", user_id="alice")
    other = DeerMem(backend_config={"storage_path": str(tmp_path)})

    def invoke_and_clear_researcher(prompt, config=None):
        other.clear_memory(agent_name="researcher", user_id="alice")
        response = MagicMock()
        response.content = _extraction_json("Planner prefers Rust")
        return response

    updater = _updater(storage, invoke_and_clear_researcher)
    result = updater.update_memory(_conversation(), thread_id="thread-2", agent_name="planner", user_id="alice")

    planner = FileMemoryStorage(config).load("planner", user_id="alice")
    researcher = FileMemoryStorage(config).load("researcher", user_id="alice")
    assert result is True
    assert researcher["facts"] == []
    assert "Planner prefers Rust" in {fact["content"] for fact in planner["facts"]}


def test_concurrent_update_still_rebases_extracted_facts(tmp_path: Path) -> None:
    config = DeerMemConfig(storage_path=str(tmp_path), fact_confidence_threshold=0.7, max_facts=100)
    storage = FileMemoryStorage(config)
    assert storage.save(_memory_with_fact("User likes Python"), "researcher", user_id="alice")
    competing = FileMemoryStorage(config)
    loaded = storage.load("researcher", user_id="alice")

    def invoke_and_upsert(prompt, config=None):
        extra = copy.deepcopy(_memory_with_fact("User also likes Rust")["facts"][0])
        extra["id"] = "fact_concurrent"
        competing.apply_changes(
            {"upserts": [extra], "upsertRevisions": {"fact_concurrent": None}},
            agent_name="researcher",
            user_id="alice",
            expected_manifest_revision=int(loaded["revision"] or 0),
        )
        response = MagicMock()
        response.content = _extraction_json("User prefers concise updates")
        return response

    updater = _updater(storage, invoke_and_upsert)
    result = updater.update_memory(_conversation(), thread_id="thread-3", agent_name="researcher", user_id="alice")

    facts = {fact["content"] for fact in FileMemoryStorage(config).load("researcher", user_id="alice")["facts"]}
    assert result is True
    assert "User also likes Rust" in facts
    assert "User prefers concise updates" in facts


def test_is_stale_clear_generation_is_componentwise() -> None:
    assert is_stale_clear_generation((0, 0), (1, 0)) is True
    assert is_stale_clear_generation((0, 0), (0, 1)) is True
    assert is_stale_clear_generation((1, 1), (1, 1)) is False
    assert is_stale_clear_generation((2, 1), (1, 1)) is False


def test_peek_clear_generation_reads_json_without_loading_facts(tmp_path: Path) -> None:
    storage = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)))
    assert storage.save(_memory_with_fact(), "agent-a", user_id="alice")
    with patch.object(storage, "_load_agent_facts", side_effect=AssertionError("facts loaded")):
        assert storage.peek_clear_generation("agent-a", user_id="alice") == (0, 0)

    loaded = storage.load("agent-a", user_id="alice")
    storage.apply_changes(
        {"deletes": [_FACT_ID], "deleteRevisions": {_FACT_ID: 1}},
        agent_name="agent-a",
        user_id="alice",
        expected_manifest_revision=int(loaded["revision"] or 0),
        bump_clear_generation="agent",
    )
    with patch.object(storage, "_load_agent_facts", side_effect=AssertionError("facts loaded")):
        assert storage.peek_clear_generation("agent-a", user_id="alice") == (0, 1)


def test_queued_before_clear_extraction_does_not_restore_facts_after_cross_manager_clear(tmp_path: Path) -> None:
    host_llm = MagicMock()
    host_llm.invoke = MagicMock(side_effect=AssertionError("queued extraction must not call the LLM after a newer clear"))
    manager_a = _manager(tmp_path, host_llm)
    manager_a.create_fact("User likes Python", category="preference", confidence=0.9, agent_name="researcher", user_id="alice")

    manager_a.add(thread_id="thread-1", messages=_queue_conversation(), agent_name="researcher", user_id="alice")
    assert manager_a._queue.pending_count == 1
    assert manager_a._queue._items[0].clear_generation == (0, 0)
    _stop_debounce(manager_a)

    manager_b = _manager(tmp_path)
    manager_b.clear_memory(agent_name="researcher", user_id="alice")
    assert manager_b.get_memory(agent_name="researcher", user_id="alice")["facts"] == []

    manager_a._queue.flush()

    host_llm.invoke.assert_not_called()
    fresh = manager_b.get_memory(agent_name="researcher", user_id="alice")
    assert fresh["facts"] == []


def test_queued_coalesce_after_clear_keeps_pre_clear_fence(tmp_path: Path) -> None:
    host_llm = MagicMock()
    host_llm.invoke = MagicMock(side_effect=AssertionError("coalesced extraction must not call the LLM after a newer clear"))
    manager_a = _manager(tmp_path, host_llm)
    manager_a.create_fact("User likes Python", category="preference", confidence=0.9, agent_name="researcher", user_id="alice")

    manager_a.add(thread_id="thread-1", messages=_queue_conversation(), agent_name="researcher", user_id="alice")
    assert manager_a._queue._items[0].clear_generation == (0, 0)
    _stop_debounce(manager_a)

    manager_b = _manager(tmp_path)
    manager_b.clear_memory(agent_name="researcher", user_id="alice")

    manager_a.add(
        thread_id="thread-1",
        messages=_queue_conversation(human="Also remember that I prefer typed Python.", ai="Noted, I will keep that preference."),
        agent_name="researcher",
        user_id="alice",
    )
    assert manager_a._queue.pending_count == 1
    assert manager_a._queue._items[0].clear_generation == (0, 0)
    _stop_debounce(manager_a)

    manager_a._queue.flush()

    host_llm.invoke.assert_not_called()
    assert manager_b.get_memory(agent_name="researcher", user_id="alice")["facts"] == []
