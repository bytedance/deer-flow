"""Python code execution tool."""

import io
import sys
import traceback
import contextlib

from langchain.tools import tool


@tool("python_exec", parse_docstring=True)
def python_exec_tool(code: str) -> str:
    """Execute Python code and return output.

    Args:
        code: Python code to execute
    """
    output = io.StringIO()
    error_output = io.StringIO()

    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error_output):
            exec(code, {"__builtins__": __builtins__})

        result = output.getvalue()
        err = error_output.getvalue()

        if err:
            result = result + "\n[STDERR]: " + err if result else err

        return result if result else "(No output)"
    except Exception:
        return f"Error: {traceback.format_exc()}"
