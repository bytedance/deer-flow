"""Trusted admission hook between durable native admission and task attachment.

Only operator startup code may install app.state.native_run_admission_host.
HTTP request fields cannot select the host. A host stages its durable work and
hands off the pending RunManager record before returning True. False keeps the
normal local native worker path. The dispatcher owns queued lease renewal and
recovery; this hook does not create a second graph or execution runtime.
"""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import asdict, replace

from deerflow.runtime.runs.manager import RunManager, RunRecord, RunStartupError


async def attach_native_admission(request, manager: RunManager, record: RunRecord, worker_factory: Callable[[RunRecord], Awaitable[None]], *, snapshot_factory=None) -> None:
    host = getattr(request.app.state, "native_run_admission_host", None)
    try:
        if host is not None and (await host.admit_native(record, snapshot_factory) if snapshot_factory is not None and hasattr(host, "admit_native") else await host.admit(record)):
            if not record.ownership_lost or record.task is not None:
                raise RunStartupError("Native admission host did not hand off the pending run")
            return
        if host is not None and getattr(host, "quiescing", False):
            raise RunStartupError("Native admission host is quiescing")
    except BaseException as exc:
        # A handed-off run belongs to the dispatcher. Never finalize it from
        # the former owner, even if the host lost its acknowledgement.
        if not record.ownership_lost:
            await manager.fail_start_if_pending(record.run_id, error=f"Native admission host failed: {type(exc).__name__}")
        raise
    if record.ownership_lost:
        raise RunStartupError("Native admission host declined after handing off ownership")
    worker = worker_factory(record)
    try:
        record.task = asyncio.create_task(worker)
    except Exception as exc:
        worker.close()
        await manager.fail_start_if_pending(record.run_id, error=f"Failed to attach run worker: {exc}")
        raise


@contextmanager
def native_admission_workspace(record):
    """Bind a private admitted Run snapshot, never the current UI selection.

    This shape check grants no new authority: scoped repository reads and the
    pending-owner CAS still reauthorize membership and the original generation.
    """
    from deerflow.authz.workspace import reset_current_workspace, set_current_workspace

    RunManager._workspace_transition_kwargs(record)
    token = set_current_workspace(record.workspace_context) if record.workspace_context is not None else None
    try:
        yield record.workspace_context
    finally:
        if token is not None:
            reset_current_workspace(token)


async def make_native_snapshot(request, record, *, run_ctx, body, config, graph_input, admitted_knowledge_scope, scope_assistant_id, scheduled_task_runtime, require_existing_thread, transport_node=None, transport_secret=None):
    """Capture admission output, never live request secrets or closure objects."""
    with native_admission_workspace(record):
        from langchain_core.messages import messages_to_dict
        from langgraph.types import Command

        from app.gateway.services import _ensure_thread_metadata
        from deerflow.runtime.goal import read_thread_goal
        from deerflow.runtime.secret_context import redact_config_secrets

        metadata = await _ensure_thread_metadata(run_ctx, record, owner_user_id=record.user_id, require_existing_thread=require_existing_thread)
        if metadata is None or not metadata.get("incarnation"):
            raise RunStartupError("Remote native execution requires thread incarnation")
        if isinstance(graph_input, Command):
            encoded_input = {"command": {"resume": graph_input.resume}}
        else:
            encoded_input = {"input": {**graph_input, "messages": messages_to_dict(graph_input.get("messages", []))}} if graph_input is not None else {"input": None}
        from app.gateway.conversation_access import _source_id

        body_snapshot = body.model_dump(mode="json", exclude={"input", "config", "metadata", "context"})
        body_snapshot["conversation_references"] = [_source_id(value, str(request.url)) for value in body.conversation_references or []]
        conversation_sources = body_snapshot["conversation_references"] if run_ctx.conversation_reader is not None else []
        if not conversation_sources and run_ctx.conversation_reader is not None and scheduled_task_runtime is not None:
            previous = record.metadata.get("scheduled_previous_thread_id")
            if isinstance(previous, str):
                conversation_sources = [previous]
        snapshot = {
            "run_id": record.run_id,
            "user_id": record.user_id,
            "thread_id": record.thread_id,
            "incarnation": metadata["incarnation"],
            "assistant_id": record.assistant_id,
            "kwargs": record.kwargs,
            "metadata": record.metadata,
            "goal": await read_thread_goal(run_ctx.checkpointer, record.thread_id),
            "execution": {
                **encoded_input,
                "config": redact_config_secrets(config),
                "body": body_snapshot,
                "conversation_sources": conversation_sources,
                "knowledge_scope": admitted_knowledge_scope,
                "scope_assistant_id": scope_assistant_id,
                "scheduled_task_runtime": scheduled_task_runtime,
                "dependency_continuation": run_ctx.dependency_continuation,
                "require_existing_thread": require_existing_thread,
            },
        }

        if record.workspace_context is not None:
            context = record.workspace_context
            if run_ctx.workspace_context != context or metadata.get("workspace_id") != context.workspace_id or metadata.get("user_id") != record.user_id or metadata["incarnation"] != record.thread_incarnation:
                raise RunStartupError("Remote native snapshot differs from its captured admission")
            from deerflow.persistence.workspaces.run_control import NativeRunStopTarget

            snapshot.update(workspace_id=context.workspace_id, workspace_context=asdict(context), created_at=NativeRunStopTarget.from_record(record).created_at)

        if transport_secret is not None:
            from ecs_executor.agent_dispatch import seal_native_secrets

            snapshot["secret_carrier"] = seal_native_secrets(snapshot, transport_node, transport_secret, config.get("context"))
        return snapshot


async def verify_native_launch_for_receiver(app, job, token, secret):
    """Resolve pending launch authority from native SQL, never transport scope.

    The signed values are locators/expectations only. Native control storage
    independently resolves the immutable target and live authorization facts.
    The later pending-owner CAS rechecks those facts under native locks.
    """
    from ecs_executor.agent_dispatch import verify_native_launch

    native = job["native"]
    store = getattr(app.state, "run_store", None)
    scoped = getattr(store, "workspace_scope_required", False) or any(value.get(key) is not None for value in (job, native) for key in ("workspace_id", "workspace_context"))
    if not scoped:
        return verify_native_launch(job, token, secret), None
    inspect = getattr(store, "inspect_dispatch_control", None)
    if inspect is None:
        raise ValueError("Native launch capability requires native control storage")
    identity = {key: native.get(key) for key in ("run_id", "user_id", "workspace_id", "thread_id", "incarnation", "workspace_context", "created_at")}
    control = await inspect(identity=identity, owner_worker_id="dispatch:" + job["id"])
    if control is None or control["status"] != "pending" or control["cancel_action"] is not None or not control["live"] or not control["lease_active"] or control["stop_recorded"] or control["lifetime_completed"]:
        raise ValueError("Native launch capability no longer has pending authority")
    context = control["target"].workspace_context
    return verify_native_launch(job, token, secret, expected_workspace_context=context), context


async def adopt_native_run(app, job, token, secret, *, admission_check=None):
    """Bind independently resolved scope through reads, owner CAS and task capture."""
    from deerflow.authz.workspace import get_current_workspace, reset_current_workspace, set_current_workspace

    native, context = await verify_native_launch_for_receiver(app, job, token, secret)
    if context is None:
        if get_current_workspace() is not None:
            raise ValueError("Native launch capability cannot inherit an ambient workspace")
        return await _adopt_native_run(app, job, native, secret, None, admission_check=admission_check)
    scope_token = set_current_workspace(context)
    try:
        return await _adopt_native_run(app, job, native, secret, context, admission_check=admission_check)
    finally:
        reset_current_workspace(scope_token)


async def _adopt_native_run(app, job, native, secret, workspace_context, *, admission_check=None):
    """Trusted worker entry: signed authority + canonical durable row + owner CAS."""
    from types import SimpleNamespace

    from langchain_core.messages import messages_from_dict
    from langgraph.types import Command

    from app.gateway import services
    from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL
    from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, get_internal_user
    from deerflow.runtime.goal import read_thread_goal
    from deerflow.utils.assembly_io import run_assembly

    manager = app.state.run_manager
    original = await manager.get(native["run_id"], user_id=native["user_id"])
    if original is None or any(getattr(original, key) != native[key] for key in ("thread_id", "user_id", "assistant_id", "kwargs", "metadata")):
        raise ValueError("Native admission snapshot mismatch")
    request = SimpleNamespace(app=app, headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: native["user_id"]}, state=SimpleNamespace(user=get_internal_user(), auth_source=AUTH_SOURCE_INTERNAL), cookies={})
    ctx = replace(services.get_run_context(request), workspace_context=workspace_context)
    thread = await ctx.thread_store.get(native["thread_id"], user_id=native["user_id"])
    if thread is None or thread.get("incarnation") != native["incarnation"] or not await ctx.thread_store.check_access(native["thread_id"], native["user_id"], require_existing=True):
        raise ValueError("Native admission thread incarnation mismatch")
    if await read_thread_goal(ctx.checkpointer, native["thread_id"]) != native["goal"]:
        raise ValueError("Native admission goal mismatch")
    from copy import deepcopy

    from ecs_executor.agent_dispatch import open_native_secrets

    execution = deepcopy(native["execution"])
    if execution.get("dependency_continuation") is not None:
        ctx = replace(ctx, dependency_continuation=execution["dependency_continuation"])
    request_secrets = open_native_secrets(native, job["node_id"], secret, native.get("secret_carrier"))
    if request_secrets:
        execution["config"].setdefault("context", {})["secrets"] = request_secrets
    body = services.RunCreateRequest.model_validate({**execution["body"], "assistant_id": native["assistant_id"], "input": None, "context": execution["config"].get("context", {})})
    graph_input = Command(resume=execution["command"]["resume"]) if "command" in execution else execution["input"]
    if isinstance(graph_input, dict):
        graph_input = {**graph_input, "messages": messages_from_dict(graph_input.get("messages", []))}
    owner = await services.resolve_trusted_internal_owner_for_attribution(request, native["user_id"])
    if owner is None and native["user_id"] == services.AUTH_DISABLED_USER_ID and services.is_auth_disabled():
        owner = services.get_auth_disabled_user()
    if execution.get("conversation_sources"):
        from app.gateway.conversation_access import _prepare_owner_bound_conversation_reader

        if owner is None or "runs:read" not in await services.resolve_route_permissions(owner, is_internal=False):
            raise ValueError("Native admission conversation permission revoked")
        prepared = _prepare_owner_bound_conversation_reader(tuple(execution["conversation_sources"]), user_id=native["user_id"], run_context=ctx, run_manager=manager, app_config=ctx.app_config)

        async def conversation_reader(*args, **kwargs):
            current_owner = await services.get_local_provider().get_user(native["user_id"])
            if current_owner is None or "runs:read" not in await services.resolve_route_permissions(current_owner, is_internal=False):
                return '{"status":"unavailable","messages":[],"next_cursor":null,"has_more":false}'
            return await prepared[0](*args, **kwargs)

        ctx = replace(ctx, conversation_reader=conversation_reader)
    if execution["scheduled_task_runtime"] is not None:
        ctx = replace(ctx, scheduled_task_runtime=execution["scheduled_task_runtime"])
    factory = await run_assembly(services.resolve_agent_factory, native["assistant_id"])
    if admission_check is not None:
        admission_check()
    record = await manager.adopt_pending(native["run_id"], thread_id=native["thread_id"], user_id=native["user_id"], expected_owner_worker_id="dispatch:" + job["id"], workspace_context=workspace_context)

    async def execute():
        from deerflow.runtime.user_context import reset_current_user, set_current_user

        owner_token = set_current_user(owner or get_internal_user(native["user_id"]))
        try:
            await services.execute_admitted_native_run(
                request,
                record,
                run_ctx=ctx,
                body=body,
                config=execution["config"],
                graph_input=graph_input,
                owner_user_id=native["user_id"],
                require_existing_thread=True,
                agent_factory=factory,
                stream_modes=services.normalize_stream_modes(body.stream_mode),
                admitted_knowledge_scope=execution["knowledge_scope"],
                current_human_message=services._current_human_message(graph_input),
                internal_owner_user=owner,
                user=request.state.user,
                scope_assistant_id=execution["scope_assistant_id"],
                scheduled_task_runtime=execution["scheduled_task_runtime"],
            )
        finally:
            reset_current_user(owner_token)

    if admission_check is not None:
        admission_check()
    record.task = asyncio.create_task(execute())
    return record


async def prepare_native_host(app, startup_config):
    """Operator-only opt-in. Enabled misconfiguration aborts Gateway startup."""
    import json
    import os
    from pathlib import Path

    path = os.environ.get("ECS_NATIVE_CONFIG")
    if not path:
        return None
    snapshot = getattr(app.state, "browser_control_snapshot", None)
    config = snapshot.native_config if snapshot is not None else json.loads(Path(path).read_text(encoding="utf-8"))
    if config.get("enabled") is not True:
        return None
    from ecs_executor.agent_dispatch import NativeDispatchHost, NativeWorkerHost, install_native_dispatch

    if not startup_config.deployment.multi_instance or startup_config.database.backend != "postgres" or not startup_config.run_ownership.heartbeat_enabled or startup_config.run_events.backend != "db":
        raise ValueError("Enabled native dispatch requires native multi-instance PostgreSQL/events/ownership")
    role = config.get("role")
    if role == "central":
        from ecs_executor.job_store import JobStore
        from ecs_executor.nodes import Node
        from ecs_executor.scheduling import Scheduling
        from ecs_executor.scope import _secret

        store = JobStore(os.environ[config["database_url_env"]])
        if store.engine.dialect.name != "postgresql":
            raise ValueError("Native pool requires PostgreSQL")
        from ecs_executor.schema import require_schema

        await asyncio.to_thread(require_schema, store.engine)
        nodes = {key: Node.model_validate(value) for key, value in config["nodes"].items()}
        if config["native_node"] not in nodes or nodes[config["native_node"]].max_concurrency != 1 or "C" not in nodes[config["native_node"]].kinds:
            raise ValueError("Native affinity requires one fixed serial worker")
        native_node = nodes[config["native_node"]]
        if native_node.resident_cpu_millis < 1500 or native_node.resident_memory_mib < 2048:
            raise ValueError("Native warm AIO plus Gateway requires at least 1500m CPU/2048MiB resident budget")
        credentials = {node: os.environ[variable] for node, variable in config["worker_credential_env"].items()}
        if set(credentials) != set(nodes) or len(set(credentials.values())) != len(credentials):
            raise ValueError("Every fixed node needs a distinct credential")
        for credential in credentials.values():
            _secret(credential.encode())
        pool = await asyncio.to_thread(Scheduling, store, nodes=nodes)
        host = NativeDispatchHost(app, pool, config, credentials)
        install_native_dispatch(app, host)
        # Runs owned by a durable queued job are live even if this Gateway
        # restarted. Refresh them before native startup orphan reconciliation.
        await host.maintain()
    elif role == "worker":
        if startup_config.sandbox.use != "deerflow.community.aio_sandbox:AioSandboxProvider" or startup_config.sandbox.replicas != 1 or not startup_config.sandbox.hard_capacity:
            raise ValueError("Native worker requires the bounded native AIO provider with replicas=1")
        if os.environ.get("DEER_FLOW_SANDBOX_CPUS") != "1" or os.environ.get("DEER_FLOW_SANDBOX_MEMORY") != "1g":
            raise ValueError("Native warm resident budget requires Docker limits 1 CPU and 1 GiB")
        host = NativeWorkerHost(app, config)
        try:
            # Every native role must protect durable queued dispatch ownership
            # before native orphan recovery. Central unavailability fails
            # startup closed; supervisors retry after central is ready.
            response = await host.request("bootstrap")
            if response.get("renewed") is not True:
                raise ValueError("Native worker bootstrap renewal unconfirmed")
        except BaseException:
            await host.stop()
            raise
    else:
        raise ValueError("Enabled native dispatch requires central or worker role")
    app.state.native_run_admission_host = host
    from app.gateway.browser_control import get_browser_control

    provider = get_browser_control(app)
    if provider is not None:
        try:
            await provider.bind(app, host)
        except BaseException:
            await host.stop()
            raise
    return host
