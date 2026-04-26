"""Tests for canvas execution engine."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.canvas.engine import CanvasEngine
from deerflow.canvas.models import (
    AgentExecutionMode,
    Canvas,
    CanvasEdge,
    CanvasNode,
    CanvasStatus,
    NodeResult,
    NodeType,
)


def create_test_canvas() -> Canvas:
    """Create a simple test canvas with two nodes."""
    node1 = CanvasNode(
        id="node-1",
        type=NodeType.DATA_SOURCE,
        position={"x": 0, "y": 0},
        data={"connection_id": "conn-1", "table_name": "users"},
    )
    node2 = CanvasNode(
        id="node-2",
        type=NodeType.SQL_EXECUTOR,
        position={"x": 100, "y": 0},
        data={"sql": "SELECT * FROM users", "output_table": "result"},
    )
    edge = CanvasEdge(source="node-1", target="node-2")

    return Canvas(
        id="test-canvas",
        thread_id="thread-1",
        name="Test Canvas",
        description="A test canvas",
        agent_execution_mode=AgentExecutionMode.READONLY,
        nodes=[node1, node2],
        edges=[edge],
        status=CanvasStatus.IDLE,
    )


class TestCanvasEngine:
    def test_topological_sort_returns_correct_order(self):
        """Nodes should be sorted by dependencies."""
        canvas = create_test_canvas()
        engine = CanvasEngine(canvas, db_connections={})

        sorted_nodes = engine.topological_sort()

        # node-1 should come before node-2
        assert sorted_nodes[0].id == "node-1"
        assert sorted_nodes[1].id == "node-2"

    def test_topological_sort_detects_cycle(self):
        """Engine should detect cycles in DAG."""
        node1 = CanvasNode(
            id="n1",
            type=NodeType.SQL_EXECUTOR,
            position={"x": 0, "y": 0},
            data={"sql": "SELECT 1", "output_table": "t1"},
        )
        node2 = CanvasNode(
            id="n2",
            type=NodeType.SQL_EXECUTOR,
            position={"x": 100, "y": 0},
            data={"sql": "SELECT 2", "output_table": "t2"},
        )
        # Create cycle: n1 -> n2 -> n1
        edge1 = CanvasEdge(source="n1", target="n2")
        edge2 = CanvasEdge(source="n2", target="n1")

        canvas = Canvas(
            id="cycle-canvas",
            thread_id="thread-1",
            name="Cycle",
            description="Canvas with cycle",
            agent_execution_mode=AgentExecutionMode.READONLY,
            nodes=[node1, node2],
            edges=[edge1, edge2],
            status=CanvasStatus.IDLE,
        )

        engine = CanvasEngine(canvas, db_connections={})

        with pytest.raises(ValueError, match="cycle"):
            engine.topological_sort()

    def test_resolve_variables_from_node_data(self):
        """Engine should resolve {{node-X.field}} references."""
        node1 = CanvasNode(
            id="node-1",
            type=NodeType.SQL_EXECUTOR,
            position={"x": 0, "y": 0},
            data={"sql": "SELECT * FROM t", "output_table": "temp1"},
        )
        node2 = CanvasNode(
            id="node-2",
            type=NodeType.SQL_EXECUTOR,
            position={"x": 100, "y": 0},
            data={
                "sql": "SELECT * FROM {{node-1.output_table}}",
                "output_table": "temp2",
            },
        )
        edge = CanvasEdge(source="node-1", target="node-2")

        canvas = Canvas(
            id="var-canvas",
            thread_id="thread-1",
            name="Variables",
            description="Canvas with variable references",
            agent_execution_mode=AgentExecutionMode.READONLY,
            nodes=[node1, node2],
            edges=[edge],
            status=CanvasStatus.IDLE,
        )

        engine = CanvasEngine(canvas, db_connections={})

        # After executing node-1, resolve variables for node-2
        engine.resolved_variables["node-1.output_table"] = "temp1"

        resolved = engine.resolve_variables_for_node(node2)

        assert resolved["sql"] == "SELECT * FROM temp1"

    @pytest.mark.asyncio
    async def test_execute_runs_all_nodes_in_order(self):
        """Engine should execute all nodes in topological order."""
        canvas = create_test_canvas()

        # Mock executors
        with patch("deerflow.canvas.engine.get_executor") as mock_get:
            mock_executor = MagicMock()
            mock_executor.execute = AsyncMock(return_value=NodeResult(success=True, output_table=None))
            mock_get.return_value = mock_executor

            engine = CanvasEngine(canvas, db_connections={"conn-1": {}})
            result = await engine.execute()

        assert result.status == CanvasStatus.COMPLETED
        assert len(result.completed_nodes) == 2

    @pytest.mark.asyncio
    async def test_execute_stops_on_failure(self):
        """Engine should stop execution when a node fails."""
        canvas = create_test_canvas()

        with patch("deerflow.canvas.engine.get_executor") as mock_get:
            mock_executor = MagicMock()
            # First node succeeds, second fails
            mock_executor.execute = AsyncMock(
                side_effect=[
                    NodeResult(success=True, output_table=None),
                    NodeResult(success=False, error="SQL error"),
                ]
            )
            mock_get.return_value = mock_executor

            engine = CanvasEngine(canvas, db_connections={"conn-1": {}})
            result = await engine.execute()

        assert result.status == CanvasStatus.FAILED
