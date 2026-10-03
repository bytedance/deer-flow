"""Shared helper for persistent router writes drained across cancellation.

The persistent-write surfaces used to fork one drain wrapper each
(``_drained_write`` in ``routers/agents.py``, ``_run_store_mutation`` in
``routers/subagents.py``, the inline managed-models save drain). Route
modules copy this one canonical implementation instead.
"""

import asyncio
import logging
from collections.abc import Callable

from deerflow.utils.file_io import await_drained

logger = logging.getLogger(__name__)


async def run_drained_write[**P, T](
    action: str,
    func: Callable[P, T],
    expected_errors: tuple[type[Exception], ...] = (),
    /,
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """Run a persistent write off the event loop and drain it across cancellation.

    A client that disconnects mid-request cancels the handler task: a bare
    ``asyncio.to_thread`` either cancels a still-queued worker — the write
    silently never happens — or detaches from a running one, dropping its
    failure because the handler's ``except`` never runs. ``await_drained``
    lets the worker finish first; expected domain errors re-raise unlogged
    (the caller maps them to a 4xx while still connected), anything else is
    logged with the exception type only — the text can carry user content.
    """

    def _logged() -> T:
        try:
            return func(*args, **kwargs)
        except expected_errors:
            raise
        except Exception as exc:
            # Non-cancelled failures are logged again by the outer route handler.
            logger.error("%s failed (%s)", action, type(exc).__name__)
            raise

    return await await_drained(asyncio.to_thread(_logged))
