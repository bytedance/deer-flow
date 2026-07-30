"""Notification helpers for the host-side hook points.

Every helper is fail-open: an observation failure is logged and the next
observer still runs. Callers short-circuit on the precomputed `has_*` flags
before constructing any payload, so the zero-extension path allocates nothing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from typing import Any

from deerflow_extension_api import (
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
    """Task identity for a lead agent execution.

    A lead execution is 1:1 with a run — goal continuations re-enter the same
    run and reuse the same task — so the run id *is* the task id. Lead and
    subagent then share one task abstraction and extensions write one code path.
    """
    return run_id


def lead_task_outcome(*, aborted: bool, succeeded: bool) -> TaskOutcome:
    """Classify how a lead execution ended.

    Takes plain booleans rather than a ``RunRecord`` so the extension layer
    stays free of runtime schema imports and the classification is unit
    testable on its own.

    Deliberately keyed on *success*, not on an error probe: only an explicitly
    successful run reports COMPLETED, so a status the host never anticipated —
    a run still marked running because a ``BaseException`` escaped, a future
    ``timeout`` status — degrades to FAILED rather than being reported as a
    clean completion. Abort wins over both: a cancelled run commonly also
    unwinds through an exception, and the caller asked for the stop, so that is
    the more specific explanation.
    """
    if aborted:
        return TaskOutcome.ABORTED
    if succeeded:
        return TaskOutcome.COMPLETED
    return TaskOutcome.FAILED


def subagent_task_outcome(*, cancelled: bool, succeeded: bool) -> TaskOutcome:
    """Classify how a subagent execution ended.

    The sibling of :func:`lead_task_outcome`, and keyed the same way and for the
    same reason: only an explicitly successful execution reports COMPLETED, so a
    status the host never set — the result still marked RUNNING because a
    ``BaseException`` escaped the executor's ``except Exception`` — degrades to
    FAILED instead of being reported as a clean success.

    Takes booleans rather than a ``SubagentStatus`` so this module keeps no
    import of ``deerflow.subagents``, which imports this one.
    """
    if cancelled:
        return TaskOutcome.ABORTED
    if succeeded:
        return TaskOutcome.COMPLETED
    return TaskOutcome.FAILED


async def _notify_each(
    contributors: tuple[tuple[str, Any], ...],
    hook: str,
    invoke: Callable[[Any], Any],
    task_id: str,
    timeout: float | None,
) -> None:
    """Call ``hook`` on every contributor, fail-open, within a shared budget.

    ``timeout`` bounds the whole notification, not each contributor: it is a
    shared budget consumed in order, so a contributor that takes 1s of a 3s
    budget leaves 2s for the rest, instead of each getting a fresh full timeout
    (which would make the total unbounded in the number of extensions). A
    contributor that exhausts the budget is logged as skipped rather than
    silently dropped — the host cannot wait forever, but it also must not let
    one hung extension look like success.

    Everything, including *producing* the awaitable, happens inside the try:
    contributors are arbitrary objects with no runtime validation, so a plain
    ``def`` or a stale signature raises at call time rather than at await time.
    """
    deadline = None if timeout is None else asyncio.get_running_loop().time() + timeout
    for source, contributor in contributors:
        try:
            call = invoke(contributor)
            if deadline is None:
                await call
                continue
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                close = getattr(call, "close", None)
                if close is not None:
                    close()
                logger.warning(
                    "Extension %s: %s skipped for task %s, the %.1fs budget was already spent",
                    source,
                    hook,
                    task_id,
                    timeout,
                )
                continue
            await asyncio.wait_for(call, remaining)
        except Exception:
            logger.exception("Extension %s: %s failed for task %s", source, hook, task_id)


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
        lambda contributor: contributor.on_task_start(extensions.app_store, task_store, info),
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
        lambda contributor: contributor.on_task_stop(extensions.app_store, task_store, info, outcome),
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
    if not extensions.system_model_observers:
        # Checked before the fallback store is built: callers are expected to
        # short-circuit on has_system_model_observers, but this keeps the
        # module's own "zero-extension path allocates nothing" promise true
        # even for a call site that forgets to.
        return
    store = task_store if task_store is not None else ExtensionData("detached")
    await _notify_each_on_extension_loop(
        extensions.system_model_observers,
        "on_system_model_call",
        lambda observer: observer.on_system_model_call(extensions.app_store, store, kind, request, result),
        kind.value,
        timeout,
    )


def task_store_for_system_call(invoke_config: object) -> ExtensionData | None:
    """Best-effort compatibility lookup for an out-of-graph call's task store.

    Live call sites pass the store explicitly because LangGraph can normalize
    ``RunnableConfig`` into shapes this helper cannot safely recover from.
    This fallback preserves older/direct callers that still put the store in a
    top-level ``context``. Returns None when no task is live, which is a
    legitimate state, not an error.
    """
    from deerflow_extension_api import EXTENSION_TASK_STORE_KEY

    if not isinstance(invoke_config, Mapping):
        return None
    context = invoke_config.get("context")
    if not isinstance(context, Mapping):
        return None
    store = context.get(EXTENSION_TASK_STORE_KEY)
    return store if isinstance(store, ExtensionData) else None


#: Loop on which extension services bind resources and notification hooks run.
#: An observer holding an async client built on one loop breaks when awaited on
#: another (issue #2615's failure mode, reproduced inside extension code).
_notify_loop: asyncio.AbstractEventLoop | None = None

#: Strong references to in-flight fire-and-forget dispatches. Without these
#: CPython may collect a pending task and log "Task was destroyed but it is
#: pending" instead of running the observer.
_pending_dispatches: set[asyncio.Future[Any]] = set()

_warned_no_loop = False
_system_observations_enabled = True


def set_extension_notify_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Register the loop extension notification hooks are dispatched onto.

    Must be the serving loop on which ``ExtensionService.start()`` binds
    extension resources. Hosts that never register one (the embedded client,
    the TUI, plain scripts) execute awaited hooks on their current loop; only
    synchronous fire-and-forget system-model observations are dropped.
    """
    global _notify_loop, _system_observations_enabled, _warned_no_loop
    _notify_loop = loop
    _system_observations_enabled = True
    _warned_no_loop = False


def reset_extension_notify_loop() -> None:
    global _notify_loop, _system_observations_enabled, _warned_no_loop
    _notify_loop = None
    _system_observations_enabled = True
    _warned_no_loop = False
    _pending_dispatches.clear()


def suspend_extension_system_observations() -> None:
    """Drop new synchronous system observations without detaching task hooks.

    Gateway shutdown uses this before flushing the memory debounce thread: new
    fire-and-forget observations must not target a loop that is about to stop,
    while in-flight subagents still need that same registered loop for their
    awaited task-stop lifecycle hook.
    """
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
    """Run awaited hooks where extension services bind their async resources."""
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
        logger.exception("Could not dispatch extension %s for task %s to the registered loop", hook, task_id)
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
        logger.exception("Extension %s dispatch failed for task %s", hook, task_id)


def dispatch_system_model_observation(coro: Coroutine[Any, Any, None], what: str) -> bool:
    """Submit an observation to the registered loop without waiting for it.

    The entry point for *synchronous* call sites. Observers are ``async def`` by
    contract, and the call sites that need this run on threads with no event
    loop of their own (DeerMem's debounce timer), so the coroutine is handed to
    the serving loop where extension services bound their resources rather
    than run here.

    Two deliberate non-choices:

    - **Never blocks.** ``run_coroutine_threadsafe(...).result()`` hangs forever
      when the target loop has been stopped but not closed: the submission is
      accepted and the future is never resolved. On the memory path that would
      wedge the debounce queue's ``_processing`` flag for the rest of the
      process lifetime.
    - **Never dispatches to ``get_running_loop()``.** Handing the coroutine to
      whichever of this process's loops happens to be current (Gateway, the
      isolated subagent loop, BoxLite's) is the cross-loop bug this whole
      mechanism exists to avoid.

    Returns whether the observation was submitted, for tests and diagnostics.
    """
    global _warned_no_loop

    loop = _notify_loop
    submitted = False
    try:
        if not _system_observations_enabled:
            return False
        if loop is None or not loop.is_running():
            # `is_running()` rather than `is_closed()`: a stopped-but-not-closed
            # loop reports itself open and silently never runs the coroutine.
            if not _warned_no_loop:
                _warned_no_loop = True
                logger.warning("No running loop registered for extension observations; %s and later ones are dropped", what)
            return False
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception:
            # The loop can close between the check above and this call.
            logger.debug("Could not dispatch %s to the extension notify loop", what, exc_info=True)
            return False
        # Narrower race, not eliminated: the loop can also stop between the
        # check and the submit, in which case the future never resolves and is
        # released only by reset_extension_notify_loop(). Unfixable without
        # cooperation from the loop; the Gateway resets before stopping.
        _pending_dispatches.add(future)
        future.add_done_callback(_pending_dispatches.discard)
        submitted = True
        return True
    finally:
        if not submitted:
            # Close on every path that did not hand the coroutine off, or it is
            # garbage collected with "coroutine was never awaited".
            coro.close()


async def observe_system_model_call(
    kind: SystemOperationKind,
    *,
    messages: Any,
    model_name: str | None,
    invoke_config: Any,
    invoke: Callable[[], Awaitable[Any]],
    task_store: ExtensionData | None = None,
    timeout: float | None = None,
) -> Any:
    """Run an out-of-graph model call and notify observers on both paths.

    One helper rather than the same try/except/notify block repeated at every
    call site: the sites are spread across four modules, and a duplicated guard
    is exactly how the task-lifecycle hooks drifted apart earlier in this work.

    Failures are notified and then re-raised — the call's own error handling is
    unchanged, observation is purely additive. A system call that raised is the
    event an observability extension most needs, so notifying only on success
    would hide it.

    ``task_store`` is the authoritative carrier for a live task. The config
    lookup remains only as a compatibility fallback for direct callers.
    """
    from deerflow.extensions import get_loaded_extensions

    extensions = get_loaded_extensions()
    if not extensions.has_system_model_observers:
        # Zero-extension path: no snapshot objects, no clock reads, no store
        # lookup — just the original call.
        return await invoke()

    store = task_store if task_store is not None else task_store_for_system_call(invoke_config)
    request = SystemModelRequest(messages=messages, model_name=model_name, invoke_config=invoke_config if isinstance(invoke_config, Mapping) else None)
    started = time.monotonic()
    try:
        response = await invoke()
    except Exception as exc:
        await notify_system_model_call(
            extensions,
            store,
            kind,
            request,
            SystemModelResult(error=exc, duration_ms=(time.monotonic() - started) * 1000),
            timeout=timeout,
        )
        raise
    await notify_system_model_call(
        extensions,
        store,
        kind,
        request,
        SystemModelResult(response=response, duration_ms=(time.monotonic() - started) * 1000),
        timeout=timeout,
    )
    return response
