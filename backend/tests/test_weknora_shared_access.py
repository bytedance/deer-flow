"""Dynamic users share only an explicitly configured read-only connection."""

import asyncio

import pytest
from test_weknora_extension import adapter as adapter

from deerflow.knowledge import KnowledgeRequestContext


@pytest.fixture
def shared(adapter):
    from deerflow_extension_weknora import WeKnoraProvider

    _, calls, state, config, transport = adapter
    space = config["spaces"][0]
    space.pop("user_ids")
    space["access_mode"] = "authenticated"
    space["knowledge_base_ids"] = ["kb-1"]
    return WeKnoraProvider(config, transport=transport), calls, state, config


@pytest.mark.asyncio
@pytest.mark.parametrize("user", ["new-registration-a", "new-registration-b"])
async def test_shared_new_users_can_browse_and_search_without_user_bindings(shared, user):
    provider, calls, *_ = shared
    context = KnowledgeRequestContext(user, "lead_agent", authenticated_user_id=user)
    catalog = await provider.catalog(context=context, page=1, page_size=20, search="")
    assert len(catalog.items) == 1
    dataset = catalog.items[0].id
    documents = await provider.documents(dataset, context=context, page=1, page_size=20, search="")
    assert documents.items[0].id == "doc-1"
    selected = KnowledgeRequestContext(user, "lead_agent", {"version": 1, "mode": "selected", "dataset_ids": [dataset]}, authenticated_user_id=user)
    assert (await provider.search_scoped("Cedar", context=selected)).hits
    await provider.entries_search("Cedar", context=selected)
    assert all(r.method == "GET" or r.url.path.endswith(("/hybrid-search", "/wiki/search")) for r in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(("user", "verified"), [("new-user", None), ("default", None), ("new-user", "other-user"), ("", "")])
async def test_shared_requires_matching_verified_identity_before_http(shared, user, verified):
    provider, calls, *_ = shared
    context = KnowledgeRequestContext(user, "lead_agent", authenticated_user_id=verified)
    with pytest.raises(PermissionError):
        await provider.catalog(context=context, page=1, page_size=20, search="")
    assert not calls


@pytest.mark.asyncio
async def test_shared_still_enforces_agent_and_base_restrictions(shared):
    provider, calls, state, _ = shared
    with pytest.raises(PermissionError):
        await provider.catalog(context=KnowledgeRequestContext("new-user", "forbidden-agent", authenticated_user_id="new-user"), page=1, page_size=20, search="")
    assert not calls
    state["bases"] = [{"id": "kb-1", "name": "Allowed"}, {"id": "kb-private", "name": "Private"}]
    context = KnowledgeRequestContext("new-user", "researcher", authenticated_user_id="new-user")
    catalog = await provider.catalog(context=context, page=1, page_size=20, search="")
    assert [item.name for item in catalog.items] == ["Allowed"]
    state["document"]["knowledge_base_id"] = "kb-private"
    with pytest.raises(PermissionError):
        await provider.search_scoped("Cedar", context=context)


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"user_ids": None},
        {"user_ids": []},
        {"access_mode": "all"},
        {"access_mode": "authenticated", "user_ids": ["alice"]},
        {"access_mode": "authenticated", "user_ids": []},
        {"access_mode": True},
    ],
)
def test_access_mode_must_be_explicit_and_unambiguous(adapter, changes):
    from deerflow_extension_weknora import WeKnoraProvider

    config = adapter[3]
    space = dict(config["spaces"][0])
    space.pop("user_ids")
    with pytest.raises(ValueError):
        WeKnoraProvider({"spaces": [{**space, **changes}]})


@pytest.mark.asyncio
async def test_verified_user_does_not_bypass_default_allowlist(adapter):
    provider, calls, *_ = adapter
    with pytest.raises(PermissionError):
        await provider.catalog(context=KnowledgeRequestContext("new-user", "lead_agent", authenticated_user_id="new-user"), page=1, page_size=20, search="")
    assert not calls


@pytest.mark.parametrize("credential", ["session", "pat", "anonymous", "auth_disabled", "internal"])
def test_gateway_propagates_only_verified_user_to_shared_catalog_and_tool(shared, monkeypatch, credential):
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    from app.gateway.auth.models import User
    from app.gateway.auth_middleware import AuthMiddleware
    from app.gateway.deps import get_config
    from app.gateway.internal_auth import create_internal_auth_headers
    from app.gateway.routers import knowledge
    from deerflow.config.app_config import AppConfig
    from deerflow.config.authorization_config import AuthorizationConfig
    from deerflow.extensions import EXTENSION_SNAPSHOT_CONTEXT_KEY, ExtensionRegistry
    from deerflow.knowledge.tools import knowledge_search_tool

    provider, calls, *_ = shared
    users = [User(email=f"shared-{i}@example.com", password_hash="unused", system_role="user") for i in range(2)]

    async def resolve_user(request):
        return users[int(request.cookies["access_token"])]

    async def resolve_pat(app, authorization):
        return users[0], frozenset({"threads:read"})

    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", resolve_user)
    monkeypatch.setattr("app.gateway.auth.pat.authenticate_pat", resolve_pat)
    monkeypatch.setattr("app.gateway.auth.pat.is_pat_allowed_route", lambda *args: True)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig())
    registry = ExtensionRegistry()
    with registry.attributed_to("deerflow_extension_weknora:install"):
        registry.knowledge_provider("weknora", provider)
    loaded = registry.build()
    config = AppConfig.model_validate(
        {
            "models": [],
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "knowledge_base": {"enabled": True, "scope_selection_enabled": True},
            "tools": [{"name": "knowledge_search", "group": "knowledge", "use": "deerflow.knowledge.tools:knowledge_search_tool", "provider": "weknora"}],
        }
    )
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.state.extensions = loaded
    app.include_router(knowledge.router)
    app.dependency_overrides[get_config] = lambda: config
    graph_builder = StateGraph(MessagesState, context_schema=dict)
    graph_builder.add_node("tools", ToolNode([knowledge_search_tool]))
    graph_builder.add_edge(START, "tools")
    graph_builder.add_edge("tools", END)
    graph = graph_builder.compile()

    @app.get("/api/shared-search")
    async def search(request: Request):
        # These forged values must never become authentication evidence.
        context = {
            "user_id": str(request.state.user.id),
            "authenticated_user_id": str(request.state.user.id),
            "authenticated": True,
            "app_config": config,
            EXTENSION_SNAPSHOT_CONTEXT_KEY: loaded,
        }
        if request.query_params.get("child"):
            context.update(is_subagent=True, agent_id="researcher")
        result = await asyncio.create_task(
            graph.ainvoke(
                {"messages": [AIMessage(content="", tool_calls=[{"id": "shared-search", "name": "knowledge_search", "args": {"query": "Cedar"}}])]},
                context=context,
            )
        )
        message = result["messages"][-1]
        return {"content": message.content, "artifact": message.artifact}

    headers = {}
    cookies = {}
    if credential == "session":
        cookies["access_token"] = "0"
    elif credential == "pat":
        headers["Authorization"] = "Bearer synthetic-pat"
    elif credential == "auth_disabled":
        monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    elif credential == "internal":
        headers = create_internal_auth_headers()

    allowed = credential in {"session", "pat"}
    with TestClient(app, headers=headers, cookies=cookies) as client:
        catalog = client.get("/api/knowledge/retrieval-catalog/datasets?agent_name=lead_agent&authenticated=true&user_id=alice")
        assert catalog.status_code == (200 if allowed else 401 if credential == "anonymous" else 403)
        search = client.get("/api/shared-search")
        if allowed:
            assert search.json()["artifact"]["knowledge_sources"]
            assert client.get("/api/shared-search?child=1").json()["artifact"]["knowledge_sources"]
            dataset = catalog.json()["items"][0]["id"]
            assert client.get(f"/api/knowledge/retrieval-catalog/datasets/{dataset}/documents?agent_name=lead_agent").status_code == 200
            if credential == "session":
                client.cookies.set("access_token", "1")
                assert client.get("/api/knowledge/retrieval-catalog/datasets?agent_name=lead_agent").status_code == 200
        else:
            assert search.status_code == 401 or search.json()["artifact"] is None
            assert not calls
