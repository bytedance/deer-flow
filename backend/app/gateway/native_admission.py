"""Trusted admission hook between durable native admission and task attachment.

Only operator startup code may install app.state.native_run_admission_host.
HTTP request fields cannot select the host. A host stages its durable work and
hands off the pending RunManager record before returning True. False keeps the
normal local native worker path. The dispatcher owns queued lease renewal and
recovery; this hook does not create a second graph or execution runtime.
"""

import asyncio
from collections.abc import Awaitable, Callable

from deerflow.runtime.runs.manager import RunManager, RunRecord, RunStartupError


async def attach_native_admission(request, manager: RunManager, record: RunRecord, worker_factory: Callable[[RunRecord], Awaitable[None]]) -> None:
    host = getattr(request.app.state, "native_run_admission_host", None)
    try:
        if host is not None and await host.admit(record):
            if not record.ownership_lost or record.task is not None:
                raise RunStartupError("Native admission host did not hand off the pending run")
            return
    except BaseException as exc:
        # A handed-off run belongs to the dispatcher. Never finalize it from
        # the former owner, even if the host lost its acknowledgement.
        if not record.ownership_lost:
            await manager.fail_start_if_pending(record.run_id, error=f"Native admission host failed: {type(exc).__name__}")
        raise
    if record.ownership_lost:
        raise RunStartupError("Native admission host declined after handing off ownership")
    worker = worker_factory(record)
    try:
        record.task = asyncio.create_task(worker)
    except Exception as exc:
        worker.close()
        await manager.fail_start_if_pending(record.run_id, error=f"Failed to attach run worker: {exc}")
        raise
