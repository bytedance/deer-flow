"""Tests for the scheduled-task notification delivery outbox (issue #4254).

The outbox is the durable queue between scheduled-task completion and IM
delivery: the completion hook only enqueues, a separate delivery worker
claims and sends. Execution status and delivery status stay independent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from deerflow.persistence.notification_deliveries import (
    NotificationDeliveryRepository,
    NotificationDeliveryRow,
)


@pytest.fixture
async def repo(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'deliveries.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        yield NotificationDeliveryRepository(get_session_factory())
    finally:
        await close_engine()


def _enqueue_kwargs(**overrides):
    kwargs = {
        "task_id": "task-1",
        "task_run_id": "run-1",
        "event": "run_completed",
        "provider": "wecom",
        "target": "GaoZhiChao",
        "owner_user_id": "alice",
        "payload": {"summary": "daily report ready"},
    }
    kwargs.update(overrides)
    return kwargs


class TestNotificationDeliveryRepository:
    @pytest.mark.anyio
    async def test_enqueue_creates_pending_delivery(self, repo):
        delivery = await repo.enqueue(**_enqueue_kwargs())

        assert delivery["status"] == "pending"
        assert delivery["attempts"] == 0
        assert delivery["provider"] == "wecom"
        assert delivery["target"] == "GaoZhiChao"
        assert delivery["payload"] == {"summary": "daily report ready"}

    @pytest.mark.anyio
    async def test_enqueue_is_idempotent_per_run_event_target(self, repo):
        # (task_run_id, event, provider, target) is the idempotency key the
        # issue design calls for: a retried completion hook must not enqueue
        # a second notification for the same outcome.
        first = await repo.enqueue(**_enqueue_kwargs())
        second = await repo.enqueue(**_enqueue_kwargs(payload={"summary": "different"}))

        assert second["id"] == first["id"]
        assert second["payload"] == {"summary": "daily report ready"}
        assert len(await repo.list_by_task_run("run-1")) == 1

    @pytest.mark.anyio
    async def test_enqueue_allows_distinct_events_and_targets(self, repo):
        await repo.enqueue(**_enqueue_kwargs())
        await repo.enqueue(**_enqueue_kwargs(event="run_failed"))
        await repo.enqueue(**_enqueue_kwargs(target="bob"))

        assert len(await repo.list_by_task_run("run-1")) == 3

    @pytest.mark.anyio
    async def test_claim_returns_only_due_pending_rows(self, repo):
        due = await repo.enqueue(**_enqueue_kwargs(task_run_id="run-due"))
        await repo.enqueue(**_enqueue_kwargs(task_run_id="run-future", available_at=datetime.now(UTC) + timedelta(hours=1)))

        claimed = await repo.claim_due_deliveries(now=datetime.now(UTC), limit=10)

        assert [row["id"] for row in claimed] == [due["id"]]

    @pytest.mark.anyio
    async def test_claim_marks_rows_in_flight_so_second_claim_is_empty(self, repo):
        await repo.enqueue(**_enqueue_kwargs())

        first = await repo.claim_due_deliveries(now=datetime.now(UTC), limit=10)
        second = await repo.claim_due_deliveries(now=datetime.now(UTC), limit=10)

        assert len(first) == 1
        assert second == []

    @pytest.mark.anyio
    async def test_claim_respects_limit(self, repo):
        for index in range(3):
            await repo.enqueue(**_enqueue_kwargs(task_run_id=f"run-{index}"))

        claimed = await repo.claim_due_deliveries(now=datetime.now(UTC), limit=2)

        assert len(claimed) == 2

    @pytest.mark.anyio
    async def test_mark_sent_finalises_delivery(self, repo):
        delivery = await repo.enqueue(**_enqueue_kwargs())

        updated = await repo.mark_sent(delivery["id"])

        assert updated["status"] == "sent"
        assert updated["sent_at"] is not None

    @pytest.mark.anyio
    async def test_mark_failed_reschedules_with_backoff_while_retries_remain(self, repo):
        delivery = await repo.enqueue(**_enqueue_kwargs())
        before = datetime.now(UTC)

        updated = await repo.mark_failed(delivery["id"], error="wecom: rate limited")

        assert updated["status"] == "pending"
        assert updated["attempts"] == 1
        assert updated["last_error"] == "wecom: rate limited"
        retry_at = updated["available_at"]
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        assert retry_at > before

    @pytest.mark.anyio
    async def test_mark_failed_exhausts_retries(self, repo):
        delivery = await repo.enqueue(**_enqueue_kwargs())

        updated = None
        for _ in range(delivery["max_attempts"]):
            claimed = await repo.claim_due_deliveries(now=datetime.now(UTC) + timedelta(days=1), limit=1)
            assert len(claimed) == 1
            updated = await repo.mark_failed(claimed[0]["id"], error="boom")

        assert updated["status"] == "failed"
        # A failed (exhausted) row is never claimed again.
        assert await repo.claim_due_deliveries(now=datetime.now(UTC) + timedelta(days=1), limit=1) == []

    @pytest.mark.anyio
    async def test_list_by_task_run_scopes_to_one_run(self, repo):
        await repo.enqueue(**_enqueue_kwargs(task_run_id="run-a"))
        await repo.enqueue(**_enqueue_kwargs(task_run_id="run-b"))

        rows = await repo.list_by_task_run("run-a")

        assert len(rows) == 1
        assert rows[0]["task_run_id"] == "run-a"

    @pytest.mark.anyio
    async def test_unique_constraint_rejects_manual_duplicate(self, repo):
        from sqlalchemy.exc import IntegrityError

        await repo.enqueue(**_enqueue_kwargs())
        with pytest.raises(IntegrityError):
            async with repo.session_factory() as session:
                session.add(
                    NotificationDeliveryRow(
                        id="manual-duplicate",
                        task_id="task-1",
                        task_run_id="run-1",
                        event="run_completed",
                        provider="wecom",
                        target="GaoZhiChao",
                        owner_user_id="alice",
                    )
                )
                await session.commit()
