"""Tests for canvas component executors."""

import pytest

from deerflow.canvas.components.base import (
    ComponentExecutor,
    ExecutionContext,
    NodeResult,
)
from deerflow.canvas.models import CanvasNode, NodeType


class TestComponentExecutor:
    def test_base_class_is_abstract(self):
        """ComponentExecutor should be abstract and not instantiable."""
        with pytest.raises(TypeError):
            ComponentExecutor()

    def test_validate_returns_empty_list_by_default(self):
        """Default validate implementation returns empty errors list."""
        # Create a concrete implementation for testing
        class DummyExecutor(ComponentExecutor):
            @property
            def node_type(self) -> str:
                return "dummy"

            async def execute(self, node, context):
                return NodeResult(success=True)

        executor = DummyExecutor()
        node = CanvasNode(id="test", type=NodeType.DATA_SOURCE, position={"x": 0, "y": 0}, data={})
        errors = executor.validate(node)
        assert errors == []


class TestExecutionContext:
    def test_create_execution_context(self):
        """ExecutionContext can be created with required fields."""
        context = ExecutionContext(
            canvas_id="canvas-1",
            thread_id="thread-1",
            db_connections={},
            sandbox=None,
            resolved_variables={},
        )
        assert context.canvas_id == "canvas-1"
        assert context.thread_id == "thread-1"

    def test_execution_context_with_resolved_variables(self):
        """ExecutionContext can store resolved variable values."""
        context = ExecutionContext(
            canvas_id="canvas-1",
            thread_id="thread-1",
            db_connections={},
            sandbox=None,
            resolved_variables={"node-1.output_table": "temp_table"},
        )
        assert context.resolved_variables["node-1.output_table"] == "temp_table"
