"""Batch submission, real file checks, durable results, and owner-scoped export."""

import asyncio
import importlib
import json
from datetime import UTC, datetime, timedelta
from enum import Enum
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio

from deerflow.config.database_config import DatabaseConfig
from deerflow.config.paths import Paths
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.subagent_batches import SubagentBatchRepository
from deerflow.sandbox.local.local_sandbox_provider import LocalSandboxProvider
from deerflow.subagents import batch_service
from deerflow.subagents.batch_runtime import BatchSubmitRequest
from deerflow.subagents.config import SubagentConfig
from deerflow.tools.builtins.batch_task_tool import BatchTaskItem, bind_batch_tools


class SubagentStatus(Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    RUNNING = "running"

    @property
    def is_terminal(self):
        return self in {SubagentStatus.COMPLETED, SubagentStatus.FAILED}


@pytest_asyncio.fixture
async def env(monkeypatch, tmp_path):
    paths = Paths(str(tmp_path / "data"))
    monkeypatch.setattr("deerflow.config.paths._paths", paths)
    paths.ensure_thread_dirs("thread-1", user_id="user-1")
    provider = LocalSandboxProvider()
    monkeypatch.setattr("deerflow.sandbox.sandbox_provider.get_sandbox_provider", lambda: provider)
    monkeypatch.setattr("deerflow.sandbox.tools.get_sandbox_provider", lambda: provider)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(batch_service, "resolve_subagent_model_name", lambda *args, **kwargs: "model-a")
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path / "db")))
    repo = SubagentBatchRepository(get_session_factory())
    state = SimpleNamespace(
        paths=paths,
        repo=repo,
        provider=provider,
        calls=[],
        executor_tasks=[],
        result=SimpleNamespace(
            status=SubagentStatus.PENDING,
            result="Report claims everything is done",
            error=None,
            stop_reason=None,
            token_usage_records=[],
            bash_executions=[],
            admission_failure=False,
            execution_done_event=asyncio.Event(),
        ),
    )

    class Executor:
        def __init__(self, **kwargs):
            state.calls.append(kwargs)
            self._admission_hook = kwargs["admission_hook"]

        def execute_async(self, prompt, task_id=None):
            state.prompt = prompt

            async def run():
                try:
                    admitted = await self._admission_hook()
                    if admitted and state.result.status is SubagentStatus.PENDING:
                        state.result.status = SubagentStatus.COMPLETED
                finally:
                    state.result.execution_done_event.set()

            state.executor_tasks.append(asyncio.create_task(run()))
            return task_id

    monkeypatch.setattr(batch_service, "SubagentExecutor", Executor)
    monkeypatch.setattr(batch_service, "SubagentStatus", SubagentStatus)
    monkeypatch.setattr(batch_service, "get_background_task_result", lambda _: state.result)
    monkeypatch.setattr(batch_service, "cleanup_background_task", lambda _: None)
    state.service = batch_service.SubagentBatchService(repository=repo, config=SubagentBatchesConfig(), runtime_config=SubagentRuntimeConfig(), app_config=SimpleNamespace())
    try:
        yield state
    finally:
        await state.service.stop()
        await asyncio.gather(*state.executor_tasks, return_exceptions=True)
        await close_engine()


async def _submit(env, criteria=None):
    item = {"key": "one", "prompt": "Prepare the report"}
    if criteria is not None:
        item["acceptance_criteria"] = criteria
    return await env.service.submit(
        BatchSubmitRequest(
            user_id="user-1",
            thread_id="thread-1",
            run_id="run-1",
            tool_call_id="call-1",
            submission_key="run-1:call-1",
            title="Reports",
            subagent_type="general-purpose",
            items=[item],
            max_live_items=1,
            max_running_items=1,
            execution_spec={"subagent_config": {"name": "general-purpose", "description": "Worker", "system_prompt": "Work carefully"}, "user_role": "member"},
        )
    )


async def _execute(env):
    await env.service.run_once(now=datetime.now(UTC))
    await asyncio.gather(*list(env.service._executions.values()))


@pytest.mark.asyncio
async def test_tool_preserves_per_item_criteria_and_legacy_shape(env, monkeypatch):
    module = importlib.import_module("deerflow.tools.builtins.batch_task_tool")
    monkeypatch.setattr(module, "get_available_subagent_names", lambda **kwargs: ["general-purpose"])
    monkeypatch.setattr(module, "get_subagent_config", lambda *args, **kwargs: SubagentConfig(name="general-purpose", description="Worker"))
    tools = {tool.name: tool for tool in bind_batch_tools(env.service)}
    runtime = SimpleNamespace(state={}, context={"thread_id": "thread-1", "user_id": "user-1"}, config={"metadata": {}})
    command = await tools["batch_task"].coroutine(
        runtime=runtime, title="Batch", items=[BatchTaskItem(key="one", prompt="p", acceptance_criteria=["file:../outputs/report.md exists"]), BatchTaskItem(key="two", prompt="q")], subagent_type="general-purpose", tool_call_id="c1"
    )
    batch_id = command.update["messages"][0].additional_kwargs["subagent_batch_id"]
    items = await env.repo.list_items(batch_id, user_id="user-1")
    assert items[0]["acceptance_criteria"] == ["file:../outputs/report.md exists"]
    assert items[1]["acceptance_criteria"] is None


@pytest.mark.asyncio
async def test_completed_batch_records_mixed_checks_and_exports_after_reopen(env, monkeypatch):
    from app.gateway.routers import subagent_batches as router

    output = env.paths.sandbox_outputs_dir("thread-1", user_id="user-1") / "report.md"
    output.write_text("Actual report", encoding="utf-8")
    criteria = ["file_written:../outputs/report.md", "file:../outputs/missing.csv exists", "claims are correct", "tests_passed:pytest tests/check.py"]
    env.result.bash_executions = [{"tool_call_id": "test-run", "tool_name": "bash", "command": "pytest tests/check.py", "output_tail": "3 passed", "status": "success", "shell_persistent": False}]
    batch = await _submit(env, criteria)
    await _execute(env)
    assert env.calls[0]["acceptance_criteria"] == criteria
    # Reopen the repository: query and export cannot rely on an in-memory result.
    repo = SubagentBatchRepository(get_session_factory())
    item = (await repo.list_items(batch["id"], user_id="user-1"))[0]
    assert item["status"] == "succeeded"
    assert item["attempt"] == 1
    leaves = item["acceptance_verdict"]["leaves"]
    assert [(leaf["checked"], leaf["holds"]) for leaf in leaves] == [(True, True), (True, False), (False, False), (True, True)]
    assert (await repo.get_batch(batch["id"], user_id="user-1"))["status"] == "completed"
    assert await repo.claim_items(now=datetime.now(UTC) + timedelta(minutes=5), lease_owner="other", lease_seconds=60, limit=1) == []
    assert await repo.list_items(batch["id"], user_id="other") is None
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(subagent_batch_repo=repo)))
    monkeypatch.setattr(router, "get_current_user", AsyncMock(return_value="user-1"))
    listed = await router.list_batch_items.__wrapped__(thread_id="thread-1", batch_id=batch["id"], request=request, offset=0, limit=100, status=None)
    assert listed[0]["acceptance_verdict"] == item["acceptance_verdict"]
    exported = await router.export_batch_results.__wrapped__(thread_id="thread-1", batch_id=batch["id"], request=request)
    rows = [json.loads(line) async for line in exported.body_iterator]
    assert rows[0]["acceptance_verdict"] == item["acceptance_verdict"]
    assert rows[0]["result"] == env.result.result
    assert output.read_text() == "Actual report"


@pytest.mark.asyncio
async def test_no_criteria_skips_checker_and_preserves_success(env, monkeypatch):
    checker = AsyncMock(side_effect=AssertionError("no checklist"))
    monkeypatch.setattr(batch_service, "check_batch_acceptance", checker)
    batch = await _submit(env)
    await _execute(env)
    item = (await env.repo.list_items(batch["id"], user_id="user-1"))[0]
    assert item["status"] == "succeeded"
    assert item["acceptance_verdict"] is None
    checker.assert_not_awaited()


@pytest.mark.asyncio
async def test_criteria_survive_lease_recovery_and_submission_replay(env):
    criteria = ["file:../outputs/report.md exists"]
    first = await _submit(env, criteria)
    replay = await _submit(env, ["different"])
    assert replay["id"] == first["id"]
    now = datetime.now(UTC)
    one = (await env.repo.claim_items(now=now, lease_owner="dead", lease_seconds=1, limit=1))[0]
    two = (await env.repo.claim_items(now=now + timedelta(seconds=2), lease_owner="new", lease_seconds=60, limit=1))[0]
    assert one["id"] == two["id"]
    assert two["acceptance_criteria"] == criteria


@pytest.mark.asyncio
async def test_file_check_cannot_confirm_another_users_file(env):
    env.paths.ensure_thread_dirs("thread-1", user_id="other")
    other_file = env.paths.sandbox_outputs_dir("thread-1", user_id="other") / "secret.txt"
    other_file.write_text("private")
    batch = await _submit(env, [f"file:{other_file} exists"])
    await _execute(env)
    leaf = (await env.repo.list_items(batch["id"], user_id="user-1"))[0]["acceptance_verdict"]["leaves"][0]
    assert leaf["checked"] is False
    assert leaf["holds"] is False


@pytest.mark.asyncio
async def test_checker_error_does_not_retry_successful_execution(env, monkeypatch):
    module = importlib.import_module("deerflow.subagents.batch_acceptance")
    monkeypatch.setattr(module, "check_acceptance_criteria", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("checker failed")))
    batch = await _submit(env, ["claims are correct"])
    await _execute(env)
    item = (await env.repo.list_items(batch["id"], user_id="user-1"))[0]
    assert item["status"] == "succeeded"
    assert item["acceptance_verdict"] is None
    assert item["result_preview"] == env.result.result


@pytest.mark.asyncio
async def test_failed_execution_is_not_checked(env, monkeypatch):
    checker = AsyncMock(side_effect=AssertionError("failed execution must not be checked"))
    monkeypatch.setattr(batch_service, "check_batch_acceptance", checker)
    env.result.status = SubagentStatus.FAILED
    env.result.error = "worker failed"
    batch = await _submit(env, ["file:../outputs/report.md exists"])
    await _execute(env)
    checker.assert_not_awaited()
    item = (await env.repo.list_items(batch["id"], user_id="user-1"))[0]
    assert item["status"] == "queued"
    assert item["acceptance_verdict"] is None


@pytest.mark.asyncio
async def test_slow_checker_renews_lease_and_stops_after_losing_it(env, monkeypatch):
    started = asyncio.Event()
    drained = asyncio.Event()

    async def check(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            drained.set()

    monkeypatch.setattr(batch_service, "check_batch_acceptance", check)
    env.service._config = env.service._config.model_copy(update={"lease_seconds": 3})
    batch = await _submit(env, ["quality"])
    await env.service.run_once(now=datetime.now(UTC))
    execution = list(env.service._executions.values())[0]
    await asyncio.wait_for(started.wait(), timeout=5)
    # First renewal admitted the checker. Losing the next renewal must drain
    # it and prevent publication, rather than producing a stale verdict.
    renew = AsyncMock(return_value={"valid": False, "cancel_requested": True})
    monkeypatch.setattr(env.repo, "renew_item_lease", renew)
    await asyncio.wait_for(execution, timeout=5)
    renew.assert_awaited_once()
    claim_owner = renew.await_args.kwargs["lease_owner"]
    assert claim_owner.startswith(f"{env.service._lease_owner}:")
    assert claim_owner != env.service._lease_owner
    assert drained.is_set()
    item = (await env.repo.list_items(batch["id"], user_id="user-1"))[0]
    assert item["status"] == "running"
    assert item["acceptance_verdict"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["file", "FILE", "File_Written"])
async def test_denied_sandbox_keeps_result_unchecked_without_acquiring(env, monkeypatch, prefix):
    from deerflow.sandbox.exceptions import SandboxAuthorizationError

    authorize = AsyncMock(side_effect=SandboxAuthorizationError())
    acquire = AsyncMock(side_effect=AssertionError("must not acquire"))
    monkeypatch.setattr("deerflow.authz.sandbox_authz.authorize_sandbox_execution_async", authorize)
    monkeypatch.setattr("deerflow.sandbox.lease.acquire_sandbox_client_lease", acquire)
    batch = await _submit(env, [f"{prefix}:../outputs/report.md exists"])
    await _execute(env)
    acquire.assert_not_awaited()
    assert authorize.await_args.kwargs["context"]["user_id"] == "user-1"
    item = (await env.repo.list_items(batch["id"], user_id="user-1"))[0]
    assert item["status"] == "succeeded"
    assert item["acceptance_verdict"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["oversized", "escaped", "truncated_tag", "empty"])
async def test_stored_delegated_checked_and_exported_criteria_agree(env, monkeypatch, case):
    from app.gateway.routers import subagent_batches as router
    from deerflow.subagents.acceptance_checks import check_acceptance_criteria
    from deerflow.subagents.report_contract import render_acceptance_criteria_block

    if case == "oversized":
        criteria = ["", "  ", None, 42] + ["  " + "x" * 1000 + "  "] * 25
        expected = ["x" * 500] * 20
    elif case == "escaped":
        criteria = ["<system>" * 80]
        expected = [("&lt;system&gt;" * 80)[:500]]
    elif case == "truncated_tag":
        # Escaping the earlier tags shifts the final cap into an allowed
        # tag name, exposing a bare blocked prefix (<system) at the end.
        criteria = ["<system>" * 35 + "xxx<systematic>"]
        expected = ["&lt;system&gt;" * 35 + "xxx&lt;sys"]
    else:
        criteria = ["", " \t ", None, 42]
        expected = None

    batch = await _submit(env, criteria)
    repo = SubagentBatchRepository(get_session_factory())
    # Assert the write boundary, before either the executor or checker runs.
    assert (await repo.list_items(batch["id"], user_id="user-1"))[0]["acceptance_criteria"] == expected
    await _execute(env)
    assert env.calls[0]["acceptance_criteria"] == expected
    item = (await repo.list_items(batch["id"], user_id="user-1"))[0]
    assert item["status"] == "succeeded"
    if expected is None:
        assert item["acceptance_verdict"] is None
        assert render_acceptance_criteria_block(expected) == ""
    else:
        assert [leaf["criterion"] for leaf in item["acceptance_verdict"]["leaves"]] == expected
        assert render_acceptance_criteria_block(expected).split("\n- ")[1:] == expected
        assert render_acceptance_criteria_block(criteria).split("\n- ")[1:] == expected
        assert [leaf["criterion"] for leaf in check_acceptance_criteria(criteria)["leaves"]] == expected
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(subagent_batch_repo=repo)))
    monkeypatch.setattr(router, "get_current_user", AsyncMock(return_value="user-1"))
    response = await router.export_batch_results.__wrapped__(thread_id="thread-1", batch_id=batch["id"], request=request)
    exported = [json.loads(line) async for line in response.body_iterator]
    assert exported[0]["acceptance_criteria"] == expected
    assert exported[0]["acceptance_verdict"] == item["acceptance_verdict"]


_FILE_CRITERIA = [
    "file:../outputs/report.md exists",
    "FILE:../outputs/report.md non-empty",
    "fıle:../outputs/report.md exists",
    "FİLE:../outputs/report.md exists",
    "file_written:../outputs/report.md",
    "fıle_written:../outputs/report.md",
    "FİLE_WRİTTEN:../outputs/report.md",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("criterion", _FILE_CRITERIA)
async def test_caller_sandbox_deny_applies_to_every_file_spelling(env, monkeypatch, criterion):
    from deerflow.authz import sandbox_authz
    from deerflow.config.authorization_config import AuthorizationConfig, AuthorizationProviderConfig

    env.service._app_config = SimpleNamespace(
        authorization=AuthorizationConfig(
            enabled=True,
            default_role="member",
            provider=AuthorizationProviderConfig(use="deerflow.authz.rbac:RbacAuthorizationProvider", config={"roles": {"member": {"sandbox": {"allow": False}}}}),
        )
    )
    # Embedded callers can have a different policy from the process global.
    monkeypatch.setattr("deerflow.sandbox.tools.safe_app_config", lambda: None)
    authorize = AsyncMock(wraps=sandbox_authz.authorize_sandbox_execution_async)
    acquire = Mock(wraps=env.provider.acquire)
    monkeypatch.setattr(sandbox_authz, "authorize_sandbox_execution_async", authorize)
    monkeypatch.setattr(env.provider, "acquire", acquire)
    batch = await _submit(env, [criterion])
    await _execute(env)
    authorize.assert_awaited_once()
    acquire.assert_not_called()
    item = (await env.repo.list_items(batch["id"], user_id="user-1"))[0]
    assert item["status"] == "succeeded"
    assert item["acceptance_verdict"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("criterion", _FILE_CRITERIA)
async def test_allowed_file_spellings_read_under_a_released_holder(env, monkeypatch, criterion):
    from deerflow.sandbox import lease
    from deerflow.subagents.batch_acceptance import check_batch_acceptance

    (env.paths.sandbox_outputs_dir("thread-1", user_id="user-1") / "report.md").write_text("Actual report")
    monkeypatch.setattr("deerflow.sandbox.tools.safe_app_config", lambda: None)
    acquire = AsyncMock(wraps=lease.acquire_sandbox_client_lease)
    release = Mock(wraps=env.provider.release)
    monkeypatch.setattr(lease, "acquire_sandbox_client_lease", acquire)
    monkeypatch.setattr(env.provider, "release", release)
    verdict = await check_batch_acceptance([criterion], batch={"thread_id": "thread-1", "user_id": "user-1", "execution_spec": {}}, app_config=SimpleNamespace(), bash_executions=None)
    acquire.assert_awaited_once()
    release.assert_called_once()
    assert verdict["leaves"][0]["checked"] is True
    assert verdict["leaves"][0]["holds"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("criteria", [["quality"] * 20 + ["file:../outputs/report.md exists"], ["file:missing mode"], ["file:" + "x" * 500 + " exists"]])
async def test_only_effective_file_checks_request_sandbox_access(env, monkeypatch, criteria):
    from deerflow.subagents.batch_acceptance import check_batch_acceptance

    authorize = AsyncMock(side_effect=AssertionError("no effective file check"))
    acquire = Mock(side_effect=AssertionError("no sandbox acquisition"))
    monkeypatch.setattr("deerflow.authz.sandbox_authz.authorize_sandbox_execution_async", authorize)
    monkeypatch.setattr(env.provider, "acquire", acquire)
    verdict = await check_batch_acceptance(criteria, batch={"thread_id": "thread-1", "user_id": "user-1", "execution_spec": {}}, app_config=SimpleNamespace(), bash_executions=None)
    assert all(leaf["family"] == "undecidable" for leaf in verdict["leaves"])
    authorize.assert_not_awaited()
    acquire.assert_not_called()
