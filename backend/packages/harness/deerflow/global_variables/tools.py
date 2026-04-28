"""Global variables tools for LLM interaction."""

from __future__ import annotations

import logging
from typing import Any

from langchain.tools import ToolRuntime, tool
from langgraph.typing import ContextT

from deerflow.agents.thread_state import ThreadState
from deerflow.config import get_global_variables_config
from deerflow.global_variables.storage import get_storage

logger = logging.getLogger(__name__)


def _get_thread_id(runtime: ToolRuntime[ContextT, ThreadState] | None) -> str | None:
    if runtime is None:
        return None
    if runtime.context and runtime.context.get("thread_id"):
        return runtime.context.get("thread_id")
    return runtime.config.get("configurable", {}).get("thread_id")


def _validate_key(key: str) -> str:
    if not key or not isinstance(key, str):
        raise ValueError("Variable key must be a non-empty string")
    if len(key) > 100:
        raise ValueError("Variable key must be at most 100 characters")
    return key.strip()


def _validate_value(value: Any) -> str:
    config = get_global_variables_config()
    str_value = str(value)
    if len(str_value) > config.max_value_length:
        raise ValueError(f"Variable value exceeds maximum length of {config.max_value_length} characters")
    return str_value


def _get_var_info(var_data: dict[str, Any], key: str) -> str | None:
    variables = var_data.get("variables", {})
    if key not in variables:
        return None
    var = variables[key]
    if isinstance(var, dict):
        return f"{key} = {var.get('value', '')} (updated_at: {var.get('updated_at', 'unknown')}, updated_by: {var.get('updated_by', 'unknown')})"
    return f"{key} = {var}"


def _check_llm_editable(var_data: dict[str, Any], key: str) -> str | None:
    """Check if a variable can be edited by LLM. Returns error message if not editable, None if OK."""
    variables = var_data.get("variables", {})
    existing = variables.get(key)
    if existing is None:
        return None
    if isinstance(existing, dict):
        if existing.get("is_system"):
            return f"Error: variable '{key}' is a system variable and cannot be modified"
        if not existing.get("llm_editable", True):
            return f"Error: variable '{key}' is not editable by the AI assistant"
    return None


@tool("get_variable", parse_docstring=True)
def get_variable_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    key: str,
    scope: str = "project",
) -> str:
    """Get the value of a global variable.

    Args:
        key: The variable key to retrieve.
        scope: The scope of the variable. Must be 'project' or 'thread'.
    """
    if scope not in ("project", "thread"):
        return f"Error: scope must be 'project' or 'thread', got '{scope}'"

    try:
        key = _validate_key(key)
    except ValueError as e:
        return f"Error: {e}"

    thread_id = _get_thread_id(runtime)
    data = get_storage().load(scope, thread_id=thread_id)
    result = _get_var_info(data, key)

    if result is None:
        return f"Variable '{key}' not found in {scope} scope"
    return result


@tool("set_variable", parse_docstring=True)
def set_variable_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    key: str,
    value: str,
    scope: str = "project",
    description: str = "",
) -> str:
    """Set the value of a global variable.

    Args:
        key: The variable key to set.
        value: The variable value.
        scope: The scope of the variable. Must be 'project' or 'thread'.
        description: Optional description of the variable.
    """
    if scope not in ("project", "thread"):
        return f"Error: scope must be 'project' or 'thread', got '{scope}'"

    try:
        key = _validate_key(key)
        value = _validate_value(value)
    except ValueError as e:
        return f"Error: {e}"

    config = get_global_variables_config()
    if not config.enabled:
        return "Error: global variables system is disabled"

    thread_id = _get_thread_id(runtime)
    data = get_storage().load(scope, thread_id=thread_id)

    error = _check_llm_editable(data, key)
    if error:
        return error

    variables = data.get("variables", {})

    if len(variables) >= config.max_variables_per_scope:
        return f"Error: {scope} scope has reached maximum variables limit ({config.max_variables_per_scope})"

    from deerflow.global_variables.storage import utc_now_iso_z

    existing = variables.get(key, {})
    existing_llm_editable = existing.get("llm_editable", True) if isinstance(existing, dict) else True

    variables[key] = {
        "value": value,
        "description": description,
        "llm_editable": existing_llm_editable,
        "updated_at": utc_now_iso_z(),
        "updated_by": "llm",
    }
    data["variables"] = variables
    get_storage().save(data, scope, thread_id=thread_id)

    return f"Set variable '{key}' = '{value}' in {scope} scope"


@tool("delete_variable", parse_docstring=True)
def delete_variable_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    key: str,
    scope: str = "project",
) -> str:
    """Delete a global variable.

    Args:
        key: The variable key to delete.
        scope: The scope of the variable. Must be 'project' or 'thread'.
    """
    if scope not in ("project", "thread"):
        return f"Error: scope must be 'project' or 'thread', got '{scope}'"

    try:
        key = _validate_key(key)
    except ValueError as e:
        return f"Error: {e}"

    thread_id = _get_thread_id(runtime)
    data = get_storage().load(scope, thread_id=thread_id)

    error = _check_llm_editable(data, key)
    if error:
        return error

    variables = data.get("variables", {})

    if key not in variables:
        return f"Variable '{key}' not found in {scope} scope"

    del variables[key]
    data["variables"] = variables
    get_storage().save(data, scope, thread_id=thread_id)

    return f"Deleted variable '{key}' from {scope} scope"


@tool("list_variables", parse_docstring=True)
def list_variables_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    scope: str = "project",
) -> str:
    """List all global variables in a scope.

    Args:
        scope: The scope of the variables. Must be 'project' or 'thread'.
    """
    if scope not in ("project", "thread"):
        return f"Error: scope must be 'project' or 'thread', got '{scope}'"

    thread_id = _get_thread_id(runtime)
    data = get_storage().load(scope, thread_id=thread_id)
    variables = data.get("variables", {})

    if not variables:
        return f"No variables found in {scope} scope"

    lines = [f"Variables in {scope} scope:"]
    for key, var in variables.items():
        if isinstance(var, dict):
            lines.append(f"  - {key} = {var.get('value', '')}")
        else:
            lines.append(f"  - {key} = {var}")

    return "\n".join(lines)
