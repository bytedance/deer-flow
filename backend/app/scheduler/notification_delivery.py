"""Outbox delivery worker for scheduled-task IM notifications (issue #4254).

The scheduler's finalization observer (``ScheduledTaskService._on_finalization``)
writes durable outbox rows in the transaction that records each outcome; this
worker owns the actual IM send. Notice text lives in ``notification_text``.
Execution state and delivery state stay separated: the worker moves outbox
rows through ``pending -> sending -> sent|failed`` and never touches run or
task rows. Retries with backoff live in the repository (``mark_failed``);
the worker just claims what is due and reports outcomes.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.channels.base import ChannelUnavailable
from app.channels.capabilities import supports_proactive_notifications
from app.scheduler.notification_text import DEFAULT_NOTIFICATION_LOCALE, redact_egress_text, render_notification_text, wants_result_summary

__all__ = ["NotificationDeliveryWorker", "redact_egress_text", "render_notification_text"]

logger = logging.getLogger(__name__)

# Resolves a provider name (e.g. "wecom") to a running Channel instance, or
# None when the channel is not configured/running. Sync or async callables
# are both accepted (``ChannelService.get_channel`` is sync).
ChannelResolver = Callable[[str], Any]

# Resolves the run's final reply, keyed ``(run_id, owner_user_id)``, or None
# when no reply is available. The renderer reduces it to the tasks page's
# one-line run summary. Sync or async callables are both accepted; failures
# send the notice without a result line.
SummaryResolver = Callable[[str, str | None], Any]

# Lists an owner's channel connections (``ChannelConnectionRepository
# .list_connections``), each a dict with ``provider``, ``external_account_id``
# and ``status``. Sync or async callables are both accepted. The worker uses
# it to confirm, at send time, that the delivery's target is still bound.
ConnectionResolver = Callable[[str], Any]

# A claimed row stuck in "sending" longer than this is considered orphaned
# (process died between claim and the final status write) and flipped back
# to pending. Generous on purpose: a healthy send plus status write finishes
# in seconds, and resetting too eagerly would double-send live deliveries.
_STALE_SENDING_TIMEOUT_SECONDS = 600

# Matches Gateway ``_SHUTDOWN_HOOK_TIMEOUT_SECONDS``: this worker sits in
# front of external IM I/O, so an unbounded join would stall the whole
# lifespan shutdown path the channel-service bound was added to protect.
_STOP_TIMEOUT_SECONDS = 5.0


class NotificationDeliveryWorker:
    """Polls the notification outbox and pushes due deliveries over IM."""

    def __init__(
        self,
        *,
        delivery_repo,
        resolve_channel: ChannelResolver,
        poll_interval_seconds: int = 5,
        batch_size: int = 10,
        resolve_run_summary: SummaryResolver | None = None,
        resolve_connections: ConnectionResolver | None = None,
        stale_sending_timeout_seconds: int = _STALE_SENDING_TIMEOUT_SECONDS,
        stop_timeout_seconds: float = _STOP_TIMEOUT_SECONDS,
        default_locale: str = DEFAULT_NOTIFICATION_LOCALE,
    ) -> None:
        self._delivery_repo = delivery_repo
        self._resolve_channel = resolve_channel
        self._resolve_run_summary = resolve_run_summary
        self._resolve_connections = resolve_connections
        self._poll_interval_seconds = poll_interval_seconds
        self._batch_size = batch_size
        self._stale_sending_timeout_seconds = stale_sending_timeout_seconds
        self._stop_timeout_seconds = stop_timeout_seconds
        # ``channel_connections.notification_locale``: the language of rows
        # whose owner has no UI language preference (and of legacy rows).
        self._default_locale = default_locale
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._lifecycle_lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._task is not None:
                return
            self._stop.clear()
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            task = self._task
            if task is None:
                return
            self._stop.set()
            try:
                try:
                    await asyncio.wait_for(task, timeout=self._stop_timeout_seconds)
                except TimeoutError:
                    logger.warning(
                        "Notification delivery worker stop exceeded %.1fs; cancelling in-flight poll",
                        self._stop_timeout_seconds,
                    )
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            finally:
                if self._task is task:
                    self._task = None

    async def run_once(self, *, now: datetime) -> None:
        await self._recover_stale_sending(now)
        rows = await self._delivery_repo.claim_due_deliveries(now=now, limit=self._batch_size)
        for row in rows:
            try:
                await self._deliver(row)
            except Exception:
                # One poisoned row must not abort the loop and strand the
                # rest of the claimed batch in "sending". Best-effort
                # mark_failed; if even that raises, the stale reset above
                # reclaims the row on a later poll.
                logger.exception("Notification delivery %s crashed; isolating from the rest of the batch", row.get("id"))
                try:
                    await self._delivery_repo.mark_failed(row["id"], claim_token=row.get("claim_token"), error="delivery crashed before completion")
                except Exception:
                    logger.warning("Could not mark crashed delivery %s as failed; stale reset will recover it", row.get("id"), exc_info=True)

    async def _recover_stale_sending(self, now: datetime) -> None:
        """Lease-style reconciliation, run before every claim (the first poll
        after startup is covered too). Mirrors how the scheduler recovers
        stale active runs."""
        try:
            reset = await self._delivery_repo.reset_stale_sending_rows(
                now=now,
                timeout=timedelta(seconds=self._stale_sending_timeout_seconds),
            )
            if reset:
                logger.info("Recovered %s notification deliveries stuck in 'sending'", reset)
        except Exception:
            logger.warning("Failed to reset stale sending rows; retrying next poll", exc_info=True)

    async def _resolve_summary(self, delivery: dict[str, Any]) -> str | None:
        """Best-effort lookup of the run's final reply at delivery time.

        Read at delivery time, not enqueue time, so retried deliveries see
        the freshest value and the outbox payload stays small. Any failure
        sends the notice without its result line instead of blocking it.
        """
        if self._resolve_run_summary is None:
            return None
        run_id = delivery.get("run_id")
        if not run_id:
            return None
        try:
            summary = self._resolve_run_summary(run_id, delivery.get("owner_user_id"))
            if inspect.isawaitable(summary):
                summary = await summary
        except Exception:
            logger.warning("Failed to resolve run summary for run %s; sending skeleton notification", run_id, exc_info=True)
            return None
        if isinstance(summary, str) and summary.strip():
            return summary
        return None

    async def _target_still_connected(self, delivery: dict[str, Any]) -> bool | None:
        """Return whether the delivery's ``(provider, target)`` is still a
        ``connected`` identity of its owner, or None when that could not be
        determined (no resolver wired, or the lookup failed).

        The outbox row was written while the identity was connected, but
        delivery can run up to a day later (counted retries, then parking),
        and ``disconnect_connection`` only flips the connection row. The
        lookup is scoped to the row's own ``owner_user_id`` so it cannot
        match another owner's binding of the same external account.
        """
        if self._resolve_connections is None:
            return None
        owner_user_id = delivery.get("owner_user_id")
        provider = delivery.get("provider")
        target = delivery.get("target")
        if not owner_user_id or not provider or not target:
            return None
        try:
            connections = self._resolve_connections(owner_user_id)
            if inspect.isawaitable(connections):
                connections = await connections
        except Exception:
            logger.warning("Failed to check channel connections for delivery %s; parking it", delivery.get("id"), exc_info=True)
            return None
        if connections is None:
            connections = []
        if not isinstance(connections, (list, tuple)):
            # An unexpected shape is a lookup problem, not evidence that the
            # binding is gone: iterating a dict or a str would "find" nothing
            # and drop the row for good.
            logger.warning("Channel connection lookup for delivery %s returned %s, not a list; parking it", delivery.get("id"), type(connections).__name__)
            return None
        for connection in connections:
            if not isinstance(connection, dict):
                continue
            # The resolver is called with the row's owner; a row that names a
            # different owner is skipped as well, so a resolver that is not
            # owner-scoped still cannot make another user's binding count.
            row_owner = connection.get("owner_user_id")
            if row_owner is not None and row_owner != owner_user_id:
                continue
            if connection.get("provider") == provider and connection.get("external_account_id") == target and connection.get("status") == "connected":
                return True
        return False

    async def _deliver(self, delivery: dict[str, Any]) -> None:
        delivery_id = delivery["id"]
        provider = delivery.get("provider") or ""
        if not supports_proactive_notifications(provider):
            # The scheduler enqueues only for providers with proactive push;
            # a row for any other provider predates that rule. It can never
            # be sent, so it ends now instead of using up its retries.
            await self._delivery_repo.mark_failed(
                delivery_id,
                claim_token=delivery.get("claim_token"),
                error="provider does not support proactive notifications",
                terminal=True,
            )
            return
        if self._resolve_connections is not None:
            # Re-check the binding at delivery time, before anything else: a
            # target the owner has disconnected since enqueue must never
            # receive the push, however long the row waited, and it must not
            # sit in parking for a day either when the channel is also down
            # (disconnecting a provider revokes its connections and stops its
            # channel together). A lookup failure parks instead, so a
            # transient store error neither drops nor sends the row.
            still_connected = await self._target_still_connected(delivery)
            if still_connected is False:
                await self._delivery_repo.mark_failed(
                    delivery_id,
                    claim_token=delivery.get("claim_token"),
                    error=f"target is no longer a connected {provider} identity of its owner",
                    terminal=True,
                )
                return
            if still_connected is None:
                await self._delivery_repo.mark_failed(delivery_id, claim_token=delivery.get("claim_token"), error="could not verify the target's channel connection", count_attempt=False)
                return
        # Re-check channel liveness at delivery time, not enqueue time: the
        # channel may have been disabled or disconnected after the outbox row
        # was written, and the row stays retryable for when it comes back.
        channel = self._resolve_channel(provider)
        if inspect.isawaitable(channel):
            channel = await channel
        if channel is None or not getattr(channel, "is_running", True):
            # Channel outage is not the delivery's fault: park the row
            # without consuming its retry budget so it survives an
            # hours-long outage and delivers once the channel returns.
            await self._delivery_repo.mark_failed(delivery_id, claim_token=delivery.get("claim_token"), error=f"channel '{provider}' is not running", count_attempt=False)
            return
        enriched = delivery
        if wants_result_summary(delivery):
            summary = await self._resolve_summary(delivery)
            if summary is not None:
                # Copy before enriching: the claimed row must not be mutated
                # in place (its payload is the durable outbox snapshot).
                enriched = dict(delivery)
                enriched["payload"] = {**(delivery.get("payload") or {}), "result_summary": summary}
        try:
            await channel.send_notification(
                target=delivery.get("target") or "",
                text_markdown=render_notification_text(enriched, default_locale=self._default_locale),
            )
        except ChannelUnavailable as exc:
            await self._delivery_repo.mark_failed(delivery_id, claim_token=delivery.get("claim_token"), error=str(exc), count_attempt=False)
            return
        except Exception as exc:
            await self._delivery_repo.mark_failed(delivery_id, claim_token=delivery.get("claim_token"), error=str(exc))
            return
        await self._delivery_repo.mark_sent(delivery_id, claim_token=delivery.get("claim_token"))

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once(now=datetime.now(UTC))
            except Exception:
                # A transient DB error must not kill the poller task for the
                # rest of the process life (same policy as the scheduler).
                logger.exception("Notification delivery poll failed; retrying next interval")
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._poll_interval_seconds,
                )
            except TimeoutError:
                continue
