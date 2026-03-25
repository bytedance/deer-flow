"""Built-in tool for invoking external ACP-compatible agents."""

import logging
import os
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class _InvokeACPAgentInput(BaseModel):
    agent: str = Field(description="Name of the ACP agent to invoke")
    prompt: str = Field(description="The task prompt to send to the agent")
    cwd: str | None = Field(
        default=None,
        description="Working directory for the agent subprocess. "
        "Use /mnt/user-data/workspace to run in the thread workspace. "
        "Defaults to the current thread's workspace when available.",
    )


def _resolve_cwd(cwd: str | None) -> str:
    """Resolve cwd: translate virtual paths and apply thread-workspace default.

    Args:
        cwd: Virtual or physical path, or None to use the thread workspace default.

    Returns:
        An absolute physical filesystem path to use as the working directory.
    """
    if cwd is None:
        # Try to use the current thread's workspace directory
        try:
            from langgraph.config import get_config

            config = get_config()
            thread_id = config.get("configurable", {}).get("thread_id")
            if thread_id:
                from deerflow.config.paths import get_paths

                workspace = get_paths().sandbox_work_dir(thread_id)
                if workspace.exists():
                    return str(workspace)
        except Exception:
            pass
        return os.path.abspath(os.getcwd())

    # Translate DeerFlow virtual paths (/mnt/user-data/...) to physical paths
    from deerflow.config.paths import VIRTUAL_PATH_PREFIX

    if cwd.startswith(VIRTUAL_PATH_PREFIX) or cwd.startswith("/mnt/user-data"):
        try:
            from langgraph.config import get_config

            config = get_config()
            thread_id = config.get("configurable", {}).get("thread_id")
            if thread_id:
                from deerflow.config.paths import get_paths

                return str(get_paths().resolve_virtual_path(thread_id, cwd))
        except Exception as e:
            logger.warning("Failed to translate virtual path %r: %s", cwd, e)

    return os.path.abspath(cwd)


def _build_mcp_servers() -> dict[str, dict[str, Any]]:
    """Build ACP ``mcpServers`` config from DeerFlow's enabled MCP servers."""
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.client import build_servers_config

    return build_servers_config(ExtensionsConfig.from_file())


def _build_permission_response(options: list[Any]):
    """Auto-approve ACP permission requests one call at a time when possible."""
    from acp import RequestPermissionResponse
    from acp.schema import AllowedOutcome, DeniedOutcome

    for preferred_kind in ("allow_once", "allow_always"):
        for option in options:
            if getattr(option, "kind", None) != preferred_kind:
                continue

            option_id = getattr(option, "option_id", None)
            if option_id is None:
                option_id = getattr(option, "optionId")

            return RequestPermissionResponse(
                outcome=AllowedOutcome(outcome="selected", optionId=option_id),
            )

    return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))


def build_invoke_acp_agent_tool(agents: dict) -> BaseTool:
    """Create the ``invoke_acp_agent`` tool with a description generated from configured agents.

    The tool description includes the list of available agents so that the LLM
    knows which agents it can invoke without requiring hardcoded names.

    Args:
        agents: Mapping of agent name -> ``ACPAgentConfig``.

    Returns:
        A LangChain ``BaseTool`` ready to be included in the tool list.
    """
    agent_lines = "\n".join(f"- {name}: {cfg.description}" for name, cfg in agents.items())
    description = f"Invoke an external ACP-compatible agent and return its final response.\n\nAvailable agents:\n{agent_lines}"

    # Capture agents in closure so the function can reference it
    _agents = dict(agents)

    async def _invoke(agent: str, prompt: str, cwd: str | None = None) -> str:
        if agent not in _agents:
            available = ", ".join(_agents.keys())
            return f"Error: Unknown agent '{agent}'. Available: {available}"

        agent_config = _agents[agent]

        try:
            from acp import PROTOCOL_VERSION, Client, text_block
            from acp.schema import ClientCapabilities, Implementation
        except ImportError:
            return (
                "Error: agent-client-protocol package is not installed. "
                "Run `uv sync` to install project dependencies."
            )

        class _CollectingClient(Client):
            """Minimal ACP Client that collects streamed text from session updates."""

            def __init__(self) -> None:
                self._chunks: list[str] = []

            @property
            def collected_text(self) -> str:
                return "".join(self._chunks)

            async def session_update(self, session_id: str, update, **kwargs) -> None:  # type: ignore[override]
                try:
                    from acp.schema import TextContentBlock

                    if hasattr(update, "content") and isinstance(update.content, TextContentBlock):
                        self._chunks.append(update.content.text)
                except Exception:
                    pass

            async def request_permission(self, options, session_id: str, tool_call, **kwargs):  # type: ignore[override]
                response = _build_permission_response(options)
                outcome = response.outcome.outcome
                if outcome == "selected":
                    logger.info("ACP permission auto-approved for tool call %s in session %s", tool_call.tool_call_id, session_id)
                else:
                    logger.warning("ACP permission denied for tool call %s in session %s", tool_call.tool_call_id, session_id)
                return response

        client = _CollectingClient()
        cmd = agent_config.command
        args = agent_config.args or []
        physical_cwd = _resolve_cwd(cwd)
        mcp_servers = _build_mcp_servers()

        try:
            from acp import spawn_agent_process

            async with spawn_agent_process(client, cmd, *args, cwd=physical_cwd) as (conn, proc):
                await conn.initialize(
                    protocol_version=PROTOCOL_VERSION,
                    client_capabilities=ClientCapabilities(),
                    client_info=Implementation(name="deerflow", title="DeerFlow", version="0.1.0"),
                )
                session_kwargs: dict[str, Any] = {"cwd": physical_cwd, "mcp_servers": mcp_servers}
                if agent_config.model:
                    session_kwargs["model"] = agent_config.model
                session = await conn.new_session(**session_kwargs)
                await conn.prompt(
                    session_id=session.session_id,
                    prompt=[text_block(prompt)],
                )
            result = client.collected_text
            logger.info("ACP agent '%s' returned %d characters", agent, len(result))
            return result or "(no response)"
        except Exception as e:
            logger.error("ACP agent '%s' invocation failed: %s", agent, e)
            return f"Error invoking ACP agent '{agent}': {e}"

    return StructuredTool.from_function(
        name="invoke_acp_agent",
        description=description,
        coroutine=_invoke,
        args_schema=_InvokeACPAgentInput,
    )
