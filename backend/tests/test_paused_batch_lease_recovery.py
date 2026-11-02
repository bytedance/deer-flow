"""Paused batches still reconcile abandoned attempts without starting new work."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from _router_auth_helpers import make_authed_test_app
from fastapi import FastAPI

from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.routers import subagent_batches
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.subagent_batches import SubagentBatchRepository
from deerflow.persistence.subagent_batches.model import SubagentBatchItemRow
from deerflow.persistence.thread_meta import ThreadMetaRepository
from deerflow.subagents.batch_service import SubagentBatchService

_URL = "/api/threads/thread-1/subagent-batches/batch-1"


async def _open_database(app: FastAPI, tmp_path: Path) -> tuple[SubagentBatchRepository, SubagentBatchService]:
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sessions = get_session_factory()
    app.state.subagent_batch_repo = SubagentBatchRepository(sessions)
    app.state.thread_store = ThreadMetaRepository(sessions)
    service = SubagentBatchService(
        repository=app.state.subagent_batch_repo,
        config=SubagentBatchesConfig(lease_seconds=10),
        runtime_config=SubagentRuntimeConfig(),
    )
    # No executor is needed: a paused batch must never dispatch its items.
    service._execute_item = AsyncMock()
    app.state.subagent_batch_service = service
    return app.state.subagent_batch_repo, service


@pytest_asyncio.fixture
async def api(tmp_path):
    # Synthetic session identity; routing, owner checks and SQL are real.
    user = SimpleNamespace(id="user-1", system_role="user")
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
    app.include_router(subagent_batches.router)

    @app.middleware("http")
    async def session_source(request, call_next):
        request.state.auth_source = AUTH_SOURCE_SESSION
        return await call_next(request)

    try:
        await _open_database(app, tmp_path)
        await app.state.thread_store.create("thread-1", user_id="user-1")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield app, client, tmp_path
    finally:
        await close_engine()


async def _create(repo: SubagentBatchRepository, *, count: int, max_attempts: int) -> None:
    await repo.create_batch(
        batch_id="batch-1",
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
        tool_call_id="call-1",
        submission_key="run-1:call-1",
        title="Paused research",
        subagent_type="general-purpose",
        items=[{"key": f"item-{index}", "prompt": f"Process {index}"} for index in range(count)],
        max_live_items=1,
        max_running_items=1,
        max_attempts=max_attempts,
        execution_spec={},
    )


async def _finish(repo: SubagentBatchRepository, item: dict, *, owner: str, now: datetime) -> None:
    assert await repo.finalize_item(
        item["id"],
        lease_owner=owner,
        succeeded=True,
        result="Saved report",
        result_preview="Saved report",
        result_truncated=False,
        error=None,
        stop_reason=None,
        token_usage=None,
        model_name=None,
        completed_at=now,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("max_attempts", [1, 2])
async def test_paused_batch_recovers_expired_item_without_dispatch_after_restart(api, max_attempts):
    app, client, tmp_path = api
    repo = app.state.subagent_batch_repo
    await _create(repo, count=2, max_attempts=max_attempts)
    now = datetime.now(UTC)
    lost = (await repo.claim_items(now=now, lease_owner="lost-worker", lease_seconds=10, limit=1))[0]
    assert await repo.mark_item_running(lost["id"], lease_owner="lost-worker", now=now)
    assert (await client.post(f"{_URL}/pause")).json()["status"] == "paused"

    # Reopen the same file, with no heartbeat/finalization from the lost worker.
    await close_engine()
    repo, service = await _open_database(app, tmp_path)
    await service.run_once(now=now + timedelta(seconds=10))
    before = (await client.get(f"{_URL}/items")).json()
    assert before[0]["status"] == "running"  # Equality is still a live lease.

    await service.run_once(now=now + timedelta(seconds=11))
    response = await client.get(f"{_URL}/items")
    assert response.status_code == 200
    items = response.json()
    assert [item["status"] for item in items] == ["failed" if max_attempts == 1 else "queued", "pending"]
    assert items[0]["attempt"] == 1
    async with get_session_factory()() as session:
        stored = await session.get(SubagentBatchItemRow, lost["id"])
        assert stored.lease_owner is None
        assert stored.lease_expires_at is None
    assert (await client.get(_URL)).json()["status"] == "paused"
    service._execute_item.assert_not_awaited()

    if max_attempts == 1:
        retried = await client.post(f"{_URL}/items/{lost['id']}/retry")
        assert retried.status_code == 200
        assert retried.json()["attempt"] == 0
        await service.run_once(now=now + timedelta(seconds=12))
        assert (await client.get(_URL)).json()["status"] == "paused"
        service._execute_item.assert_not_awaited()

    # Explicit resume is still required to claim retryable work.
    assert (await client.post(f"{_URL}/resume")).json()["status"] == "queued"
    resumed = (await repo.claim_items(now=now + timedelta(seconds=13), lease_owner="new-worker", lease_seconds=10, limit=1))[0]
    assert resumed["id"] == lost["id"]
    assert resumed["attempt"] == (1 if max_attempts == 1 else 2)
    await _finish(repo, resumed, owner="new-worker", now=now + timedelta(seconds=14))
    exported = await client.get(f"{_URL}/results.jsonl")
    rows = [json.loads(line) for line in exported.text.splitlines()]
    assert rows[0]["result"] == "Saved report"
    assert rows[1]["status"] == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("live_completion", [False, True])
@pytest.mark.parametrize("succeeded_sibling", [False, True])
async def test_last_paused_item_reaches_terminal_status_on_completion_or_expiry(api, live_completion, succeeded_sibling):
    app, client, _ = api
    repo = app.state.subagent_batch_repo
    await _create(repo, count=2 if succeeded_sibling else 1, max_attempts=1)
    now = datetime.now(UTC)
    item = (await repo.claim_items(now=now, lease_owner="worker", lease_seconds=10, limit=1))[0]
    if succeeded_sibling:
        await _finish(repo, item, owner="worker", now=now)
        item = (await repo.claim_items(now=now, lease_owner="worker", lease_seconds=10, limit=1))[0]
    assert (await client.post(f"{_URL}/pause")).json()["status"] == "paused"
    if live_completion:
        await _finish(repo, item, owner="worker", now=now + timedelta(seconds=1))
    else:
        await app.state.subagent_batch_service.run_once(now=now + timedelta(seconds=11))

    batch = (await client.get(_URL)).json()
    assert batch["status"] == ("completed" if live_completion or succeeded_sibling else "failed")
    assert batch["completed_at"] is not None
    assert batch["counts"]["leased"] == batch["counts"]["running"] == 0
    app.state.subagent_batch_service._execute_item.assert_not_awaited()
