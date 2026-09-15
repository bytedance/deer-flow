"""Tests for the in-memory watermark (skip already-extracted messages)."""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.storage import MemoryStorage
from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater, _message_identity


class _FakeLLM:
    """Returns a canned empty-update response; counts invocations and records
    each call's prompt so tests can assert *what* was fed, not just how many
    times ``invoke`` ran (a call-count-only assertion cannot tell "fed the
    correct 2-message tail" apart from "fed all 6 messages again")."""

    def __init__(self) -> None:
        self.invoke_count = 0
        self.prompts: list[Any] = []
        self._response = _EmptyResponse()

    def invoke(self, prompt: Any, config: Any = None) -> Any:
        self.invoke_count += 1
        self.prompts.append(prompt)
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

    def peek_clear_generation(self, agent_name: str | None = None, *, user_id: str | None = None) -> tuple[int, int]:
        return (0, 0)


class _GenerationStorage(_FakeStorage):
    """Tracks a clear-generation fence so tests can land a clear after persist."""

    def __init__(self) -> None:
        super().__init__()
        self._generation = (0, 0)

    def peek_clear_generation(self, agent_name: str | None = None, *, user_id: str | None = None) -> tuple[int, int]:
        return self._generation

    def simulate_clear(self) -> None:
        self.memory["facts"] = []
        self._generation = (self._generation[0], self._generation[1] + 1)


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
    # Pre-set via ``_watermark_set`` (not a raw dict write): the internal value
    # is ``(sequence, identity)``, not a bare identity -- a raw write here
    # would silently break the lookup (``_watermark_get`` indexes ``[1]``) and
    # make every assertion below pass for the wrong reason (over-extraction,
    # not the targeted partial feed this test exists to check).
    updater._watermark_set(("t1", "u", "a"), _message_identity(msgs[3]), sequence=None)  # ...A rb extracted
    surviving = msgs[2:]  # summarization removed the front pair
    updater.update_memory(surviving, thread_id="t1", agent_name="a", user_id="u")
    # The pending tail (H c, A rc) was fed -> exactly one extraction, and the
    # fed content is exactly that tail: the already-extracted "b" turn must be
    # absent. A call-count-only assertion cannot tell this apart from
    # re-feeding the whole surviving list (which also invokes the LLM once).
    assert llm.invoke_count == 1
    fed = str(llm.prompts[-1])
    assert "reply-b" not in fed, "already-extracted turn 'b' must not be re-fed"
    assert "reply-c" in fed, "pending turn 'c' must be fed"


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
    # ``_watermark_set``, not a raw dict write -- see the front-removal test above.
    updater._watermark_set(key, _message_identity(msgs[1]), sequence=None)  # ...A ra extracted; H b, A rb pending
    # Emergency flush of the front subset about to be removed.
    updater.update_memory(msgs[:2], thread_id="t1", agent_name="a", user_id="u", bypass_watermark=True)
    assert llm.invoke_count == 1  # subset extracted in full
    # Watermark did not regress to the subset's last message.
    assert updater._watermarks[key] == (None, _message_identity(msgs[1]))
    # A subsequent normal feed of the full conversation still extracts the tail,
    # and only the tail: the "a" turn must not be re-fed.
    updater.update_memory(msgs, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 2
    fed = str(llm.prompts[-1])
    assert "reply-a" not in fed, "already-extracted turn 'a' must not be re-fed"
    assert "reply-b" in fed, "pending turn 'b' must be fed"


def test_emergency_flush_of_cleared_prefix_does_not_restore_when_boundary_absent() -> None:
    """Summarization keeps the recent tail and only submits the older prefix.

    After A+B is extracted and cleared, exclusion must cover the whole prefix,
    not just the tail identity B. Flushing only A (B is not in the payload)
    must not treat the missing tail as "no boundary" and re-feed A.
    """
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    msgs = _msgs("a", "b")

    updater.update_memory(msgs, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 1
    updater.promote_clear_exclusions(user_id="u", agent_name="a")

    llm.invoke_count = 0
    llm.prompts.clear()
    result = updater.update_memory(msgs[:2], thread_id="t1", agent_name="a", user_id="u", bypass_watermark=True)
    assert result is True
    assert llm.invoke_count == 0


def test_cleared_queued_prefix_is_excluded_from_later_emergency_flush() -> None:
    """Same prefix-only flush after the snapshot was only sitting in the queue."""
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    msgs = _msgs("a", "b")

    updater.mark_feed_consumed(msgs, thread_id="t1", user_id="u", agent_name="a", bypass_watermark=False, sequence=1)
    result = updater.update_memory(msgs[:2], thread_id="t1", agent_name="a", user_id="u", bypass_watermark=True)
    assert result is True
    assert llm.invoke_count == 0


def test_later_summary_subset_does_not_retreat_clear_exclusion_coverage() -> None:
    """A later emergency subset must not shrink exclusion from A+B down to A.

    Call-arrival sequence is later for the summarization flush, but its
    messages are an older prefix. Union coverage, do not replace the tail.
    """
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    msgs = _msgs("a", "b")

    updater.update_memory(msgs, thread_id="t1", agent_name="a", user_id="u", sequence=1)
    updater.mark_feed_consumed(msgs, thread_id="t1", user_id="u", agent_name="a", bypass_watermark=False, sequence=1)
    updater.mark_feed_consumed(msgs[:2], thread_id="t1", user_id="u", agent_name="a", bypass_watermark=True, sequence=2)
    updater.promote_clear_exclusions(user_id="u", agent_name="a")

    llm.invoke_count = 0
    llm.prompts.clear()
    updater.update_memory(msgs, thread_id="t1", agent_name="a", user_id="u", bypass_watermark=True, sequence=3)
    assert llm.invoke_count == 0


def test_clear_exclusion_still_feeds_messages_outside_cleared_coverage() -> None:
    """Missing the old tail must not drop a genuinely new conversation."""
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    msgs = _msgs("a", "b")
    updater.update_memory(msgs, thread_id="t1", agent_name="a", user_id="u")
    updater.promote_clear_exclusions(user_id="u", agent_name="a")

    llm.invoke_count = 0
    llm.prompts.clear()
    updater.update_memory(_msgs("only-new"), thread_id="t1", agent_name="a", user_id="u", bypass_watermark=True)
    assert llm.invoke_count == 1
    assert "reply-only-new" in str(llm.prompts[-1])
    assert "reply-a" not in str(llm.prompts[-1])


def test_persist_then_clear_before_coverage_registers_exclusion() -> None:
    """A clear that lands after persist, before coverage publish, must still
    exclude the feed. Ordinary re-send skips via the watermark; emergency
    flush must not restore the same turns (promote scanned too early).
    """
    llm = _FakeLLM()
    storage = _GenerationStorage()
    updater = MemoryUpdater(_config(), storage, llm)
    msgs = [
        HumanMessage(content="I like Python", id="h-python"),
        AIMessage(content="I'll remember that.", id="a-python"),
    ]
    original_finalize = updater._finalize_update

    def persist_then_clear(*args: Any, **kwargs: Any) -> Any:
        outcome = original_finalize(*args, **kwargs)
        storage.simulate_clear()
        updater.promote_clear_exclusions(user_id="u", agent_name="a")
        return outcome

    updater._finalize_update = persist_then_clear  # type: ignore[method-assign]
    updater.update_memory(msgs, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 1

    llm.invoke_count = 0
    llm.prompts.clear()
    assert updater.update_memory(msgs, thread_id="t1", agent_name="a", user_id="u") is True
    assert llm.invoke_count == 0

    assert updater.update_memory(msgs, thread_id="t1", agent_name="a", user_id="u", bypass_watermark=True) is True
    assert llm.invoke_count == 0


def test_drop_excluded_does_not_cut_prefix_on_content_identity() -> None:
    """A repeated assistant wording is not a position boundary when there is no id."""
    remember = "I will remember your preference."
    excluded = frozenset(
        {
            ("content", "human", "I like Python"),
            ("content", "ai", remember),
        }
    )
    messages = [
        HumanMessage(content="I like Rust", id=""),
        AIMessage(content=remember, id=""),
    ]
    remaining = MemoryUpdater._drop_excluded_identities(excluded, messages)
    assert [msg.content for msg in remaining] == ["I like Rust"]


def test_drop_excluded_still_cuts_prefix_at_stable_message_id() -> None:
    """A unique message id remains a reliable prefix boundary (watermark-tail promote)."""
    excluded = frozenset({("id", "old-ai")})
    messages = [
        HumanMessage(content="I like Python", id="old-human"),
        AIMessage(content="I'll remember that.", id="old-ai"),
        HumanMessage(content="I like Rust", id="new-human"),
    ]
    remaining = MemoryUpdater._drop_excluded_identities(excluded, messages)
    assert [msg.id for msg in remaining] == ["new-human"]


def test_duplicate_assistant_content_without_ids_still_feeds_new_user_turn() -> None:
    """Emergency flush after clear must keep a new user turn when only the
    assistant wording collides with an excluded no-id message.
    """
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    remember = "I will remember your preference."
    pre_clear = [
        HumanMessage(content="I like Python", id=""),
        AIMessage(content=remember, id=""),
    ]
    updater.update_memory(pre_clear, thread_id="t1", agent_name="a", user_id="u")
    updater.promote_clear_exclusions(user_id="u", agent_name="a")

    llm.invoke_count = 0
    llm.prompts.clear()
    post_clear = [
        HumanMessage(content="I like Rust", id=""),
        AIMessage(content=remember, id=""),
    ]
    updater.update_memory(post_clear, thread_id="t1", agent_name="a", user_id="u", bypass_watermark=True)
    assert llm.invoke_count == 1
    fed = str(llm.prompts[-1])
    assert "I like Rust" in fed
    assert "I like Python" not in fed


def test_emergency_only_extract_then_later_clear_excludes_regular_feed() -> None:
    """Bypass must publish extracted coverage without advancing the watermark.

    After an emergency-only persist, a later clear has no watermark to scan.
    Promotion must still copy that coverage so a regular re-send cannot
    restore the already-extracted, then-cleared turns.
    """
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    msgs = [
        HumanMessage(content="I like Python", id="h-python"),
        AIMessage(content="I'll remember that.", id="a-python"),
    ]
    extra = [
        HumanMessage(content="I like Rust", id="h-rust"),
        AIMessage(content="Noted about Rust.", id="a-rust"),
    ]
    key = ("t1", "u", "a")

    updater.update_memory(msgs, thread_id="t1", agent_name="a", user_id="u", bypass_watermark=True)
    assert llm.invoke_count == 1
    assert key not in updater._watermarks
    assert updater._extracted_coverages.get(key) == frozenset(
        {
            _message_identity(msgs[0]),
            _message_identity(msgs[1]),
        }
    )

    updater.promote_clear_exclusions(user_id="u", agent_name="a")

    llm.invoke_count = 0
    llm.prompts.clear()
    result = updater.update_memory(msgs + extra, thread_id="t1", agent_name="a", user_id="u")
    assert result is True
    assert llm.invoke_count == 1
    fed = str(llm.prompts[-1])
    assert "I like Python" not in fed
    assert "I like Rust" in fed

    llm.invoke_count = 0
    llm.prompts.clear()
    assert updater.update_memory(msgs, thread_id="t1", agent_name="a", user_id="u", bypass_watermark=True) is True
    assert llm.invoke_count == 0


def test_emergency_only_coverage_cache_is_bounded_lru() -> None:
    """Coverage published by bypass still shares the watermark key cap."""
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(watermark_max_keys=2), _FakeStorage(), llm)
    msgs = [
        HumanMessage(content="I like Python", id="h-python"),
        AIMessage(content="I'll remember that.", id="a-python"),
    ]
    for thread_id in ("t1", "t2", "t3"):
        updater.update_memory(msgs, thread_id=thread_id, agent_name="a", user_id="u", bypass_watermark=True)
    assert ("t1", "u", "a") not in updater._extracted_coverages
    assert ("t2", "u", "a") in updater._extracted_coverages
    assert ("t3", "u", "a") in updater._extracted_coverages
    assert not updater._watermarks


def test_emergency_flush_honors_clear_exclusion_not_extraction_watermark() -> None:
    """Emergency flush may re-feed already-extracted turns, but not turns
    consumed because a clear landed. The two boundaries are independent:
    bypass skips the extraction watermark and must still drop the
    clear-exclusion coverage set.

    Unique message ids are required: watermark-tail promote uses the tail as
    a prefix boundary only when that identity is a stable id.
    """
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    msgs = [
        HumanMessage(content="a", id="h-a"),
        AIMessage(content="reply-a", id="a-a"),
        HumanMessage(content="b", id="h-b"),
        AIMessage(content="reply-b", id="a-b"),
    ]
    key = ("t1", "u", "a")
    updater._watermark_set(key, _message_identity(msgs[1]), sequence=1)
    updater.promote_clear_exclusions(user_id="u", agent_name="a")

    result = updater.update_memory(msgs[:2], thread_id="t1", agent_name="a", user_id="u", bypass_watermark=True)
    assert result is True
    assert llm.invoke_count == 0
    assert updater._watermarks[key] == (1, _message_identity(msgs[1]))

    updater.update_memory(msgs, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 1
    fed = str(llm.prompts[-1])
    assert "reply-a" not in fed, "cleared turn 'a' must not be re-fed"
    assert "reply-b" in fed, "post-clear turn 'b' must still be fed"


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


class _BlockingOrderedDict(OrderedDict):
    """An ``OrderedDict`` whose *next* ``get()`` call captures its result and
    then blocks before returning it -- simulating a thread that has already
    read a (possibly stale) value and is merely delayed before acting on it.

    Used to reproduce a check-then-act race in ``_watermark_set``: without a
    lock around the whole read-check-write, a delayed reader can still act on
    a value it read before a concurrent writer's update landed.
    """

    def __init__(self) -> None:
        super().__init__()
        self.block_on_next_get = False
        self.blocked = threading.Event()
        self.release = threading.Event()

    def get(self, key: Any, default: Any = None) -> Any:  # noqa: D102
        if self.block_on_next_get:
            self.block_on_next_get = False
            value = OrderedDict.get(self, key, default)
            self.blocked.set()
            assert self.release.wait(timeout=5), "test did not release the blocked watermark read in time"
            return value
        return OrderedDict.get(self, key, default)


def test_watermark_set_check_and_write_is_atomic_across_threads() -> None:
    """#5125 review (2026-09-12 follow-up): ``_watermark_set``'s "is the
    incoming sequence stale?" check and its write must be one atomic
    operation, not a separate read then a separate write.

    Without a lock around both, this interleaving corrupts the result even
    though the sequence *values* are individually correct:
      1. Thread A (sequence=1) reads "no watermark yet" and is delayed before
         writing (e.g. descheduled, or -- in production -- exactly the
         generation-fenced drop this whole ``sequence`` mechanism defends).
      2. Thread B (sequence=2, the real later work) reads the same "nothing
         yet", passes its own check, and writes ``(2, "B")``.
      3. Thread A resumes and, holding only its stale "nothing yet" read,
         still writes ``(1, "A")`` -- clobbering B's newer, correct write.
    A single lock spanning the read and the write serializes A entirely
    before B's ``get()`` can observe anything, so B's write always lands last
    and wins (as it should, since it has the higher sequence).
    """
    updater = MemoryUpdater(_config(), _FakeStorage(), _FakeLLM())
    key = ("t1", "u", "a")
    blocking_dict = _BlockingOrderedDict()
    updater._watermarks = blocking_dict
    blocking_dict.block_on_next_get = True

    def write_a() -> None:
        updater._watermark_set(key, ("id", "A"), sequence=1)

    thread_a = threading.Thread(target=write_a)
    thread_a.start()
    assert blocking_dict.blocked.wait(timeout=5), "thread A never reached the blocked read"

    # Thread B calls _watermark_set for the same key while A is delayed. If
    # _watermark_set is properly locked, B blocks acquiring that lock (A is
    # still "inside" the critical section, merely delayed) and cannot make
    # progress until A finishes and releases it.
    thread_b = threading.Thread(target=lambda: updater._watermark_set(key, ("id", "B"), sequence=2))
    thread_b.start()

    blocking_dict.release.set()
    thread_a.join(timeout=5)
    thread_b.join(timeout=5)
    assert not thread_a.is_alive()
    assert not thread_b.is_alive()

    # B's higher-sequence write must win, regardless of A's delay.
    assert updater._watermarks[key] == (2, ("id", "B"))
