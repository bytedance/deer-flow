"""Data Output component - exports table data to files."""

import csv
import json
import logging
import re
from pathlib import Path
from typing import Any

from deerflow.canvas.components.base import ComponentExecutor, ExecutionContext, NodeResult
from deerflow.canvas.models import CanvasNode

logger = logging.getLogger(__name__)

# Regex pattern for valid SQL table names (alphanumeric and underscore, must start with letter or underscore)
TABLE_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Supported output formats
SUPPORTED_FORMATS = ["csv", "json"]


class DataOutputExecutor(ComponentExecutor):
    """Executor for data_output nodes.

    Exports table data to files in various formats (CSV, JSON).
    Output files are stored in the thread's outputs directory.
    """

    @property
    def node_type(self) -> str:
        return "data_output"

    def _validate_table_name(self, table_name: str) -> str:
        """Validate table name to prevent SQL injection.

        Args:
            table_name: The table name to validate.

        Returns:
            The validated table name.

        Raises:
            ValueError: If the table name contains invalid characters.
        """
        if not TABLE_NAME_PATTERN.match(table_name):
            raise ValueError(f"Invalid table name: {table_name}")
        return table_name

    def _validate_filename(self, filename: str) -> str:
        """Validate filename to prevent path traversal.

        Args:
            filename: The filename to validate.

        Returns:
            The sanitized filename.
        """
        # Remove any path separators
        safe_filename = filename.replace("/", "_").replace("\\", "_")
        # Remove parent directory references
        safe_filename = safe_filename.replace("..", "_")
        if safe_filename != filename:
            logger.warning(f"Sanitized filename: {filename} -> {safe_filename}")
        return safe_filename

    async def execute(
        self,
        node: CanvasNode,
        context: ExecutionContext,
    ) -> NodeResult:
        """Export table data to file.

        Args:
            node: Node containing input_table, output_format, filename
            context: Execution context with database connections

        Returns:
            NodeResult with output_file path
        """
        input_table_ref = node.data.get("input_table", "")
        output_format = node.data.get("output_format", "csv")
        filename = node.data.get("filename", "output.csv")

        # Validate filename for path traversal prevention
        filename = self._validate_filename(filename)

        # Resolve input table reference
        input_table = context.resolved_variables.get(input_table_ref, input_table_ref)

        # Validate table name for SQL injection prevention
        try:
            input_table = self._validate_table_name(input_table)
        except ValueError as e:
            return NodeResult(
                success=False,
                error=str(e),
            )

        # Get database connection
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

        try:
            # Query data from table
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT * FROM {input_table}")
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()

            # Write output file
            _output_path = self._write_file(
                columns=columns,
                rows=rows,
                output_format=output_format,
                filename=filename,
                context=context,
            )

            logs.append(f"Exported {len(rows)} rows to {filename}")
            logger.info(f"Data output executor {node.id}: exported {len(rows)} rows")

            return NodeResult(
                success=True,
                output_file=filename,
                rows_affected=len(rows),
                logs=logs,
            )
        except Exception as e:
            error_msg = f"Data export failed: {str(e)}"
            logs.append(error_msg)
            logger.error(f"Data output executor {node.id}: {error_msg}")
            return NodeResult(
                success=False,
                error=error_msg,
                logs=logs,
            )

    def _write_file(
        self,
        columns: list[str],
        rows: list[tuple],
        output_format: str,
        filename: str,
        context: ExecutionContext,
    ) -> str:
        """Write data to file in specified format.

        Returns the output file path.
        """
        # Get thread outputs directory
        outputs_dir = self._get_outputs_dir(context)
        file_path = outputs_dir / filename

        if output_format == "csv":
            self._write_csv(file_path, columns, rows)
        elif output_format == "json":
            self._write_json(file_path, columns, rows)
        else:
            raise ValueError(f"Unsupported output format: {output_format}")

        return str(file_path)

    def _write_csv(self, file_path: Path, columns: list[str], rows: list[tuple]) -> None:
        """Write data as CSV."""
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)

    def _write_json(self, file_path: Path, columns: list[str], rows: list[tuple]) -> None:
        """Write data as JSON."""
        data = [dict(zip(columns, row)) for row in rows]
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _get_outputs_dir(self, context: ExecutionContext) -> Path:
        """Get the outputs directory for the thread."""
        # Use thread-specific outputs directory
        from deerflow.config.paths import get_paths

        paths = get_paths()
        base_dir = paths.base_dir / "threads" / context.thread_id / "user-data" / "outputs"
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir

    def _get_connection_info(self, node: CanvasNode, context: ExecutionContext) -> dict[str, Any] | None:
        """Get database connection info for this node."""
        for conn_id, conn_info in context.db_connections.items():
            return conn_info
        return None

    def validate(self, node: CanvasNode) -> list[str]:
        """Validate data output configuration."""
        errors = []

        if "input_table" not in node.data:
            errors.append("data_output requires 'input_table' in data")
        if "filename" not in node.data:
            errors.append("data_output requires 'filename' in data")

        output_format = node.data.get("output_format", "csv")
        if output_format not in SUPPORTED_FORMATS:
            errors.append(f"data_output format must be one of: {SUPPORTED_FORMATS}")

        return errors