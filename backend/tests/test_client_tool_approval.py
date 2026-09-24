"""Tests for interrupt handling in the embedded client's stream contract."""

from collections.abc import Mapping
from types import SimpleNamespace

import pytest
from langgraph.types import Interrupt

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
