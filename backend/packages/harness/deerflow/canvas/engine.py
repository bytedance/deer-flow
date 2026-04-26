"""Canvas DAG execution engine."""

import logging
import re
from collections import defaultdict, deque
from typing import Any

from deerflow.canvas.components import (
    DataOutputExecutor,
    DataSourceExecutor,
    PythonScriptExecutor,
    SQLExecutorExecutor,
)
from deerflow.canvas.components.base import ExecutionContext
from deerflow.canvas.models import (
    AgentExecutionMode,
    Canvas,
    CanvasNode,
    CanvasStatus,
    ExecutionResult,
    NodeResult,
    NodeType,
)

logger = logging.getLogger(__name__)

# Pattern for {{node-X.field}} variable references
VARIABLE_PATTERN = re.compile(r"\{\{(node-\d+)\.(\w+)\}\}")


# Component executor registry
EXECUTORS = {
    NodeType.DATA_SOURCE: DataSourceExecutor(),
    NodeType.SQL_EXECUTOR: SQLExecutorExecutor(),
    NodeType.PYTHON_SCRIPT: PythonScriptExecutor(),
    NodeType.DATA_OUTPUT: DataOutputExecutor(),
}


def get_executor(node_type: NodeType):
    """Get executor for node type."""
    return EXECUTORS.get(node_type)


class CanvasEngine:
    """Engine for executing canvas DAG.

    Supports two execution modes:
    - readonly: Execute all nodes continuously
    - interactive: Pause after each node for agent decision
    """

    def __init__(
        self,
        canvas: Canvas,
        db_connections: dict[str, Any],
        sandbox: Any = None,
    ):
        self.canvas = canvas
        self.db_connections = db_connections
        self.sandbox = sandbox
        self.resolved_variables: dict[str, Any] = {}
        self.results: dict[str, NodeResult] = {}

    def topological_sort(self) -> list[CanvasNode]:
        """Sort nodes by dependencies using Kahn's algorithm.

        Raises:
            ValueError: If DAG contains a cycle
        """
        # Build adjacency list and in-degree count
        adj = defaultdict(list)
        in_degree = {node.id: 0 for node in self.canvas.nodes}

        for edge in self.canvas.edges:
            adj[edge.source].append(edge.target)
            in_degree[edge.target] += 1

        # Find all nodes with no incoming edges
        queue = deque(node_id for node_id, degree in in_degree.items() if degree == 0)

        sorted_nodes = []
        node_map = {node.id: node for node in self.canvas.nodes}

        while queue:
            node_id = queue.popleft()
            sorted_nodes.append(node_map[node_id])

            for neighbor in adj[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Check for cycle
        if len(sorted_nodes) != len(self.canvas.nodes):
            raise ValueError("DAG contains a cycle")

        return sorted_nodes

    def resolve_variables_for_node(self, node: CanvasNode) -> dict[str, Any]:
        """Resolve {{node-X.field}} references in node data."""
        resolved_data = {}

        for key, value in node.data.items():
            if isinstance(value, str):
                # Replace {{node-X.field}} patterns
                def replace_var(match):
                    node_id = match.group(1)
                    field = match.group(2)
                    var_key = f"{node_id}.{field}"
                    return str(self.resolved_variables.get(var_key, match.group(0)))

                resolved_data[key] = VARIABLE_PATTERN.sub(replace_var, value)
            else:
                resolved_data[key] = value

        return resolved_data

    async def execute(self) -> ExecutionResult:
        """Execute the canvas DAG.

        Returns:
            ExecutionResult with final status and node results
        """
        self.canvas.status = CanvasStatus.RUNNING

        try:
            sorted_nodes = self.topological_sort()
        except ValueError as e:
            logger.error(f"Canvas {self.canvas.id}: {e}")
            return ExecutionResult(
                canvas_id=self.canvas.id,
                status=CanvasStatus.FAILED,
                failed_nodes=[],
                results={},
            )

        completed_nodes = []
        failed_nodes = []

        for node in sorted_nodes:
            try:
                # Resolve variables for this node
                resolved_data = self.resolve_variables_for_node(node)

                # Create execution context
                context = ExecutionContext(
                    canvas_id=self.canvas.id,
                    thread_id=self.canvas.thread_id,
                    db_connections=self.db_connections,
                    sandbox=self.sandbox,
                    resolved_variables=resolved_data,
                )

                # Get and execute with appropriate executor
                executor = get_executor(node.type)
                if not executor:
                    raise ValueError(f"No executor for node type: {node.type}")

                result = await executor.execute(node, context)
                self.results[node.id] = result

                if result.success:
                    completed_nodes.append(node.id)
                    # Store output_table for downstream nodes
                    if result.output_table:
                        self.resolved_variables[f"{node.id}.output_table"] = result.output_table
                    logger.info(f"Canvas {self.canvas.id}: node {node.id} completed")
                else:
                    failed_nodes.append(node.id)
                    logger.error(f"Canvas {self.canvas.id}: node {node.id} failed: {result.error}")
                    # Stop execution on failure
                    if self.canvas.agent_execution_mode == AgentExecutionMode.READONLY:
                        break

            except Exception as e:
                logger.exception(f"Canvas {self.canvas.id}: node {node.id} error")
                failed_nodes.append(node.id)
                self.results[node.id] = NodeResult(
                    success=False,
                    error=str(e),
                )
                break

        # Determine final status
        if failed_nodes:
            status = CanvasStatus.FAILED
        elif len(completed_nodes) == len(sorted_nodes):
            status = CanvasStatus.COMPLETED
        else:
            status = CanvasStatus.PAUSED

        self.canvas.status = status

        return ExecutionResult(
            canvas_id=self.canvas.id,
            status=status,
            completed_nodes=completed_nodes,
            failed_nodes=failed_nodes,
            results=self.results,
        )
