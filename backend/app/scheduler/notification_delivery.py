"""Outbox delivery worker for scheduled-task IM notifications (issue #4254).

The completion hook (``ScheduledTaskService._enqueue_run_notifications``)
only writes durable outbox rows; this worker owns the actual IM send.
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
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Resolves a provider name (e.g. "wecom") to a running Channel instance, or
# None when the channel is not configured/running. Sync or async callables
# are both accepted (``ChannelService.get_channel`` is sync).
ChannelResolver = Callable[[str], Any]

_ERROR_TEXT_LIMIT = 500


def _truncate(text: str, *, limit: int = _ERROR_TEXT_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def render_notification_text(delivery: dict[str, Any]) -> str:
    """Render a bounded markdown summary of the run outcome for IM push."""
    payload = delivery.get("payload") or {}
    event = delivery.get("event") or ""
    task_id = payload.get("task_id") or delivery.get("task_id")
    if event == "run_failed":
        lines = ["**Scheduled task failed**", f"Task: `{task_id}`"]
        error = payload.get("error")
        if error:
            lines.append(f"Error: {_truncate(str(error))}")
    else:
        lines = ["**Scheduled task completed**", f"Task: `{task_id}`"]
    if delivery.get("run_id"):
        lines.append(f"Run: `{delivery['run_id']}`")
    return "\n".join(lines)


class NotificationDeliveryWorker:
    """Polls the notification outbox and pushes due deliveries over IM."""

    def __init__(
        self,
        *,
        delivery_repo,
        resolve_channel: ChannelResolver,
        poll_interval_seconds: int = 5,
        batch_size: int = 10,
    ) -> None:
        self._delivery_repo = delivery_repo
        self._resolve_channel = resolve_channel
        self._poll_interval_seconds = poll_interval_seconds
        self._batch_size = batch_size
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def run_once(self, *, now: datetime) -> None:
        rows = await self._delivery_repo.claim_due_deliveries(now=now, limit=self._batch_size)
        for row in rows:
            await self._deliver(row)

    async def _deliver(self, delivery: dict[str, Any]) -> None:
        delivery_id = delivery["id"]
        provider = delivery.get("provider") or ""
        # Re-check channel liveness at delivery time, not enqueue time: the
        # channel may have been disabled or disconnected after the outbox row
        # was written, and the row stays retryable for when it comes back.
        channel = self._resolve_channel(provider)
        if inspect.isawaitable(channel):
            channel = await channel
        if channel is None:
            await self._delivery_repo.mark_failed(delivery_id, error=f"channel '{provider}' is not running")
            return
        try:
            await channel.send_notification(
                target=delivery.get("target") or "",
                text_markdown=render_notification_text(delivery),
            )
        except Exception as exc:
            await self._delivery_repo.mark_failed(delivery_id, error=str(exc))
            return
        await self._delivery_repo.mark_sent(delivery_id)

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
