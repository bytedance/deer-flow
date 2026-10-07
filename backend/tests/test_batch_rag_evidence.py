"""RAG producer -> durable worker -> reopened SQL -> owner JSONL evidence."""

import asyncio
import importlib.util
import json
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from langchain_core.messages import ToolMessage

from deerflow.community.ragflow.formatting import format_retrieval_sources
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.subagent_batches import SubagentBatchRepository
from deerflow.subagents import batch_service
from deerflow.subagents.batch_runtime import BatchSubmitRequest
from deerflow.subagents.step_events import capture_step_message


class Status(Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def is_terminal(self):
        return self is not Status.RUNNING


def retrieval(*, text="Original evidence", name="knowledge_search"):
    content, artifact = format_retrieval_sources(
        {"chunks": [{"id": "chunk", "dataset_id": "kb", "document_id": "doc", "document_keyword": "Manual.pdf", "content": text}]},
        dataset_names_by_id={"kb": "Engineering"},
        max_chars_per_chunk=20_000,
        max_total_chars=30_000,
    )
    captured = []
    capture_step_message(ToolMessage(content=content, artifact=artifact, name=name, tool_call_id="search", id="message"), captured, set())
    return content, captured


@pytest_asyncio.fixture
async def env(monkeypatch, tmp_path):
    db = DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path / "db"))
    await init_engine_from_config(db)
    repo = SubagentBatchRepository(get_session_factory())
    state = SimpleNamespace(repo=repo, db=db, result=SimpleNamespace(status=Status.COMPLETED, result="plain report", ai_messages=[], error=None, stop_reason=None, token_usage_records=[]))

    class Executor:
        def __init__(self, **kwargs):
            state.owner = kwargs["user_id"]
            state.scope = kwargs["knowledge_scope"]

        def execute_async(self, prompt, task_id=None):
            return task_id

    monkeypatch.setattr(batch_service, "SubagentExecutor", Executor)
    monkeypatch.setattr(batch_service, "SubagentStatus", Status)
    monkeypatch.setattr(batch_service, "get_background_task_result", lambda _: state.result)
    monkeypatch.setattr(batch_service, "cleanup_background_task", lambda _: None)
    monkeypatch.setattr(batch_service, "resolve_subagent_model_name", lambda *args, **kwargs: "offline-model")
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])
    state.service = batch_service.SubagentBatchService(repository=repo, config=SubagentBatchesConfig(), runtime_config=SubagentRuntimeConfig(), app_config=SimpleNamespace())
    try:
        yield state
    finally:
        await state.service.stop()
        await close_engine()


async def execute(env):
    batch = await env.service.submit(
        BatchSubmitRequest(
            user_id="user-1",
            thread_id="thread-1",
            run_id="run-1",
            tool_call_id="call-1",
            submission_key="submission",
            title="Research",
            subagent_type="general-purpose",
            items=[{"key": "one", "prompt": "Research the selected knowledge base"}],
            max_live_items=None,
            max_running_items=None,
            execution_spec={"subagent_config": {"name": "general-purpose", "description": "Researcher", "system_prompt": "Research"}, "knowledge_scope": {"version": 1, "mode": "selected", "dataset_ids": ["kb"]}},
        )
    )
    await env.service.run_once(now=datetime.now(UTC))
    await asyncio.gather(*list(env.service._executions.values()))
    return batch


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["knowledge_search", "task"])
async def test_cited_evidence_survives_worker_database_reopen_and_export(env, monkeypatch, tool_name):
    from app.gateway.routers import subagent_batches as router

    env.result.result, env.result.ai_messages = retrieval(name=tool_name)
    source = env.result.ai_messages[0]["artifact"]["knowledge_sources"]["sources"][0]
    expected_source = deepcopy(source)
    batch = await execute(env)
    assert env.owner == "user-1" and env.scope["dataset_ids"] == ["kb"]
    # Actual engine teardown/reopen; neither the worker nor provider can serve evidence.
    await env.service.stop()
    await close_engine()
    await init_engine_from_config(env.db)
    repo = SubagentBatchRepository(get_session_factory())
    source["text"] = "Provider content changed after retrieval"
    env.result.ai_messages = []
    assert "result_artifact" not in (await repo.list_items(batch["id"], user_id="user-1"))[0]
    assert await repo.list_items(batch["id"], user_id="other", include_result=True) is None
    monkeypatch.setattr(router, "get_current_user", AsyncMock(return_value="user-1"))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(subagent_batch_repo=repo, subagent_batches_available=False)))
    response = await router.export_batch_results.__wrapped__(thread_id="thread-1", batch_id=batch["id"], request=request)
    rows = [json.loads(line) async for line in response.body_iterator]
    row = rows[0]
    assert row["result"] == env.result.result
    assert row["result_artifact"]["knowledge_sources"]["sources"] == [expected_source]
    assert "Original evidence" in row["result_artifact"]["knowledge_sources"]["sources"][0]["text"]
    assert "execution_spec" not in row and "prompt" not in row


@pytest.mark.asyncio
async def test_real_subagent_graph_captures_artifact_for_durable_export(env, monkeypatch, tmp_path):
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.tools import StructuredTool

    from deerflow.config.app_config import AppConfig
    from deerflow.subagents.config import SubagentConfig

    # conftest stubs executor to break a circular import. Load the production
    # executor, keeping its actual graph, middleware, ToolNode and step capture.
    path = Path(__file__).parents[1] / "packages/harness/deerflow/subagents/executor.py"
    spec = importlib.util.spec_from_file_location("_batch_evidence_executor", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "graph"))
    content, messages = retrieval()
    artifact = messages[0]["artifact"]

    class Model(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    model = Model(messages=iter([AIMessage(content="Searching", tool_calls=[{"name": "knowledge_search", "args": {}, "id": "search"}])]))
    monkeypatch.setattr(module, "create_chat_model", lambda **kwargs: model)
    tool = StructuredTool.from_function(lambda: (content, artifact), name="knowledge_search", description="Offline captured evidence", response_format="content_and_artifact", return_direct=True)
    config = AppConfig.model_validate({"models": [{"name": "offline", "use": "langchain_openai:ChatOpenAI", "model": "offline"}], "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "summarization": {"enabled": False}})
    executor = module.SubagentExecutor(config=SubagentConfig(name="researcher", description="Research", skills=[]), tools=[tool], parent_model="offline", app_config=config, thread_id="thread-1", user_id="user-1")
    try:
        env.result = await executor._aexecute("Return evidence")
        assert env.result.status is module.SubagentStatus.COMPLETED, env.result.error
        assert env.result.result == content
        captured = [m for m in env.result.ai_messages if m["type"] == "tool"]
        assert captured[0]["artifact"] == artifact
        monkeypatch.setattr(batch_service, "SubagentStatus", module.SubagentStatus)
        batch = await execute(env)
        row = (await env.repo.list_items(batch["id"], user_id="user-1", include_result=True))[0]
        assert row["status"] == "succeeded"
        assert row["result_artifact"]["knowledge_sources"]["sources"] == artifact["knowledge_sources"]["sources"]
    finally:
        module._shutdown_isolated_subagent_loop()


@pytest.mark.parametrize("change", ["uncited", "unsupported-tool", "future-version", "invalid-id", "invalid-provider", "invalid-text", "invalid-locator", "overlong-name"])
def test_unrelated_or_invalid_evidence_is_not_persisted(change):
    from deerflow.community.ragflow.sources import durable_source_artifact

    content, messages = retrieval()
    source = messages[0]["artifact"]["knowledge_sources"]["sources"][0]
    if change == "uncited":
        content = "A report with no citations"
    elif change == "unsupported-tool":
        messages[0]["name"] = "arbitrary_tool"
    elif change == "future-version":
        messages[0]["artifact"]["knowledge_sources"]["version"] = 2
    elif change == "invalid-id":
        content = content.replace(source["id"], "invalid")
        source["id"] = "invalid"
    elif change == "invalid-provider":
        source["provider"] = "other"
    elif change == "invalid-text":
        source["text"] = None
    elif change == "invalid-locator":
        source["document_id"] = ""
    else:
        source["document_name"] = "x" * 513
    result = durable_source_artifact(messages, content, max_chars=1000)
    assert result is None or result["knowledge_sources"]["sources"] == []


@pytest.mark.parametrize("max_chars", [1, 1000, 1800, 10_000])
def test_evidence_budget_keeps_whole_records_and_reports_omissions(max_chars):
    from deerflow.community.ragflow.sources import durable_source_artifact

    content, messages = retrieval(text='Quoted "evidence" and 中文 ' * 200)
    original = deepcopy(messages)
    small_content, small_messages = retrieval(text="A small source fits")
    # Both citations occur in the report; a large early source cannot starve a small later one.
    result = durable_source_artifact(messages + small_messages, content + small_content, max_chars=max_chars)
    assert messages == original
    if result is None:
        assert max_chars == 1
        return
    assert len(json.dumps(result, ensure_ascii=False)) <= max_chars
    payload = result["knowledge_sources"]
    assert len(payload["sources"]) + payload["omitted_count"] == 2
    originals = [m["artifact"]["knowledge_sources"]["sources"][0] for m in messages + small_messages]
    assert all(source in originals for source in payload["sources"])
    if max_chars in (1000, 1800):
        assert payload["sources"] == [originals[1]]
        assert payload["omitted_count"] == 1


def test_forwarding_limit_counts_duplicate_omissions_once():
    from deerflow.community.ragflow.sources import cited_source_artifact, durable_source_artifact

    entries = [retrieval(text=f"Evidence {index}") for index in range(102)]
    content = "\n".join(entry[0] for entry in entries)
    messages = [message for entry in entries for message in entry[1]]
    result = durable_source_artifact(messages + messages, content, max_chars=100_000)
    assert len(result["knowledge_sources"]["sources"]) == 100
    assert result["knowledge_sources"]["omitted_count"] == 2
    # Ordinary task forwarding retains its existing artifact shape.
    assert "omitted_count" not in cited_source_artifact(messages, content)["knowledge_sources"]


@pytest.mark.asyncio
async def test_report_truncation_selects_only_complete_stored_citations(env):
    content, messages = retrieval()
    env.service._config = SubagentBatchesConfig(max_result_chars=1000, result_preview_max_chars=64)
    env.result.result = "x" * 1100 + content
    env.result.ai_messages = messages
    batch = await execute(env)
    row = (await env.repo.list_items(batch["id"], user_id="user-1", include_result=True))[0]
    assert row["result"] == "x" * 1000 and row["result_truncated"] is True
    assert row["result_artifact"] is None


@pytest.mark.asyncio
async def test_plain_results_keep_nullable_evidence(env):
    batch = await execute(env)
    row = (await env.repo.list_items(batch["id"], user_id="user-1", include_result=True))[0]
    assert row["result"] == "plain report" and row["result_artifact"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "cancel-running", "stale-lease", "failure", "retry"])
async def test_fenced_or_failed_attempts_cannot_publish_evidence(env, action):
    content, messages = retrieval()
    from deerflow.community.ragflow.sources import durable_source_artifact

    artifact = durable_source_artifact(messages, content, max_chars=1000)
    batch = await env.repo.create_batch(
        batch_id="batch",
        user_id="user-1",
        thread_id="thread-1",
        run_id=None,
        tool_call_id=None,
        submission_key="key",
        title="R",
        subagent_type="general-purpose",
        items=[{"key": "item", "prompt": "Research"}],
        max_live_items=1,
        max_running_items=1,
        max_attempts=2 if action == "stale-lease" else 1,
        execution_spec={},
    )
    now = datetime.now(UTC)
    item = (await env.repo.claim_items(now=now, lease_owner="worker", lease_seconds=60, limit=1))[0]
    if action == "cancel-running":
        assert await env.repo.mark_item_running(item["id"], lease_owner="worker", now=now)
    if action in {"cancel", "cancel-running"}:
        await env.repo.cancel_batch(batch["id"], user_id="user-1")
    if action == "stale-lease":
        reclaimed = await env.repo.claim_items(now=now + timedelta(seconds=61), lease_owner="replacement", lease_seconds=60, limit=1)
        assert len(reclaimed) == 1 and reclaimed[0]["attempt"] == 2
    accepted = await env.repo.finalize_item(
        item["id"],
        lease_owner="worker",
        succeeded=action not in {"failure", "retry"},
        result=content,
        result_preview=content[:64],
        result_truncated=False,
        result_artifact=artifact,
        error="failed",
        stop_reason=None,
        token_usage=None,
        model_name=None,
        completed_at=now,
    )
    assert accepted is (action not in {"cancel", "cancel-running", "stale-lease"})
    if action == "retry":
        # A legacy/external failure row may have old evidence; explicit retry clears it.
        from deerflow.persistence.subagent_batches.model import SubagentBatchItemRow

        async with get_session_factory()() as session:
            stored = await session.get(SubagentBatchItemRow, item["id"])
            stored.result_artifact = artifact
            await session.commit()
        assert await env.repo.retry_item(batch["id"], item["id"], user_id="other") is None
        await env.repo.retry_item(batch["id"], item["id"], user_id="user-1")
    row = (await env.repo.list_items(batch["id"], user_id="user-1", include_result=True))[0]
    assert row["result_artifact"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("user,permission,thread,status", [("user-1", True, "thread-1", 200), ("user-1", False, "thread-1", 403), ("other", True, "thread-1", 404), ("user-1", True, "other-thread", 404), (None, True, "thread-1", 401)])
async def test_http_export_checks_permission_thread_and_batch_owner(env, monkeypatch, user, permission, thread, status):
    import httpx
    from fastapi import FastAPI

    from app.gateway import deps
    from app.gateway.authz import AuthContext
    from app.gateway.routers import subagent_batches as router

    env.result.result, env.result.ai_messages = retrieval()
    batch = await execute(env)
    app = FastAPI()
    app.include_router(router.router)
    app.state.subagent_batch_repo = env.repo

    @app.middleware("http")
    async def auth_boundary(request, call_next):
        request.state.auth = AuthContext(user=SimpleNamespace(id=user) if user else None, permissions=["threads:read"] if permission else [])
        return await call_next(request)

    # Authentication and the thread store are controlled; the actual permission decorator,
    # route, SQL batch ownership, streaming and serialization remain production code.
    monkeypatch.setattr(deps, "get_thread_store", lambda request: SimpleNamespace(check_access=AsyncMock(return_value=thread == "thread-1")))
    monkeypatch.setattr(router, "get_current_user", AsyncMock(return_value=user))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/threads/{thread}/subagent-batches/{batch['id']}/results.jsonl")
    assert response.status_code == status
    if status == 200:
        row = json.loads(response.text)
        assert row["result_artifact"]["knowledge_sources"]["sources"][0]["text"] == "Original evidence"
    else:
        assert "Original evidence" not in response.text
