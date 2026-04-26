"""Canvas module for data analysis DAG functionality."""

from deerflow.canvas.engine import CanvasEngine, get_executor
from deerflow.canvas.storage import CanvasStorage
from deerflow.canvas.tools import (
    CANVAS_EXT_TOOLS,
    CANVAS_TOOLS,
    canvas_add_edge_tool,
    canvas_add_node_tool,
    canvas_execute_tool,
    # Extended tools for canvas-analysis skill
    canvas_inspect_tool,
    canvas_list_tables_tool,
    canvas_plan_tool,
    canvas_preview_data_tool,
    canvas_status_tool,
    canvas_table_schema_tool,
)

from .models import (
    AgentDecision,
    AgentExecutionMode,
    Canvas,
    CanvasEdge,
    CanvasNode,
    CanvasStatus,
    ExecutionLogEntry,
    ExecutionResult,
    NodeResult,
    NodeType,
    Position,
)

__all__ = [
    "AgentDecision",
    "AgentExecutionMode",
    "Canvas",
    "CanvasEdge",
    "CanvasEngine",
    "CanvasNode",
    "CanvasStatus",
    "CanvasStorage",
    "CANVAS_TOOLS",
    "CANVAS_EXT_TOOLS",
    "canvas_add_edge_tool",
    "canvas_add_node_tool",
    "canvas_execute_tool",
    "canvas_plan_tool",
    "canvas_status_tool",
    # Extended tools
    "canvas_inspect_tool",
    "canvas_list_tables_tool",
    "canvas_table_schema_tool",
    "canvas_preview_data_tool",
    "ExecutionLogEntry",
    "ExecutionResult",
    "get_executor",
    "NodeResult",
    "NodeType",
    "Position",
]
