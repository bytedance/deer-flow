"""Tests for canvas data models."""

from deerflow.canvas.models import (
    AgentExecutionMode,
    Canvas,
    CanvasEdge,
    CanvasNode,
    CanvasStatus,
    NodeType,
)


class TestCanvasNode:
    def test_create_data_source_node(self):
        node = CanvasNode(
            id="node-1",
            type=NodeType.DATA_SOURCE,
            position={"x": 100, "y": 100},
            data={"connection_id": "conn-1", "table_name": "users"},
        )
        assert node.id == "node-1"
        assert node.type == NodeType.DATA_SOURCE
        assert node.data["connection_id"] == "conn-1"

    def test_create_sql_executor_node(self):
        node = CanvasNode(
            id="node-2",
            type=NodeType.SQL_EXECUTOR,
            position={"x": 300, "y": 100},
            data={"sql": "SELECT * FROM t", "output_table": "result"},
        )
        assert node.type == NodeType.SQL_EXECUTOR
        assert "output_table" in node.data

    def test_node_position_defaults_to_zero(self):
        node = CanvasNode(
            id="node-3",
            type=NodeType.PYTHON_SCRIPT,
            position={"x": 0, "y": 0},
            data={"script": "pass", "output_table": "out"},
        )
        assert node.position.x == 0
        assert node.position.y == 0


class TestCanvasEdge:
    def test_create_edge(self):
        edge = CanvasEdge(source="node-1", target="node-2")
        assert edge.source == "node-1"
        assert edge.target == "node-2"


class TestCanvas:
    def test_create_canvas(self):
        canvas = Canvas(
            id="canvas-1",
            thread_id="thread-abc",
            name="Test Canvas",
            description="A test canvas",
            agent_execution_mode=AgentExecutionMode.READONLY,
            nodes=[],
            edges=[],
            status=CanvasStatus.IDLE,
        )
        assert canvas.id == "canvas-1"
        assert canvas.status == CanvasStatus.IDLE

    def test_canvas_with_nodes(self):
        node1 = CanvasNode(
            id="n1",
            type=NodeType.DATA_SOURCE,
            position={"x": 0, "y": 0},
            data={"connection_id": "c1", "table_name": "t1"},
        )
        node2 = CanvasNode(
            id="n2",
            type=NodeType.SQL_EXECUTOR,
            position={"x": 100, "y": 0},
            data={"sql": "SELECT 1", "output_table": "out"},
        )
        edge = CanvasEdge(source="n1", target="n2")
        canvas = Canvas(
            id="canvas-2",
            thread_id="thread-xyz",
            name="With Nodes",
            description="Canvas with nodes",
            agent_execution_mode=AgentExecutionMode.INTERACTIVE,
            nodes=[node1, node2],
            edges=[edge],
            status=CanvasStatus.IDLE,
        )
        assert len(canvas.nodes) == 2
        assert len(canvas.edges) == 1

    def test_canvas_serialization(self):
        canvas = Canvas(
            id="canvas-3",
            thread_id="thread-123",
            name="Serialization Test",
            description="Test JSON serialization",
            agent_execution_mode=AgentExecutionMode.READONLY,
            nodes=[],
            edges=[],
            status=CanvasStatus.IDLE,
        )
        json_data = canvas.model_dump()
        assert json_data["id"] == "canvas-3"
        assert json_data["agent_execution_mode"] == "readonly"
