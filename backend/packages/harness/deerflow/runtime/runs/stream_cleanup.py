from __future__ import annotations

import asyncio
import inspect
import sys
from typing import Any


class AgentStreamCloseCancelledError(RuntimeError):
    """Raised when the stream cancels its own asynchronous teardown."""


def _stream_close_cancelled(exc: asyncio.CancelledError) -> AgentStreamCloseCancelledError:
    error = AgentStreamCloseCancelledError("Agent stream cancelled its own close operation")
    error.__cause__ = exc
    return error


async def close_agent_stream(stream: Any) -> None:
    """Close an agent stream before propagating caller cancellation.

    Stream teardown owns provider, graph, and tool cleanup that must finish
    before the caller releases run-scoped resources.  Host cancellation is
    therefore deferred while the close task drains.  A cancellation raised by
    the close awaitable itself remains visible to the caller.
    """
    close = getattr(stream, "aclose", None)
    if close is None:
        return
    caller = asyncio.current_task()
    active_exception = sys.exception()
    cancellation_count = caller.cancelling() if caller is not None else 0
    close_failure: Exception | None = None
    result: Any = None
    try:
        result = close()
    except asyncio.CancelledError as exc:
        close_failure = _stream_close_cancelled(exc)
    except Exception as exc:
        close_failure = exc
    if caller is None:  # pragma: no cover - every running coroutine has a task
        if inspect.isawaitable(result):
            await result
        elif close_failure is not None:
            raise close_failure
        return

    deferred_cancellation: asyncio.CancelledError | None = None

    def consume_new_host_cancellation(exc: asyncio.CancelledError) -> bool:
        nonlocal cancellation_count, deferred_cancellation
        current_count = caller.cancelling()
        new_cancellations = current_count - cancellation_count
        if new_cancellations <= 0:
            return False
        preserve_cancellation = active_exception is None and deferred_cancellation is None
        cancellations_to_consume = new_cancellations - int(preserve_cancellation)
        for _ in range(cancellations_to_consume):
            caller.uncancel()
        if preserve_cancellation:
            deferred_cancellation = exc
        cancellation_count = caller.cancelling()
        return True

    # Deliver cancellation that was already pending before close_task exists.
    # A zero count delta here is therefore host-side, not close-task cancellation.
    try:
        await asyncio.sleep(0)
    except asyncio.CancelledError as exc:
        current_count = caller.cancelling()
        new_cancellations = max(0, current_count - cancellation_count)
        preserve_cancellation = active_exception is None
        cancellations_to_consume = new_cancellations - int(preserve_cancellation and new_cancellations > 0)
        for _ in range(cancellations_to_consume):
            caller.uncancel()
        if preserve_cancellation:
            deferred_cancellation = exc
        cancellation_count = caller.cancelling()
    else:
        cancellation_count = caller.cancelling()

    close_task = asyncio.ensure_future(result) if inspect.isawaitable(result) else None
    while close_task is not None and not close_task.done():
        try:
            await asyncio.shield(close_task)
        except asyncio.CancelledError as exc:
            if not consume_new_host_cancellation(exc):
                close_failure = _stream_close_cancelled(exc)
                break
        except Exception as exc:
            close_failure = exc
            break

    if close_task is not None and close_task.done():
        try:
            close_task.result()
        except asyncio.CancelledError as exc:
            close_failure = _stream_close_cancelled(exc)
        except Exception as exc:
            close_failure = exc

    if active_exception is not None:
        if close_failure is not None:
            raise active_exception from close_failure
        return
    if deferred_cancellation is not None:
        if close_failure is not None:
            raise deferred_cancellation from close_failure
        raise deferred_cancellation
    if close_failure is not None:
        raise close_failure
