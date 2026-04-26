"""Tests for canvas Agent tools."""

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from deerflow.canvas.tools import canvas_plan_tool, canvas_execute_tool


def make_runtime(thread_id: str = "thread-1") -> SimpleNamespace:
    """Create a mock runtime for testing."""
    return SimpleNamespace(
        state={},
        context={"thread_id": thread_id},
        config={},
    )


class TestCanvasPlanTool:
    def test_canvas_plan_creates_new_canvas(self):
        """canvas_plan creates a new canvas with description."""
        runtime = make_runtime()

        with patch("deerflow.canvas.tools.CanvasStorage") as mock_storage:
            mock_storage.return_value.load.return_value = None
            mock_storage.return_value.save = MagicMock()

            result = canvas_plan_tool.func(
                runtime=runtime,
                description="Analyze sales data",
                name="Sales Analysis",
                agent_execution_mode="readonly",
                tool_call_id="tc-1",
            )

        assert result is not None
        assert result.update is not None
        assert "messages" in result.update
        # 验证 canvas 已创建
        mock_storage.return_value.save.assert_called_once()

    def test_canvas_plan_uses_existing_canvas(self):
        """canvas_plan can update existing canvas."""
        from deerflow.canvas.models import Canvas, CanvasStatus, AgentExecutionMode

        runtime = make_runtime()
        existing_canvas = Canvas(
            id="canvas-1",
            thread_id="thread-1",
            name="Existing",
            description="Existing canvas",
            agent_execution_mode=AgentExecutionMode.READONLY,
            nodes=[],
            edges=[],
            status=CanvasStatus.IDLE,
        )

        with patch("deerflow.canvas.tools.CanvasStorage") as mock_storage:
            mock_storage.return_value.load.return_value = existing_canvas
            mock_storage.return_value.save = MagicMock()

            result = canvas_plan_tool.func(
                runtime=runtime,
                description="Add more analysis",
                name="Updated Analysis",
                agent_execution_mode="readonly",
                tool_call_id="tc-2",
            )

        assert result is not None
        assert result.update is not None
        # 验证 canvas 已保存
        mock_storage.return_value.save.assert_called_once()


class TestCanvasExecuteTool:
    def test_canvas_execute_returns_error_if_no_canvas(self):
        """canvas_execute returns error if no canvas exists."""
        runtime = make_runtime()

        with patch("deerflow.canvas.tools.CanvasStorage") as mock_storage:
            mock_storage.return_value.load.return_value = None

            result = canvas_execute_tool.func(
                runtime=runtime,
                tool_call_id="tc-3",
            )

        assert result is not None
        assert result.update is not None
        assert "messages" in result.update
        # 应该有错误消息
        messages = result.update["messages"]
        assert len(messages) > 0
        assert "Error" in messages[0].content or "No canvas" in messages[0].content
