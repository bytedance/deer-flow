"""Delivery dispatcher routes scheduled-job results to the right sink.

The dispatcher is the only ``DeliverySink`` the executor talks to. It
inspects ``job["source_channel"]`` and dispatches:

- ``"web"``                  → ``InAppNotifier`` (logs for now; PR #8 will
                               persist a notifications row when the Web
                               UI lands)
- ``"im:<platform>:..."``    → ``IMPusher`` (publishes via MessageBus)
- anything else              → log a warning and no-op

Falls back to ``LoggingDeliverySink`` semantics when both sub-sinks are
missing — keeps the executor contract intact.
"""

from __future__ import annotations

import logging
from typing import Any

from app.scheduled_jobs.im_pusher import IMPusher

logger = logging.getLogger(__name__)


class InAppNotifier:
    """Web in-app notification sink.

    MVP behaviour: log only. PR #8 will swap this for a real
    notifications table write when the Web bell UI ships.
    """

    async def deliver(
        self,
        *,
        job: dict[str, Any],
        thread_id: str,
        result_text: str,
        status: str,
        error_msg: str | None = None,
    ) -> None:
        preview = (result_text or "")[:80].replace("\n", " ")
        logger.info(
            "scheduled_job in-app notification: job=%s user=%s status=%s preview=%r",
            job.get("id"),
            job.get("user_id"),
            status,
            preview,
        )


class DeliveryDispatcher:
    """Routes by ``source_channel`` to the right sink.

    Satisfies the ``DeliverySink`` protocol so the executor doesn't need
    to know about IM vs Web vs anything else.
    """

    def __init__(
        self,
        *,
        im_pusher: IMPusher | None = None,
        in_app: InAppNotifier | None = None,
    ) -> None:
        self._im = im_pusher
        self._in_app = in_app or InAppNotifier()

    async def deliver(
        self,
        *,
        job: dict[str, Any],
        thread_id: str,
        result_text: str,
        status: str,
        error_msg: str | None = None,
    ) -> None:
        source = job.get("source_channel", "web")

        if source == "web":
            await self._in_app.deliver(
                job=job,
                thread_id=thread_id,
                result_text=result_text,
                status=status,
                error_msg=error_msg,
            )
            return

        if source.startswith("im:"):
            if self._im is None:
                logger.warning(
                    "im source_channel but no IMPusher configured; falling back to log: job=%s source=%s",
                    job.get("id"),
                    source,
                )
                return
            await self._im.push(
                job=job,
                thread_id=thread_id,
                result_text=result_text,
                status=status,
                error_msg=error_msg,
            )
            return

        logger.warning(
            "unknown source_channel %r for job %s; delivery skipped",
            source,
            job.get("id"),
        )
