"""Synthetic v0.8.3 responses; never contacts an external provider."""

import json
from pathlib import Path

import httpx
import pytest

from deerflow.knowledge import KnowledgeRequestContext, format_result, sources_from_messages


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-weknora"))
    from deerflow_extension_weknora import WeKnoraProvider

    monkeypatch.setenv("WEKNORA_TEST_KEY", "synthetic-secret")
    calls = []
    document = {"id": "doc-1", "knowledge_base_id": "kb-1", "title": "Synthetic guide", "parse_status": "completed", "enable_status": "enabled"}
    state = {"document": document, "hits": [{"knowledge_id": "doc-1", "content": "Cedar is synthetic evidence.", "knowledge_title": "Synthetic guide", "score": 0.8}]}

    def handler(request):
        calls.append(request)
        assert request.headers["X-API-Key"] == "synthetic-secret"
        assert request.headers["X-Tenant-ID"] in {"1", "2"}
        if state.get("status"):
            return httpx.Response(state["status"], text="synthetic-secret upstream body")
        if request.url.path == "/api/v1/knowledge-bases":
            data = state.get("bases", [{"id": "kb-1", "name": "Synthetic base"}])
        elif request.url.path == "/api/v1/knowledge-bases/kb-1/knowledge":
            return httpx.Response(200, json={"success": True, "data": [state["document"]], **state.get("pagination", {"total": 1})})
        elif request.url.path == "/api/v1/knowledge/doc-1":
            data = state["document"]
        elif request.url.path == "/api/v1/knowledge-search":
            return httpx.Response(403, json={"success": False, "error": "KB-restricted keys reject global knowledge_ids"})
        elif request.url.path == "/api/v1/knowledge-bases/kb-1/hybrid-search":
            data = state["hits"]
        else:
            return httpx.Response(404, json={"success": False})
        return httpx.Response(200, json={"success": True, "data": data})

    config = {"spaces": [{"base_url": "https://weknora.example", "tenant_id": "1", "api_key_env": "WEKNORA_TEST_KEY", "user_ids": ["alice"], "agent_names": ["lead_agent", "researcher"]}]}
    transport = httpx.MockTransport(handler)
    return WeKnoraProvider(config, transport=transport), calls, state, config, transport


async def selection(provider, *, docs=True):
    context = KnowledgeRequestContext("alice", "lead_agent")
    page = await provider.catalog(context=context, page=1, page_size=20, search="")
    dataset_id = page.items[0].id
    scope = {"version": 1, "mode": "selected", "dataset_ids": [dataset_id]}
    if docs:
        scope["document_filters"] = [{"dataset_id": dataset_id, "document_ids": ["doc-1"]}]
    return KnowledgeRequestContext("alice", "lead_agent", scope)


@pytest.mark.asyncio
async def test_catalog_documents_search_shared_evidence(adapter):
    provider, calls, _, _, _ = adapter
    ctx = await selection(provider)
    page = await provider.documents(ctx.scope["dataset_ids"][0], context=ctx, page=1, page_size=20, search="guide")
    assert page.items[0].selectable and page.items[0].id == "doc-1"
    assert calls[-1].url.params["keyword"] == "guide"
    result = await provider.search_scoped("Cedar", context=ctx)
    body = json.loads(next(r.content for r in calls if r.method == "POST"))
    assert body["knowledge_ids"] == ["doc-1"]
    assert "knowledge_base_ids" not in body
    assert body["query_text"] == "Cedar"
    assert body["skip_context_enrichment"] is True
    assert next(r for r in calls if r.method == "POST").url.path == "/api/v1/knowledge-bases/kb-1/hybrid-search"
    content, artifact = format_result(result)
    sources = sources_from_messages([{"type": "tool", "content": content, "artifact": artifact}])
    assert len(sources) == 1 and sources[0].provider == "weknora"
    assert sources[0].excerpt == "Cedar is synthetic evidence."
    assert sources[0].page is None and sources[0].url is None
    assert sources_from_messages([{"type": "tool", "content": "removed", "artifact": artifact}]) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("user,agent", [("mallory", "lead_agent"), ("alice", "unbound"), ("alice", None)])
async def test_unbound_identity_cannot_make_requests(adapter, user, agent):
    provider, calls, *_ = adapter
    ctx = KnowledgeRequestContext(user, agent)
    with pytest.raises(PermissionError):
        await provider.catalog(context=ctx, page=1, page_size=20, search="")
    with pytest.raises(PermissionError):
        await provider.search_scoped("Cedar", context=ctx)
    assert not calls


@pytest.mark.asyncio
async def test_no_context_search_is_not_an_authorization_bypass(adapter):
    provider, calls, *_ = adapter
    with pytest.raises(PermissionError):
        await provider.search("Cedar")
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [{"version": 1, "mode": "disabled"}, {"mode": "selected", "dataset_ids": []}])
async def test_disabled_or_invalid_scope_never_calls_upstream(adapter, scope):
    provider, calls, *_ = adapter
    with pytest.raises(ValueError):
        await provider.search_scoped("Cedar", context=KnowledgeRequestContext("alice", "lead_agent", scope))
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"knowledge_base_id": "other"}, {"id": "other"}, {"enable_status": "disabled"}, {"parse_status": "pending"}])
async def test_document_validation_precedes_search(adapter, change):
    provider, calls, state, *_ = adapter
    ctx = await selection(provider)
    state["document"].update(change)
    with pytest.raises(PermissionError):
        await provider.search_scoped("Cedar", context=ctx)
    assert not any(r.method == "POST" for r in calls)


@pytest.mark.asyncio
async def test_unselected_result_fails_entire_request(adapter):
    provider, calls, state, *_ = adapter
    ctx = await selection(provider)
    state["hits"].append({"knowledge_id": "other", "content": "must never escape"})
    with pytest.raises(PermissionError):
        await provider.search_scoped("Cedar", context=ctx)
    assert len([r for r in calls if r.method == "POST"]) == 1


@pytest.mark.asyncio
async def test_dataset_search_verifies_returned_document_membership(adapter):
    provider, _, state, *_ = adapter
    ctx = await selection(provider, docs=False)
    state["document"]["knowledge_base_id"] = "other"
    with pytest.raises(PermissionError):
        await provider.search_scoped("Cedar", context=ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,error", [(401, PermissionError), (403, PermissionError), (404, FileNotFoundError), (500, RuntimeError), (302, RuntimeError)])
async def test_http_errors_are_redacted_and_never_retried(adapter, status, error):
    provider, calls, state, *_ = adapter
    state["status"] = status
    with pytest.raises(error) as exc:
        await provider.catalog(context=KnowledgeRequestContext("alice", "lead_agent"), page=1, page_size=20, search="")
    assert "synthetic-secret" not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_multi_space_ids_are_stable_bounded_and_isolated(adapter):
    provider, _, _, config, transport = adapter
    from deerflow_extension_weknora import WeKnoraProvider

    config["spaces"].append({**config["spaces"][0], "tenant_id": "2", "user_ids": ["bob"]})
    multi = WeKnoraProvider(config, transport=transport)
    alice = await multi.catalog(context=KnowledgeRequestContext("alice", "lead_agent"), page=1, page_size=20, search="")
    bob = await multi.catalog(context=KnowledgeRequestContext("bob", "lead_agent"), page=1, page_size=20, search="")
    old = await provider.catalog(context=KnowledgeRequestContext("alice", "lead_agent"), page=1, page_size=20, search="")
    assert alice.items[0].id == old.items[0].id != bob.items[0].id
    assert len(alice.items[0].id) <= 256
    with pytest.raises(PermissionError):
        await multi.search_scoped("Cedar", context=KnowledgeRequestContext("bob", "lead_agent", {"version": 1, "mode": "selected", "dataset_ids": [alice.items[0].id]}))


@pytest.mark.asyncio
async def test_all_scope_still_sends_explicit_targets_and_subagent_works(adapter):
    provider, calls, *_ = adapter
    await provider.search_scoped("Cedar", context=KnowledgeRequestContext("alice", "researcher"))
    body = json.loads(next(r.content for r in calls if r.method == "POST"))
    assert "knowledge_base_ids" not in body and "knowledge_ids" not in body
    assert next(r for r in calls if r.method == "POST").url.path == "/api/v1/knowledge-bases/kb-1/hybrid-search"


@pytest.mark.asyncio
async def test_secrets_redacted_and_missing_attribution_not_invented(adapter):
    provider, _, state, *_ = adapter
    state["hits"][0].update(content="synthetic-secret evidence", knowledge_title="")
    state["document"]["title"] = ""
    result = await provider.search_scoped("Cedar", context=KnowledgeRequestContext("alice", "lead_agent"))
    assert "synthetic-secret" not in result.model_dump_json()
    assert result.hits[0].source is None


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", ["..", "../secret", "%2e%2e", "a/b", "x" * 257])
async def test_unsafe_native_ids_fail_before_path_request(adapter, bad_id):
    provider, calls, *_ = adapter
    ctx = await selection(provider)
    ctx.scope["document_filters"][0]["document_ids"] = [bad_id]
    with pytest.raises(ValueError):
        await provider.search_scoped("Cedar", context=ctx)
    assert not any("/knowledge/" in r.url.path or r.method == "POST" for r in calls)


def test_configuration_rejects_implicit_authorization_and_credentials(adapter):
    from deerflow_extension_weknora import WeKnoraProvider

    _, _, _, config, _ = adapter
    for change in ({"tenant_id": None}, {"user_ids": []}, {"base_url": "https://user:secret@example.com"}, {"api_key_env": ""}, {"knowledge_base_ids": []}):
        with pytest.raises(ValueError):
            WeKnoraProvider({"spaces": [{**config["spaces"][0], **change}]})


@pytest.mark.asyncio
async def test_packaged_registration_real_tool_replay_budget_and_delegation(adapter, monkeypatch):
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    from deerflow.extensions import EXTENSION_SNAPSHOT_CONTEXT_KEY, load_extensions
    from deerflow.extensions.loader import ExtensionSpec
    from deerflow.knowledge import tools
    from deerflow.knowledge.providers import GENERIC_KNOWLEDGE_TOOL, resolve_knowledge_provider
    from deerflow.knowledge.sources import prune_sources
    from deerflow.runtime.serialization import serialize_channel_values_for_api
    from deerflow.tools.builtins.task_tool import _task_result_command

    _, _, _, config, transport = adapter
    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_weknora:install", config=config)])
    assert diagnostics == []
    app_config = SimpleNamespace(get_tool_config=lambda _: SimpleNamespace(use=GENERIC_KNOWLEDGE_TOOL, model_extra={"provider": "weknora"}))
    provider = resolve_knowledge_provider(app_config, extensions=loaded)
    provider._transport = transport
    ctx = await selection(provider)
    monkeypatch.setattr(tools, "get_app_config", lambda: app_config)
    builder = StateGraph(MessagesState, context_schema=dict)
    builder.add_node("tools", ToolNode([tools.knowledge_search_tool]))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    result = await builder.compile().ainvoke(
        {"messages": [AIMessage(content="", tool_calls=[{"id": "call", "name": "knowledge_search", "args": {"query": "Cedar"}}])]},
        context={"user_id": "alice", "is_subagent": True, "agent_id": "researcher", "__knowledge_scope_execution": ctx.scope, EXTENSION_SNAPSHOT_CONTEXT_KEY: loaded},
    )
    message = result["messages"][-1]
    sources = sources_from_messages([message])
    assert len(sources) == 1 and sources[0].provider == "weknora"
    persisted = json.loads(json.dumps(serialize_channel_values_for_api({"messages": [message]})))
    assert sources_from_messages(persisted["messages"]) == sources
    command = _task_result_command(tool_call_id="task", status="completed", result=message.content, knowledge_sources=[s.model_dump(mode="json", exclude_none=True) for s in sources])
    assert sources_from_messages(command.update["messages"]) == sources
    _, pruned = prune_sources("truncated", message.artifact)
    assert pruned["knowledge_sources"] == []


@pytest.mark.asyncio
async def test_missing_key_fails_closed(adapter, monkeypatch):
    provider, calls, *_ = adapter
    monkeypatch.delenv("WEKNORA_TEST_KEY")
    with pytest.raises(RuntimeError):
        await provider.search_scoped("Cedar", context=KnowledgeRequestContext("alice", "lead_agent"))
    assert not calls


@pytest.mark.asyncio
async def test_allowlist_and_missing_configured_base(adapter):
    from deerflow_extension_weknora import WeKnoraProvider

    _, calls, state, config, transport = adapter
    config["spaces"][0]["knowledge_base_ids"] = ["kb-1"]
    provider = WeKnoraProvider(config, transport=transport)
    state["bases"] = [{"id": "kb-1", "name": "Allowed"}, {"id": "kb-2", "name": "Excluded"}]
    page = await provider.catalog(context=KnowledgeRequestContext("alice", "lead_agent"), page=1, page_size=20, search="")
    assert [item.name for item in page.items] == ["Allowed"]
    state["bases"] = [{"id": "kb-2", "name": "Excluded"}]
    with pytest.raises(PermissionError):
        await provider.search_scoped("Cedar", context=KnowledgeRequestContext("alice", "lead_agent"))
    assert not any(r.method == "POST" for r in calls)


@pytest.mark.asyncio
async def test_empty_catalog_never_sends_unconstrained_search(adapter):
    provider, calls, state, *_ = adapter
    state["bases"] = None
    result = await provider.search_scoped("Cedar", context=KnowledgeRequestContext("alice", "lead_agent"))
    assert result.hits == [] and not any(r.method == "POST" for r in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {"success": False, "data": []}, {"success": True}, {"success": True, "data": "bad"}])
async def test_malformed_upstream_response_fails_closed(adapter, payload):
    provider, *_ = adapter
    provider._transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    with pytest.raises(RuntimeError):
        await provider.catalog(context=KnowledgeRequestContext("alice", "lead_agent"), page=1, page_size=20, search="")


@pytest.mark.asyncio
async def test_response_size_limit(adapter):
    provider, *_ = adapter
    provider._transport = httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * (4 * 1024 * 1024 + 1)))
    with pytest.raises(RuntimeError, match="size"):
        await provider.catalog(context=KnowledgeRequestContext("alice", "lead_agent"), page=1, page_size=20, search="")


@pytest.mark.asyncio
async def test_all_document_selections_checked_before_any_search(adapter):
    provider, calls, *_ = adapter
    ctx = await selection(provider)
    ctx.scope["document_filters"][0]["document_ids"].append("missing")
    with pytest.raises(FileNotFoundError):
        await provider.search_scoped("Cedar", context=ctx)
    assert not any(r.method == "POST" for r in calls)


def test_gateway_catalog_uses_authenticated_user_with_real_adapter(adapter):
    from _router_auth_helpers import make_authed_test_app
    from deerflow_extension_weknora import WeKnoraProvider
    from fastapi.testclient import TestClient

    from app.gateway.auth.models import User
    from app.gateway.deps import get_config
    from app.gateway.routers import knowledge
    from deerflow.config.app_config import AppConfig
    from deerflow.extensions import ExtensionRegistry

    _, calls, _, config, transport = adapter
    user = User(email="weknora@example.com", password_hash="unused", system_role="user")
    config["spaces"][0]["user_ids"] = [str(user.id)]
    provider = WeKnoraProvider(config, transport=transport)
    registry = ExtensionRegistry()
    with registry.attributed_to("deerflow_extension_weknora:install"):
        registry.knowledge_provider("weknora", provider)
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
    app.state.extensions = registry.build()
    app.include_router(knowledge.router)
    app_config = AppConfig.model_validate(
        {
            "models": [],
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "knowledge_base": {"enabled": True, "scope_selection_enabled": True},
            "tools": [{"name": "knowledge_search", "group": "knowledge", "use": "deerflow.knowledge.tools:knowledge_search_tool", "provider": "weknora"}],
        }
    )
    app.dependency_overrides[get_config] = lambda: app_config
    with TestClient(app) as client:
        cap = client.get("/api/knowledge/capabilities?agent_name=lead_agent")
        assert cap.status_code == 200 and cap.json()["scope_selection_enabled"] is True
        catalog = client.get("/api/knowledge/retrieval-catalog/datasets?agent_name=lead_agent&user_id=mallory")
        assert catalog.status_code == 200
        dataset_id = catalog.json()["items"][0]["id"]
        documents = client.get(f"/api/knowledge/retrieval-catalog/datasets/{dataset_id}/documents?agent_name=lead_agent")
        assert documents.status_code == 200 and documents.json()["items"][0]["selectable"] is True
        assert client.get("/api/knowledge/retrieval-catalog/datasets/unknown/documents?agent_name=lead_agent").status_code == 403
    assert all(r.method == "GET" for r in calls)


@pytest.mark.asyncio
async def test_oversized_hit_list_does_not_cause_unbounded_detail_requests(adapter):
    provider, calls, state, *_ = adapter
    state["hits"] = [{"knowledge_id": f"doc-{i}", "content": "synthetic"} for i in range(101)]
    with pytest.raises(RuntimeError, match="result limit"):
        await provider.search_scoped("Cedar", context=KnowledgeRequestContext("alice", "lead_agent"))
    assert not any("/knowledge/" in r.url.path for r in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("pagination", [{}, {"total": None}, {"total": "1"}, {"total": True}, {"total": -1}, {"total": 1.5}])
async def test_invalid_document_total_is_explicit_provider_error(adapter, pagination):
    provider, calls, state, *_ = adapter
    ctx = await selection(provider)
    state["pagination"] = pagination
    with pytest.raises(RuntimeError, match="Invalid WeKnora document total"):
        await provider.documents(ctx.scope["dataset_ids"][0], context=ctx, page=1, page_size=20, search="")
    assert not any(r.method == "POST" for r in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["hits", "document"])
@pytest.mark.parametrize("data", ["bad", [], ["bad"], 42])
async def test_malformed_retrieval_payloads_fail_without_retry(adapter, target, data):
    provider, calls, state, *_ = adapter
    ctx = await selection(provider)
    state[target] = data
    if target == "hits" and data == []:
        assert (await provider.search_scoped("Cedar", context=ctx)).hits == []
    else:
        with pytest.raises(RuntimeError, match="Invalid WeKnora"):
            await provider.search_scoped("Cedar", context=ctx)
    assert len([r for r in calls if r.method == "POST"]) == (1 if target == "hits" else 0)


@pytest.mark.asyncio
async def test_retrieval_response_size_limit_without_retry(adapter):
    provider, calls, _, _, transport = adapter
    ctx = await selection(provider, docs=False)
    posts = []

    async def handler(request):
        if request.method == "POST":
            posts.append(request)
            return httpx.Response(200, content=b"x" * (4 * 1024 * 1024 + 1))
        return await transport.handle_async_request(request)

    provider._transport = httpx.MockTransport(handler)
    with pytest.raises(RuntimeError, match="size"):
        await provider.search_scoped("Cedar", context=ctx)
    assert len(posts) == 1
    assert not any("/knowledge/" in r.url.path for r in calls)
