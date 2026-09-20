"""Persisted custom-agent knowledge defaults, using the existing scope contract."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from app.gateway.knowledge_scope_admission import admit_message_knowledge_scope
from app.gateway.routers.agents import AgentCreateRequest, AgentUpdateRequest, create_agent_endpoint, get_agent, update_agent
from deerflow.config.agents_api_config import load_agents_api_config_from_dict
from deerflow.config.agents_config import AgentConfig, preserve_non_managed_fields
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
