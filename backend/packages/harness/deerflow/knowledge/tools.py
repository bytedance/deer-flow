"""Stable Agent entry point for registered read-only knowledge providers."""

import logging
from collections.abc import Mapping

from langchain_core.tools import StructuredTool

from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig
from deerflow.extensions import resolve_run_extensions
from deerflow.knowledge.providers import KNOWLEDGE_TOOL_OPERATIONS, get_knowledge_capabilities, resolve_knowledge_provider, search_provider, validate_scope_capabilities
from deerflow.knowledge.sources import format_result
from deerflow.knowledge_scope import KNOWLEDGE_SCOPE_RUNTIME_KEY, execution_scope
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)


def _execution_agent_name(context: Mapping, config: object = None) -> str:
    """Identify the current executor, rather than a delegated run's parent."""
    if context.get("is_subagent") is True:
        name = context.get("agent_id")
    else:
        configurable = config.get("configurable") if isinstance(config, Mapping) else None
        legacy_name = configurable.get("agent_name") if isinstance(configurable, Mapping) else None
        name = context.get("agent_name", legacy_name)
    if name is None and context.get("is_subagent") is not True:
        return "lead_agent"
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Invalid knowledge execution agent identity")
    return name


async def execute_knowledge_search(query: str, runtime: Runtime, *, tool_name: str = "knowledge_search") -> tuple[str, dict | None]:
    """Retrieve evidence from the configured knowledge provider.

    Args:
        query: Specific question or search terms for the configured retrieval tool.
        runtime: Trusted execution context and run configuration.
        tool_name: Configured document, Wiki entry, or entity relation tool.
    """
    if not query.strip():
        return "Error: query must not be empty.", None
    context = runtime.context if isinstance(runtime.context, Mapping) else {}
    try:
        raw_scope = context.get(KNOWLEDGE_SCOPE_RUNTIME_KEY)
        scope = execution_scope(raw_scope) if raw_scope is not None else None
        if scope is not None and scope["mode"] == "disabled":
            return "Error: Knowledge search is disabled for this turn.", None
        app_config = context.get("app_config")
        if not isinstance(app_config, AppConfig):
            app_config = get_app_config()
        extensions = resolve_run_extensions(context)
        if scope is not None:
            validate_scope_capabilities(scope, get_knowledge_capabilities(app_config, extensions=extensions))
        provider = resolve_knowledge_provider(app_config, extensions=extensions, tool_name=tool_name)
        result = await search_provider(
            provider,
            query.strip(),
            scope=scope,
            user_id=resolve_runtime_user_id(runtime),
            operation=KNOWLEDGE_TOOL_OPERATIONS[tool_name],
            agent_name=_execution_agent_name(context, getattr(runtime, "config", None)),
        )
        return format_result(result)
    except PermissionError:
        return "Error: The selected knowledge scope is not accessible.", None
    except Exception as exc:
        # Provider exceptions may contain credentials or resource identifiers.
        logger.warning("Knowledge retrieval failed (%s)", type(exc).__name__)
        return "Error: Knowledge retrieval failed; check the provider and selected scope.", None


async def _knowledge_search_entrypoint(query: str, runtime: Runtime) -> tuple[str, dict | None]:
    return await execute_knowledge_search(query, runtime)


async def _entries_search_entrypoint(query: str, runtime: Runtime) -> tuple[str, dict | None]:
    return await execute_knowledge_search(query, runtime, tool_name="knowledge_entries_search")


async def _relations_search_entrypoint(query: str, runtime: Runtime) -> tuple[str, dict | None]:
    return await execute_knowledge_search(query, runtime, tool_name="entity_relations_search")


def _tool(name, coroutine, description):
    return StructuredTool.from_function(
        coroutine=coroutine,
        name=name,
        response_format="content_and_artifact",
        description=description + " Within this turn's scope. Cite only supplied [citation:Title](#knowledge-source-ID) links exactly; never invent source locators or relations.",
    )


knowledge_search_tool = _tool("knowledge_search", _knowledge_search_entrypoint, "Search accessible document evidence.")
knowledge_entries_search_tool = _tool("knowledge_entries_search", _entries_search_entrypoint, "Search accessible published Wiki and knowledge entries.")
entity_relations_search_tool = _tool("entity_relations_search", _relations_search_entrypoint, "Search upstream entities and relations. Returned paths may be incomplete; absence does not disprove a relation.")
