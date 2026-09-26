"""Tests for interrupt handling in the embedded client's stream contract."""

from collections.abc import Mapping
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.types import Interrupt

from deerflow.agents.middlewares.human_in_the_loop import DISABLE_TOOL_APPROVAL_KEY
from deerflow.client import DeerFlowClient


class TestStreamEventType:
    def test_interrupt_is_a_declared_event_type(self):
        from deerflow.client import StreamEventType

        assert "interrupt" in StreamEventType.__args__


class TestInterruptEventsReachCallers:
    """A parked run must surface as an ``interrupt`` event on the stream.

    ``values`` snapshots already carry ``__interrupt__``, so this needs no
    extra stream mode; the branch simply has to stop discarding the channel.
    """

    @staticmethod
    def _events(monkeypatch, chunk):
        """Drive the real ``values`` branch with a stubbed graph stream.

        Only graph construction is stubbed out; the branch under test, and the
        interrupt projection it calls, are the production ones.
        """
        client = DeerFlowClient.__new__(DeerFlowClient)
        client._agent = SimpleNamespace(stream=lambda *a, **k: iter([("values", chunk)]))
        client._agent_name = None
        client._checkpointer = None
        client._checkpoint_channel_mode = None
        client._environment = {}
        client._model_name = "test-model"
        monkeypatch.setattr(client, "_get_runnable_config", lambda thread_id, **kw: {"configurable": {"thread_id": thread_id}})
        monkeypatch.setattr(client, "_ensure_agent", lambda config, context=None: None)
        monkeypatch.setattr("deerflow.client._stream_with_sandbox_lease_cleanup", lambda items, context: items)
        return list(client._stream_turn("hi", thread_id="t-1"))

    def test_a_parked_run_emits_an_interrupt_event(self, monkeypatch):
        payload = {"action_requests": [{"name": "bash_tool", "args": {"command": "ls"}}]}

        events = self._events(monkeypatch, {"messages": [], "__interrupt__": (Interrupt(value=payload, id="int-1"),)})

        interrupts = [event for event in events if event.type == "interrupt"]
        assert [entry["id"] for entry in interrupts[0].data["interrupts"]] == ["int-1"]
        assert interrupts[0].data["interrupts"][0]["value"] == payload

    def test_an_ordinary_snapshot_emits_no_interrupt_event(self, monkeypatch):
        events = self._events(monkeypatch, {"messages": []})

        assert [event for event in events if event.type == "interrupt"] == []


class TestResumeValidation:
    """``resume`` needs both a parked thread and at least one decision."""

    def test_requires_a_thread_id(self):
        client = DeerFlowClient.__new__(DeerFlowClient)
        with pytest.raises(ValueError, match="thread_id"):
            next(client.resume([{"type": "approve"}], thread_id=""))

    def test_requires_at_least_one_decision(self):
        client = DeerFlowClient.__new__(DeerFlowClient)
        with pytest.raises(ValueError, match="at least one decision"):
            next(client.resume([], thread_id="t-1"))

    def test_forwards_decisions_as_a_resume_command(self, monkeypatch):
        client = DeerFlowClient.__new__(DeerFlowClient)
        seen = {}

        def fake_stream(message, *, thread_id=None, resume=None, **kwargs):
            seen["message"] = message
            seen["thread_id"] = thread_id
            seen["resume"] = resume
            yield from ()

        monkeypatch.setattr(client, "stream", fake_stream)

        list(client.resume([{"type": "approve"}], thread_id="t-1"))

        assert seen["thread_id"] == "t-1"
        assert seen["resume"] == {"decisions": [{"type": "approve"}]}
        # A resume must not append a new HumanMessage.
        assert seen["message"] == ""

    def test_copies_each_decision_mapping(self, monkeypatch):
        """The payload must not alias caller-owned mappings."""
        client = DeerFlowClient.__new__(DeerFlowClient)
        seen = {}

        def fake_stream(message, *, thread_id=None, resume=None, **kwargs):
            seen["resume"] = resume
            yield from ()

        monkeypatch.setattr(client, "stream", fake_stream)

        original = {"type": "approve"}
        list(client.resume([original], thread_id="t-1"))

        forwarded = seen["resume"]["decisions"][0]
        assert forwarded == original
        assert forwarded is not original
        assert isinstance(forwarded, Mapping)


class TestResumeIsNeverDowngraded:
    """A resume must keep approval on, whatever the caller's session sends.

    ``resume()`` forwards ``**kwargs`` verbatim and documents them as "same
    overrides as ``stream()``", so a caller holding ``disable_tool_approval`` at
    session level would otherwise downgrade the one call that must not be.
    Downgrading a resume does not auto-approve it: ``_approval_disabled`` makes
    ``_last_reviewable_ai_message`` return ``None``, so ``after_model`` returns
    before re-entering ``interrupt()``, LangGraph discards the posted decisions
    with no error, and the gated calls stay unanswered on the original
    ``AIMessage`` — the tools node then runs them with their pre-review args,
    turning a ``reject`` into an execution.

    The embedded client is precisely the caller expected to park and answer, and
    the TUI passes this switch at every call site today, so it hits this the
    moment it grows a resume submission. Mirrors
    ``tests/test_tool_approval_client_downgrade.py::test_a_resume_is_not_downgraded``
    for the Gateway.
    """

    @staticmethod
    def _context(monkeypatch, **stream_kwargs):
        """Capture the run context the client hands to the graph.

        Only graph construction is stubbed; the context assembly under test is
        the production one.
        """
        client = DeerFlowClient.__new__(DeerFlowClient)
        seen = {}

        def fake_stream(state, *, config=None, context=None, **kw):
            seen["context"] = context
            return iter(())

        client._agent = SimpleNamespace(stream=fake_stream)
        client._agent_name = None
        client._checkpointer = None
        client._checkpoint_channel_mode = None
        client._environment = {}
        client._model_name = "test-model"
        monkeypatch.setattr(client, "_get_runnable_config", lambda thread_id, **kw: {"configurable": {"thread_id": thread_id}})
        monkeypatch.setattr(client, "_ensure_agent", lambda config, context=None: None)
        monkeypatch.setattr("deerflow.client._stream_with_sandbox_lease_cleanup", lambda items, context: items)
        list(client._stream_turn("hi", thread_id="t-1", **stream_kwargs))
        return seen["context"]

    def test_a_resume_is_not_downgraded(self, monkeypatch):
        context = self._context(monkeypatch, resume={"decisions": [{"type": "reject"}]}, **{DISABLE_TOOL_APPROVAL_KEY: True})

        assert DISABLE_TOOL_APPROVAL_KEY not in context

    def test_a_resume_of_any_shape_is_not_downgraded(self, monkeypatch):
        """The exclusion keys off ``resume``, not off what it carries."""
        context = self._context(monkeypatch, resume="plain-value", **{DISABLE_TOOL_APPROVAL_KEY: True})

        assert DISABLE_TOOL_APPROVAL_KEY not in context

    def test_an_ordinary_run_is_still_downgraded(self, monkeypatch):
        """The downgrade itself must survive — a TUI run has no approval surface."""
        context = self._context(monkeypatch, **{DISABLE_TOOL_APPROVAL_KEY: True})

        assert context[DISABLE_TOOL_APPROVAL_KEY] is True

    def test_an_ordinary_run_without_the_switch_keeps_approval(self, monkeypatch):
        context = self._context(monkeypatch)

        assert DISABLE_TOOL_APPROVAL_KEY not in context


class TestResumeDoesNotReplayThePriorTurn:
    """A resume must not re-emit the checkpoint it resumes from.

    ``_stream_turn`` normally separates "this turn" from history by finding the
    ``HumanMessage`` carrying this call's ``run_id``. A resume passes
    ``Command(resume=...)`` and deliberately appends no ``HumanMessage``, so that
    marker never appears: without a checkpoint-seeded baseline the whole prior
    turn is re-emitted as new deltas and its ``usage_metadata`` is added to this
    resume's cumulative total.

    Mirrors ``test_client.py::test_resumed_stream_does_not_reemit_history_or_count_old_usage``,
    which covers the ordinary-turn path that *does* have the marker.
    """

    OLD_USAGE = {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}
    NEW_USAGE = {"input_tokens": 11, "output_tokens": 4, "total_tokens": 15}

    @staticmethod
    def _prior_turn():
        """One completed turn, as it sits in the parked checkpoint."""
        return [
            HumanMessage(content="first turn", id="h-old", additional_kwargs={"run_id": "old-run"}),
            AIMessage(content="old answer", id="ai-old", usage_metadata=TestResumeDoesNotReplayThePriorTurn.OLD_USAGE),
            ToolMessage(content="old result", id="tool-old", name="ls", tool_call_id="call-old"),
        ]

    @staticmethod
    def _gated_call(args):
        return AIMessage(content="", id="ai-gated", tool_calls=[{"name": "bash_tool", "args": args, "id": "call-gated"}])

    def _events(self, monkeypatch, chunks, *, checkpoint_messages):
        """Drive the real ``values``/``messages`` handling of a resume."""
        client = DeerFlowClient.__new__(DeerFlowClient)
        client._agent = SimpleNamespace(stream=lambda *a, **k: iter(chunks))
        client._agent_name = None
        client._checkpointer = None
        client._checkpoint_channel_mode = None
        client._environment = {}
        client._model_name = "test-model"
        monkeypatch.setattr(client, "_get_runnable_config", lambda thread_id, **kw: {"configurable": {"thread_id": thread_id}})
        monkeypatch.setattr(client, "_ensure_agent", lambda config, context=None: None)
        monkeypatch.setattr("deerflow.client._stream_with_sandbox_lease_cleanup", lambda items, context: items)
        monkeypatch.setattr(client, "_resume_baseline_messages", lambda checkpointer, checkpoint_config: checkpoint_messages)
        return list(client._stream_turn("", thread_id="t-1", resume={"decisions": [{"type": "approve"}]}))

    def test_the_prior_turn_is_not_re_emitted(self, monkeypatch):
        prior = self._prior_turn()
        gated = self._gated_call({"command": "ls"})
        after = ToolMessage(content="new result", id="tool-new", name="bash_tool", tool_call_id="call-gated")

        events = self._events(
            monkeypatch,
            [
                ("values", {"messages": [*prior, gated]}),
                ("values", {"messages": [*prior, gated, after]}),
            ],
            checkpoint_messages=[*prior, gated],
        )

        emitted = {event.data.get("id") for event in events if event.type == "messages-tuple"}
        assert "ai-old" not in emitted
        assert "tool-old" not in emitted
        assert "tool-new" in emitted

    def test_the_prior_turns_usage_is_not_counted_again(self, monkeypatch):
        prior = self._prior_turn()
        gated = self._gated_call({"command": "ls"})
        new_ai = AIMessage(content="done", id="ai-new", usage_metadata=self.NEW_USAGE)

        events = self._events(
            monkeypatch,
            [
                ("values", {"messages": [*prior, gated]}),
                ("messages", (AIMessageChunk(content="done", id="ai-new", usage_metadata=self.NEW_USAGE), {})),
                ("values", {"messages": [*prior, gated, new_ai]}),
            ],
            checkpoint_messages=[*prior, gated],
        )

        assert events[-1].data["usage"] == self.NEW_USAGE

    def test_an_edited_gated_call_still_reaches_the_client(self, monkeypatch):
        """The gated message is rewritten under its own id, so it is not history.

        ``edit`` keeps the call id and changes only the args. The baseline skip
        is a ``continue`` placed *before* the "same id, different object" branch,
        and that branch only re-emits appended *text* anyway — so seeding the
        gated message's id would silently drop the human's edit.
        """
        prior = self._prior_turn()
        edited = self._gated_call({"command": "ls -la"})

        events = self._events(
            monkeypatch,
            [("values", {"messages": [*prior, edited]})],
            checkpoint_messages=[*prior, self._gated_call({"command": "ls"})],
        )

        tool_calls = [call for event in events if event.type == "messages-tuple" for call in (event.data.get("tool_calls") or ())]
        assert [call["args"] for call in tool_calls] == [{"command": "ls -la"}]

    def test_the_re_emitted_call_keeps_its_ids_so_consumers_can_merge(self, monkeypatch):
        """Re-emission is safe only because the ids are stable.

        Consumers merge by id rather than appending — the TUI reducer matches an
        assistant row by message id and a tool card by ``tool_call_id``, both
        scanning the whole transcript, precisely because this client's dedup is
        per-turn and re-emits across turns. An edit must therefore arrive under
        the *same* ids as the call the human reviewed, or it renders as a second
        tool card instead of updating the first.
        """
        prior = self._prior_turn()

        events = self._events(
            monkeypatch,
            [("values", {"messages": [*prior, self._gated_call({"command": "ls -la"})]})],
            checkpoint_messages=[*prior, self._gated_call({"command": "ls"})],
        )

        ai_events = [event.data for event in events if event.type == "messages-tuple" and event.data.get("type") == "ai"]
        assert [event["id"] for event in ai_events] == ["ai-gated"]
        assert [call["id"] for event in ai_events for call in (event.get("tool_calls") or ())] == ["call-gated"]

    def test_the_gated_calls_own_usage_is_not_counted_again(self, monkeypatch):
        """Held out of history, but not out of the usage ledger.

        The gated message's ``usage_metadata`` was spent on the turn that parked
        and counted there. Re-emitting the message is harmless — clients merge by
        id — but re-counting its tokens would bill this resume for the park's
        model call.
        """
        prior = self._prior_turn()
        gated = self._gated_call({"command": "ls"})
        gated.usage_metadata = self.OLD_USAGE

        events = self._events(
            monkeypatch,
            [
                ("values", {"messages": [*prior, gated]}),
                ("values", {"messages": [*prior, gated, ToolMessage(content="out", id="tool-new", name="bash_tool", tool_call_id="call-gated")]}),
            ],
            checkpoint_messages=[*prior, gated],
        )

        assert events[-1].data["usage"] == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        # Still emitted, so an edit under this id can reach the client.
        assert "ai-gated" in {event.data.get("id") for event in events if event.type == "messages-tuple"}

    def test_an_ordinary_turn_still_uses_its_run_id_marker(self, monkeypatch):
        """The non-resume path must keep working off the ``HumanMessage`` marker."""
        client = DeerFlowClient.__new__(DeerFlowClient)
        prior = self._prior_turn()
        new_ai = AIMessage(content="answer", id="ai-new", usage_metadata=self.NEW_USAGE)
        seen = {}

        def stream(state, *, context=None, **kw):
            current = HumanMessage(content="second", id="h-current", additional_kwargs={"run_id": context["run_id"]})
            seen["baseline_called"] = False
            return iter([("values", {"messages": [*prior, current, new_ai]})])

        client._agent = SimpleNamespace(stream=stream)
        client._agent_name = None
        client._checkpointer = None
        client._checkpoint_channel_mode = None
        client._environment = {}
        client._model_name = "test-model"
        monkeypatch.setattr(client, "_get_runnable_config", lambda thread_id, **kw: {"configurable": {"thread_id": thread_id}})
        monkeypatch.setattr(client, "_ensure_agent", lambda config, context=None: None)
        monkeypatch.setattr("deerflow.client._stream_with_sandbox_lease_cleanup", lambda items, context: items)

        events = list(client._stream_turn("second", thread_id="t-1"))

        emitted = {event.data.get("id") for event in events if event.type == "messages-tuple"}
        assert emitted == {"ai-new"}
        assert events[-1].data["usage"] == self.NEW_USAGE
