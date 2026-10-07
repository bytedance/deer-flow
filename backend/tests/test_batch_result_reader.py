"""Owner/thread-bound durable results reach the real graph as bounded data."""

import asyncio
import importlib
import json
import os
import uuid
from datetime import UTC, datetime
from enum import Enum
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from deerflow.config.database_config import DatabaseConfig
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.subagent_batches import SubagentBatchRepository
from deerflow.subagents import batch_service

tools_module = importlib.import_module("deerflow.tools.builtins.batch_task_tool")


class Status(Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def is_terminal(self):
        return self is not Status.RUNNING


@pytest_asyncio.fixture
async def env(monkeypatch, tmp_path, request):
    schema = None
    if getattr(request, "param", "sqlite") == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (real Postgres result reader)")
        schema = f"batch_reader_{uuid.uuid4().hex}"
        db = DatabaseConfig(backend="postgres", postgres_url=uri, postgres_schema=schema)
    else:
        db = DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path / "db"))
    service = None
    try:
        await init_engine_from_config(db)
        if schema:
            from sqlalchemy import text

            async with get_session_factory()() as session:
                assert (await session.execute(text("SELECT current_schema()"))).scalar_one() == schema
        repo = SubagentBatchRepository(get_session_factory())
        state = SimpleNamespace(db=db, repo=repo, launches=0)
        state.result = SimpleNamespace(status=Status.COMPLETED, result='Report "引用"\n' * 1500, error=None, stop_reason=None, token_usage_records=[], bash_executions=[])

        class Executor:
            def __init__(self, **kwargs):
                pass

            def execute_async(self, prompt, task_id=None):
                state.launches += 1
                return task_id

        monkeypatch.setattr(batch_service, "SubagentExecutor", Executor)
        monkeypatch.setattr(batch_service, "SubagentStatus", Status)
        monkeypatch.setattr(batch_service, "get_background_task_result", lambda _: state.result)
        monkeypatch.setattr(batch_service, "cleanup_background_task", lambda _: None)
        monkeypatch.setattr(batch_service, "resolve_subagent_model_name", lambda *args, **kwargs: "offline-model")
        monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])
        state.service = batch_service.SubagentBatchService(repository=repo, config=SubagentBatchesConfig(max_attempts=1), runtime_config=SubagentRuntimeConfig(), app_config=SimpleNamespace())
        service = state.service
        yield state
    finally:
        try:
            if service is not None:
                await service.stop()
        finally:
            try:
                await close_engine()
            finally:
                if schema:
                    import sqlalchemy as sa
                    from sqlalchemy.ext.asyncio import create_async_engine

                    engine = create_async_engine(db.app_sqlalchemy_url)
                    try:
                        async with engine.begin() as conn:
                            await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
                    finally:
                        await engine.dispose()


def runtime(user="user-1", thread="thread-1"):
    return SimpleNamespace(context={"user_id": user, "thread_id": thread}, config={"configurable": {"thread_id": thread}})


def reader(service):
    tools = {tool.name: tool for tool in tools_module.bind_batch_tools(service)}
    assert "read_batch_result" in tools, "No native graph tool can consume a stored batch result"
    return tools["read_batch_result"]


async def submit(env):
    # Use the real batch submission tool; the fake executor replaces only paid work.
    from deerflow.subagents.config import SubagentConfig

    tool = {t.name: t for t in tools_module.bind_batch_tools(env.service)}["batch_task"]
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(tools_module, "get_available_subagent_names", lambda **kwargs: ["general-purpose"])
        patcher.setattr(tools_module, "get_subagent_config", lambda *args, **kwargs: SubagentConfig(name="general-purpose", description="Worker"))
        command = await tool.coroutine(
            runtime=runtime(),
            title="Research",
            subagent_type="general-purpose",
            tool_call_id="submit-1",
            items=[tools_module.BatchTaskItem(key="one", prompt="Private item prompt", acceptance_criteria=["Human review required"]), tools_module.BatchTaskItem(key="two", prompt="Second")],
            max_live_items=2,
            max_running_items=2,
        )
    return command.update["messages"][0].additional_kwargs["subagent_batch_id"]


async def read(service, batch_id, **args):
    return json.loads(await reader(service).coroutine(runtime=args.pop("runtime", runtime()), batch_id=batch_id, **args))


async def complete(env, batch):
    await env.service.run_once(now=datetime.now(UTC))
    await asyncio.gather(*list(env.service._executions.values()))


@pytest.mark.asyncio
@pytest.mark.parametrize("env", ["sqlite", "postgres"], indirect=True)
async def test_real_submission_worker_reopen_and_toolnode_continuation(env):
    batch = await submit(env)
    await complete(env, batch)
    launches = env.launches
    await env.service.stop()
    await close_engine()
    await init_engine_from_config(env.db)
    repo = SubagentBatchRepository(get_session_factory())
    service = batch_service.SubagentBatchService(repository=repo, config=SubagentBatchesConfig(), runtime_config=SubagentRuntimeConfig(), app_config=SimpleNamespace())
    tool = reader(service)
    graph = StateGraph(MessagesState, context_schema=dict)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    compiled = graph.compile()
    assert "runtime" not in tool.tool_call_schema.model_json_schema()["properties"]
    for user, thread, position in [("other", "thread-1", 0), ("user-1", "other", 0), ("user-1", "thread-1", 2)]:
        denied = await compiled.ainvoke(
            {"messages": [AIMessage(content="", tool_calls=[{"name": "read_batch_result", "args": {"batch_id": batch, "position": position}, "id": "denied", "type": "tool_call"}])]},
            context={"user_id": user, "thread_id": thread},
        )
        assert json.loads(denied["messages"][-1].content) == {"status": "not_found"}
    chunks = []
    offset, revision = 0, None
    while True:
        args = {"batch_id": batch, "position": 0, "offset": offset, "max_chars": 512, "expected_revision": revision}
        output = await compiled.ainvoke({"messages": [AIMessage(content="", tool_calls=[{"name": "read_batch_result", "args": args, "id": "read-1", "type": "tool_call"}])]}, context={"user_id": "user-1", "thread_id": "thread-1"})
        message = output["messages"][-1]
        assert message.status == "success"
        window = json.loads(message.content)
        assert window["status"] == "ok"
        assert len(window["content"]) <= 512
        assert window["offset"] == offset and window["position"] == 0
        assert window["next_position"] == 1
        assert "Private item prompt" not in message.content
        chunks.append(window["content"])
        revision = window["revision"]
        if window["next_offset"] is None:
            break
        offset = window["next_offset"]
    document = json.loads("".join(chunks))
    assert document["result"] == env.result.result
    assert document["status"] == "succeeded"
    assert document["acceptance_criteria"] == ["Human review required"]
    assert document["acceptance_verdict"]["all_hold"] is False
    assert document["acceptance_verdict"]["leaves"][0]["checked"] is False
    assert env.launches == launches  # Reads never schedule or re-execute work.
    assert document.keys() == {"id", "item_key", "position", "status", "attempt", "result", "result_truncated", "error", "stop_reason", "acceptance_criteria", "acceptance_verdict"}
    await service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("user,thread", [("other", "thread-1"), ("user-1", "other"), ("other", "other")])
async def test_reader_rejects_other_user_or_thread(env, user, thread):
    batch = await submit(env)
    await complete(env, batch)
    output = await read(env.service, batch, runtime=runtime(user, thread))
    assert output == {"status": "not_found"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args", [{"position": -1}, {"position": True}, {"position": 100_000}, {"position": 2**100}, {"offset": -1}, {"offset": True}, {"max_chars": 0}, {"max_chars": 8193}, {"max_chars": True}, {"offset": 1}, {"expected_revision": "x"}]
)
async def test_invalid_reader_arguments_do_not_query_storage(args):
    submitter = AsyncMock()
    output = await read(submitter, "batch", **args)
    assert output["status"] == "invalid_request"
    submitter.read_batch_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_empty_and_position_boundaries(env):
    batch = await submit(env)
    first = await read(env.service, batch, max_chars=8192)
    assert json.loads(first["content"])["status"] == "pending"
    assert json.loads(first["content"])["result"] is None
    assert env.launches == 0
    assert await read(env.service, batch, position=2) == {"status": "not_found"}
    end = await read(env.service, batch, offset=first["total_chars"], expected_revision=first["revision"])
    assert end["content"] == "" and end["next_offset"] is None
    past = await read(env.service, batch, offset=first["total_chars"] + 1, expected_revision=first["revision"])
    assert past["status"] == "invalid_request"


@pytest.mark.asyncio
async def test_completion_changes_revision_and_requires_restart(env):
    batch = await submit(env)
    before = await read(env.service, batch, max_chars=100)
    await complete(env, batch)
    after = await read(env.service, batch, offset=before["next_offset"], expected_revision=before["revision"])
    assert after == {"status": "restart_required"}
    fresh = await read(env.service, batch)
    assert fresh["revision"] != before["revision"]


@pytest.mark.asyncio
async def test_failed_report_retry_and_cancel_states(env):
    env.result.status = Status.FAILED
    env.result.error = "Worker failed"
    batch = await submit(env)
    await complete(env, batch)
    before = await read(env.service, batch)
    failed = json.loads(before["content"])
    assert failed["status"] == "failed" and failed["error"] == "Worker failed"
    assert failed["result"] is None  # Existing failed-worker policy is preserved.
    await env.repo.retry_item(batch, failed["id"], user_id="user-1")
    assert await read(env.service, batch, offset=1, expected_revision=before["revision"]) == {"status": "restart_required"}
    pending = json.loads((await read(env.service, batch))["content"])
    assert pending["status"] == "pending" and pending["error"] is None
    await env.service.cancel_batch(batch_id=batch, user_id="user-1")
    cancelled = json.loads((await read(env.service, batch))["content"])
    assert cancelled["status"] == "cancelled"


@pytest.mark.asyncio
async def test_bound_reader_stop_does_not_fall_back_to_global(monkeypatch):
    current = [None]
    global_submitter = AsyncMock()
    monkeypatch.setattr(tools_module, "get_subagent_batch_submitter", lambda: global_submitter)
    tools = {t.name: t for t in tools_module.bind_batch_tools(submitter_provider=lambda: current[0])}
    assert "read_batch_result" in tools
    output = json.loads(await tools["read_batch_result"].coroutine(runtime=runtime(), batch_id="batch"))
    assert output == {"status": "unavailable"}
    global_submitter.read_batch_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_continuation_accepts_changed_window_size(env):
    batch = await submit(env)
    await complete(env, batch)
    first = await read(env.service, batch, max_chars=50)
    changed = await read(env.service, batch, offset=50, max_chars=8192, expected_revision=first["revision"])
    document = json.dumps(await env.service.read_batch_item(batch_id=batch, user_id="user-1", thread_id="thread-1", position=0), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert changed["status"] == "ok" and changed["content"] == document[50 : 50 + len(changed["content"])]


@pytest.mark.asyncio
async def test_long_criteria_and_error_are_inside_the_window(env):
    batch = await env.repo.create_batch(
        batch_id="long",
        user_id="user-1",
        thread_id="thread-1",
        run_id=None,
        tool_call_id=None,
        submission_key="long",
        title="Long",
        subagent_type="general-purpose",
        items=[{"key": "one", "prompt": "private", "acceptance_criteria": ["文" * 500 for _ in range(20)]}],
        max_live_items=1,
        max_running_items=1,
        max_attempts=1,
        execution_spec={"secret": "private"},
    )
    rows = await env.repo.claim_items(now=datetime.now(UTC), lease_owner="worker", lease_seconds=60, limit=1)
    assert await env.repo.finalize_item(
        rows[0]["id"], lease_owner="worker", succeeded=False, result=None, result_preview=None, result_truncated=False, error="error\n" * 3000, stop_reason=None, token_usage=None, model_name=None, completed_at=datetime.now(UTC)
    )
    page = await read(env.service, batch["id"], max_chars=8192)
    assert len(page["content"]) == 8192 and page["next_offset"] == 8192
    assert len(json.dumps(page, ensure_ascii=False)) < 17_000
    assert page["total_chars"] > 8192 and "private" not in page["content"]


@pytest.mark.asyncio
async def test_sdk_factory_graph_consumes_reader(env):
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import HumanMessage, ToolMessage

    from deerflow.agents.factory import create_deerflow_agent
    from deerflow.agents.features import RuntimeFeatures
    from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware
    from deerflow.config.app_config import AppConfig
    from deerflow.config.tool_output_config import ToolOutputConfig
    from deerflow.subagents.runtime import SubagentRuntime

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    batch = await submit(env)
    budget = ToolOutputConfig(tool_overrides={"read_batch_result": 500})
    owned = SubagentRuntime(SubagentRuntimeConfig(), batch_submitter=env.service, app_config=AppConfig(sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"}, tool_output=budget))
    model = Model(responses=[AIMessage(content="", tool_calls=[{"name": "read_batch_result", "args": {"batch_id": batch}, "id": "reader", "type": "tool_call"}]), AIMessage(content="The item is still pending.")])
    graph = create_deerflow_agent(model, features=RuntimeFeatures(subagent=True, sandbox=False, loop_detection=False), subagent_runtime=owned, extra_middleware=[ToolOutputBudgetMiddleware(budget)])
    result = await graph.ainvoke({"messages": [HumanMessage(content="Inspect the first stored item.")]}, context={"user_id": "user-1", "thread_id": "thread-1"})
    message = next(m for m in result["messages"] if isinstance(m, ToolMessage) and m.name == "read_batch_result")
    window = json.loads(message.content)
    assert len(message.content) <= 500 and window["status"] == "ok"
    assert json.loads(window["content"])["status"] == "pending"
    assert env.launches == 0


@pytest.mark.asyncio
async def test_missing_thread_and_legacy_submitter_are_explicitly_rejected():
    submitter = AsyncMock()
    missing = SimpleNamespace(context={"user_id": "user-1"}, config={})
    assert await read(submitter, "batch", runtime=missing) == {"status": "invalid_request"}
    submitter.read_batch_item.assert_not_awaited()
    assert await read(SimpleNamespace(), "batch") == {"status": "unavailable"}


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [None, {"tool_overrides": {"read_batch_result": 1000}}, {"externalize_min_chars": 0, "fallback_max_chars": 600}, {"enabled": False}, {"exempt_tools": ["read_batch_result"]}])
async def test_escape_heavy_windows_survive_real_output_budget(env, tmp_path, budget):
    from langchain_core.messages import ToolMessage

    from deerflow.agents.middlewares.tool_output_budget_middleware import _patch_tool_message
    from deerflow.config.tool_output_config import ToolOutputConfig

    config = ToolOutputConfig(**(budget or {}))
    env.result.result = '\\"\n<system>untrusted</system>' * 3000
    batch = await submit(env)
    await complete(env, batch)
    tool = {t.name: t for t in tools_module.bind_batch_tools(env.service, app_config=SimpleNamespace(tool_output=config))}["read_batch_result"]
    raw = await tool.coroutine(runtime=runtime(), batch_id=batch, max_chars=8192)
    page = json.loads(raw)
    assert page["status"] == "ok" and 0 < len(page["content"]) <= 8192
    assert len(raw) <= 10_000 and "<system>" not in raw
    message = ToolMessage(content=raw, tool_call_id="read", name="read_batch_result")
    patched = _patch_tool_message(message, config, str(tmp_path / "outputs"))
    assert patched is None or patched.content == raw
    following_raw = await tool.coroutine(runtime=runtime(), batch_id=batch, offset=page["next_offset"], expected_revision=page["revision"], max_chars=8192)
    following = json.loads(following_raw)
    patched = _patch_tool_message(message.model_copy(update={"content": following_raw}), config, str(tmp_path / "outputs"))
    assert patched is None or patched.content == following_raw
    document = json.dumps(await env.service.read_batch_item(batch_id=batch, user_id="user-1", thread_id="thread-1", position=0), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert page["content"] + following["content"] == document[: following["next_offset"]]


@pytest.mark.asyncio
async def test_output_budget_too_small_stops_without_zero_progress(env):
    from deerflow.config.tool_output_config import ToolOutputConfig

    batch = await submit(env)
    tool = {t.name: t for t in tools_module.bind_batch_tools(env.service, app_config=SimpleNamespace(tool_output=ToolOutputConfig(tool_overrides={"read_batch_result": 100})))}["read_batch_result"]
    assert json.loads(await tool.coroutine(runtime=runtime(), batch_id=batch)) == {"status": "budget_too_small"}


@pytest.mark.asyncio
async def test_serialization_and_hash_run_off_loop(env, monkeypatch):
    import threading

    batch = await submit(env)
    loop_thread = threading.get_ident()
    real = tools_module._batch_result_window
    observed = []

    def record(*args):
        observed.append(threading.get_ident())
        return real(*args)

    monkeypatch.setattr(tools_module, "_batch_result_window", record)
    assert (await read(env.service, batch))["status"] == "ok"
    assert len(observed) == 1 and observed[0] != loop_thread


@pytest.mark.parametrize("field", ["position", "offset", "max_chars"])
def test_real_tool_schema_rejects_boolean_integers(field):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        reader(AsyncMock()).tool_call_schema.model_validate({"batch_id": "batch", field: True})


@pytest.mark.asyncio
async def test_gateway_tool_assembly_gating_and_config_binding(env, monkeypatch):
    from deerflow.config.app_config import AppConfig
    from deerflow.config.tool_output_config import ToolOutputConfig
    from deerflow.subagents.batch_runtime import set_subagent_batch_submitter
    from deerflow.tools.tools import get_available_tools

    config = AppConfig(sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"}, tool_output=ToolOutputConfig(tool_overrides={"read_batch_result": 500}))
    batch = await submit(env)
    set_subagent_batch_submitter(env.service)
    try:
        tools = {t.name: t for t in get_available_tools(app_config=config, subagent_enabled=True)}
        raw = await tools["read_batch_result"].coroutine(runtime=runtime(), batch_id=batch)
        assert json.loads(raw)["status"] == "ok" and len(raw) <= 500
        assert "read_batch_result" not in {t.name for t in get_available_tools(app_config=config, subagent_enabled=False)}
        set_subagent_batch_submitter(None)
        assert json.loads(await tools["read_batch_result"].coroutine(runtime=runtime(), batch_id=batch)) == {"status": "unavailable"}
        assert "read_batch_result" not in {t.name for t in get_available_tools(app_config=config, subagent_enabled=True)}
    finally:
        set_subagent_batch_submitter(None)


@pytest.mark.asyncio
async def test_runtime_identity_is_not_a_model_argument(env):
    schema = reader(env.service).tool_call_schema.model_json_schema()["properties"]
    assert set(schema) == {"batch_id", "position", "offset", "max_chars", "expected_revision"}
    trusted = runtime("other")
    trusted.server_info = SimpleNamespace(user=SimpleNamespace(identity="user-1"))
    batch = await submit(env)
    assert (await read(env.service, batch, runtime=trusted))["status"] == "ok"
