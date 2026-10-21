import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import event, update

from app.gateway.app import create_app
from app.gateway.routers import subagent_batches
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.subagent_batches import SubagentBatchRepository
from deerflow.persistence.subagent_batches.model import SubagentBatchItemRow


def _batch(**overrides):
    return {
        "id": "batch-1",
        "user_id": "user-1",
        "thread_id": "thread-1",
        "status": "running",
        "total_items": 2,
        "counts": {"running": 1, "pending": 1},
        **overrides,
    }


class Repository:
    def __init__(self) -> None:
        self.batch = _batch()
        self.items = [
            {"id": "item-1", "batch_id": "batch-1", "item_key": "one", "status": "succeeded", "result": "done"},
            {"id": "item-2", "batch_id": "batch-1", "item_key": "two", "status": "failed", "error": "bad"},
        ]
        self.include_result_calls = []
        self.limits = []

    async def get_batch(self, batch_id, *, user_id):
        if batch_id != self.batch["id"] or user_id != self.batch["user_id"]:
            return None
        return self.batch

    async def list_by_thread(self, thread_id, *, user_id, limit):
        assert (thread_id, user_id, limit) == ("thread-1", "user-1", 20)
        return [self.batch]

    async def list_items(self, batch_id, *, user_id, offset=0, limit=100, status=None, include_result=False):
        assert batch_id == "batch-1" and user_id == "user-1"
        self.include_result_calls.append(include_result)
        self.limits.append(limit)
        values = self.items
        if status is not None:
            values = [item for item in values if item["status"] == status]
        return values[offset : offset + limit]


def _request(repo, *, available=True, service=None):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                subagent_batch_repo=repo,
                subagent_batch_service=service,
                subagent_batches_available=available,
            )
        )
    )


def test_gateway_mounts_subagent_batch_routes() -> None:
    paths = {route.path for route in create_app().routes}
    assert "/api/threads/{thread_id}/subagent-batches" in paths
    assert "/api/threads/{thread_id}/subagent-batches/{batch_id}/items" in paths
    assert "/api/threads/{thread_id}/subagent-batches/{batch_id}/results.jsonl" in paths


@pytest.mark.asyncio
async def test_list_and_detail_are_owner_scoped(monkeypatch) -> None:
    repo = Repository()
    request = _request(repo)
    monkeypatch.setattr(subagent_batches, "get_current_user", AsyncMock(return_value="user-1"))

    listed = await subagent_batches.list_batches.__wrapped__(thread_id="thread-1", request=request, limit=20)
    detail = await subagent_batches.get_batch.__wrapped__(thread_id="thread-1", batch_id="batch-1", request=request)

    assert listed == [repo.batch]
    assert detail == repo.batch

    with pytest.raises(HTTPException) as cross_thread:
        await subagent_batches.get_batch.__wrapped__(thread_id="thread-2", batch_id="batch-1", request=request)
    assert cross_thread.value.status_code == 404


@pytest.mark.asyncio
async def test_item_list_route_never_reads_full_results(monkeypatch, tmp_path) -> None:
    # The workspace polls this route every 2 s; only the JSONL export may pay
    # for full reports, evidence JSON and prompts.
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        repo = SubagentBatchRepository(get_session_factory())
        await repo.create_batch(
            batch_id="batch-1",
            user_id="user-1",
            thread_id="thread-1",
            run_id=None,
            tool_call_id=None,
            submission_key="submission-1",
            title="Research",
            subagent_type="general-purpose",
            items=[{"key": "one", "prompt": "private prompt"}],
            max_live_items=1,
            max_running_items=1,
            max_attempts=1,
            execution_spec={},
        )
        async with get_session_factory()() as session:
            await session.execute(update(SubagentBatchItemRow).where(SubagentBatchItemRow.batch_id == "batch-1").values(status="succeeded", result="full report", result_artifact={"knowledge_sources": {}}, result_preview="preview"))
            await session.commit()
        monkeypatch.setattr(subagent_batches, "get_current_user", AsyncMock(return_value="user-1"))
        statements = []
        sync_engine = get_engine().sync_engine
        listener = lambda *args, **kwargs: statements.append(args[2])  # noqa: E731
        event.listen(sync_engine, "before_cursor_execute", listener)
        try:
            items = await subagent_batches.list_batch_items.__wrapped__(thread_id="thread-1", batch_id="batch-1", request=_request(repo), offset=0, limit=100, status=None)
        finally:
            event.remove(sync_engine, "before_cursor_execute", listener)
    finally:
        await close_engine()

    assert [item["result_preview"] for item in items] == ["preview"]
    assert not {"prompt", "result", "result_artifact"} & items[0].keys()
    item_columns = set().union(*(re.findall(r"subagent_batch_items\.(\w+)", statement) for statement in statements if "FROM subagent_batch_items" in statement))
    assert "result_preview" in item_columns
    assert not {"prompt", "result", "result_artifact"} & item_columns


@pytest.mark.asyncio
async def test_cancel_requires_running_worker_and_exact_owner(monkeypatch) -> None:
    repo = Repository()
    service = AsyncMock()
    service.cancel_batch.return_value = _batch(status="cancelled")
    monkeypatch.setattr(subagent_batches, "get_current_user", AsyncMock(return_value="user-1"))

    result = await subagent_batches.cancel_batch.__wrapped__(
        thread_id="thread-1",
        batch_id="batch-1",
        request=_request(repo, service=service),
    )
    assert result["status"] == "cancelled"
    service.cancel_batch.assert_awaited_once_with(batch_id="batch-1", user_id="user-1")

    with pytest.raises(HTTPException) as unavailable:
        await subagent_batches.cancel_batch.__wrapped__(
            thread_id="thread-1",
            batch_id="batch-1",
            request=_request(repo, available=False, service=service),
        )
    assert unavailable.value.status_code == 503


@pytest.mark.asyncio
async def test_jsonl_export_streams_item_results(monkeypatch) -> None:
    repo = Repository()
    monkeypatch.setattr(subagent_batches, "get_current_user", AsyncMock(return_value="user-1"))

    response = await subagent_batches.export_batch_results.__wrapped__(
        thread_id="thread-1",
        batch_id="batch-1",
        request=_request(repo),
    )
    payload = b"".join([chunk async for chunk in response.body_iterator]).decode()
    rows = [json.loads(line) for line in payload.splitlines()]

    assert [row["id"] for row in rows] == ["item-1", "item-2"]
    assert rows[0]["result"] == "done"
    assert repo.include_result_calls and all(repo.include_result_calls)


@pytest.mark.asyncio
async def test_jsonl_export_reads_full_results_in_small_pages(monkeypatch) -> None:
    # A full row can hold max_result_chars of report plus as much evidence
    # JSON, up to 2M characters at the config ceiling; 500-row pages
    # materialized hundreds of MB per request before the first line streamed.
    repo = Repository()
    repo.items = [{"id": f"item-{index}", "batch_id": "batch-1", "status": "succeeded", "result": str(index)} for index in range(25)]
    monkeypatch.setattr(subagent_batches, "get_current_user", AsyncMock(return_value="user-1"))

    response = await subagent_batches.export_batch_results.__wrapped__(
        thread_id="thread-1",
        batch_id="batch-1",
        request=_request(repo),
    )
    payload = b"".join([chunk async for chunk in response.body_iterator]).decode()

    assert [json.loads(line)["id"] for line in payload.splitlines()] == [f"item-{index}" for index in range(25)]
    assert max(repo.limits) <= 10
    assert len(repo.limits) > 2
