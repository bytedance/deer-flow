"""LangChain tools for canvas operations.

These tools allow the Agent to create and manipulate data analysis canvases.
"""

import logging
import uuid
from typing import Annotated

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.typing import ContextT

from deerflow.canvas.models import (
    AgentExecutionMode,
    Canvas,
    CanvasEdge,
    CanvasNode,
    CanvasStatus,
    NodeType,
    Position,
)
from deerflow.canvas.storage import CanvasStorage
from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)


def _get_thread_id(runtime: ToolRuntime[ContextT, dict]) -> str | None:
    """Resolve thread ID from runtime context."""
    thread_id = runtime.context.get("thread_id") if runtime.context else None
    if thread_id:
        return thread_id

    runtime_config = getattr(runtime, "config", None) or {}
    return runtime_config.get("configurable", {}).get("thread_id")


def _get_storage() -> CanvasStorage:
    """Get canvas storage instance."""
    return CanvasStorage(base_dir=get_paths().base_dir)


@tool("canvas_plan", parse_docstring=True)
def canvas_plan_tool(
    runtime: ToolRuntime[ContextT, dict],
    description: str,
    name: str = "",
    agent_execution_mode: str = "readonly",
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Create or update a canvas with the given description.

    Use this tool to plan a data analysis workflow. The canvas will contain
    a DAG of data processing nodes that can be executed.

    Args:
        description: Detailed description of what the canvas should analyze.
        name: Optional name for the canvas.
        agent_execution_mode: How agent participates in execution ("readonly" or "interactive").
    """
    thread_id = _get_thread_id(runtime)
    if not thread_id:
        return Command(
            update={"messages": [ToolMessage("Error: Thread ID not available", tool_call_id=tool_call_id)]},
        )

    storage = _get_storage()
    canvas = storage.load(thread_id)

    try:
        mode = AgentExecutionMode(agent_execution_mode)
    except ValueError:
        mode = AgentExecutionMode.READONLY

    if canvas is None:
        # Create new canvas
        canvas = Canvas(
            id=f"canvas-{uuid.uuid4().hex[:8]}",
            thread_id=thread_id,
            name=name or "Data Analysis",
            description=description,
            agent_execution_mode=mode,
            nodes=[],
            edges=[],
            status=CanvasStatus.IDLE,
        )
        logger.info(f"Created new canvas {canvas.id} for thread {thread_id}")
    else:
        # Update existing canvas
        canvas.name = name or canvas.name
        canvas.description = description
        canvas.agent_execution_mode = mode
        logger.info(f"Updated canvas {canvas.id} for thread {thread_id}")

    storage.save(canvas)

    return Command(
        update={
            "messages": [
                ToolMessage(
                    f"Canvas '{canvas.name}' ready with description: {description}\nCanvas ID: {canvas.id}\nAgent Mode: {mode.value}",
                    tool_call_id=tool_call_id,
                )
            ],
        },
    )


@tool("canvas_add_node", parse_docstring=True)
def canvas_add_node_tool(
    runtime: ToolRuntime[ContextT, dict],
    node_type: str,
    config: dict,
    node_id: str = "",
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Add a node to the current canvas.

    Use this tool to add processing nodes to the canvas DAG.

    Args:
        node_type: Type of node ("data_source", "sql_executor", "python_script", "data_output").
        config: Node configuration (varies by type).
        node_id: Optional custom node ID (auto-generated if not provided).
    """
    thread_id = _get_thread_id(runtime)
    if not thread_id:
        return Command(
            update={"messages": [ToolMessage("Error: Thread ID not available", tool_call_id=tool_call_id)]},
        )

    storage = _get_storage()
    canvas = storage.load(thread_id)

    if canvas is None:
        return Command(
            update={"messages": [ToolMessage("Error: No canvas exists. Use canvas_plan first.", tool_call_id=tool_call_id)]},
        )

    try:
        ntype = NodeType(node_type)
    except ValueError:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Error: Invalid node type '{node_type}'. Valid types: {[t.value for t in NodeType]}",
                        tool_call_id=tool_call_id,
                    )
                ]
            },
        )

    # Generate node ID if not provided
    node_id = node_id or f"node-{len(canvas.nodes) + 1}"

    # Calculate position (simple layout)
    y_position = len(canvas.nodes) * 100.0

    node = CanvasNode(
        id=node_id,
        type=ntype,
        position=Position(x=0.0, y=y_position),
        data=config,
    )

    canvas.nodes.append(node)
    storage.save(canvas)

    logger.info(f"Added node {node_id} ({node_type}) to canvas {canvas.id}")

    return Command(
        update={
            "messages": [
                ToolMessage(
                    f"Added {node_type} node '{node_id}' to canvas.\nTotal nodes: {len(canvas.nodes)}",
                    tool_call_id=tool_call_id,
                )
            ],
        },
    )


@tool("canvas_add_edge", parse_docstring=True)
def canvas_add_edge_tool(
    runtime: ToolRuntime[ContextT, dict],
    source: str,
    target: str,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Add an edge connecting two nodes in the canvas.

    Use this tool to define the data flow between nodes.

    Args:
        source: Source node ID.
        target: Target node ID.
    """
    thread_id = _get_thread_id(runtime)
    if not thread_id:
        return Command(
            update={"messages": [ToolMessage("Error: Thread ID not available", tool_call_id=tool_call_id)]},
        )

    storage = _get_storage()
    canvas = storage.load(thread_id)

    if canvas is None:
        return Command(
            update={"messages": [ToolMessage("Error: No canvas exists. Use canvas_plan first.", tool_call_id=tool_call_id)]},
        )

    # Validate nodes exist
    node_ids = {n.id for n in canvas.nodes}
    if source not in node_ids:
        return Command(
            update={"messages": [ToolMessage(f"Error: Source node '{source}' not found", tool_call_id=tool_call_id)]},
        )
    if target not in node_ids:
        return Command(
            update={"messages": [ToolMessage(f"Error: Target node '{target}' not found", tool_call_id=tool_call_id)]},
        )

    # Check for duplicate edge
    for edge in canvas.edges:
        if edge.source == source and edge.target == target:
            return Command(
                update={"messages": [ToolMessage(f"Edge {source} -> {target} already exists", tool_call_id=tool_call_id)]},
            )

    edge = CanvasEdge(source=source, target=target)
    canvas.edges.append(edge)
    storage.save(canvas)

    logger.info(f"Added edge {source} -> {target} to canvas {canvas.id}")

    return Command(
        update={
            "messages": [
                ToolMessage(
                    f"Added edge: {source} -> {target}\nTotal edges: {len(canvas.edges)}",
                    tool_call_id=tool_call_id,
                )
            ],
        },
    )


@tool("canvas_execute", parse_docstring=True)
def canvas_execute_tool(
    runtime: ToolRuntime[ContextT, dict],
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Execute the canvas DAG.

    Use this tool to run the data analysis workflow. All nodes will be
    executed in topological order based on their dependencies.

    Args:
        runtime: LangGraph tool runtime context (injected).
        tool_call_id: Unique identifier for this tool call (injected).
    """
    thread_id = _get_thread_id(runtime)
    if not thread_id:
        return Command(
            update={"messages": [ToolMessage("Error: Thread ID not available", tool_call_id=tool_call_id)]},
        )

    storage = _get_storage()
    canvas = storage.load(thread_id)

    if canvas is None:
        return Command(
            update={"messages": [ToolMessage("Error: No canvas exists. Use canvas_plan first.", tool_call_id=tool_call_id)]},
        )

    if not canvas.nodes:
        return Command(
            update={"messages": [ToolMessage("Error: Canvas has no nodes to execute", tool_call_id=tool_call_id)]},
        )

    # Import engine lazily to avoid circular imports
    from deerflow.canvas.engine import CanvasEngine

    # Get database connections from config
    from deerflow.config import get_app_config

    config = get_app_config()
    db_connections = {}
    if hasattr(config, "db_connections"):
        db_connections = {conn.name: conn.model_dump() for conn in config.db_connections}

    # Create engine and execute
    _engine = CanvasEngine(
        canvas=canvas,
        db_connections=db_connections,
        sandbox=None,  # Sandbox will be provided by middleware
    )

    # Return a command that will trigger async execution
    # The actual execution will be handled by a separate async mechanism
    logger.info(f"Canvas {canvas.id} execution requested")

    return Command(
        update={
            "messages": [
                ToolMessage(
                    f"Canvas execution started.\nCanvas ID: {canvas.id}\nNodes: {len(canvas.nodes)}\nEdges: {len(canvas.edges)}\nUse canvas_status to check progress.",
                    tool_call_id=tool_call_id,
                )
            ],
        },
    )


@tool("canvas_status", parse_docstring=True)
def canvas_status_tool(
    runtime: ToolRuntime[ContextT, dict],
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Get the current status of the canvas.

    Use this tool to check the execution status and results of the canvas.

    Args:
        runtime: LangGraph tool runtime context (injected).
        tool_call_id: Unique identifier for this tool call (injected).
    """
    thread_id = _get_thread_id(runtime)
    if not thread_id:
        return Command(
            update={"messages": [ToolMessage("Error: Thread ID not available", tool_call_id=tool_call_id)]},
        )

    storage = _get_storage()
    canvas = storage.load(thread_id)

    if canvas is None:
        return Command(
            update={"messages": [ToolMessage("No canvas exists for this thread.", tool_call_id=tool_call_id)]},
        )

    # Build status report
    status_lines = [
        f"Canvas: {canvas.name}",
        f"Status: {canvas.status.value}",
        f"Description: {canvas.description}",
        f"Nodes: {len(canvas.nodes)}",
        f"Edges: {len(canvas.edges)}",
        f"Agent Mode: {canvas.agent_execution_mode.value}",
    ]

    if canvas.execution_log:
        status_lines.append("\nExecution Log:")
        for entry in canvas.execution_log[-5:]:  # Show last 5 entries
            status_lines.append(f"  - {entry.node_id}: {'OK' if entry.success else 'FAILED'}")

    return Command(
        update={"messages": [ToolMessage("\n".join(status_lines), tool_call_id=tool_call_id)]},
    )


# Export all tools
CANVAS_TOOLS = [
    canvas_plan_tool,
    canvas_add_node_tool,
    canvas_add_edge_tool,
    canvas_execute_tool,
    canvas_status_tool,
]

__all__ = [
    "canvas_plan_tool",
    "canvas_add_node_tool",
    "canvas_add_edge_tool",
    "canvas_execute_tool",
    "canvas_status_tool",
    "CANVAS_TOOLS",
]
