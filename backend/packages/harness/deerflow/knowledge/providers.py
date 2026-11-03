"""Resolve read-only providers and enforce operation-level scope capabilities.

No provider configuration, HTTP calls or resource permissions live here.
Legacy tool paths select compatibility adapters; new providers are installed
through the operator-controlled extension registry and the generic core tool.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

from deerflow.knowledge_scope import execution_scope

from .contract import KnowledgeCapabilities, KnowledgeRequestContext, RetrievalProvider, RetrievalResult

RAGFLOW_KNOWLEDGE_TOOL = "deerflow.community.ragflow.tools:knowledge_search_tool"
LIGHTRAG_KNOWLEDGE_TOOL = "deerflow.community.lightrag.tools:knowledge_search_tool"
GENERIC_KNOWLEDGE_TOOL = "deerflow.knowledge.tools:knowledge_search_tool"

logger = logging.getLogger(__name__)

KNOWLEDGE_TOOL_OPERATIONS = {
    "knowledge_search": "search",
    "knowledge_entries_search": "entries_search",
    "entity_relations_search": "relations_search",
}
GENERIC_KNOWLEDGE_TOOLS = {name: f"deerflow.knowledge.tools:{name}_tool" for name in KNOWLEDGE_TOOL_OPERATIONS}


def operation_capabilities(capabilities: KnowledgeCapabilities, operation: str) -> KnowledgeCapabilities:
    if operation == "search":
        return KnowledgeCapabilities(operations=capabilities.operations & {"search", "sources", "catalog", "documents", "dataset_filter", "document_filter"})
    if operation not in {"entries_search", "relations_search"}:
        raise ValueError("Unknown knowledge retrieval operation")
    prefix = operation.removesuffix("search")
    operations = {name for name in ("sources", "catalog", "documents") if capabilities.supports(name)}
    if capabilities.supports(operation):
        operations.add("search")
    for name in ("dataset_filter", "document_filter"):
        if capabilities.supports(prefix + name):
            operations.add(name)
    return KnowledgeCapabilities(operations=operations)


def validate_provider(provider: Any) -> None:
    capabilities = getattr(provider, "capabilities", None)
    if not isinstance(capabilities, KnowledgeCapabilities) or not any(capabilities.supports(op) for op in KNOWLEDGE_TOOL_OPERATIONS.values()):
        raise ValueError("Knowledge providers require KnowledgeCapabilities with a search operation")
    methods = {"search"} if capabilities.supports("search") else set()
    if capabilities.supports("catalog"):
        methods.add("catalog")
    if capabilities.supports("documents"):
        methods.add("documents")
    if capabilities.supports("dataset_filter") or capabilities.supports("document_filter"):
        methods.add("search_scoped")
    for operation in ("entries_search", "relations_search"):
        if capabilities.supports(operation):
            methods.add(operation)
        prefix = operation.removesuffix("search")
        if any(capabilities.supports(prefix + name) for name in ("dataset_filter", "document_filter")) and not capabilities.supports(operation):
            raise ValueError("Filter capability requires its retrieval operation")
    for method in methods:
        if not inspect.iscoroutinefunction(getattr(provider, method, None)):
            raise ValueError(f"Knowledge provider capability requires async {method}")


def _configured_tools(app_config: Any) -> list[tuple[str, Any]]:
    get_tool = getattr(app_config, "get_tool_config", None)
    if not callable(get_tool):
        return []
    result = []
    for name in KNOWLEDGE_TOOL_OPERATIONS:
        tool = get_tool(name)
        if tool is None:
            continue
        expected = GENERIC_KNOWLEDGE_TOOLS[name]
        if getattr(tool, "use", None) == expected or (name == "knowledge_search" and getattr(tool, "use", None) in {RAGFLOW_KNOWLEDGE_TOOL, LIGHTRAG_KNOWLEDGE_TOOL}):
            result.append((name, tool))
    return result


def get_knowledge_capabilities(app_config: Any, *, extensions: Any = None) -> KnowledgeCapabilities:
    """One scope must be enforceable by every configured retrieval operation.

    Different provider registrations have no shared resource-ID namespace;
    their combination supports all/disabled only. Never reinterpret selected IDs.
    """
    configured = _configured_tools(app_config)
    if not configured:
        return KnowledgeCapabilities(operations=frozenset())
    projected = []
    identities = set()
    for name, tool in configured:
        use = getattr(tool, "use", None)
        if use == RAGFLOW_KNOWLEDGE_TOOL:
            from deerflow.community.ragflow.formatting import CAPABILITIES

            capabilities = CAPABILITIES
            identities.add(use)
        elif use == LIGHTRAG_KNOWLEDGE_TOOL:
            from deerflow.community.lightrag.formatting import CAPABILITIES

            capabilities = CAPABILITIES
            identities.add(use)
        else:
            provider = _registered_provider(tool, extensions=extensions)
            provider_name = (getattr(tool, "model_extra", None) or {}).get("provider")
            operation = KNOWLEDGE_TOOL_OPERATIONS[name]
            if provider is None or not provider.capabilities.supports(operation):
                logger.error(
                    "Invalid knowledge tool configuration: tool=%r provider=%r operation=%r (%s)",
                    name,
                    provider_name,
                    operation,
                    "not registered" if provider is None else "operation not advertised",
                )
                raise ValueError("Invalid knowledge tool configuration; check operator logs")
            capabilities = operation_capabilities(provider.capabilities, operation)
            identities.add((getattr(tool, "model_extra", None) or {}).get("provider"))
        projected.append(set(capabilities.operations))
    operations = set.intersection(*projected)
    if len(identities) > 1:
        operations -= {"catalog", "documents", "dataset_filter", "document_filter"}
    return KnowledgeCapabilities(operations=operations)


def _registered_provider(tool: Any, *, extensions: Any = None) -> RetrievalProvider | None:
    if getattr(tool, "use", None) not in GENERIC_KNOWLEDGE_TOOLS.values():
        return None
    from deerflow.extensions import get_loaded_extensions

    loaded = extensions if extensions is not None else get_loaded_extensions()
    name = (getattr(tool, "model_extra", None) or {}).get("provider")
    for _, (registered_name, provider) in loaded.knowledge_providers:
        if registered_name == name:
            return provider
    return None


def resolve_knowledge_provider(app_config: Any, *, extensions: Any = None, tool_name: str | None = None) -> RetrievalProvider:
    configured = _configured_tools(app_config)
    tool = next((tool for name, tool in configured if tool_name is None or name == tool_name), None)
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


async def search_provider(provider: RetrievalProvider, query: str, *, scope: object | None, user_id: str, agent_name: str | None, operation: str = "search") -> RetrievalResult:
    capabilities = operation_capabilities(provider.capabilities, operation)
    if not capabilities.supports("search"):
        raise ValueError("Knowledge retrieval operation is unavailable")
    canonical = validate_scope_capabilities(scope, capabilities) if scope is not None else None
    if canonical is not None and canonical["mode"] == "disabled":
        raise ValueError("Knowledge search is disabled for this turn")
    context = KnowledgeRequestContext(user_id=user_id, agent_name=agent_name, scope=canonical)
    contextual_search = getattr(provider, "search_scoped" if operation == "search" else operation, None)
    if callable(contextual_search):
        result = await contextual_search(query, context=context)
    elif canonical is not None and canonical["mode"] == "selected":
        raise ValueError("Knowledge provider cannot apply the selected scope")
    elif operation != "search":
        raise ValueError("Knowledge retrieval operation is unavailable")
    else:
        result = await provider.search(query)
    # Validate provider values before they can become model-visible evidence.
    payload = result.model_dump() if isinstance(result, RetrievalResult) else result
    return RetrievalResult.model_validate(payload)
