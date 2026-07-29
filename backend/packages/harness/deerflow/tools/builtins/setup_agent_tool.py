import logging

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command

from deerflow.config.agents_config import SOUL_FILENAME, validate_agent_name
from deerflow.config.paths import get_paths
from deerflow.persistence.agents import get_agent_store
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)


@tool(parse_docstring=True)
def setup_agent(
    soul: str,
    description: str,
    runtime: Runtime,
    skills: list[str] | None = None,
) -> Command:
    """Setup the custom DeerFlow agent.

    Args:
        soul: Full SOUL.md content defining the agent's personality and behavior.
        description: One-line description of what the agent does.
        skills: Optional list of skill names this agent should use. None means use all enabled skills, empty list means no skills.
    """

    # Reject empty / whitespace-only soul before touching the filesystem.
    # Without this guard the tool would happily persist an empty SOUL.md and
    # still report success, which caused the frontend to enter the "agent
    # created" state for an unusable agent (issue #3549). Failing loud lets
    # the model retry instead of silently producing a broken artifact and,
    # together with the upstream agent_name fix, prevents the global default
    # SOUL.md from being overwritten with empty content.
    if not soul or not soul.strip():
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="Error: soul content is empty; refusing to create agent with an empty SOUL.md",
                        tool_call_id=runtime.tool_call_id,
                    )
                ]
            }
        )

    agent_name: str | None = runtime.context.get("agent_name") if runtime.context else None

    try:
        agent_name = validate_agent_name(agent_name)
        if agent_name:
            # Custom agents are persisted under the current user's bucket (via
            # the configured store — file or db) so different users, and
            # different nodes, resolve the same agent. setup is idempotent, so
            # this is an upsert.
            user_id = resolve_runtime_user_id(runtime)
            config_data: dict = {"name": agent_name}
            if description:
                config_data["description"] = description
            if skills is not None:
                config_data["skills"] = skills
            get_agent_store().update(agent_name, config_data, soul, user_id=user_id)
        else:
            # Default agent (no agent_name): SOUL.md lives at the global base
            # dir. It is not a custom-agent record, so it stays file-based
            # regardless of the agent-storage backend.
            paths = get_paths()
            paths.base_dir.mkdir(parents=True, exist_ok=True)
            (paths.base_dir / SOUL_FILENAME).write_text(soul, encoding="utf-8")

        logger.info(f"[agent_creator] Created agent '{agent_name}'")
        return Command(
            update={
                "created_agent_name": agent_name,
                "messages": [ToolMessage(content=f"Agent '{agent_name}' created successfully!", tool_call_id=runtime.tool_call_id)],
            }
        )

    except Exception as e:
        logger.error(f"[agent_creator] Failed to create agent '{agent_name}': {e}", exc_info=True)
        return Command(update={"messages": [ToolMessage(content=f"Error: {e}", tool_call_id=runtime.tool_call_id)]})
