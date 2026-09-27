"""Compaction destroys the mapping it is observed by.

Summarization replaces N messages with one summary. After the fact, only the
summary survives, so 'which messages became this summary' is not reconstructible
from state — it has to be emitted at the moment of the transform.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from deerflow_extension_api import CompactionEvent, canonical_hash


def test_event_records_both_ends_of_the_transform():
    event = CompactionEvent(
        transform_kind="summarization",
        transform_version="1",
        source_content_hashes=("h1", "h2"),
        output_content_hash="h3",
        compacted_message_count=2,
        kept_message_count=4,
    )
    assert event.source_content_hashes == ("h1", "h2")
    assert event.output_content_hash == "h3"


def test_source_hashes_are_a_tuple_so_the_event_cannot_be_mutated_after_emission():
    event = CompactionEvent(
        transform_kind="summarization",
        transform_version="1",
        source_content_hashes=("h1",),
        output_content_hash="h3",
        compacted_message_count=1,
        kept_message_count=1,
    )
    with pytest.raises(AttributeError):
        event.output_content_hash = "other"


_UNOBSERVED = object()


def _observed_extensions(observer=None):
    """A real ``LoadedExtensions`` carrying one compaction observer.

    ``replace`` on the ambient set rather than a hand-built stub: the
    middleware reads other fields off ``_extensions`` too (the system-model
    call path), so a namespace carrying only the observer tuple would pass
    these tests while diverging from what the middleware is handed in
    production.
    """
    from dataclasses import replace

    from deerflow.extensions import get_agent_build_extensions

    return replace(get_agent_build_extensions(), context_compaction_observers=(("test-source", observer or (lambda event, context=None: None)),))


def test_source_hashes_are_computed_on_content_directly_not_a_stringified_copy():
    """Regression: hashing ``str(message.content)`` would defeat canonical_hash's
    key-order normalization for multimodal (``list[dict]``) content, which
    ``view_image_middleware`` and other producers routinely inject. Two
    logically identical messages whose dict content differs only in key
    insertion order must hash the same.
    """
    from langchain_core.messages import HumanMessage

    from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware

    a = HumanMessage(content=[{"type": "text", "text": "hi"}, {"b": 1, "a": 2}])
    b = HumanMessage(content=[{"type": "text", "text": "hi"}, {"a": 2, "b": 1}])

    middleware = DeerFlowSummarizationMiddleware(model=MagicMock(), extensions=_observed_extensions())
    hashes = middleware._freeze_compaction_sources([a, b])
    assert hashes[0] == hashes[1]
    assert hashes[0] == canonical_hash(a.content)
    # str() on a dict renders insertion order, so the pre-stringified form
    # this guards against would not have matched.
    assert str(a.content) != str(b.content)


# --- Driving a real compaction --------------------------------------------
#
# Mirrors tests/test_summarization_middleware.py's `_messages` / `_middleware` /
# `_runtime` fixture helpers rather than inventing a second way to drive the
# middleware: a static model, `token_counter=len`, and a runtime carrying a
# plain `context` mapping.


def _messages() -> list:
    from langchain_core.messages import AIMessage, HumanMessage

    return [
        HumanMessage(content="user-1"),
        AIMessage(content="assistant-1"),
        HumanMessage(content="user-2"),
        AIMessage(content="assistant-2"),
    ]


def _runtime(thread_id: str | None = "thread-1") -> SimpleNamespace:
    context = {}
    if thread_id is not None:
        context["thread_id"] = thread_id
    return SimpleNamespace(context=context)


def _middleware(*, trigger=("messages", 4), keep=("messages", 2), extensions=_UNOBSERVED):
    from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware

    model = MagicMock()
    model.invoke.return_value = SimpleNamespace(text="compressed summary")
    model.ainvoke = AsyncMock(return_value=SimpleNamespace(text="compressed summary"))
    model.with_config.return_value = model
    return DeerFlowSummarizationMiddleware(
        model=model,
        trigger=trigger,
        keep=keep,
        token_counter=len,
        extensions=_observed_extensions() if extensions is _UNOBSERVED else extensions,
    )


class TestSummarizationEmitsTheEvent:
    @pytest.mark.asyncio
    async def test_a_compaction_notifies_observers_once(self, monkeypatch):
        from deerflow.agents.middlewares import summarization_middleware

        events = []
        monkeypatch.setattr(
            summarization_middleware,
            "notify_context_compacted",
            lambda event, extensions=None: events.append(event),
        )
        middleware = _middleware()

        result = await middleware.abefore_model({"messages": _messages()}, _runtime())

        assert result is not None
        assert len(events) == 1
        event = events[0]
        assert event.transform_kind == "summarization"
        assert event.compacted_message_count == 2
        assert event.kept_message_count == 2
        assert event.source_content_hashes == (
            canonical_hash("user-1"),
            canonical_hash("assistant-1"),
        )
        assert event.output_content_hash == canonical_hash("compressed summary")

    @pytest.mark.asyncio
    async def test_no_event_is_emitted_when_the_trigger_does_not_fire(self, monkeypatch):
        from deerflow.agents.middlewares import summarization_middleware

        events = []
        monkeypatch.setattr(
            summarization_middleware,
            "notify_context_compacted",
            lambda event, extensions=None: events.append(event),
        )
        # A trigger threshold far above the message count never fires, so
        # compaction never runs and the record half is never reached.
        middleware = _middleware(trigger=("messages", 100))

        result = await middleware.abefore_model({"messages": _messages()}, _runtime())

        assert result is None
        assert events == []


class TestAnInstallWithNoObserverPaysNothing:
    """Hashing the sources is an O(context-size) canonical-JSON pass.

    Every install runs this middleware; almost none of them register a
    compaction observer. The check cannot live in ``notify_context_compacted``
    — by the time it is called the hashing has already happened — so the freeze
    site has to make it itself.
    """

    def test_the_sources_are_not_hashed_when_nothing_observes(self):
        from dataclasses import replace

        from deerflow.extensions import get_agent_build_extensions

        unobserved = replace(get_agent_build_extensions(), context_compaction_observers=())
        middleware = _middleware(extensions=unobserved)

        assert middleware._freeze_compaction_sources(_messages()) == ()

    def test_the_sources_are_hashed_when_an_observer_is_registered(self):
        middleware = _middleware(extensions=_observed_extensions())

        assert middleware._freeze_compaction_sources(_messages()) == tuple(canonical_hash(m.content) for m in _messages())

    @pytest.mark.asyncio
    async def test_the_compaction_itself_still_happens_unobserved(self, monkeypatch):
        """The skip must cost the run nothing but the hashes."""
        from dataclasses import replace

        from deerflow.agents.middlewares import summarization_middleware
        from deerflow.extensions import get_agent_build_extensions

        events = []
        monkeypatch.setattr(summarization_middleware, "notify_context_compacted", lambda event, extensions=None: events.append(event))
        unobserved = replace(get_agent_build_extensions(), context_compaction_observers=())

        result = await _middleware(extensions=unobserved).abefore_model({"messages": _messages()}, _runtime())

        assert result is not None, "compaction must still run; only the observation bookkeeping is skipped"
        # The middleware still calls notify (which would itself no-op on the
        # empty observer tuple); what it must not do is compute the hashes.
        assert [e.source_content_hashes for e in events] == [()]
