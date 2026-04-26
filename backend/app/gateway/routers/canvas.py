"""Canvas REST API endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deerflow.canvas import Canvas, CanvasStatus, ExecutionResult
from deerflow.canvas.storage import CanvasStorage
from deerflow.canvas.engine import CanvasEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["canvas"])


class CanvasResponse(BaseModel):
    """Response model for canvas data."""

    id: str
    thread_id: str
    name: str
    description: str
    agent_execution_mode: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    status: str
    execution_log: list[dict[str, Any]]


class CanvasUpdateRequest(BaseModel):
    """Request model for updating canvas."""

    name: str | None = None
    description: str | None = None
    agent_execution_mode: str | None = None
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None


class CanvasExecuteRequest(BaseModel):
    """Request model for executing canvas."""

    db_connections: dict[str, Any] = Field(default_factory=dict, description="Database connections to use")


class ExecutionStatusResponse(BaseModel):
    """Response model for execution status."""

    canvas_id: str
    status: str
    current_node: str | None
    completed_nodes: list[str]
    pending_nodes: list[str]
    results: dict[str, Any]


class ComponentResponse(BaseModel):
    """Response model for component info."""

    type: str
    name: str
    description: str
    config_schema: dict[str, Any]


class ComponentsListResponse(BaseModel):
    """Response model for component list."""

    components: list[ComponentResponse]


# Component registry - simple component info
COMPONENT_INFO = {
    "data_source": {
        "name": "Data Source",
        "description": "Declare a data source from database table",
        "config_schema": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "table_name": {"type": "string"},
            },
            "required": ["connection_id", "table_name"],
        },
    },
    "sql_executor": {
        "name": "SQL Executor",
        "description": "Execute SQL to create or update a table",
        "config_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string"},
                "output_table": {"type": "string"},
            },
            "required": ["sql", "output_table"],
        },
    },
    "python_script": {
        "name": "Python Script",
        "description": "Execute Python code for data processing",
        "config_schema": {
            "type": "object",
            "properties": {
                "script": {"type": "string"},
                "input_tables": {"type": "array", "items": {"type": "string"}},
                "output_table": {"type": "string"},
            },
            "required": ["script", "output_table"],
        },
    },
    "data_output": {
        "name": "Data Output",
        "description": "Export table data to file",
        "config_schema": {
            "type": "object",
            "properties": {
                "input_table": {"type": "string"},
                "output_format": {"type": "string", "enum": ["csv", "json"]},
                "filename": {"type": "string"},
            },
            "required": ["input_table", "filename"],
        },
    },
}


def _canvas_to_response(canvas: Canvas) -> CanvasResponse:
    """Convert Canvas model to response."""
    return CanvasResponse(
        id=canvas.id,
        thread_id=canvas.thread_id,
        name=canvas.name,
        description=canvas.description,
        agent_execution_mode=canvas.agent_execution_mode.value,
        nodes=[n.model_dump() for n in canvas.nodes],
        edges=[e.model_dump() for e in canvas.edges],
        status=canvas.status.value,
        execution_log=[log.model_dump() for log in canvas.execution_log],
    )


@router.get("/threads/{thread_id}/canvas", response_model=CanvasResponse)
async def get_canvas(thread_id: str):
    """Get canvas for a thread."""
    storage = CanvasStorage()
    canvas = storage.load(thread_id)

    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")

    return _canvas_to_response(canvas)


@router.put("/threads/{thread_id}/canvas", response_model=CanvasResponse)
async def update_canvas(thread_id: str, request: CanvasUpdateRequest):
    """Create or update canvas for a thread."""
    storage = CanvasStorage()
    canvas = storage.load(thread_id)

    if canvas is None:
        # Create new canvas
        from deerflow.canvas.models import AgentExecutionMode

        canvas = Canvas(
            id=f"canvas-{thread_id}",
            thread_id=thread_id,
            name=request.name or "New Canvas",
            description=request.description or "",
            agent_execution_mode=AgentExecutionMode(request.agent_execution_mode or "readonly"),
            nodes=[],
            edges=[],
            status=CanvasStatus.IDLE,
        )
    else:
        # Update existing
        if request.name is not None:
            canvas.name = request.name
        if request.description is not None:
            canvas.description = request.description
        if request.agent_execution_mode is not None:
            from deerflow.canvas.models import AgentExecutionMode

            canvas.agent_execution_mode = AgentExecutionMode(request.agent_execution_mode)
        if request.nodes is not None:
            from deerflow.canvas.models import CanvasNode

            canvas.nodes = [CanvasNode(**n) if isinstance(n, dict) else n for n in request.nodes]
        if request.edges is not None:
            from deerflow.canvas.models import CanvasEdge

            canvas.edges = [CanvasEdge(**e) if isinstance(e, dict) else e for e in request.edges]

    storage.save(canvas)
    return _canvas_to_response(canvas)


@router.post("/threads/{thread_id}/canvas/execute", response_model=ExecutionStatusResponse)
async def execute_canvas(thread_id: str, request: CanvasExecuteRequest):
    """Execute canvas DAG."""
    storage = CanvasStorage()
    canvas = storage.load(thread_id)

    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")

    if len(canvas.nodes) == 0:
        raise HTTPException(status_code=400, detail="Canvas has no nodes")

    # Create engine and execute
    engine = CanvasEngine(canvas, db_connections=request.db_connections)
    result: ExecutionResult = await engine.execute()

    # Save updated canvas
    storage.save(canvas)

    return ExecutionStatusResponse(
        canvas_id=result.canvas_id,
        status=result.status.value,
        current_node=None,
        completed_nodes=result.completed_nodes,
        pending_nodes=[],
        results={k: v.model_dump() for k, v in result.results.items()},
    )


@router.get("/threads/{thread_id}/canvas/status", response_model=ExecutionStatusResponse)
async def get_execution_status(thread_id: str):
    """Get canvas execution status."""
    storage = CanvasStorage()
    canvas = storage.load(thread_id)

    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")

    completed_nodes = [log.node_id for log in canvas.execution_log if log.success]

    return ExecutionStatusResponse(
        canvas_id=canvas.id,
        status=canvas.status.value,
        current_node=None,
        completed_nodes=completed_nodes,
        pending_nodes=[n.id for n in canvas.nodes if n.id not in completed_nodes],
        results={},
    )


@router.get("/canvas/components", response_model=ComponentsListResponse)
async def list_components():
    """Get available canvas components."""
    components = [
        ComponentResponse(
            type=type_,
            name=info["name"],
            description=info["description"],
            config_schema=info["config_schema"],
        )
        for type_, info in COMPONENT_INFO.items()
    ]
    return ComponentsListResponse(components=components)


@router.delete("/threads/{thread_id}/canvas")
async def delete_canvas(thread_id: str):
    """Delete canvas for a thread."""
    storage = CanvasStorage()
    storage.delete(thread_id)
    return {"success": True}