"""MCP server that exposes DeerFlow's lead agent as tool-callable endpoints.

Run with:
    cd backend && PYTHONPATH=. uv run python -m deerflow.mcp.server

Or via Makefile:
    make mcp-server

The server uses stdio transport and exposes two tools:
- ``deerflow_research``: Deep research with planning, web search, and multi-step reasoning.
- ``deerflow_ask``: Quick Q&A without planning overhead.

Configuration is resolved through DeerFlow's standard ``AppConfig.resolve_config_path()``
mechanism (``DEER_FLOW_CONFIG_PATH`` env var, or ``config.yaml`` in cwd / parent).
"""

from __future__ import annotations

import logging
import sys
import uuid

from langchain_core.messages import HumanMessage
from mcp.server.fastmcp import FastMCP

from deerflow.agents import make_lead_agent

logger = logging.getLogger("deerflow.mcp.server")

_mcp_tools_initialized = False


async def _ensure_mcp_tools() -> None:
    """Lazily initialise external MCP tools that the lead agent may call."""
    global _mcp_tools_initialized
    if _mcp_tools_initialized:
        return
    try:
        from deerflow.mcp import initialize_mcp_tools

        await initialize_mcp_tools()
    except Exception as exc:
        logger.warning("Failed to initialize DeerFlow MCP tools: %s", exc)
    _mcp_tools_initialized = True


async def _invoke_agent(
    query: str,
    *,
    thinking: bool = True,
    plan_mode: bool = False,
    model_name: str | None = None,
) -> str:
    """Invoke the DeerFlow lead agent and return its final text response.

    Args:
        query: The user query to send to the agent.
        thinking: Whether to enable the thinking/reasoning mode.
        plan_mode: Whether to enable multi-step planning.
        model_name: Override the default model.

    Returns:
        The agent's final text content, optionally followed by artifacts.
    """
    await _ensure_mcp_tools()

    thread_id = f"mcp-{uuid.uuid4().hex[:12]}"
    config: dict = {
        "configurable": {
            "thread_id": thread_id,
            "thinking_enabled": thinking,
            "is_plan_mode": plan_mode,
        }
    }
    if model_name:
        config["configurable"]["model_name"] = model_name

    agent = make_lead_agent(config)
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=query)]},
        config=config,
    )

    messages = result.get("messages", [])
    if not messages:
        return "(DeerFlow returned no messages)"

    last = messages[-1]
    content = getattr(last, "content", None) or str(last)

    artifacts = result.get("artifacts", [])
    if artifacts:
        content += "\n\n--- Artifacts ---\n" + "\n".join(artifacts)

    return content


def create_mcp_server() -> FastMCP:
    """Create and return a configured ``FastMCP`` server instance.

    The returned server exposes ``deerflow_research`` and ``deerflow_ask`` tools.
    Call ``server.run(transport="stdio")`` to start it.
    """
    server = FastMCP(
        "deerflow",
        instructions="DeerFlow AI agent tools. Use these to perform deep research with web search, generate code, or answer complex questions.",
    )

    @server.tool()
    async def deerflow_research(query: str) -> str:
        """Deep research using DeerFlow's AI agent with web search, planning, and multi-step reasoning.

        Best for questions that benefit from:
        - Web search and information gathering
        - Multi-step research plans
        - Synthesizing information from multiple sources
        - Generating comprehensive reports

        Args:
            query: The research question or topic to investigate.
        """
        return await _invoke_agent(query, thinking=True, plan_mode=True)

    @server.tool()
    async def deerflow_ask(question: str) -> str:
        """Ask DeerFlow's AI agent a direct question (no planning, faster response).

        Best for:
        - Quick factual questions
        - Code explanations
        - Simple tasks that don't need web search or multi-step planning

        Args:
            question: The question to answer.
        """
        return await _invoke_agent(question, thinking=True, plan_mode=False)

    return server


def main() -> None:
    """Entry point for ``python -m deerflow.mcp.server``."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    server = create_mcp_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
