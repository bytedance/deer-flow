"""Tests for the scheduled-task notification delivery outbox (issue #4254).

The outbox is the durable queue between scheduled-task completion and IM
delivery: the completion hook only enqueues, a separate delivery worker
claims and sends. Execution status and delivery status stay independent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from deerflow.persistence.notification_deliveries import NotificationDeliveryRepository, NotificationDeliveryRow
from deerflow.persistence.notification_deliveries.sql import (
    _CHANNEL_PARK_MAX_AGE,
    _CHANNEL_PARK_MAX_ATTEMPTS,
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
    @pytest.mark.parametrize("completion", ["sent", "retry", "park", "terminal"])
    async def test_completion_is_fenced_when_reclaimed_before_update(self, repo, completion):
        import asyncio

        await repo.enqueue(**_enqueue_kwargs())
        now = datetime.now(UTC)
        old = (await repo.claim_due_deliveries(now=now, limit=1))[0]
        entered = asyncio.Event()
        resume = asyncio.Event()
        real_factory = repo.session_factory

        class PausedSession:
            def __init__(self):
                self.session = real_factory()

            async def __aenter__(self):
                await self.session.__aenter__()
                return self

            async def __aexit__(self, *exc_info):
                return await self.session.__aexit__(*exc_info)

            async def execute(self, statement, *args, **kwargs):
                if getattr(statement, "is_update", False):
                    entered.set()
                    await resume.wait()
                return await self.session.execute(statement, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self.session, name)

        paused_repo = NotificationDeliveryRepository(PausedSession)
        if completion == "sent":
            operation = paused_repo.mark_sent(old["id"], claim_token=old["claim_token"])
        else:
            operation = paused_repo.mark_failed(
                old["id"],
                claim_token=old["claim_token"],
                error="late",
                count_attempt=completion != "park",
                terminal=completion == "terminal",
            )
        task = asyncio.create_task(operation)
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            later = now + timedelta(minutes=11)
            await repo.reset_stale_sending_rows(now=later, timeout=timedelta(minutes=10))
            current = (await repo.claim_due_deliveries(now=later, limit=1))[0]
            resume.set()
            assert await task == current
            async with real_factory() as session:
                assert repo._to_dict(await session.get(NotificationDeliveryRow, old["id"])) == current
        finally:
            resume.set()
            await asyncio.gather(task, return_exceptions=True)

    @pytest.mark.anyio
    @pytest.mark.parametrize("completion", ["sent", "retry", "park", "terminal"])
    @pytest.mark.parametrize("reclaim", [False, True])
    async def test_stale_completion_cannot_modify_reset_or_reclaimed_delivery(self, repo, completion, reclaim):
        await repo.enqueue(**_enqueue_kwargs())
        now = datetime.now(UTC)
        old_claim = (await repo.claim_due_deliveries(now=now, limit=1))[0]
        later = now + timedelta(minutes=11)
        await repo.reset_stale_sending_rows(now=later, timeout=timedelta(minutes=10))
        if reclaim:
            current = (await repo.claim_due_deliveries(now=later, limit=1))[0]
            assert current["claim_token"] != old_claim["claim_token"]
        else:
            async with repo.session_factory() as session:
                current = repo._to_dict(await session.get(NotificationDeliveryRow, old_claim["id"]))
        if completion == "sent":
            updated = await repo.mark_sent(old_claim["id"], claim_token=old_claim["claim_token"])
        else:
            updated = await repo.mark_failed(
                old_claim["id"],
                claim_token=old_claim["claim_token"],
                error="late failure",
                count_attempt=completion != "park",
                terminal=completion == "terminal",
            )
        assert updated == current
        async with repo.session_factory() as session:
            assert repo._to_dict(await session.get(NotificationDeliveryRow, old_claim["id"])) == current

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
        claimed = await repo.claim_due_deliveries(now=datetime.now(UTC), limit=10)
        assert len(claimed) == 1

    @pytest.mark.anyio
    async def test_enqueue_allows_distinct_events_and_targets(self, repo):
        await repo.enqueue(**_enqueue_kwargs())
        await repo.enqueue(**_enqueue_kwargs(event="run_failed"))
        await repo.enqueue(**_enqueue_kwargs(target="bob"))

        claimed = await repo.claim_due_deliveries(now=datetime.now(UTC), limit=10)
        assert len(claimed) == 3

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
    async def test_claim_excludes_rows_already_claimed_by_another_worker(self, repo):
        """The claim result set must be exactly the rows THIS transaction
        flipped. Replay the multi-worker race deterministically: right after
        this worker's due-id SELECT, a rival worker commits a claim on one of
        the same rows; the stale id must not come back in the result set,
        otherwise multi-instance deployments double-send
        (``scheduler.multi_instance`` is a supported mode)."""
        from sqlalchemy import select

        await repo.enqueue(**_enqueue_kwargs(task_run_id="run-mine"))
        await repo.enqueue(**_enqueue_kwargs(task_run_id="run-stolen", target="bob"))

        real_factory = repo.session_factory

        async def _rival_steals_one():
            async with real_factory() as session:
                row = (await session.execute(select(NotificationDeliveryRow).where(NotificationDeliveryRow.status == "pending").order_by(NotificationDeliveryRow.created_at, NotificationDeliveryRow.id).limit(1))).scalars().one()
                row.status = "sending"
                await session.commit()

        fired = {"done": False}

        class _InterceptSession:
            """Fires the rival claim right after the first SELECT of the
            intercepted claim transaction."""

            def __init__(self, session):
                self._session = session

            async def __aenter__(self):
                await self._session.__aenter__()
                return self

            async def __aexit__(self, *exc_info):
                return await self._session.__aexit__(*exc_info)

            async def execute(self, stmt, *args, **kwargs):
                result = await self._session.execute(stmt, *args, **kwargs)
                if not fired["done"] and getattr(stmt, "is_select", False):
                    fired["done"] = True
                    await _rival_steals_one()
                return result

            def __getattr__(self, name):
                return getattr(self._session, name)

        racing_repo = NotificationDeliveryRepository(lambda: _InterceptSession(real_factory()))
        claimed = await racing_repo.claim_due_deliveries(now=datetime.now(UTC), limit=10)

        assert fired["done"] is True
        # Exactly one row remains for this worker; the rival-owned row must
        # not be in the result set even though the due-id view still saw it.
        assert len(claimed) == 1

    @pytest.mark.anyio
    async def test_claim_stamps_updated_at_for_stale_detection(self, repo):
        """Claim must write ``updated_at`` explicitly: a Core UPDATE does not
        fire ORM ``onupdate``, and the stale-``sending`` recovery measures
        its timeout from the moment the row was claimed."""
        await repo.enqueue(**_enqueue_kwargs(), available_at=datetime.now(UTC) - timedelta(hours=2))
        claim_at = datetime.now(UTC)

        claimed = await repo.claim_due_deliveries(now=claim_at, limit=1)

        updated_at = claimed[0]["updated_at"]
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        assert abs((updated_at - claim_at).total_seconds()) < 1

    @pytest.mark.anyio
    async def test_reset_stale_sending_rows_flips_back_only_timed_out_rows(self, repo):
        """A row claimed then orphaned (crash between claim and the final
        status write) must become claimable again once the timeout passes --
        otherwise it sits in ``sending`` forever."""
        stuck = await repo.enqueue(**_enqueue_kwargs(task_run_id="run-stuck"))
        await repo.claim_due_deliveries(now=datetime.now(UTC), limit=1)

        # Freshly claimed rows are not stale yet.
        assert await repo.reset_stale_sending_rows(now=datetime.now(UTC), timeout=timedelta(minutes=10)) == 0

        assert await repo.reset_stale_sending_rows(now=datetime.now(UTC) + timedelta(minutes=11), timeout=timedelta(minutes=10)) == 1

        reclaimed = await repo.claim_due_deliveries(now=datetime.now(UTC) + timedelta(minutes=11), limit=1)
        assert [row["id"] for row in reclaimed] == [stuck["id"]]

    @pytest.mark.anyio
    async def test_reset_stale_sending_rows_ignores_terminal_and_pending_rows(self, repo):
        await repo.enqueue(**_enqueue_kwargs(task_run_id="run-sent"))
        await repo.enqueue(**_enqueue_kwargs(task_run_id="run-pending"))
        claimed = await repo.claim_due_deliveries(now=datetime.now(UTC), limit=1)
        await repo.mark_sent(claimed[0]["id"], claim_token=claimed[0]["claim_token"])

        reset = await repo.reset_stale_sending_rows(now=datetime.now(UTC) + timedelta(hours=1), timeout=timedelta(minutes=10))

        assert reset == 0

    @pytest.mark.anyio
    async def test_mark_sent_finalises_delivery(self, repo):
        await repo.enqueue(**_enqueue_kwargs())
        delivery = (await repo.claim_due_deliveries(now=datetime.now(UTC), limit=1))[0]

        updated = await repo.mark_sent(delivery["id"], claim_token=delivery["claim_token"])

        assert updated["status"] == "sent"
        assert updated["sent_at"] is not None

    @pytest.mark.anyio
    async def test_mark_failed_reschedules_with_backoff_while_retries_remain(self, repo):
        await repo.enqueue(**_enqueue_kwargs())
        delivery = (await repo.claim_due_deliveries(now=datetime.now(UTC), limit=1))[0]
        before = datetime.now(UTC)

        updated = await repo.mark_failed(delivery["id"], claim_token=delivery["claim_token"], error="wecom: rate limited")

        assert updated["status"] == "pending"
        assert updated["attempts"] == 1
        assert updated["last_error"] == "wecom: rate limited"
        retry_at = updated["available_at"]
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        assert retry_at > before

    @pytest.mark.anyio
    async def test_mark_failed_terminal_finalises_at_once_whatever_the_budget(self, repo):
        # Used when the delivery can never become valid again (the owner
        # disconnected the target): no backoff, no parking, budget untouched.
        await repo.enqueue(**_enqueue_kwargs())
        delivery = (await repo.claim_due_deliveries(now=datetime.now(UTC), limit=1))[0]

        updated = await repo.mark_failed(delivery["id"], claim_token=delivery["claim_token"], error="target is no longer connected", terminal=True)

        assert updated["status"] == "failed"
        assert updated["attempts"] == 0
        assert updated["parked_attempts"] == 0
        assert updated["last_error"] == "target is no longer connected"
        assert await repo.claim_due_deliveries(now=datetime.now(UTC) + timedelta(days=2), limit=10) == []

    @pytest.mark.anyio
    async def test_terminal_states_are_sticky(self, repo):
        # A late write from a crash handler or a stale claimant must neither
        # reopen a finished row nor relabel it.
        await repo.enqueue(**_enqueue_kwargs())
        dropped = (await repo.claim_due_deliveries(now=datetime.now(UTC), limit=1))[0]
        await repo.mark_failed(dropped["id"], claim_token=dropped["claim_token"], error="target is no longer connected", terminal=True)
        after_late_failure = await repo.mark_failed(dropped["id"], claim_token=dropped["claim_token"], error="delivery crashed before completion")
        after_late_sent = await repo.mark_sent(dropped["id"], claim_token=dropped["claim_token"])
        assert after_late_failure["status"] == "failed"
        assert after_late_sent["status"] == "failed"
        assert after_late_sent["last_error"] == "target is no longer connected"
        assert after_late_sent["attempts"] == 0

        await repo.enqueue(**_enqueue_kwargs(target="other-target"))
        sent = (await repo.claim_due_deliveries(now=datetime.now(UTC), limit=1))[0]
        await repo.mark_sent(sent["id"], claim_token=sent["claim_token"])
        after_late_failure = await repo.mark_failed(sent["id"], claim_token=sent["claim_token"], error="late failure", count_attempt=False)
        assert after_late_failure["status"] == "sent"
        assert after_late_failure["last_error"] is None
        assert await repo.claim_due_deliveries(now=datetime.now(UTC) + timedelta(days=2), limit=10) == []

    @pytest.mark.anyio
    async def test_mark_failed_exhausts_retries(self, repo):
        delivery = await repo.enqueue(**_enqueue_kwargs())

        updated = None
        for _ in range(delivery["max_attempts"]):
            claimed = await repo.claim_due_deliveries(now=datetime.now(UTC) + timedelta(days=1), limit=1)
            assert len(claimed) == 1
            updated = await repo.mark_failed(claimed[0]["id"], claim_token=claimed[0]["claim_token"], error="boom")

        assert updated["status"] == "failed"
        # A failed (exhausted) row is never claimed again.
        assert await repo.claim_due_deliveries(now=datetime.now(UTC) + timedelta(days=1), limit=1) == []

    @pytest.mark.anyio
    async def test_mark_failed_without_counting_attempt_preserves_budget_until_park_cap(self, repo):
        """Channel-down failures are parked, not counted: the row keeps its
        full retry budget until parking expires, then settles to failed."""
        await repo.enqueue(**_enqueue_kwargs())
        delivery = (await repo.claim_due_deliveries(now=datetime.now(UTC), limit=1))[0]
        before = datetime.now(UTC)

        updated = await repo.mark_failed(delivery["id"], claim_token=delivery["claim_token"], error="channel 'wecom' is not running", count_attempt=False)

        assert updated["status"] == "pending"
        assert updated["attempts"] == 0
        assert updated["parked_attempts"] == 1
        retry_at = updated["available_at"]
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        assert retry_at >= before + timedelta(minutes=10)

        for _ in range(_CHANNEL_PARK_MAX_ATTEMPTS - 1):
            delivery = (await repo.claim_due_deliveries(now=datetime.now(UTC) + timedelta(days=1), limit=1))[0]
            updated = await repo.mark_failed(delivery["id"], claim_token=delivery["claim_token"], error="channel still down", count_attempt=False)
            assert updated["status"] == "pending"
            assert updated["attempts"] == 0

        delivery = (await repo.claim_due_deliveries(now=datetime.now(UTC) + timedelta(days=1), limit=1))[0]
        updated = await repo.mark_failed(delivery["id"], claim_token=delivery["claim_token"], error="channel still down", count_attempt=False)
        assert updated["status"] == "failed"
        assert updated["attempts"] == 0

    @pytest.mark.anyio
    async def test_mark_failed_parking_expires_by_row_age(self, repo):
        await repo.enqueue(**_enqueue_kwargs())
        delivery = (await repo.claim_due_deliveries(now=datetime.now(UTC), limit=1))[0]
        async with repo.session_factory() as session:
            row = await session.get(NotificationDeliveryRow, delivery["id"])
            row.created_at = datetime.now(UTC) - _CHANNEL_PARK_MAX_AGE - timedelta(minutes=1)
            await session.commit()

        updated = await repo.mark_failed(delivery["id"], claim_token=delivery["claim_token"], error="channel 'wecom' is not running", count_attempt=False)

        assert updated["status"] == "failed"
        assert updated["attempts"] == 0

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
