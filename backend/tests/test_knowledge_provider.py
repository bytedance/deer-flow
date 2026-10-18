from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langchain_core.messages import HumanMessage

from app.gateway.knowledge_scope_admission import admit_message_knowledge_scope
from deerflow.extensions import ExtensionRegistry, reset_loaded_extensions, set_loaded_extensions
from deerflow.knowledge import KnowledgeCapabilities, RetrievalResult
from deerflow.knowledge.providers import GENERIC_KNOWLEDGE_TOOL, get_knowledge_capabilities, search_provider


@pytest.fixture(autouse=True)
def clear_registry():
    reset_loaded_extensions()
    yield
    reset_loaded_extensions()


def provider_config(name="test"):
    tool = SimpleNamespace(use=GENERIC_KNOWLEDGE_TOOL, model_extra={"provider": name})
    return SimpleNamespace(
        knowledge_base=SimpleNamespace(enabled=True, scope_selection_enabled=True),
        get_tool_config=lambda _: tool,
    )


def install_provider(operations):
    provider = SimpleNamespace(
        capabilities=KnowledgeCapabilities(operations=frozenset(operations)),
        search=AsyncMock(return_value=RetrievalResult()),
        search_scoped=AsyncMock(return_value=RetrievalResult()),
        catalog=AsyncMock(),
        documents=AsyncMock(),
    )
    registry = ExtensionRegistry()
    with registry.attributed_to("test:install"):
        assert registry.knowledge_provider("test", provider)
    set_loaded_extensions(registry.build())
    return provider


def test_search_only_provider_needs_no_catalog_or_scoped_search():
    provider = SimpleNamespace(capabilities=KnowledgeCapabilities(), search=AsyncMock())
    registry = ExtensionRegistry()
    with registry.attributed_to("test:install"):
        registry.knowledge_provider("test", provider)
    set_loaded_extensions(registry.build())
    assert get_knowledge_capabilities(provider_config()).operations == {"search"}


@pytest.mark.parametrize("operations", [{"search"}, {"search", "catalog"}])
def test_admission_rejects_unadvertised_dataset_filter(operations):
    provider = install_provider(operations)
    graph_input = {
        "messages": [
            HumanMessage(
                content="q",
                additional_kwargs={
                    "knowledge_scope": {"version": 1, "mode": "selected", "dataset_ids": ["private"]},
                },
            )
        ]
    }
    with pytest.raises(HTTPException) as exc:
        admit_message_knowledge_scope(graph_input, assistant_id="lead_agent", app_config=provider_config(), agent_config=None)
    assert exc.value.status_code == 422
    provider.search.assert_not_called()


def test_filter_admission_does_not_require_catalog_and_recovery_is_authoritative():
    install_provider({"search", "dataset_filter"})
    graph_input = {
        "messages": [
            HumanMessage(
                content="q",
                additional_kwargs={
                    "knowledge_scope": {"version": 1, "mode": "all"},
                },
            )
        ]
    }
    recovered = {"version": 1, "mode": "selected", "dataset_ids": ["private"]}
    assert (
        admit_message_knowledge_scope(
            graph_input,
            assistant_id="lead_agent",
            app_config=provider_config(),
            agent_config=None,
            recovery=True,
            recovery_scope=recovered,
        )
        == recovered
    )


@pytest.mark.asyncio
async def test_execution_rechecks_filter_capabilities_without_falling_back():
    provider = install_provider({"search", "dataset_filter"})
    scope = {"version": 1, "mode": "selected", "dataset_ids": ["private"], "document_filters": [{"dataset_id": "private", "document_ids": ["secret"]}]}
    with pytest.raises(ValueError, match="document_filter"):
        await search_provider(provider, "q", scope=scope, user_id="alice", agent_name="lead_agent")
    provider.search.assert_not_awaited()
    provider.search_scoped.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_receives_only_execution_scope_and_host_identity():
    provider = install_provider({"search", "dataset_filter"})
    scope = {"version": 1, "mode": "selected", "dataset_ids": ["private"], "display": {"datasets": [{"id": "private", "name": "untrusted label"}]}}
    await search_provider(provider, "q", scope=scope, user_id="alice", agent_name="researcher")
    context = provider.search_scoped.await_args.kwargs["context"]
    assert context.user_id == "alice"
    assert context.agent_name == "researcher"
    assert context.scope == {"version": 1, "mode": "selected", "dataset_ids": ["private"]}
    provider.search.assert_not_awaited()


def test_registration_rollback_and_duplicate_names():
    registry = ExtensionRegistry()
    provider = SimpleNamespace(capabilities=KnowledgeCapabilities(), search=AsyncMock())
    with registry.attributed_to("test:install"):
        registry.knowledge_provider("test", provider)
        mark = registry.mark()
        registry.knowledge_provider("second", provider)
        with pytest.raises(ValueError, match="Duplicate"):
            registry.knowledge_provider("test", provider)
        registry.rollback_to(mark)
    assert [name for _, (name, _) in registry.build().knowledge_providers] == ["test"]


def test_registration_rejects_capabilities_without_implementation():
    registry = ExtensionRegistry()
    provider = SimpleNamespace(capabilities=KnowledgeCapabilities(operations={"search", "dataset_filter"}), search=AsyncMock())
    with registry.attributed_to("test:install"), pytest.raises(ValueError, match="search_scoped"):
        registry.knowledge_provider("test", provider)


@pytest.mark.asyncio
async def test_search_only_provider_and_disabled_scope_do_not_need_catalog():
    provider = SimpleNamespace(capabilities=KnowledgeCapabilities(), search=AsyncMock(return_value=RetrievalResult()))
    assert await search_provider(provider, "q", scope=None, user_id="alice", agent_name=None) == RetrievalResult()
    provider.search.assert_awaited_once_with("q")
    with pytest.raises(ValueError, match="disabled"):
        await search_provider(provider, "q", scope={"version": 1, "mode": "disabled"}, user_id="alice", agent_name=None)
    assert provider.search.await_count == 1


@pytest.mark.asyncio
async def test_permission_denial_never_retries_unconstrained():
    provider = install_provider({"search", "dataset_filter"})
    provider.search_scoped.side_effect = PermissionError("private provider details")
    with pytest.raises(PermissionError):
        await search_provider(provider, "q", scope={"version": 1, "mode": "selected", "dataset_ids": ["private"]}, user_id="alice", agent_name="lead_agent")
    provider.search.assert_not_awaited()
    assert provider.search_scoped.await_count == 1


@pytest.mark.asyncio
async def test_generic_tool_uses_run_snapshot_and_validates_source_artifact(monkeypatch):
    from langchain_core.messages import ToolMessage

    from deerflow.extensions import EXTENSION_SNAPSHOT_CONTEXT_KEY, get_loaded_extensions
    from deerflow.knowledge import KnowledgeSource, RetrievalHit, sources_from_messages, tools
    from deerflow.knowledge.sources import prune_sources
    from deerflow.runtime.serialization import serialize_channel_values_for_api

    provider = install_provider({"search", "sources", "dataset_filter"})
    source = KnowledgeSource(provider="test", title="Private manual", excerpt="Actual provider evidence.")
    provider.search_scoped.return_value = RetrievalResult(hits=[RetrievalHit(content=source.excerpt, source=source)])
    loaded = get_loaded_extensions()
    reset_loaded_extensions()  # A newer singleton must not replace the running snapshot.
    monkeypatch.setattr(tools, "get_app_config", provider_config)
    runtime = SimpleNamespace(
        context={
            "user_id": "alice",
            "agent_name": "researcher",
            EXTENSION_SNAPSHOT_CONTEXT_KEY: loaded,
            "__knowledge_scope_execution": {"version": 1, "mode": "selected", "dataset_ids": ["private"]},
        }
    )
    content, artifact = await tools._knowledge_search_entrypoint("q", runtime)
    message = ToolMessage(content=content, artifact=artifact, tool_call_id="retrieval-1", name="knowledge_search")
    import json

    persisted = json.loads(json.dumps(serialize_channel_values_for_api({"messages": [message]})))
    assert sources_from_messages(persisted["messages"]) == [source]
    assert provider.search_scoped.await_args.kwargs["context"].user_id == "alice"
    # A truncated tool message cannot retain evidence that is no longer visible.
    _, pruned = prune_sources("truncated", artifact)
    assert pruned["knowledge_sources"] == []


@pytest.mark.asyncio
async def test_generic_tool_keeps_run_config_and_authenticated_identity(monkeypatch):
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.config.tool_config import ToolConfig
    from deerflow.extensions import EXTENSION_SNAPSHOT_CONTEXT_KEY, get_loaded_extensions
    from deerflow.knowledge import tools

    provider = install_provider({"search", "dataset_filter"})
    config = AppConfig(
        tools=[ToolConfig(name="knowledge_search", group="knowledge", use=GENERIC_KNOWLEDGE_TOOL, provider="test")],
        sandbox=SandboxConfig(use="example.remote:Sandbox"),
    )
    monkeypatch.setattr(tools, "get_app_config", lambda: provider_config("replacement"))
    runtime = SimpleNamespace(
        context={"app_config": config, "user_id": "forged", EXTENSION_SNAPSHOT_CONTEXT_KEY: get_loaded_extensions()},
        server_info=SimpleNamespace(user=SimpleNamespace(identity="authenticated")),
    )
    content, artifact = await tools._knowledge_search_entrypoint("q", runtime)
    assert not content.startswith("Error:")
    assert artifact is not None
    assert provider.search_scoped.await_args.kwargs["context"].user_id == "authenticated"


@pytest.mark.asyncio
@pytest.mark.parametrize("assistant_id", [None, "lead_agent", "researcher"])
@pytest.mark.parametrize("request_config", [None, {"configurable": {"agent_name": "researcher"}}, {"context": {"agent_name": "writer"}}])
async def test_generic_tool_identity_matches_real_gateway_run_config(monkeypatch, assistant_id, request_config):
    from app.gateway.services import build_run_config
    from deerflow.knowledge import tools

    provider = install_provider({"search", "dataset_filter"})
    monkeypatch.setattr(tools, "get_app_config", provider_config)
    run_config = build_run_config("knowledge-thread", request_config, None, assistant_id=assistant_id)
    runtime = SimpleNamespace(context=run_config.get("context", {}), config=run_config)
    content, _ = await tools._knowledge_search_entrypoint("q", runtime)
    assert not content.startswith("Error:")
    merged = {**run_config.get("configurable", {}), **run_config.get("context", {})}
    assert provider.search_scoped.await_args.kwargs["context"].agent_name == (merged.get("agent_name") or "lead_agent")


@pytest.mark.asyncio
async def test_subagent_identity_takes_precedence_over_inherited_parent_name(monkeypatch):
    from deerflow.knowledge import tools

    provider = install_provider({"search", "dataset_filter"})
    monkeypatch.setattr(tools, "get_app_config", provider_config)
    runtime = SimpleNamespace(context={"is_subagent": True, "agent_id": "child", "agent_name": "parent"})
    content, _ = await tools._knowledge_search_entrypoint("q", runtime)
    assert not content.startswith("Error:")
    assert provider.search_scoped.await_args.kwargs["context"].agent_name == "child"


@pytest.mark.asyncio
async def test_missing_subagent_identity_does_not_fall_back_to_lead_agent(monkeypatch):
    from deerflow.knowledge import tools

    provider = install_provider({"search", "dataset_filter"})
    monkeypatch.setattr(tools, "get_app_config", provider_config)
    runtime = SimpleNamespace(context={"is_subagent": True, "agent_name": "parent"})
    content, artifact = await tools._knowledge_search_entrypoint("q", runtime)
    assert content.startswith("Error:")
    assert artifact is None
    provider.search_scoped.assert_not_awaited()


@pytest.mark.asyncio
async def test_standalone_admission_cannot_forge_knowledge_subagent_identity(monkeypatch):
    from app.gateway.langgraph_auth import _scrub_run_incarnation
    from deerflow.knowledge import tools

    provider = install_provider({"search", "dataset_filter"})
    monkeypatch.setattr(tools, "get_app_config", provider_config)
    request = {"kwargs": {"context": {"is_subagent": True, "agent_id": "privileged-child"}}}
    _scrub_run_incarnation(request)
    runtime = SimpleNamespace(context=request["kwargs"]["context"], config=request["kwargs"]["config"])
    content, _ = await tools._knowledge_search_entrypoint("q", runtime)
    assert not content.startswith("Error:")
    assert provider.search_scoped.await_args.kwargs["context"].agent_name == "lead_agent"


@pytest.mark.asyncio
async def test_standalone_admission_overrides_persisted_assistant_child_identity(monkeypatch):
    from langgraph_sdk import Auth

    from app.gateway.langgraph_auth import add_owner_filter
    from deerflow.knowledge import tools

    provider = install_provider({"search", "dataset_filter"})
    monkeypatch.setattr(tools, "get_app_config", provider_config)
    defaults = {"is_subagent": True, "agent_id": "privileged-child"}
    request = {"kwargs": {"context": {}}, "assistant_id": "lead_agent"}
    auth_context = Auth.types.AuthContext(resource="threads", action="create_run", user=SimpleNamespace(identity="alice"), permissions=[])
    await add_owner_filter(auth_context, request)
    # The standalone runtime merges stored assistant defaults AFTER admission.
    effective_context = {**defaults, **request["kwargs"]["context"]}
    runtime = SimpleNamespace(context=effective_context, config=request["kwargs"]["config"])
    content, _ = await tools._knowledge_search_entrypoint("q", runtime)
    assert not content.startswith("Error:")
    assert provider.search_scoped.await_args.kwargs["context"].agent_name == "lead_agent"
    assert provider.search_scoped.await_args.kwargs["context"].user_id == "alice"


@pytest.mark.asyncio
async def test_disabled_scope_returns_specific_error_before_loading_provider(monkeypatch):
    from deerflow.knowledge import tools

    provider = install_provider({"search", "dataset_filter"})

    def unavailable_config():
        pytest.fail("disabled search must not load configuration or resolve a provider")

    monkeypatch.setattr(tools, "get_app_config", unavailable_config)
    runtime = SimpleNamespace(context={"__knowledge_scope_execution": {"version": 1, "mode": "disabled"}})
    assert await tools._knowledge_search_entrypoint("q", runtime) == ("Error: Knowledge search is disabled for this turn.", None)
    provider.search.assert_not_awaited()
    provider.search_scoped.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [{"version": 2, "mode": "disabled"}, {"version": 1, "mode": "selected", "dataset_ids": []}])
async def test_malformed_scope_is_rejected_before_loading_provider(monkeypatch, scope):
    from deerflow.knowledge import tools

    provider = install_provider({"search", "dataset_filter"})
    monkeypatch.setattr(tools, "get_app_config", lambda: pytest.fail("invalid scope must fail before loading config"))
    runtime = SimpleNamespace(context={"__knowledge_scope_execution": scope})
    content, artifact = await tools._knowledge_search_entrypoint("q", runtime)
    assert content == "Error: Knowledge retrieval failed; check the provider and selected scope."
    assert artifact is None
    provider.search.assert_not_awaited()
    provider.search_scoped.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_tool_node_injects_scope_and_emits_shared_evidence(monkeypatch):
    from langchain_core.messages import AIMessage, ToolMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    from deerflow.extensions import EXTENSION_SNAPSHOT_CONTEXT_KEY, get_loaded_extensions
    from deerflow.knowledge import KnowledgeSource, RetrievalHit, sources_from_messages, tools

    provider = install_provider({"search", "sources", "dataset_filter"})
    source = KnowledgeSource(provider="test", title="Guide", excerpt="Actual private evidence")
    provider.search_scoped.return_value = RetrievalResult(hits=[RetrievalHit(content=source.excerpt, source=source)])
    monkeypatch.setattr(tools, "get_app_config", provider_config)
    scope = {"version": 1, "mode": "selected", "dataset_ids": ["private"]}
    builder = StateGraph(MessagesState, context_schema=dict)
    builder.add_node("tools", ToolNode([tools.knowledge_search_tool]))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    result = await builder.compile().ainvoke(
        {"messages": [AIMessage(content="", tool_calls=[{"id": "call", "name": "knowledge_search", "args": {"query": "q"}}])]},
        context={"user_id": "alice", "__knowledge_scope_execution": scope, EXTENSION_SNAPSHOT_CONTEXT_KEY: get_loaded_extensions()},
    )
    message = result["messages"][-1]
    assert isinstance(message, ToolMessage)
    assert sources_from_messages([message]) == [source]
    context = provider.search_scoped.await_args.kwargs["context"]
    assert context.user_id == "alice"
    assert context.scope == scope
    provider.search.assert_not_awaited()


@pytest.mark.parametrize("mode", ["all", "disabled"])
def test_lightrag_accepts_only_nonfiltering_scopes(mode):
    config = provider_config()
    config.get_tool_config = lambda _: SimpleNamespace(use="deerflow.community.lightrag.tools:knowledge_search_tool")
    graph_input = {"messages": [HumanMessage(content="q", additional_kwargs={"knowledge_scope": {"version": 1, "mode": mode}})]}
    assert admit_message_knowledge_scope(graph_input, assistant_id="lead_agent", app_config=config, agent_config=None) == {"version": 1, "mode": mode}


@pytest.mark.asyncio
async def test_packaged_provider_catalog_scope_and_sources(monkeypatch):
    from pathlib import Path

    from deerflow.extensions import load_extensions
    from deerflow.extensions.loader import ExtensionSpec
    from deerflow.knowledge import KnowledgeRequestContext, format_result, sources_from_messages
    from deerflow.knowledge.providers import resolve_knowledge_provider

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-knowledge"))
    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_knowledge:install")])
    assert diagnostics == []
    provider = resolve_knowledge_provider(provider_config("synthetic-example"), extensions=loaded)
    context = KnowledgeRequestContext(user_id="alice", agent_name="lead_agent")
    catalog = await provider.catalog(context=context, page=1, page_size=20, search="")
    dataset = catalog.items[0]
    documents = await provider.documents(dataset.id, context=context, page=1, page_size=20, search="")
    scope = {"version": 1, "mode": "selected", "dataset_ids": [dataset.id], "document_filters": [{"dataset_id": dataset.id, "document_ids": [documents.items[0].id]}]}
    result = await search_provider(provider, "Cedar", scope=scope, user_id="alice", agent_name="lead_agent")
    content, artifact = format_result(result)
    sources = sources_from_messages([{"type": "tool", "content": content, "artifact": artifact}])
    assert len(sources) == 1 and sources[0].provider == "synthetic-example"
    assert sources[0].page is None and sources[0].url is None
    with pytest.raises(PermissionError):
        await search_provider(provider, "Cedar", scope={"version": 1, "mode": "selected", "dataset_ids": ["missing"]}, user_id="alice", agent_name="lead_agent")


@pytest.mark.asyncio
async def test_ragflow_adapter_keeps_selected_documents_allowlist_and_redaction(monkeypatch):
    from test_ragflow_tools import DATASET_ID_1, DATASET_ID_2, FakeRAGFlowClient, _config, _dataset

    from deerflow.community.ragflow import provider as ragflow_provider

    fake = FakeRAGFlowClient(
        datasets_by_id={DATASET_ID_1: [_dataset(DATASET_ID_1, "Private guide")]},
        documents_by_dataset_id={DATASET_ID_1: [{"id": "doc-1", "run": "DONE", "chunk_count": 1}]},
        retrieval={"chunks": [{"dataset_id": DATASET_ID_1, "document_keyword": "guide.pdf", "content": "Evidence ragflow-secret"}]},
    )
    monkeypatch.setattr(ragflow_provider, "build_ragflow_retrieval_client", lambda _: fake)
    provider = ragflow_provider.RAGFlowKnowledgeProvider(_config(datasets=[DATASET_ID_1]))
    scope = {"version": 1, "mode": "selected", "dataset_ids": [DATASET_ID_1], "document_filters": [{"dataset_id": DATASET_ID_1, "document_ids": ["doc-1"]}]}
    result = await search_provider(provider, "q", scope=scope, user_id="alice", agent_name="lead_agent")
    assert fake.retrieve_calls[0][1]["dataset_ids"] == [DATASET_ID_1]
    assert fake.retrieve_calls[0][1]["document_ids"] == ["doc-1"]
    assert result.hits[0].source.dataset_name == "Private guide"
    assert "ragflow-secret" not in str(result.model_dump())
    before = len(fake.retrieve_calls)
    with pytest.raises(PermissionError):
        await search_provider(provider, "q", scope={"version": 1, "mode": "selected", "dataset_ids": [DATASET_ID_2]}, user_id="alice", agent_name="lead_agent")
    assert len(fake.retrieve_calls) == before
