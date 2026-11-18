"""Persisted custom-agent knowledge defaults, using the existing scope contract."""

from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from _router_auth_helpers import make_authed_test_app
from fastapi import HTTPException
from langchain.tools import ToolRuntime
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from app.gateway.auth.models import User
from app.gateway.knowledge_scope_admission import admit_message_knowledge_scope
from app.gateway.routers.agents import AgentCreateRequest, AgentUpdateRequest, create_agent_endpoint, get_agent, router, update_agent
from deerflow.config.agents_api_config import load_agents_api_config_from_dict
from deerflow.config.agents_config import AgentConfig, preserve_non_managed_fields
from deerflow.config.app_config import AppConfig, pop_current_app_config, push_current_app_config
from deerflow.knowledge_scope import canonicalize_knowledge_scope

SCOPE = {
    "version": 1,
    "mode": "selected",
    "dataset_ids": ["policies"],
    "document_filters": [{"dataset_id": "policies", "document_ids": ["leave"]}],
    "display": {"datasets": [{"id": "policies", "name": "Policies", "documents": [{"id": "leave", "name": "Leave.pdf"}]}]},
}


def test_agent_config_validates_and_preserves_knowledge_default():
    config = AgentConfig(name="researcher", knowledge_scope=SCOPE)
    assert canonicalize_knowledge_scope(config.knowledge_scope) == SCOPE
    assert preserve_non_managed_fields(config)["knowledge_scope"]["dataset_ids"] == ["policies"]
    with pytest.raises(ValidationError):
        AgentConfig(name="researcher", knowledge_scope={"version": 1, "mode": "selected", "dataset_ids": []})


@pytest.fixture
def agent_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    yield
    load_agents_api_config_from_dict({})


@pytest.mark.asyncio
async def test_api_round_trip_preserve_replace_and_clear(agent_home):
    created = await create_agent_endpoint(AgentCreateRequest(name="researcher", knowledge_scope=SCOPE))
    assert canonicalize_knowledge_scope(created.knowledge_scope) == SCOPE
    updated = await update_agent("researcher", AgentUpdateRequest(description="Updated"))
    assert canonicalize_knowledge_scope(updated.knowledge_scope) == SCOPE
    await update_agent("researcher", AgentUpdateRequest(knowledge_scope={"version": 1, "mode": "disabled"}))
    assert canonicalize_knowledge_scope((await get_agent("researcher")).knowledge_scope) == {"version": 1, "mode": "disabled"}
    await update_agent("researcher", AgentUpdateRequest(knowledge_scope=None))
    assert (await get_agent("researcher")).knowledge_scope is None


@pytest.mark.parametrize("override", [None, {"version": 1, "mode": "all"}, {"version": 1, "mode": "disabled"}])
def test_default_is_snapshotted_but_explicit_turn_selection_wins(override):
    message = HumanMessage(content="Policy?", additional_kwargs={} if override is None else {"knowledge_scope": override})
    graph_input = {"messages": [message]}
    agent = SimpleNamespace(tool_groups=None, knowledge_scope=SCOPE)
    app = SimpleNamespace(knowledge_base=SimpleNamespace(enabled=True), get_tool_config=lambda _: SimpleNamespace(use="deerflow.community.ragflow.tools:knowledge_search_tool"))
    result = admit_message_knowledge_scope(graph_input, assistant_id="researcher", app_config=app, agent_config=agent)
    expected = override or SCOPE
    assert graph_input["messages"][0].additional_kwargs["knowledge_scope"] == expected
    assert result == {key: value for key, value in expected.items() if key != "display"}
    assert message.additional_kwargs == ({} if override is None else {"knowledge_scope": override})


@pytest.mark.parametrize("recovered", [None, {"version": 1, "mode": "disabled"}])
def test_recovery_does_not_pick_up_changed_agent_default(recovered):
    graph_input = {"messages": [HumanMessage(content="Policy?")]}
    app = SimpleNamespace(knowledge_base=SimpleNamespace(enabled=True), get_tool_config=lambda _: SimpleNamespace(use="deerflow.community.ragflow.tools:knowledge_search_tool"))
    result = admit_message_knowledge_scope(graph_input, assistant_id="researcher", app_config=app, agent_config=SimpleNamespace(tool_groups=None, knowledge_scope=SCOPE), recovery=True, recovery_scope=recovered)
    assert result == recovered
    assert graph_input["messages"][0].additional_kwargs == ({} if recovered is None else {"knowledge_scope": recovered})


@pytest.mark.asyncio
async def test_harness_setup_and_self_update_preserve_binding(agent_home):
    from deerflow.runtime.user_context import get_effective_user_id
    from deerflow.tools.builtins.setup_agent_tool import setup_agent
    from deerflow.tools.builtins.update_agent_tool import update_agent as update_tool

    await create_agent_endpoint(AgentCreateRequest(name="researcher", knowledge_scope=SCOPE))
    runtime = SimpleNamespace(context={"agent_name": "researcher", "user_id": get_effective_user_id()}, config={"configurable": {}}, tool_call_id="setup-1")
    result = setup_agent.func(soul="Updated soul", description="Rebootstrapped", runtime=runtime)
    assert "successfully" in result.update["messages"][0].content
    assert canonicalize_knowledge_scope((await get_agent("researcher")).knowledge_scope) == SCOPE
    assert (await get_agent("researcher")).description == "Rebootstrapped"
    update_tool.func(description="Updated by agent", runtime=runtime)
    assert canonicalize_knowledge_scope((await get_agent("researcher")).knowledge_scope) == SCOPE
    assert (await get_agent("researcher")).description == "Updated by agent"


@pytest.mark.asyncio
async def test_same_name_file_agents_keep_separate_bindings(agent_home):
    from app.gateway.services import _load_scope_agent_config
    from deerflow.persistence.agents import get_agent_store

    store = get_agent_store()
    store.create("researcher", {"knowledge_scope": SCOPE}, "Soul", user_id="alice")
    store.create("researcher", {"knowledge_scope": {"version": 1, "mode": "disabled"}}, "Soul", user_id="bob")
    alice = await _load_scope_agent_config(assistant_id="researcher", user_id="alice")
    bob = await _load_scope_agent_config(assistant_id="researcher", user_id="bob")
    assert canonicalize_knowledge_scope(alice.knowledge_scope) == SCOPE
    assert bob.knowledge_scope.mode == "disabled"


@pytest.mark.parametrize("tool_groups", [[], ["web"]])
def test_default_never_reenables_agent_knowledge_tools(tool_groups):
    from fastapi import HTTPException

    app = SimpleNamespace(knowledge_base=SimpleNamespace(enabled=True), get_tool_config=lambda _: SimpleNamespace(use="deerflow.community.ragflow.tools:knowledge_search_tool"))
    with pytest.raises(HTTPException) as error:
        admit_message_knowledge_scope({"messages": [HumanMessage(content="Policy?")]}, assistant_id="researcher", app_config=app, agent_config=SimpleNamespace(tool_groups=tool_groups, knowledge_scope=SCOPE))
    assert error.value.status_code == 422


@pytest.fixture(params=["file", "db"])
def self_update_context(request, agent_home, tmp_path):
    from sqlalchemy import create_engine

    from deerflow.persistence.agents import AgentRow, get_agent_store
    from deerflow.persistence.base import Base

    app = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "agent_storage": {"backend": request.param},
            "database": {"backend": "sqlite", "sqlite_dir": str(tmp_path)},
            "knowledge_base": {"enabled": True},
            "tools": [{"name": "knowledge_search", "group": "knowledge", "use": "deerflow.community.ragflow.tools:knowledge_search_tool"}],
        }
    )
    if request.param == "db":
        engine = create_engine(app.database.app_sync_sqlalchemy_url)
        Base.metadata.create_all(engine, tables=[AgentRow.__table__])
        engine.dispose()
    runtime = ToolRuntime(state={}, context={"agent_name": "researcher", "user_id": "alice"}, config={}, stream_writer=lambda _: None, tools=[], tool_call_id="update-1", store=None)
    push_current_app_config(app)
    try:
        yield get_agent_store(), app, runtime
    finally:
        pop_current_app_config()


@pytest.mark.asyncio
@pytest.mark.parametrize("old_groups", [None, ["web", "knowledge"]])
@pytest.mark.parametrize("new_groups", [[], ["web"]])
@pytest.mark.parametrize("scope", [SCOPE, {"version": 1, "mode": "disabled"}, {"version": 1, "mode": "all"}])
async def test_self_update_removing_knowledge_keeps_next_turn_admissible(self_update_context, old_groups, new_groups, scope):
    from app.gateway.services import _load_scope_agent_config
    from deerflow.tools.builtins.update_agent_tool import update_agent as update_tool

    store, app, runtime = self_update_context
    config = {"tool_groups": old_groups, "knowledge_scope": scope, "display_name": "Researcher"}
    store.create("researcher", config, "Research soul", user_id="alice")
    store.create("researcher", config, "Bob's soul", user_id="bob")
    before = await _load_scope_agent_config(assistant_id="researcher", user_id="alice")
    admit_message_knowledge_scope({"messages": [HumanMessage(content="Hello")]}, assistant_id="researcher", app_config=app, agent_config=before)

    result = update_tool.invoke({"runtime": runtime, "tool_groups": new_groups})
    assert result.update["messages"][0].status == "success"
    updated = await _load_scope_agent_config(assistant_id="researcher", user_id="alice")
    message = HumanMessage(content="Hello again")
    assert admit_message_knowledge_scope({"messages": [message]}, assistant_id="researcher", app_config=app, agent_config=updated) is None
    assert updated.knowledge_scope is None
    assert updated.tool_groups == new_groups
    assert updated.display_name == "Researcher"
    assert store.get_soul("researcher", user_id="alice") == "Research soul"
    assert canonicalize_knowledge_scope(store.get("researcher", user_id="bob").knowledge_scope) == scope

    # Clearing a default must not admit an explicit scope without tool access.
    with pytest.raises(HTTPException) as error:
        admit_message_knowledge_scope({"messages": [HumanMessage(content="Search", additional_kwargs={"knowledge_scope": scope})]}, assistant_id="researcher", app_config=app, agent_config=updated)
    assert error.value.status_code == 422


@pytest.mark.parametrize(
    "updates",
    [{"description": "Updated"}, {"skills": []}, {"soul": "Updated soul"}, {"tool_groups": ["knowledge"]}, {"tool_groups": ["web", "knowledge"]}, {"description": "Updated", "tool_groups": "null"}],
)
def test_self_update_preserves_knowledge_when_access_is_not_removed(self_update_context, updates):
    from deerflow.tools.builtins.update_agent_tool import update_agent as update_tool

    store, _, runtime = self_update_context
    store.create("researcher", {"tool_groups": ["web", "knowledge"], "knowledge_scope": SCOPE}, "Soul", user_id="alice")
    result = update_tool.invoke({"runtime": runtime, **updates})
    assert result.update["messages"][0].status == "success"
    assert canonicalize_knowledge_scope(store.get("researcher", user_id="alice").knowledge_scope) == SCOPE


def test_self_update_does_not_rewrite_untouched_incompatible_default(self_update_context):
    from deerflow.tools.builtins.update_agent_tool import update_agent as update_tool

    store, _, runtime = self_update_context
    store.create("researcher", {"tool_groups": ["web"], "knowledge_scope": SCOPE}, "Soul", user_id="alice")
    result = update_tool.invoke({"runtime": runtime, "description": "Updated", "tool_groups": ["web"]})
    assert result.update["messages"][0].status == "success"
    assert canonicalize_knowledge_scope(store.get("researcher", user_id="alice").knowledge_scope) == SCOPE


def test_self_update_without_knowledge_default_keeps_none(self_update_context):
    from deerflow.tools.builtins.update_agent_tool import update_agent as update_tool

    store, _, runtime = self_update_context
    store.create("researcher", {"tool_groups": ["web", "knowledge"]}, "Soul", user_id="alice")
    result = update_tool.invoke({"runtime": runtime, "tool_groups": []})
    assert result.update["messages"][0].status == "success"
    updated = store.get("researcher", user_id="alice")
    assert updated.tool_groups == []
    assert updated.knowledge_scope is None


@pytest_asyncio.fixture
async def http_update_context(self_update_context):
    store, config, _ = self_update_context
    user = User(id=uuid4(), email="agent-scope@example.com", password_hash="unused", system_role="user")
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent.test") as client:
        yield client, store, config, str(user.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("old_groups", [None, ["web", "knowledge"]])
@pytest.mark.parametrize("new_groups", [[], ["web"]])
@pytest.mark.parametrize("scope", [SCOPE, {"version": 1, "mode": "disabled"}, {"version": 1, "mode": "all"}])
async def test_http_removing_knowledge_keeps_next_turn_admissible(http_update_context, old_groups, new_groups, scope):
    from app.gateway.services import _load_scope_agent_config

    client, store, app, owner = http_update_context
    config = {"tool_groups": old_groups, "knowledge_scope": scope, "display_name": "Researcher"}
    store.create("researcher", config, "Research soul", user_id=owner)
    store.create("researcher", config, "Bob's soul", user_id="bob")

    response = await client.put("/api/agents/researcher", json={"tool_groups": new_groups})
    assert response.status_code == 200, response.text
    updated = await _load_scope_agent_config(assistant_id="researcher", user_id=owner)
    assert admit_message_knowledge_scope({"messages": [HumanMessage(content="Hello again")]}, assistant_id="researcher", app_config=app, agent_config=updated) is None
    assert response.json()["knowledge_scope"] is None
    assert updated.knowledge_scope is None
    assert updated.tool_groups == new_groups
    assert updated.display_name == "Researcher"
    assert store.get_soul("researcher", user_id=owner) == "Research soul"
    assert canonicalize_knowledge_scope(store.get("researcher", user_id="bob").knowledge_scope) == scope

    with pytest.raises(HTTPException) as error:
        admit_message_knowledge_scope({"messages": [HumanMessage(content="Search", additional_kwargs={"knowledge_scope": scope})]}, assistant_id="researcher", app_config=app, agent_config=updated)
    assert error.value.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "updates,expected",
    [
        ({}, SCOPE),
        ({"description": "Updated"}, SCOPE),
        ({"skills": []}, SCOPE),
        ({"soul": "Updated soul"}, SCOPE),
        ({"tool_groups": ["knowledge"]}, SCOPE),
        ({"tool_groups": ["web", "knowledge"]}, SCOPE),
        ({"tool_groups": None}, SCOPE),
        ({"knowledge_scope": None}, None),
        ({"tool_groups": ["web"], "knowledge_scope": None}, None),
        ({"knowledge_scope": {"version": 1, "mode": "disabled"}}, {"version": 1, "mode": "disabled"}),
        ({"tool_groups": ["knowledge"], "knowledge_scope": {"version": 1, "mode": "all"}}, {"version": 1, "mode": "all"}),
        ({"tool_groups": ["web"], "knowledge_scope": {"version": 1, "mode": "disabled"}}, {"version": 1, "mode": "disabled"}),
    ],
)
async def test_http_updates_preserve_omission_and_explicit_scope_semantics(http_update_context, updates, expected):
    client, store, _, owner = http_update_context
    store.create("researcher", {"tool_groups": ["web", "knowledge"], "knowledge_scope": SCOPE}, "Soul", user_id=owner)
    response = await client.put("/api/agents/researcher", json=updates)
    assert response.status_code == 200, response.text
    updated = store.get("researcher", user_id=owner)
    if expected is None:
        assert updated.knowledge_scope is None
        assert response.json()["knowledge_scope"] is None
    else:
        assert canonicalize_knowledge_scope(updated.knowledge_scope) == expected
        assert canonicalize_knowledge_scope(response.json()["knowledge_scope"]) == expected
    assert updated.tool_groups == updates.get("tool_groups", ["web", "knowledge"])


@pytest.mark.asyncio
async def test_http_unchanged_groups_do_not_migrate_incompatible_default(http_update_context):
    client, store, _, owner = http_update_context
    store.create("researcher", {"tool_groups": ["web"], "knowledge_scope": SCOPE}, "Soul", user_id=owner)
    response = await client.put("/api/agents/researcher", json={"description": "Updated", "tool_groups": ["web"]})
    assert response.status_code == 200, response.text
    assert canonicalize_knowledge_scope(store.get("researcher", user_id=owner).knowledge_scope) == SCOPE


@pytest.mark.asyncio
async def test_http_without_knowledge_default_keeps_none(http_update_context):
    client, store, _, owner = http_update_context
    store.create("researcher", {"tool_groups": ["web", "knowledge"]}, "Soul", user_id=owner)
    response = await client.put("/api/agents/researcher", json={"tool_groups": []})
    assert response.status_code == 200, response.text
    updated = store.get("researcher", user_id=owner)
    assert updated.tool_groups == []
    assert updated.knowledge_scope is None
