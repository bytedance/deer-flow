import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.gateway.app import create_app
from app.gateway.routers import subagent_batches


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
