"""Native ToolNode -> durable MCP -> real MCP HTTP -> B ledger, on native SQL."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401
from test_workspace_mcp import _in_workspace_case


def _exercise_native_tool_to_b(native_engine, executor_engine, tmp_path, monkeypatch, *, after_queue=None, execution_image=None, execution_argv=None):  # noqa: F811
    import httpx
    from ecs_executor.job_store import JobStore
    from ecs_executor.jobs import ExecutionJobs, ExecutionProfile
    from ecs_executor.mcp_server import create_server
    from ecs_executor.schema import upgrade_schema
    from ecs_executor.scope import mint_execution_scope, mint_management_scope, verify_management_scope
    from langchain_core.messages import AIMessage
    from langchain_core.tools import tool
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    from app.mcp_tasks.service import McpTaskService
    from deerflow.authz.workspace import WorkspaceContext, get_current_workspace, set_current_workspace
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp import client as mcp_client
    from deerflow.mcp.task_tool_caller import McpTaskToolCaller
    from deerflow.mcp.tasks import McpTaskDriverRegistry
    from deerflow.mcp.tasks.ordinary import OrdinaryMcpTaskDriver
    from deerflow.mcp.tasks.runtime import set_mcp_task_submitter
    from deerflow.mcp.tools import _make_background_submit_tool
    from deerflow.persistence.mcp_tasks.model import McpTaskRow
    from deerflow.persistence.mcp_tasks.sql import McpTaskRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.workspaces.model import WorkspaceMembershipRow
    from deerflow.runtime import RunStatus
    from deerflow.runtime.context_keys import RUN_OWNER_WORKER_CONTEXT_KEY
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    upgrade_schema(executor_engine)
    store = JobStore(executor_engine.url.render_as_string(hide_password=False))
    secret = b"synthetic-scoped-B-secret-at-least-32-bytes"
    jobs = ExecutionJobs(
        store,
        secret=secret,
        audience="B",
        profiles={"small": ExecutionProfile(image=execution_image or "fixture-only-no-launch")},
        user_profiles={"owner": {"small"}},
        artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "shared",
        metadata_database_url=native_engine.url.render_as_string(hide_password=False),
        workspace_required=True,
        native_server_name="ecs",
    )
    for key, value in {"SERVER": "ecs", "SUBMIT_TOOL": "submit", "STATUS_TOOL": "status", "CANCEL_TOOL": "cancel", "AUDIENCE": "B", "SECRET": secret.decode()}.items():
        monkeypatch.setenv("ECS_EXECUTOR_SCOPE_" + key, value)
    config = ExtensionsConfig.model_validate(
        {
            "mcpInterceptors": ["ecs_executor.interceptor:build_execution_scope_interceptor"],
            "mcpServers": {
                "ecs": {
                    "type": "http",
                    "url": "http://127.0.0.1:8003/mcp",
                    "headers": {"Authorization": "Bearer discovery-only"},
                    "user_auth": {"enabled": True, "on_missing": "deny", "users": {"owner": "Bearer owner-credential"}},
                    "task_toolsets": [{"name": "execution", "submit_tool": "submit", "status_tool": "status", "cancel_tool": "cancel"}],
                }
            },
        }
    )
    monkeypatch.setattr("ecs_executor.interceptor.get_extensions_config", lambda: config)
    server = create_server(jobs, user_credentials={"owner": "owner-credential"}, discovery_credential="discovery-only")
    app = server.streamable_http_app()
    original_params = mcp_client.build_server_params

    def params(name, server_config):
        result = original_params(name, server_config)
        # Replace network plumbing only. Real MCP serialization, interceptor,
        # per-user credential, receiver, durable repositories and SQL all run.
        result["httpx_client_factory"] = lambda headers=None, timeout=None, auth=None: httpx.AsyncClient(transport=httpx.ASGITransport(app=app), headers=headers, timeout=timeout or 30, auth=auth)
        return result

    monkeypatch.setattr(mcp_client, "build_server_params", params)
    monkeypatch.setattr("deerflow.mcp.task_tool_caller.build_server_params", params)

    async def scenario(case):
        parent = await ThreadMetaRepository(case.sf).create("wire-main", user_id="owner")
        run = await case.runs.create_or_reject(parent["thread_id"], user_id="owner")
        await case.runs.try_start(run.run_id)
        registry = McpTaskDriverRegistry()
        caller = McpTaskToolCaller(config)
        driver = OrdinaryMcpTaskDriver(caller)
        registry.register("ordinary-tools", driver)
        tasks = McpTaskService(repository=McpTaskRepository(case.sf, workspace_required=True), drivers=registry, poll_interval_seconds=1, lease_seconds=120, max_concurrent_polls=1)
        from deerflow.mcp.tasks import runtime as task_runtime

        previous = task_runtime._submitter
        set_mcp_task_submitter(tasks)

        @tool
        async def submit(request_key: str, profile: str, argv: list[str], input_refs: dict[str, dict[str, str]] | None = None) -> str:
            """Execute through the durable native task wrapper."""
            raise AssertionError("The Agent must use the native durable wrapper")

        wrapped = _make_background_submit_tool(submit, server_name="ecs", task_name="execution", submit_tool="submit", status_tool="status", cancel_tool="cancel", connection_scope="deployment")
        builder = StateGraph(MessagesState, context_schema=dict)
        builder.add_node("tools", ToolNode([wrapped], handle_tool_errors=False))
        builder.add_edge(START, "tools")
        builder.add_edge("tools", END)
        graph = builder.compile()
        owner_token = set_current_user(SimpleNamespace(id="owner"))
        try:
            async with server.session_manager.run():
                import base64
                import hashlib

                source = jobs.publication.paths.sandbox_uploads_dir(run.thread_id, user_id="owner") / "program.txt"
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(b"original input")
                references = {"program.txt": {"path": "uploads/program.txt", "sha256": hashlib.sha256(b"original input").hexdigest()}}
                arguments = {"request_key": "report", "profile": "small", "argv": execution_argv or ["echo", "report"], "input_refs": references}
                state = {"messages": [AIMessage(content="", tool_calls=[{"name": "submit", "args": arguments, "id": "submit-1", "type": "tool_call"}])]}
                await graph.ainvoke(
                    state, context={"user_id": "owner", "thread_id": run.thread_id, "thread_incarnation": run.thread_incarnation, "run_id": run.run_id, "workspace_context": case.original, RUN_OWNER_WORKER_CONTEXT_KEY: run.owner_worker_id}
                )
                async with case.sf() as session:
                    row = await session.scalar(sa.select(McpTaskRow).where(McpTaskRow.run_id == run.run_id))
                    assert row is not None, "native MCP did not durably commit submission"
                    remote_id, local_id = row.remote_task_id, row.id
                    assert row.workspace_context_json == asdict(case.original)
                    saved_scope = WorkspaceContext(**row.workspace_context_json)
                staged = store.get(remote_id)
                assert staged["state"] == "staged" and staged["workspace_context"] == asdict(case.original)
                assert staged["run_id"] == run.run_id and staged["incarnation"] == parent["incarnation"]
                assert base64.b64decode(staged["spec"]["input_files"]["program.txt"]) == b"original input"
                orphan_args = arguments | {"request_key": "uncommitted"}
                submission_token = mint_execution_scope(
                    secret=secret, audience="B", user_id="owner", thread_id=run.thread_id, incarnation=run.thread_incarnation, run_id=run.run_id, operation="submit", arguments=orphan_args, workspace_context=saved_scope
                )
                orphan = jobs.submit("owner", submission_token, orphan_args)["task_id"]
                orphan_token = mint_management_scope(secret=secret, audience="B", user_id="owner", task_id=orphan, operation="status", workspace_context=saved_scope)
                with pytest.raises(PermissionError):
                    jobs.status("owner", orphan_token, {"task_id": orphan})
                assert store.get(orphan)["state"] == "staged", "no native receipt must mean no activation"
                source.write_bytes(b"later source content")
                await case.runs.set_status_if_not_cancelled(run.run_id, RunStatus.success)
                set_current_workspace(case.other)
                await tasks.run_once(now=datetime.now(UTC) + timedelta(seconds=30))
                queued = store.get(remote_id)
                assert queued["state"] == "queued", "background v2 status did not confirm native MCP commitment"
                assert get_current_workspace() == case.other
                async with case.sf() as session:
                    row = await session.get(McpTaskRow, local_id)
                    assert row.status == "working" and row.workspace_context_json == asdict(case.original)
                    assert row.run_id == run.run_id and row.remote_task_id == remote_id
                if after_queue is not None:
                    await after_queue(SimpleNamespace(case=case, jobs=jobs, store=store, tasks=tasks, remote_id=remote_id, local_id=local_id, run=run, original=case.original, other=case.other))
                    return
                assert store.claim_queued() is None, "physical launch needs its own integration"
                assert base64.b64decode(queued["spec"]["input_files"]["program.txt"]) == b"original input"
                management = mint_management_scope(secret=secret, audience="B", user_id="owner", task_id=remote_id, operation="status", workspace_context=saved_scope)
                with pytest.raises(ValueError, match="workspace"):
                    verify_management_scope(management, secret=secret, authenticated_user_id="owner", arguments={"task_id": remote_id}, expected_audience="B", expected_operation="status")
                legacy = mint_management_scope(secret=secret, audience="B", user_id="owner", task_id=remote_id, operation="status")
                with pytest.raises(ValueError, match="workspace"):
                    jobs.status("owner", legacy, {"task_id": remote_id})
                wrong_space = await caller.call_tool(server_name="ecs", tool_name="status", arguments={"task_id": remote_id}, user_id="owner", thread_id=run.thread_id, thread_incarnation=run.thread_incarnation)
                assert wrong_space.isError, "caller selection retargeted background identity"
                set_current_workspace(saved_scope)
                mutations = [
                    (McpTaskRow, "workspace_context_json", None, asdict(saved_scope)),
                    (McpTaskRow, "run_id", "foreign-run", run.run_id),
                    (McpTaskRow, "remote_task_id", "unrelated", remote_id),
                    (McpTaskRow, "server_name", "different-server", "ecs"),
                    (McpTaskRow, "thread_incarnation", "replaced", run.thread_incarnation),
                    (McpTaskRow, "cancel_requested_at", datetime.now(UTC), None),
                    (McpTaskRow, "status", "cancelled", "working"),
                    (WorkspaceMembershipRow, "status", "removed", "active"),
                ]
                for model, field, changed, original in mutations:
                    predicate = model.id == local_id if model is McpTaskRow else sa.and_(model.workspace_id == saved_scope.workspace_id, model.user_id == "owner")
                    with native_engine.begin() as connection:
                        connection.execute(sa.update(model).where(predicate).values({field: changed}))
                    try:
                        denied = await caller.call_tool(server_name="ecs", tool_name="status", arguments={"task_id": remote_id}, user_id="owner", thread_id=run.thread_id, thread_incarnation=run.thread_incarnation)
                        assert denied.isError, (model.__tablename__, field)
                        assert store.get(remote_id)["state"] == "queued"
                        if model is WorkspaceMembershipRow:
                            with pytest.raises(ValueError, match="access denied"):
                                jobs.publication.snapshot(staged, references, limit=1024)
                    finally:
                        with native_engine.begin() as connection:
                            connection.execute(sa.update(model).where(predicate).values({field: original}))
                cancelled = await caller.call_tool(server_name="ecs", tool_name="cancel", arguments={"task_id": remote_id}, user_id="owner", thread_id=run.thread_id, thread_incarnation=run.thread_incarnation)
                assert not cancelled.isError and cancelled.structuredContent["status"] == "cancelled"
                set_current_workspace(case.other)
                await tasks.run_once(now=datetime.now(UTC) + timedelta(seconds=60))
                assert get_current_workspace() == case.other
                async with case.sf() as session:
                    row = await session.get(McpTaskRow, local_id)
                    assert row.status == "cancelled" and row.workspace_context_json == asdict(saved_scope)
                # This is a receiver-mode downgrade fence, not a tenant startup bypass.
                with pytest.raises(ValueError, match="workspace"):
                    ExecutionJobs(
                        store,
                        secret=secret,
                        audience="B",
                        profiles=jobs.profiles,
                        user_profiles=jobs.user_profiles,
                        artifact_root=tmp_path / "legacy",
                        workspace_root=tmp_path / "shared",
                        metadata_database_url=native_engine.url.render_as_string(hide_password=False),
                    )
                store.expire_staged(now=10**12)
                assert store.get(orphan)["state"] == "failed"
                with executor_engine.connect() as connection:
                    historical = connection.execute(sa.text("SELECT state,version,execution_identity FROM ecs_execution_jobs WHERE id='unknown'")).one()
                    assert historical.state == "uncertain" and historical.version == 7 and historical.execution_identity is None

        finally:
            reset_current_user(owner_token)
            set_mcp_task_submitter(previous)

    try:
        _in_workspace_case(native_engine, scenario)
    finally:
        store.engine.dispose()
        jobs.publication.engine.dispose()


def test_native_tool_to_scoped_b_commit_and_background_status(native_engine, executor_engine, tmp_path, monkeypatch):  # noqa: F811
    _exercise_native_tool_to_b(native_engine, executor_engine, tmp_path, monkeypatch)
