"""Stable Agent entry point for registered read-only knowledge providers."""

import logging
from collections.abc import Mapping

from langchain_core.tools import StructuredTool

from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig
from deerflow.extensions import resolve_run_extensions
from deerflow.knowledge.providers import resolve_knowledge_provider, search_provider
from deerflow.knowledge.sources import format_result
from deerflow.knowledge_scope import KNOWLEDGE_SCOPE_RUNTIME_KEY
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)


async def _knowledge_search_entrypoint(query: str, runtime: Runtime) -> tuple[str, dict | None]:
    """Retrieve evidence from the configured knowledge provider.

    Args:
        query: Specific question or search terms for private documents.
    """
    if not query.strip():
        return "Error: query must not be empty.", None
    context = runtime.context if isinstance(runtime.context, Mapping) else {}
    try:
        app_config = context.get("app_config")
        if not isinstance(app_config, AppConfig):
            app_config = get_app_config()
        provider = resolve_knowledge_provider(app_config, extensions=resolve_run_extensions(context))
        result = await search_provider(
            provider,
            query.strip(),
            scope=context.get(KNOWLEDGE_SCOPE_RUNTIME_KEY),
            user_id=resolve_runtime_user_id(runtime),
            agent_name=context.get("agent_name"),
        )
        return format_result(result)
    except PermissionError:
        return "Error: The selected knowledge scope is not accessible.", None
    except Exception as exc:
        # Provider exceptions may contain credentials or resource identifiers.
        logger.warning("Knowledge retrieval failed (%s)", type(exc).__name__)
        return "Error: Knowledge retrieval failed; check the provider and selected scope.", None


knowledge_search_tool = StructuredTool.from_function(
    coroutine=_knowledge_search_entrypoint,
    name="knowledge_search",
    response_format="content_and_artifact",
    description="Search accessible knowledge within this turn's scope. Cite only supplied [citation:Title](#knowledge-source-ID) links exactly; never invent source locators.",
    parse_docstring=True,
)
