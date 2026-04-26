"""Tests for canvas component executors."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from deerflow.canvas.components.base import (
    ComponentExecutor,
    ExecutionContext,
    NodeResult,
)
from deerflow.canvas.components.data_source import DataSourceExecutor
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


class TestDataSourceExecutor:
    def test_node_type_is_data_source(self):
        """DataSourceExecutor handles data_source nodes."""
        executor = DataSourceExecutor()
        assert executor.node_type == "data_source"

    def test_validate_requires_connection_id(self):
        """DataSource requires connection_id in data."""
        executor = DataSourceExecutor()
        node = CanvasNode(
            id="n1",
            type=NodeType.DATA_SOURCE,
            position={"x": 0, "y": 0},
            data={"table_name": "users"},  # missing connection_id
        )
        errors = executor.validate(node)
        assert len(errors) == 1
        assert "connection_id" in errors[0]

    def test_validate_requires_table_name(self):
        """DataSource requires table_name in data."""
        executor = DataSourceExecutor()
        node = CanvasNode(
            id="n2",
            type=NodeType.DATA_SOURCE,
            position={"x": 0, "y": 0},
            data={"connection_id": "conn-1"},  # missing table_name
        )
        errors = executor.validate(node)
        assert len(errors) == 1
        assert "table_name" in errors[0]

    def test_validate_returns_empty_for_valid_node(self):
        """Valid DataSource node passes validation."""
        executor = DataSourceExecutor()
        node = CanvasNode(
            id="n3",
            type=NodeType.DATA_SOURCE,
            position={"x": 0, "y": 0},
            data={"connection_id": "conn-1", "table_name": "users"},
        )
        errors = executor.validate(node)
        assert errors == []

    @pytest.mark.asyncio
    async def test_execute_returns_success_without_building_table(self):
        """DataSource execution returns success without creating table."""
        executor = DataSourceExecutor()
        node = CanvasNode(
            id="n4",
            type=NodeType.DATA_SOURCE,
            position={"x": 0, "y": 0},
            data={"connection_id": "conn-1", "table_name": "users"},
        )
        context = ExecutionContext(
            canvas_id="canvas-1",
            thread_id="thread-1",
            db_connections={"conn-1": {"type": "postgres"}},
            sandbox=None,
            resolved_variables={},
        )
        result = await executor.execute(node, context)
        # data_source does not output a table, it references existing table
        assert result.success is True
        assert result.output_table is None


class TestSQLExecutorExecutor:
    def test_node_type_is_sql_executor(self):
        """SQLExecutor handles sql_executor nodes."""
        from deerflow.canvas.components.sql_executor import SQLExecutorExecutor

        executor = SQLExecutorExecutor()
        assert executor.node_type == "sql_executor"

    def test_validate_requires_sql(self):
        """SQL executor requires sql in data."""
        from deerflow.canvas.components.sql_executor import SQLExecutorExecutor

        executor = SQLExecutorExecutor()
        node = CanvasNode(
            id="n1",
            type=NodeType.SQL_EXECUTOR,
            position={"x": 0, "y": 0},
            data={"output_table": "result"},  # missing sql
        )
        errors = executor.validate(node)
        assert len(errors) == 1
        assert "sql" in errors[0]

    def test_validate_requires_output_table(self):
        """SQL executor requires output_table in data."""
        from deerflow.canvas.components.sql_executor import SQLExecutorExecutor

        executor = SQLExecutorExecutor()
        node = CanvasNode(
            id="n2",
            type=NodeType.SQL_EXECUTOR,
            position={"x": 0, "y": 0},
            data={"sql": "SELECT 1"},  # missing output_table
        )
        errors = executor.validate(node)
        assert len(errors) == 1
        assert "output_table" in errors[0]

    def test_validate_returns_empty_for_valid_node(self):
        """Valid SQL executor node passes validation."""
        from deerflow.canvas.components.sql_executor import SQLExecutorExecutor

        executor = SQLExecutorExecutor()
        node = CanvasNode(
            id="n3",
            type=NodeType.SQL_EXECUTOR,
            position={"x": 0, "y": 0},
            data={"sql": "SELECT * FROM users", "output_table": "result"},
        )
        errors = executor.validate(node)
        assert errors == []

    @pytest.mark.asyncio
    async def test_execute_resolves_variables_and_runs_sql(self):
        """SQL executor resolves variables and executes SQL."""
        from deerflow.canvas.components.sql_executor import SQLExecutorExecutor

        executor = SQLExecutorExecutor()
        node = CanvasNode(
            id="n4",
            type=NodeType.SQL_EXECUTOR,
            position={"x": 0, "y": 0},
            data={
                "sql": "CREATE TABLE {{output_table}} AS SELECT * FROM {{source_table}}",
                "output_table": "my_result",
            },
        )

        # Mock database connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.rowcount = 100

        context = ExecutionContext(
            canvas_id="canvas-1",
            thread_id="thread-1",
            db_connections={"conn-1": {"connection": mock_conn, "type": "postgres"}},
            sandbox=None,
            resolved_variables={
                "source_table": "raw_data",
            },
        )

        with patch.object(executor, "_get_connection_info", return_value={"connection": mock_conn, "type": "postgres"}):
            result = await executor.execute(node, context)

        assert result.success is True
        assert result.output_table == "my_result"
        assert result.rows_affected == 100
