"""Host-bound native invocation admission; no long IO under SQL locks.

The private task-local guard is created only by run_agent from its immutable
admission. Config, callbacks and operator model caches cannot select a tenant.
"""

import asyncio
from contextvars import ContextVar

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.callbacks.base import BaseCallbackManager
from langchain_core.rate_limiters import BaseRateLimiter
from langgraph.errors import GraphBubbleUp

from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied
from deerflow.utils.file_io import await_drained

_current_guard = ContextVar("native_worker_invocation_guard", default=None)


class WorkerInvocationDenied(GraphBubbleUp):
    """Native stop signal; retry/error normalization must not consume it."""


class WorkerInvocationGuard:
    def __init__(self, repository, target):
        self.repository = repository
        self.target = target
        self.loop = asyncio.get_running_loop()
        self.closed = False
        self._providers = set()

    async def check(self):
        if self.closed or asyncio.get_running_loop() is not self.loop:
            raise WorkerInvocationDenied("Native invocation requires its live async worker")
        try:
            await self.repository.check_worker_invocation(self.target)
        except WorkspaceAccessDenied:
            raise WorkerInvocationDenied("Native execution authority is no longer available") from None
        if self.closed:
            raise WorkerInvocationDenied("Native worker has closed")

    def track(self, task):
        """Retain this Run's actual provider work, including abandoned callers."""
        if self.closed or asyncio.get_running_loop() is not self.loop:
            task.cancel()
            raise WorkerInvocationDenied("Native worker has closed")
        self._providers.add(task)
        task.add_done_callback(self._providers.discard)

    async def drain(self):
        async def join():
            while self._providers:
                await asyncio.gather(*tuple(self._providers), return_exceptions=True)

        await await_drained(join())

    async def aclose(self):
        self.close()
        await self.drain()

    def close(self):
        self.closed = True


def get_invocation_guard():
    return _current_guard.get()


def bind_invocation_guard(guard):
    return _current_guard.set(guard)


def reset_invocation_guard(token):
    _current_guard.reset(token)


async def check_invocation(*, required=False):
    guard = get_invocation_guard()
    if guard is None:
        if required:
            raise WorkerInvocationDenied("Native invocation authority is required")
        return
    await guard.check()


def check_invocation_sync(*, required=False):
    guard = get_invocation_guard()
    if guard is None:
        if required:
            raise WorkerInvocationDenied("Native invocation authority is required")
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if guard.closed or loop is guard.loop or not guard.loop.is_running():
        raise WorkerInvocationDenied("Use native async invocation on the worker loop")
    future = asyncio.run_coroutine_threadsafe(guard.check(), guard.loop)
    try:
        future.result(timeout=30)
    except TimeoutError:
        future.cancel()
        raise WorkerInvocationDenied("Native invocation authority check timed out") from None


class WorkerInvocationCallback(AsyncCallbackHandler):
    # Model-local callbacks also protect explicit callbacks=[] system calls.
    # No guard/Run reference is retained on a cached model instance.
    run_inline = True
    raise_error = True

    async def on_chat_model_start(self, serialized, messages, **kwargs):
        await check_invocation(required=True)

    async def on_tool_start(self, serialized, input_str, **kwargs):
        await check_invocation(required=True)


def install_invocation_callback(config):
    handler = WorkerInvocationCallback()
    callbacks = config.get("callbacks")
    if callbacks is None or isinstance(callbacks, list):
        config["callbacks"] = [handler, *(item for item in callbacks or [] if not isinstance(item, WorkerInvocationCallback))]
    elif isinstance(callbacks, BaseCallbackManager):
        callbacks = callbacks.copy()
        callbacks.handlers = [handler, *(item for item in callbacks.handlers if not isinstance(item, WorkerInvocationCallback))]
        callbacks.inheritable_handlers = [handler, *(item for item in callbacks.inheritable_handlers if not isinstance(item, WorkerInvocationCallback))]
        config["callbacks"] = callbacks
    else:
        raise WorkerInvocationDenied("Unsupported native invocation callback container")
    return handler


class WorkerInvocationRateLimiter(BaseRateLimiter):
    """Preserve existing queue policy, then reauthorize before provider dispatch."""

    def __init__(self, inner):
        self.inner = inner

    def acquire(self, *, blocking=True):
        check_invocation_sync(required=True)
        acquired = self.inner.acquire(blocking=blocking) if self.inner is not None else True
        if acquired:
            check_invocation_sync(required=True)
        return acquired

    async def aacquire(self, *, blocking=True):
        await check_invocation(required=True)
        acquired = await self.inner.aacquire(blocking=blocking) if self.inner is not None else True
        if acquired:
            await check_invocation(required=True)
        return acquired
