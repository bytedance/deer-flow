"""Isolating extension middleware failures from the user's run.

Extension middlewares execute inside LangChain's call chain, so an unhandled
exception would abort the user's run. Every contributed middleware is wrapped
so an observation failure degrades to a diagnostic and the call passes through.
The downstream handler is tracked so isolation recovery never adds another
model request or tool side effect: pre-handler extension failures invoke it
once, post-handler failures return its captured result, and handler failures
remain owned by the graph's error policy.

The wrapper must mirror the inner middleware's full interface, not just the
four wrap-call hooks: LangChain discovers capabilities by inspecting the
wrapper — hook participation via class-level identity checks
(`m.__class__.before_model is not AgentMiddleware.before_model`), tools,
state_schema and transformers via instance attributes. Lifecycle mirroring is
exact in both directions. LangChain deliberately treats each sync/async wrap
pair as one capability and wires both execution paths when either side exists,
so the wrapper supplies a silent pass-through counterpart when the inner
implements only one side; otherwise the base class raises
``NotImplementedError`` before isolation can fail open.

All first-version contributions are observational, hence fail-open. A future
intercepting (decision-making) contribution would need to fail closed and must
opt out of this wrapper explicitly.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langgraph.errors import GraphBubbleUp

from deerflow.extensions.loader import Diagnostic

logger = logging.getLogger(__name__)

_UNSAFE_GRAPH_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


def graph_safe_middleware_name(value: str) -> str:
    """Normalize a middleware identity for LangGraph node names."""
    return _UNSAFE_GRAPH_NAME.sub("_", value)


_WRAP_HOOKS = ("wrap_model_call", "awrap_model_call", "wrap_tool_call", "awrap_tool_call")
_WRAP_HOOK_PAIRS = (
    ("wrap_model_call", "awrap_model_call"),
    ("wrap_tool_call", "awrap_tool_call"),
)
_LIFECYCLE_HOOKS = (
    "before_agent",
    "abefore_agent",
    "before_model",
    "abefore_model",
    "after_model",
    "aafter_model",
    "after_agent",
    "aafter_agent",
)


def _implemented_hooks(inner: AgentMiddleware) -> frozenset[str]:
    """The hooks ``inner`` actually overrides, by LangChain's own class-level
    identity check — instance-level attributes are invisible to the factory,
    so they are invisible here too."""
    return frozenset(hook for hook in (*_WRAP_HOOKS, *_LIFECYCLE_HOOKS) if getattr(type(inner), hook, None) is not getattr(AgentMiddleware, hook, None))


def _make_sync_wrap_delegate(hook: str):
    def delegate(self: IsolatedMiddleware, request: Any, handler: Callable[[Any], Any]) -> Any:
        return self._invoke_sync(hook, getattr(self._inner, hook), request, handler)

    return delegate


def _make_async_wrap_delegate(hook: str):
    async def delegate(self: IsolatedMiddleware, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        return await self._invoke_async(hook, getattr(self._inner, hook), request, handler)

    return delegate


def _make_sync_wrap_passthrough():
    def delegate(self: IsolatedMiddleware, request: Any, handler: Callable[[Any], Any]) -> Any:
        return handler(request)

    return delegate


def _make_async_wrap_passthrough():
    async def delegate(self: IsolatedMiddleware, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        return await handler(request)

    return delegate


def _make_sync_lifecycle_delegate(hook: str):
    def delegate(self: IsolatedMiddleware, state: Any, runtime: Any) -> Any:
        return self._invoke_lifecycle_sync(hook, state, runtime)

    return delegate


def _make_async_lifecycle_delegate(hook: str):
    async def delegate(self: IsolatedMiddleware, state: Any, runtime: Any) -> Any:
        return await self._invoke_lifecycle_async(hook, state, runtime)

    return delegate


# Async variants are named explicitly: startswith("a") would also catch the
# sync after_model/after_agent.
_ASYNC_HOOKS = frozenset(hook for hook in (*_WRAP_HOOKS, *_LIFECYCLE_HOOKS) if hook[1:].startswith(("wrap", "before", "after")))


def _delegate_for(hook: str):
    if hook in _WRAP_HOOKS:
        return _make_async_wrap_delegate(hook) if hook in _ASYNC_HOOKS else _make_sync_wrap_delegate(hook)
    return _make_async_lifecycle_delegate(hook) if hook in _ASYNC_HOOKS else _make_sync_lifecycle_delegate(hook)


_subclass_cache: dict[frozenset[str], type[IsolatedMiddleware]] = {}
_subclass_cache_lock = threading.Lock()


def _wrapper_subclass(hooks: frozenset[str]) -> type[IsolatedMiddleware]:
    """A cached IsolatedMiddleware subclass defining ``hooks`` and required
    wrap-hook pass-through counterparts.

    Per hook set, not per middleware: every inner middleware with the same
    implemented-hook combination shares one subclass.
    """
    with _subclass_cache_lock:
        subclass = _subclass_cache.get(hooks)
        if subclass is None:
            namespace = {hook: _delegate_for(hook) for hook in hooks}
            for sync_hook, async_hook in _WRAP_HOOK_PAIRS:
                if sync_hook in hooks and async_hook not in hooks:
                    namespace[async_hook] = _make_async_wrap_passthrough()
                elif async_hook in hooks and sync_hook not in hooks:
                    namespace[sync_hook] = _make_sync_wrap_passthrough()
            subclass = type(IsolatedMiddleware.__name__, (IsolatedMiddleware,), namespace)
            _subclass_cache[hooks] = subclass
        return subclass


class IsolatedMiddleware(AgentMiddleware):
    """Wrap one extension middleware so its failures cannot break the run.

    Instantiation returns a cached subclass that defines exactly the hooks the
    inner middleware implements, so LangChain's class-level capability checks
    see the same interface on the wrapper as on the inner middleware itself.
    """

    def __new__(cls, inner: AgentMiddleware, source: str, on_error: Callable[[Diagnostic], None], *, name: str | None = None):
        if cls is IsolatedMiddleware:
            cls = _wrapper_subclass(_implemented_hooks(inner))
        return super().__new__(cls)

    def __init__(
        self,
        inner: AgentMiddleware,
        source: str,
        on_error: Callable[[Diagnostic], None],
        *,
        name: str | None = None,
    ) -> None:
        super().__init__()
        self._inner = inner
        self._source = source
        self._on_error = on_error
        if name is None:
            inner_name = getattr(inner, "name", type(inner).__name__)
            name = f"extension:{source}:{inner_name}"
        self._name = graph_safe_middleware_name(name)
        # Mirror the declared-contribution attributes LangChain reads off the
        # middleware instance (factory.py: m.tools, m.state_schema,
        # m.transformers). state_schema is a class attribute on the base but
        # must be per-instance here: cached subclasses are shared across
        # middlewares whose schemas differ.
        self.tools = getattr(inner, "tools", [])
        self.transformers = getattr(inner, "transformers", ())
        self.state_schema = getattr(inner, "state_schema", AgentMiddleware.state_schema)

    @property
    def name(self) -> str:
        """Stable graph and trace identity for this isolated contribution."""
        return self._name

    @property
    def inner(self) -> AgentMiddleware:
        """The wrapped middleware. Used by ordering checks and tests."""
        return self._inner

    @property
    def source(self) -> str:
        """Extension this middleware came from. Read by the provenance map."""
        return self._source

    def _report(self, hook: str, exc: Exception) -> None:
        message = f"{type(self._inner).__name__}.{hook} failed and was skipped: {exc}"
        logger.exception("Extension %s: %s", self._source, message)
        try:
            self._on_error(Diagnostic.error(self._source, message))
        except Exception:  # pragma: no cover - reporting must never raise
            logger.exception("Extension %s: diagnostic reporting failed", self._source)

    def _invoke_sync(
        self,
        hook: str,
        inner_hook: Callable[[Any, Callable[[Any], Any]], Any],
        request: Any,
        handler: Callable[[Any], Any],
    ) -> Any:
        handler_called = False
        handler_succeeded = False
        handler_result: Any = None
        handler_error: BaseException | None = None
        handler_error_traceback: TracebackType | None = None
        duplicate_call_error: RuntimeError | None = None

        def tracked_handler(inner_request: Any) -> Any:
            nonlocal handler_called, duplicate_call_error
            nonlocal handler_error, handler_error_traceback
            nonlocal handler_result, handler_succeeded
            if handler_called:
                duplicate_call_error = RuntimeError(f"{type(self._inner).__name__}.{hook} called the downstream handler more than once")
                raise duplicate_call_error
            handler_called = True
            handler_error = None
            handler_error_traceback = None
            handler_succeeded = False
            try:
                # The first contract slice is observational: a contributed
                # wrapper may inspect the request but cannot substitute a new
                # one after the host's policy/authorization layers have run.
                handler_result = handler(request)
            except BaseException as exc:
                handler_error = exc
                handler_error_traceback = exc.__traceback__
                raise
            else:
                handler_succeeded = True
                return handler_result

        try:
            inner_hook(request, tracked_handler)
            if handler_error is not None:
                raise handler_error.with_traceback(handler_error_traceback)
            if duplicate_call_error is not None:
                raise duplicate_call_error
            if not handler_called:
                raise RuntimeError(f"{type(self._inner).__name__}.{hook} did not call the downstream handler")
            return handler_result
        except GraphBubbleUp as exc:
            if handler_error is not None:
                if handler_error is exc:
                    raise
                raise handler_error.with_traceback(handler_error_traceback) from None
            if handler_succeeded:
                self._report(hook, duplicate_call_error or exc)
                return handler_result
            raise
        except Exception as exc:
            if handler_error is not None:
                if handler_error is exc:
                    raise
                raise handler_error.with_traceback(handler_error_traceback) from None
            self._report(hook, exc)
            if handler_succeeded:
                return handler_result
            return handler(request)

    async def _invoke_async(
        self,
        hook: str,
        inner_hook: Callable[
            [Any, Callable[[Any], Awaitable[Any]]],
            Awaitable[Any],
        ],
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        handler_called = False
        handler_succeeded = False
        handler_result: Any = None
        handler_error: BaseException | None = None
        handler_error_traceback: TracebackType | None = None
        duplicate_call_error: RuntimeError | None = None

        async def tracked_handler(inner_request: Any) -> Any:
            nonlocal handler_called, duplicate_call_error
            nonlocal handler_error, handler_error_traceback
            nonlocal handler_result, handler_succeeded
            if handler_called:
                duplicate_call_error = RuntimeError(f"{type(self._inner).__name__}.{hook} called the downstream handler more than once")
                raise duplicate_call_error
            handler_called = True
            handler_error = None
            handler_error_traceback = None
            handler_succeeded = False
            try:
                handler_result = await handler(request)
            except BaseException as exc:
                handler_error = exc
                handler_error_traceback = exc.__traceback__
                raise
            else:
                handler_succeeded = True
                return handler_result

        try:
            await inner_hook(request, tracked_handler)
            if handler_error is not None:
                raise handler_error.with_traceback(handler_error_traceback)
            if duplicate_call_error is not None:
                raise duplicate_call_error
            if not handler_called:
                raise RuntimeError(f"{type(self._inner).__name__}.{hook} did not call the downstream handler")
            return handler_result
        except GraphBubbleUp as exc:
            if handler_error is not None:
                if handler_error is exc:
                    raise
                raise handler_error.with_traceback(handler_error_traceback) from None
            if handler_succeeded:
                self._report(hook, duplicate_call_error or exc)
                return handler_result
            raise
        except Exception as exc:
            if handler_error is not None:
                if handler_error is exc:
                    raise
                raise handler_error.with_traceback(handler_error_traceback) from None
            self._report(hook, exc)
            if handler_succeeded:
                return handler_result
            return await handler(request)

    def _invoke_lifecycle_sync(self, hook: str, state: Any, runtime: Any) -> Any:
        """Lifecycle hooks have no handler to fall through to: the fail-open
        degradation for a failed observation is applying no state update."""
        try:
            return getattr(self._inner, hook)(state, runtime)
        except GraphBubbleUp:
            raise
        except Exception as exc:
            self._report(hook, exc)
            return None

    async def _invoke_lifecycle_async(self, hook: str, state: Any, runtime: Any) -> Any:
        try:
            return await getattr(self._inner, hook)(state, runtime)
        except GraphBubbleUp:
            raise
        except Exception as exc:
            self._report(hook, exc)
            return None
