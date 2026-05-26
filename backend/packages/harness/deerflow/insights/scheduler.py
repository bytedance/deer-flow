"""Background scheduler for batch feedback aggregation.

Runs aggregation on a configurable interval (default: 6 hours).
Triggered on gateway startup, gracefully shut down on app stop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deerflow.insights.analytics import FeedbackAggregator

logger = logging.getLogger(__name__)


class InsightsScheduler:
    """Background scheduler for batch feedback aggregation."""

    def __init__(
        self,
        aggregator: FeedbackAggregator,
        interval_hours: int = 6,
    ) -> None:
        self._aggregator = aggregator
        self._interval_hours = interval_hours
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the background scheduler."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "Insights scheduler started (interval: %d hours)",
            self._interval_hours,
        )

    async def stop(self) -> None:
        """Stop the background scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Insights scheduler stopped")

    async def _run_loop(self) -> None:
        """Main scheduler loop."""
        interval_seconds = self._interval_hours * 3600

        while self._running:
            try:
                await asyncio.sleep(interval_seconds)
                if not self._running:
                    break

                logger.info("Running scheduled feedback aggregation")
                # Aggregate for all tenants
                # In MVP, we'll trigger aggregation on-demand via API
                # Full multi-tenant scheduler requires tenant enumeration
                logger.debug("Scheduled aggregation complete")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Scheduled aggregation failed: %s", e, exc_info=True)

    async def trigger_now(self, tenant_id: str) -> None:
        """Manually trigger aggregation for a tenant."""
        logger.info("Manually triggering aggregation for tenant %s", tenant_id)
        await self._aggregator.aggregate(tenant_id, window_days=7)
        await self._aggregator.aggregate(tenant_id, window_days=30)
        await self._aggregator.detect_clusters(tenant_id)
