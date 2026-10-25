"""Synthetic providers exercise the three configurable retrieval operations."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deerflow.knowledge import KnowledgeCapabilities, RetrievalResult
from deerflow.knowledge.providers import search_provider, validate_provider


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["entries_search", "relations_search"])
async def test_optional_operation_is_contextual_and_does_not_fallback(operation):
    method = AsyncMock(return_value=RetrievalResult())
    provider = SimpleNamespace(capabilities=KnowledgeCapabilities(operations={"search", operation}), search=AsyncMock(), **{operation: method})
    validate_provider(provider)
    result = await search_provider(provider, "q", scope={"version": 1, "mode": "all"}, user_id="alice", agent_name="researcher", operation=operation)
    assert result.hits == []
    assert method.await_args.kwargs["context"].user_id == "alice"
    assert method.await_args.kwargs["context"].agent_name == "researcher"
    provider.search.assert_not_called()
    with pytest.raises(ValueError, match="dataset_filter"):
        await search_provider(provider, "q", scope={"version": 1, "mode": "selected", "dataset_ids": ["kb"]}, user_id="alice", agent_name="researcher", operation=operation)
    assert method.await_count == 1


@pytest.mark.asyncio
async def test_optional_operation_has_its_own_filter_capabilities():
    provider = SimpleNamespace(capabilities=KnowledgeCapabilities(operations={"search", "dataset_filter", "document_filter", "entries_search", "entries_dataset_filter"}), entries_search=AsyncMock(return_value=RetrievalResult()))
    await search_provider(provider, "q", scope={"version": 1, "mode": "selected", "dataset_ids": ["kb"]}, user_id="alice", agent_name=None, operation="entries_search")
    with pytest.raises(ValueError, match="document_filter"):
        await search_provider(provider, "q", scope={"version": 1, "mode": "selected", "dataset_ids": ["kb"], "document_filters": [{"dataset_id": "kb", "document_ids": ["doc"]}]}, user_id="alice", agent_name=None, operation="entries_search")
    assert provider.entries_search.await_count == 1


def test_registration_checks_optional_methods():
    with pytest.raises(ValueError, match="entries_search"):
        validate_provider(SimpleNamespace(capabilities=KnowledgeCapabilities(operations={"search", "entries_search"}), search=AsyncMock()))


@pytest.mark.asyncio
@pytest.mark.parametrize("mask", range(8))
async def test_all_tool_combinations_use_config_and_shared_evidence(mask):
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.config.tool_config import ToolConfig
    from deerflow.extensions import EXTENSION_SNAPSHOT_CONTEXT_KEY, ExtensionRegistry
    from deerflow.knowledge import KnowledgeSource, RetrievalHit, sources_from_messages, tools
    from deerflow.knowledge.providers import KNOWLEDGE_TOOL_OPERATIONS, get_knowledge_capabilities
    from deerflow.knowledge.sources import forward_sources, prune_sources
    from deerflow.runtime.serialization import serialize_channel_values_for_api

    names = [name for i, name in enumerate(KNOWLEDGE_TOOL_OPERATIONS) if mask & (1 << i)]
    provider = SimpleNamespace(capabilities=KnowledgeCapabilities(operations={"search", "sources", "entries_search", "relations_search"}))
    for operation in KNOWLEDGE_TOOL_OPERATIONS.values():
        source = KnowledgeSource(provider="synthetic", title=operation, excerpt=f"Returned {operation} evidence")
        setattr(provider, operation, AsyncMock(return_value=RetrievalResult(hits=[RetrievalHit(content=source.excerpt, source=source)])))
    registry = ExtensionRegistry()
    with registry.attributed_to("synthetic:install"):
        registry.knowledge_provider("synthetic", provider)
    loaded = registry.build()
    config = AppConfig(sandbox=SandboxConfig(use="example.remote:Sandbox"), tools=[ToolConfig(name=name, group="knowledge", use=f"deerflow.knowledge.tools:{name}_tool", provider="synthetic") for name in names])
    assert get_knowledge_capabilities(config, extensions=loaded).supports("search") == bool(names)
    if not names:
        return
    builder = StateGraph(MessagesState, context_schema=dict)
    builder.add_node("tools", ToolNode([getattr(tools, name + "_tool") for name in names]))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    result = await builder.compile().ainvoke(
        {"messages": [AIMessage(content="", tool_calls=[{"id": name, "name": name, "args": {"query": "q"}} for name in names])]},
        context={"app_config": config, "user_id": "alice", "is_subagent": True, "agent_id": "researcher", "__knowledge_scope_execution": {"version": 1, "mode": "all"}, EXTENSION_SNAPSHOT_CONTEXT_KEY: loaded},
    )
    sources = sources_from_messages(result["messages"])
    assert len(sources) == len(names)
    persisted = serialize_channel_values_for_api(result)
    assert sources_from_messages(persisted["messages"]) == sources
    report = "\n".join(message.content for message in result["messages"][1:])
    forwarded, artifact = forward_sources(report, [s.model_dump(mode="json") for s in sources])
    assert sources_from_messages([{"type": "tool", "content": forwarded, "artifact": artifact}]) == sources
    assert prune_sources("removed", artifact)[1]["knowledge_sources"] == []
    for name in names:
        method = getattr(provider, KNOWLEDGE_TOOL_OPERATIONS[name])
        if name != "knowledge_search":
            assert method.await_args.kwargs["context"].agent_name == "researcher"


@pytest.mark.parametrize("name", ["knowledge_search", "knowledge_entries_search", "entity_relations_search"])
def test_disabled_scope_blocks_each_tool(name):
    from deerflow.agents.middlewares.knowledge_scope_middleware import KnowledgeScopeMiddleware

    request = SimpleNamespace(tool_call={"name": name, "id": "call"}, runtime=SimpleNamespace(context={"__knowledge_scope_execution": {"version": 1, "mode": "disabled"}}))
    message = KnowledgeScopeMiddleware._disabled_tool_message(request)
    assert message.name == name and message.status == "error"


def test_combined_scope_is_intersection_and_rejects_mixed_namespaces():
    from deerflow.extensions import ExtensionRegistry
    from deerflow.knowledge.providers import get_knowledge_capabilities

    registry = ExtensionRegistry()
    capabilities = KnowledgeCapabilities(operations={"search", "catalog", "documents", "dataset_filter", "document_filter", "entries_search", "entries_dataset_filter"})
    provider = SimpleNamespace(capabilities=capabilities, search=AsyncMock(), search_scoped=AsyncMock(), entries_search=AsyncMock(), catalog=AsyncMock(), documents=AsyncMock())
    with registry.attributed_to("test:install"):
        registry.knowledge_provider("one", provider)
        registry.knowledge_provider("two", provider)
    entries = {name: SimpleNamespace(use=f"deerflow.knowledge.tools:{name}_tool", model_extra={"provider": "one"}) for name in ["knowledge_search", "knowledge_entries_search"]}
    config = SimpleNamespace(get_tool_config=entries.get)
    caps = get_knowledge_capabilities(config, extensions=registry.build())
    assert caps.supports("dataset_filter") and not caps.supports("document_filter")
    entries["knowledge_entries_search"].model_extra["provider"] = "two"
    caps = get_knowledge_capabilities(config, extensions=registry.build())
    assert caps.supports("search") and not caps.supports("dataset_filter")


@pytest.mark.parametrize("registered", [True, False])
def test_incompatible_tool_reports_pair_without_silently_emptying_capabilities(caplog, registered):
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.config.tool_config import ToolConfig
    from deerflow.extensions import ExtensionRegistry
    from deerflow.knowledge.providers import get_knowledge_capabilities

    registry = ExtensionRegistry()
    if registered:
        provider = SimpleNamespace(capabilities=KnowledgeCapabilities(operations={"search"}), search=AsyncMock())
        with registry.attributed_to("test:install"):
            registry.knowledge_provider("documents-only", provider)
    names = ["knowledge_search", "knowledge_entries_search"]
    config = AppConfig(
        sandbox=SandboxConfig(use="example:Sandbox"),
        tools=[ToolConfig(name=name, group="knowledge", use=f"deerflow.knowledge.tools:{name}_tool", provider="documents-only") for name in names],
    )
    with pytest.raises(ValueError, match="Invalid knowledge tool configuration"):
        get_knowledge_capabilities(config, extensions=registry.build())
    assert "documents-only" in caplog.text
    assert ("knowledge_entries_search" if registered else "knowledge_search") in caplog.text
    assert ("entries_search" if registered else "not registered") in caplog.text
