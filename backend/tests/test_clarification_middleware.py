"""Tests for ClarificationMiddleware, focusing on options type coercion."""

import json
from types import SimpleNamespace

import pytest
from langgraph.graph.message import add_messages

from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware


@pytest.fixture
def middleware():
    return ClarificationMiddleware()


class TestFormatClarificationMessage:
    """Tests for _format_clarification_message options handling."""

    def test_options_as_native_list(self, middleware):
        """Normal case: options is already a list."""
        args = {
            "question": "Which env?",
            "clarification_type": "approach_choice",
            "options": ["dev", "staging", "prod"],
        }
        result = middleware._format_clarification_message(args)
        assert "1. dev" in result
        assert "2. staging" in result
        assert "3. prod" in result

    def test_options_as_json_string(self, middleware):
        """Bug case (#1995): model serializes options as a JSON string."""
        args = {
            "question": "Which env?",
            "clarification_type": "approach_choice",
            "options": json.dumps(["dev", "staging", "prod"]),
        }
        result = middleware._format_clarification_message(args)
        assert "1. dev" in result
        assert "2. staging" in result
        assert "3. prod" in result
        # Must NOT contain per-character output
        assert "1. [" not in result
        assert '2. "' not in result

    def test_options_as_json_string_scalar(self, middleware):
        """JSON string decoding to a non-list scalar is treated as one option."""
        args = {
            "question": "Which env?",
            "clarification_type": "approach_choice",
            "options": json.dumps("development"),
        }
        result = middleware._format_clarification_message(args)
        assert "1. development" in result
        # Must be a single option, not per-character iteration.
        assert "2." not in result

    def test_options_as_plain_string(self, middleware):
        """Edge case: options is a non-JSON string, treated as single option."""
        args = {
            "question": "Which env?",
            "clarification_type": "approach_choice",
            "options": "just one option",
        }
        result = middleware._format_clarification_message(args)
        assert "1. just one option" in result

    def test_options_none(self, middleware):
        """Options is None — no options section rendered."""
        args = {
            "question": "Tell me more",
            "clarification_type": "missing_info",
            "options": None,
        }
        result = middleware._format_clarification_message(args)
        assert "1." not in result

    def test_options_empty_list(self, middleware):
        """Options is an empty list — no options section rendered."""
        args = {
            "question": "Tell me more",
            "clarification_type": "missing_info",
            "options": [],
        }
        result = middleware._format_clarification_message(args)
        assert "1." not in result

    def test_options_missing(self, middleware):
        """Options key is absent — defaults to empty list."""
        args = {
            "question": "Tell me more",
            "clarification_type": "missing_info",
        }
        result = middleware._format_clarification_message(args)
        assert "1." not in result

    def test_context_included(self, middleware):
        """Context is rendered before the question."""
        args = {
            "question": "Which env?",
            "clarification_type": "approach_choice",
            "context": "Need target env for config",
            "options": ["dev", "prod"],
        }
        result = middleware._format_clarification_message(args)
        assert "Need target env for config" in result
        assert "Which env?" in result
        assert "1. dev" in result

    def test_json_string_with_mixed_types(self, middleware):
        """JSON string containing non-string elements still works."""
        args = {
            "question": "Pick one",
            "clarification_type": "approach_choice",
            "options": json.dumps(["Option A", 2, True, None]),
        }
        result = middleware._format_clarification_message(args)
        assert "1. Option A" in result
        assert "2. 2" in result
        assert "3. True" in result
        assert "4. None" in result


class TestHumanInputPayload:
    """Tests for structured human input request payloads."""

    def test_payload_with_native_options(self, middleware):
        payload = middleware._build_human_input_payload(
            {
                "question": "Which environment should I deploy to?",
                "clarification_type": "approach_choice",
                "context": "Need the target environment for config.",
                "options": ["development", "staging", "production"],
            },
            tool_call_id="call-abc",
            request_id="clarification:call-abc",
        )

        assert payload == {
            "version": 1,
            "kind": "human_input_request",
            "source": "ask_clarification",
            "request_id": "clarification:call-abc",
            "tool_call_id": "call-abc",
            "clarification_type": "approach_choice",
            "question": "Which environment should I deploy to?",
            "context": "Need the target environment for config.",
            "input_mode": "choice_with_other",
            "options": [
                {"id": "option-1", "label": "development", "value": "development"},
                {"id": "option-2", "label": "staging", "value": "staging"},
                {"id": "option-3", "label": "production", "value": "production"},
            ],
        }

    def test_payload_with_json_string_options(self, middleware):
        payload = middleware._build_human_input_payload(
            {
                "question": "Pick one",
                "clarification_type": "approach_choice",
                "options": json.dumps(["Option A", 2, True, None]),
            },
            tool_call_id="call-abc",
            request_id="clarification:call-abc",
        )

        assert payload["input_mode"] == "choice_with_other"
        assert payload["options"] == [
            {"id": "option-1", "label": "Option A", "value": "Option A"},
            {"id": "option-2", "label": "2", "value": "2"},
            {"id": "option-3", "label": "True", "value": "True"},
            {"id": "option-4", "label": "None", "value": "None"},
        ]

    def test_payload_with_plain_string_option(self, middleware):
        payload = middleware._build_human_input_payload(
            {
                "question": "Pick one",
                "clarification_type": "approach_choice",
                "options": "just one option",
            },
            tool_call_id="call-abc",
            request_id="clarification:call-abc",
        )

        assert payload["input_mode"] == "choice_with_other"
        assert payload["options"] == [{"id": "option-1", "label": "just one option", "value": "just one option"}]

    def test_payload_without_options_is_free_text(self, middleware):
        payload = middleware._build_human_input_payload(
            {
                "question": "Tell me more",
                "clarification_type": "missing_info",
                "options": None,
            },
            tool_call_id="call-abc",
            request_id="clarification:call-abc",
        )

        assert payload["input_mode"] == "free_text"
        assert "options" not in payload

    def test_payload_missing_options_is_free_text(self, middleware):
        payload = middleware._build_human_input_payload(
            {
                "question": "Tell me more",
                "clarification_type": "missing_info",
            },
            tool_call_id="call-abc",
            request_id="clarification:call-abc",
        )

        assert payload["input_mode"] == "free_text"
        assert "options" not in payload


class TestClarificationCommandIdempotency:
    """Clarification tool-call retries should not duplicate messages in state."""

    def test_repeated_tool_call_uses_stable_message_id(self, middleware):
        request = SimpleNamespace(
            tool_call={
                "name": "ask_clarification",
                "id": "call-clarify-1",
                "args": {
                    "question": "Which environment should I use?",
                    "clarification_type": "approach_choice",
                    "options": ["dev", "prod"],
                },
            }
        )

        first = middleware.wrap_tool_call(request, lambda _req: pytest.fail("handler should not be called"))
        second = middleware.wrap_tool_call(request, lambda _req: pytest.fail("handler should not be called"))

        first_message = first.update["messages"][0]
        second_message = second.update["messages"][0]

        assert first_message.id == "clarification:call-clarify-1"
        assert second_message.id == first_message.id
        assert second_message.tool_call_id == first_message.tool_call_id
        assert first_message.artifact["human_input"]["request_id"] == "clarification:call-clarify-1"
        assert first_message.artifact["human_input"]["tool_call_id"] == "call-clarify-1"
        assert first_message.artifact["human_input"]["clarification_type"] == "approach_choice"
        assert first_message.artifact["human_input"]["input_mode"] == "choice_with_other"

        merged = add_messages(add_messages([], [first_message]), [second_message])

        assert len(merged) == 1
        assert merged[0].id == "clarification:call-clarify-1"
        assert merged[0].content == first_message.content
        assert merged[0].artifact == first_message.artifact

    def test_tool_message_model_dump_preserves_human_input_artifact(self, middleware):
        request = SimpleNamespace(
            tool_call={
                "name": "ask_clarification",
                "id": "call-clarify-1",
                "args": {
                    "question": "Which environment should I use?",
                    "clarification_type": "approach_choice",
                    "options": ["dev", "prod"],
                },
            }
        )

        result = middleware.wrap_tool_call(request, lambda _req: pytest.fail("handler should not be called"))
        message = result.update["messages"][0]
        dumped = message.model_dump()

        assert dumped["artifact"]["human_input"]["request_id"] == "clarification:call-clarify-1"
        assert dumped["artifact"]["human_input"]["options"] == [
            {"id": "option-1", "label": "dev", "value": "dev"},
            {"id": "option-2", "label": "prod", "value": "prod"},
        ]
        assert "Which environment should I use?" in dumped["content"]


class TestClarificationDisabled:
    """When ``disable_clarification`` is set in runtime context, a clarification
    must NOT interrupt the run — it returns a ToolMessage nudging the agent to
    proceed, so non-interactive channels (GitHub) don't dead-end."""

    def _request(self, *, runtime_context):
        return SimpleNamespace(
            tool_call={
                "name": "ask_clarification",
                "id": "call-clarify-1",
                "args": {"question": "Should I create the issue?", "clarification_type": "suggestion"},
            },
            runtime=SimpleNamespace(context=runtime_context),
        )

    def test_disabled_returns_toolmessage_not_command(self, middleware):
        request = self._request(runtime_context={"disable_clarification": True})
        result = middleware.wrap_tool_call(request, lambda _req: pytest.fail("handler should not be called"))
        # Not a Command(goto=END) — a plain ToolMessage so the loop continues.
        from langchain_core.messages import ToolMessage

        assert isinstance(result, ToolMessage)
        assert result.tool_call_id == "call-clarify-1"
        assert result.artifact is None

    def test_disabled_message_tells_agent_to_proceed(self, middleware):
        request = self._request(runtime_context={"disable_clarification": True})
        result = middleware.wrap_tool_call(request, lambda _req: pytest.fail("handler should not be called"))
        assert "disabled" in result.content.lower()
        assert "proceed" in result.content.lower()

    def test_disabled_async_path(self, middleware):
        request = self._request(runtime_context={"disable_clarification": True})

        async def handler(_req):
            return pytest.fail("handler should not be called")

        import asyncio

        result = asyncio.run(middleware.awrap_tool_call(request, handler))
        from langchain_core.messages import ToolMessage

        assert isinstance(result, ToolMessage)

    def test_not_disabled_still_interrupts(self, middleware):
        """Without the flag, the original goto=END behavior is preserved."""
        from langgraph.types import Command

        request = self._request(runtime_context={})  # no disable_clarification
        result = middleware.wrap_tool_call(request, lambda _req: pytest.fail("handler should not be called"))
        assert isinstance(result, Command)
        assert result.goto == "__end__"

    def test_no_runtime_context_still_interrupts(self, middleware):
        """Defensive: missing runtime/context falls back to interrupting."""
        from langgraph.types import Command

        request = SimpleNamespace(
            tool_call={
                "name": "ask_clarification",
                "id": "c1",
                "args": {"question": "q?", "clarification_type": "missing_info"},
            },
            runtime=None,
        )
        result = middleware.wrap_tool_call(request, lambda _req: pytest.fail("handler should not be called"))
        assert isinstance(result, Command)

    def test_non_clarification_tool_call_unaffected_by_flag(self, middleware):
        """The flag only affects ask_clarification; other tools run normally."""
        other = SimpleNamespace(
            tool_call={"name": "bash", "id": "b1", "args": {"command": "echo hi"}},
            runtime=SimpleNamespace(context={"disable_clarification": True}),
        )
        sentinel = "ran"
        result = middleware.wrap_tool_call(other, lambda _req: sentinel)
        assert result == sentinel

    def test_missing_tool_call_id_still_gets_stable_message_id(self, middleware):
        request = SimpleNamespace(
            tool_call={
                "name": "ask_clarification",
                "args": {
                    "question": "Which environment should I use?",
                    "clarification_type": "missing_info",
                },
            }
        )

        first = middleware.wrap_tool_call(request, lambda _req: pytest.fail("handler should not be called"))
        second = middleware.wrap_tool_call(request, lambda _req: pytest.fail("handler should not be called"))

        first_message = first.update["messages"][0]
        second_message = second.update["messages"][0]

        assert first_message.id.startswith("clarification:")
        assert second_message.id == first_message.id

        merged = add_messages(add_messages([], [first_message]), [second_message])

        assert len(merged) == 1
