"""One durable follow-up belongs to one explicitly opted-in native batch."""

from datetime import UTC, datetime, timedelta

import pytest
from test_batch_dependencies import create, finish
from test_batch_dependencies import repo as _repo_fixture

from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.subagent_batches import SubagentBatchRepository

repo = _repo_fixture


async def completed_batch(repo, *, succeeded=True):
    await create(
        repo,
        [{"key": "a", "prompt": "Read A"}],
        title="Summarize records",
        max_live_items=1,
        max_running_items=1,
        continuation={"prompt": "Write the requested summary", "grant": {"token_version": 1}},
    )
    now = datetime.now(UTC)
    assert await repo.claim_continuations(now=now, lease_owner="first", lease_seconds=30) == []
    item = (await repo.claim_items(now=now, lease_owner="worker", lease_seconds=120, limit=1))[0]
    await finish(repo, item, succeeded=succeeded, result="Read A", result_preview="Read A", error=None, model_name="local", completed_at=now)
    return now


@pytest.mark.asyncio
async def test_continuation_has_one_claim_and_recovers_with_the_same_identity(repo):
    now = await completed_batch(repo)
    first = await repo.claim_continuations(now=now, lease_owner="first", lease_seconds=30)
    assert len(first) == 1
    assert await repo.claim_continuations(now=now, lease_owner="second", lease_seconds=30) == []
    reopened = SubagentBatchRepository(get_session_factory())
    recovered = await reopened.claim_continuations(now=now + timedelta(seconds=31), lease_owner="second", lease_seconds=30)
    assert recovered[0]["id"] == first[0]["id"]
    assert recovered[0]["continuation"] == first[0]["continuation"]
    assert not await repo.finish_continuation("batch", lease_owner="first", status="dispatched", run_id="stale")
    assert await repo.finish_continuation("batch", lease_owner="second", status="dispatched", run_id="follow-up")
    assert await repo.claim_continuations(now=now + timedelta(minutes=2), lease_owner="third", lease_seconds=30) == []
    public = await repo.get_batch("batch", user_id="owner")
    assert public["continuation_status"] == "dispatched" and public["continuation_run_id"] == "follow-up"
    assert "continuation" not in public and "token_version" not in str(public)


@pytest.mark.asyncio
async def test_cancelling_a_completed_batch_suppresses_an_unlaunched_followup(repo):
    now = await completed_batch(repo)
    await repo.cancel_batch("batch", user_id="owner")
    public = await repo.get_batch("batch", user_id="owner")
    assert public["status"] == "completed"
    assert public["continuation_status"] == "cancelled"
    assert await repo.claim_continuations(now=now, lease_owner="worker", lease_seconds=30) == []


@pytest.mark.asyncio
async def test_cancel_wins_over_an_inflight_followup_receipt(repo):
    now = await completed_batch(repo)
    assert len(await repo.claim_continuations(now=now, lease_owner="first", lease_seconds=30)) == 1
    await repo.cancel_batch("batch", user_id="owner")
    assert not await repo.finish_continuation("batch", lease_owner="first", status="dispatched", run_id="late")
    assert (await repo.get_batch("batch", user_id="owner"))["continuation_status"] == "cancelled"


@pytest.mark.asyncio
async def test_deferred_continuations_yield_to_other_conversations_after_reopen(repo):
    for index in range(17):
        await create(
            repo,
            [{"key": "a", "prompt": "Read"}],
            batch_id=f"batch-{index:02}",
            user_id=f"owner-{index}",
            thread_id=f"thread-{index}",
            run_id=f"run-{index}",
            submission_key=f"submit-{index}",
            max_live_items=1,
            max_running_items=1,
            continuation={"prompt": "Summarize"},
        )
    items = await repo.claim_items(now=datetime.now(UTC), lease_owner="worker", lease_seconds=120, limit=17)
    assert len(items) == 17
    for item in items:
        await finish(repo, item, result="Done", result_preview="Done", model_name="local")
    seen = set()
    for index in range(3):
        reopened = SubagentBatchRepository(get_session_factory())
        owner = f"followup-{index}"
        claimed = await reopened.claim_continuations(now=datetime.now(UTC), lease_owner=owner, lease_seconds=30, limit=8)
        seen.update(batch["id"] for batch in claimed)
        for batch in claimed:
            assert await reopened.finish_continuation(batch["id"], lease_owner=owner, status="pending")
    assert seen == {f"batch-{index:02}" for index in range(17)}


@pytest.mark.asyncio
async def test_manual_item_retry_defers_an_unadmitted_followup(repo):
    now = await completed_batch(repo, succeeded=False)
    await repo.claim_continuations(now=now, lease_owner="before-retry", lease_seconds=30)
    item = (await repo.list_items("batch", user_id="owner"))[0]
    assert await repo.retry_item("batch", item["id"], user_id="owner")
    assert not await repo.finish_continuation("batch", lease_owner="before-retry", status="dispatched", run_id="late")
    assert await repo.claim_continuations(now=now, lease_owner="after-retry", lease_seconds=30) == []
    assert (await repo.get_batch("batch", user_id="owner"))["continuation_status"] == "pending"


@pytest.mark.asyncio
async def test_goal_suppression_and_claim_do_not_deadlock(repo, monkeypatch):
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    from deerflow.persistence.engine import get_engine

    if get_engine().dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock interleaving")
    now = await completed_batch(repo)
    await repo.claim_continuations(now=now, lease_owner="initial", lease_seconds=30)
    await repo.finish_continuation("batch", lease_owner="initial", status="pending")
    locked, release = asyncio.Event(), asyncio.Event()
    original = AsyncSession.execute
    claim_task = suppression = None
    suppression_pid = None

    async def execute(session, statement, *args, **kwargs):
        nonlocal suppression_pid
        if asyncio.current_task() is suppression and suppression_pid is None:
            suppression_pid = (await original(session, text("SELECT pg_backend_pid()"))).scalar_one()
        result = await original(session, statement, *args, **kwargs)
        if asyncio.current_task() is claim_task and getattr(statement, "is_update", False) and statement.table.name == "subagent_batches":
            locked.set()
            await release.wait()
        return result

    monkeypatch.setattr(AsyncSession, "execute", execute)
    claim_task = asyncio.create_task(repo.claim_continuations(now=now, lease_owner="claim", lease_seconds=30))
    try:
        await asyncio.wait_for(locked.wait(), 3)
        suppression = asyncio.create_task(repo.suppress_thread_continuations("thread"))
        waiting = False
        for _ in range(200):
            async with repo._sf() as session:
                waiting = await session.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE pid=:pid AND wait_event_type='Lock'"), {"pid": suppression_pid})
            if waiting:
                break
            await asyncio.sleep(0.01)
        assert waiting, "suppression must reach the competing row lock"
        release.set()
        await asyncio.wait_for(asyncio.gather(claim_task, suppression), 5)
        assert (await repo.get_batch("batch", user_id="owner"))["continuation_status"] == "suppressed"
    finally:
        release.set()
        for task in (claim_task, suppression):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (claim_task, suppression) if task is not None), return_exceptions=True)


@pytest.mark.asyncio
async def test_schema_upgrade_and_rollback_preserve_existing_batch_work(repo):
    import asyncio

    from alembic import command
    from sqlalchemy import text

    from deerflow.persistence import bootstrap
    from deerflow.persistence.engine import get_engine

    await completed_batch(repo)
    engine = get_engine()
    async with engine.connect() as connection:
        schema = await connection.scalar(text("SELECT current_schema()")) if engine.dialect.name == "postgresql" else ""
    config = bootstrap._get_alembic_config(engine, postgres_schema=schema)
    await asyncio.to_thread(command.downgrade, config, "0051_merge_run_inputs_fencing")
    async with engine.connect() as connection:
        assert (await connection.execute(text("SELECT title FROM subagent_batches WHERE id='batch'"))).scalar_one() == "Summarize records"
        assert (await connection.execute(text("SELECT status FROM subagent_batch_items WHERE batch_id='batch'"))).scalar_one() == "succeeded"
    await asyncio.to_thread(command.upgrade, config, "head")
    batch = await repo.get_batch("batch", user_id="owner")
    assert batch["counts"]["succeeded"] == 1
    assert "continuation_status" not in batch
