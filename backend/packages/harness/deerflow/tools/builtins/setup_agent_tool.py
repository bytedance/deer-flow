import logging
import os
import tempfile

import yaml
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)


def _atomic_write_text(path, content: str, encoding: str = "utf-8") -> None:
    """Write content to a file atomically via a temp file + os.replace."""
    dir_path = path.parent
    fd, tmp = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


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

    try:
        paths = get_paths()
        agent_dir = paths.agent_dir(agent_name) if agent_name else paths.base_dir
        agent_dir.mkdir(parents=True, exist_ok=True)

        if agent_name:
            config_file = agent_dir / "config.yaml"

            # Idempotency: skip if config already exists and is valid
            if config_file.exists():
                try:
                    existing = yaml.safe_load(config_file.read_text(encoding="utf-8"))
                    if isinstance(existing, dict) and existing.get("name") == agent_name:
                        logger.info(f"[agent_creator] Agent '{agent_name}' already exists, skipping config write")
                        # Still update SOUL.md in case content changed
                        _atomic_write_text(agent_dir / "SOUL.md", soul)
                        return Command(
                            update={
                                "messages": [ToolMessage(content=f"Agent '{agent_name}' created successfully!", tool_call_id=runtime.tool_call_id)],
                            }
                        )
                except Exception:
                    pass  # Config exists but is invalid, overwrite it

            config_data: dict = {"name": agent_name}
            if description:
                config_data["description"] = description

            # Atomic write to prevent corruption from concurrent calls
            _atomic_write_text(config_file, yaml.dump(config_data, default_flow_style=False, allow_unicode=True))

        _atomic_write_text(agent_dir / "SOUL.md", soul)

        logger.info(f"[agent_creator] Created agent '{agent_name}' at {agent_dir}")
        return Command(
            update={
                "messages": [ToolMessage(content=f"Agent '{agent_name}' created successfully!", tool_call_id=runtime.tool_call_id)],
            }
        )

    except Exception as e:
        import shutil

        if agent_name and agent_dir.exists():
            # Cleanup the custom agent directory only if it was created but an error occurred during setup
            shutil.rmtree(agent_dir)
        logger.error(f"[agent_creator] Failed to create agent '{agent_name}': {e}", exc_info=True)
        return Command(update={"messages": [ToolMessage(content=f"Error: {e}", tool_call_id=runtime.tool_call_id)]})
