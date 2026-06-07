"""Tests for STORY-067: DataAvailabilityMiddleware.

Verifies that the middleware:
- Scans ToolMessages for envelope format
- Generates DATA AVAILABILITY block
- Injects it into model request messages
- Skips when no envelope ToolMessages are present
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


class TestDataAvailabilityMiddleware:
    """Unit tests for DataAvailabilityMiddleware."""

    @pytest.fixture
    def middleware(self):
        from deerflow.agents.middlewares.data_availability_middleware import DataAvailabilityMiddleware

        return DataAvailabilityMiddleware()

    def _make_envelope_tool_message(self, *, source: str, status: str, error_code: str | None = None, data_len: int = 100) -> ToolMessage:
        import json

        content = json.dumps({
            "status": status,
            "source": source,
            "error_code": error_code,
            "message": f"{error_code}: connection failed" if error_code else None,
            "data": {"chars": data_len} if status == "ok" else None,
        })
        return ToolMessage(
            content=content,
            tool_call_id=f"call_{source}",
            name=f"query_{source}",
        )

    def _make_plain_tool_message(self) -> ToolMessage:
        return ToolMessage(
            content="Some plain text result, not envelope format",
            tool_call_id="call_plain",
            name="plain_tool",
        )

    def _make_model_request(self, messages: list):
        request = MagicMock()
        request.messages = messages
        request.override = MagicMock(side_effect=lambda **kwargs: MagicMock(messages=kwargs.get("messages", messages)))
        return request

    def test_injects_availability_block_with_mixed_status(self, middleware):
        """AC1: Injects DATA AVAILABILITY when envelope ToolMessages present."""
        messages = [
            HumanMessage(content="请进行日常巡检"),
            AIMessage(content="好的，我来调用工具"),
            self._make_envelope_tool_message(source="kubernetes", status="ok", data_len=32339),
            self._make_envelope_tool_message(source="prometheus", status="error", error_code="TIMEOUT"),
            self._make_envelope_tool_message(source="elasticsearch", status="ok", data_len=0),
        ]
        request = self._make_model_request(messages)
        handler = MagicMock(return_value=MagicMock())

        middleware.wrap_model_call(request, handler)

        request.override.assert_called_once()
        injected_messages = request.override.call_args[1]["messages"]

        reminder_msgs = [m for m in injected_messages if isinstance(m, HumanMessage) and m.additional_kwargs.get("data_availability_reminder")]
        assert len(reminder_msgs) == 1

        reminder_content = reminder_msgs[0].content
        assert "DATA AVAILABILITY" in reminder_content
        assert "✅" in reminder_content
        assert "❌" in reminder_content
        assert "kubernetes" in reminder_content
        assert "prometheus" in reminder_content
        assert "TIMEOUT" in reminder_content
        assert "MUST NOT" in reminder_content

    def test_skips_when_no_envelope_messages(self, middleware):
        """AC3: No injection when no envelope ToolMessages."""
        messages = [
            HumanMessage(content="你好"),
            AIMessage(content="你好！有什么可以帮你的？"),
        ]
        request = self._make_model_request(messages)
        handler = MagicMock(return_value=MagicMock())

        middleware.wrap_model_call(request, handler)

        request.override.assert_not_called()
        handler.assert_called_once_with(request)

    def test_skips_plain_tool_messages(self, middleware):
        """AC3: Plain (non-envelope) ToolMessages don't trigger injection."""
        messages = [
            HumanMessage(content="搜索一下"),
            self._make_plain_tool_message(),
        ]
        request = self._make_model_request(messages)
        handler = MagicMock(return_value=MagicMock())

        middleware.wrap_model_call(request, handler)

        request.override.assert_not_called()
        handler.assert_called_once_with(request)

    def test_does_not_modify_existing_messages(self, middleware):
        """R5: Existing ToolMessages are not modified."""
        tool_msg = self._make_envelope_tool_message(source="kubernetes", status="ok")
        original_content = tool_msg.content
        messages = [
            HumanMessage(content="巡检"),
            tool_msg,
        ]
        request = self._make_model_request(messages)
        handler = MagicMock(return_value=MagicMock())

        middleware.wrap_model_call(request, handler)

        assert tool_msg.content == original_content

    def test_all_success_sources_show_checkmark(self, middleware):
        """All successful sources marked with ✅."""
        messages = [
            HumanMessage(content="巡检"),
            self._make_envelope_tool_message(source="kubernetes", status="ok", data_len=500),
            self._make_envelope_tool_message(source="elasticsearch", status="ok", data_len=200),
            self._make_envelope_tool_message(source="devops_release", status="ok", data_len=0),
        ]
        request = self._make_model_request(messages)
        handler = MagicMock(return_value=MagicMock())

        middleware.wrap_model_call(request, handler)

        request.override.assert_called_once()
        injected_messages = request.override.call_args[1]["messages"]
        reminder_msgs = [m for m in injected_messages if isinstance(m, HumanMessage) and m.additional_kwargs.get("data_availability_reminder")]
        reminder_content = reminder_msgs[0].content
        assert "❌" not in reminder_content
        assert reminder_content.count("✅") == 3

    def test_all_failed_sources_show_cross(self, middleware):
        """All failed sources marked with ❌."""
        messages = [
            HumanMessage(content="巡检"),
            self._make_envelope_tool_message(source="prometheus", status="error", error_code="TIMEOUT"),
            self._make_envelope_tool_message(source="elasticsearch", status="error", error_code="AUTH_ERROR"),
        ]
        request = self._make_model_request(messages)
        handler = MagicMock(return_value=MagicMock())

        middleware.wrap_model_call(request, handler)

        request.override.assert_called_once()
        injected_messages = request.override.call_args[1]["messages"]
        reminder_msgs = [m for m in injected_messages if isinstance(m, HumanMessage) and m.additional_kwargs.get("data_availability_reminder")]
        reminder_content = reminder_msgs[0].content
        assert "✅" not in reminder_content
        assert reminder_content.count("❌") == 2

    @pytest.mark.asyncio
    async def test_async_wrap_model_call(self, middleware):
        """AC1: Async variant also injects correctly."""
        messages = [
            HumanMessage(content="巡检"),
            self._make_envelope_tool_message(source="kubernetes", status="ok", data_len=100),
            self._make_envelope_tool_message(source="prometheus", status="error", error_code="CONNECTION_FAILED"),
        ]
        request = self._make_model_request(messages)
        handler = AsyncMock(return_value=MagicMock())

        await middleware.awrap_model_call(request, handler)

        request.override.assert_called_once()
        injected_messages = request.override.call_args[1]["messages"]
        reminder_msgs = [m for m in injected_messages if isinstance(m, HumanMessage) and m.additional_kwargs.get("data_availability_reminder")]
        assert len(reminder_msgs) == 1

    def test_does_not_inject_duplicate(self, middleware):
        """If DATA AVAILABILITY already injected, don't add another."""
        messages = [
            HumanMessage(content="巡检"),
            self._make_envelope_tool_message(source="kubernetes", status="ok"),
            HumanMessage(
                content="<system-reminder>\n<data_availability>\n...\n</data_availability>\n</system-reminder>",
                additional_kwargs={"data_availability_reminder": True, "hide_from_ui": True},
            ),
        ]
        request = self._make_model_request(messages)
        handler = MagicMock(return_value=MagicMock())

        middleware.wrap_model_call(request, handler)

        request.override.assert_not_called()
        handler.assert_called_once_with(request)
