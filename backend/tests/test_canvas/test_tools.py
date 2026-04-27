"""Tests for canvas Agent tools."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from langchain_core.messages import ToolMessage

from deerflow.canvas.tools import canvas_add_node_tool, canvas_execute_tool, canvas_plan_tool


def make_runtime(thread_id: str = "thread-1") -> SimpleNamespace:
    """Create a mock runtime for testing."""
    return SimpleNamespace(
        state={},
        context={"thread_id": thread_id},
        config={},
        tool_call_id="tool-call-1",
    )


class TestCanvasPlanTool:
    def test_canvas_add_node_schema_exposes_object_config(self):
        """canvas_add_node publishes a structured object schema for config."""
        config_schema = canvas_add_node_tool.args["config"]
        assert config_schema["type"] == "object"
        assert config_schema["description"] == "Node configuration (varies by type)."

    def test_canvas_plan_returns_tool_message(self):
        """canvas_plan returns a ToolMessage keyed by runtime.tool_call_id."""
        runtime = make_runtime()
        with patch("deerflow.canvas.tools.CanvasStorage") as mock_storage:
            mock_storage.return_value.load.return_value = None
            mock_storage.return_value.save = MagicMock()

            result = canvas_plan_tool.func(
                description="Analyze sales data",
                name="Sales Analysis",
                agent_execution_mode="readonly",
                runtime=runtime,
            )

        message = result.update["messages"][0]
        assert isinstance(message, ToolMessage)
        assert message.tool_call_id == "tool-call-1"
        assert "Canvas 'Sales Analysis' ready" in message.content

    def test_canvas_add_node_adds_node(self):
        """canvas_add_node adds a node using standard typed arguments."""
        runtime = make_runtime()
        with patch("deerflow.canvas.tools.CanvasStorage") as mock_storage:
            from deerflow.canvas.models import AgentExecutionMode, Canvas, CanvasStatus

            mock_storage.return_value.load.return_value = Canvas(
                id="canvas-1",
                thread_id="thread-1",
                name="Existing",
                description="Existing canvas",
                agent_execution_mode=AgentExecutionMode.READONLY,
                nodes=[],
                edges=[],
                status=CanvasStatus.IDLE,
            )
            mock_storage.return_value.save = MagicMock()

            result = canvas_add_node_tool.func(
                node_type="data_source",
                config={
                    "connection_id": "dataflow",
                    "table_name": "fact_sales",
                    "display_name": "销售事实表",
                },
                node_id="node-1",
                runtime=runtime,
            )

        assert result is not None
        assert result.update is not None
        message = result.update["messages"][0]
        assert isinstance(message, ToolMessage)
        assert "Added data_source node 'node-1'" in message.content
        mock_storage.return_value.save.assert_called_once()

    def test_canvas_plan_creates_new_canvas(self):
        """canvas_plan creates a new canvas with description."""
        runtime = make_runtime()

        with patch("deerflow.canvas.tools.CanvasStorage") as mock_storage:
            mock_storage.return_value.load.return_value = None
            mock_storage.return_value.save = MagicMock()

            result = canvas_plan_tool.func(
                description="Analyze sales data",
                name="Sales Analysis",
                agent_execution_mode="readonly",
                runtime=runtime,
            )

        assert result is not None
        assert result.update is not None
        assert "messages" in result.update
        assert isinstance(result.update["messages"][0], ToolMessage)
        # 验证 canvas 已创建
        mock_storage.return_value.save.assert_called_once()

    def test_canvas_plan_uses_existing_canvas(self):
        """canvas_plan can update existing canvas."""
        from deerflow.canvas.models import AgentExecutionMode, Canvas, CanvasStatus

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
                description="Add more analysis",
                name="Updated Analysis",
                agent_execution_mode="readonly",
                runtime=runtime,
            )

        assert result is not None
        assert result.update is not None
        assert isinstance(result.update["messages"][0], ToolMessage)
        # 验证 canvas 已保存
        mock_storage.return_value.save.assert_called_once()


class TestCanvasExecuteTool:
    def test_canvas_execute_returns_error_if_no_canvas(self):
        """canvas_execute returns error if no canvas exists."""
        runtime = make_runtime()

        with patch("deerflow.canvas.tools.CanvasStorage") as mock_storage:
            mock_storage.return_value.load.return_value = None

            result = asyncio.run(canvas_execute_tool.coroutine(runtime=runtime))

        assert result is not None
        assert result.update is not None
        assert "messages" in result.update
        # 应该有错误消息
        messages = result.update["messages"]
        assert len(messages) > 0
        assert isinstance(messages[0], ToolMessage)
        assert "Error" in messages[0].content or "No canvas" in messages[0].content
