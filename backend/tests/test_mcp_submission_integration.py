"""Submission cancellation through a real MCP subprocess and SQL repository."""

import asyncio
import importlib.util
import sys
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.mcp_tasks.service as service_module
from app.mcp_tasks.service import McpTaskService
from deerflow.config.app_config import AppConfig
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.paths import Paths
from deerflow.mcp.client import build_server_params
from deerflow.mcp.session_pool import MCPSessionPool
from deerflow.mcp.task_tool_caller import McpTaskToolCaller
from deerflow.mcp.tasks import ORDINARY_MCP_TASK_DRIVER, McpTaskDriverRegistry, OrdinaryMcpTaskDriver, TaskSubmitRequest
from deerflow.mcp.tasks.runtime import set_mcp_task_submitter
from deerflow.mcp.tools import _configure_task_tools_for_server
from deerflow.persistence.engine import close_engine, get_engine, init_engine_from_config
from deerflow.persistence.mcp_tasks import McpTaskRepository
from deerflow.persistence.mcp_tasks.model import McpTaskRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.runtime.user_context import get_current_user
from deerflow.subagents.config import SubagentConfig

_USER = "test-user-autouse"
_THREAD = "submission-thread"
_INCARNATION = "submission-incarnation"
_REMOTE = "remote-report"
_SUBMISSION_CONTEXT = ContextVar("mcp_submission_integration_context", default=None)
_SERVER = """
import asyncio
import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("submission-barriers")
accepted = asyncio.Event()
release = asyncio.Event()
tasks = {}
cancel_calls = 0
submit_calls = 0


@mcp.tool()
async def submit_report(hold_reply: bool = False) -> dict[str, object]:
    global submit_calls
    submit_calls += 1
    tasks.setdefault("remote-report", "running")
    accepted.set()
    if hold_reply:
        await release.wait()
    return {"task_id": "remote-report", "status": "running", "pid": os.getpid()}


@mcp.tool()
async def status_report(task_id: str) -> dict[str, object]:
    return {"task_id": task_id, "status": tasks[task_id]}


@mcp.tool()
async def cancel_report(task_id: str) -> dict[str, object]:
    global cancel_calls
    cancel_calls += 1
    tasks[task_id] = "cancelled"
    return {"task_id": task_id, "status": "cancelled"}


@mcp.tool()
async def wait_until_accepted() -> dict[str, object]:
    await accepted.wait()
    return {"submit_calls": submit_calls}


@mcp.tool()
async def release_reply() -> dict[str, object]:
    release.set()
    return {"released": True}


@mcp.tool()
async def inspect_task() -> dict[str, object]:
    return {
        "status": tasks.get("remote-report"),
        "cancel_calls": cancel_calls,
        "submit_calls": submit_calls,
    }


@mcp.tool()
async def process_identity() -> dict[str, object]:
    return {"pid": os.getpid()}


mcp.run(transport="stdio")
"""


@dataclass
class _SqlBarrier:
    phase: str | None
    armed: bool = False
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    integrity_error_seen: bool = False


def _session_class(barrier: _SqlBarrier) -> type[AsyncSession]:
    class GatedSession(AsyncSession):
        _duplicate_commit = False

        async def commit(self):
            inserting_task = any(isinstance(row, McpTaskRow) for row in self.new)
            if barrier.armed and inserting_task and barrier.phase == "commit":
                barrier.armed = False
                barrier.entered.set()
                await barrier.release.wait()
            try:
                result = await super().commit()
            except IntegrityError:
                self._duplicate_commit = True
                barrier.integrity_error_seen = True
                raise
            if barrier.armed and inserting_task and barrier.phase == "postcommit":
                barrier.armed = False
                barrier.entered.set()
                await barrier.release.wait()
            return result

        async def rollback(self):
            if barrier.armed and self._duplicate_commit and barrier.phase == "rollback":
                barrier.armed = False
                barrier.entered.set()
                await barrier.release.wait()
            return await super().rollback()

    return GatedSession


@asynccontextmanager
async def _runtime(tmp_path, monkeypatch, *, phase=None):
    barrier = _SqlBarrier(phase)
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path / "sql")))
    factory = async_sessionmaker(get_engine(), class_=_session_class(barrier), expire_on_commit=False)
    repo = McpTaskRepository(factory)
    now = datetime.now(UTC)
    async with factory() as session:
        session.add(ThreadMetaRow(thread_id=_THREAD, incarnation=_INCARNATION, user_id=_USER, metadata_json={}, created_at=now, updated_at=now))
        await session.commit()

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "reports": {
                    "type": "stdio",
                    "command": sys.executable,
                    "args": ["-c", _SERVER],
                    "task_toolsets": [{"name": "reports", "submit_tool": "submit_report", "status_tool": "status_report", "cancel_tool": "cancel_report"}],
                }
            }
        }
    )
    pool = MCPSessionPool()
    monkeypatch.setattr("deerflow.mcp.task_tool_caller.get_session_pool", lambda: pool)
    monkeypatch.setattr("deerflow.mcp.task_tool_caller.get_paths", lambda: Paths(tmp_path / "home"))
    caller = McpTaskToolCaller(config)
    registry = McpTaskDriverRegistry()
    registry.register(ORDINARY_MCP_TASK_DRIVER, OrdinaryMcpTaskDriver(caller))
    service = McpTaskService(repository=repo, drivers=registry, poll_interval_seconds=60, lease_seconds=120, max_concurrent_polls=2)
    server_config = config.mcp_servers["reports"]
    # Discover the schema over MCP too; the production configuration wrapper
    # replaces only submit and keeps status/cancel private to its driver.
    discovered = await load_mcp_tools(None, connection=build_server_params("reports", server_config))
    configured = _configure_task_tools_for_server(discovered, server_name="reports", server_config=server_config, tool_name_prefix=False)
    submit_tool = next(tool for tool in configured if tool.name == "submit_report")
    runtime = SimpleNamespace(context={"thread_id": _THREAD, "thread_incarnation": _INCARNATION, "run_id": "submission-run"}, config={}, tool_call_id="submission-call")

    async def control(name):
        result = await caller.call_tool(server_name="reports", tool_name=name, arguments={}, user_id=_USER, thread_id=_THREAD, thread_incarnation=_INCARNATION)
        assert not result.isError
        return result.structuredContent

    async def submit(*, hold_reply=False):
        return await submit_tool.coroutine(deerflow_runtime=runtime, hold_reply=hold_reply)

    await service.start()
    set_mcp_task_submitter(service)
    try:
        yield SimpleNamespace(service=service, repo=repo, barrier=barrier, control=control, submit=submit, submit_tool=submit_tool, caller=caller)
    finally:
        barrier.release.set()
        set_mcp_task_submitter(None)
        try:
            await service.stop()
        finally:
            try:
                await pool.close_all()
            finally:
                await close_engine()


async def _deliver_cancellation(task):
    """Let the cancellation reach its await before releasing the peer barrier."""
    turn = asyncio.Event()
    task.cancel()
    asyncio.get_running_loop().call_soon(turn.set)
    await turn.wait()


async def _rows(runtime):
    return await runtime.repo.list_by_thread(_THREAD, user_id=_USER, thread_incarnation=_INCARNATION)


@pytest.mark.asyncio
async def test_cancelled_submit_retains_late_mcp_handle_and_cancels_owned_row(tmp_path, monkeypatch):
    async with _runtime(tmp_path, monkeypatch) as runtime:
        submission = asyncio.create_task(runtime.submit(hold_reply=True))
        try:
            accepted = await asyncio.wait_for(runtime.control("wait_until_accepted"), timeout=15)
            assert accepted["submit_calls"] == 1
            await _deliver_cancellation(submission)
            await runtime.control("release_reply")
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(submission), timeout=10)
            await runtime.service.stop()

            rows = await _rows(runtime)
            assert len(rows) == 1, "the accepted remote handle must retain a durable owner after caller cancellation"
            assert rows[0]["remote_task_id"] == _REMOTE
            assert rows[0]["cancel_requested_at"] is not None
            # Exercise the ordinary control-lease worker even when its first
            # cancellation attempt was already made by the submission handoff.
            await runtime.service.run_once(now=datetime.now(UTC) + timedelta(seconds=120))
            remote = await runtime.control("inspect_task")
            assert remote == {"status": "cancelled", "cancel_calls": 1, "submit_calls": 1}
            assert (await _rows(runtime))[0]["status"] == "cancelled"
        finally:
            await runtime.control("release_reply")
            if not submission.done():
                submission.cancel()
            await asyncio.wait_for(asyncio.gather(submission, return_exceptions=True), timeout=10)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["commit", "rollback"])
async def test_cancelled_duplicate_submit_preserves_existing_remote_owner(tmp_path, monkeypatch, phase):
    async with _runtime(tmp_path, monkeypatch, phase=phase) as runtime:
        first = await runtime.service.submit(
            driver_name=ORDINARY_MCP_TASK_DRIVER,
            request=TaskSubmitRequest(
                user_id=_USER,
                thread_id=_THREAD,
                thread_incarnation=_INCARNATION,
                run_id="first-run",
                tool_call_id="first-call",
                server_name="reports",
                task_name="reports",
                arguments={"hold_reply": False},
                driver_data={"submit_tool": "submit_report", "status_tool": "status_report", "cancel_tool": "cancel_report", "connection_scope": "deployment"},
            ),
        )
        assert first.keys() == (await _rows(runtime))[0].keys()
        assert not {"_thread_incarnation", "reference"}.intersection(first), "ownership bookkeeping must not change the public receipt"
        runtime.barrier.armed = True
        duplicate = asyncio.create_task(runtime.submit())
        try:
            await asyncio.wait_for(runtime.barrier.entered.wait(), timeout=15)
            await _deliver_cancellation(duplicate)
            runtime.barrier.release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(duplicate), timeout=10)
            await runtime.service.stop()

            remote = await runtime.control("inspect_task")
            assert remote == {"status": "running", "cancel_calls": 0, "submit_calls": 2}, "abandoning a duplicate submit must not cancel the already-owned remote task"
            assert runtime.barrier.integrity_error_seen, "the real SQL unique constraint must decide ownership"
            rows = await _rows(runtime)
            assert [row["id"] for row in rows] == [first["id"]]
            assert rows[0]["cancel_requested_at"] is None
        finally:
            runtime.barrier.release.set()
            if not duplicate.done():
                duplicate.cancel()
            await asyncio.wait_for(asyncio.gather(duplicate, return_exceptions=True), timeout=10)


@pytest.mark.asyncio
async def test_cancelled_submit_after_sql_commit_records_durable_cancellation(tmp_path, monkeypatch):
    async with _runtime(tmp_path, monkeypatch, phase="postcommit") as runtime:
        runtime.barrier.armed = True
        submission = asyncio.create_task(runtime.submit())
        try:
            await asyncio.wait_for(runtime.barrier.entered.wait(), timeout=15)
            assert len(await _rows(runtime)) == 1, "the SQL commit must have happened before cancellation"
            await _deliver_cancellation(submission)
            runtime.barrier.release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(submission), timeout=10)
            await runtime.service.stop()

            row = (await _rows(runtime))[0]
            assert row["cancel_requested_at"] is not None, "a committed owner must retain cancellation across worker restart"
            await runtime.service.run_once(now=datetime.now(UTC) + timedelta(seconds=120))
            assert await runtime.control("inspect_task") == {"status": "cancelled", "cancel_calls": 1, "submit_calls": 1}
        finally:
            runtime.barrier.release.set()
            if not submission.done():
                submission.cancel()
            await asyncio.wait_for(asyncio.gather(submission, return_exceptions=True), timeout=10)


class _SubmissionModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_child", [False, True], ids=["delivered", "cancelled"])
async def test_native_subagent_submit_uses_service_loop_and_preserves_context(tmp_path, monkeypatch, cancel_child):
    # Load the real executor beside conftest's circular-import stub. Its graph,
    # tool runtime and persistent native execution loop remain unchanged.
    path = Path(sys.modules[SubagentConfig.__module__].__file__).with_name("executor.py")
    spec = importlib.util.spec_from_file_location("_mcp_submission_executor", path)
    executor_module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, executor_module)
    spec.loader.exec_module(executor_module)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    main_loop = asyncio.get_running_loop()
    observed = asyncio.Event()
    observations = []
    execution_id = None
    result = None

    async with _runtime(tmp_path, monkeypatch) as runtime:

        async def observe_submit(request, handler):
            if request.name != "submit_report":
                return await handler(request)
            observation = {"loop": asyncio.get_running_loop(), "context": _SUBMISSION_CONTEXT.get(), "user": get_current_user().id}
            observations.append(observation)
            main_loop.call_soon_threadsafe(observed.set)
            response = await handler(request)
            observation["pid"] = response.structuredContent["pid"]
            return response

        runtime.caller._submit_interceptors.insert(0, observe_submit)
        process = await runtime.control("process_identity")
        model = _SubmissionModel(
            messages=iter(
                [
                    AIMessage(content="", tool_calls=[{"name": "submit_report", "args": {"hold_reply": cancel_child}, "id": "child-submit"}]),
                    AIMessage(content="The report was submitted."),
                ]
            )
        )

        monkeypatch.setattr(executor_module, "create_chat_model", lambda **kwargs: model)
        app_config = AppConfig.model_validate(
            {
                "models": [{"name": "offline", "use": "langchain_openai:ChatOpenAI", "model": "offline"}],
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "summarization": {"enabled": False},
            }
        )
        executor = executor_module.SubagentExecutor(
            config=SubagentConfig(name="reporter", description="Submit an offline report", skills=[]),
            tools=[runtime.submit_tool],
            parent_model="offline",
            app_config=app_config,
            thread_id=_THREAD,
            thread_incarnation=_INCARNATION,
            user_id=_USER,
            run_id="native-submission-run",
        )
        original_timeout = service_module._CANCELLATION_DRAIN_TIMEOUT_SECONDS
        try:
            if cancel_child:
                # The child must finish cancelling before the remote reply is
                # released. A zero caller drain budget makes that handshake
                # event-driven without spending the production grace period.
                monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0)
            token = _SUBMISSION_CONTEXT.set("native-child-context")
            try:
                execution_id = executor.execute_async("Submit the report")
            finally:
                _SUBMISSION_CONTEXT.reset(token)
            result = executor_module.get_background_task_result(execution_id)
            assert result is not None
            await asyncio.wait_for(observed.wait(), timeout=15)
            assert executor_module._isolated_subagent_loop is not None
            assert executor_module._isolated_subagent_loop is not main_loop
            assert observations[0]["loop"] is main_loop, "durable submission must not inherit the native child's loop"
            assert observations[0]["context"] == "native-child-context"
            assert observations[0]["user"] == _USER
            if cancel_child:
                await runtime.control("wait_until_accepted")
                executor_module.request_cancel_background_task(execution_id)
                assert await asyncio.to_thread(result.execution_done_event.wait, 15), result.error
                monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", original_timeout)
                await runtime.control("release_reply")
            assert await asyncio.to_thread(result.execution_done_event.wait, 15), result.error
            expected = executor_module.SubagentStatus.CANCELLED if cancel_child else executor_module.SubagentStatus.COMPLETED
            assert result.status == expected, result.error
            await runtime.service.stop()
            rows = await _rows(runtime)
            assert len(rows) == 1
            if cancel_child:
                assert rows[0]["cancel_requested_at"] is not None
                await runtime.service.run_once(now=datetime.now(UTC) + timedelta(seconds=120))
            else:
                assert rows[0]["cancel_requested_at"] is None
            remote = await runtime.control("inspect_task")
            assert remote == {"status": "cancelled" if cancel_child else "running", "cancel_calls": int(cancel_child), "submit_calls": 1}
            assert observations[0]["pid"] == process["pid"], "submit must reuse the service loop's stdio process"
            assert _SUBMISSION_CONTEXT.get() is None
        finally:
            monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", original_timeout)
            await runtime.control("release_reply")
            if execution_id is not None:
                executor_module.request_cancel_background_task(execution_id)
                if result is not None:
                    assert await asyncio.to_thread(result.execution_done_event.wait, 15)
                executor_module.cleanup_background_task(execution_id)
            await asyncio.to_thread(executor_module._shutdown_isolated_subagent_loop)
