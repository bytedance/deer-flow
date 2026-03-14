"""Dedicated Python code execution tool with structured I/O and output truncation."""

import logging
import os

from langchain.tools import ToolRuntime, tool
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState
from src.sandbox.exceptions import SandboxError
from src.sandbox.tools import (
    ensure_sandbox_initialized,
    ensure_thread_directories_exist,
    get_thread_data,
    is_local_sandbox,
    replace_virtual_path,
    truncate_output,
)

logger = logging.getLogger(__name__)

# Maximum characters to return in tool output (saves context tokens)
MAX_OUTPUT_LENGTH = 4096


@tool("execute_python", parse_docstring=True)
def execute_python_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,
    code: str,
    save_output_to: str | None = None,
) -> str:
    """Execute Python code in a sandboxed environment with structured output.

    Prefer this tool over `bash(command="python ...")` for data analysis, computation,
    and any task where structured output handling is beneficial. Output is automatically
    truncated to save context tokens, with an option to save full output to a file.

    Examples:
        execute_python(description="Analyze CSV", code="import pandas as pd\\ndf = pd.read_csv('/mnt/user-data/uploads/data.csv')\\nprint(df.describe())")
        execute_python(description="Save stats", code="import json\\nprint(json.dumps({'mean': 42.5}))", save_output_to="/mnt/user-data/outputs/stats.json")
        execute_python(description="Plot chart", code="import matplotlib; matplotlib.use('Agg')\\nimport matplotlib.pyplot as plt\\nplt.plot([1,2,3])")

    Args:
        description: Explain the purpose of this code execution in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        code: The Python code to execute. Include all necessary imports. Each execution is stateless.
        save_output_to: Optional absolute path to save the full (untruncated) output. Useful when output may exceed the display limit.
    """
    if not code or not code.strip():
        return "Error: No code provided"

    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)

        thread_data = get_thread_data(runtime) if is_local_sandbox(runtime) else None

        # Write code to a temp file in workspace
        workspace_path = "/mnt/user-data/workspace"
        if is_local_sandbox(runtime) and thread_data:
            workspace_path = replace_virtual_path(workspace_path, thread_data)

        # Create temp script
        os.makedirs(workspace_path, exist_ok=True)
        script_name = f"_exec_{os.getpid()}_{id(code)}.py"
        script_path = os.path.join(workspace_path, script_name)

        try:
            # Write the code
            with open(script_path, "w") as f:
                f.write(code)

            # Execute via sandbox
            virtual_script_path = f"/mnt/user-data/workspace/{script_name}"
            if is_local_sandbox(runtime):
                # For local sandbox, use the actual path
                output = sandbox.execute_command(f"python {script_path}")
            else:
                output = sandbox.execute_command(f"python {virtual_script_path}")

        finally:
            # Clean up temp script
            try:
                os.remove(script_path)
            except OSError:
                pass

        # Save full output if requested
        if save_output_to and output:
            save_path = save_output_to
            if is_local_sandbox(runtime) and thread_data:
                save_path = replace_virtual_path(save_path, thread_data)
            try:
                save_dir = os.path.dirname(save_path)
                if save_dir:
                    os.makedirs(save_dir, exist_ok=True)
                with open(save_path, "w") as f:
                    f.write(output)
            except OSError as e:
                logger.warning("Failed to save output to %s: %s", save_output_to, e)

        # Truncate output for context efficiency
        if not output:
            return "(no output)"

        if len(output) <= MAX_OUTPUT_LENGTH:
            return output

        truncated = truncate_output(output, MAX_OUTPUT_LENGTH)
        notice = f"\n\n[Output truncated — {len(output)} chars total]"
        if save_output_to:
            notice += f"\n[Full output saved to {save_output_to}]"
        else:
            notice += "\n[Use save_output_to parameter to save the full output]"
        return truncated + notice

    except SandboxError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: Unexpected error executing Python code: {type(e).__name__}: {e}"
