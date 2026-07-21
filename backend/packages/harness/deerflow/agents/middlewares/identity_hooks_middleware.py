"""Optional identity-provider MCP hooks at thread/session start.

Fires configured ``sessionStart`` tool calls against an external MCP server
(e.g. Lithtrix) without importing provider code into DeerFlow core. Hook
results are normalized into a bounded, tag-neutralized HumanMessage (never
system-role authority) so substrate context reaches the model. Failures are
logged and ignored so research is not blocked by substrate outages.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.config import get_config
from langgraph.runtime import Runtime

from deerflow.config.extensions_config import ExtensionsConfig, get_extensions_config
from deerflow.mcp.client import build_server_params
from deerflow.mcp.session_pool import get_session_pool
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)

IDENTITY_HOOKS_CONTEXT_KEY = "identity_hooks_external_context"
_EXTERNAL_CONTEXT_BEGIN = "--- BEGIN EXTERNAL IDENTITY CONTEXT (untrusted) ---"
_EXTERNAL_CONTEXT_END = "--- END EXTERNAL IDENTITY CONTEXT ---"
_IDENTITY_HOOKS_MAX_TOOL_CHARS = 16_000
_IDENTITY_HOOKS_MAX_TOTAL_CHARS = 32_000


def _resolve_thread_id(runtime: Runtime) -> str | None:
    context = runtime.context or {}
    thread_id = context.get("thread_id")
    if thread_id is not None:
        return str(thread_id)
    try:
        config = get_config()
        thread_id = config.get("configurable", {}).get("thread_id")
        return str(thread_id) if thread_id is not None else None
    except RuntimeError:
        return None


def _session_start_already_fired(state: AgentState | None) -> bool:
    hooks_state = (state or {}).get("identity_hooks") or {}
    return bool(hooks_state.get("session_start_fired"))


def _extract_call_tool_text(call_tool_result: Any) -> str:
    """Extract plain text from an MCP CallToolResult without LangChain conversion."""
    from mcp.types import EmbeddedResource, TextContent, TextResourceContents

    parts: list[str] = []
    for item in getattr(call_tool_result, "content", None) or []:
        if isinstance(item, TextContent):
            parts.append(item.text)
        elif isinstance(item, EmbeddedResource):
            resource = item.resource
            if isinstance(resource, TextResourceContents):
                parts.append(resource.text)

    structured = getattr(call_tool_result, "structuredContent", None)
    if structured is not None and not parts:
        parts.append(json.dumps(structured, ensure_ascii=False, separators=(",", ":")))

    return "\n".join(parts).strip()


def _sanitize_hook_text(text: str) -> str:
    from deerflow.agents.middlewares.input_sanitization_middleware import neutralize_untrusted_tags

    return neutralize_untrusted_tags(text)


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]"


def _format_tool_section(tool_name: str, body: str) -> str:
    return f"[identity-hook tool={tool_name}]\n{body}"


def _wrap_external_context_block(body: str) -> str:
    return f"{_EXTERNAL_CONTEXT_BEGIN}\n{body}\n{_EXTERNAL_CONTEXT_END}"


async def run_session_start_hooks(
    *,
    config: ExtensionsConfig,
    thread_id: str,
    user_id: str,
) -> str | None:
    """Invoke configured sessionStart MCP tools and return sanitized context text."""
    hooks = config.identity_hooks
    if hooks is None or not hooks.enabled:
        return None

    enabled_servers = config.get_enabled_mcp_servers()
    server_config = enabled_servers.get(hooks.mcp_server_ref)
    if server_config is None:
        logger.warning(
            "identity_hooks_skip server=%s reason=disabled_or_missing",
            hooks.mcp_server_ref,
        )
        return None

    if not hooks.session_start:
        return None

    try:
        connection = build_server_params(hooks.mcp_server_ref, server_config)
    except Exception:
        logger.exception(
            "identity_hooks_connection_failed server=%s",
            hooks.mcp_server_ref,
        )
        return None

    scope_key = f"{user_id}:{thread_id}"
    pool = get_session_pool()
    try:
        session = await pool.get_session(hooks.mcp_server_ref, scope_key, connection)
    except Exception:
        logger.exception(
            "identity_hooks_session_failed server=%s",
            hooks.mcp_server_ref,
        )
        return None

    call_kwargs: dict[str, Any] = {}
    if server_config.tool_call_timeout:
        call_kwargs["read_timeout_seconds"] = timedelta(seconds=server_config.tool_call_timeout)

    sections: list[str] = []
    total_chars = 0
    for call in hooks.session_start:
        try:
            call_tool_result = await session.call_tool(call.tool, call.args, **call_kwargs)
        except Exception:
            logger.exception("identity_hooks_call_failed tool=%s", call.tool)
            continue

        raw_text = _extract_call_tool_text(call_tool_result)
        if not raw_text:
            continue

        sanitized = _sanitize_hook_text(raw_text)
        sanitized = _truncate_text(sanitized, _IDENTITY_HOOKS_MAX_TOOL_CHARS)
        section = _format_tool_section(call.tool, sanitized)
        remaining = _IDENTITY_HOOKS_MAX_TOTAL_CHARS - total_chars
        if remaining <= 0:
            break
        if len(section) > remaining:
            section = _truncate_text(section, remaining)
        sections.append(section)
        total_chars += len(section)

    if not sections:
        return None
    return _wrap_external_context_block("\n\n".join(sections))


class IdentityHooksMiddleware(AgentMiddleware[AgentState]):
    """Fire optional identity-provider MCP hooks once per lead-agent thread."""

    def __init__(self, extensions_config: ExtensionsConfig | None = None) -> None:
        super().__init__()
        self._extensions_config = extensions_config

    def _config(self) -> ExtensionsConfig:
        return self._extensions_config or get_extensions_config()

    async def _prepare_hook_update(self, state: AgentState, runtime: Runtime) -> dict | None:
        if _session_start_already_fired(state):
            return None

        config = self._config()
        hooks = config.identity_hooks
        if hooks is None or not hooks.enabled or not hooks.session_start:
            return None

        thread_id = _resolve_thread_id(runtime)
        if thread_id is None:
            logger.debug("identity_hooks_skip reason=missing_thread_id")
            return None

        user_id = get_effective_user_id() or "default"
        context_block = await run_session_start_hooks(
            config=config,
            thread_id=thread_id,
            user_id=user_id,
        )

        update: dict[str, Any] = {"identity_hooks": {"session_start_fired": True}}
        if context_block:
            update["messages"] = [
                HumanMessage(
                    content=context_block,
                    additional_kwargs={
                        IDENTITY_HOOKS_CONTEXT_KEY: True,
                        "hide_from_ui": True,
                    },
                )
            ]
        return update

    @override
    def before_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._prepare_hook_update(state, runtime))
        return None

    @override
    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        return await self._prepare_hook_update(state, runtime)
