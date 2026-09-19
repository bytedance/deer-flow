"""Durable clear-generation fence: extraction must not restore facts after clear."""

from __future__ import annotations

import copy
import json
import sys
import threading
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.storage import (
    CLEAR_GENERATION_CAPABILITY,
    FileMemoryStorage,
    MemoryClearGenerationConflict,
    MemoryManifestRevisionConflict,
    MemoryStorage,
    create_empty_memory,
    create_storage,
    declares_clear_generation_fence,
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


def test_clear_all_raises_generation_before_per_agent_wipes(tmp_path: Path) -> None:
    """A stale writer must be fenced before the first interior agent wipe.

    ``clear_all`` used to delete each agent with the user generation still at
    0 and bump only in the final summaries commit. A same-process extraction
    could then reload the emptied agent, rebase, and restore facts the rest of
    the loop never re-wipes.
    """
    config = DeerMemConfig(storage_path=str(tmp_path))
    storage = FileMemoryStorage(config)
    assert storage.save(_memory_with_fact("A likes Python"), "planner", user_id="alice")
    researcher_fact = copy.deepcopy(_memory_with_fact("User likes Python")["facts"][0])
    researcher_fact["id"] = "fact_researcher"
    assert storage.save(_memory_with_fact() | {"facts": [researcher_fact]}, "researcher", user_id="alice")
    loaded = storage.load("researcher", user_id="alice")
    old_generation = scope_clear_generation(loaded, "researcher")

    path = storage._get_memory_file_path(user_id="alice")
    real_commit = storage._commit_changes_locked
    probing = False
    fenced_commits = 0

    def wrapped(*args, **kwargs):
        nonlocal probing, fenced_commits
        result = real_commit(*args, **kwargs)
        if probing:
            return result
        probing = True
        try:
            # Probe inside the held locks: a same-process writer on Linux can
            # enter _commit_changes_locked while clear_all still owns flock.
            restored = copy.deepcopy(_memory_with_fact("restored during clear_all")["facts"][0])
            restored["id"] = "fact_restored"
            current = storage._load_memory_file(path)
            with pytest.raises(MemoryClearGenerationConflict):
                real_commit(
                    path,
                    user_id="alice",
                    agent_name="researcher",
                    upserts=[restored],
                    deletes=[],
                    summaries=None,
                    expected_revision=int((current or {}).get("revision") or 0),
                    upsert_revisions={"fact_restored": None},
                    expected_clear_generation=old_generation,
                )
            fenced_commits += 1
        finally:
            probing = False
        return result

    storage._commit_changes_locked = wrapped  # type: ignore[method-assign]
    storage.clear_all(user_id="alice")

    assert fenced_commits >= 1
    assert storage.load("planner", user_id="alice")["facts"] == []
    assert storage.load("researcher", user_id="alice")["facts"] == []
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["clearGeneration"] == 1


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
    conversation = _conversation()
    result = updater.update_memory(conversation, thread_id="thread-1", agent_name="researcher", user_id="alice")

    fresh = FileMemoryStorage(config).load("researcher", user_id="alice")
    assert result is False
    assert fresh["facts"] == []

    later = updater.update_memory(conversation, thread_id="thread-1", agent_name="researcher", user_id="alice")
    assert later is True
    assert updater._llm.invoke.call_count == 1
    assert FileMemoryStorage(config).load("researcher", user_id="alice")["facts"] == []


def test_in_flight_extraction_does_not_restore_facts_after_cross_worker_clear_all(tmp_path: Path) -> None:
    config = DeerMemConfig(storage_path=str(tmp_path), fact_confidence_threshold=0.7, max_facts=100)
    storage = FileMemoryStorage(config)
    assert storage.save(_memory_with_fact("A likes Python"), "planner", user_id="alice")
    researcher_fact = copy.deepcopy(_memory_with_fact("User likes Python")["facts"][0])
    researcher_fact["id"] = "fact_researcher"
    assert storage.save(_memory_with_fact() | {"facts": [researcher_fact]}, "researcher", user_id="alice")
    other = DeerMem(backend_config={"storage_path": str(tmp_path)})

    def invoke_and_clear_all(prompt, config=None):
        other.clear_memory(user_id="alice")
        response = MagicMock()
        response.content = _extraction_json("User likes Python")
        return response

    updater = _updater(storage, invoke_and_clear_all)
    conversation = _conversation()
    result = updater.update_memory(conversation, thread_id="thread-1", agent_name="researcher", user_id="alice")

    assert result is False
    assert FileMemoryStorage(config).load("planner", user_id="alice")["facts"] == []
    assert FileMemoryStorage(config).load("researcher", user_id="alice")["facts"] == []

    later = updater.update_memory(conversation, thread_id="thread-1", agent_name="researcher", user_id="alice")
    assert later is True
    assert updater._llm.invoke.call_count == 1
    assert FileMemoryStorage(config).load("researcher", user_id="alice")["facts"] == []


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

    conversation = _queue_conversation()
    manager_a.add(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
    assert manager_a._queue.pending_count == 1
    assert manager_a._queue._items[0].clear_generation == (0, 0)
    _stop_debounce(manager_a)

    manager_b = _manager(tmp_path)
    manager_b.clear_memory(agent_name="researcher", user_id="alice")
    assert manager_b.get_memory(agent_name="researcher", user_id="alice")["facts"] == []

    manager_a._queue.flush()

    host_llm.invoke.assert_not_called()
    assert manager_b.get_memory(agent_name="researcher", user_id="alice")["facts"] == []

    manager_a.add(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
    _stop_debounce(manager_a)
    manager_a._queue.flush()
    host_llm.invoke.assert_not_called()
    assert manager_b.get_memory(agent_name="researcher", user_id="alice")["facts"] == []


def test_same_manager_clear_does_not_restore_cancelled_pending_on_next_turn(tmp_path: Path) -> None:
    """#5123 drops the debounce buffer; the fence must still consume that snapshot."""
    host_llm = MagicMock()
    host_llm.invoke = MagicMock(side_effect=AssertionError("cancelled pending extraction must not restore after clear"))
    manager = _manager(tmp_path, host_llm)
    manager.create_fact("User likes Python", category="preference", confidence=0.9, agent_name="researcher", user_id="alice")

    conversation = _queue_conversation()
    manager.add(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
    assert manager._queue.pending_count == 1
    _stop_debounce(manager)

    manager.clear_memory(agent_name="researcher", user_id="alice")
    assert manager._queue.pending_count == 0
    assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []

    manager.add(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    manager._queue.flush()

    host_llm.invoke.assert_not_called()
    assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []


def test_late_in_flight_completion_does_not_regress_watermark_past_a_cancelled_newer_turn(tmp_path: Path) -> None:
    """#5125 review (2026-09-12): a delayed, generation-fenced drop must not
    move the watermark backward past a later turn a concurrent clear already
    cancelled and consumed.

    Sequence reproduced (matches the reviewer's report):
      1. Turn A ("I like Python") is pulled off the debounce queue and its LLM
         call is in flight (slow provider).
      2. Turn A+B ("...actually I prefer Rust") is queued for the same
         conversation while A is still running.
      3. A clear lands: it cancels the still-queued A+B snapshot (which
         advances the watermark *past* B, per the existing fence) and bumps
         the clear generation.
      4. A's in-flight LLM call returns. The commit is correctly fenced
         (dropped) because a newer clear landed -- but marking that drop
         "consumed" must not overwrite the watermark that step 3 already
         advanced further, or the next turn re-feeds B's pre-clear message
         and restores it now that no further clear is pending.
    """
    turn_a = _queue_conversation()
    turn_a_plus_b = _queue_conversation(
        human="Actually, on second thought I prefer Rust.",
        ai="Noted, I will remember Rust instead.",
    )
    full_conversation = [*turn_a, *turn_a_plus_b]

    invoke_started = threading.Event()
    release_invoke = threading.Event()
    invoke_calls: list[list[Any]] = []

    def slow_invoke(prompt, config=None):
        invoke_calls.append(prompt)
        if len(invoke_calls) == 1:
            # Simulate a slow provider: block until the test has finished
            # queuing + cancelling the newer turn on another "worker".
            invoke_started.set()
            assert release_invoke.wait(timeout=5), "test did not release the in-flight LLM call in time"
            return MagicMock(content=_extraction_json("User likes Python"))
        return MagicMock(content=_extraction_json("User prefers Rust"))

    host_llm = MagicMock()
    host_llm.invoke = MagicMock(side_effect=slow_invoke)
    manager = _manager(tmp_path, host_llm)

    # Step 1: turn A is pulled off the queue and blocks mid-LLM-call.
    manager.add(thread_id="thread-1", messages=turn_a, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    worker = threading.Thread(target=lambda: manager._queue.flush(skip_inter_item_delay=True))
    worker.start()
    assert invoke_started.wait(timeout=5), "in-flight LLM call for turn A never started"

    # Step 2: turn A+B is queued for the same conversation while A is in flight.
    manager.add(thread_id="thread-1", messages=full_conversation, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    assert manager._queue.pending_count == 1

    # Step 3: a clear cancels the still-queued A+B snapshot (advancing the
    # watermark past B) and bumps the clear generation.
    manager.clear_memory(agent_name="researcher", user_id="alice")
    assert manager._queue.pending_count == 0

    # Step 4: release A's in-flight call. Its commit must be fenced, and its
    # own (older) watermark advance must not undo step 3's.
    release_invoke.set()
    worker.join(timeout=5)
    assert not worker.is_alive()

    assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []

    # The middleware always re-sends the full running conversation. If the
    # watermark had regressed to turn A's tail, this would re-feed B's
    # pre-clear "prefer Rust" message; since no further clear is pending, that
    # extraction would succeed and restore the cleared content.
    manager.add(thread_id="thread-1", messages=full_conversation, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    manager._queue.flush()

    assert len(invoke_calls) == 1, "turn B's pre-clear message must not be re-extracted after the clear"
    assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []


def test_queued_coalesce_after_clear_extracts_post_clear_turns(tmp_path: Path) -> None:
    host_llm = MagicMock()
    host_llm.invoke = MagicMock(return_value=MagicMock(content=_extraction_json("User prefers typed Python")))
    manager_a = _manager(tmp_path, host_llm)
    manager_a.create_fact("User likes Python", category="preference", confidence=0.9, agent_name="researcher", user_id="alice")

    pre_clear = _queue_conversation()
    post_clear = _queue_conversation(human="Also remember that I prefer typed Python.", ai="Noted, I will keep that preference.")
    full_conversation = [*pre_clear, *post_clear]
    manager_a.add(thread_id="thread-1", messages=pre_clear, agent_name="researcher", user_id="alice")
    assert manager_a._queue._items[0].clear_generation == (0, 0)
    _stop_debounce(manager_a)

    manager_b = _manager(tmp_path)
    manager_b.clear_memory(agent_name="researcher", user_id="alice")

    manager_a.add(thread_id="thread-1", messages=full_conversation, agent_name="researcher", user_id="alice")
    assert manager_a._queue.pending_count == 1
    assert manager_a._queue._items[0].clear_generation == (0, 1)
    _stop_debounce(manager_a)

    manager_a._queue.flush()

    host_llm.invoke.assert_called_once()
    facts = {fact["content"] for fact in manager_b.get_memory(agent_name="researcher", user_id="alice")["facts"]}
    assert "User likes Python" not in facts
    assert "User prefers typed Python" in facts

    manager_a.add(thread_id="thread-1", messages=full_conversation, agent_name="researcher", user_id="alice")
    _stop_debounce(manager_a)
    manager_a._queue.flush()
    host_llm.invoke.assert_called_once()
    later = {fact["content"] for fact in manager_b.get_memory(agent_name="researcher", user_id="alice")["facts"]}
    assert later == facts


def test_out_of_order_enqueue_does_not_restore_facts_after_clear(tmp_path: Path) -> None:
    host_llm = MagicMock()
    host_llm.invoke = MagicMock(return_value=MagicMock(content=_extraction_json("User prefers typed Python")))
    manager_a = _manager(tmp_path, host_llm)
    manager_a.create_fact("User likes Python", category="preference", confidence=0.9, agent_name="researcher", user_id="alice")

    pre_clear = _queue_conversation()
    post_clear = _queue_conversation(human="Also remember that I prefer typed Python.", ai="Noted, I will keep that preference.")
    full_conversation = [*pre_clear, *post_clear]

    manager_b = _manager(tmp_path)
    manager_b.clear_memory(agent_name="researcher", user_id="alice")

    manager_a.add(thread_id="thread-1", messages=full_conversation, agent_name="researcher", user_id="alice")
    queued = manager_a._queue._items[0]
    assert queued.clear_generation == (0, 1)
    queued_messages = list(queued.messages)
    _stop_debounce(manager_a)

    with manager_a._queue._lock:
        # call_sequence=0: this simulates a caller whose add() call started
        # (and peeked the clear generation) before manager_a's real add()
        # above, but is only now winning the lock -- i.e. a lower sequence
        # than that already-queued call's (1), consistent with how a real
        # add() would have captured it pre-lock (see _next_sequence).
        manager_a._queue._enqueue_locked(
            thread_id="thread-1",
            messages=pre_clear,
            agent_name="researcher",
            user_id="alice",
            trace_id=None,
            signals=frozenset(),
            bypass_watermark=False,
            captured_clear_generation=(0, 0),
            call_sequence=0,
        )

    assert manager_a._queue.pending_count == 1
    assert manager_a._queue._items[0].messages == queued_messages
    assert manager_a._queue._items[0].clear_generation == (0, 1)

    manager_a._queue.flush()

    host_llm.invoke.assert_called_once()
    facts = {fact["content"] for fact in manager_b.get_memory(agent_name="researcher", user_id="alice")["facts"]}
    assert "User likes Python" not in facts
    assert "User prefers typed Python" in facts


def test_delayed_lock_acquisition_does_not_regress_watermark_across_a_clear(tmp_path: Path) -> None:
    """#5125 review (2026-09-12 follow-up): the sequence used to order
    watermark writes must reflect when a call *arrived* (peeked, pre-lock),
    not when it *won the queue lock* -- those can differ, and a caller
    delayed behind the lock while a clear and a newer turn race ahead of it
    must keep the low sequence it started with.

    Sequence reproduced:
      1. Turn A's ``add()`` peeks the (pre-clear) generation but blocks before
         acquiring the queue lock (e.g. a slow scheduler).
      2. Turn A+B is queued for real (a normal ``add()`` call) while A is
         still blocked.
      3. A clear cancels the queued A+B snapshot -- advancing the watermark
         past B -- and bumps the generation.
      4. Turn D is queued post-clear, carrying the *full* running conversation
         (A+B+D), exactly as the middleware always sends it: clearing memory
         does not rewrite the chat transcript.
      5. A is released and finally wins the lock. Its peek is stale, so it
         takes the "refused older add, consume it" branch -- but that must not
         out-rank step 3's watermark: A's own sequence was assigned back in
         step 1, before B, the clear, or D ever happened.
      6. Flushing D's queued (full A+B+D) snapshot must feed only D's new
         turn -- if the watermark had regressed to A's tail in step 5, this
         would re-feed B's pre-clear "prefer Rust" mention and, since no
         further clear is pending, restore it.
    """
    turn_a = _queue_conversation()
    turn_b = _queue_conversation(human="Actually, I prefer Rust.", ai="Noted, I will remember Rust instead.")
    turn_d = _queue_conversation(human="What language do I use for scripting?", ai="Let me check your notes.")

    def fake_invoke(prompt: Any, config: Any = None) -> Any:
        # A minimal, content-driven fake: only extract a fact when the fed
        # text actually mentions Rust, so any accidental re-feed of turn B is
        # directly observable as a restored fact, regardless of exactly which
        # other turns rode along in the same LLM call.
        if "Rust" in str(prompt):
            return MagicMock(content=_extraction_json("User prefers Rust"))
        return MagicMock(content=json.dumps({"user": {}, "history": {}, "newFacts": [], "factsToRemove": []}))

    host_llm = MagicMock()
    host_llm.invoke = MagicMock(side_effect=fake_invoke)
    manager = _manager(tmp_path, host_llm)

    real_peek = manager._updater.peek_clear_generation
    peeked_first = threading.Event()
    release_first = threading.Event()
    peek_count = {"n": 0}

    def blocking_peek(agent_name: str | None = None, *, user_id: str | None = None) -> tuple[int, int]:
        peek_count["n"] += 1
        if peek_count["n"] == 1:
            # Capture the pre-clear value *before* blocking: a real caller's
            # peek already returned by the time it is merely waiting on the
            # queue lock, so the value it carries into the lock is this one,
            # not whatever the generation has become by the time it wakes.
            value = real_peek(agent_name, user_id=user_id)
            peeked_first.set()
            assert release_first.wait(timeout=5), "test did not release the delayed peek in time"
            return value
        return real_peek(agent_name, user_id=user_id)

    manager._updater.peek_clear_generation = blocking_peek

    errors: list[BaseException] = []

    def enqueue_a() -> None:
        try:
            manager.add(thread_id="thread-1", messages=turn_a, agent_name="researcher", user_id="alice")
        except BaseException as exc:  # noqa: BLE001 - surfaced via `errors`
            errors.append(exc)

    # Step 1: turn A peeks (pre-clear) and then blocks before the queue lock.
    a_thread = threading.Thread(target=enqueue_a)
    a_thread.start()
    assert peeked_first.wait(timeout=5), "turn A's peek never started"

    # Step 2: turn A+B is queued for real while A is still blocked.
    manager.add(thread_id="thread-1", messages=[*turn_a, *turn_b], agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    assert manager._queue.pending_count == 1

    # Step 3: a clear cancels the queued A+B snapshot (advancing the
    # watermark past B) and bumps the generation.
    manager.clear_memory(agent_name="researcher", user_id="alice")
    assert manager._queue.pending_count == 0

    # Step 4: turn D is queued post-clear, carrying the full running
    # conversation (clearing memory does not rewrite the chat transcript).
    full_at_d = [*turn_a, *turn_b, *turn_d]
    manager.add(thread_id="thread-1", messages=full_at_d, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    assert manager._queue.pending_count == 1

    # Step 5: release A. It wins the lock now, finds D's newer generation, and
    # is refused -- but must not out-rank step 3's watermark.
    release_first.set()
    a_thread.join(timeout=5)
    assert not a_thread.is_alive()
    assert errors == []

    # D's queued snapshot itself must be untouched by A's late, stale enqueue.
    assert manager._queue.pending_count == 1
    assert manager._queue._items[0].messages == full_at_d

    # Step 6: flush D. It must feed only D's new turn.
    manager._queue.flush()

    facts = {fact["content"] for fact in manager.get_memory(agent_name="researcher", user_id="alice")["facts"]}
    assert "User prefers Rust" not in facts, "turn B's pre-clear message must not be re-extracted after the clear"


def test_create_memory_fact_retries_after_cross_worker_clear(tmp_path: Path) -> None:
    """A clear between create's snapshot and first commit must still store the new fact.

    Extraction drops on MemoryClearGenerationConflict so pre-clear chat cannot
    restore wiped facts. Manual create upserts a brand-new fact_id, so the same
    exception is retried with the post-clear fence.
    """
    storage = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)))
    updater = _updater(storage, lambda *_args, **_kwargs: _extraction_json("unused"))
    assert storage.save(_memory_with_fact(), "researcher", user_id="alice")

    real_apply = storage.apply_changes
    apply_calls = {"n": 0}

    def apply_after_concurrent_clear(*args, **kwargs):
        apply_calls["n"] += 1
        if apply_calls["n"] == 1:
            FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path))).clear_all(user_id="alice")
        return real_apply(*args, **kwargs)

    storage.apply_changes = apply_after_concurrent_clear
    memory, fact_id = updater.create_memory_fact(
        content="I live in Beijing",
        category="context",
        confidence=0.9,
        agent_name="researcher",
        user_id="alice",
    )

    assert fact_id is not None
    assert apply_calls["n"] == 2
    contents = {fact["content"] for fact in memory["facts"]}
    assert "I live in Beijing" in contents
    assert "User likes Python" not in contents


class IgnoringClearGenerationStorage(MemoryStorage):
    """Custom provider that swallows fence kwargs through ``**scope``."""

    def __init__(self, config: DeerMemConfig | None = None) -> None:
        self._memory = create_empty_memory()

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        return copy.deepcopy(self._memory)

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        return self.load(agent_name, user_id=user_id)

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None, expected_revision: int | None = None) -> bool:
        self._memory = copy.deepcopy(memory_data)
        return True

    def apply_changes(self, change_set: dict[str, Any], **scope: Any) -> dict[str, Any]:
        return {"complete": False}

    def clear_all(self, *, user_id: str | None = None) -> dict[str, Any]:
        self._memory = create_empty_memory()
        return copy.deepcopy(self._memory)


class NamedFenceWithoutCapabilitiesStorage(MemoryStorage):
    """Declares fence parameters but does not implement ``capabilities()``."""

    def __init__(self, config: DeerMemConfig | None = None) -> None:
        self._memory = create_empty_memory()

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        return copy.deepcopy(self._memory)

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        return self.load(agent_name, user_id=user_id)

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None, expected_revision: int | None = None) -> bool:
        self._memory = copy.deepcopy(memory_data)
        return True

    def apply_changes(
        self,
        change_set: dict[str, Any],
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        expected_manifest_revision: int | None = None,
        allow_manifest_rebase: bool = False,
        expected_clear_generation: tuple[int, int] | None = None,
        bump_clear_generation: str | None = None,
    ) -> dict[str, Any]:
        return {"complete": False}

    def clear_all(self, *, user_id: str | None = None) -> dict[str, Any]:
        self._memory = create_empty_memory()
        return copy.deepcopy(self._memory)


class NamedFenceOmittingCapabilityStorage(NamedFenceWithoutCapabilitiesStorage):
    """Names the fence parameters but advertises a different capability set."""

    def capabilities(self) -> set[str]:
        return {"custom"}

    def peek_clear_generation(self, agent_name: str | None = None, *, user_id: str | None = None) -> tuple[int, int]:
        return (0, 0)


class NamedFenceWithoutPeekStorage(NamedFenceWithoutCapabilitiesStorage):
    """Satisfies apply/clear_all/capabilities but inherits the base peek."""

    def capabilities(self) -> set[str]:
        return {CLEAR_GENERATION_CAPABILITY}


class TransactionalClearGenerationStorage(MemoryStorage):
    """In-memory provider that checks and bumps clear generation under one lock."""

    def __init__(
        self,
        config: DeerMemConfig | None = None,
        *,
        store: dict[str, Any] | None = None,
        lock: threading.Lock | None = None,
    ) -> None:
        self._lock = lock if lock is not None else threading.Lock()
        self._store = store if store is not None else self._empty_store()

    @staticmethod
    def _empty_store() -> dict[str, Any]:
        return {"user_gen": 0, "agent_gens": {}, "revision": 0, "facts": {}}

    def capabilities(self) -> set[str]:
        return {CLEAR_GENERATION_CAPABILITY}

    def peek_clear_generation(self, agent_name: str | None = None, *, user_id: str | None = None) -> tuple[int, int]:
        with self._lock:
            return self._store["user_gen"], self._store["agent_gens"].get(agent_name, 0)

    def _document_locked(self, agent_name: str | None, user_id: str | None) -> dict[str, Any]:
        memory = create_empty_memory()
        memory["revision"] = self._store["revision"]
        memory["facts"] = copy.deepcopy(self._store["facts"].get((user_id, agent_name), []))
        if self._store["user_gen"]:
            memory["clearGeneration"] = self._store["user_gen"]
        if self._store["agent_gens"]:
            memory["agentClearGenerations"] = dict(self._store["agent_gens"])
        return memory

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            return self._document_locked(agent_name, user_id)

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        return self.load(agent_name, user_id=user_id)

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None, expected_revision: int | None = None) -> bool:
        with self._lock:
            self._store["facts"][(user_id, agent_name)] = copy.deepcopy(memory_data.get("facts", []))
            self._store["revision"] = int(memory_data.get("revision") or self._store["revision"]) + 1
        return True

    def apply_changes(
        self,
        change_set: dict[str, Any],
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        expected_manifest_revision: int | None = None,
        allow_manifest_rebase: bool = False,
        expected_clear_generation: tuple[int, int] | None = None,
        bump_clear_generation: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            current = (self._store["user_gen"], self._store["agent_gens"].get(agent_name, 0) if agent_name else 0)
            if expected_clear_generation is not None and is_stale_clear_generation(expected_clear_generation, current):
                raise MemoryClearGenerationConflict(f"Expected clear generation {expected_clear_generation}, found {current}")
            if expected_manifest_revision is not None and expected_manifest_revision != self._store["revision"]:
                raise MemoryManifestRevisionConflict(f"Expected user-memory revision {expected_manifest_revision}, found {self._store['revision']}")
            facts = list(self._store["facts"].get((user_id, agent_name), []))
            by_id = {str(fact.get("id")): fact for fact in facts}
            for incoming in change_set.get("upserts", []):
                by_id[str(incoming["id"])] = copy.deepcopy(incoming)
            for fact_id in change_set.get("deletes", []):
                by_id.pop(str(fact_id), None)
            self._store["facts"][(user_id, agent_name)] = list(by_id.values())
            if bump_clear_generation == "user":
                self._store["user_gen"] += 1
            elif bump_clear_generation == "agent":
                if agent_name is None:
                    raise ValueError("agent_name is required to bump agent clear generation")
                self._store["agent_gens"][agent_name] = self._store["agent_gens"].get(agent_name, 0) + 1
            self._store["revision"] += 1
            return {"complete": False}

    def clear_all(self, *, user_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if user_id is not None:
                for key in list(self._store["facts"]):
                    if key[0] == user_id:
                        self._store["facts"][key] = []
            else:
                self._store["facts"] = {}
            self._store["user_gen"] += 1
            self._store["revision"] += 1
            return self._document_locked(None, user_id)


def _install_storage_module(name: str, **classes: type) -> None:
    module = types.ModuleType(name)
    for class_name, storage_cls in classes.items():
        setattr(module, class_name, storage_cls)
    sys.modules[name] = module


def test_create_storage_rejects_provider_that_ignores_clear_generation() -> None:
    assert declares_clear_generation_fence(IgnoringClearGenerationStorage) is False
    _install_storage_module("clear_generation_fakes", IgnoringClearGenerationStorage=IgnoringClearGenerationStorage)
    try:
        with pytest.raises(ValueError, match="clear-generation"):
            create_storage(DeerMemConfig(storage_class="clear_generation_fakes.IgnoringClearGenerationStorage"))
    finally:
        sys.modules.pop("clear_generation_fakes", None)


def test_create_storage_rejects_provider_without_capabilities_method() -> None:
    assert declares_clear_generation_fence(NamedFenceWithoutCapabilitiesStorage) is False
    _install_storage_module("clear_generation_fakes", Storage=NamedFenceWithoutCapabilitiesStorage)
    try:
        with pytest.raises(ValueError, match="clear-generation"):
            create_storage(DeerMemConfig(storage_class="clear_generation_fakes.Storage"))
    finally:
        sys.modules.pop("clear_generation_fakes", None)


def test_create_storage_rejects_provider_that_omits_clear_generation_capability() -> None:
    assert declares_clear_generation_fence(NamedFenceOmittingCapabilityStorage) is True
    _install_storage_module("clear_generation_fakes", Storage=NamedFenceOmittingCapabilityStorage)
    try:
        with pytest.raises(ValueError, match="clear-generation"):
            create_storage(DeerMemConfig(storage_class="clear_generation_fakes.Storage"))
    finally:
        sys.modules.pop("clear_generation_fakes", None)


def test_create_storage_rejects_provider_without_peek_clear_generation() -> None:
    assert declares_clear_generation_fence(NamedFenceWithoutPeekStorage) is False
    _install_storage_module("clear_generation_fakes", Storage=NamedFenceWithoutPeekStorage)
    try:
        with pytest.raises(ValueError, match="clear-generation"):
            create_storage(DeerMemConfig(storage_class="clear_generation_fakes.Storage"))
    finally:
        sys.modules.pop("clear_generation_fakes", None)


def test_base_peek_clear_generation_does_not_load_the_document() -> None:
    storage = NamedFenceWithoutPeekStorage()
    with pytest.raises(NotImplementedError):
        storage.peek_clear_generation("researcher", user_id="alice")


def test_create_storage_accepts_transactional_clear_generation_provider() -> None:
    _install_storage_module("clear_generation_fakes", TransactionalClearGenerationStorage=TransactionalClearGenerationStorage)
    try:
        storage = create_storage(DeerMemConfig(storage_class="clear_generation_fakes.TransactionalClearGenerationStorage"))
    finally:
        sys.modules.pop("clear_generation_fakes", None)
    assert isinstance(storage, TransactionalClearGenerationStorage)
    assert CLEAR_GENERATION_CAPABILITY in storage.capabilities()


def test_transactional_custom_storage_fence_rejects_stale_write_after_clear() -> None:
    store = TransactionalClearGenerationStorage._empty_store()
    lock = threading.Lock()
    writer = TransactionalClearGenerationStorage(DeerMemConfig(), store=store, lock=lock)
    clearer = TransactionalClearGenerationStorage(DeerMemConfig(), store=store, lock=lock)
    fact = copy.deepcopy(_memory_with_fact()["facts"][0])
    writer.apply_changes(
        {"upserts": [fact], "upsertRevisions": {fact["id"]: None}},
        agent_name="researcher",
        user_id="alice",
        expected_manifest_revision=0,
        expected_clear_generation=(0, 0),
    )
    clearer.clear_all(user_id="alice")
    restored = copy.deepcopy(fact)
    restored["id"] = "fact_restored"
    with pytest.raises(MemoryClearGenerationConflict):
        writer.apply_changes(
            {"upserts": [restored], "upsertRevisions": {"fact_restored": None}},
            agent_name="researcher",
            user_id="alice",
            expected_manifest_revision=int(writer.load("researcher", user_id="alice")["revision"] or 0),
            expected_clear_generation=(0, 0),
        )
    assert writer.load("researcher", user_id="alice")["facts"] == []


def test_transactional_custom_storage_serializes_clear_and_stale_write() -> None:
    store = TransactionalClearGenerationStorage._empty_store()
    lock = threading.Lock()
    writer = TransactionalClearGenerationStorage(DeerMemConfig(), store=store, lock=lock)
    clearer = TransactionalClearGenerationStorage(DeerMemConfig(), store=store, lock=lock)
    seed = copy.deepcopy(_memory_with_fact()["facts"][0])
    writer.apply_changes(
        {"upserts": [seed], "upsertRevisions": {seed["id"]: None}},
        agent_name="researcher",
        user_id="alice",
        expected_manifest_revision=0,
        expected_clear_generation=(0, 0),
    )
    restored = copy.deepcopy(seed)
    restored["id"] = "fact_restored"
    errors: list[BaseException] = []

    def stale_write() -> None:
        try:
            writer.apply_changes(
                {"upserts": [restored], "upsertRevisions": {"fact_restored": None}},
                agent_name="researcher",
                user_id="alice",
                expected_manifest_revision=int(writer.load("researcher", user_id="alice")["revision"] or 0),
                expected_clear_generation=(0, 0),
            )
        except MemoryClearGenerationConflict as exc:
            errors.append(exc)

    worker = threading.Thread(target=stale_write)
    worker.start()
    clearer.clear_all(user_id="alice")
    worker.join()
    assert writer.load("researcher", user_id="alice")["facts"] == []


def test_llm_timeout_during_clear_consumes_pre_clear_snapshot(tmp_path: Path) -> None:
    """A clear that lands while the memory LLM is in flight must still consume
    the snapshot when that call fails. Otherwise the next full conversation
    re-extracts the cleared turns against the new generation.
    """
    invoke_started = threading.Event()
    release_invoke = threading.Event()

    def timeout_invoke(prompt, config=None):
        invoke_started.set()
        assert release_invoke.wait(timeout=5), "test did not release the in-flight LLM call in time"
        raise TimeoutError("memory LLM timed out")

    host_llm = MagicMock()
    host_llm.invoke = MagicMock(side_effect=timeout_invoke)
    manager = _manager(tmp_path, host_llm)
    conversation = _queue_conversation()

    manager.add(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    worker = threading.Thread(target=lambda: manager._queue.flush(skip_inter_item_delay=True))
    worker.start()
    assert invoke_started.wait(timeout=5), "in-flight LLM call never started"

    manager.clear_memory(agent_name="researcher", user_id="alice")
    release_invoke.set()
    worker.join(timeout=5)
    assert not worker.is_alive()

    host_llm.invoke.reset_mock()
    host_llm.invoke.side_effect = None
    host_llm.invoke.return_value = MagicMock(content=_extraction_json("User likes Python"))

    manager.add(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    manager._queue.flush()

    host_llm.invoke.assert_not_called()
    assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []


def test_invalid_json_during_clear_consumes_pre_clear_snapshot(tmp_path: Path) -> None:
    invoke_started = threading.Event()
    release_invoke = threading.Event()

    def invalid_json_invoke(prompt, config=None):
        invoke_started.set()
        assert release_invoke.wait(timeout=5), "test did not release the in-flight LLM call in time"
        return MagicMock(content="not-json")

    host_llm = MagicMock()
    host_llm.invoke = MagicMock(side_effect=invalid_json_invoke)
    manager = _manager(tmp_path, host_llm)
    conversation = _queue_conversation()

    manager.add(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    worker = threading.Thread(target=lambda: manager._queue.flush(skip_inter_item_delay=True))
    worker.start()
    assert invoke_started.wait(timeout=5), "in-flight LLM call never started"

    manager.clear_memory(agent_name="researcher", user_id="alice")
    release_invoke.set()
    worker.join(timeout=5)
    assert not worker.is_alive()

    host_llm.invoke.reset_mock()
    host_llm.invoke.side_effect = None
    host_llm.invoke.return_value = MagicMock(content=_extraction_json("User likes Python"))

    manager.add(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    manager._queue.flush()

    host_llm.invoke.assert_not_called()
    assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []


def test_llm_failure_without_clear_leaves_snapshot_retryable(tmp_path: Path) -> None:
    host_llm = MagicMock()
    host_llm.invoke = MagicMock(side_effect=[MagicMock(content="not-json"), MagicMock(content=_extraction_json("User likes Python"))])
    manager = _manager(tmp_path, host_llm)
    conversation = _queue_conversation()

    manager.add(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    manager._queue.flush()
    assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []

    manager.add(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    manager._queue.flush()

    assert host_llm.invoke.call_count == 2
    facts = {fact["content"] for fact in manager.get_memory(agent_name="researcher", user_id="alice")["facts"]}
    assert "User likes Python" in facts


def test_same_generation_delayed_snapshot_does_not_restore_after_clear(tmp_path: Path) -> None:
    host_llm = MagicMock()
    host_llm.invoke = MagicMock(return_value=MagicMock(content=_extraction_json("User prefers typed Python")))
    manager = _manager(tmp_path, host_llm)
    turn_a = _queue_conversation()
    turn_b = _queue_conversation(
        human="Also remember that I prefer typed Python.",
        ai="Noted, I will keep that preference.",
    )
    full_conversation = [*turn_a, *turn_b]

    with patch.object(manager._queue, "_schedule_timer"):
        manager.add(thread_id="thread-1", messages=full_conversation, agent_name="researcher", user_id="alice")
        queued_messages = list(manager._queue._items[0].messages)
        with manager._queue._lock:
            manager._queue._enqueue_locked(
                thread_id="thread-1",
                messages=turn_a,
                agent_name="researcher",
                user_id="alice",
                trace_id=None,
                signals=frozenset(),
                bypass_watermark=False,
                captured_clear_generation=(0, 0),
                call_sequence=0,
            )

    assert manager._queue.pending_count == 1
    assert manager._queue._items[0].messages == queued_messages

    manager._queue.flush()
    manager.clear_memory(agent_name="researcher", user_id="alice")
    host_llm.invoke.reset_mock()

    manager.add(thread_id="thread-1", messages=full_conversation, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    manager._queue.flush()

    host_llm.invoke.assert_not_called()
    assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []


def test_emergency_flush_after_clear_does_not_restore_pre_clear_facts(tmp_path: Path) -> None:
    host_llm = MagicMock()
    host_llm.invoke = MagicMock(return_value=MagicMock(content=_extraction_json("User likes Python")))
    manager = _manager(tmp_path, host_llm)
    conversation = _queue_conversation()

    manager.add(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    manager._queue.flush()
    assert {fact["content"] for fact in manager.get_memory(agent_name="researcher", user_id="alice")["facts"]} == {"User likes Python"}

    manager.clear_memory(agent_name="researcher", user_id="alice")
    assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []
    host_llm.invoke.reset_mock()

    manager.add(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    manager._queue.flush()
    host_llm.invoke.assert_not_called()

    manager.add_nowait(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    manager._queue.flush()

    host_llm.invoke.assert_not_called()
    assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []


def test_emergency_flush_after_clear_still_extracts_post_clear_turns(tmp_path: Path) -> None:
    host_llm = MagicMock()
    host_llm.invoke = MagicMock(return_value=MagicMock(content=_extraction_json("User likes Python")))
    manager = _manager(tmp_path, host_llm)
    pre_clear = _queue_conversation()
    post_clear = _queue_conversation(
        human="Also remember that I prefer typed Python.",
        ai="Noted, I will keep that preference.",
    )
    full_conversation = [*pre_clear, *post_clear]

    manager.add(thread_id="thread-1", messages=pre_clear, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    manager._queue.flush()
    manager.clear_memory(agent_name="researcher", user_id="alice")

    host_llm.invoke.reset_mock()
    prompts: list[str] = []

    def invoke_post_clear(prompt, config=None):
        prompts.append(str(prompt))
        return MagicMock(content=_extraction_json("User prefers typed Python"))

    host_llm.invoke.side_effect = invoke_post_clear
    with patch.object(manager._queue, "_schedule_timer"):
        manager.add_nowait(thread_id="thread-1", messages=full_conversation, agent_name="researcher", user_id="alice")
    assert manager._queue.pending_count == 1
    queued_contents = [getattr(message, "content", None) for message in manager._queue._items[0].messages]
    assert queued_contents == [
        "Remember that I like Python.",
        "I'll keep that preference in mind.",
        "Also remember that I prefer typed Python.",
        "Noted, I will keep that preference.",
    ]
    manager._queue.flush()

    assert host_llm.invoke.call_count == 1, prompts
    assert "Remember that I like Python." not in prompts[0]
    facts = {fact["content"] for fact in manager.get_memory(agent_name="researcher", user_id="alice")["facts"]}
    assert "User likes Python" not in facts
    assert "User prefers typed Python" in facts


def test_emergency_flush_of_cleared_prefix_does_not_restore_facts(tmp_path: Path) -> None:
    """Summarization that keeps B and only submits A must not rewrite A's facts."""
    host_llm = MagicMock()
    host_llm.invoke = MagicMock(return_value=MagicMock(content=_extraction_json("User likes Python")))
    manager = _manager(tmp_path, host_llm)
    turn_a = _queue_conversation()
    turn_b = _queue_conversation(human="Also remember I like Rust.", ai="Noted about Rust.")
    conversation = [*turn_a, *turn_b]

    with patch.object(manager._queue, "_schedule_timer"):
        manager.add(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
    manager._queue.flush()
    assert {fact["content"] for fact in manager.get_memory(agent_name="researcher", user_id="alice")["facts"]} == {"User likes Python"}

    manager.clear_memory(agent_name="researcher", user_id="alice")
    assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []
    host_llm.invoke.reset_mock()

    with patch.object(manager._queue, "_schedule_timer"):
        manager.add_nowait(thread_id="thread-1", messages=turn_a, agent_name="researcher", user_id="alice")
        assert manager._queue.pending_count == 1
    manager._queue.flush()

    host_llm.invoke.assert_not_called()
    assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []


def test_queued_then_cleared_prefix_flush_does_not_restore_facts(tmp_path: Path) -> None:
    """A+B still in the debounce queue when cleared: later prefix A must stay excluded."""
    host_llm = MagicMock()
    host_llm.invoke = MagicMock(return_value=MagicMock(content=_extraction_json("User likes Python")))
    manager = _manager(tmp_path, host_llm)
    turn_a = _queue_conversation()
    turn_b = _queue_conversation(human="Also remember I like Rust.", ai="Noted about Rust.")
    conversation = [*turn_a, *turn_b]

    with patch.object(manager._queue, "_schedule_timer"):
        manager.add(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
        assert manager._queue.pending_count == 1

    manager.clear_memory(agent_name="researcher", user_id="alice")
    host_llm.invoke.reset_mock()

    with patch.object(manager._queue, "_schedule_timer"):
        manager.add_nowait(thread_id="thread-1", messages=turn_a, agent_name="researcher", user_id="alice")
    manager._queue.flush()

    host_llm.invoke.assert_not_called()
    assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []


def test_later_summary_subset_does_not_retreat_exclusion_and_restore_tail(tmp_path: Path) -> None:
    """A later emergency A must not shrink exclusion from B back to A."""
    host_llm = MagicMock()
    host_llm.invoke = MagicMock(return_value=MagicMock(content=_extraction_json("User likes Python")))
    manager = _manager(tmp_path, host_llm)
    turn_a = _queue_conversation()
    turn_b = _queue_conversation(human="Also remember I like Rust.", ai="Noted about Rust.")
    conversation = [*turn_a, *turn_b]

    with patch.object(manager._queue, "_schedule_timer"):
        manager.add(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
    manager._queue.flush()
    assert {fact["content"] for fact in manager.get_memory(agent_name="researcher", user_id="alice")["facts"]} == {"User likes Python"}

    host_llm.invoke.reset_mock()
    host_llm.invoke.return_value = MagicMock(content=_extraction_json("User likes Rust"))
    with patch.object(manager._queue, "_schedule_timer"):
        manager.add(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
        manager.add_nowait(thread_id="thread-1", messages=turn_a, agent_name="researcher", user_id="alice")
        assert manager._queue.pending_count == 2
    manager.clear_memory(agent_name="researcher", user_id="alice")
    assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []

    with patch.object(manager._queue, "_schedule_timer"):
        manager.add_nowait(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
        assert manager._queue.pending_count == 1
    manager._queue.flush()

    host_llm.invoke.assert_not_called()
    assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []


def test_emergency_only_add_nowait_then_later_clear_does_not_restore(tmp_path: Path) -> None:
    """add_nowait persist, then a later clear, must not restore via regular add.

    Emergency extraction does not write a watermark. Clear still has to
    promote that coverage so the next ordinary add of the same pre-clear
    turns (plus a new one) cannot rewrite the cleared preference.
    """
    host_llm = MagicMock()
    host_llm.invoke = MagicMock(return_value=MagicMock(content=_extraction_json("User likes Python")))
    manager = _manager(tmp_path, host_llm)
    turn_a = [
        HumanMessage(content="Remember that I like Python.", id="human-python"),
        AIMessage(content="I'll keep that preference in mind.", id="ai-python"),
    ]
    turn_b = [
        HumanMessage(content="Also remember I like Rust.", id="human-rust"),
        AIMessage(content="Noted about Rust.", id="ai-rust"),
    ]

    with patch.object(manager._queue, "_schedule_timer"):
        manager.add_nowait(thread_id="thread-1", messages=turn_a, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    manager._queue.flush()
    assert {fact["content"] for fact in manager.get_memory(agent_name="researcher", user_id="alice")["facts"]} == {"User likes Python"}
    assert manager._updater._watermarks == {}
    assert ("thread-1", "alice", "researcher") in manager._updater._extracted_coverages

    manager.clear_memory(agent_name="researcher", user_id="alice")
    assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []

    prompts: list[str] = []

    def invoke_rust(prompt: Any, config: Any = None) -> MagicMock:
        prompts.append(str(prompt))
        return MagicMock(content=_extraction_json("User likes Rust"))

    host_llm.invoke.reset_mock()
    host_llm.invoke.side_effect = invoke_rust
    with patch.object(manager._queue, "_schedule_timer"):
        manager.add(thread_id="thread-1", messages=turn_a + turn_b, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    manager._queue.flush()

    assert host_llm.invoke.call_count == 1, prompts
    assert "Remember that I like Python." not in prompts[0]
    assert "Also remember I like Rust." in prompts[0]
    facts = {fact["content"] for fact in manager.get_memory(agent_name="researcher", user_id="alice")["facts"]}
    assert "User likes Python" not in facts
    assert "User likes Rust" in facts

    host_llm.invoke.reset_mock()
    prompts.clear()
    with patch.object(manager._queue, "_schedule_timer"):
        manager.add_nowait(thread_id="thread-1", messages=turn_a, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    manager._queue.flush()
    host_llm.invoke.assert_not_called()
    facts = {fact["content"] for fact in manager.get_memory(agent_name="researcher", user_id="alice")["facts"]}
    assert "User likes Python" not in facts


def test_persist_then_clear_before_coverage_does_not_restore_via_add_nowait(tmp_path: Path) -> None:
    """Facts persisted, then clear+promote before coverage publish.

    Ordinary re-send skips via the watermark; add_nowait must not restore
    the Python preference because the persist path itself registers exclusion.
    """
    host_llm = MagicMock()
    host_llm.invoke = MagicMock(return_value=MagicMock(content=_extraction_json("User likes Python")))
    manager = _manager(tmp_path, host_llm)
    conversation = [
        HumanMessage(content="Remember that I like Python.", id="human-python"),
        AIMessage(content="I'll keep that preference in mind.", id="ai-python"),
    ]
    original_finalize = manager._updater._finalize_update

    def persist_then_clear(*args: Any, **kwargs: Any) -> Any:
        outcome = original_finalize(*args, **kwargs)
        manager.clear_memory(agent_name="researcher", user_id="alice")
        return outcome

    manager._updater._finalize_update = persist_then_clear  # type: ignore[method-assign]
    manager.add(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    manager._queue.flush()

    assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []
    host_llm.invoke.reset_mock()

    manager.add(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    manager._queue.flush()
    host_llm.invoke.assert_not_called()

    manager.add_nowait(thread_id="thread-1", messages=conversation, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    manager._queue.flush()

    host_llm.invoke.assert_not_called()
    assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []


def test_duplicate_assistant_content_without_ids_does_not_drop_new_user_turn(tmp_path: Path) -> None:
    """No-id content fallback: a repeated assistant reply must not discard the new user turn."""
    remember = "I will remember your preference."
    host_llm = MagicMock()
    host_llm.invoke = MagicMock(return_value=MagicMock(content=_extraction_json("User likes Python")))
    manager = _manager(tmp_path, host_llm)
    pre_clear = [
        HumanMessage(content="I like Python", id=""),
        AIMessage(content=remember, id=""),
    ]
    manager.add(thread_id="thread-1", messages=pre_clear, agent_name="researcher", user_id="alice")
    _stop_debounce(manager)
    manager._queue.flush()
    manager.clear_memory(agent_name="researcher", user_id="alice")

    prompts: list[str] = []

    def invoke_rust(prompt: Any, config: Any = None) -> MagicMock:
        prompts.append(str(prompt))
        return MagicMock(content=_extraction_json("User likes Rust"))

    host_llm.invoke.reset_mock()
    host_llm.invoke.side_effect = invoke_rust
    post_clear = [
        HumanMessage(content="I like Rust", id=""),
        AIMessage(content=remember, id=""),
    ]
    with patch.object(manager._queue, "_schedule_timer"):
        manager.add_nowait(thread_id="thread-1", messages=post_clear, agent_name="researcher", user_id="alice")
    manager._queue.flush()

    assert host_llm.invoke.call_count == 1, prompts
    assert "I like Rust" in prompts[0]
    assert "I like Python" not in prompts[0]
    facts = {fact["content"] for fact in manager.get_memory(agent_name="researcher", user_id="alice")["facts"]}
    assert "User likes Python" not in facts
    assert "User likes Rust" in facts
