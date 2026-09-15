"""Tests for the in-memory watermark (skip already-extracted messages)."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.storage import MemoryStorage
from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater, _message_identity


class _FakeLLM:
    """Returns a canned empty-update response; counts invocations."""

    def __init__(self) -> None:
        self.invoke_count = 0
        self._response = _EmptyResponse()

    def invoke(self, prompt: Any, config: Any = None) -> Any:
        self.invoke_count += 1
        return self._response


class _EmptyResponse:
    content = json.dumps(
        {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "staleFactsToExtend": [],
            "factsToConsolidate": [],
        }
    )
    usage_metadata: dict[str, int] | None = None


class _FakeStorage(MemoryStorage):
    """Minimal in-memory storage stub (load/save) for the save() path."""

    def __init__(self) -> None:
        self.memory: dict[str, Any] = {"version": "2.0", "revision": 0, "user": {}, "history": {}, "facts": []}

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        return json.loads(json.dumps(self.memory))

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        return self.load(agent_name, user_id=user_id)

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None, expected_revision: int | None = None) -> bool:
        self.memory = json.loads(json.dumps(memory_data))
        return True


def _config(**overrides: Any) -> DeerMemConfig:
    base: dict[str, Any] = {}
    base.update(overrides)
    return DeerMemConfig(**base)


def _msgs(*texts: str) -> list[Any]:
    out: list[Any] = []
    for t in texts:
        out.append(HumanMessage(content=t))
        out.append(AIMessage(content=f"reply-{t}"))
    return out


def test_watermark_skips_already_extracted_messages() -> None:
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    messages = _msgs("first")

    updater.update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 1

    # Same messages again -> nothing new since the watermark -> skipped, no LLM call.
    result = updater.update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    assert result is True
    assert llm.invoke_count == 1


def test_watermark_feeds_only_new_messages_on_growth() -> None:
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    messages = _msgs("first")
    updater.update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 1

    # Append a new turn; only the new turn is fed (watermark = prior length).
    messages += _msgs("second")
    updater.update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 2


def test_watermark_is_per_thread() -> None:
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    messages = _msgs("first")
    # Thread t1 extracts; thread t2 has its own watermark (starts at 0).
    updater.update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    updater.update_memory(messages, thread_id="t2", agent_name="a", user_id="u")
    assert llm.invoke_count == 2


def test_watermark_resets_when_conversation_shrinks() -> None:
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    long_msgs = _msgs("first", "second", "third")
    updater.update_memory(long_msgs, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 1
    # A shorter message list (e.g. after summarization) must not get stuck at a
    # watermark past the end; it re-extracts from the start.
    short_msgs = _msgs("only")
    updater.update_memory(short_msgs, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 2


def test_watermark_front_removal_does_not_skip_pending_tail() -> None:
    """Regression: an index watermark skips un-extracted turns when
    summarization removes the conversation front. The watermark is
    content/identity based, so after a front removal it finds the last-extracted
    message at its NEW index and feeds the real pending tail instead of slicing
    past the (now shorter) list.

    Setup: 6 messages; pre-set the watermark to msg[3] so msgs[0..3] are
    "already extracted" and msgs[4..5] are pending. Summarization then removes
    the front pair (msgs[0..1]). The surviving 4-message list must still feed
    the pending pair (msgs[4..5]) -- an index watermark (=4) would slice [4:]
    on a 4-element list and feed nothing, losing them.
    """
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    msgs = _msgs("a", "b", "c")  # [H a, A ra, H b, A rb, H c, A rc]
    updater._watermarks[("t1", "u", "a")] = _message_identity(msgs[3])  # ...A rb extracted
    surviving = msgs[2:]  # summarization removed the front pair
    updater.update_memory(surviving, thread_id="t1", agent_name="a", user_id="u")
    # The pending tail (H c, A rc) was fed -> exactly one extraction.
    assert llm.invoke_count == 1


def test_emergency_flush_bypasses_watermark_and_does_not_regress() -> None:
    """Regression: the emergency (summarization) flush path
    bypasses the watermark -- it extracts its subset in full and does NOT
    advance the conversation watermark (advancing from the subset's own last
    message, which is older than the conversation's latest, would regress it
    and skip the real tail on the next normal feed)."""
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    msgs = _msgs("a", "b")  # [H a, A ra, H b, A rb]
    key = ("t1", "u", "a")
    updater._watermarks[key] = _message_identity(msgs[1])  # ...A ra extracted; H b, A rb pending
    # Emergency flush of the front subset about to be removed.
    updater.update_memory(msgs[:2], thread_id="t1", agent_name="a", user_id="u", bypass_watermark=True)
    assert llm.invoke_count == 1  # subset extracted in full
    # Watermark did not regress to the subset's last message.
    assert updater._watermarks[key] == _message_identity(msgs[1])
    # A subsequent normal feed of the full conversation still extracts the tail.
    updater.update_memory(msgs, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 2


def test_watermark_cache_is_bounded_lru() -> None:
    """The watermark cache is a bounded LRU: over capacity it drops the
    least-recently-used key, and a dropped key re-extracts one batch on the
    next turn for that thread (no loss)."""
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(watermark_max_keys=2), _FakeStorage(), llm)
    msgs = _msgs("first")
    # Three distinct threads fill the cache (cap=2); the least-recently-used
    # key (t1) is evicted.
    updater.update_memory(msgs, thread_id="t1", agent_name="a", user_id="u")
    updater.update_memory(msgs, thread_id="t2", agent_name="a", user_id="u")
    updater.update_memory(msgs, thread_id="t3", agent_name="a", user_id="u")
    assert len(updater._watermarks) == 2
    assert ("t1", "u", "a") not in updater._watermarks  # evicted (LRU)
    # t1's next turn finds no watermark -> re-extracts one batch (not skipped).
    updater.update_memory(msgs, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 4  # t1, t2, t3, then t1 re-extract
