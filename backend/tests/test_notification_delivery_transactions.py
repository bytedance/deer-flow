"""Notification obligations must share the occurrence's commit boundary."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from deerflow.persistence.notification_deliveries import NotificationDeliveryRepository, NotificationDeliveryRow


@pytest.fixture
async def delivery_repo(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'notifications.db'}", sqlite_dir=str(tmp_path))
    try:
        yield NotificationDeliveryRepository(get_session_factory())
    finally:
        await close_engine()


def delivery_args(**overrides):
    return {
        "task_id": "task-a",
        "task_run_id": "occurrence-a",
        "run_id": "run-a",
        "event": "task_paused",
        "provider": "wecom",
        "target": "alice-external",
        "owner_user_id": "alice",
        "payload": {"reason_code": "consecutive_unmet"},
        **overrides,
    }


@pytest.mark.anyio
async def test_delivery_is_not_visible_until_occurrence_transaction_commits(delivery_repo):
    async with delivery_repo.session_factory() as session:
        inserted = await delivery_repo.enqueue_in_session(session, **delivery_args())
        assert inserted["status"] == "pending"
        async with delivery_repo.session_factory() as reader:
            assert await reader.scalar(select(func.count()).select_from(NotificationDeliveryRow)) == 0
        await session.commit()
    claimed = await delivery_repo.claim_due_deliveries(now=datetime.now(UTC), limit=5)
    assert [row["id"] for row in claimed] == [inserted["id"]]


@pytest.mark.anyio
async def test_rollback_cannot_leave_a_pause_notification_without_the_pause(delivery_repo):
    async with delivery_repo.session_factory() as session:
        await delivery_repo.enqueue_in_session(session, **delivery_args())
        await session.rollback()
    assert await delivery_repo.claim_due_deliveries(now=datetime.now(UTC), limit=5) == []


@pytest.mark.anyio
async def test_completion_replay_preserves_the_first_delivery_payload(delivery_repo):
    async with delivery_repo.session_factory() as session:
        first = await delivery_repo.enqueue_in_session(session, **delivery_args())
        second = await delivery_repo.enqueue_in_session(session, **delivery_args(payload={"reason_code": "different"}))
        assert first["id"] == second["id"]
        assert second["payload"] == first["payload"]
        await session.commit()
    assert len(await delivery_repo.claim_due_deliveries(now=datetime.now(UTC), limit=5)) == 1


@pytest.mark.anyio
async def test_one_occurrence_can_commit_unmet_and_pause_notices_together(delivery_repo):
    async with delivery_repo.session_factory() as session:
        await delivery_repo.enqueue_in_session(session, **delivery_args(event="run_unmet"))
        await delivery_repo.enqueue_in_session(session, **delivery_args(event="task_paused"))
        await session.commit()
    claimed = await delivery_repo.claim_due_deliveries(now=datetime.now(UTC), limit=5)
    assert {row["event"] for row in claimed} == {"run_unmet", "task_paused"}
