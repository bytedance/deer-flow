"""Unit tests for SafetyFinishReasonMiddleware."""

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.errors import GraphBubbleUp

from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware
from deerflow.agents.middlewares.safety_termination_detectors import (
    SafetyTermination,
)
from deerflow.config.safety_finish_reason_config import (
    SafetyDetectorConfig,
    SafetyFinishReasonConfig,
)


def _runtime(thread_id="t-1"):
    runtime = MagicMock()
    runtime.context = {"thread_id": thread_id}
    return runtime


def _ai(
    *,
    content="",
    tool_calls=None,
    response_metadata=None,
    additional_kwargs=None,
):
    return AIMessage(
        content=content,
        tool_calls=tool_calls or [],
        response_metadata=response_metadata or {},
        additional_kwargs=additional_kwargs or {},
    )


def _write_call(idx=1, content_text="半截"):
    return {
        "id": f"call_write_{idx}",
        "name": "write_file",
        "args": {"path": "/mnt/user-data/outputs/x.md", "content": content_text},
    }


class AlwaysHitDetector:
    """Test fixture: always reports the given termination."""

    name = "always_hit"

    def __init__(self, *, reason_field="finish_reason", reason_value="content_filter", extras=None):
        self.reason_field = reason_field
        self.reason_value = reason_value
        self.extras = extras or {}

    def detect(self, message):
        return SafetyTermination(
            detector=self.name,
            reason_field=self.reason_field,
            reason_value=self.reason_value,
            extras=self.extras,
        )


class NeverHitDetector:
    name = "never_hit"

    def detect(self, message):
        return None


class RaisingDetector:
    name = "raising"

    def detect(self, message):
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# Core trigger behaviour
# ---------------------------------------------------------------------------


class TestTriggerCriteria:
    def test_content_filter_with_tool_calls_triggers(self):
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    content="partial",
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }
        result = mw._apply(state, _runtime())
        assert result is not None
        patched = result["messages"][0]
        assert patched.tool_calls == []

    def test_content_filter_without_tool_calls_passes_through(self):
        """issue scope: when there are no tool calls the partial text is a
        legitimate final response and should not be rewritten."""
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    content="partial response",
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }
        assert mw._apply(state, _runtime()) is None

    def test_content_filter_blank_content_no_tool_calls_backfills(self):
        """#4393: an empty content_filter response with no tool calls would be
        persisted empty and rejected by strict providers on the next request.
        Backfill an explanation so the persisted message is non-empty."""
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    content="",
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }
        result = mw._apply(state, _runtime())
        assert result is not None
        patched = result["messages"][0]
        assert patched.tool_calls == []
        assert isinstance(patched.content, str)
        assert patched.content.strip()  # never persisted empty
        assert "safety-related signal" in patched.content
        assert "returned no content" in patched.content
        # It must not claim tool calls were suppressed — none existed.
        assert "were suppressed" not in patched.content
        record = patched.additional_kwargs["safety_termination"]
        assert record["suppressed_tool_call_count"] == 0
        assert record["suppressed_tool_call_names"] == []

    def test_content_filter_whitespace_content_no_tool_calls_backfills(self):
        """Whitespace-only content is still blank to a strict provider."""
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    content="   \n  ",
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }
        result = mw._apply(state, _runtime())
        assert result is not None
        patched = result["messages"][0]
        assert patched.tool_calls == []
        assert "returned no content" in patched.content

    def test_content_filter_none_content_no_tool_calls_backfills(self):
        """content=None is reachable via model_copy rewrites (which skip
        validation) and must be treated as blank, not stringified to 'None'."""
        mw = SafetyFinishReasonMiddleware()
        none_content = _ai(response_metadata={"finish_reason": "content_filter"}).model_copy(update={"content": None})
        assert none_content.content is None  # precondition for the regression
        result = mw._apply({"messages": [none_content]}, _runtime())
        assert result is not None
        patched = result["messages"][0]
        assert patched.tool_calls == []
        assert isinstance(patched.content, str)
        assert patched.content.strip()
        assert "returned no content" in patched.content

    def test_anthropic_refusal_blank_content_no_tool_calls_backfills(self):
        """The empty-content backfill is detector-agnostic (#4393)."""
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    content="",
                    response_metadata={"stop_reason": "refusal"},
                )
            ]
        }
        result = mw._apply(state, _runtime())
        assert result is not None
        assert result["messages"][0].content.strip()

    def test_blank_content_no_tool_calls_without_safety_signal_passes_through(self):
        """A blank response with no safety signal is out of scope: only a
        detected safety termination triggers the backfill."""
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    content="",
                    response_metadata={"finish_reason": "stop"},
                )
            ]
        }
        assert mw._apply(state, _runtime()) is None

    def test_normal_tool_calls_pass_through(self):
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "tool_calls"},
                )
            ]
        }
        assert mw._apply(state, _runtime()) is None

    def test_normal_stop_with_tool_calls_pass_through(self):
        # Some providers report finish_reason='stop' for tool-call messages.
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "stop"},
                )
            ]
        }
        assert mw._apply(state, _runtime()) is None

    def test_empty_message_list_passes_through(self):
        mw = SafetyFinishReasonMiddleware()
        assert mw._apply({"messages": []}, _runtime()) is None

    def test_non_ai_last_message_passes_through(self):
        mw = SafetyFinishReasonMiddleware()
        state = {"messages": [HumanMessage(content="hi"), SystemMessage(content="sys")]}
        assert mw._apply(state, _runtime()) is None

    def test_anthropic_refusal_with_tool_calls_triggers(self):
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    tool_calls=[_write_call()],
                    response_metadata={"stop_reason": "refusal"},
                )
            ]
        }
        result = mw._apply(state, _runtime())
        assert result is not None
        assert result["messages"][0].tool_calls == []

    def test_gemini_safety_with_tool_calls_triggers(self):
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "SAFETY"},
                )
            ]
        }
        result = mw._apply(state, _runtime())
        assert result is not None
        assert result["messages"][0].tool_calls == []


# ---------------------------------------------------------------------------
# Message rewriting
# ---------------------------------------------------------------------------


class TestMessageRewrite:
    def test_clears_structured_tool_calls(self):
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    tool_calls=[_write_call(1), _write_call(2)],
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }
        result = mw._apply(state, _runtime())
        patched = result["messages"][0]
        assert patched.tool_calls == []

    def test_clears_raw_additional_kwargs_tool_calls(self):
        """Critical defence-in-depth: DanglingToolCallMiddleware will recover
        tool calls from additional_kwargs.tool_calls if we forget them, which
        would re-emit a synthetic ToolMessage downstream and confuse the
        model. We must wipe both."""
        mw = SafetyFinishReasonMiddleware()
        raw_tool_calls = [
            {
                "id": "call_write_1",
                "type": "function",
                "function": {"name": "write_file", "arguments": '{"path": "/x"}'},
            }
        ]
        state = {
            "messages": [
                _ai(
                    tool_calls=[_write_call(1)],
                    response_metadata={"finish_reason": "content_filter"},
                    additional_kwargs={
                        "tool_calls": raw_tool_calls,
                        "function_call": {"name": "write_file", "arguments": "{}"},
                    },
                )
            ]
        }
        result = mw._apply(state, _runtime())
        patched = result["messages"][0]
        assert "tool_calls" not in patched.additional_kwargs
        assert "function_call" not in patched.additional_kwargs

    def test_preserves_other_additional_kwargs(self):
        # vLLM puts reasoning under additional_kwargs.reasoning; Anthropic
        # may carry other provider-specific keys. They must not be wiped.
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "content_filter"},
                    additional_kwargs={
                        "reasoning": "thinking text",
                        "custom_provider_field": {"x": 1},
                    },
                )
            ]
        }
        patched = mw._apply(state, _runtime())["messages"][0]
        assert patched.additional_kwargs["reasoning"] == "thinking text"
        assert patched.additional_kwargs["custom_provider_field"] == {"x": 1}

    def test_writes_observability_field(self):
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    tool_calls=[_write_call(1), _write_call(2)],
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }
        patched = mw._apply(state, _runtime())["messages"][0]
        record = patched.additional_kwargs["safety_termination"]
        assert record["detector"] == "openai_compatible_content_filter"
        assert record["reason_field"] == "finish_reason"
        assert record["reason_value"] == "content_filter"
        assert record["suppressed_tool_call_count"] == 2
        assert record["suppressed_tool_call_names"] == ["write_file", "write_file"]

    def test_preserves_response_metadata_finish_reason(self):
        """Downstream SSE converters read response_metadata.finish_reason —
        we want them to see the *real* provider reason, not 'stop'."""
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "content_filter", "model_name": "kimi-k2"},
                )
            ]
        }
        patched = mw._apply(state, _runtime())["messages"][0]
        assert patched.response_metadata["finish_reason"] == "content_filter"
        assert patched.response_metadata["model_name"] == "kimi-k2"

    def test_appends_user_facing_explanation_to_str_content(self):
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    content="some partial text",
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }
        patched = mw._apply(state, _runtime())["messages"][0]
        assert isinstance(patched.content, str)
        assert patched.content.startswith("some partial text")
        assert "safety-related signal" in patched.content

    def test_handles_empty_content(self):
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    content="",
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }
        patched = mw._apply(state, _runtime())["messages"][0]
        assert isinstance(patched.content, str)
        assert "safety-related signal" in patched.content

    def test_handles_list_content_thinking_blocks(self):
        """Anthropic thinking / vLLM reasoning models emit content blocks.
        Naively concatenating a string would raise TypeError."""
        mw = SafetyFinishReasonMiddleware()
        thinking_blocks = [
            {"type": "thinking", "text": "let me consider..."},
            {"type": "text", "text": "partial answer"},
        ]
        state = {
            "messages": [
                _ai(
                    content=thinking_blocks,
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }
        patched = mw._apply(state, _runtime())["messages"][0]
        assert isinstance(patched.content, list)
        assert patched.content[:2] == thinking_blocks
        assert patched.content[-1]["type"] == "text"
        assert "safety-related signal" in patched.content[-1]["text"]

    def test_idempotent_on_already_cleared_message(self):
        # Re-running the middleware on a message we already cleared must not
        # re-trigger (tool_calls is now empty → fast passthrough).
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }
        first = mw._apply(state, _runtime())
        state2 = {"messages": [first["messages"][0]]}
        second = mw._apply(state2, _runtime())
        assert second is None

    def test_preserves_message_id_for_add_messages_replacement(self):
        """LangGraph's add_messages reducer treats same-id messages as
        replacements. model_copy keeps id by default."""
        mw = SafetyFinishReasonMiddleware()
        original = _ai(
            tool_calls=[_write_call()],
            response_metadata={"finish_reason": "content_filter"},
        )
        # AIMessage auto-generates id; capture it
        original_id = original.id
        state = {"messages": [original]}
        patched = mw._apply(state, _runtime())["messages"][0]
        assert patched.id == original_id


# ---------------------------------------------------------------------------
# Detector wiring
# ---------------------------------------------------------------------------


class TestDetectorWiring:
    def test_iterates_detectors_in_order(self):
        first = AlwaysHitDetector(reason_value="first")
        second = AlwaysHitDetector(reason_value="second")
        mw = SafetyFinishReasonMiddleware(detectors=[first, second])
        state = {"messages": [_ai(tool_calls=[_write_call()])]}
        patched = mw._apply(state, _runtime())["messages"][0]
        assert patched.additional_kwargs["safety_termination"]["reason_value"] == "first"

    def test_returns_none_when_no_detector_matches(self):
        mw = SafetyFinishReasonMiddleware(detectors=[NeverHitDetector(), NeverHitDetector()])
        state = {
            "messages": [
                _ai(
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }
        assert mw._apply(state, _runtime()) is None

    def test_buggy_detector_does_not_break_run(self):
        mw = SafetyFinishReasonMiddleware(detectors=[RaisingDetector(), AlwaysHitDetector()])
        state = {"messages": [_ai(tool_calls=[_write_call()])]}
        result = mw._apply(state, _runtime())
        assert result is not None
        assert result["messages"][0].additional_kwargs["safety_termination"]["detector"] == "always_hit"

    def test_constructor_copies_detectors(self):
        """Caller mutation after construction must not leak into us."""
        detectors = [AlwaysHitDetector()]
        mw = SafetyFinishReasonMiddleware(detectors=detectors)
        detectors.clear()
        state = {"messages": [_ai(tool_calls=[_write_call()])]}
        assert mw._apply(state, _runtime()) is not None


# ---------------------------------------------------------------------------
# from_config
# ---------------------------------------------------------------------------


class TestFromConfig:
    def test_default_config_uses_builtin_detectors(self):
        mw = SafetyFinishReasonMiddleware.from_config(SafetyFinishReasonConfig())
        assert len(mw._detectors) == 3
        names = {d.name for d in mw._detectors}
        assert names == {"openai_compatible_content_filter", "anthropic_refusal", "gemini_safety"}

    def test_custom_detectors_loaded_via_reflection(self):
        cfg = SafetyFinishReasonConfig(
            detectors=[
                SafetyDetectorConfig(
                    use="deerflow.agents.middlewares.safety_termination_detectors:OpenAICompatibleContentFilterDetector",
                    config={"finish_reasons": ["custom_filter"]},
                ),
            ]
        )
        mw = SafetyFinishReasonMiddleware.from_config(cfg)
        assert len(mw._detectors) == 1
        # Confirm the kwargs propagated.
        state = {
            "messages": [
                _ai(
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "custom_filter"},
                )
            ]
        }
        assert mw._apply(state, _runtime()) is not None
        # Default token no longer matches.
        state2 = {
            "messages": [
                _ai(
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }
        assert mw._apply(state2, _runtime()) is None

    def test_empty_detector_list_rejected(self):
        cfg = SafetyFinishReasonConfig(detectors=[])
        with pytest.raises(ValueError, match="enabled=false"):
            SafetyFinishReasonMiddleware.from_config(cfg)

    def test_non_detector_class_rejected(self):
        cfg = SafetyFinishReasonConfig(
            detectors=[SafetyDetectorConfig(use="builtins:dict")],
        )
        with pytest.raises(TypeError):
            SafetyFinishReasonMiddleware.from_config(cfg)


# ---------------------------------------------------------------------------
# Stream event
# ---------------------------------------------------------------------------


class TestAuditEvent:
    """Verify SafetyFinishReasonMiddleware records a `middleware:safety_termination`
    audit event via RunJournal.record_middleware when the run-scoped journal is
    exposed under runtime.context["__run_journal"].

    Background: review on PR #3035 — SSE custom event handles live consumers,
    but post-run audit needs a row in run_events that can be queried with one
    SQL statement (no JOIN against message body).
    """

    def _runtime_with_journal(self, journal):
        runtime = MagicMock()
        runtime.context = {"thread_id": "t-audit", "__run_journal": journal}
        return runtime

    def test_records_audit_event_when_journal_present(self):
        journal = MagicMock()
        mw = SafetyFinishReasonMiddleware()
        tc = _write_call(1)
        state = {
            "messages": [
                _ai(
                    content="partial",
                    tool_calls=[tc],
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }
        result = mw._apply(state, self._runtime_with_journal(journal))
        assert result is not None

        journal.record_middleware.assert_called_once()
        call = journal.record_middleware.call_args
        # tag is positional or kwarg depending on call style; we use kwargs.
        assert call.kwargs["tag"] == "safety_termination"
        assert call.kwargs["name"] == "SafetyFinishReasonMiddleware"
        assert call.kwargs["hook"] == "after_model"
        assert call.kwargs["action"] == "suppress_tool_calls"

        changes = call.kwargs["changes"]
        assert changes["detector"] == "openai_compatible_content_filter"
        assert changes["reason_field"] == "finish_reason"
        assert changes["reason_value"] == "content_filter"
        assert changes["suppressed_tool_call_count"] == 1
        assert changes["suppressed_tool_call_names"] == ["write_file"]
        assert changes["suppressed_tool_call_ids"] == ["call_write_1"]
        assert "message_id" in changes
        assert isinstance(changes["extras"], dict)

    def test_audit_event_never_carries_tool_arguments(self):
        """PR #3035 review IMPORTANT: tool args are the filtered content itself
        and must NOT be persisted to run_events under any circumstance."""
        journal = MagicMock()
        mw = SafetyFinishReasonMiddleware()
        sensitive_tc = {
            "id": "call_x",
            "name": "write_file",
            "args": {"path": "/x", "content": "FILTERED_CONTENT_DO_NOT_PERSIST"},
        }
        state = {
            "messages": [
                _ai(
                    tool_calls=[sensitive_tc],
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }
        mw._apply(state, self._runtime_with_journal(journal))
        flat = repr(journal.record_middleware.call_args)
        assert "FILTERED_CONTENT_DO_NOT_PERSIST" not in flat, "tool arguments must not leak into audit event"
        assert "args" not in journal.record_middleware.call_args.kwargs["changes"]

    def test_no_journal_in_runtime_context_is_silently_skipped(self):
        """Subagent runtime / unit tests / no-event-store paths have no journal.
        Middleware must still intervene and clear tool_calls — only the audit
        event is skipped."""
        mw = SafetyFinishReasonMiddleware()
        runtime = MagicMock()
        runtime.context = {"thread_id": "t-noj"}  # no __run_journal
        state = {
            "messages": [
                _ai(
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }
        # Should not raise; should still clear tool_calls.
        result = mw._apply(state, runtime)
        assert result is not None
        assert result["messages"][0].tool_calls == []

    def test_journal_record_exception_warns_without_breaking_run(self, caplog):
        """Buggy journal must never propagate an exception into the agent loop."""
        journal = MagicMock()
        journal.record_middleware.side_effect = RuntimeError("db down")
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }
        # Must not raise.
        with caplog.at_level("WARNING"):
            result = mw._apply(state, self._runtime_with_journal(journal))

        assert result is not None
        assert result["messages"][0].tool_calls == []
        assert "Failed to record middleware:safety_termination event" in caplog.text

    def test_no_record_when_passthrough(self):
        """When the middleware does NOT intervene, no audit event is written."""
        journal = MagicMock()
        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "tool_calls"},  # healthy
                )
            ]
        }
        assert mw._apply(state, self._runtime_with_journal(journal)) is None
        journal.record_middleware.assert_not_called()


class TestStreamEvent:
    def test_emits_event_when_writer_available(self, monkeypatch):
        captured: list = []
        dispatched: list = []

        def fake_writer(payload):
            captured.append(payload)

        def fake_emit_custom_event(payload, *, writer):
            writer(payload)
            dispatched.append(payload)

        # Patch get_stream_writer at the symbol-resolution site.
        import langgraph.config

        monkeypatch.setattr(langgraph.config, "get_stream_writer", lambda: fake_writer)
        monkeypatch.setattr(
            "deerflow.agents.middlewares.safety_finish_reason_middleware.emit_custom_event",
            fake_emit_custom_event,
        )

        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }
        mw._apply(state, _runtime("t-stream"))

        assert len(captured) == 1
        payload = captured[0]
        assert payload["type"] == "safety_termination"
        assert payload["detector"] == "openai_compatible_content_filter"
        assert payload["reason_field"] == "finish_reason"
        assert payload["reason_value"] == "content_filter"
        assert payload["suppressed_tool_call_count"] == 1
        assert payload["suppressed_tool_call_names"] == ["write_file"]
        assert payload["thread_id"] == "t-stream"
        assert dispatched == captured

    @pytest.mark.anyio
    async def test_async_hook_uses_async_event_dispatch(self, monkeypatch):
        captured: list = []
        dispatched: list = []

        async def fake_emit_custom_event(payload, *, writer):
            writer(payload)
            dispatched.append(payload)

        import langgraph.config

        monkeypatch.setattr(langgraph.config, "get_stream_writer", lambda: captured.append)
        monkeypatch.setattr(
            "deerflow.agents.middlewares.safety_finish_reason_middleware.aemit_custom_event",
            fake_emit_custom_event,
        )

        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }

        result = await mw.aafter_model(state, _runtime("t-async-stream"))

        assert result is not None
        assert result["messages"][0].tool_calls == []
        assert dispatched == captured
        assert [payload["type"] for payload in captured] == ["safety_termination"]
        assert captured[0]["thread_id"] == "t-async-stream"

    def test_sync_event_preserves_langgraph_control_flow(self, monkeypatch):
        import langgraph.config

        def interrupt_dispatch(*_args, **_kwargs):
            raise GraphBubbleUp

        monkeypatch.setattr(langgraph.config, "get_stream_writer", lambda: lambda _payload: None)
        monkeypatch.setattr(
            "deerflow.agents.middlewares.safety_finish_reason_middleware.emit_custom_event",
            interrupt_dispatch,
        )

        termination = SafetyTermination(
            detector="test",
            reason_field="finish_reason",
            reason_value="content_filter",
        )
        with pytest.raises(GraphBubbleUp):
            SafetyFinishReasonMiddleware()._emit_event(termination, ["write_file"], _runtime())

    @pytest.mark.anyio
    async def test_async_event_preserves_langgraph_control_flow(self, monkeypatch):
        import langgraph.config

        async def interrupt_dispatch(*_args, **_kwargs):
            raise GraphBubbleUp

        monkeypatch.setattr(langgraph.config, "get_stream_writer", lambda: lambda _payload: None)
        monkeypatch.setattr(
            "deerflow.agents.middlewares.safety_finish_reason_middleware.aemit_custom_event",
            interrupt_dispatch,
        )

        termination = SafetyTermination(
            detector="test",
            reason_field="finish_reason",
            reason_value="content_filter",
        )
        with pytest.raises(GraphBubbleUp):
            await SafetyFinishReasonMiddleware()._aemit_event(termination, ["write_file"], _runtime())

    def test_writer_unavailable_does_not_break(self, monkeypatch):
        import langgraph.config

        def boom():
            raise LookupError("not in a stream context")

        monkeypatch.setattr(langgraph.config, "get_stream_writer", boom)

        mw = SafetyFinishReasonMiddleware()
        state = {
            "messages": [
                _ai(
                    tool_calls=[_write_call()],
                    response_metadata={"finish_reason": "content_filter"},
                )
            ]
        }
        # Should not raise.
        result = mw._apply(state, _runtime())
        assert result is not None
