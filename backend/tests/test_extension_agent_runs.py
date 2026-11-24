"""Host-bound run control: authorization, lifecycle and ordinary admission."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

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


def test_unstamped_requests_receive_no_delegated_capability(host):
    control, request, _ = host
    assert control.bind(SimpleNamespace(state=SimpleNamespace())) is None
    assert control.bind(SimpleNamespace(state=SimpleNamespace(user=request.state.user, auth_source="internal"))) is None
    request.state.auth = SimpleNamespace(is_authenticated=False)
    assert control.bind(request) is None


def test_binding_rejects_inconsistent_authenticated_identity(host):
    control, request, _ = host
    request.state.user = User(email="other@example.com")
    with pytest.raises(PermissionError):
        control.bind(request)


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
async def test_handle_rechecks_current_account_disablement(host, monkeypatch):
    control, request, load_user = host
    runs = control.bind(request)
    handler = AsyncMock(return_value=SimpleNamespace(thread_id="thread-a"))
    monkeypatch.setattr("app.gateway.routers.threads.create_thread", handler)
    assert await runs.create_thread() == "thread-a"
    # Disabling the account leaves token_version unchanged, so the per-operation
    # guard must observe the current disabled state, not only the mint-time one.
    load_user.return_value = request.state.user.model_copy(update={"disabled": True})
    with pytest.raises(AgentRunError, match="revoked"):
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
            await getattr(request.app.state, "release_worker", asyncio.Event()).wait()
        if present := getattr(request.app.state, "present_worker_report", None):
            await present(prompt, runtime)
        if prompt == "approve":
            prompt = interrupt({"question": "Continue?"})
        return {"messages": [AIMessage(content=f"answer:{prompt}")]}

    def factory(*, config):
        if (settings := getattr(state, "observed_worker_settings", None)) is not None and "run_id" in config["context"]:
            context = config["context"]
            settings.append((config["recursion_limit"], context.get("thinking_enabled"), context.get("is_plan_mode")))
        builder = StateGraph(MessagesState)
        builder.add_node("answer", answer)
        builder.set_entry_point("answer")
        builder.set_finish_point("answer")
        from deerflow_extension_api import AgentAssemblyDescriptor

        from deerflow.agents.lead_agent.agent import LeadAgentAssembly

        descriptor = AgentAssemblyDescriptor(
            namespace="fixture",
            agent_name="lead-agent",
            requested_model=None,
            effective_model="fixture-model",
            model_parameters={"temperature": 0},
            thinking_enabled=False,
            reasoning_effort=None,
            base_prompt_hash="fixture-prompt",
            tools=(),
            middlewares=(),
            deferred_tool_names=(),
            enabled_skills=(),
            effective_policies={"skill_catalog_hash": "fixture-skills"},
        )
        return LeadAgentAssembly(graph=builder.compile(), descriptor=descriptor, effective_model="fixture-model")

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
@pytest.mark.skipif(os.name != "posix", reason="Descriptor-confined artifact imports require POSIX")
async def test_team_artifact_import_is_authorized_idempotent_and_confined(runtime):
    import asyncio
    import hashlib

    from deerflow.config.paths import get_paths

    runs, state, request, entered, _ = runtime
    runs = runs.for_plugin("artifact-fixture")
    thread = await runs.create_thread(thread_id="artifact-recipient")
    content = b"%PDF-1.7\n\x00\xff immutable source"
    imported = await runs.import_artifact(thread_id=thread, filename="report.pdf", content=content)
    assert imported["sha256"] == hashlib.sha256(content).hexdigest()
    assert imported["size"] == len(content)
    target = get_paths().sandbox_uploads_dir(thread, user_id=str(request.state.user.id)) / imported["filename"]
    assert await asyncio.to_thread(target.read_bytes) == content
    assert await runs.import_artifact(thread_id=thread, filename="report.pdf", content=content) == imported
    assert len(await asyncio.to_thread(lambda: list(target.parent.iterdir()))) == 1
    await asyncio.to_thread(target.write_bytes, b"recipient edited its copy")
    with pytest.raises(AgentRunError) as changed:
        await runs.import_artifact(thread_id=thread, filename="report.pdf", content=content)
    assert changed.value.status_code == 422
    assert await asyncio.to_thread(target.read_bytes) == b"recipient edited its copy"
    run = await runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "wait"}]})
    await asyncio.wait_for(entered.wait(), 5)
    with pytest.raises(AgentRunError) as busy:
        await runs.import_artifact(thread_id=thread, filename="other.pdf", content=content)
    assert busy.value.status_code == 409
    with pytest.raises(AgentRunError) as capture_busy:
        await runs.read_artifact(thread_id=thread, path="/mnt/user-data/outputs/report.pdf")
    assert capture_busy.value.status_code == 409
    await runs.cancel(thread_id=thread, run_id=run.run_id)
    await runs.wait(thread_id=thread, run_id=run.run_id, timeout=5)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="Descriptor-confined artifact imports require POSIX")
async def test_team_artifact_import_rechecks_permission_owner_and_payload(runtime, monkeypatch):
    runs, state, request, _, _ = runtime
    thread = await runs.create_thread(thread_id="artifact-recipient")
    runs = runs.for_plugin("artifact-fixture")
    for filename, content in (("../escape.txt", b"x"), ("/etc/passwd", b"x"), ("bad\nname.txt", b"x"), ("report.pdf", b"x" * (2 * 1024 * 1024 + 1))):
        with pytest.raises(AgentRunError) as invalid:
            await runs.import_artifact(thread_id=thread, filename=filename, content=content)
        assert invalid.value.status_code == 422
    with pytest.raises(AgentRunError) as missing:
        await runs.import_artifact(thread_id="unknown-thread", filename="report.txt", content=b"x")
    assert missing.value.status_code == 404
    monkeypatch.setattr("app.gateway.extension_agent_runs.resolve_route_permissions", AsyncMock(return_value=["threads:read"]))
    with pytest.raises(AgentRunError) as denied:
        await runs.import_artifact(thread_id=thread, filename="report.txt", content=b"x")
    assert denied.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("launcher", ["scheduled", "mcp"])
async def test_internal_launchers_work_with_installed_host_without_delegation(runtime, launcher, monkeypatch):
    from app.gateway.services import launch_mcp_task_notification_run, launch_scheduled_thread_run

    runs, state, request, _, handles = runtime
    monkeypatch.setattr("app.gateway.services.get_local_provider", lambda: SimpleNamespace(get_user=AsyncMock(return_value=request.state.user)))
    thread = await runs.create_thread(thread_id="internal-launch")
    kwargs = dict(app=request.app, thread_id=thread, assistant_id="lead_agent", owner_user_id=str(request.state.user.id))
    if launcher == "scheduled":
        result = await launch_scheduled_thread_run(**kwargs, prompt="scheduled", metadata={"scheduled_task_run_id": "occurrence-1"})
    else:
        result = await launch_mcp_task_notification_run(**kwargs, task_id="task-1", dispatch_version=1, dispatch_attempt=1, event={"status": "completed"})
    assert (await runs.wait(thread_id=thread, run_id=result["run_id"], timeout=5)).status == "success"
    assert handles == [None]
    assert (await state.thread_store.get(thread, user_id=str(request.state.user.id)))["user_id"] == str(request.state.user.id)


@pytest.mark.asyncio
async def test_plugin_actions_isolate_same_local_idempotency_key(runtime):
    import json

    from deerflow_extension_api.agent_runs import AGENT_RUNS_RESOLVER_KEY
    from deerflow_extension_api.auth import EXTENSION_PRINCIPAL_RESOLVER_KEY, ExtensionPrincipal
    from deerflow_extension_api.plugins import BackendAction, PluginContribution

    from app.gateway.routers.plugins import invoke_plugin_action
    from deerflow.extensions.registry import ExtensionRegistry

    runs, state, request, _, _ = runtime
    thread = await runs.create_thread(thread_id="plugin-keys")

    async def start(payload, context):
        run = await context.agent_runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "same input"}]}, idempotency_key=payload["key"])
        return {"run_id": run.run_id}

    registry = ExtensionRegistry()
    for namespace in ("community.first", "community.second"):
        with registry.attributed_to(namespace):
            registry.plugin(PluginContribution(namespace=namespace, title=namespace, enabled=True, backend=(BackendAction("start", start),)))
    state.extensions = registry.build()
    setattr(state, AGENT_RUNS_RESOLVER_KEY, state.agent_runs_host.bind)
    setattr(state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda _: ExtensionPrincipal(str(request.state.user.id)))

    async def invoke(namespace):
        async def receive():
            return {"type": "http.request", "body": json.dumps({"key": "shared:operation"}).encode(), "more_body": False}

        admitted = Request({"type": "http", "app": request.app, "headers": [], "state": {"user": request.state.user, "auth": request.state.auth, "auth_source": "session"}}, receive)
        return await invoke_plugin_action(admitted, namespace, "start")

    first = await invoke("community.first")
    await runs.wait(thread_id=thread, run_id=first["run_id"], timeout=5)
    second = await invoke("community.second")
    assert second["run_id"] != first["run_id"]
    await runs.wait(thread_id=thread, run_id=second["run_id"], timeout=5)
    assert (await invoke("community.first"))["run_id"] == first["run_id"]


@pytest.mark.asyncio
async def test_plugin_scoping_preserves_key_validation_and_authorization(host):
    control, request, load_user = host
    scoped = control.bind(request).for_plugin("community.test")
    assert scoped.for_plugin("community.test") is scoped
    with pytest.raises(AgentRunError):
        scoped.for_plugin("community.other")
    for key in ("", " ", "x" * 201, 1):
        with pytest.raises(AgentRunError) as invalid:
            await scoped.start(thread_id="thread", input={}, idempotency_key=key)
        assert invalid.value.status_code == 422
    load_user.return_value = None
    with pytest.raises(AgentRunError) as revoked:
        await scoped.get(thread_id="thread", run_id="run")
    assert revoked.value.status_code == 403


@pytest.mark.asyncio
async def test_wait_uses_capped_backoff_and_returns_terminal_status(host, monkeypatch):
    from deerflow_extension_api.agent_runs import AgentRun

    control, request, _ = host
    runs = control.bind(request)
    runs.get = AsyncMock(side_effect=[AgentRun("thread", "run", "running")] * 6 + [AgentRun("thread", "run", "interrupted")])
    sleep = AsyncMock()
    monkeypatch.setattr("app.gateway.extension_agent_runs.asyncio.sleep", sleep)
    assert (await runs.wait(thread_id="thread", run_id="run")).status == "interrupted"
    assert [call.args[0] for call in sleep.await_args_list] == [0.25, 0.5, 1, 2, 4, 4]


@pytest.mark.asyncio
async def test_real_interrupt_resume_conflict_and_cancel(runtime):
    import asyncio

    runs, _, _, entered, _ = runtime
    thread = await runs.create_thread(thread_id="interrupt-test")
    first = await runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "approve"}]})
    assert (await runs.wait(thread_id=thread, run_id=first.run_id, timeout=5)).status == "waiting_for_input"
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
async def test_create_thread_rejects_an_assistant_id_that_names_no_agent(runtime):
    runs, state, _, _, _ = runtime
    with pytest.raises(AgentRunError) as rejected:
        await runs.create_thread(assistant_id="bad name!", thread_id="invalid-agent")
    assert rejected.value.status_code == 422
    assert await state.thread_store.get("invalid-agent", user_id=None) is None


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


@pytest.mark.asyncio
async def test_configuration_revision_is_private_scoped_and_detects_changes(host, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    control, request, load_user = host
    app_config = {"models": [{"api_key": "secret", "name": "a"}]}
    agent_config = {"name": "reviewer", "model": "a"}
    soul = Mock(return_value="review carefully")
    monkeypatch.setattr("deerflow.config.app_config.get_app_config", lambda: SimpleNamespace(model_dump=lambda **kw: app_config))
    monkeypatch.setattr("deerflow.config.extensions_config.get_extensions_config", lambda: SimpleNamespace(model_dump=lambda **kw: {}))
    monkeypatch.setattr("deerflow.config.agents_config.load_agent_config", lambda *a, **kw: SimpleNamespace(model_dump=lambda **kw: agent_config))
    monkeypatch.setattr("deerflow.config.agents_config.load_agent_soul", soul)
    runs = control.bind(request)
    before = await runs.configuration_revision(assistant_ids=["reviewer", "lead_agent"])
    assert len(before) == 64 and "secret" not in before
    assert before == await runs.configuration_revision(assistant_ids=["lead_agent", "reviewer"])
    soul.return_value = "changed instructions"
    assert before != await runs.configuration_revision(assistant_ids=["reviewer", "lead_agent"])
    soul.return_value = "review carefully"
    agent_config["model"] = "b"
    assert before != await runs.configuration_revision(assistant_ids=["reviewer", "lead_agent"])
    load_user.return_value = None
    with pytest.raises(AgentRunError, match="revoked"):
        await runs.configuration_revision(assistant_ids=["lead_agent"])


@pytest.mark.asyncio
async def test_actual_assembly_evidence_is_retained_and_bound(runtime):
    runs, state, request, _, _ = runtime
    thread = await runs.create_thread(thread_id="proof-thread")
    run = await runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "proof"}]})
    assert (await runs.wait(thread_id=thread, run_id=run.run_id, timeout=5)).status == "success"
    evidence = await runs.configuration_evidence(thread_id=thread, run_id=run.run_id)
    assert evidence["model"] == "fixture-model"
    assert evidence["run_id"] == run.run_id
    evidence["model"] = "tampered"
    retained = await runs.configuration_evidence(thread_id=thread, run_id=run.run_id)
    assert retained["model"] == "fixture-model"
    with pytest.raises(ValueError, match="immutable"):
        await state.run_manager.record_assembly_evidence(run.run_id, evidence)
    other = await runs.create_thread(thread_id="other-proof-thread")
    with pytest.raises(AgentRunError):
        await runs.configuration_evidence(thread_id=other, run_id=run.run_id)


@pytest.mark.asyncio
async def test_evidence_persistence_failure_prevents_execution(runtime, monkeypatch):
    runs, state, _, _, handles = runtime

    async def fail(*args, **kwargs):
        raise RuntimeError("evidence persistence unavailable")

    monkeypatch.setattr(state.run_manager, "record_assembly_evidence", fail)
    thread = await runs.create_thread(thread_id="proof-failure")
    run = await runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "must not run"}]})
    assert (await runs.wait(thread_id=thread, run_id=run.run_id, timeout=5)).status == "error"
    assert not handles
    with pytest.raises(AgentRunError, match="unavailable"):
        await runs.configuration_evidence(thread_id=thread, run_id=run.run_id)


@pytest.mark.asyncio
async def test_peer_takeover_during_assembly_is_not_undone_by_evidence(runtime, monkeypatch, tmp_path):
    """A peer reclaims the run while this worker assembles; evidence must not revive the row."""
    import asyncio
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update
    from test_run_repository import _cleanup, _make_repo

    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.persistence.run.model import RunRow
    from deerflow.runtime import RunManager
    from deerflow.runtime.assembly_evidence import EVIDENCE_KEY

    runs, state, _, _, handles = runtime
    repository = await _make_repo(tmp_path)
    state.run_store = repository
    await state.run_manager.shutdown()
    ownership = RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=30, grace_seconds=1)
    state.run_manager = RunManager(store=repository, run_ownership_config=ownership, worker_id="worker-a")
    peer = RunManager(store=repository, run_ownership_config=ownership, worker_id="worker-b")
    loop = asyncio.get_running_loop()
    taken_over = []

    async def peer_takeover():
        # The peer sees an expired lease (clock skew or a stalled owner) that
        # the owning worker still believes is live.
        async with repository._sf() as session:
            await session.execute(update(RunRow).where(RunRow.thread_id == thread).values(lease_expires_at=datetime.now(UTC) - timedelta(minutes=1)))
            await session.commit()
        taken_over.extend(await peer.reconcile_orphaned_inflight_runs(error="reclaimed by worker-b", stop_reason="orphan_recovered"))

    import app.gateway.services as services

    assemble = services.resolve_agent_factory("lead_agent")

    def factory_with_takeover(*, config):
        asyncio.run_coroutine_threadsafe(peer_takeover(), loop).result(timeout=5)
        return assemble(config=config)

    monkeypatch.setattr("app.gateway.services.resolve_agent_factory", lambda _: factory_with_takeover)
    try:
        thread = await runs.create_thread(thread_id="takeover-during-assembly")
        run = await runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "must not run"}]})
        record = await state.run_manager.get(run.run_id)
        await asyncio.wait({record.task}, timeout=5)
        assert [record.run_id for record in taken_over] == [run.run_id]
        row = await repository.get(run.run_id, user_id=None)
        assert row["status"] == "error"
        assert row["error"] == "reclaimed by worker-b"
        assert row["stop_reason"] == "orphan_recovered"
        assert EVIDENCE_KEY not in row["metadata"]
        assert record.ownership_lost
        assert not handles
        # The owner's renewal stays rejected, so the peer's outcome is final.
        await state.run_manager._renew_leases()
        assert (await repository.get(run.run_id, user_id=None))["status"] == "error"
    finally:
        await state.run_manager.shutdown()
        await _cleanup()


@pytest.mark.asyncio
async def test_durable_configuration_revision_survives_host_replacement_and_rotation(host, monkeypatch):
    control, request, load_user = host
    monkeypatch.setattr("deerflow.config.app_config.get_app_config", lambda: SimpleNamespace(model_dump=lambda **kw: {"model": "test"}))
    monkeypatch.setattr("deerflow.config.extensions_config.get_extensions_config", lambda: SimpleNamespace(model_dump=lambda **kw: {}))
    secret = SimpleNamespace(jwt_secret="stable-test-signing-key")
    monkeypatch.setattr("app.gateway.auth.config.get_auth_config", lambda: secret)
    first = control.bind(request)
    durable = await first.configuration_revision(assistant_ids=["lead_agent"], durable=True)
    ephemeral = await first.configuration_revision(assistant_ids=["lead_agent"])
    control.close()
    second = GatewayAgentRunsHost(request.app, load_user=load_user).bind(request)
    assert durable == await second.configuration_revision(assistant_ids=["lead_agent"], durable=True)
    assert ephemeral != await second.configuration_revision(assistant_ids=["lead_agent"])
    secret.jwt_secret = "rotated"
    assert durable != await second.configuration_revision(assistant_ids=["lead_agent"], durable=True)
    load_user.return_value = None
    with pytest.raises(AgentRunError):
        await second.configuration_revision(assistant_ids=["lead_agent"], durable=True)


@pytest.mark.asyncio
async def test_execution_fence_namespace_and_host_prerequisites(runtime):
    from deerflow_extension_api import ExecutionFence

    runs, state, request, _, _ = runtime
    runs = runs.for_plugin("test.fenced")
    thread_id = await runs.create_thread(thread_id="fenced-thread")
    with pytest.raises(AgentRunError, match="belong to this plugin"):
        await runs.start(thread_id=thread_id, input={}, execution_fence=ExecutionFence("other", "workflow", "owner", 1))
    with pytest.raises(AgentRunError, match="heartbeats"):
        await runs.start(thread_id=thread_id, input={}, execution_fence=ExecutionFence("test.fenced", "workflow", "owner", 1))


@pytest.mark.asyncio
async def test_host_forwards_fence_to_atomic_admission(runtime, monkeypatch, tmp_path):
    from deerflow_extension_api import ExecutionFence
    from sqlalchemy import insert
    from test_run_repository import _cleanup, _make_repo

    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.persistence.extension_leases.model import ExtensionExecutionLeaseRow
    from deerflow.runtime import RunManager

    runs, state, request, _, _ = runtime
    repository = await _make_repo(tmp_path)
    state.run_store = repository
    await state.run_manager.shutdown()
    state.run_manager = RunManager(store=repository, run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
    # Transport is irrelevant to this admission test; advertise its prerequisite
    # without starting Redis. The actual host/manager/store admission path is real.
    monkeypatch.setattr(type(state.stream_bridge), "supports_cross_process", True, raising=False)
    monkeypatch.setattr(type(state.stream_bridge), "start_producer_lease", AsyncMock(return_value=True), raising=False)
    runs = runs.for_plugin("test.fenced")
    thread_id = await runs.create_thread(thread_id="fenced-host-thread")
    async with repository._sf() as session:
        await session.execute(insert(ExtensionExecutionLeaseRow).values(namespace="test.fenced", resource_id="workflow", user_id=str(request.state.user.id), holder_id="new", epoch=2, expires_at=9999999999))
        await session.commit()
    try:
        with pytest.raises(AgentRunError) as failure:
            await runs.start(thread_id=thread_id, input={"messages": [{"role": "user", "content": "must not execute"}]}, execution_fence=ExecutionFence("test.fenced", "workflow", "old", 1))
        assert failure.value.status_code == 409
        assert "execution fence" in str(failure.value)
    finally:
        await state.run_manager.shutdown()
        await _cleanup()


@pytest.mark.asyncio
async def test_configuration_revision_canonicalizes_sets_but_preserves_list_order(host, monkeypatch):
    class OrderedSet(set):
        def __init__(self, values):
            super().__init__(values)
            self.values = values

        def __iter__(self):
            return iter(self.values)

    control, request, _ = host
    data = {"tools": ["first", "second"], "exempt_tools": OrderedSet(["task", "present_files"])}

    # Pydantic JSON mode loses the distinction between sets and ordered lists.
    def dump(**kwargs):
        return {**data, "exempt_tools": list(data["exempt_tools"])} if kwargs.get("mode") == "json" else data

    monkeypatch.setattr("deerflow.config.app_config.get_app_config", lambda: SimpleNamespace(model_dump=dump))
    monkeypatch.setattr("deerflow.config.extensions_config.get_extensions_config", lambda: SimpleNamespace(model_dump=lambda **kw: {}))
    runs = control.bind(request)
    before = await runs.configuration_revision(assistant_ids=["lead_agent"], durable=True)
    data["exempt_tools"] = OrderedSet(["present_files", "task"])
    assert before == await runs.configuration_revision(assistant_ids=["lead_agent"], durable=True)
    data["tools"].reverse()
    assert before != await runs.configuration_revision(assistant_ids=["lead_agent"], durable=True)


@pytest.mark.asyncio
async def test_capture_authority_snapshots_the_session_ceiling(host, monkeypatch):
    control, request, _ = host
    runs = control.bind(request)
    handler = AsyncMock(return_value=SimpleNamespace(thread_id="thread-a"))
    monkeypatch.setattr("app.gateway.routers.threads.create_thread", handler)
    assert await runs.create_thread() == "thread-a"
    captured = runs.capture_authority()
    assert captured == {
        "token_version": request.state.user.token_version,
        "source": "session",
        "permissions": sorted(request.state.auth.permissions),
    }


@pytest.mark.asyncio
async def test_restore_delegated_authority_enforces_validator_per_operation(host, monkeypatch):
    control, request, load_user = host
    handler = AsyncMock(return_value=SimpleNamespace(thread_id="thread-a"))
    monkeypatch.setattr("app.gateway.routers.threads.create_thread", handler)
    calls = []

    async def validator():
        calls.append(1)
        if len(calls) > 1:
            raise PermissionError("grant revoked by the owner")

    runs = await control.restore_delegated_authority(
        user_id=str(request.state.user.id),
        grant={"token_version": request.state.user.token_version, "source": "session", "permissions": ["threads:write"]},
        validator=validator,
        plugin_namespace="workflows",
    )
    assert await runs.create_thread() == "thread-a"
    with pytest.raises(AgentRunError, match="Delegated authorization revoked"):
        await runs.create_thread()
    assert handler.await_count == 1


@pytest.mark.asyncio
async def test_restore_delegated_authority_maps_validator_errors_to_403(host, monkeypatch):
    control, request, _ = host
    handler = AsyncMock(return_value=SimpleNamespace(thread_id="thread-a"))
    monkeypatch.setattr("app.gateway.routers.threads.create_thread", handler)

    async def validator():
        raise AgentRunError(403, "Workflow recovery grant expired or revoked")

    runs = await control.restore_delegated_authority(
        user_id=str(request.state.user.id),
        grant={"token_version": request.state.user.token_version, "source": "session", "permissions": ["threads:write"]},
        validator=validator,
    )
    with pytest.raises(AgentRunError, match="grant expired or revoked"):
        await runs.create_thread()
    assert handler.await_count == 0


@pytest.mark.asyncio
async def test_restore_delegated_authority_rejects_stale_grants(host):
    control, request, load_user = host
    user = request.state.user
    load_user.return_value = user.model_copy(update={"token_version": user.token_version + 1})
    with pytest.raises(AgentRunError, match="Delegated authorization revoked"):
        await control.restore_delegated_authority(
            user_id=str(user.id),
            grant={"token_version": user.token_version, "source": "session", "permissions": ["threads:write"]},
        )
    with pytest.raises(AgentRunError, match="Invalid delegated authority"):
        await control.restore_delegated_authority(
            user_id=str(user.id),
            grant={"token_version": user.token_version, "source": "pat", "permissions": ["threads:write"]},
        )
    with pytest.raises(AgentRunError, match="Invalid delegated authority"):
        await control.restore_delegated_authority(
            user_id=str(user.id),
            grant={"token_version": user.token_version, "source": "session", "permissions": [1]},
        )


@pytest.mark.asyncio
async def test_restored_delegated_handle_is_plugin_scoped_with_extension_origin(host):
    control, request, _ = host
    runs = await control.restore_delegated_authority(
        user_id=str(request.state.user.id),
        grant={"token_version": request.state.user.token_version, "source": "session", "permissions": ["threads:write"]},
        plugin_namespace="workflows",
    )
    assert runs.for_plugin("workflows") is runs
    assert runs._origin == {"kind": "extension", "namespace": "workflows"}
    with pytest.raises(AgentRunError, match="already bound"):
        runs.for_plugin("other")


@pytest_asyncio.fixture
async def worker_gateway(runtime, tmp_path):
    import asyncio

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.gateway.coordination_workers import CoordinationWorkers
    from app.gateway.routers import coordination, thread_runs
    from deerflow.persistence.bootstrap import bootstrap_schema
    from deerflow.persistence.channel_connections.sql import ChannelConnectionRepository
    from deerflow.persistence.coordination.workers import CoordinationWorkerRepository
    from deerflow.persistence.run import RunRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.runtime import RunManager
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    runs, state, request, entered, _ = runtime
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'workers.db'}")
    await bootstrap_schema(engine, backend="sqlite")
    factory = async_sessionmaker(engine)
    async with factory.begin() as session:
        session.add(UserRow(id=str(request.state.user.id), email=request.state.user.email))
    state.run_store = RunRepository(factory)
    await state.run_manager.shutdown()
    state.run_manager = RunManager(store=state.run_store)
    state.coordination_workers = CoordinationWorkers(CoordinationWorkerRepository(factory), state.agent_runs_host, ChannelConnectionRepository(factory))
    state.release_worker = asyncio.Event()
    state.observed_worker_settings = []
    request.app.include_router(coordination.router)
    request.app.include_router(thread_runs.router)

    async def authenticated(scope, receive, send):
        token = set_current_user(request.state.user)
        try:
            await request.app({**scope, "state": dict(request.scope["state"])}, receive, send)
        finally:
            reset_current_user(token)

    try:
        async with AsyncClient(transport=ASGITransport(app=authenticated), base_url="http://gateway") as client:
            yield client, runs, state, entered, str(request.state.user.id)
    finally:
        await state.coordination_workers.close()
        await state.run_manager.shutdown()
        await engine.dispose()


async def _wait_for_worker(client, task_id, section, field, value):
    import asyncio

    async with asyncio.timeout(12):
        while True:
            response = await client.get(f"/api/coordination/tasks/{task_id}")
            response.raise_for_status()
            view = response.json()
            if view[section][field] == value:
                return view
            await asyncio.sleep(0.05)


@pytest.mark.asyncio
@pytest.mark.parametrize("followup_report", [None, b"revised report"], ids=["text-followup", "same-name-file"])
async def test_managed_worker_routes_followups_and_retains_the_producing_runs_file(worker_gateway, followup_report):
    import asyncio
    from uuid import uuid4

    from langchain_core.messages import AIMessage, ToolMessage
    from langgraph.types import Command

    from deerflow.config.paths import get_paths
    from deerflow.persistence.coordination.sql import TaskNotFound

    client, runs, state, entered, owner = worker_gateway

    async def present_report(prompt, runtime):
        assert runtime.context["subagent_enabled"] is True
        report = b"original report" if prompt == "wait" else followup_report
        if report is not None:
            outputs = get_paths().sandbox_outputs_dir(runtime.context["thread_id"], user_id=owner)
            await asyncio.to_thread(outputs.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread((outputs / "report.txt").write_bytes, report)
            journal = runtime.context["__run_journal"]
            journal._remember_current_run_tool_calls(AIMessage(content="", tool_calls=[{"id": "present", "name": "present_files", "args": {}}]), caller="lead_agent")
            journal.on_tool_end(Command(update={"artifacts": ["/mnt/user-data/outputs/report.txt"], "messages": [ToolMessage("Presented", tool_call_id="present")]}), run_id=uuid4())

    state.present_worker_report = present_report
    url = "/api/coordination/tasks"
    body = {"request_id": "dispatch", "objective": "wait"}
    first = (await client.post(url, json=body)).raise_for_status().json()
    task_id, thread, run = first["task"]["id"], first["assignment"]["thread_id"], first["execution"]["run_id"]
    assert first["task"]["project_id"] is None and (await client.post(url, json=body)).json()["execution"]["run_id"] == run
    await asyncio.wait_for(entered.wait(), 10)
    thread_url = f"/api/threads/{thread}"
    inbox_url = f"{url}/{task_id}/inputs"
    (await client.post(inbox_url, json={"request_id": "task-input", "content": "task follow-up"})).raise_for_status()
    followup = {"request_id": "fix", "mode": "queue", "text": "new requirement"}
    receipt = (await client.post(f"{thread_url}/runs/{run}/inputs", json=followup)).raise_for_status().json()
    assert receipt["status"] == "pending"
    assert (await client.post(f"{thread_url}/runs/{run}/inputs", json=followup)).json() == receipt
    direct = asyncio.create_task(client.post(f"{thread_url}/runs", json={"input": {"messages": [{"type": "human", "content": [{"type": "text", "text": "final instruction"}]}]}}))
    try:
        await _wait_for_worker(client, task_id, "task", "latest_input_seq", 3)
        pending = (await client.get(inbox_url)).raise_for_status().json()
        assert [(item["sequence"], item["source"], item["content"], item["status"]) for item in pending] == [
            (1, "task_api", "task follow-up", "pending"),
            (2, "run_input", "new requirement", "pending"),
            (3, "worker_chat", "final instruction", "pending"),
        ]
        assert (await client.get(inbox_url, params={"after": 1, "limit": 1})).raise_for_status().json() == pending[1:2]
        assert (await client.get(f"{url}/missing-task/inputs")).status_code == 404
    finally:
        state.release_worker.set()
        (await direct).raise_for_status()
    result = await _wait_for_worker(client, task_id, "task", "status", "succeeded")
    final_run = result["execution"]["run_id"]
    assert final_run != run and result["task"]["result_ref"] == f"{thread_url}/runs/{final_run}/messages"
    assert (await direct).raise_for_status().json()["run_id"] == final_run
    assert (await runs.get_state(thread_id=thread))["values"]["messages"][-1]["content"] == "answer:final instruction"
    assert (await client.get(f"{thread_url}/inputs")).json()["items"][0]["run_id"] == final_run
    admitted = (await client.get(inbox_url)).raise_for_status().json()
    assert [(item["run_id"], item["status"]) for item in admitted] == [(final_run, "admitted")] * 3
    artifact_list = f"{url}/{task_id}/artifacts"
    artifacts = (await client.get(artifact_list)).raise_for_status().json()
    expected_versions = [(run, 1, b"original report")]
    if followup_report:
        expected_versions.append((final_run, 2, followup_report))
    assert [(item["run_id"], item["turn"]) for item in artifacts] == [(producer, turn) for producer, turn, _ in expected_versions]
    assert {item["source_path"] for item in artifacts} == {"/mnt/user-data/outputs/report.txt"}
    assert len({item["url"] for item in artifacts}) == len(expected_versions)
    assert result["execution"]["artifacts"] == (artifacts[1:] if followup_report else [])
    assert (await client.get(artifact_list, params={"limit": 1, "offset": 1})).raise_for_status().json() == artifacts[1:]
    assert (await client.get(f"{url}/missing-task/artifacts")).status_code == 404
    await asyncio.to_thread((get_paths().sandbox_outputs_dir(thread, user_id=owner) / "report.txt").unlink)
    for artifact, (_, _, content) in zip(artifacts, expected_versions, strict=True):
        assert (await client.get(artifact["url"])).raise_for_status().content == content
    with pytest.raises(TaskNotFound):
        await state.coordination_workers.repo.read_artifact("another-user", task_id, artifacts[0]["id"])


@pytest.mark.asyncio
async def test_managed_worker_reuses_saved_run_settings_for_followups(worker_gateway):
    import asyncio

    client, _, state, entered, _ = worker_gateway
    url = "/api/coordination/tasks"
    settings = {"recursion_limit": 400, "thinking_enabled": True, "is_plan_mode": False}
    body = {"request_id": "dispatch", "objective": "wait", "run": settings}
    first = (await client.post(url, json=body)).raise_for_status().json()
    task_id = first["task"]["id"]
    try:
        await asyncio.wait_for(entered.wait(), 10)
        assert first["task"]["run_settings"] == settings
        assert (await client.post(url, json=body)).raise_for_status().json() == first
        assert (await client.post(url, json={**body, "run": {**settings, "is_plan_mode": True}})).status_code == 409
        (await client.post(f"{url}/{task_id}/inputs", json={"request_id": "follow-up", "content": "Review the results"})).raise_for_status()
    finally:
        state.release_worker.set()

    finished = await _wait_for_worker(client, task_id, "task", "status", "succeeded")
    assert finished["execution"]["turn"] == 2
    assert state.observed_worker_settings == [(400, True, False)] * 2


@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [{"recursion_limit": 0}, {"recursion_limit": True}, {"thinking_enabled": "false"}, {"user_id": "another-user"}, {"subagent_enabled": False}])
async def test_managed_worker_rejects_invalid_run_settings(worker_gateway, settings):
    client, _, _, _, _ = worker_gateway
    response = await client.post("/api/coordination/tasks", json={"request_id": "invalid", "objective": "Review", "run": settings})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][:2] == ["body", "run"]


@pytest.mark.asyncio
async def test_managed_worker_create_retry_returns_task_after_grant_expires(worker_gateway, monkeypatch):
    import asyncio

    client, _, state, entered, owner = worker_gateway
    url = "/api/coordination/tasks"
    body = {"request_id": "create-replay", "objective": "wait"}
    first = (await client.post(url, json=body)).raise_for_status().json()
    assert first["task"]["run_settings"] is None
    assert (await client.post(url, json={**body, "run": {}})).raise_for_status().json() == first
    task_id = first["task"]["id"]
    await asyncio.wait_for(entered.wait(), 10)
    try:
        grant = await state.coordination_workers.repo.grant(owner, task_id)
        monkeypatch.setattr("deerflow.persistence.coordination.workers.time", lambda: grant["expires_at"] + 1)
        detail = (await client.get(f"{url}/{task_id}")).raise_for_status().json()
        replay = (await client.post(url, json=body)).raise_for_status().json()
        assert replay == detail
        assert replay["authorization_required"] is True
        assert replay["execution"]["run_id"] == first["execution"]["run_id"]
        assert (await client.post(url, json={**body, "objective": "changed"})).status_code == 409
        assert (await client.post(url, json={**body, "assistant_id": "different"})).status_code == 409
    finally:
        state.release_worker.set()


@pytest.mark.asyncio
async def test_managed_worker_replays_accepted_inputs_after_grant_expires(worker_gateway, monkeypatch):
    import asyncio

    client, _, state, entered, owner = worker_gateway
    tasks = "/api/coordination/tasks"
    first = (await client.post(tasks, json={"request_id": "receipt-replay", "objective": "wait"})).raise_for_status().json()
    task_id, thread_id, run_id = first["task"]["id"], first["assignment"]["thread_id"], first["execution"]["run_id"]
    inputs = [
        (f"{tasks}/{task_id}/inputs", "content", {"request_id": "follow-up", "content": "Task follow-up"}),
        (f"/api/threads/{thread_id}/runs/{run_id}/inputs", "text", {"request_id": "follow-up", "mode": "queue", "text": "Run follow-up"}),
    ]
    await asyncio.wait_for(entered.wait(), 10)
    try:
        receipts = [(await client.post(path, json=payload)).raise_for_status().json() for path, _, payload in inputs]
    finally:
        state.release_worker.set()
    finished = await _wait_for_worker(client, task_id, "task", "status", "succeeded")
    workers = state.coordination_workers
    grant = await workers.repo.grant(owner, task_id)
    monkeypatch.setattr("deerflow.persistence.coordination.workers.time", lambda: grant["expires_at"] + 1)
    wake = Mock(side_effect=AssertionError("receipt replay must not wake a Worker"))
    monkeypatch.setattr(workers, "watch", wake)

    for (path, text_field, payload), receipt in zip(inputs, receipts, strict=True):
        assert (await client.post(path, json=payload)).raise_for_status().json() == receipt
        assert (await client.post(path, json={**payload, text_field: "changed"})).status_code == 409
        assert (await client.post(path, json={**payload, "request_id": "new"})).status_code == 403
    wake.assert_not_called()
    assert (await client.get(f"{tasks}/{task_id}")).raise_for_status().json() == finished


@pytest.mark.asyncio
async def test_managed_worker_replays_legacy_task_input_without_grant(worker_gateway):
    from hashlib import sha256

    client, _, state, _, owner = worker_gateway
    repo = state.coordination_workers.repo
    task = await repo.create(owner, request_id="old-task", objective="Review")
    payload = {"request_id": "old-input", "content": "Check the report"}
    receipt = await repo.append_input(owner, task["id"], request_id="input:" + sha256(b"old-input").hexdigest(), content=payload["content"])
    url = f"/api/coordination/tasks/{task['id']}/inputs"
    assert (await client.post(url, json=payload)).raise_for_status().json() == receipt
    assert (await client.post(url, json={**payload, "request_id": "new"})).status_code == 403


@pytest.mark.asyncio
async def test_managed_worker_requires_explicit_resume_and_fences_cancellation(worker_gateway):
    import asyncio

    client, runs, state, entered, _ = worker_gateway
    url = "/api/coordination/tasks"
    settings = {"recursion_limit": 240, "thinking_enabled": False, "is_plan_mode": True}
    paused = (await client.post(url, json={"request_id": "pause", "objective": "approve", "run": settings})).raise_for_status().json()
    task_id = paused["task"]["id"]
    await _wait_for_worker(client, task_id, "execution", "status", "waiting_for_input")
    target = f"/api/threads/{paused['assignment']['thread_id']}/runs"
    reply = {"json": {"command": {"resume": "confirmed"}, "config": {"recursion_limit": 25}, "context": {"is_plan_mode": False}}, "headers": {"Idempotency-Key": "reply"}}
    answered = (await client.post(target, **reply)).raise_for_status().json()
    result = await _wait_for_worker(client, task_id, "task", "status", "succeeded")
    assert result["task"]["result_ref"].endswith(f"/{answered['run_id']}/messages")
    assert (await client.post(target, **reply)).raise_for_status().json()["run_id"] == answered["run_id"]
    assert state.observed_worker_settings == [(240, False, True)] * 2

    other = (await client.post(url, json={"request_id": "cancel", "objective": "wait"})).raise_for_status().json()
    await asyncio.wait_for(entered.wait(), 10)
    task_id, thread = other["task"]["id"], other["assignment"]["thread_id"]
    cancelled = (await client.post(f"{url}/{task_id}/cancel", json={"expected_revision": other["task"]["revision"]})).raise_for_status().json()
    assert cancelled["status"] == "cancelled"
    assert (await runs.get(thread_id=thread, run_id=other["execution"]["run_id"])).status == "interrupted"
    assert (await client.post(f"/api/threads/{thread}/runs", json={"input": {"messages": [{"role": "user", "content": "too late"}]}})).status_code == 409


@pytest.mark.asyncio
async def test_managed_worker_cancel_returns_cancelling_and_finishes_in_background(worker_gateway, monkeypatch):
    import asyncio

    from app.gateway import coordination_workers

    client, runs, _, entered, _ = worker_gateway
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    request_stop = type(runs).cancel

    async def paused_stop(self, *, thread_id, run_id):
        calls.append(run_id)
        started.set()
        await release.wait()
        if len(calls) == 1:
            raise AgentRunError(503, "Run is temporarily unavailable")
        await request_stop(self, thread_id=thread_id, run_id=run_id)

    monkeypatch.setattr(type(runs), "cancel", paused_stop)
    monkeypatch.setattr(coordination_workers, "CANCEL_RESPONSE_TIMEOUT", 0.05, raising=False)
    url = "/api/coordination/tasks"
    first = (await client.post(url, json={"objective": "wait", "request_id": "background-cancel"})).raise_for_status().json()
    task_id, run_id = first["task"]["id"], first["execution"]["run_id"]
    await asyncio.wait_for(entered.wait(), 10)
    cancel_url, body = f"{url}/{task_id}/cancel", {"expected_revision": first["task"]["revision"]}
    pending = asyncio.create_task(client.post(cancel_url, json=body))
    try:
        await asyncio.wait_for(started.wait(), 5)
        done, _ = await asyncio.wait({pending}, timeout=3)
        assert pending in done, "Cancellation response waited for the blocked run"
        response = pending.result()
        assert response.status_code == 202 and response.json()["status"] == "cancelling"
        assert (await client.post(cancel_url, json=body)).json()["status"] == "cancelling"
        assert calls == [run_id]
        assert (await client.post(f"{url}/{task_id}/inputs", json={"request_id": "late", "content": "too late"})).status_code == 409
    finally:
        release.set()
        await pending
    final = await _wait_for_worker(client, task_id, "task", "status", "cancelled")
    assert calls == [run_id, run_id]
    assert final["execution"]["status"] == "cancelled"
    assert (await runs.get(thread_id=first["assignment"]["thread_id"], run_id=run_id)).status == "interrupted"


async def _restart_coordination(state):
    from app.gateway.coordination_workers import CoordinationWorkers
    from deerflow.runtime import RunManager

    previous = state.coordination_workers
    await previous.close()
    await state.run_manager.shutdown()
    state.agent_runs_host.close()
    host = GatewayAgentRunsHost(state.agent_runs_host.app, load_user=state.agent_runs_host.load_user)
    state.agent_runs_host = host
    state.run_manager = RunManager(store=state.run_store)
    state.coordination_workers = CoordinationWorkers(previous.repo, host, previous._connections)
    await state.coordination_workers.recover_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("previous_outcome", ["completed", "shutdown", "cancel-takeover", "orphan-no-checkpoint"])
async def test_managed_worker_restart_reconciles_the_persisted_task(worker_gateway, tmp_path, previous_outcome):
    import asyncio

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from deerflow.config.app_config import get_app_config
    from deerflow.runtime import ORPHAN_RECOVERY_STOP_REASON
    from deerflow.runtime.runs.manager import STARTUP_ORPHAN_RECOVERY_ERROR

    client, runs, state, entered, _ = worker_gateway
    limit = get_app_config().max_recursion_limit
    settings = {"recursion_limit": limit + 100, "thinking_enabled": False, "is_plan_mode": True}
    path = str(tmp_path / "checkpoints.sqlite")
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        if previous_outcome != "orphan-no-checkpoint":
            state.checkpointer = saver
        first = (await client.post("/api/coordination/tasks", json={"objective": "wait", "request_id": "restart", "run": settings})).raise_for_status().json()
        task_id, run_id, thread = first["task"]["id"], first["execution"]["run_id"], first["assignment"]["thread_id"]
        await asyncio.wait_for(entered.wait(), 10)
        await state.coordination_workers.close()
        if previous_outcome == "completed":
            state.release_worker.set()
            assert (await runs.wait_coordination_worker(thread_id=thread, run_id=run_id)).status == "success"
        await state.run_manager.shutdown()
        if previous_outcome == "cancel-takeover":
            await state.run_store.update_status(run_id, "error", error="Run reclaimed by worker during cancellation", stop_reason=ORPHAN_RECOVERY_STOP_REASON)
        elif previous_outcome == "orphan-no-checkpoint":
            await state.run_store.update_status(run_id, "error", error=STARTUP_ORPHAN_RECOVERY_ERROR, stop_reason=ORPHAN_RECOVERY_STOP_REASON)
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        state.checkpointer = saver
        await _restart_coordination(state)
        state.release_worker.set()
        finished = await _wait_for_worker(client, task_id, "task", "status", "failed" if previous_outcome in ("cancel-takeover", "orphan-no-checkpoint") else "succeeded")
    assert finished["assignment"]["thread_id"] == thread
    assert finished["execution"]["turn"] == (2 if previous_outcome == "shutdown" else 1)
    assert state.observed_worker_settings == [(limit, False, True)] * finished["execution"]["turn"]
    assert finished["task"]["run_settings"] == settings
    assert (finished["execution"]["run_id"] != run_id) is (previous_outcome == "shutdown")
    if previous_outcome == "orphan-no-checkpoint":
        assert finished["execution"]["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["runs:create", "threads:write", "revoked"])
async def test_managed_worker_admission_waits_for_restored_authorization(worker_gateway, monkeypatch, denial):
    client, runs, state, _, owner = worker_gateway
    service = state.coordination_workers
    task = await service.repo.create(owner, request_id="pending-admission", objective="continue")
    task_id = task["id"]
    grant = service._new_grant(runs.capture_authority())
    turn = await service.repo.prepare(owner, task_id, "lead_agent", initial_grant=grant)
    authorized, grant_id = await service.authority(owner, task_id)
    permissions = grant["authority"]["permissions"]
    policy = AsyncMock(return_value=[permission for permission in permissions if permission != denial])
    monkeypatch.setattr("app.gateway.extension_agent_runs.resolve_route_permissions", policy)
    if denial == "revoked":
        await service.repo.set_grant(owner, task_id, None)

    driver = service.watch(authorized, owner, task_id, grant_id)
    with pytest.raises(AgentRunError) as exc:
        await driver
    assert exc.value.status_code == 403
    url = f"/api/coordination/tasks/{task_id}"
    view = (await client.get(url)).raise_for_status().json()
    assert view["execution"]["id"] == turn[1]["id"]
    assert view["execution"]["run_id"] is None
    assert view["task"]["status"] == "running"
    assert view["execution"]["status"] == "admitting"
    assert view["authorization_required"] is True
    retry = await client.post("/api/coordination/tasks", json={"request_id": "pending-admission", "objective": "continue"})
    assert retry.status_code == 403
    await service.recover_once()
    assert (owner, task_id) not in service._drivers

    policy.return_value = permissions
    if denial == "revoked":
        assert (await client.put(f"{url}/authorization")).raise_for_status().json()["authorization_required"] is False
    else:
        assert (await service.repo.grant(owner, task_id))["id"] == grant_id
    await service.recover_once()
    finished = await _wait_for_worker(client, task_id, "task", "status", "succeeded")
    assert finished["authorization_required"] is False
    assert finished["execution"]["id"] == turn[1]["id"]


@pytest.mark.asyncio
async def test_managed_worker_restart_finishes_a_previously_fenced_cancellation(worker_gateway):
    import asyncio

    client, _, state, entered, owner = worker_gateway
    first = (await client.post("/api/coordination/tasks", json={"objective": "wait", "request_id": "restart-cancel"})).raise_for_status().json()
    task_id = first["task"]["id"]
    await asyncio.wait_for(entered.wait(), 10)
    await state.coordination_workers.repo.request_cancel(owner, task_id, expected_revision=first["task"]["revision"])
    await _restart_coordination(state)
    finished = await _wait_for_worker(client, task_id, "task", "status", "cancelled")
    assert finished["execution"]["run_id"] == first["execution"]["run_id"]
    assert finished["execution"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_bound_channel_grant_is_invalid_after_reconnect_and_owner_can_reauthorize(worker_gateway):
    import asyncio

    from app.channels.message_bus import InboundMessage

    client, _, state, entered, owner = worker_gateway
    service = state.coordination_workers
    binding = {"owner_user_id": owner, "provider": "telegram", "external_account_id": "sender"}
    connection = await service._connections.upsert_connection(**binding)
    message = InboundMessage(channel_name="telegram", chat_id="chat", user_id="sender", text="wait", connection_id=connection["id"], owner_user_id=owner)
    first = await service.dispatch_bound_channel(message, request_id="event", objective="wait")
    task_id = first["task"]["id"]
    assert (await service.dispatch_bound_channel(message, request_id="event", objective="wait"))["execution"]["run_id"] == first["execution"]["run_id"]
    await asyncio.wait_for(entered.wait(), 10)
    await service._connections.disconnect_connection(connection_id=connection["id"], owner_user_id=owner)
    with pytest.raises(AgentRunError, match="no longer bound"):
        await service.dispatch_bound_channel(message, request_id="another-event", objective="wait")
    await service._connections.upsert_connection(**binding)
    url = f"/api/coordination/tasks/{task_id}"
    assert (await client.get(url)).json()["authorization_required"] is True
    assert (await client.post(f"{url}/inputs", json={"request_id": "new", "content": "retry"})).status_code == 403
    assert (await client.put(f"{url}/authorization")).raise_for_status().json()["authorization_required"] is False
    assert (await client.delete(f"{url}/authorization")).status_code == 204
    assert (await client.get(url)).json()["authorization_required"] is True
