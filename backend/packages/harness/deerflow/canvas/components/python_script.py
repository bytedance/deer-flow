"""Python Script component - executes Python code in sandbox."""

import asyncio
import logging
import uuid

from deerflow.canvas.components.base import ComponentExecutor, ExecutionContext
from deerflow.canvas.models import CanvasNode, NodeResult

logger = logging.getLogger(__name__)


class PythonScriptExecutor(ComponentExecutor):
    """Executor for python_script nodes.

    Executes Python scripts in a sandbox environment with:
    - Pre-installed libraries: pandas, numpy, sqlalchemy
    - Environment variables: INPUT_TABLES, OUTPUT_TABLE, DB_URL
    """

    @property
    def node_type(self) -> str:
        return "python_script"

    async def execute(
        self,
        node: CanvasNode,
        context: ExecutionContext,
    ) -> NodeResult:
        """Execute Python script in sandbox.

        Args:
            node: Node containing script, input_tables, output_table
            context: Execution context with sandbox and database connections

        Returns:
            NodeResult with output_table name
        """
        script = node.data.get("script", "")
        input_tables = node.data.get("input_tables", [])
        output_table = node.data.get("output_table", "")

        if not context.sandbox:
            return NodeResult(
                success=False,
                error="Sandbox not available for Python execution",
            )

        # Get database connection info
        db_url = self._get_db_url(context)

        # Resolve input table references
        resolved_input_tables = [context.resolved_variables.get(t, t) for t in input_tables]

        logs = []
        script_filename = f"script_{node.id}_{uuid.uuid4().hex[:8]}.py"

        try:
            # Prepare script with environment setup
            script_with_env = self._prepare_script_with_env(
                script,
                resolved_input_tables,
                output_table,
                db_url,
            )

            # 在事件循环中运行同步 sandbox 方法
            loop = asyncio.get_event_loop()

            # 写入临时脚本文件
            script_path = f"/tmp/{script_filename}"
            await loop.run_in_executor(
                None,
                context.sandbox.write_file,
                script_path,
                script_with_env,
            )

            # 使用临时文件执行脚本
            result = await loop.run_in_executor(
                None,
                context.sandbox.execute_command,
                f"python {script_path}",
            )

            # 清理临时文件
            await loop.run_in_executor(
                None,
                context.sandbox.execute_command,
                f"rm -f {script_path}",
            )

            # 检查执行结果
            # LocalSandbox.execute_command 返回字符串，失败时包含 "Exit Code: X"
            if isinstance(result, str) and "Exit Code:" in result:
                # 提取错误信息
                error_msg = result.split("Exit Code:")[0].strip()
                if "Std Error:" in error_msg:
                    error_msg = error_msg.split("Std Error:")[-1].strip()
                logs.append(f"Script execution failed: {error_msg[:500]}")
                logger.error(f"Python script executor {node.id}: {error_msg[:500]}")
                return NodeResult(
                    success=False,
                    error=error_msg[:500],
                    logs=logs,
                )

            # 如果返回值是字符串，检查是否包含 Python 异常
            if isinstance(result, str) and "Traceback" in result:
                logs.append(f"Script execution may have errors: {result[:500]}")
                logger.warning(f"Python script executor {node.id}: potential error in output")

            logs.append("Script executed successfully")
            logger.info(f"Python script executor {node.id}: created table {output_table}")

            return NodeResult(
                success=True,
                output_table=output_table,
                logs=logs,
            )
        except Exception as e:
            error_msg = f"Python script execution failed: {str(e)}"
            logs.append(error_msg)
            logger.error(f"Python script executor {node.id}: {error_msg}")
            return NodeResult(
                success=False,
                error=error_msg,
                logs=logs,
            )

    def _prepare_script_with_env(
        self,
        script: str,
        input_tables: list[str],
        output_table: str,
        db_url: str,
    ) -> str:
        """Prepare script with environment variable injection.

        Creates a wrapper script that sets environment variables
        before executing the user's script.
        """
        env_setup = f"""
import os
os.environ['INPUT_TABLES'] = {repr(",".join(input_tables))}
os.environ['OUTPUT_TABLE'] = {repr(output_table)}
os.environ['DB_URL'] = {repr(db_url)}

"""
        return env_setup + script

    def _get_db_url(self, context: ExecutionContext) -> str:
        """Get database URL from context."""
        for conn_id, conn_info in context.db_connections.items():
            return conn_info.get("url", "") or conn_info.get("connection_url", "")
        return ""

    def validate(self, node: CanvasNode) -> list[str]:
        """Validate Python script configuration."""
        errors = []

        if "script" not in node.data:
            errors.append("python_script requires 'script' in data")
        if "output_table" not in node.data:
            errors.append("python_script requires 'output_table' in data")

        return errors
