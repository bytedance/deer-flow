"""A pre-compaction snapshot must not re-send messages already extracted.

Each turn's normal update feeds its new messages once and advances the
watermark. When summarization later removes the front of the conversation it
hands those same messages back as an emergency snapshot. The snapshot bypasses
the watermark -- it does not contain the watermark message, so the watermark
cannot place it -- and used to be fed in full: one paid extraction call per
compaction over turns that were already extracted, which can also re-propose
their facts in different words.

The updater now remembers, in process, which messages a successful extraction
consumed, and feeds a snapshot only the rest. Everything not positively known
to be extracted is still fed: loss is the one direction this path cannot take.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core import updater as updater_module
from deerflow.agents.memory.backends.deermem.deermem.core.storage import MemoryStorage
from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater, _message_identity
from deerflow.agents.memory.summarization_hook import memory_flush_hook
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.config.memory_config import MemoryConfig

QUEUE_MODULE = "deerflow.agents.memory.backends.deermem.deermem.core.queue"
HOOK_MODULE = "deerflow.agents.memory.summarization_hook"
SCOPE = {"thread_id": "t1", "agent_name": "a", "user_id": "u"}
KEY = ("t1", "u", "a")
_EMPTY_UPDATE = json.dumps(
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


class _RecordingLLM:
    """Returns an empty update and keeps each prompt, to check what was fed.

    ``outcomes`` overrides successive calls: an exception is raised, a string is
    returned as the response content.
    """

    def __init__(self, *outcomes: Any) -> None:
        self.prompts: list[str] = []
        self._outcomes = list(outcomes)

    @property
    def invoke_count(self) -> int:
        return len(self.prompts)

    def invoke(self, prompt: Any, config: Any = None) -> Any:
        self.prompts.append(str(prompt))
        outcome = self._outcomes.pop(0) if self._outcomes else _EMPTY_UPDATE
        if isinstance(outcome, BaseException):
            raise outcome
        return SimpleNamespace(content=outcome, usage_metadata=None)


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


def _updater(llm: _RecordingLLM, **config: Any) -> MemoryUpdater:
    return MemoryUpdater(DeerMemConfig(**config), _FakeStorage(), llm)


def _turn(name: str) -> list[Any]:
    """One finished turn, with message ids as the graph state assigns them."""
    return [HumanMessage(content=f"question-{name}", id=f"human-{name}"), AIMessage(content=f"answer-{name}", id=f"ai-{name}")]


def test_snapshot_of_already_extracted_messages_makes_no_llm_call() -> None:
    llm = _RecordingLLM()
    updater = _updater(llm)
    conversation = _turn("one") + _turn("two") + _turn("three")
    assert updater.update_memory(conversation, **SCOPE) is True
    assert llm.invoke_count == 1
    watermark = updater._watermarks[KEY]

    # Compaction removes the first two turns and snapshots them first.
    assert updater.update_memory(conversation[:4], **SCOPE, bypass_watermark=True) is True

    assert llm.invoke_count == 1
    assert updater._watermarks[KEY] == watermark


def test_snapshot_feeds_only_the_messages_not_yet_extracted() -> None:
    llm = _RecordingLLM()
    updater = _updater(llm)
    conversation = _turn("one") + _turn("two")
    updater.update_memory(conversation[:2], **SCOPE)

    # Turn two is still waiting in the debounce queue when compaction snapshots both turns.
    assert updater.update_memory(conversation, **SCOPE, bypass_watermark=True) is True

    assert llm.invoke_count == 2
    assert "question-two" in llm.prompts[1]
    assert "answer-two" in llm.prompts[1]
    assert "question-one" not in llm.prompts[1]
    assert "answer-one" not in llm.prompts[1]


def test_a_repeated_snapshot_is_extracted_once() -> None:
    llm = _RecordingLLM()
    updater = _updater(llm)
    snapshot = _turn("one")

    assert updater.update_memory(snapshot, **SCOPE, bypass_watermark=True) is True
    assert updater.update_memory(snapshot, **SCOPE, bypass_watermark=True) is True

    assert llm.invoke_count == 1
    assert KEY not in updater._watermarks, "the emergency path never advances the conversation watermark"


@pytest.mark.parametrize("outcome", [RuntimeError("provider unavailable"), "not a memory update"])
def test_a_failed_extraction_is_not_remembered(outcome: Any) -> None:
    """Only a persisted extraction consumes a message: a failed one must leave
    the snapshot as the last chance to extract it."""
    llm = _RecordingLLM(outcome)
    updater = _updater(llm)
    conversation = _turn("one")
    assert updater.update_memory(conversation, **SCOPE) is False

    assert updater.update_memory(conversation, **SCOPE, bypass_watermark=True) is True

    assert llm.invoke_count == 2
    assert "question-one" in llm.prompts[1]


def test_a_prescreen_skip_is_not_remembered() -> None:
    """A pre-screen skip advances the watermark without an extraction, and the
    emergency path is never judged: the snapshot still extracts those turns."""
    llm = _RecordingLLM()
    updater = _updater(llm, judge=lambda context: SimpleNamespace(skip=not context["bypass_watermark"], payload=None, hints=None))
    conversation = _turn("one")
    assert updater.update_memory(conversation, **SCOPE) is True
    assert llm.invoke_count == 0
    assert updater._watermarks[KEY] == _message_identity(conversation[-1])

    assert updater.update_memory(conversation, **SCOPE, bypass_watermark=True) is True

    assert llm.invoke_count == 1
    assert "question-one" in llm.prompts[0]


def test_messages_without_an_id_are_never_skipped() -> None:
    """Without an id only the text identifies a message, and a later "yes" is
    not the "yes" that was extracted."""
    llm = _RecordingLLM()
    updater = _updater(llm)
    conversation = [HumanMessage(content="yes"), AIMessage(content="Understood.")]
    updater.update_memory(conversation, **SCOPE)

    updater.update_memory(conversation, **SCOPE, bypass_watermark=True)

    assert llm.invoke_count == 2
    assert "yes" in llm.prompts[1]


def test_a_reused_id_with_different_content_is_fed() -> None:
    llm = _RecordingLLM()
    updater = _updater(llm)
    updater.update_memory([HumanMessage(content="I live in Paris.", id="human-1"), AIMessage(content="Noted.", id="ai-1")], **SCOPE)

    edited = [HumanMessage(content="I live in Berlin.", id="human-1"), AIMessage(content="Noted.", id="ai-1")]
    updater.update_memory(edited, **SCOPE, bypass_watermark=True)

    assert llm.invoke_count == 2
    assert "I live in Berlin." in llm.prompts[1]


@pytest.mark.parametrize(
    "other_scope",
    [
        {"thread_id": "t2", "agent_name": "a", "user_id": "u"},
        {"thread_id": "t1", "agent_name": "b", "user_id": "u"},
        {"thread_id": "t1", "agent_name": "a", "user_id": "u2"},
    ],
)
def test_extracted_messages_are_remembered_per_thread_user_and_agent(other_scope: dict[str, str]) -> None:
    llm = _RecordingLLM()
    updater = _updater(llm)
    conversation = _turn("one")
    updater.update_memory(conversation, **SCOPE)

    updater.update_memory(conversation, **other_scope, bypass_watermark=True)

    assert llm.invoke_count == 2


def test_only_the_most_recent_messages_of_a_conversation_are_remembered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forgetting an old message costs one repeated extraction, never a skip."""
    monkeypatch.setattr(updater_module, "_EXTRACTED_MESSAGES_PER_CONVERSATION", 2)
    llm = _RecordingLLM()
    updater = _updater(llm)
    conversation = _turn("one") + _turn("two")
    updater.update_memory(conversation, **SCOPE)
    assert len(updater._extracted_messages[KEY]) == 2

    updater.update_memory(conversation[2:], **SCOPE, bypass_watermark=True)
    assert llm.invoke_count == 1

    updater.update_memory(conversation[:2], **SCOPE, bypass_watermark=True)
    assert llm.invoke_count == 2
    assert "question-one" in llm.prompts[1]


def test_remembered_conversations_are_bounded_like_the_watermark_cache() -> None:
    llm = _RecordingLLM()
    updater = _updater(llm, watermark_max_keys=1)
    first = _turn("one")
    updater.update_memory(first, thread_id="t1", agent_name="a", user_id="u")
    updater.update_memory(_turn("two"), thread_id="t2", agent_name="a", user_id="u")
    assert list(updater._extracted_messages) == [("t2", "u", "a")]

    updater.update_memory(first, thread_id="t1", agent_name="a", user_id="u", bypass_watermark=True)

    assert llm.invoke_count == 3


def test_a_snapshot_that_reads_a_record_keeps_it_from_eviction() -> None:
    """A read is a use, as in the watermark cache: a full cache must not evict
    the record that has just saved a call."""
    llm = _RecordingLLM()
    updater = _updater(llm, watermark_max_keys=2)
    first = _turn("one")
    updater.update_memory(first, thread_id="t1", agent_name="a", user_id="u")
    updater.update_memory(_turn("two"), thread_id="t2", agent_name="a", user_id="u")

    # Skipped in full: nothing is fed, so nothing is recorded again for t1.
    updater.update_memory(first, thread_id="t1", agent_name="a", user_id="u", bypass_watermark=True)
    assert llm.invoke_count == 2
    updater.update_memory(_turn("three"), thread_id="t3", agent_name="a", user_id="u")

    assert list(updater._extracted_messages) == [("t1", "u", "a"), ("t3", "u", "a")]
    updater.update_memory(first, thread_id="t1", agent_name="a", user_id="u", bypass_watermark=True)
    assert llm.invoke_count == 3


@pytest.mark.parametrize(
    ("extracted", "expected"),
    [
        (2, "Memory snapshot: feeding 2 of 4 messages, 2 already extracted (thread=t1)"),
        (4, "Memory snapshot: feeding 0 of 4 messages, 4 already extracted (thread=t1)"),
    ],
)
def test_a_filtered_snapshot_logs_how_much_it_skipped(caplog: pytest.LogCaptureFixture, extracted: int, expected: str) -> None:
    """The saving has to be visible at the default log level, also when only
    part of the snapshot was skipped."""
    updater = _updater(_RecordingLLM())
    conversation = _turn("one") + _turn("two")
    updater.update_memory(conversation[:extracted], **SCOPE)

    with caplog.at_level(logging.INFO, logger=updater_module.logger.name):
        updater.update_memory(conversation, **SCOPE, bypass_watermark=True)

    assert expected in caplog.messages


def test_a_snapshot_that_skips_nothing_logs_no_saving(caplog: pytest.LogCaptureFixture) -> None:
    updater = _updater(_RecordingLLM())

    with caplog.at_level(logging.INFO, logger=updater_module.logger.name):
        updater.update_memory(_turn("one"), **SCOPE, bypass_watermark=True)

    assert not [message for message in caplog.messages if message.startswith("Memory snapshot:")]


PREFERENCE = "My favorite beverage is oolong tea."


def _facts(manager: DeerMem) -> list[dict[str, Any]]:
    return manager.get_memory(agent_name="researcher", user_id="alice")["facts"]


@pytest.mark.parametrize("delete_the_fact_first", [False, True])
def test_compaction_does_not_extract_already_extracted_turns_again(tmp_path: Path, delete_the_fact_first: bool) -> None:
    """End to end through the real hook, queue, updater and storage.

    Turns the after-agent path already extracted are not sent to the extractor
    again when compaction removes them. That second extraction is also what
    restored a fact the user had deleted in between.
    """
    conversations: list[str] = []

    def extract(messages: list, **_kwargs: Any) -> AIMessage:
        conversation = str(messages[-1].content).split("<conversation>", 1)[1].split("</conversation>", 1)[0]
        conversations.append(conversation)
        facts = [{"content": PREFERENCE, "category": "preference", "confidence": 0.95, "scope": "user", "durability": "durable", "authority": "descriptive"}] if PREFERENCE in conversation else []
        return AIMessage(content=json.dumps({"user": {}, "history": {}, "newFacts": facts, "factsToRemove": []}))

    manager = DeerMem(backend_config={"storage_path": str(tmp_path), "retrieval_adapter": "", "host_llm": SimpleNamespace(invoke=extract)})
    summary_model = MagicMock()
    summary_model.with_config.return_value = summary_model
    summary_model.invoke.return_value = SimpleNamespace(text="A short summary omitting specific preferences.")
    middleware = DeerFlowSummarizationMiddleware(
        model=summary_model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
        before_summarization=[memory_flush_hook],
    )
    runtime = SimpleNamespace(context={"thread_id": "target", "user_id": "alice", "agent_name": "researcher"})
    queue = manager._queue
    try:
        with patch(QUEUE_MODULE + ".threading.Timer"), patch(HOOK_MODULE + ".get_memory_config", return_value=MemoryConfig(enabled=True)), patch(HOOK_MODULE + ".get_memory_manager", return_value=manager):
            state = {
                "messages": [
                    HumanMessage(content=PREFERENCE, id="human-0"),
                    AIMessage(content="I have recorded your preference.", id="ai-0"),
                    HumanMessage(content="What is the capital of France?", id="human-1"),
                    AIMessage(content="Paris.", id="ai-1"),
                ]
            }
            # Two finished turns reach the extractor through the after-agent path.
            manager.add("target", state["messages"], agent_name="researcher", user_id="alice")
            assert queue.flush_sync(10)
            assert len(conversations) == 1
            assert [fact["content"] for fact in _facts(manager)] == [PREFERENCE]
            if delete_the_fact_first:
                manager.delete_fact(_facts(manager)[0]["id"], agent_name="researcher", user_id="alice")

            # The next request arrives and compaction removes the extracted front.
            state["messages"].append(HumanMessage(content="And of Italy?", id="human-2"))
            compacted = middleware.compact_state(state, runtime, force=True)
            assert compacted is not None
            assert {message.id for message in compacted.messages_to_summarize} <= {"human-0", "ai-0", "human-1", "ai-1"}
            assert "human-0" in {message.id for message in compacted.messages_to_summarize}
            assert queue.flush_sync(10)

        assert len(conversations) == 1, "the snapshot carried only turns that were already extracted"
        assert [fact["content"] for fact in _facts(manager)] == ([] if delete_the_fact_first else [PREFERENCE])
    finally:
        queue.clear()
        manager._storage.close()
