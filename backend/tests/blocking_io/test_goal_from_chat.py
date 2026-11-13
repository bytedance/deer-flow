"""Goal synthesis reads real config and model authorization off the event loop."""

import asyncio
import json

import httpx
import pytest
from _router_auth_helpers import make_authed_test_app
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.gateway import services
from app.gateway.auth.models import User
from app.gateway.routers import threads
from deerflow.config.app_config import reset_app_config
from deerflow.config.extensions_config import reset_extensions_config
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor, build_state_mutation_graph
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.store.memory import MemoryRunStore


@pytest.fixture
def file_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    extensions_path.write_text("{}", encoding="utf-8")
    reset_app_config()
    reset_extensions_config()
    yield config_path
    reset_app_config()
    reset_extensions_config()


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [True, False])
async def test_goal_from_chat_uses_file_config_and_model_policy(file_config, monkeypatch, allowed):
    config = {
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        "models": [
            {
                "name": "synthesis",
                "model": "fixture",
                "use": "langchain_core.language_models.fake_chat_models:FakeListChatModel",
                "responses": [json.dumps({"objective": "Reconcile the invoices.", "unclear": False, "reason": ""})],
            }
        ],
        "authorization": {
            "enabled": True,
            "provider": {
                "use": "deerflow.authz.rbac:RbacAuthorizationProvider",
                "config": {"roles": {"user": {"models": {"allow": ["synthesis"] if allowed else []}}}},
            },
        },
    }
    await asyncio.to_thread(file_config.write_text, json.dumps(config), encoding="utf-8")
    user = User(email="goal-test@example.com", password_hash="unused", system_role="user")
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
    app.include_router(threads.router)

    @app.middleware("http")
    async def trusted_session(request, call_next):
        request.state.auth_source = "session"
        return await call_next(request)

    app.state.checkpointer = InMemorySaver()
    app.state.store = InMemoryStore()
    app.state.run_event_store = MemoryRunEventStore()
    app.state.run_store = MemoryRunStore()
    app.state.run_manager = RunManager(store=app.state.run_store, event_store=app.state.run_event_store)
    app.state.thread_store = MemoryThreadMetaStore(app.state.store)
    await app.state.thread_store.create("goal-thread", user_id=str(user.id))
    graph = await asyncio.to_thread(build_state_mutation_graph, "seed", "full")
    accessor = CheckpointStateAccessor.bind(graph, app.state.checkpointer)
    await accessor.aupdate(
        {"configurable": {"thread_id": "goal-thread", "checkpoint_ns": ""}},
        {"messages": [HumanMessage(content="Reconcile the invoices.")]},
        as_node="seed",
    )
    monkeypatch.setattr(services, "resolve_agent_factory", lambda _: lambda **kwargs: graph)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway.test") as client:
        for _ in range(2):  # Cold config load and cached-config revalidation.
            response = await client.post("/api/threads/goal-thread/goal/from-chat", json={})
            assert response.status_code == (200 if allowed else 403), response.text
            if allowed:
                assert response.json()["goal"]["objective"] == "Reconcile the invoices."
        goal = await threads.read_thread_goal(app.state.checkpointer, "goal-thread")
        assert (goal is not None) is allowed
