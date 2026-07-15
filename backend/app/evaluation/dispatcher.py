from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


class EvalDispatcher:
    def __init__(
        self,
        *,
        repository,
        service,
        poll_interval_seconds: float = 5.0,
        lease_seconds: int = 300,
        batch_size: int = 1,
    ) -> None:
        self._repo = repository
        self._service = service
        self._poll_interval_seconds = poll_interval_seconds
        self._lease_seconds = lease_seconds
        self._batch_size = batch_size
        self._lease_owner = f"{socket.gethostname()}:{uuid.uuid4().hex}"
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    @property
    def lease_owner(self) -> str:
        return self._lease_owner

    async def run_once(self, *, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        await self._repo.requeue_stale_runs(now=current)
        claimed = await self._repo.claim_queued_runs(
            now=current,
            lease_owner=self._lease_owner,
            lease_seconds=self._lease_seconds,
            limit=self._batch_size,
        )
        for run in claimed:
            heartbeat_task = asyncio.create_task(self._heartbeat_run(run["id"]))
            try:
                await self._service.run_eval(run["id"])
            except Exception as exc:
                logger.exception("Evaluation run %s failed", run["id"])
                await self._repo.update_report(
                    run["id"],
                    status="failed",
                    error=str(exc),
                    finished_at=datetime.now(UTC),
                )
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval_seconds)
            except TimeoutError:
                continue

    async def _heartbeat_run(self, run_id: str) -> None:
        interval = max(0.05, min(self._poll_interval_seconds, self._lease_seconds / 3))
        while True:
            await asyncio.sleep(interval)
            renewed = await self._repo.renew_lease(
                run_id,
                lease_owner=self._lease_owner,
                now=datetime.now(UTC),
                lease_seconds=self._lease_seconds,
            )
            if not renewed:
                return
