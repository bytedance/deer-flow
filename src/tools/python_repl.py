# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
import os
from typing import Annotated, Optional, Tuple

from langchain_core.tools import tool
from langchain_experimental.utilities import PythonREPL

from .decorators import log_io


def _is_python_repl_enabled() -> bool:
    """Check if Python REPL tool is enabled from configuration."""
    # Check environment variable first
    env_enabled = os.getenv("ENABLE_PYTHON_REPL", "false").lower()
    if env_enabled in ("true", "1", "yes", "on"):
        return True
    return False


def _auto_fix_unterminated_triple_quotes(code: str) -> Tuple[str, bool]:
    """
    Attempt to automatically fix unterminated triple-quoted strings by appending the closing quotes.

    Args:
        code: The original Python code submitted to the REPL

    Returns:
        A tuple of (fixed_code, was_fixed)
    """
    fixed_code = code.rstrip()
    was_fixed = False

    for quote in ("'''", '"""'):
        quote_count = fixed_code.count(quote)
        if quote_count % 2 != 0:
            logger.warning(
                "Detected unmatched triple quotes (%s) in Python REPL input. Auto-appending closing quotes.",
                quote,
            )
            fixed_code = f"{fixed_code}\n{quote}"
            was_fixed = True

    if was_fixed:
        fixed_code = f"{fixed_code}\n"

    return fixed_code, was_fixed


# Initialize REPL and logger
repl: Optional[PythonREPL] = PythonREPL() if _is_python_repl_enabled() else None
logger = logging.getLogger(__name__)


@tool
@log_io
def python_repl_tool(
    code: Annotated[
        str, "The python code to execute to do further analysis or calculation."
    ],
):
    """Use this to execute python code and do data analysis or calculation. If you want to see the output of a value,
    you should print it out with `print(...)`. This is visible to the user."""

    # Check if the tool is enabled
    if not _is_python_repl_enabled():
        error_msg = "Python REPL tool is disabled. Please enable it in environment configuration."
        logger.warning(error_msg)
        return f"Tool disabled: {error_msg}"

    if not isinstance(code, str):
        error_msg = f"Invalid input: code must be a string, got {type(code)}"
        logger.error(error_msg)
        return f"Error executing code:\n```python\n{code}\n```\nError: {error_msg}"

    logger.info("Executing Python code")
    try:
        result = repl.run(code)
        # Check if the result is an error message by looking for typical error patterns
        if isinstance(result, str) and ("Error" in result or "Exception" in result):
            logger.error(result)
            return f"Error executing code:\n```python\n{code}\n```\nError: {result}"
        logger.info("Code execution successful")
    except SyntaxError as e:
        error_msg = repr(e)
        if "unterminated triple-quoted string literal" in error_msg:
            fixed_code, was_fixed = _auto_fix_unterminated_triple_quotes(code)
            if was_fixed:
                try:
                    result = repl.run(fixed_code)
                    logger.info(
                        "Code execution successful after auto-fixing unmatched triple quotes"
                    )
                    return (
                        "Successfully executed after auto-fixing unterminated triple-quoted string:\n"
                        f"```python\n{fixed_code}\n```\nStdout: {result}"
                    )
                except BaseException as retry_error:
                    retry_msg = repr(retry_error)
                    logger.error(
                        "Auto-fix for triple quotes failed with: %s", retry_msg
                    )
                    return (
                        "Error executing code even after attempting to auto-fix unterminated triple-quoted string:\n"
                        f"```python\n{code}\n```\n"
                        f"Auto-fix attempt:\n```python\n{fixed_code}\n```\n"
                        f"Original error: {error_msg}\n"
                        f"Auto-fix error: {retry_msg}"
                    )
        logger.error(error_msg)
        return f"Error executing code:\n```python\n{code}\n```\nError: {error_msg}"
    except BaseException as e:
        error_msg = repr(e)
        logger.error(error_msg)
        return f"Error executing code:\n```python\n{code}\n```\nError: {error_msg}"

    result_str = f"Successfully executed:\n```python\n{code}\n```\nStdout: {result}"
    return result_str
