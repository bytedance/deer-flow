from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
import pytest_asyncio
from sqlalchemy import text

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.run import RunRepository
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URI")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="requires TEST_POSTGRES_URI (real Postgres for scheduler concurrency)",
)


def _postgres_url(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in {"sslmode", "channel_binding"}])
    return urlunsplit(parts._replace(query=query))


@pytest_asyncio.fixture()
async def postgres_repositories():
    assert POSTGRES_URL is not None
    schema = f"scheduler_{uuid.uuid4().hex}"
    await init_engine_from_config(
        DatabaseConfig(
            backend="postgres",
            postgres_url=_postgres_url(POSTGRES_URL),
            postgres_schema=schema,
        )
    )
    sf = get_session_factory()
    assert sf is not None
    run_repo = RunRepository(sf)
    task_repo = ScheduledTaskRepository(sf, run_repository=run_repo)
    task_run_repo = ScheduledTaskRunRepository(sf, run_repository=run_repo)
    try:
        yield task_repo, task_run_repo, run_repo
    finally:
        engine = get_engine()
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await close_engine()


async def _create_cron_task(task_repo: ScheduledTaskRepository, task_id: str, *, next_run_at: datetime | None) -> None:
    await task_repo.create(
        task_id=task_id,
        user_id="user-1",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title=task_id,
        prompt="p",
        schedule_type="cron",
        schedule_spec={"cron": "* * * * *"},
        timezone="UTC",
        next_run_at=next_run_at,
    )


@pytest.mark.asyncio
async def test_postgres_global_budget_serializes_cross_pod_claims(postgres_repositories):
    task_repo, _task_run_repo, _run_repo = postgres_repositories
    now = datetime.now(UTC)
    await _create_cron_task(task_repo, "task-a", next_run_at=now)
    await _create_cron_task(task_repo, "task-b", next_run_at=now)

    claims = await asyncio.gather(
        task_repo.claim_due_tasks(
            now=now,
            lease_owner="pod-a",
            lease_seconds=60,
            limit=1,
            global_max_concurrent_runs=1,
        ),
        task_repo.claim_due_tasks(
            now=now,
            lease_owner="pod-b",
            lease_seconds=60,
            limit=1,
            global_max_concurrent_runs=1,
        ),
    )

    assert sum(len(claimed) for claimed in claims) == 1


@pytest.mark.asyncio
async def test_postgres_reconciliation_uses_metadata_and_atomically_claims_expired_run(postgres_repositories):
    task_repo, task_run_repo, run_repo = postgres_repositories
    now = datetime.now(UTC)
    for suffix in ("live", "expired"):
        await _create_cron_task(task_repo, f"task-{suffix}", next_run_at=None)
        await task_run_repo.create(
            run_record_id=f"task-run-{suffix}",
            task_id=f"task-{suffix}",
            thread_id=f"thread-{suffix}",
            scheduled_for=now,
            trigger="scheduled",
            status="running" if suffix == "expired" else "queued",
        )

    await task_run_repo.update_status("task-run-expired", status="running", run_id="run-expired")
    await run_repo.put(
        "run-live",
        thread_id="thread-live",
        user_id="user-1",
        status="running",
        metadata={
            "scheduled_task_id": "task-live",
            "scheduled_task_run_id": "task-run-live",
        },
        owner_worker_id="pod-a",
        lease_expires_at=(now + timedelta(seconds=60)).isoformat(),
    )
    await run_repo.put(
        "run-expired",
        thread_id="thread-expired",
        user_id="user-1",
        status="running",
        metadata={
            "scheduled_task_id": "task-expired",
            "scheduled_task_run_id": "task-run-expired",
        },
        owner_worker_id="pod-dead",
        lease_expires_at=(now - timedelta(seconds=60)).isoformat(),
    )

    assert await task_run_repo.reconcile_active_runs(error="lease expired", now=now) == 1
    assert (await task_run_repo.list_by_task("task-live"))[0]["status"] == "queued"
    assert (await task_run_repo.list_by_task("task-expired"))[0]["status"] == "interrupted"
    recovered = await run_repo.get("run-expired", user_id=None)
    assert recovered is not None
    assert recovered["status"] == "error"
    assert recovered["stop_reason"] == "scheduled_task_orphan_recovered"
