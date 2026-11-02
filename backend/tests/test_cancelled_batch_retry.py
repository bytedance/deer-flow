"""Retrying a failed item never reopens a cancelled batch or runs its work."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from _router_auth_helpers import make_authed_test_app

from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.routers import subagent_batches
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.subagent_batches import SubagentBatchRepository
from deerflow.persistence.thread_meta import ThreadMetaRepository
from deerflow.subagents.batch_service import SubagentBatchService

_URL = "/api/threads/thread-1/subagent-batches/batch-1"


@pytest_asyncio.fixture
async def api(tmp_path):
    # Synthetic session identity; routing, owner checks, SQL and claiming are real.
    user = SimpleNamespace(id="user-1", system_role="user")
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
    app.include_router(subagent_batches.router)

    @app.middleware("http")
    async def session_source(request, call_next):
        request.state.auth_source = AUTH_SOURCE_SESSION
        return await call_next(request)

    try:
        await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
        sessions = get_session_factory()
        app.state.subagent_batch_repo = SubagentBatchRepository(sessions)
        app.state.thread_store = ThreadMetaRepository(sessions)
        service = SubagentBatchService(
            repository=app.state.subagent_batch_repo,
            config=SubagentBatchesConfig(lease_seconds=10),
            runtime_config=SubagentRuntimeConfig(),
        )
        # No executor is needed: a cancelled batch must never dispatch its items.
        service._execute_item = AsyncMock()
        app.state.subagent_batch_service = service
        app.state.subagent_batches_available = True
        await app.state.thread_store.create("thread-1", user_id="user-1")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield app, client
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_retry_in_cancelled_batch_is_rejected_and_never_dispatched(api):
    app, client = api
    repo = app.state.subagent_batch_repo
    service = app.state.subagent_batch_service
    await repo.create_batch(
        batch_id="batch-1",
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
        tool_call_id="call-1",
        submission_key="run-1:call-1",
        title="Cancelled research",
        subagent_type="general-purpose",
        items=[{"key": f"item-{index}", "prompt": f"Process {index}"} for index in range(3)],
        max_live_items=1,
        max_running_items=1,
        max_attempts=1,
        execution_spec={},
    )
    now = datetime.now(UTC)
    failed = (await repo.claim_items(now=now, lease_owner="worker-1", lease_seconds=10, limit=1))[0]
    assert await repo.finalize_item(
        failed["id"],
        lease_owner="worker-1",
        succeeded=False,
        result=None,
        result_preview=None,
        result_truncated=False,
        error="permanent",
        stop_reason=None,
        token_usage=None,
        model_name=None,
        completed_at=now,
    )
    assert (await client.post(f"{_URL}/cancel")).json()["status"] == "cancelled"

    retried = await client.post(f"{_URL}/items/{failed['id']}/retry")

    assert retried.status_code == 409
    assert retried.json()["detail"] == "Only failed items of a batch that is not cancelled can be retried"
    await service.run_once(now=now + timedelta(seconds=1))
    service._execute_item.assert_not_awaited()
    batch = (await client.get(_URL)).json()
    assert batch["status"] == "cancelled"
    assert batch["completed_at"] is not None
    items = (await client.get(f"{_URL}/items")).json()
    assert [(item["status"], item["error"]) for item in items] == [
        ("failed", "permanent"),
        ("cancelled", "Cancelled by user"),
        ("cancelled", "Cancelled by user"),
    ]
