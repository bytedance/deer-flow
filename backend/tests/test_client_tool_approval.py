"""Tests for interrupt handling in the embedded client's stream contract."""

from collections.abc import Mapping
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.types import Interrupt

from deerflow.agents.middlewares.human_in_the_loop import DISABLE_TOOL_APPROVAL_KEY
from deerflow.client import DeerFlowClient, StreamEvent, ToolApprovalRequired


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


class TestChatDoesNotSwallowAPark:
    """``chat()`` must not present a parked run as a finished answer.

    It accumulates AI ``messages-tuple`` text and ignores every other event, so
    a park returned partial text — usually ``""`` on a tool-only turn — while the
    checkpoint sat waiting for ``resume()``, with nothing telling the caller so.
    ``stream()`` callers already see the ``interrupt`` event; the convenience
    wrapper has no channel for it, hence the exception.
    """

    @staticmethod
    def _client(monkeypatch, events):
        client = DeerFlowClient.__new__(DeerFlowClient)
        monkeypatch.setattr(client, "stream", lambda *a, **k: iter(events))
        return client

    PAYLOAD = {"action_requests": [{"name": "bash_tool", "args": {"command": "ls"}}]}

    def _parked_events(self, *, text: str = ""):
        events = []
        if text:
            events.append(StreamEvent(type="messages-tuple", data={"type": "ai", "id": "ai-1", "content": text}))
        events.append(StreamEvent(type="interrupt", data={"interrupts": [{"id": "int-1", "value": self.PAYLOAD}]}))
        return events

    def test_a_tool_only_park_raises_instead_of_returning_empty_text(self, monkeypatch):
        client = self._client(monkeypatch, self._parked_events())

        with pytest.raises(ToolApprovalRequired):
            client.chat("run ls", thread_id="t-1")

    def test_a_park_after_partial_text_still_raises(self, monkeypatch):
        """Partial text is exactly the case that looked like a complete answer."""
        client = self._client(monkeypatch, self._parked_events(text="Let me check"))

        with pytest.raises(ToolApprovalRequired):
            client.chat("run ls", thread_id="t-1")

    def test_the_error_carries_what_resume_needs(self, monkeypatch):
        client = self._client(monkeypatch, self._parked_events(text="Let me check"))

        with pytest.raises(ToolApprovalRequired) as excinfo:
            client.chat("run ls", thread_id="t-1")

        error = excinfo.value
        assert error.thread_id == "t-1"
        assert [entry["id"] for entry in error.interrupts] == ["int-1"]
        assert error.interrupts[0]["value"] == self.PAYLOAD
        # The text produced before the park is not thrown away.
        assert error.partial_text == "Let me check"

    def test_the_error_names_resume_so_the_caller_knows_the_next_step(self, monkeypatch):
        client = self._client(monkeypatch, self._parked_events())

        with pytest.raises(ToolApprovalRequired, match="resume"):
            client.chat("run ls", thread_id="t-1")

    def test_a_generated_thread_id_still_reaches_the_error(self, monkeypatch):
        """``chat(message)`` is the documented default, and it parks too.

        The ID is generated inside ``_stream_turn``, so forwarding ``chat``'s
        own ``thread_id=None`` left the exception telling the caller to
        ``resume(thread_id=None)`` — which ``resume()`` rejects, stranding the
        parked checkpoint with no way to name it.
        """
        seen: dict[str, str | None] = {}
        events = self._parked_events()

        def _stream(message, *, thread_id=None, **kwargs):
            seen["thread_id"] = thread_id
            return iter(events)

        client = DeerFlowClient.__new__(DeerFlowClient)
        monkeypatch.setattr(client, "stream", _stream)

        with pytest.raises(ToolApprovalRequired) as excinfo:
            client.chat("run ls")

        assert excinfo.value.thread_id is not None
        # The resumable ID must be the thread the run actually used, not a
        # second one minted for the error message.
        assert excinfo.value.thread_id == seen["thread_id"]

    def test_a_generated_thread_id_is_resumable(self, monkeypatch):
        """``resume()`` rejects a falsy thread, so the ID must satisfy it."""
        from deerflow.utils.thread_id import validate_thread_id

        client = self._client(monkeypatch, self._parked_events())

        with pytest.raises(ToolApprovalRequired) as excinfo:
            client.chat("run ls")

        assert validate_thread_id(excinfo.value.thread_id) == excinfo.value.thread_id

    def test_an_ordinary_turn_still_returns_its_text(self, monkeypatch):
        """The park branch must not disturb the normal contract."""
        client = self._client(
            monkeypatch,
            [
                StreamEvent(type="messages-tuple", data={"type": "ai", "id": "ai-1", "content": "Hello"}),
                StreamEvent(type="messages-tuple", data={"type": "ai", "id": "ai-1", "content": " there"}),
                StreamEvent(type="end", data={}),
            ],
        )

        assert client.chat("hi", thread_id="t-1") == "Hello there"

    def test_a_tool_only_turn_that_did_not_park_still_returns_empty(self, monkeypatch):
        """An empty answer is only a bug when a park caused it."""
        client = self._client(monkeypatch, [StreamEvent(type="end", data={})])

        assert client.chat("hi", thread_id="t-1") == ""


class TestRejectionSurvivesSerialization:
    """A rejected call must not look like a successful one on embedded streams.

    Upstream's ``_process_decision`` distinguishes the two synthetic results
    purely by ``ToolMessage.status``: ``reject`` builds ``status="error"``,
    ``respond`` builds ``status="success"``. Both client serialization paths
    dropped that field, so the two decisions were indistinguishable — the TUI
    translator reads ``status``/``is_error`` and defaults a missing value to
    success, rendering a human-rejected call as ``ok``.

    ``status`` is forwarded verbatim rather than reinterpreted, so the embedded
    stream, the values snapshot, and what the model itself receives all agree.
    """

    @staticmethod
    def _rejected():
        return ToolMessage(content="User rejected the tool call.", id="tm-r", name="bash_tool", tool_call_id="call-1", status="error")

    @staticmethod
    def _responded():
        return ToolMessage(content="Answered on the tool's behalf.", id="tm-s", name="bash_tool", tool_call_id="call-1", status="success")

    def test_a_rejection_is_an_error_on_the_message_stream(self):
        assert DeerFlowClient._tool_message_event(self._rejected()).data["status"] == "error"

    def test_a_response_is_a_success_on_the_message_stream(self):
        assert DeerFlowClient._tool_message_event(self._responded()).data["status"] == "success"

    def test_a_rejection_is_an_error_in_the_values_snapshot(self):
        assert DeerFlowClient._serialize_message(self._rejected())["status"] == "error"

    def test_a_response_is_a_success_in_the_values_snapshot(self):
        assert DeerFlowClient._serialize_message(self._responded())["status"] == "success"

    def test_the_two_decisions_are_distinguishable(self):
        """The bug itself: both paths must separate reject from respond."""
        for project in (lambda msg: DeerFlowClient._tool_message_event(msg).data, DeerFlowClient._serialize_message):
            assert project(self._rejected())["status"] != project(self._responded())["status"]

    def test_the_tui_renders_a_rejection_as_an_error(self):
        """End of the chain: the translator this field exists to feed."""
        from deerflow.tui.runtime import translate

        event = DeerFlowClient._tool_message_event(self._rejected())
        results = [action for action in translate(event) if type(action).__name__ == "ToolResult"]

        assert [action.is_error for action in results] == [True]

    def test_an_ordinary_tool_result_still_carries_its_status(self):
        """Not approval-specific: every ToolMessage has this native field."""
        ok = ToolMessage(content="out", id="tm-1", name="ls", tool_call_id="call-1")

        assert DeerFlowClient._tool_message_event(ok).data["status"] == "success"
        assert DeerFlowClient._serialize_message(ok)["status"] == "success"


class TestResumeValidation:
    """``resume`` needs a parked thread, the interrupt it answers, and a decision."""

    def test_requires_a_thread_id(self):
        client = DeerFlowClient.__new__(DeerFlowClient)
        with pytest.raises(ValueError, match="thread_id"):
            next(client.resume([{"type": "approve"}], thread_id="", interrupt_id="int-1"))

    def test_requires_an_interrupt_id(self):
        """Without it the resume would answer whatever is pending now."""
        client = DeerFlowClient.__new__(DeerFlowClient)
        with pytest.raises(ValueError, match="interrupt_id"):
            next(client.resume([{"type": "approve"}], thread_id="t-1", interrupt_id=""))

    def test_requires_at_least_one_decision(self):
        client = DeerFlowClient.__new__(DeerFlowClient)
        with pytest.raises(ValueError, match="at least one decision"):
            next(client.resume([], thread_id="t-1", interrupt_id="int-1"))

    @staticmethod
    def _parked_client(monkeypatch, pending=("int-1",)):
        client = DeerFlowClient.__new__(DeerFlowClient)
        monkeypatch.setattr(client, "_pending_interrupt_ids", lambda thread_id, **kw: list(pending))
        return client

    def test_forwards_decisions_as_a_resume_command(self, monkeypatch):
        client = self._parked_client(monkeypatch)
        seen = {}

        def fake_stream(message, *, thread_id=None, resume=None, **kwargs):
            seen["message"] = message
            seen["thread_id"] = thread_id
            seen["resume"] = resume
            yield from ()

        monkeypatch.setattr(client, "stream", fake_stream)

        list(client.resume([{"type": "approve"}], thread_id="t-1", interrupt_id="int-1"))

        assert seen["thread_id"] == "t-1"
        # Keyed by the interrupt id, so LangGraph delivers it only there.
        assert seen["resume"] == {"int-1": {"decisions": [{"type": "approve"}]}}
        # A resume must not append a new HumanMessage.
        assert seen["message"] == ""

    def test_copies_each_decision_mapping(self, monkeypatch):
        """The payload must not alias caller-owned mappings."""
        client = self._parked_client(monkeypatch)
        seen = {}

        def fake_stream(message, *, thread_id=None, resume=None, **kwargs):
            seen["resume"] = resume
            yield from ()

        monkeypatch.setattr(client, "stream", fake_stream)

        original = {"type": "approve"}
        list(client.resume([original], thread_id="t-1", interrupt_id="int-1"))

        forwarded = seen["resume"]["int-1"]["decisions"][0]
        assert forwarded == original
        assert forwarded is not original
        assert isinstance(forwarded, Mapping)


class TestResumeChecksThePark:
    """``resume()`` must not report success for decisions nobody received.

    A newer ordinary run on the thread replaces the park instead of queueing
    behind it. A bare ``Command(resume=...)`` then either finds nothing pending
    (a silent no-op) or answers the newer park's tool calls. The client checks
    the reviewed interrupt is still the pending one, and sends the decisions
    keyed by its id so LangGraph cannot deliver them anywhere else.
    """

    @staticmethod
    def _client(monkeypatch, snapshot_interrupts):
        """Real ``_pending_interrupt_ids`` over a stubbed graph and checkpointer."""
        client = DeerFlowClient.__new__(DeerFlowClient)
        client._agent = SimpleNamespace(get_state=lambda config: SimpleNamespace(interrupts=snapshot_interrupts, metadata={}))
        client._checkpointer = object()
        client._checkpoint_channel_mode = "full"
        monkeypatch.setattr(client, "_get_runnable_config", lambda thread_id, **kw: {"configurable": {"thread_id": thread_id}})
        monkeypatch.setattr(client, "_ensure_agent", lambda config, context=None: None)
        streamed = []

        def fake_stream(message, *, thread_id=None, resume=None, **kwargs):
            streamed.append(resume)
            yield from ()

        monkeypatch.setattr(client, "stream", fake_stream)
        return client, streamed

    def test_a_thread_with_nothing_pending_is_refused(self, monkeypatch):
        """Would otherwise be a silent no-op that looks like a completed resume."""
        client, streamed = self._client(monkeypatch, ())

        with pytest.raises(ValueError, match="nothing is pending"):
            list(client.resume([{"type": "approve"}], thread_id="t-1", interrupt_id="int-1"))
        assert streamed == []

    def test_a_superseded_interrupt_id_is_refused(self, monkeypatch):
        """A newer park replaced the one the human reviewed."""
        client, streamed = self._client(monkeypatch, (Interrupt(value={}, id="int-new"),))

        with pytest.raises(ValueError, match="superseded"):
            list(client.resume([{"type": "approve"}], thread_id="t-1", interrupt_id="int-old"))
        assert streamed == []

    def test_the_matching_interrupt_id_is_resumed(self, monkeypatch):
        client, streamed = self._client(monkeypatch, (Interrupt(value={}, id="int-1"),))

        list(client.resume([{"type": "approve"}], thread_id="t-1", interrupt_id="int-1"))

        assert streamed == [{"int-1": {"decisions": [{"type": "approve"}]}}]

    def test_the_interrupt_id_is_not_forwarded_as_a_stream_override(self, monkeypatch):
        client, _ = self._client(monkeypatch, (Interrupt(value={}, id="int-1"),))
        seen = {}

        def fake_stream(message, *, thread_id=None, resume=None, **kwargs):
            seen.update(kwargs)
            yield from ()

        monkeypatch.setattr(client, "stream", fake_stream)
        list(client.resume([{"type": "approve"}], thread_id="t-1", interrupt_id="int-1"))

        assert "interrupt_id" not in seen


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

        LangGraph emits the parked ``values`` state *before* replaying the
        interrupted node, so the client sees the pre-edit args first and only
        then the rewritten ones — under the same message and call id. Both
        snapshots are supplied here because one alone cannot show the bug: with
        only the edited snapshot the message is new, takes the full emission
        path, and the edit trivially arrives.
        """
        prior = self._prior_turn()

        events = self._events(
            monkeypatch,
            [
                ("values", {"messages": [*prior, self._gated_call({"command": "ls"})]}),
                ("values", {"messages": [*prior, self._gated_call({"command": "ls -la"})]}),
            ],
            checkpoint_messages=[*prior, self._gated_call({"command": "ls"})],
        )

        tool_calls = [call for event in events if event.type == "messages-tuple" for call in (event.data.get("tool_calls") or ())]
        assert [call["args"] for call in tool_calls] == [{"command": "ls"}, {"command": "ls -la"}]

    def test_an_unchanged_gated_call_is_not_re_emitted(self, monkeypatch):
        """An ``approve`` replays the node without touching the args.

        The replacement branch must key off an actual change, or every resume
        emits a duplicate tool call that consumers cannot tell from a new one.
        """
        prior = self._prior_turn()

        events = self._events(
            monkeypatch,
            [
                ("values", {"messages": [*prior, self._gated_call({"command": "ls"})]}),
                ("values", {"messages": [*prior, self._gated_call({"command": "ls"})]}),
            ],
            checkpoint_messages=[*prior, self._gated_call({"command": "ls"})],
        )

        tool_calls = [call for event in events if event.type == "messages-tuple" for call in (event.data.get("tool_calls") or ())]
        assert [call["args"] for call in tool_calls] == [{"command": "ls"}]

    def test_a_partial_edit_re_emits_the_whole_call_list(self, monkeypatch):
        """One edited call among several still carries its siblings.

        ``tool_calls`` on the wire is always a message's complete list, never a
        per-call delta, and consumers merge it onto the message by id. Emitting
        only the changed call would therefore *remove* the untouched ones from
        the client's view of that message.
        """
        prior = self._prior_turn()

        def multi(command):
            return AIMessage(
                content="",
                id="ai-multi",
                tool_calls=[
                    {"name": "bash_tool", "args": {"command": command}, "id": "call-a"},
                    {"name": "write_file", "args": {"path": "/tmp/x"}, "id": "call-b"},
                ],
            )

        events = self._events(
            monkeypatch,
            [
                ("values", {"messages": [*prior, multi("ls")]}),
                ("values", {"messages": [*prior, multi("ls -la")]}),
            ],
            checkpoint_messages=[*prior, multi("ls")],
        )

        emitted = [event.data["tool_calls"] for event in events if event.type == "messages-tuple" and event.data.get("tool_calls")]
        assert [[(call["id"], call["args"]) for call in batch] for batch in emitted] == [
            [("call-a", {"command": "ls"}), ("call-b", {"path": "/tmp/x"})],
            [("call-a", {"command": "ls -la"}), ("call-b", {"path": "/tmp/x"})],
        ]

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
            [
                ("values", {"messages": [*prior, self._gated_call({"command": "ls"})]}),
                ("values", {"messages": [*prior, self._gated_call({"command": "ls -la"})]}),
            ],
            checkpoint_messages=[*prior, self._gated_call({"command": "ls"})],
        )

        ai_events = [event.data for event in events if event.type == "messages-tuple" and event.data.get("type") == "ai"]
        assert {event["id"] for event in ai_events} == {"ai-gated"}
        assert {call["id"] for event in ai_events for call in (event.get("tool_calls") or ())} == {"call-gated"}

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
