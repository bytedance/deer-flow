"""SQL repository for the scheduled-task notification delivery outbox.

The scheduler's finalization observer calls
:meth:`NotificationDeliveryRepository.enqueue_in_session` (idempotent, inside
the outcome's transaction), and the delivery worker uses ``claim_due_deliveries`` /
``mark_sent`` / ``mark_failed``. Claim flips rows ``pending -> sending``
inside one transaction guarded by ``status = 'pending'`` and stamps a fresh
``claim_token``. Completion writes that carry the token are conditionally
updated only while that claim owns the row, fencing stale workers after
reconciliation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.notification_deliveries.model import NotificationDeliveryRow

logger = logging.getLogger(__name__)

# Exponential backoff base/cap for retries: 60s, 120s, 240s, 480s, ...
# capped at 15 minutes. Bounded so a broken channel still drains the outbox
# to "failed" within roughly an hour at max_attempts=5.
_RETRY_BASE_SECONDS = 60
_RETRY_MAX_SECONDS = 900

# Flat re-poll interval for rows parked because the owning channel is not
# running. These failures do not consume the retry budget, so the row can
# wait out an hours-long channel outage and still deliver once it returns.
_CHANNEL_DOWN_RETRY_SECONDS = 900

# Parking is unbounded in count by default; cap it so a permanently absent
# provider (removed from config, never starts) settles to ``failed`` instead
# of retrying every 15 minutes for the life of the deployment. Age and
# parked-attempt limits are both checked — whichever trips first wins.
_CHANNEL_PARK_MAX_AGE = timedelta(days=2)
# 96 × 15min ≈ 24h of parking at the flat backoff interval.
_CHANNEL_PARK_MAX_ATTEMPTS = 96

# Rows in these states are finished; later status writes are ignored.
_TERMINAL_DELIVERY_STATUSES = frozenset({"sent", "failed"})


class NotificationDeliveryRepository:
    """Persistence facade for the notification delivery outbox."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex

    @staticmethod
    def _to_dict(row: NotificationDeliveryRow) -> dict[str, Any]:
        data = row.to_dict()
        data["payload"] = data.pop("payload_json") or {}
        return data

    async def enqueue(
        self,
        *,
        task_id: str,
        task_run_id: str,
        event: str,
        provider: str,
        target: str,
        owner_user_id: str,
        payload: dict[str, Any] | None = None,
        run_id: str | None = None,
        available_at: datetime | None = None,
        max_attempts: int = 5,
    ) -> dict[str, Any]:
        """Insert one delivery; a duplicate (task_run_id, event, provider,
        target) returns the existing row instead of raising."""
        row = NotificationDeliveryRow(
            id=self._new_id(),
            task_id=task_id,
            task_run_id=task_run_id,
            run_id=run_id,
            event=event,
            provider=provider,
            target=target,
            owner_user_id=owner_user_id,
            payload_json=dict(payload or {}),
            max_attempts=max_attempts,
        )
        if available_at is not None:
            row.available_at = available_at
        try:
            async with self.session_factory() as session:
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return self._to_dict(row)
        except IntegrityError:
            existing = await self._find_by_idempotency_key(
                task_run_id=task_run_id,
                event=event,
                provider=provider,
                target=target,
            )
            if existing is None:
                raise
            return self._to_dict(existing)

    async def enqueue_in_session(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        task_run_id: str,
        event: str,
        provider: str,
        target: str,
        owner_user_id: str,
        payload: dict[str, Any] | None = None,
        run_id: str | None = None,
        available_at: datetime | None = None,
        max_attempts: int = 5,
    ) -> dict[str, Any]:
        """Stage an idempotent delivery without committing its caller's work.

        Occurrence finalization uses the same transaction for the task change
        and its notification obligation. Conflict handling must not roll back
        that transaction or open a second writer while it holds the parent lock.
        """
        dialect = session.get_bind().dialect.name
        if dialect not in {"sqlite", "postgresql"}:
            raise ValueError(f"Unsupported notification database dialect: {dialect}")
        insert = sqlite_insert if dialect == "sqlite" else pg_insert
        values = {
            "id": self._new_id(),
            "task_id": task_id,
            "task_run_id": task_run_id,
            "run_id": run_id,
            "event": event,
            "provider": provider,
            "target": target,
            "owner_user_id": owner_user_id,
            "payload_json": dict(payload or {}),
            "max_attempts": max_attempts,
        }
        if available_at is not None:
            values["available_at"] = available_at
        statement = insert(NotificationDeliveryRow).values(**values).on_conflict_do_nothing(index_elements=["task_run_id", "event", "provider", "target"])
        await session.execute(statement)
        row = await session.scalar(
            select(NotificationDeliveryRow).where(
                NotificationDeliveryRow.task_run_id == task_run_id,
                NotificationDeliveryRow.event == event,
                NotificationDeliveryRow.provider == provider,
                NotificationDeliveryRow.target == target,
            )
        )
        if row is None:
            raise RuntimeError("Notification insert produced no delivery row")
        return self._to_dict(row)

    async def _find_by_idempotency_key(
        self,
        *,
        task_run_id: str,
        event: str,
        provider: str,
        target: str,
    ) -> NotificationDeliveryRow | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(NotificationDeliveryRow).where(
                    NotificationDeliveryRow.task_run_id == task_run_id,
                    NotificationDeliveryRow.event == event,
                    NotificationDeliveryRow.provider == provider,
                    NotificationDeliveryRow.target == target,
                )
            )
            return result.scalar_one_or_none()

    async def claim_due_deliveries(self, *, now: datetime, limit: int) -> list[dict[str, Any]]:
        """Atomically claim due pending rows by flipping them to ``sending``.

        The UPDATE is guarded by ``status = 'pending'`` and returns its own
        result set via ``RETURNING`` (SQLite >= 3.35, Postgres), so the rows
        handed back are exactly the rows THIS transaction flipped. A separate
        re-SELECT would also match rows a concurrent worker flipped in the
        same window and hand them out twice -- the multi-pod double-send the
        docstring above rules out.

        Each claim stamps a token that completion methods use for fencing.
        """
        if limit <= 0:
            return []
        async with self.session_factory() as session:
            due_ids = (
                (
                    await session.execute(
                        select(NotificationDeliveryRow.id)
                        .where(
                            NotificationDeliveryRow.status == "pending",
                            NotificationDeliveryRow.available_at <= now,
                        )
                        .order_by(NotificationDeliveryRow.available_at, NotificationDeliveryRow.created_at)
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            if not due_ids:
                return []
            claimed = (
                (
                    await session.execute(
                        update(NotificationDeliveryRow)
                        .where(
                            NotificationDeliveryRow.id.in_(due_ids),
                            NotificationDeliveryRow.status == "pending",
                        )
                        .values(status="sending", claim_token=uuid.uuid4().hex, updated_at=now)
                        .returning(NotificationDeliveryRow)
                    )
                )
                .scalars()
                .all()
            )
            await session.commit()
            return [self._to_dict(row) for row in claimed]

    async def reset_stale_sending_rows(self, *, now: datetime, timeout: timedelta) -> int:
        """Flip rows stuck in ``sending`` past ``timeout`` back to ``pending``.

        A row gets stranded there when the process dies between claim and the
        final ``mark_sent``/``mark_failed`` write (SIGKILL/OOM), or when that
        write itself raises. Without this reconciliation such rows sit in
        ``sending`` forever. The accepted price is a possible duplicate push
        for a delivery that actually went out right before the crash -- the
        at-least-once trade-off documented on the outbox. The timeout is
        measured from ``updated_at``, which claim stamps at flip time.
        """
        cutoff = now - timeout
        async with self.session_factory() as session:
            result = await session.execute(
                update(NotificationDeliveryRow)
                .where(
                    NotificationDeliveryRow.status == "sending",
                    NotificationDeliveryRow.updated_at <= cutoff,
                )
                .values(status="pending", claim_token=None, updated_at=now)
            )
            await session.commit()
            return result.rowcount

    async def mark_sent(self, delivery_id: str, *, claim_token: str | None = None) -> dict[str, Any]:
        async with self.session_factory() as session:
            row = await session.get(NotificationDeliveryRow, delivery_id)
            if row is None:
                raise LookupError(f"notification delivery {delivery_id} not found")
            if row.status in _TERMINAL_DELIVERY_STATUSES:
                # A late write after the row was already finalized (a crash
                # handler racing a terminal mark_failed, or a stale claimant)
                # must not reopen or relabel it.
                logger.info("notification delivery %s is already %s; ignoring late mark_sent", delivery_id, row.status)
                return self._to_dict(row)
            if claim_token is not None:
                finalized = await self._fenced_completion(
                    session,
                    delivery_id,
                    claim_token,
                    values={"status": "sent", "sent_at": datetime.now(UTC), "claim_token": None},
                )
                if finalized is None:
                    return await self._fenced_out_row(session, delivery_id, claim_token, "mark_sent")
                await session.commit()
                return self._to_dict(finalized)
            row.status = "sent"
            row.claim_token = None
            row.sent_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return self._to_dict(row)

    @staticmethod
    async def _fenced_completion(
        session: AsyncSession,
        delivery_id: str,
        claim_token: str,
        *,
        values: dict[str, Any],
    ) -> NotificationDeliveryRow | None:
        """Apply a completion only while the token still owns ``sending``."""
        values = {**values, "updated_at": datetime.now(UTC)}
        result = await session.execute(
            update(NotificationDeliveryRow)
            .where(
                NotificationDeliveryRow.id == delivery_id,
                NotificationDeliveryRow.status == "sending",
                NotificationDeliveryRow.claim_token == claim_token,
            )
            .values(**values)
            .returning(NotificationDeliveryRow)
        )
        return result.scalars().first()

    async def _fenced_out_row(
        self,
        session: AsyncSession,
        delivery_id: str,
        claim_token: str,
        operation: str,
    ) -> dict[str, Any]:
        logger.info(
            "notification delivery %s is no longer owned by claim %s; ignoring late %s",
            delivery_id,
            claim_token[:8],
            operation,
        )
        await session.rollback()
        current = await session.get(NotificationDeliveryRow, delivery_id)
        if current is None:
            raise LookupError(f"notification delivery {delivery_id} not found")
        return self._to_dict(current)

    @staticmethod
    def _failure_outcome(
        row: NotificationDeliveryRow,
        *,
        error: str | None,
        count_attempt: bool,
        terminal: bool,
        now: datetime,
    ) -> dict[str, Any]:
        values: dict[str, Any] = {"last_error": error, "claim_token": None, "updated_at": now}
        if terminal:
            values["status"] = "failed"
        elif not count_attempt:
            created_at = row.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            park_expired = (now - created_at) >= _CHANNEL_PARK_MAX_AGE or row.parked_attempts >= _CHANNEL_PARK_MAX_ATTEMPTS
            if park_expired:
                values["status"] = "failed"
                values["last_error"] = error or "channel did not return before parking limit"
            else:
                values["parked_attempts"] = row.parked_attempts + 1
                values["status"] = "pending"
                values["available_at"] = now + timedelta(seconds=_CHANNEL_DOWN_RETRY_SECONDS)
        else:
            attempts = row.attempts + 1
            values["attempts"] = attempts
            if attempts >= row.max_attempts:
                values["status"] = "failed"
            else:
                delay = min(_RETRY_BASE_SECONDS * 2 ** (attempts - 1), _RETRY_MAX_SECONDS)
                values["status"] = "pending"
                values["available_at"] = now + timedelta(seconds=delay)
        return values

    async def mark_failed(
        self,
        delivery_id: str,
        *,
        error: str | None = None,
        count_attempt: bool = True,
        terminal: bool = False,
        claim_token: str | None = None,
    ) -> dict[str, Any]:
        """Record a failed attempt; reschedule with backoff while retries
        remain, otherwise finalize the row as ``failed``.

        With ``count_attempt=False`` the failure is parked instead: the retry
        budget stays intact and the row returns on a flat long backoff. Used
        when the owning channel is not running -- an outage is not the
        delivery's fault and must not be able to exhaust its retries. Parking
        is capped by row age and ``parked_attempts`` so permanently absent
        channels eventually settle to ``failed``.

        With ``terminal=True`` the row is finalized as ``failed`` at once,
        whatever its remaining budget. Used when the delivery can never
        become valid again, such as a target the owner has since
        disconnected: neither waiting nor retrying would make sending it
        right.
        """
        async with self.session_factory() as session:
            row = await session.get(NotificationDeliveryRow, delivery_id)
            if row is None:
                raise LookupError(f"notification delivery {delivery_id} not found")
            if row.status in _TERMINAL_DELIVERY_STATUSES:
                # Terminal states are sticky: a counted or parked mark_failed
                # arriving after a terminal one must not flip the row back to
                # pending and send it later after all.
                logger.info("notification delivery %s is already %s; ignoring late mark_failed", delivery_id, row.status)
                return self._to_dict(row)
            now = datetime.now(UTC)
            values = self._failure_outcome(row, error=error, count_attempt=count_attempt, terminal=terminal, now=now)
            if claim_token is not None:
                updated = await self._fenced_completion(session, delivery_id, claim_token, values=values)
                if updated is None:
                    return await self._fenced_out_row(session, delivery_id, claim_token, "mark_failed")
                await session.commit()
                return self._to_dict(updated)
            for name, value in values.items():
                setattr(row, name, value)
            await session.commit()
            await session.refresh(row)
            return self._to_dict(row)
