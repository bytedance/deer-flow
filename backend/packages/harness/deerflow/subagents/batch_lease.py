"""Owned lease heartbeat for one durable batch execution."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


class BatchItemLease:
    """Keep initialization and execution leased until their supervisor exits."""

    def __init__(self, repository, *, item_id: str, owner: str, seconds: int) -> None:
        self._repository = repository
        self.item_id = item_id
        self.owner = owner
        self._seconds = seconds
        self.valid = True
        self._stop = asyncio.Event()
        self._renew_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    async def renew(self) -> bool:
        async with self._renew_lock:
            if not self.valid:
                return False
            try:
                result = await self._repository.renew_item_lease(self.item_id, lease_owner=self.owner, lease_seconds=self._seconds, now=datetime.now(UTC))
                self.valid = result["valid"]
            except Exception:
                self.valid = False
                logger.exception("Durable batch lease renewal failed (item_id=%s)", self.item_id)
            return self.valid

    async def _heartbeat(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(1.0, self._seconds / 3))
            except TimeoutError:
                if not await self.renew():
                    return

    async def __aenter__(self) -> BatchItemLease:
        if await self.renew():
            self._task = asyncio.create_task(self._heartbeat(), name=f"batch-item-lease-{self.item_id}")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        if self._task is None:
            return
        cancellation: asyncio.CancelledError | None = None
        # Never leave a renewal writing after this execution releases ownership.
        # Database calls retain their normal connection/statement timeouts.
        while not self._task.done():
            try:
                await asyncio.wait({self._task})
            except asyncio.CancelledError as error:
                if cancellation is None:
                    cancellation = error
        self._task.result()
        if cancellation is not None:
            raise cancellation
