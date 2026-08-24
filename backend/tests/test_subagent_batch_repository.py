from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.subagent_batches import SubagentBatchRepository


@pytest_asyncio.fixture(autouse=True)
async def _close_engine() -> None:
    yield
    await close_engine()


async def _repo(tmp_path) -> SubagentBatchRepository:
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None
    return SubagentBatchRepository(sf)


async def _create(
    repo: SubagentBatchRepository,
    *,
    count: int = 4,
    max_live: int = 2,
    max_running: int = 1,
    max_attempts: int = 2,
) -> dict:
    return await repo.create_batch(
        batch_id="batch-1",
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
        tool_call_id="call-1",
        submission_key="run-1:call-1",
        title="Research records",
        subagent_type="general-purpose",
        items=[{"key": f"item-{i}", "prompt": f"Process {i}"} for i in range(count)],
        max_live_items=max_live,
        max_running_items=max_running,
        max_attempts=max_attempts,
        execution_spec={
            "subagent_config": {
                "name": "general-purpose",
                "description": "test",
                "system_prompt": "private instructions",
            },
            "authz_attributes": {"tenant": "private-tenant"},
        },
    )


@pytest.mark.asyncio
async def test_claim_separates_total_live_leased_and_running(tmp_path) -> None:
    repo = await _repo(tmp_path)
    created = await _create(repo)
    assert created["counts"]["pending"] == 4

    now = datetime.now(UTC)
    claimed = await repo.claim_items(now=now, lease_owner="worker-1", lease_seconds=60, limit=10)
    assert len(claimed) == 1
    assert claimed[0]["status"] == "leased"

    batch = await repo.get_batch("batch-1", user_id="user-1")
    assert batch is not None
    assert batch["counts"] == {
        "pending": 2,
        "queued": 1,
        "leased": 1,
        "running": 0,
        "succeeded": 0,
        "failed": 0,
        "cancelled": 0,
    }
    assert await repo.mark_item_running(claimed[0]["id"], lease_owner="worker-1", now=now)

    while_full = await repo.claim_items(
        now=now + timedelta(seconds=1),
        lease_owner="worker-2",
        lease_seconds=60,
        limit=10,
    )
    assert while_full == []


@pytest.mark.asyncio
async def test_expired_lease_is_recovered_with_stable_item_identity(tmp_path) -> None:
    repo = await _repo(tmp_path)
    await _create(repo, count=1, max_live=1, max_running=1)
    now = datetime.now(UTC)
    first = await repo.claim_items(now=now, lease_owner="worker-1", lease_seconds=30, limit=1)

    reclaimed = await repo.claim_items(
        now=now + timedelta(seconds=31),
        lease_owner="worker-2",
        lease_seconds=30,
        limit=1,
    )
    assert len(reclaimed) == 1
    assert reclaimed[0]["id"] == first[0]["id"]
    assert reclaimed[0]["item_key"] == "item-0"
    assert reclaimed[0]["attempt"] == 2


@pytest.mark.asyncio
async def test_finalize_retries_then_terminalizes_and_completes_batch(tmp_path) -> None:
    repo = await _repo(tmp_path)
    await _create(repo, count=1, max_live=1, max_running=1)
    now = datetime.now(UTC)
    first = (await repo.claim_items(now=now, lease_owner="worker-1", lease_seconds=60, limit=1))[0]
    await repo.finalize_item(
        first["id"],
        lease_owner="worker-1",
        succeeded=False,
        result=None,
        result_preview=None,
        result_truncated=False,
        error="temporary",
        stop_reason=None,
        token_usage=None,
        model_name="model-a",
        completed_at=now,
    )
    item = (await repo.list_items("batch-1", user_id="user-1"))[0]
    assert item["status"] == "queued"

    second = (await repo.claim_items(now=now + timedelta(seconds=1), lease_owner="worker-2", lease_seconds=60, limit=1))[0]
    await repo.finalize_item(
        second["id"],
        lease_owner="worker-2",
        succeeded=True,
        result="done",
        result_preview="done",
        result_truncated=False,
        error=None,
        stop_reason=None,
        token_usage={"total_tokens": 12},
        model_name="model-a",
        completed_at=now + timedelta(seconds=2),
    )
    batch = await repo.get_batch("batch-1", user_id="user-1")
    assert batch is not None
    assert batch["status"] == "completed"
    assert batch["counts"]["succeeded"] == 1


@pytest.mark.asyncio
async def test_pause_resume_cancel_and_owner_scope(tmp_path) -> None:
    repo = await _repo(tmp_path)
    await _create(repo, count=2, max_live=2, max_running=1)
    paused = await repo.pause_batch("batch-1", user_id="user-1")
    assert paused is not None and paused["status"] == "paused"
    assert await repo.claim_items(now=datetime.now(UTC), lease_owner="worker", lease_seconds=60, limit=1) == []
    resumed = await repo.resume_batch("batch-1", user_id="user-1")
    assert resumed is not None and resumed["status"] == "queued"
    cancelled = await repo.cancel_batch("batch-1", user_id="user-1")
    assert cancelled is not None and cancelled["status"] == "cancelled"
    assert cancelled["counts"]["cancelled"] == 2
    assert await repo.get_batch("batch-1", user_id="other") is None


@pytest.mark.asyncio
async def test_cancel_terminalizes_in_flight_items_and_fences_stale_completion(tmp_path) -> None:
    repo = await _repo(tmp_path)
    await _create(repo, count=1, max_live=1, max_running=1)
    now = datetime.now(UTC)
    claimed = (await repo.claim_items(now=now, lease_owner="worker-1", lease_seconds=60, limit=1))[0]
    assert await repo.mark_item_running(claimed["id"], lease_owner="worker-1", now=now)

    cancelled = await repo.cancel_batch("batch-1", user_id="user-1")

    assert cancelled is not None
    assert cancelled["counts"]["cancelled"] == 1
    item = (await repo.list_items("batch-1", user_id="user-1"))[0]
    assert item["status"] == "cancelled"
    assert not await repo.finalize_item(
        claimed["id"],
        lease_owner="worker-1",
        succeeded=True,
        result="late result",
        result_preview="late result",
        result_truncated=False,
        error=None,
        stop_reason=None,
        token_usage=None,
        model_name="model-a",
        completed_at=now + timedelta(seconds=1),
    )


@pytest.mark.asyncio
async def test_executor_admission_failure_requeues_without_consuming_attempt(tmp_path) -> None:
    repo = await _repo(tmp_path)
    await _create(repo, count=1, max_live=1, max_running=1)
    now = datetime.now(UTC)
    first = (await repo.claim_items(now=now, lease_owner="worker-1", lease_seconds=60, limit=1))[0]
    assert first["attempt"] == 1

    assert await repo.requeue_item_after_admission_failure(
        first["id"],
        lease_owner="worker-1",
        error="Process-wide subagent capacity is full",
        now=now,
    )
    queued = (await repo.list_items("batch-1", user_id="user-1"))[0]
    assert queued["status"] == "queued"
    assert queued["attempt"] == 0

    second = (await repo.claim_items(now=now + timedelta(seconds=1), lease_owner="worker-2", lease_seconds=60, limit=1))[0]
    assert second["attempt"] == 1


@pytest.mark.asyncio
async def test_all_failed_items_mark_batch_failed(tmp_path) -> None:
    repo = await _repo(tmp_path)
    await _create(repo, count=1, max_live=1, max_running=1, max_attempts=1)
    now = datetime.now(UTC)
    item = (await repo.claim_items(now=now, lease_owner="worker-1", lease_seconds=60, limit=1))[0]

    assert await repo.finalize_item(
        item["id"],
        lease_owner="worker-1",
        succeeded=False,
        result=None,
        result_preview=None,
        result_truncated=False,
        error="permanent",
        stop_reason=None,
        token_usage=None,
        model_name="model-a",
        completed_at=now,
    )
    batch = await repo.get_batch("batch-1", user_id="user-1")
    assert batch is not None
    assert batch["status"] == "failed"


@pytest.mark.asyncio
async def test_public_projections_omit_execution_context_and_full_results(tmp_path) -> None:
    repo = await _repo(tmp_path)
    created = await _create(repo, count=1, max_live=1, max_running=1)
    assert "execution_spec" not in created
    assert "user_id" not in created
    assert "submission_key" not in created
    assert "run_id" not in created
    assert "tool_call_id" not in created

    now = datetime.now(UTC)
    item = (await repo.claim_items(now=now, lease_owner="worker-1", lease_seconds=60, limit=1))[0]
    assert await repo.finalize_item(
        item["id"],
        lease_owner="worker-1",
        succeeded=True,
        result="full private result",
        result_preview="preview",
        result_truncated=False,
        error=None,
        stop_reason=None,
        token_usage=None,
        model_name="model-a",
        completed_at=now,
    )

    public_batch = await repo.get_batch("batch-1", user_id="user-1")
    assert public_batch is not None
    assert "execution_spec" not in public_batch
    public_item = (await repo.list_items("batch-1", user_id="user-1"))[0]
    assert public_item["result_preview"] == "preview"
    assert "result" not in public_item
    assert "lease_owner" not in public_item
    export_item = (await repo.list_items("batch-1", user_id="user-1", include_result=True))[0]
    assert export_item["result"] == "full private result"


@pytest.mark.asyncio
async def test_duplicate_submission_key_returns_original_batch(tmp_path) -> None:
    repo = await _repo(tmp_path)
    original = await _create(repo, count=1)
    duplicate = await repo.create_batch(
        batch_id="batch-2",
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
        tool_call_id="call-1",
        submission_key="run-1:call-1",
        title="Duplicate retry",
        subagent_type="general-purpose",
        items=[{"key": "different", "prompt": "Must not be inserted"}],
        max_live_items=1,
        max_running_items=1,
        max_attempts=2,
        execution_spec={"subagent_config": {"name": "general-purpose", "description": "test"}},
    )

    assert duplicate["id"] == original["id"] == "batch-1"
    items = await repo.list_items("batch-1", user_id="user-1", include_prompt=True)
    assert items is not None
    assert [item["item_key"] for item in items] == ["item-0"]
