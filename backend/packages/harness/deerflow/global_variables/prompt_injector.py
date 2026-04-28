"""Global variables prompt injection module."""

import logging
import re
from typing import Any

from deerflow.config import get_global_variables_config
from deerflow.global_variables.storage import get_storage

logger = logging.getLogger(__name__)

_VARIABLE_PATTERN = re.compile(r"\{\{(\w+)\}\}")


def get_merged_variables(thread_id: str | None = None) -> dict[str, Any]:
    """Merge project-level and thread-level variables.

    Thread-level variables override project-level variables with the same key.
    """
    project_data = get_storage().load("project")
    project_vars: dict[str, Any] = project_data.get("variables", {})

    if thread_id:
        thread_data = get_storage().load("thread", thread_id=thread_id)
        thread_vars: dict[str, Any] = thread_data.get("variables", {})
    else:
        thread_vars = {}

    merged = {**project_vars}
    merged.update(thread_vars)
    return merged


def replace_template_variables(text: str, thread_id: str | None = None) -> str:
    """Replace {{variable_name}} placeholders in text with actual variable values.

    Args:
        text: The text containing {{variable_name}} placeholders.
        thread_id: Optional thread ID for thread-level variable override.

    Returns:
        Text with placeholders replaced by actual values.
        Placeholders for non-existent variables are left unchanged.
    """
    merged_vars = get_merged_variables(thread_id=thread_id)

    def _replacer(match: re.Match) -> str:
        var_name = match.group(1)
        var_data = merged_vars.get(var_name)
        if var_data is None:
            return match.group(0)
        if isinstance(var_data, dict):
            return str(var_data.get("value", match.group(0)))
        return str(var_data)

    return _VARIABLE_PATTERN.sub(_replacer, text)


def build_prompt_section(thread_id: str | None = None) -> str:
    """Build the global variables section for prompt injection (legacy, kept for compatibility).

    Returns empty string if global variables are disabled or no variables exist.
    """
    config = get_global_variables_config()
    if not config.enabled or not config.injection_enabled:
        return ""

    merged_vars = get_merged_variables(thread_id)
    if not merged_vars:
        return ""

    lines = []
    total_length = 0

    for key, var_info in merged_vars.items():
        if isinstance(var_info, dict):
            value = var_info.get("value", "")
            description = var_info.get("description", "")
        else:
            value = str(var_info)
            description = ""

        line = f"- {key} = {value}"
        if description:
            line += f"  # {description}"

        if total_length + len(line) > config.max_total_prompt_length:
            logger.warning("Truncating global variables section due to max length limit")
            break

        lines.append(line)
        total_length += len(line)

    if not lines:
        return ""

    section = "\n".join(lines)
    return f"<global_variables>\n{section}\n</global_variables>\n"
