"""Fail-open notification helpers for extension runtime hooks."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from typing import Any

from deerflow_extension_api import (
    EXTENSION_TASK_STORE_KEY,
    ExtensionData,
    SystemModelRequest,
    SystemModelResult,
    SystemOperationKind,
    TaskInfo,
    TaskOutcome,
)

from deerflow.extensions.registry import LoadedExtensions

logger = logging.getLogger(__name__)


def lead_task_id(run_id: str) -> str:
    """Return the stable task id for a lead run, including continuations."""
    return run_id


def lead_task_outcome(*, aborted: bool, succeeded: bool) -> TaskOutcome:
    """Classify a lead run conservatively from its terminal state."""
    if aborted:
        return TaskOutcome.ABORTED
    if succeeded:
        return TaskOutcome.COMPLETED
    return TaskOutcome.FAILED


def subagent_task_outcome(*, cancelled: bool, succeeded: bool) -> TaskOutcome:
    """Classify a subagent execution conservatively from its terminal state."""
    if cancelled:
        return TaskOutcome.ABORTED
    if succeeded:
        return TaskOutcome.COMPLETED
    return TaskOutcome.FAILED


def _host_is_cancelling() -> bool:
    """Whether the host task itself is being cancelled.

    Fail-open has to be decided by the *origin* of a failure, not by its base
    class. ``CancelledError`` reaches a contributor's ``except`` for two very
    different reasons: the host task was cancelled (must propagate), or the
    contributor raised it on its own — an extension implementing an internal
    timeout with cancellation, for instance (must stay contained). Only the
    first increments the task's cancellation counter, so it is what tells the
    two apart.
    """
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


async def _notify_each(
    contributors: tuple[tuple[str, Any], ...],
    hook: str,
    invoke: Callable[[Any], Any],
    task_id: str,
    timeout: float | None,
) -> None:
    """Invoke contributors in order, fail-open, within one shared budget."""
    loop = asyncio.get_running_loop()
    deadline = None if timeout is None else loop.time() + timeout
    for source, contributor in contributors:
        try:
            call = invoke(contributor)
            if deadline is None:
                await call
                continue

            remaining = deadline - loop.time()
            if remaining <= 0:
                close = getattr(call, "close", None)
                if callable(close):
                    close()
                logger.warning(
                    "Extension %s: %s skipped for task %s; the %.1fs notification budget was spent",
                    source,
                    hook,
                    task_id,
                    timeout,
                )
                continue
            await asyncio.wait_for(call, remaining)
        except TimeoutError:
            if deadline is not None and loop.time() >= deadline:
                # Budget exhaustion mid-hook is the same expected operational
                # condition as the skip above, so it stays a warning rather
                # than a hook failure with an asyncio-internal traceback.
                logger.warning(
                    "Extension %s: %s timed out for task %s; the %.1fs notification budget was spent",
                    source,
                    hook,
                    task_id,
                    timeout,
                )
            else:
                # A TimeoutError the contributor raised on its own is a hook
                # failure like any other.
                logger.exception(
                    "Extension %s: %s failed for task %s",
                    source,
                    hook,
                    task_id,
                )
        except asyncio.CancelledError:
            if _host_is_cancelling():
                raise
            # The contributor raised it, so containing it keeps one broken
            # extension from skipping its successors — and, at the task-stop
            # site, from turning a run's cleanup into a deferred interrupt.
            logger.exception(
                "Extension %s: %s raised CancelledError for task %s",
                source,
                hook,
                task_id,
            )
        except Exception:
            logger.exception(
                "Extension %s: %s failed for task %s",
                source,
                hook,
                task_id,
            )


# Gateway registers its serving loop here. Subagents can run on isolated event
# loops, but extension resources must always be touched on the loop where they
# were started.
_notify_loop: asyncio.AbstractEventLoop | None = None
_pending_dispatches: set[asyncio.Future[Any]] = set()
_warned_no_loop = False
_system_observations_enabled = True


def set_extension_notify_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Bind extension notifications to the loop that owns extension resources."""
    global _notify_loop, _system_observations_enabled, _warned_no_loop
    _notify_loop = loop
    _system_observations_enabled = True
    _warned_no_loop = False


def reset_extension_notify_loop() -> None:
    """Remove the process-wide loop binding during host shutdown or tests."""
    global _notify_loop, _system_observations_enabled, _warned_no_loop
    _notify_loop = None
    _system_observations_enabled = True
    _warned_no_loop = False
    _pending_dispatches.clear()


def suspend_extension_system_observations() -> None:
    """Drop new fire-and-forget observations while awaited hooks still drain."""
    global _system_observations_enabled
    if _notify_loop is not None:
        _system_observations_enabled = False


async def _notify_each_on_extension_loop(
    contributors: tuple[tuple[str, Any], ...],
    hook: str,
    invoke: Callable[[Any], Any],
    task_id: str,
    timeout: float | None,
) -> None:
    loop = _notify_loop
    current_loop = asyncio.get_running_loop()
    if loop is None or loop is current_loop:
        await _notify_each(contributors, hook, invoke, task_id, timeout)
        return
    if not loop.is_running():
        logger.warning(
            "No running loop registered for awaited extension hook; %s for %s was dropped",
            hook,
            task_id,
        )
        return

    notification = _notify_each(contributors, hook, invoke, task_id, timeout)
    try:
        future = asyncio.run_coroutine_threadsafe(notification, loop)
    except Exception:
        notification.close()
        logger.exception(
            "Could not dispatch extension %s for task %s to the registered loop",
            hook,
            task_id,
        )
        return

    try:
        wrapped = asyncio.wrap_future(future)
        if timeout is None:
            await wrapped
        else:
            await asyncio.wait_for(wrapped, timeout)
    except TimeoutError:
        future.cancel()
        logger.warning(
            "Extension %s dispatch timed out for task %s after %.1fs",
            hook,
            task_id,
            timeout,
        )
    except asyncio.CancelledError:
        future.cancel()
        raise
    except Exception:
        logger.exception(
            "Extension %s dispatch failed for task %s",
            hook,
            task_id,
        )


async def notify_task_start(
    extensions: LoadedExtensions,
    task_store: ExtensionData,
    info: TaskInfo,
    *,
    timeout: float | None = None,
) -> None:
    await _notify_each_on_extension_loop(
        extensions.task_lifecycle,
        "on_task_start",
        lambda contributor: contributor.on_task_start(
            extensions.app_store,
            task_store,
            info,
        ),
        info.task_id,
        timeout,
    )


async def notify_task_stop(
    extensions: LoadedExtensions,
    task_store: ExtensionData,
    info: TaskInfo,
    outcome: TaskOutcome,
    *,
    timeout: float | None = None,
) -> None:
    await _notify_each_on_extension_loop(
        extensions.task_lifecycle,
        "on_task_stop",
        lambda contributor: contributor.on_task_stop(
            extensions.app_store,
            task_store,
            info,
            outcome,
        ),
        info.task_id,
        timeout,
    )


async def notify_system_model_call(
    extensions: LoadedExtensions,
    task_store: ExtensionData | None,
    kind: SystemOperationKind,
    request: SystemModelRequest,
    result: SystemModelResult,
    *,
    timeout: float | None = None,
) -> None:
    """Notify the observers from one immutable extension snapshot."""
    if not extensions.system_model_observers:
        return
    store = task_store if task_store is not None else ExtensionData("detached")
    await _notify_each_on_extension_loop(
        extensions.system_model_observers,
        "on_system_model_call",
        lambda observer: observer.on_system_model_call(
            extensions.app_store,
            store,
            kind,
            request,
            result,
        ),
        f"{store.scope_id} ({kind.value})",
        timeout,
    )


def task_store_for_system_call(invoke_config: object) -> ExtensionData | None:
    """Recover the live task store from a legacy top-level runtime context."""
    if not isinstance(invoke_config, Mapping):
        return None
    context = invoke_config.get("context")
    if not isinstance(context, Mapping):
        return None
    store = context.get(EXTENSION_TASK_STORE_KEY)
    return store if isinstance(store, ExtensionData) else None


async def observe_system_model_call(
    extensions: LoadedExtensions,
    kind: SystemOperationKind,
    *,
    messages: Any,
    model_name: str | None,
    invoke_config: Any,
    invoke: Callable[[], Awaitable[Any]],
    task_store: ExtensionData | None = None,
    timeout: float | None = None,
) -> Any:
    """Invoke a system-owned model call and report either terminal path."""
    if not extensions.has_system_model_observers:
        return await invoke()

    store = task_store if task_store is not None else task_store_for_system_call(invoke_config)
    request = SystemModelRequest(
        messages=messages,
        model_name=model_name,
        invoke_config=(invoke_config if isinstance(invoke_config, Mapping) else None),
    )
    started = time.monotonic()
    try:
        response = await invoke()
    except asyncio.CancelledError as exc:
        # Cancellation is a terminal path as well: interrupt/rollback admission
        # and shutdown both cancel the run task, so a user sending a follow-up
        # mid-run routinely ends a goal or summarization call here, with the
        # provider tokens already spent. Awaiting observers would be unreliable
        # — a repeated cancel interrupts that await before any of them runs — so
        # this reports through the same non-blocking submission the synchronous
        # memory bridge uses, then propagates the cancellation untouched. A
        # deployment with no registered notify loop drops it, exactly as that
        # bridge does.
        dispatch_system_model_observation(
            notify_system_model_call(
                extensions,
                store,
                kind,
                request,
                SystemModelResult(
                    error=exc,
                    duration_ms=(time.monotonic() - started) * 1000,
                ),
            ),
            kind.value,
        )
        raise
    except Exception as exc:
        await notify_system_model_call(
            extensions,
            store,
            kind,
            request,
            SystemModelResult(
                error=exc,
                duration_ms=(time.monotonic() - started) * 1000,
            ),
            timeout=timeout,
        )
        raise
    await notify_system_model_call(
        extensions,
        store,
        kind,
        request,
        SystemModelResult(
            response=response,
            duration_ms=(time.monotonic() - started) * 1000,
        ),
        timeout=timeout,
    )
    return response


def dispatch_system_model_observation(
    coro: Coroutine[Any, Any, None],
    what: str,
) -> bool:
    """Submit a synchronous call site's observation to the registered loop."""
    global _warned_no_loop

    loop = _notify_loop
    submitted = False
    try:
        if not _system_observations_enabled:
            return False
        if loop is None or not loop.is_running():
            if not _warned_no_loop:
                _warned_no_loop = True
                logger.warning(
                    "No running loop registered for extension observations; %s and later ones are dropped",
                    what,
                )
            return False
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception:
            logger.debug(
                "Could not dispatch %s to the extension notify loop",
                what,
                exc_info=True,
            )
            return False
        _pending_dispatches.add(future)
        future.add_done_callback(_pending_dispatches.discard)
        submitted = True
        return True
    finally:
        if not submitted:
            coro.close()
