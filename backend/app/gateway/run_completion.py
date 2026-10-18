"""Gateway-owned completion work for successful agent runs.

The runtime owns the completion hook boundary, but it must not import Gateway
services. This module is the Gateway-side adapter: it runs checkpoint
retention while the worker's finalizing fence is still held and then delegates
to the optional scheduler observer. It uses both a durable checkpoint-write
reservation and the process-local keyed lock. Retention is deliberately
fail-open so a storage cleanup problem cannot change a completed run or
prevent scheduled task finalization.
"""

from __future__ import annotations

import logging
from typing import Any

from app.gateway.checkpoint_retention import enforce_trailing_duration_retention
from deerflow.runtime import ThreadOperationKind
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.worker import _checkpoint_thread_lock

logger = logging.getLogger(__name__)


def _is_successful_terminal_run(record: Any) -> bool:
    status = getattr(record, "status", None)
    status_value = getattr(status, "value", status)
    if status_value != RunStatus.success.value:
        return False
    abort_event = getattr(record, "abort_event", None)
    return abort_event is None or not abort_event.is_set()


async def run_gateway_completion_hooks(
    record: Any,
    *,
    checkpointer: Any | None,
    run_manager: Any | None = None,
    scheduled_service: Any | None = None,
) -> None:
    """Run Gateway post-duration hooks for one terminal run.

    The worker invokes this callback after its duration metadata write and
    before releasing the same-thread finalizing barrier. Retention therefore
    classifies and deletes under the durable reservation and shared checkpoint
    lock while no successor run or history migration can fork/write against
    the just-written leaf. The scheduler observer is called even when
    retention fails, preserving its existing completion contract.
    """

    if _is_successful_terminal_run(record) and checkpointer is not None:
        try:

            async def retain() -> Any:
                return await enforce_trailing_duration_retention(
                    checkpointer,
                    record.thread_id,
                    thread_lock=_checkpoint_thread_lock(record.thread_id),
                )

            if run_manager is None:
                report = await retain()
            else:
                # The keyed lock protects this process. The durable operation
                # reservation closes the same race across Gateway workers: a
                # peer run cannot fork while classification and deletion are
                # in progress. A conflict means another operation won the
                # admission race, so leaving the leaf for a later run is safe.
                async with run_manager.reserve_thread_operation(
                    record.thread_id,
                    kind=ThreadOperationKind.checkpoint_write,
                    user_id=record.user_id,
                ):
                    report = await retain()
            if report.deleted_checkpoint_ids:
                logger.info(
                    "Checkpoint retention removed %d duration leaf for thread %s after run %s",
                    len(report.deleted_checkpoint_ids),
                    record.thread_id,
                    record.run_id,
                )
        except Exception:
            # Retention is a storage hygiene pass. A backend outage, an
            # unsupported saver, or a schema mismatch must never rewrite a
            # successful run or suppress scheduled-task finalization.
            logger.warning(
                "Checkpoint retention failed after run %s (non-fatal)",
                getattr(record, "run_id", "unknown"),
                exc_info=True,
            )

    if scheduled_service is not None:
        await scheduled_service.handle_run_completion(record)


__all__ = ["run_gateway_completion_hooks"]
