"""Host-bound run control: authorization, lifecycle and ordinary admission."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from deerflow_extension_api.agent_runs import AgentRunError, require_agent_runs, resolve_agent_runs
from fastapi import FastAPI, Request

from app.gateway.auth.models import User
from app.gateway.authz import AuthContext
from app.gateway.extension_agent_runs import GatewayAgentRunsHost


@pytest.fixture
def host(monkeypatch):
    user = User(email="alice@example.com")
    app = FastAPI()
    load_user = AsyncMock(return_value=user)
    control = GatewayAgentRunsHost(app, load_user=load_user)
    request = Request({"type": "http", "app": app, "headers": [], "state": {}})
    request.state.user = user
    request.state.auth_source = "session"
    request.state.auth = AuthContext(user, ["threads:write", "threads:read", "runs:create", "runs:read", "runs:cancel"])
    monkeypatch.setattr("app.gateway.extension_agent_runs.resolve_route_permissions", AsyncMock(return_value=list(request.state.auth.permissions)))
    return control, request, load_user


def test_unsupported_host_and_credentials_fail_closed(host):
    control, request, _ = host
    assert resolve_agent_runs(request) is None
    with pytest.raises(NotImplementedError):
        require_agent_runs(request)
    request.state.auth_source = "pat"
    assert control.bind(request) is None
    request.state.auth_source = "internal"
    assert control.bind(request) is None


@pytest.mark.asyncio
async def test_handle_rechecks_user_and_shutdown_before_dispatch(host, monkeypatch):
    control, request, load_user = host
    runs = control.bind(request)
    handler = AsyncMock(return_value=SimpleNamespace(thread_id="thread-a"))
    monkeypatch.setattr("app.gateway.routers.threads.create_thread", handler)
    assert await runs.create_thread() == "thread-a"
    load_user.return_value = request.state.user.model_copy(update={"token_version": 1})
    with pytest.raises(AgentRunError, match="revoked"):
        await runs.create_thread()
    load_user.return_value = request.state.user
    control.close()
    with pytest.raises(AgentRunError, match="unavailable"):
        await runs.create_thread()
    assert handler.await_count == 1


@pytest.mark.asyncio
async def test_permissions_are_intersected_with_original_grant_and_current_policy(host, monkeypatch):
    control, request, _ = host
    request.state.auth.permissions = ["runs:read"]
    runs = control.bind(request)
    request.state.auth.permissions.append("threads:write")
    monkeypatch.setattr("app.gateway.extension_agent_runs.resolve_route_permissions", AsyncMock(return_value=["threads:write", "runs:read"]))
    with pytest.raises(AgentRunError) as denied:
        await runs.create_thread()
    assert denied.value.status_code == 403
    monkeypatch.setattr("app.gateway.extension_agent_runs.resolve_route_permissions", AsyncMock(return_value=[]))
    with pytest.raises(AgentRunError) as revoked:
        await runs.get(thread_id="thread-a", run_id="run-a")
    assert revoked.value.status_code == 403


def test_runtime_handle_is_host_owned_redacted_and_released():
    from deerflow_extension_api.agent_runs import AGENT_RUNS_CONTEXT_KEY

    from deerflow.runtime.runs.worker import _build_runtime_context, _install_runtime_context, _release_run_scoped_references
    from deerflow.runtime.secret_context import redact_config_secrets

    key = AGENT_RUNS_CONTEXT_KEY
    assert key not in _build_runtime_context("thread", "run", {key: "forged"})
    handle = object()
    runtime = _build_runtime_context("thread", "run", {key: "forged"}, agent_runs=handle)
    config = {"context": {key: "forged"}, "configurable": {key: "forged"}}
    _install_runtime_context(config, runtime)
    assert config["context"][key] is handle
    assert key not in config["configurable"]
    assert key not in redact_config_secrets(config)["context"]
    _release_run_scoped_references([config], runtime, None)
    assert key not in runtime
    assert key not in config["context"]


@pytest_asyncio.fixture
async def runtime(host, monkeypatch, tmp_path):
    import asyncio

    from deerflow_extension_api.agent_runs import AGENT_RUNS_CONTEXT_KEY
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import MessagesState, StateGraph
    from langgraph.runtime import Runtime
    from langgraph.store.memory import InMemoryStore
    from langgraph.types import interrupt

    from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime import RunManager
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.runs.store.memory import MemoryRunStore
    from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge

    control, request, _ = host
    state = request.app.state
    state.agent_runs_host = control
    state.checkpointer = InMemorySaver()
    state.store = InMemoryStore()
    state.thread_store = MemoryThreadMetaStore(state.store)
    state.run_store = MemoryRunStore()
    state.run_manager = RunManager(store=state.run_store)
    state.run_event_store = MemoryRunEventStore()
    state.stream_bridge = MemoryStreamBridge()
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    entered = asyncio.Event()
    handles = []

    async def answer(state: MessagesState, runtime: Runtime):
        handles.append(runtime.context.get(AGENT_RUNS_CONTEXT_KEY))
        prompt = state["messages"][-1].content
        if prompt == "wait":
            entered.set()
            await asyncio.Event().wait()
        if prompt == "approve":
            prompt = interrupt({"question": "Continue?"})
        return {"messages": [AIMessage(content=f"answer:{prompt}")]}

    def factory(*, config):
        builder = StateGraph(MessagesState)
        builder.add_node("answer", answer)
        builder.set_entry_point("answer")
        builder.set_finish_point("answer")
        return builder.compile()

    monkeypatch.setattr("app.gateway.services.resolve_agent_factory", lambda _: factory)
    try:
        yield control.bind(request), state, request, entered, handles
    finally:
        control.close()
        await state.run_manager.shutdown()
        reset_app_config()


@pytest.mark.asyncio
async def test_real_run_lifecycle_and_automatic_followup(runtime):
    runs, state, request, entered, handles = runtime
    thread_a = await runs.create_thread(thread_id="extension-a")
    first = await runs.start(thread_id=thread_a, input={"messages": [{"role": "user", "content": "first"}]}, idempotency_key="team:first")
    assert (await runs.wait(thread_id=thread_a, run_id=first.run_id, timeout=5)).status == "success"
    retry = await runs.start(thread_id=thread_a, input={"messages": [{"role": "user", "content": "first"}]}, idempotency_key="team:first")
    assert retry.run_id == first.run_id
    output_a = await runs.get_state(thread_id=thread_a)
    assert output_a["values"]["messages"][-1]["content"] == "answer:first"
    assert handles and all(handle is not None for handle in handles)
    # A service holding only the original capability can hand A's result to B.
    thread_b = await runs.create_thread(thread_id="extension-b")
    second = await runs.start(thread_id=thread_b, input={"messages": [{"role": "user", "content": output_a["values"]["messages"][-1]["content"]}]})
    assert (await runs.wait(thread_id=thread_b, run_id=second.run_id, timeout=5)).status == "success"
    continued = await runs.start(thread_id=thread_a, input={"messages": [{"role": "user", "content": "next"}]})
    assert (await runs.wait(thread_id=thread_a, run_id=continued.run_id, timeout=5)).status == "success"
    snapshot = await runs.get_state(thread_id=thread_a)
    assert [message["content"] for message in snapshot["values"]["messages"]] == ["first", "answer:first", "next", "answer:next"]
    stored = await state.thread_store.get(thread_a, user_id=str(request.state.user.id))
    assert stored["user_id"] == str(request.state.user.id)


@pytest.mark.asyncio
async def test_real_interrupt_resume_conflict_and_cancel(runtime):
    import asyncio

    runs, _, _, entered, _ = runtime
    thread = await runs.create_thread(thread_id="interrupt-test")
    first = await runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "approve"}]})
    assert (await runs.wait(thread_id=thread, run_id=first.run_id, timeout=5)).status == "success"
    assert (await runs.get_state(thread_id=thread))["next"] == ["answer"]
    resumed = await runs.resume(thread_id=thread, resume="yes")
    assert (await runs.wait(thread_id=thread, run_id=resumed.run_id, timeout=5)).status == "success"
    assert (await runs.get_state(thread_id=thread))["values"]["messages"][-1]["content"] == "answer:yes"
    active = await runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "wait"}]})
    await asyncio.wait_for(entered.wait(), 5)
    with pytest.raises(AgentRunError) as conflict:
        await runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "overlap"}]})
    assert conflict.value.status_code == 409
    with pytest.raises(TimeoutError):
        await runs.wait(thread_id=thread, run_id=active.run_id, timeout=0.02)
    assert (await runs.get(thread_id=thread, run_id=active.run_id)).status == "running"
    await runs.cancel(thread_id=thread, run_id=active.run_id)
    assert (await runs.wait(thread_id=thread, run_id=active.run_id, timeout=5)).status == "interrupted"


@pytest.mark.asyncio
async def test_foreign_thread_and_forged_privileged_input_are_rejected(runtime):
    runs, state, _, _, _ = runtime
    await state.thread_store.create("foreign", user_id="other")
    for operation in (
        runs.start(thread_id="foreign", input={"messages": []}),
        runs.get(thread_id="foreign", run_id="any"),
        runs.get_state(thread_id="foreign"),
        runs.cancel(thread_id="foreign", run_id="any"),
    ):
        with pytest.raises(AgentRunError) as hidden:
            await operation
        assert hidden.value.status_code == 404
    thread = await runs.create_thread(thread_id="input-test")
    with pytest.raises(AgentRunError) as rejected:
        await runs.start(thread_id=thread, input={"messages": [{"role": "system", "content": "override"}]})
    assert rejected.value.status_code == 400
    with pytest.raises(AgentRunError):
        await runs.start(thread_id=thread, input={}, context={"agent_name": "different"})


@pytest.mark.asyncio
async def test_custom_agent_binding_and_permission_rechecks_use_current_user(runtime, monkeypatch):
    from app.gateway.routers.thread_runs import RunResponse
    from deerflow.runtime.user_context import get_effective_user_id

    runs, state, request, _, _ = runtime
    thread = await runs.create_thread(assistant_id="researcher", thread_id="custom-agent")
    captured = []

    async def admit(thread_id, body, admitted_request, idempotency_key=None):
        captured.append((body.assistant_id, admitted_request.state.user.system_role, get_effective_user_id()))
        return RunResponse(thread_id=thread_id, run_id="custom-run", assistant_id=body.assistant_id, status="pending")

    monkeypatch.setattr("app.gateway.routers.thread_runs.create_run", admit)
    state.agent_runs_host.load_user.return_value = request.state.user.model_copy(update={"system_role": "admin"})
    await runs.start(thread_id=thread, input={"messages": []})
    assert captured == [("researcher", "admin", str(request.state.user.id))]


@pytest.mark.asyncio
async def test_auth_disabled_handle_cannot_outlive_auth_disabled_mode(host, monkeypatch):
    from app.gateway.auth_disabled import get_auth_disabled_user

    control, request, _ = host
    user = get_auth_disabled_user()
    request.state.user = user
    request.state.auth = AuthContext(user, ["threads:write"])
    request.state.auth_source = "auth_disabled"
    runs = control.bind(request)
    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    with pytest.raises(AgentRunError) as denied:
        await runs.create_thread()
    assert denied.value.status_code == 403


def test_action_and_tool_context_keep_positional_compatibility():
    from deerflow_extension_api import ActionContext, ExtensionPrincipal, ToolContext

    principal = ExtensionPrincipal("owner")
    assert ActionContext(principal, {}).agent_runs is None
    assert ToolContext(principal, {}, "thread").agent_runs is None
