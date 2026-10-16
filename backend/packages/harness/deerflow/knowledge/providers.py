"""Resolve read-only providers and enforce operation-level scope capabilities.

No provider configuration, HTTP calls or resource permissions live here.
Legacy tool paths select compatibility adapters; new providers are installed
through the operator-controlled extension registry and the generic core tool.
"""

from __future__ import annotations

import inspect
from typing import Any

from deerflow.knowledge_scope import execution_scope

from .contract import KnowledgeCapabilities, KnowledgeRequestContext, RetrievalProvider, RetrievalResult

RAGFLOW_KNOWLEDGE_TOOL = "deerflow.community.ragflow.tools:knowledge_search_tool"
LIGHTRAG_KNOWLEDGE_TOOL = "deerflow.community.lightrag.tools:knowledge_search_tool"
GENERIC_KNOWLEDGE_TOOL = "deerflow.knowledge.tools:knowledge_search_tool"


def validate_provider(provider: Any) -> None:
    capabilities = getattr(provider, "capabilities", None)
    if not isinstance(capabilities, KnowledgeCapabilities) or not capabilities.supports("search"):
        raise ValueError("Knowledge providers require KnowledgeCapabilities with search")
    methods = {"search"}
    if capabilities.supports("catalog"):
        methods.add("catalog")
    if capabilities.supports("documents"):
        methods.add("documents")
    if capabilities.supports("dataset_filter") or capabilities.supports("document_filter"):
        methods.add("search_scoped")
    for method in methods:
        if not inspect.iscoroutinefunction(getattr(provider, method, None)):
            raise ValueError(f"Knowledge provider capability requires async {method}")


def get_knowledge_capabilities(app_config: Any, *, extensions: Any = None) -> KnowledgeCapabilities:
    get_tool = getattr(app_config, "get_tool_config", None)
    tool = get_tool("knowledge_search") if callable(get_tool) else None
    use = getattr(tool, "use", None)
    if use == RAGFLOW_KNOWLEDGE_TOOL:
        from deerflow.community.ragflow.formatting import CAPABILITIES

        return CAPABILITIES
    if use == LIGHTRAG_KNOWLEDGE_TOOL:
        from deerflow.community.lightrag.formatting import CAPABILITIES

        return CAPABILITIES
    provider = _registered_provider(tool, extensions=extensions)
    return provider.capabilities if provider is not None else KnowledgeCapabilities(operations=frozenset())


def _registered_provider(tool: Any, *, extensions: Any = None) -> RetrievalProvider | None:
    if getattr(tool, "use", None) != GENERIC_KNOWLEDGE_TOOL:
        return None
    from deerflow.extensions import get_loaded_extensions

    loaded = extensions if extensions is not None else get_loaded_extensions()
    name = (getattr(tool, "model_extra", None) or {}).get("provider")
    for _, (registered_name, provider) in loaded.knowledge_providers:
        if registered_name == name:
            return provider
    return None


def resolve_knowledge_provider(app_config: Any, *, extensions: Any = None) -> RetrievalProvider:
    get_tool = getattr(app_config, "get_tool_config", None)
    tool = get_tool("knowledge_search") if callable(get_tool) else None
    if getattr(tool, "use", None) == RAGFLOW_KNOWLEDGE_TOOL:
        from deerflow.community.ragflow.provider import RAGFlowKnowledgeProvider

        return RAGFlowKnowledgeProvider(app_config)
    provider = _registered_provider(tool, extensions=extensions)
    if provider is None:
        raise LookupError("Knowledge provider is not configured")
    return provider


def validate_scope_capabilities(scope: object, capabilities: KnowledgeCapabilities) -> dict[str, Any]:
    canonical = execution_scope(scope)
    if not capabilities.supports("search"):
        raise ValueError("Knowledge retrieval is unavailable")
    if canonical["mode"] == "selected":
        if not capabilities.supports("dataset_filter"):
            raise ValueError("Knowledge provider does not support dataset_filter")
        if canonical.get("document_filters") and not capabilities.supports("document_filter"):
            raise ValueError("Knowledge provider does not support document_filter")
    return canonical


async def search_provider(provider: RetrievalProvider, query: str, *, scope: object | None, user_id: str, agent_name: str | None) -> RetrievalResult:
    canonical = validate_scope_capabilities(scope, provider.capabilities) if scope is not None else None
    if canonical is not None and canonical["mode"] == "disabled":
        raise ValueError("Knowledge search is disabled for this turn")
    context = KnowledgeRequestContext(user_id=user_id, agent_name=agent_name, scope=canonical)
    contextual_search = getattr(provider, "search_scoped", None)
    if callable(contextual_search):
        result = await contextual_search(query, context=context)
    elif canonical is not None and canonical["mode"] == "selected":
        raise ValueError("Knowledge provider cannot apply the selected scope")
    else:
        result = await provider.search(query)
    # Validate provider values before they can become model-visible evidence.
    payload = result.model_dump() if isinstance(result, RetrievalResult) else result
    return RetrievalResult.model_validate(payload)
