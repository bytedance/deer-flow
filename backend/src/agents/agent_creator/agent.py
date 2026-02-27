"""Agent Creator — a conversational LangGraph agent for designing custom agents."""

from __future__ import annotations

import logging
import re
from typing import Annotated

import yaml
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from src.agents.agent_creator.prompt import AGENT_CREATOR_SYSTEM_PROMPT
from src.config.paths import get_paths
from src.models import create_chat_model

logger = logging.getLogger(__name__)

AGENT_NAME_RE = re.compile(r"^[a-z0-9-]+$")


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class AgentCreatorState(TypedDict):
    messages: Annotated[list, add_messages]
    created_agent_name: str | None


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


@tool
def create_custom_agent(
    name: str,
    soul: str,
    description: str = "",
    model: str | None = None,
    tool_groups: list[str] | None = None,
) -> dict:
    """Create a custom DeerFlow agent by writing its config.yaml and SOUL.md.

    Call this once you have gathered enough information from the user conversation
    to fully describe the agent's identity and capabilities.

    Args:
        name: Agent name — must match ^[a-z0-9-]+$ (lowercase, digits, hyphens).
        soul: Full SOUL.md content defining the agent's personality and behavior.
        description: One-line description of what the agent does.
        model: Optional model override (e.g. "deepseek-v3"). Leave None for default.
        tool_groups: Optional list of tool group names. None means all tools.

    Returns:
        dict with "status" and "name" keys.
    """
    if not AGENT_NAME_RE.match(name):
        return {"status": "error", "message": f"Invalid name '{name}'. Use only lowercase letters, digits, and hyphens."}

    paths = get_paths()
    agent_dir = paths.agent_dir(name)

    if agent_dir.exists():
        return {"status": "error", "message": f"Agent '{name}' already exists."}

    try:
        agent_dir.mkdir(parents=True, exist_ok=True)

        config_data: dict = {"name": name}
        if description:
            config_data["description"] = description
        if model is not None:
            config_data["model"] = model
        if tool_groups is not None:
            config_data["tool_groups"] = tool_groups

        config_file = agent_dir / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)

        soul_file = agent_dir / "SOUL.md"
        soul_file.write_text(soul, encoding="utf-8")

        logger.info(f"[agent_creator] Created agent '{name}' at {agent_dir}")
        return {"status": "created", "name": name}

    except Exception as e:
        import shutil

        if agent_dir.exists():
            shutil.rmtree(agent_dir)
        logger.error(f"[agent_creator] Failed to create agent '{name}': {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


def _agent_node(state: AgentCreatorState, config: RunnableConfig):
    """Call the LLM with tool binding."""
    model_name = config.get("configurable", {}).get("model_name") or config.get("configurable", {}).get("model")
    llm = create_chat_model(name=model_name, thinking_enabled=False)
    llm_with_tools = llm.bind_tools([create_custom_agent])

    from langchain_core.messages import SystemMessage

    system = SystemMessage(content=AGENT_CREATOR_SYSTEM_PROMPT)
    response = llm_with_tools.invoke([system] + state["messages"])
    return {"messages": [response]}


def _tools_node(state: AgentCreatorState):
    """Execute tool calls and detect successful agent creation."""
    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", [])

    tool_messages = []
    created_name: str | None = None

    for tc in tool_calls:
        if tc["name"] == "create_custom_agent":
            result = create_custom_agent.invoke(tc["args"])
            tool_messages.append(
                ToolMessage(
                    content=str(result),
                    tool_call_id=tc["id"],
                )
            )
            if isinstance(result, dict) and result.get("status") == "created":
                created_name = result.get("name")

    updates: dict = {"messages": tool_messages}
    if created_name is not None:
        updates["created_agent_name"] = created_name

    return updates


def _route(state: AgentCreatorState):
    """Route: if the last message has tool_calls go to tools_node, else END."""
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return "tools"
    return END


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_agent_creator(config: RunnableConfig):
    """Build and compile the agent_creator graph.

    This factory is registered in langgraph.json and called per-request.
    """
    graph = StateGraph(AgentCreatorState)
    graph.add_node("agent", _agent_node)
    graph.add_node("tools", _tools_node)

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", _route, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile()
