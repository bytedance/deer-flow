"""Report executor routing middleware.

Routes report execution based on agent config.executor_type:
- Agents with executor_type="direct" use direct execution
- Agents with executor_type="dsl" (or None) use DSL template engine
"""

from typing import Any

DEFAULT_EXECUTOR_TYPE = "dsl"


def get_executor_type_from_config(agent_config: Any) -> str:
    """Extract executor_type from agent config.

    Args:
        agent_config: AgentConfig instance or dict

    Returns:
        "direct" or "dsl"
    """
    if agent_config is None:
        return DEFAULT_EXECUTOR_TYPE

    # Handle both AgentConfig objects and dicts
    if hasattr(agent_config, "executor_type"):
        executor_type = agent_config.executor_type
    elif isinstance(agent_config, dict):
        executor_type = agent_config.get("executor_type")
    else:
        return DEFAULT_EXECUTOR_TYPE

    return executor_type if executor_type in ("direct", "dsl") else DEFAULT_EXECUTOR_TYPE


def is_direct_executor_agent(agent_config: Any) -> bool:
    """Check if the agent uses direct execution.

    Args:
        agent_config: AgentConfig instance or dict

    Returns:
        True if executor_type is "direct", False otherwise
    """
    return get_executor_type_from_config(agent_config) == "direct"


def get_report_tools_for_agent(agent_config: Any) -> list[Any]:
    """Get the appropriate report tools for an agent based on config.

    Args:
        agent_config: AgentConfig instance or dict

    Returns:
        List of tools to bind to the agent
    """
    from deerflow.tools.builtins import (
        REPORT_TEMPLATE_LIFECYCLE_TOOLS,
        REPORT_TEMPLATE_RUNTIME_TOOLS,
    )
    from deerflow.tools.builtins.report_direct_tools import report_direct_execute
    from deerflow.tools.builtins import report_template_record_fallback_tool

    if is_direct_executor_agent(agent_config):
        # Direct execution path
        return [report_direct_execute]
    else:
        # DSL template engine path
        return [
            *REPORT_TEMPLATE_LIFECYCLE_TOOLS,
            *REPORT_TEMPLATE_RUNTIME_TOOLS,
            report_template_record_fallback_tool,
        ]
