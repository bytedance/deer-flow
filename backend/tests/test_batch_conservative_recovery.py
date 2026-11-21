"""Opted-in recovery never replays an attempt that may have started."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.schema import DropSchema

from deerflow.config.database_config import DatabaseConfig
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.persistence.engine import close_engine, get_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.subagent_batches import SubagentBatchRepository
from deerflow.persistence.subagent_batches.model import SubagentBatchRow


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def repo(tmp_path, request):
    config = DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path))
    if request.param == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI")
        config = DatabaseConfig(backend="postgres", postgres_url=uri, postgres_schema="batch_recovery_" + uuid4().hex)
    await init_engine_from_config(config)
    try:
        yield SubagentBatchRepository(get_session_factory())
    finally:
        if config.backend == "postgres":
            async with get_engine().begin() as connection:
                await connection.execute(DropSchema(config.postgres_schema, cascade=True))
        await close_engine()


async def create(repo, *, policy="conservative", attempts=3, dependent=True, independent=False):
    items = [{"key": "write", "prompt": "Write one record"}]
    if dependent:
        items.append({"key": "after", "prompt": "Use the record", "depends_on": ["write"]})
    if independent:
        items.append({"key": "independent", "prompt": "Unrelated work"})
    return await repo.create_batch(
        batch_id="batch",
        user_id="owner",
        thread_id="thread",
        run_id="run",
        tool_call_id="call",
        submission_key="run:call",
        title="Recovery",
        subagent_type="general-purpose",
        items=items,
        max_live_items=2,
        max_running_items=1,
        max_attempts=attempts,
        execution_spec={},
        continuation={"prompt": "Summarize"},
        recovery_policy=policy,
    )


async def claim(repo, now, owner="worker"):
    return await repo.claim_items(now=now, lease_owner=owner, lease_seconds=10, limit=2)


async def finish(repo, item, now, *, owner="worker", succeeded=True):
    return await repo.finalize_item(
        item["id"],
        lease_owner=owner,
        succeeded=succeeded,
        result="saved" if succeeded else None,
        result_preview="saved" if succeeded else None,
        result_truncated=False,
        error=None if succeeded else "known failure",
        stop_reason=None,
        token_usage=None,
        model_name=None,
        completed_at=now,
    )


def test_recovery_policy_is_opt_in_and_validated():
    assert SubagentBatchesConfig().recovery_policy == "retry"
    assert SubagentBatchesConfig(recovery_policy="conservative").recovery_policy == "conservative"
    with pytest.raises(ValidationError):
        SubagentBatchesConfig(recovery_policy="invalid")


@pytest.mark.asyncio
@pytest.mark.parametrize("attempts", [1, 3])
@pytest.mark.parametrize("mark_running", [False, True])
async def test_dispatched_expiry_stays_unknown_and_blocks_dependencies_and_followup(repo, attempts, mark_running):
    await create(repo, attempts=attempts)
    now = datetime.now(UTC)
    item = (await claim(repo, now))[0]
    assert item["attempt_id"]
    assert await repo.mark_item_dispatch_started(item["id"], lease_owner="worker", now=now)
    if mark_running:
        assert await repo.mark_item_running(item["id"], lease_owner="worker", now=now)
    assert await claim(repo, now + timedelta(seconds=11), "replacement") == []
    unknown, dependent = await repo.list_items("batch", user_id="owner")
    assert unknown["status"] == "outcome_unknown"
    assert unknown["attempt_id"] == item["attempt_id"]
    assert unknown["attempt"] == 1 and unknown["dispatch_started_at"] is not None
    assert unknown["completed_at"] is None
    assert dependent["status"] == "pending" and dependent["attempt"] == 0
    assert (await repo.get_batch("batch", user_id="owner"))["counts"]["outcome_unknown"] == 1
    assert await repo.claim_continuations(now=now + timedelta(seconds=11), lease_owner="followup", lease_seconds=10) == []
    assert await repo.retry_item("batch", item["id"], user_id="owner") is None
    assert not await finish(repo, item, now + timedelta(seconds=12))
    await repo.pause_batch("batch", user_id="owner")
    await repo.resume_batch("batch", user_id="owner")
    assert await claim(repo, now + timedelta(seconds=100), "replacement") == []


@pytest.mark.asyncio
async def test_undispatched_expiry_retries_with_new_attempt_identity(repo):
    await create(repo)
    now = datetime.now(UTC)
    first = (await claim(repo, now))[0]
    second = (await claim(repo, now + timedelta(seconds=11), "replacement"))[0]
    assert second["id"] == first["id"] and second["attempt"] == 2
    assert second["attempt_id"] != first["attempt_id"]
    assert second["dispatch_started_at"] is None
    assert not await repo.mark_item_dispatch_started(first["id"], lease_owner="worker", now=now)


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", [None, "retry"])
async def test_legacy_and_retry_policy_preserve_automatic_recovery(repo, policy):
    await create(repo, policy="retry")
    if policy is None:
        async with repo._sf() as session:
            await session.execute(update(SubagentBatchRow).values(recovery_policy=None))
            await session.commit()
    now = datetime.now(UTC)
    first = (await claim(repo, now))[0]
    assert first["batch"]["recovery_policy"] == "retry"
    assert await repo.mark_item_dispatch_started(first["id"], lease_owner="worker", now=now)
    second = (await claim(repo, now + timedelta(seconds=11), "replacement"))[0]
    assert second["attempt"] == 2 and second["dispatch_started_at"] is None


@pytest.mark.asyncio
async def test_committed_success_survives_recovery_and_unblocks_dependency(repo):
    await create(repo)
    now = datetime.now(UTC)
    first = (await claim(repo, now))[0]
    assert await repo.mark_item_dispatch_started(first["id"], lease_owner="worker", now=now)
    assert await finish(repo, first, now)
    saved_items = await repo.list_items("batch", user_id="owner", include_result=True)
    saved_batch = await repo.get_batch("batch", user_id="owner")
    # A commit can succeed before its acknowledgement reaches the supervisor.
    assert not await repo.mark_item_outcome_unknown(first["id"], lease_owner="worker", error="commit acknowledgement lost", now=now)
    assert await repo.list_items("batch", user_id="owner", include_result=True) == saved_items
    assert await repo.get_batch("batch", user_id="owner") == saved_batch
    following = await claim(repo, now + timedelta(seconds=11), "replacement")
    assert [item["item_key"] for item in following] == ["after"]
    saved = (await repo.list_items("batch", user_id="owner", include_result=True))[0]
    assert saved["status"] == "succeeded" and saved["result"] == "saved"
    assert saved["attempt_id"] == first["attempt_id"]


@pytest.mark.asyncio
async def test_known_failure_after_dispatch_needs_explicit_retry(repo):
    await create(repo, dependent=False)
    now = datetime.now(UTC)
    first = (await claim(repo, now))[0]
    assert await repo.mark_item_dispatch_started(first["id"], lease_owner="worker", now=now)
    assert await finish(repo, first, now, succeeded=False)
    assert await claim(repo, now + timedelta(seconds=11), "replacement") == []
    assert (await repo.list_items("batch", user_id="owner"))[0]["status"] == "failed"
    retried = await repo.retry_item("batch", first["id"], user_id="owner")
    assert retried["dispatch_started_at"] is None and retried["attempt_id"] is None
    second = (await claim(repo, now + timedelta(seconds=12), "replacement"))[0]
    assert second["attempt_id"] != first["attempt_id"]


@pytest.mark.asyncio
async def test_proven_admission_failure_clears_dispatch_intent(repo):
    await create(repo, attempts=1)
    now = datetime.now(UTC)
    first = (await claim(repo, now))[0]
    assert await repo.mark_item_dispatch_started(first["id"], lease_owner="worker", now=now)
    assert await repo.requeue_item_after_admission_failure(first["id"], lease_owner="worker", error="capacity full", now=now)
    second = (await claim(repo, now, "replacement"))[0]
    assert second["attempt"] == 1 and second["dispatch_started_at"] is None
    assert second["attempt_id"] != first["attempt_id"]


@pytest.mark.asyncio
async def test_supervisor_uncertainty_requires_current_dispatched_claim(repo):
    await create(repo)
    now = datetime.now(UTC)
    item = (await claim(repo, now))[0]
    assert not await repo.mark_item_outcome_unknown(item["id"], lease_owner="worker", error="lost result", now=now)
    assert await repo.mark_item_dispatch_started(item["id"], lease_owner="worker", now=now)
    assert not await repo.mark_item_dispatch_started(item["id"], lease_owner="worker", now=now)
    assert not await repo.mark_item_outcome_unknown(item["id"], lease_owner="other", error="lost result", now=now)
    assert await repo.mark_item_outcome_unknown(item["id"], lease_owner="worker", error="lost result", now=now)
    saved = (await repo.list_items("batch", user_id="owner"))[0]
    assert saved["status"] == "outcome_unknown" and saved["error"] == "lost result"
    cancelled = await repo.cancel_batch("batch", user_id="owner")
    assert cancelled["status"] == "cancelled"
    item = (await repo.list_items("batch", user_id="owner"))[0]
    assert item["status"] == "cancelled" and item["attempt_id"] == saved["attempt_id"]
    assert item["dispatch_started_at"] == saved["dispatch_started_at"]
    assert "unknown" in item["error"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("control", ["expiry", "cancel"])
async def test_dispatch_intent_refuses_expired_or_cancelled_claim(repo, control):
    await create(repo)
    now = datetime.now(UTC)
    item = (await claim(repo, now))[0]
    if control == "cancel":
        await repo.cancel_batch("batch", user_id="owner")
    assert not await repo.mark_item_dispatch_started(item["id"], lease_owner="worker", now=now + timedelta(seconds=11) if control == "expiry" else now)


@pytest.mark.asyncio
async def test_recovery_cannot_requeue_a_dispatch_committed_after_its_expiry_read(repo, monkeypatch):
    if get_engine().dialect.name != "sqlite":
        pytest.skip("SQLite unlocked SELECT interleaving; PostgreSQL serializes these rows")
    await create(repo)
    now = datetime.now(UTC)
    item = (await claim(repo, now))[0]
    read, release = asyncio.Event(), asyncio.Event()
    original = AsyncSession.execute
    recovery = None

    async def execute(session, statement, *args, **kwargs):
        result = await original(session, statement, *args, **kwargs)
        if asyncio.current_task() is recovery and not read.is_set() and getattr(statement, "is_select", False) and "subagent_batch_items.lease_expires_at <" in str(statement) and len(statement.selected_columns) > 1:
            read.set()
            await release.wait()
        return result

    monkeypatch.setattr(AsyncSession, "execute", execute)
    recovery = asyncio.create_task(claim(repo, now + timedelta(seconds=11), "replacement"))
    try:
        await asyncio.wait_for(read.wait(), 3)
        # Admission sampled a timestamp while its lease was valid. Its commit
        # races the recovery pass's unlocked SQLite snapshot.
        assert await repo.mark_item_dispatch_started(item["id"], lease_owner="worker", now=now + timedelta(seconds=1))
    finally:
        release.set()
        claimed = await asyncio.wait_for(recovery, 3)
    assert claimed == []
    assert await claim(repo, now + timedelta(seconds=12), "replacement") == []
    saved = (await repo.list_items("batch", user_id="owner"))[0]
    assert saved["status"] == "outcome_unknown" and saved["attempt_id"] == item["attempt_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("peer_action", ["cancel", "reclaim"])
async def test_dispatch_commit_cannot_overwrite_control_or_a_new_claim(repo, monkeypatch, peer_action):
    if get_engine().dialect.name != "sqlite":
        pytest.skip("SQLite unlocked SELECT interleaving; PostgreSQL serializes these rows")
    await create(repo)
    now = datetime.now(UTC)
    item = (await claim(repo, now))[0]
    read, release = asyncio.Event(), asyncio.Event()
    original = AsyncSession.execute
    dispatch = None

    async def execute(session, statement, *args, **kwargs):
        result = await original(session, statement, *args, **kwargs)
        if asyncio.current_task() is dispatch and not read.is_set() and getattr(statement, "is_select", False) and "subagent_batch_items" in str(statement) and len(statement.selected_columns) > 1:
            read.set()
            await release.wait()
        return result

    monkeypatch.setattr(AsyncSession, "execute", execute)
    dispatch = asyncio.create_task(repo.mark_item_dispatch_started(item["id"], lease_owner="worker", now=now + timedelta(seconds=1)))
    try:
        await asyncio.wait_for(read.wait(), 3)
        if peer_action == "cancel":
            await repo.cancel_batch("batch", user_id="owner")
        else:
            assert len(await claim(repo, now + timedelta(seconds=11), "replacement")) == 1
        expected = await repo.list_items("batch", user_id="owner")
    finally:
        release.set()
        dispatched = await asyncio.wait_for(dispatch, 3)
    assert not dispatched
    assert await repo.list_items("batch", user_id="owner") == expected


@pytest.mark.asyncio
async def test_admission_retry_cannot_replace_the_stored_recovery_policy(repo):
    await create(repo)
    repeated = await create(repo, policy="retry")
    assert repeated["recovery_policy"] == "conservative"
    assert (await claim(repo, datetime.now(UTC)))[0]["batch"]["recovery_policy"] == "conservative"


@pytest.mark.asyncio
async def test_unknown_result_does_not_hold_an_independent_worker_slot(repo):
    await create(repo, independent=True)
    now = datetime.now(UTC)
    first = (await claim(repo, now))[0]
    assert await repo.mark_item_dispatch_started(first["id"], lease_owner="worker", now=now)
    next_items = await claim(repo, now + timedelta(seconds=11), "replacement")
    assert [item["item_key"] for item in next_items] == ["independent"]
    assert await finish(repo, next_items[0], now + timedelta(seconds=12), owner="replacement")
    batch = await repo.get_batch("batch", user_id="owner")
    assert batch["status"] == "running" and batch["completed_at"] is None
    assert batch["counts"]["outcome_unknown"] == batch["counts"]["succeeded"] == batch["counts"]["pending"] == 1
    assert await repo.claim_continuations(now=now + timedelta(seconds=13), lease_owner="followup", lease_seconds=10) == []
