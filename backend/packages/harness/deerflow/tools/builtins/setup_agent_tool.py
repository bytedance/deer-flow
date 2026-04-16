import logging

import yaml
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

from deerflow.config.agents_config import validate_agent_name
from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)


@tool
def setup_agent(
    soul: str,
    description: str,
    runtime: ToolRuntime,
) -> Command:
    """Setup the custom DeerFlow agent.

    Args:
        soul: Full SOUL.md content defining the agent's personality and behavior.
        description: One-line description of what the agent does.
    """

    agent_name: str | None = runtime.context.get("agent_name") if runtime.context else None
    agent_dir = None

    try:
        agent_name = validate_agent_name(agent_name)
        paths = get_paths()
        agent_dir = paths.agent_dir(agent_name) if agent_name else paths.base_dir
        agent_dir.mkdir(parents=True, exist_ok=True)

        if agent_name:
            # If agent_name is provided, we are creating a custom agent in the agents/ directory
            config_data: dict = {"name": agent_name}
            if description:
                config_data["description"] = description

            config_file = agent_dir / "config.yaml"
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)

        soul_file = agent_dir / "SOUL.md"
        soul_file.write_text(soul, encoding="utf-8")

        logger.info(f"[agent_creator] Created agent '{agent_name}' at {agent_dir}")
        return Command(
            update={
                "created_agent_name": agent_name,
                "messages": [ToolMessage(content=f"Agent '{agent_name}' created successfully!", tool_call_id=runtime.tool_call_id)],
            }
        )

    except Exception as e:
        import shutil

        if agent_name and agent_dir is not None and agent_dir.exists():
            # Cleanup the custom agent directory only if it was created but an error occurred during setup
            shutil.rmtree(agent_dir)
        logger.error(f"[agent_creator] Failed to create agent '{agent_name}': {e}", exc_info=True)
        return Command(update={"messages": [ToolMessage(content=f"Error: {e}", tool_call_id=runtime.tool_call_id)]})
