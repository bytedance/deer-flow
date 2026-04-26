"""SQL Executor component - executes SQL and creates tables."""

import logging
import re
from typing import Any

from deerflow.canvas.components.base import ComponentExecutor, ExecutionContext
from deerflow.canvas.models import CanvasNode, NodeResult

logger = logging.getLogger(__name__)

# Regex to find {{variable}} patterns
VARIABLE_PATTERN = re.compile(r"\{\{(\w+)\}\}")


class SQLExecutorExecutor(ComponentExecutor):
    """Executor for sql_executor nodes.

    Executes SQL statements to create tables (CREATE TABLE ... AS SELECT).
    Supports variable substitution using {{variable_name}} syntax.
    """

    @property
    def node_type(self) -> str:
        return "sql_executor"

    async def execute(
        self,
        node: CanvasNode,
        context: ExecutionContext,
    ) -> NodeResult:
        """Execute SQL statement.

        Args:
            node: Node containing sql and output_table
            context: Execution context with database connections

        Returns:
            NodeResult with output_table name
        """
        sql_template = node.data.get("sql", "")
        output_table = node.data.get("output_table", "")

        # Resolve variables in SQL
        resolved_sql = self._resolve_variables(sql_template, context.resolved_variables)

        # Get database connection (use first available or specific one)
        conn_info = self._get_connection_info(node, context)
        if not conn_info:
            return NodeResult(
                success=False,
                error="No database connection available",
            )

        connection = conn_info.get("connection")
        if not connection:
            return NodeResult(
                success=False,
                error="Database connection not initialized",
            )

        logs = []
        rows_affected = 0

        try:
            # Execute the SQL
            with connection.cursor() as cursor:
                cursor.execute(resolved_sql)
                rows_affected = cursor.rowcount or 0
                connection.commit()

            logs.append(f"Executed SQL successfully, {rows_affected} rows affected")
            logger.info(f"SQL executor {node.id}: created table {output_table}")

            return NodeResult(
                success=True,
                output_table=output_table,
                rows_affected=rows_affected,
                logs=logs,
            )
        except Exception as e:
            connection.rollback()
            error_msg = f"SQL execution failed: {str(e)}"
            logs.append(error_msg)
            logger.error(f"SQL executor {node.id}: {error_msg}")
            return NodeResult(
                success=False,
                error=error_msg,
                logs=logs,
            )

    def _resolve_variables(self, sql: str, variables: dict[str, Any]) -> str:
        """Replace {{variable}} patterns with resolved values."""

        def replacer(match):
            var_name = match.group(1)
            return str(variables.get(var_name, match.group(0)))

        return VARIABLE_PATTERN.sub(replacer, sql)

    def _get_connection_info(self, node: CanvasNode, context: ExecutionContext) -> dict[str, Any] | None:
        """Get database connection info for this node."""
        # First connection available, or implement connection selection logic
        for conn_id, conn_info in context.db_connections.items():
            return conn_info
        return None

    def validate(self, node: CanvasNode) -> list[str]:
        """Validate SQL executor configuration."""
        errors = []

        if "sql" not in node.data:
            errors.append("sql_executor requires 'sql' in data")
        if "output_table" not in node.data:
            errors.append("sql_executor requires 'output_table' in data")

        return errors
