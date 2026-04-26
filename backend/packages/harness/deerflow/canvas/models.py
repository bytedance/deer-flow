"""Canvas data models for data analysis DAG."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class NodeType(StrEnum):
    """Type of canvas node component."""

    DATA_SOURCE = "data_source"
    SQL_EXECUTOR = "sql_executor"
    PYTHON_SCRIPT = "python_script"
    DATA_OUTPUT = "data_output"


class CanvasStatus(StrEnum):
    """Status of canvas execution."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentExecutionMode(StrEnum):
    """How agent participates in execution."""

    INTERACTIVE = "interactive"
    READONLY = "readonly"


class AgentDecision(StrEnum):
    """Agent decision after node execution (interactive mode only)."""

    CONTINUE = "continue"
    PAUSE = "pause"
    MODIFY = "modify"
    ABORT = "abort"


class Position(BaseModel):
    """Node position on canvas."""

    x: float = Field(default=0.0, description="X coordinate")
    y: float = Field(default=0.0, description="Y coordinate")


class CanvasNode(BaseModel):
    """A node in the canvas DAG."""

    id: str = Field(..., description="Unique node identifier")
    type: NodeType = Field(..., description="Type of the node")
    position: Position = Field(default_factory=lambda: Position(x=0, y=0), description="Position on canvas")
    data: dict[str, Any] = Field(default_factory=dict, description="Node configuration data")


class CanvasEdge(BaseModel):
    """An edge connecting two nodes in the DAG."""

    source: str = Field(..., description="Source node ID")
    target: str = Field(..., description="Target node ID")


class ExecutionLogEntry(BaseModel):
    """Entry in the execution log."""

    node_id: str = Field(..., description="ID of the executed node")
    started_at: datetime = Field(..., description="Execution start time")
    completed_at: datetime | None = Field(default=None, description="Execution end time")
    success: bool = Field(default=False, description="Whether execution succeeded")
    output_table: str | None = Field(default=None, description="Output table name")
    output_file: str | None = Field(default=None, description="Output file path")
    rows_affected: int = Field(default=0, description="Number of rows affected")
    error: str | None = Field(default=None, description="Error message if failed")
    logs: list[str] = Field(default_factory=list, description="Execution logs")


class Canvas(BaseModel):
    """A canvas containing a DAG of data analysis nodes."""

    id: str = Field(..., description="Unique canvas identifier")
    thread_id: str = Field(..., description="Thread this canvas belongs to")
    name: str = Field(default="", description="Canvas name")
    description: str = Field(default="", description="Canvas description")
    agent_execution_mode: AgentExecutionMode = Field(
        default=AgentExecutionMode.READONLY,
        description="How agent participates in execution",
    )
    nodes: list[CanvasNode] = Field(default_factory=list, description="List of nodes")
    edges: list[CanvasEdge] = Field(default_factory=list, description="List of edges")
    status: CanvasStatus = Field(default=CanvasStatus.IDLE, description="Current status")
    execution_log: list[ExecutionLogEntry] = Field(
        default_factory=list,
        description="Execution history",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation time")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update time")


class NodeResult(BaseModel):
    """Result of executing a single node."""

    success: bool = Field(..., description="Whether execution succeeded")
    output_table: str | None = Field(default=None, description="Output table name")
    output_file: str | None = Field(default=None, description="Output file path")
    rows_affected: int = Field(default=0, description="Number of rows affected")
    error: str | None = Field(default=None, description="Error message if failed")
    logs: list[str] = Field(default_factory=list, description="Execution logs")


class ExecutionResult(BaseModel):
    """Result of executing the entire canvas DAG."""

    canvas_id: str = Field(..., description="Canvas ID")
    status: CanvasStatus = Field(..., description="Final status")
    completed_nodes: list[str] = Field(default_factory=list, description="IDs of completed nodes")
    failed_nodes: list[str] = Field(default_factory=list, description="IDs of failed nodes")
    results: dict[str, NodeResult] = Field(default_factory=dict, description="Results per node")
