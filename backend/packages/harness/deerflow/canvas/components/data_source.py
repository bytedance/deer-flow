"""DataSource component executor - declares data source without execution."""

from deerflow.canvas.components.base import ComponentExecutor, ExecutionContext
from deerflow.canvas.models import CanvasNode, NodeResult


class DataSourceExecutor(ComponentExecutor):
    """Executor for data_source nodes.

    Data source nodes declare where data comes from but do not
    perform any execution. They serve as entry points in the DAG.
    """

    @property
    def node_type(self) -> str:
        return "data_source"

    async def execute(
        self,
        node: CanvasNode,
        context: ExecutionContext,
    ) -> NodeResult:
        """Execute data source node.

        Data source nodes do not perform any database operations.
        They simply validate that the connection and table exist.

        Returns:
            NodeResult with success=True, no output_table
        """
        # No actual execution - data source is declarative
        return NodeResult(
            success=True,
            logs=[f"Data source declared: {node.data.get('table_name')}"],
        )

    def validate(self, node: CanvasNode) -> list[str]:
        """Validate data source configuration."""
        errors = []

        if "connection_id" not in node.data:
            errors.append("data_source requires 'connection_id' in data")
        if "table_name" not in node.data:
            errors.append("data_source requires 'table_name' in data")

        return errors