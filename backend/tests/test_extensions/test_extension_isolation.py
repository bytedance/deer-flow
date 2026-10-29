"""Tests for isolating extension middleware failures from the user's run."""

from __future__ import annotations

import asyncio

import pytest
from langchain.agents.middleware import AgentMiddleware
from langgraph.errors import GraphBubbleUp

from deerflow.extensions.isolation import IsolatedMiddleware


class _Boom(AgentMiddleware):
    def wrap_model_call(self, request, handler):
        raise ValueError("observation exploded")

    async def awrap_model_call(self, request, handler):
        raise ValueError("observation exploded")

    def wrap_tool_call(self, request, handler):
        raise ValueError("observation exploded")

    async def awrap_tool_call(self, request, handler):
        raise ValueError("observation exploded")


class _Bubble(AgentMiddleware):
    def wrap_tool_call(self, request, handler):
        raise GraphBubbleUp()

    async def awrap_tool_call(self, request, handler):
        raise GraphBubbleUp()


class _Passthrough(AgentMiddleware):
    def __init__(self) -> None:
        super().__init__()
        self.seen = 0

    def wrap_tool_call(self, request, handler):
        self.seen += 1
        return handler(request)


def _handler(request):
    return "core-result"


async def _ahandler(request):
    return "core-result"


def test_failing_middleware_falls_through_to_the_handler():
    errors = []
    wrapped = IsolatedMiddleware(_Boom(), "bad:install", errors.append)
    assert wrapped.wrap_tool_call("req", _handler) == "core-result"
    assert wrapped.wrap_model_call("req", _handler) == "core-result"
    assert len(errors) == 2
    assert errors[0].source == "bad:install"
    assert errors[0].level == "error"


def test_failing_async_middleware_falls_through():
    errors = []
    wrapped = IsolatedMiddleware(_Boom(), "bad:install", errors.append)
    assert asyncio.run(wrapped.awrap_tool_call("req", _ahandler)) == "core-result"
    assert asyncio.run(wrapped.awrap_model_call("req", _ahandler)) == "core-result"
    assert len(errors) == 2


def test_graph_bubble_up_propagates_unchanged():
    """GraphBubbleUp carries LangGraph's interrupt/pause/resume control flow.
    Swallowing it would break the graph, not just the observation."""
    wrapped = IsolatedMiddleware(_Bubble(), "ext:install", lambda d: None)
    with pytest.raises(GraphBubbleUp):
        wrapped.wrap_tool_call("req", _handler)
    with pytest.raises(GraphBubbleUp):
        asyncio.run(wrapped.awrap_tool_call("req", _ahandler))


def test_working_middleware_is_not_disturbed():
    inner = _Passthrough()
    wrapped = IsolatedMiddleware(inner, "ok:install", lambda d: None)
    assert wrapped.wrap_tool_call("req", _handler) == "core-result"
    assert inner.seen == 1


def test_sync_only_wrap_hook_falls_through_on_async_execution_path():
    inner = _Passthrough()
    wrapped = IsolatedMiddleware(inner, "ok:install", lambda d: None)

    assert asyncio.run(wrapped.awrap_tool_call("req", _ahandler)) == "core-result"
    assert inner.seen == 0, "the unavailable sync observer must not run on the async path"


def test_async_only_wrap_hook_falls_through_on_sync_execution_path():
    class _AsyncOnly(AgentMiddleware):
        async def awrap_model_call(self, request, handler):
            raise AssertionError("the unavailable async observer must not run on the sync path")

    wrapped = IsolatedMiddleware(_AsyncOnly(), "ok:install", lambda d: None)

    assert wrapped.wrap_model_call("req", _handler) == "core-result"


def test_observer_cannot_replace_the_downstream_request():
    class _RewritesRequest(AgentMiddleware):
        def wrap_tool_call(self, request, handler):
            return handler("mutated")

    seen = []

    def handler(request):
        seen.append(request)
        return "core-result"

    wrapped = IsolatedMiddleware(_RewritesRequest(), "observer:install", lambda d: None)

    assert wrapped.wrap_tool_call("original", handler) == "core-result"
    assert seen == ["original"]


def test_async_observer_cannot_replace_the_downstream_request():
    class _RewritesRequest(AgentMiddleware):
        async def awrap_model_call(self, request, handler):
            return await handler("mutated")

    seen = []

    async def handler(request):
        seen.append(request)
        return "core-result"

    wrapped = IsolatedMiddleware(_RewritesRequest(), "observer:install", lambda d: None)

    assert asyncio.run(wrapped.awrap_model_call("original", handler)) == "core-result"
    assert seen == ["original"]


def test_post_handler_failure_does_not_replay_tool_handler():
    """A post-call observer failure must not repeat a tool's side effects."""

    class _FailsAfterHandler(AgentMiddleware):
        def wrap_tool_call(self, request, handler):
            handler(request)
            raise ValueError("post-call observation exploded")

    calls: list[str] = []

    def side_effecting_handler(request):
        calls.append(request)
        return "core-result"

    errors = []
    wrapped = IsolatedMiddleware(
        _FailsAfterHandler(),
        "bad:install",
        errors.append,
    )

    assert wrapped.wrap_tool_call("req", side_effecting_handler) == "core-result"
    assert calls == ["req"]
    assert len(errors) == 1


def test_tool_handler_failure_propagates_without_replay_or_diagnostic():
    """A real tool failure belongs to the graph, not extension isolation."""
    failure = RuntimeError("tool exploded")
    calls: list[str] = []

    def failing_handler(request):
        calls.append(request)
        raise failure

    errors = []
    wrapped = IsolatedMiddleware(
        _Passthrough(),
        "observer:install",
        errors.append,
    )

    with pytest.raises(RuntimeError) as exc_info:
        wrapped.wrap_tool_call("req", failing_handler)

    assert exc_info.value is failure
    assert calls == ["req"]
    assert errors == []


def test_post_handler_failure_does_not_replay_model_handler():
    """A post-call observer failure must not duplicate provider cost."""

    class _FailsAfterHandler(AgentMiddleware):
        def wrap_model_call(self, request, handler):
            handler(request)
            raise ValueError("post-call observation exploded")

    calls: list[str] = []

    def counted_handler(request):
        calls.append(request)
        return "model-result"

    errors = []
    wrapped = IsolatedMiddleware(
        _FailsAfterHandler(),
        "bad:install",
        errors.append,
    )

    assert wrapped.wrap_model_call("req", counted_handler) == "model-result"
    assert calls == ["req"]
    assert len(errors) == 1


def test_async_post_handler_failure_does_not_replay_tool_handler():
    """Isolation must not add another async tool side effect."""

    class _FailsAfterHandler(AgentMiddleware):
        async def awrap_tool_call(self, request, handler):
            await handler(request)
            raise ValueError("post-call observation exploded")

    calls: list[str] = []

    async def side_effecting_handler(request):
        calls.append(request)
        return "core-result"

    errors = []
    wrapped = IsolatedMiddleware(
        _FailsAfterHandler(),
        "bad:install",
        errors.append,
    )

    result = asyncio.run(wrapped.awrap_tool_call("req", side_effecting_handler))

    assert result == "core-result"
    assert calls == ["req"]
    assert len(errors) == 1


def test_async_tool_handler_failure_propagates_without_replay_or_diagnostic():
    """Async graph failures remain owned by the graph's error policy."""

    class _AsyncPassthrough(AgentMiddleware):
        async def awrap_tool_call(self, request, handler):
            return await handler(request)

    failure = RuntimeError("tool exploded")
    calls: list[str] = []

    async def failing_handler(request):
        calls.append(request)
        raise failure

    errors = []
    wrapped = IsolatedMiddleware(
        _AsyncPassthrough(),
        "observer:install",
        errors.append,
    )

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(wrapped.awrap_tool_call("req", failing_handler))

    assert exc_info.value is failure
    assert calls == ["req"]
    assert errors == []


def test_async_handler_cancellation_propagates_without_replay_or_diagnostic():
    """Cancellation is control flow and must never enter fail-open recovery."""

    class _AsyncPassthrough(AgentMiddleware):
        async def awrap_tool_call(self, request, handler):
            return await handler(request)

    calls: list[str] = []

    async def cancelled_handler(request):
        calls.append(request)
        raise asyncio.CancelledError

    errors = []
    wrapped = IsolatedMiddleware(
        _AsyncPassthrough(),
        "observer:install",
        errors.append,
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(wrapped.awrap_tool_call("req", cancelled_handler))

    assert calls == ["req"]
    assert errors == []


def test_async_post_handler_failure_does_not_replay_model_handler():
    """Async provider calls also retain their first successful result."""

    class _FailsAfterHandler(AgentMiddleware):
        async def awrap_model_call(self, request, handler):
            await handler(request)
            raise ValueError("post-call observation exploded")

    calls: list[str] = []

    async def counted_handler(request):
        calls.append(request)
        return "model-result"

    errors = []
    wrapped = IsolatedMiddleware(
        _FailsAfterHandler(),
        "bad:install",
        errors.append,
    )

    result = asyncio.run(wrapped.awrap_model_call("req", counted_handler))

    assert result == "model-result"
    assert calls == ["req"]
    assert len(errors) == 1


def test_middleware_cannot_replace_a_handler_failure_with_its_own_error():
    """The graph keeps ownership even if an observer masks its exception."""

    class _MasksHandlerFailure(AgentMiddleware):
        def wrap_tool_call(self, request, handler):
            try:
                return handler(request)
            except RuntimeError:
                raise ValueError("observer cleanup exploded") from None

    failure = RuntimeError("tool exploded")
    calls: list[str] = []

    def failing_handler(request):
        calls.append(request)
        raise failure

    errors = []
    wrapped = IsolatedMiddleware(
        _MasksHandlerFailure(),
        "observer:install",
        errors.append,
    )

    with pytest.raises(RuntimeError) as exc_info:
        wrapped.wrap_tool_call("req", failing_handler)

    assert exc_info.value is failure
    assert calls == ["req"]
    assert errors == []


def test_middleware_cannot_replace_a_handler_failure_with_graph_bubble_up():
    class _MasksHandlerFailure(AgentMiddleware):
        def wrap_tool_call(self, request, handler):
            try:
                return handler(request)
            except RuntimeError:
                raise GraphBubbleUp() from None

    failure = RuntimeError("tool exploded")

    def failing_handler(request):
        raise failure

    wrapped = IsolatedMiddleware(_MasksHandlerFailure(), "observer:install", lambda d: None)

    with pytest.raises(RuntimeError) as exc_info:
        wrapped.wrap_tool_call("req", failing_handler)

    assert exc_info.value is failure


def test_post_handler_graph_bubble_up_cannot_discard_a_successful_result():
    class _InterruptsAfterHandler(AgentMiddleware):
        def wrap_tool_call(self, request, handler):
            handler(request)
            raise GraphBubbleUp()

    errors = []
    wrapped = IsolatedMiddleware(_InterruptsAfterHandler(), "observer:install", errors.append)

    assert wrapped.wrap_tool_call("req", _handler) == "core-result"
    assert len(errors) == 1


def test_middleware_cannot_swallow_a_handler_failure_with_a_fallback():
    class _SwallowsHandlerFailure(AgentMiddleware):
        def wrap_tool_call(self, request, handler):
            try:
                handler(request)
            except RuntimeError:
                return "extension-fallback"

    failure = RuntimeError("tool exploded")
    calls: list[str] = []

    def failing_handler(request):
        calls.append(request)
        raise failure

    errors = []
    wrapped = IsolatedMiddleware(_SwallowsHandlerFailure(), "observer:install", errors.append)

    with pytest.raises(RuntimeError) as exc_info:
        wrapped.wrap_tool_call("req", failing_handler)

    assert exc_info.value is failure
    assert calls == ["req"]
    assert errors == []


def test_middleware_cannot_call_a_side_effecting_handler_twice():
    class _CallsTwice(AgentMiddleware):
        def wrap_tool_call(self, request, handler):
            first = handler(request)
            try:
                handler(request)
            except RuntimeError:
                return first

    calls: list[str] = []

    def side_effecting_handler(request):
        calls.append(request)
        return "core-result"

    errors = []
    wrapped = IsolatedMiddleware(_CallsTwice(), "observer:install", errors.append)

    assert wrapped.wrap_tool_call("req", side_effecting_handler) == "core-result"
    assert calls == ["req"]
    assert len(errors) == 1
    assert "more than once" in errors[0].message


def test_middleware_cannot_skip_the_handler_or_replace_its_result():
    class _SkipsHandler(AgentMiddleware):
        def wrap_model_call(self, request, handler):
            return "extension-result"

    calls: list[str] = []

    def handler(request):
        calls.append(request)
        return "core-result"

    errors = []
    wrapped = IsolatedMiddleware(_SkipsHandler(), "observer:install", errors.append)

    assert wrapped.wrap_model_call("req", handler) == "core-result"
    assert calls == ["req"]
    assert len(errors) == 1
    assert "did not call" in errors[0].message


def test_async_middleware_cannot_swallow_or_repeat_handler_calls():
    class _SwallowsAndRepeats(AgentMiddleware):
        async def awrap_tool_call(self, request, handler):
            try:
                await handler(request)
            except RuntimeError:
                try:
                    await handler(request)
                except RuntimeError:
                    return "extension-fallback"

    failure = RuntimeError("tool exploded")
    calls: list[str] = []

    async def failing_handler(request):
        calls.append(request)
        raise failure

    errors = []
    wrapped = IsolatedMiddleware(_SwallowsAndRepeats(), "observer:install", errors.append)

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(wrapped.awrap_tool_call("req", failing_handler))

    assert exc_info.value is failure
    assert calls == ["req"]
    assert errors == []


def test_error_message_identifies_the_hook():
    errors = []
    wrapped = IsolatedMiddleware(_Boom(), "bad:install", errors.append)
    wrapped.wrap_tool_call("req", _handler)
    assert "wrap_tool_call" in errors[0].message


# --- interface preservation -------------------------------------------------
#
# LangChain discovers middleware capabilities by inspecting the *wrapper*: hook
# participation is a class-level identity check (`m.__class__.before_model is
# not AgentMiddleware.before_model`, see langchain/agents/factory.py), and
# tools/state_schema/transformers are read off the middleware instance. The
# wrapper must mirror the inner middleware's full interface, not just the four
# wrap-call hooks — otherwise lifecycle hooks silently never enter the graph
# and contributed tools/state never register.

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


def _langchain_detects(middleware: AgentMiddleware, hook_name: str) -> bool:
    """The exact check langchain.agents.factory uses to decide whether a hook
    node is added to the graph."""
    return getattr(type(middleware), hook_name) is not getattr(AgentMiddleware, hook_name)


class _LifecycleObserver(AgentMiddleware):
    """Implements every lifecycle hook, sync and async, none of the wrap-calls."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def before_agent(self, state, runtime):
        self.calls.append("before_agent")
        return {"seen": "before_agent"}

    async def abefore_agent(self, state, runtime):
        self.calls.append("abefore_agent")
        return {"seen": "abefore_agent"}

    def before_model(self, state, runtime):
        self.calls.append("before_model")
        return {"seen": "before_model"}

    async def abefore_model(self, state, runtime):
        self.calls.append("abefore_model")
        return {"seen": "abefore_model"}

    def after_model(self, state, runtime):
        self.calls.append("after_model")
        return {"seen": "after_model"}

    async def aafter_model(self, state, runtime):
        self.calls.append("aafter_model")
        return {"seen": "aafter_model"}

    def after_agent(self, state, runtime):
        self.calls.append("after_agent")
        return {"seen": "after_agent"}

    async def aafter_agent(self, state, runtime):
        self.calls.append("aafter_agent")
        return {"seen": "aafter_agent"}


def test_wrapper_advertises_the_lifecycle_hooks_the_inner_implements():
    """A wrapped lifecycle observer must be *seen* by LangChain: without a
    class-level override the factory never adds the hook node to the graph and
    the inner hook silently never runs."""
    wrapped = IsolatedMiddleware(_LifecycleObserver(), "obs:install", lambda d: None)
    missing = [hook for hook in _LIFECYCLE_HOOKS if not _langchain_detects(wrapped, hook)]
    assert missing == [], f"LangChain cannot see these wrapped hooks: {missing}"


def test_wrapper_does_not_fabricate_hooks_the_inner_lacks():
    """The mirror must be exact: fabricating hooks would bolt no-op nodes onto
    every graph and corrupt middleware_implements-based placement checks."""
    wrapped = IsolatedMiddleware(_Passthrough(), "ok:install", lambda d: None)
    fabricated = [hook for hook in _LIFECYCLE_HOOKS if _langchain_detects(wrapped, hook)]
    assert fabricated == [], f"the wrapper invented hooks the inner lacks: {fabricated}"


def test_wrapper_mirrors_sync_and_async_hooks_independently():
    """LangChain wires sync and async variants separately; an async-only inner
    must not cause a sync no-op node (and vice versa)."""

    class _AsyncOnly(AgentMiddleware):
        async def abefore_model(self, state, runtime):
            return None

    wrapped = IsolatedMiddleware(_AsyncOnly(), "obs:install", lambda d: None)
    assert _langchain_detects(wrapped, "abefore_model")
    assert not _langchain_detects(wrapped, "before_model")
    for hook in _LIFECYCLE_HOOKS:
        if hook != "abefore_model":
            assert not _langchain_detects(wrapped, hook), hook


def test_wrapper_preserves_tools_state_schema_and_transformers():
    """factory.py reads m.tools / m.state_schema / m.transformers off the
    wrapper — dropping them unregisters the middleware's contributions."""
    from langchain_core.tools import tool

    @tool
    def ext_echo(text: str) -> str:
        """Echo the text back."""
        return f"echo:{text}"

    import typing

    class _State(typing.TypedDict, total=False):
        seen: str

    def _transformer(scope):
        return None

    class _Contributing(AgentMiddleware):
        state_schema = _State
        transformers = (_transformer,)

        def __init__(self) -> None:
            super().__init__()
            self.tools = [ext_echo]

    inner = _Contributing()
    wrapped = IsolatedMiddleware(inner, "contrib:install", lambda d: None)
    assert list(wrapped.tools) == [ext_echo]
    assert wrapped.state_schema is _State
    assert tuple(wrapped.transformers) == (_transformer,)


def test_lifecycle_hooks_delegate_to_the_inner():
    inner = _LifecycleObserver()
    wrapped = IsolatedMiddleware(inner, "obs:install", lambda d: None)
    assert wrapped.before_model("state", "runtime") == {"seen": "before_model"}
    assert wrapped.after_agent("state", "runtime") == {"seen": "after_agent"}
    assert asyncio.run(wrapped.abefore_agent("state", "runtime")) == {"seen": "abefore_agent"}
    assert asyncio.run(wrapped.aafter_model("state", "runtime")) == {"seen": "aafter_model"}
    assert inner.calls == ["before_model", "after_agent", "abefore_agent", "aafter_model"]


def test_failing_lifecycle_hook_degrades_to_none_with_a_diagnostic():
    """Lifecycle hooks have no handler to fall through to; the fail-open
    degradation is returning no state update."""

    class _FailingObserver(AgentMiddleware):
        def before_model(self, state, runtime):
            raise ValueError("observation exploded")

        async def aafter_model(self, state, runtime):
            raise ValueError("observation exploded")

    errors = []
    wrapped = IsolatedMiddleware(_FailingObserver(), "bad:install", errors.append)
    assert wrapped.before_model("state", "runtime") is None
    assert asyncio.run(wrapped.aafter_model("state", "runtime")) is None
    assert [d.level for d in errors] == ["error", "error"]
    assert "before_model" in errors[0].message
    assert "aafter_model" in errors[1].message


def test_graph_bubble_up_propagates_from_lifecycle_hooks():
    """Interrupts ride on lifecycle hooks too (human-in-the-loop pauses from
    after_model); isolation must not swallow graph control flow."""

    class _Interrupting(AgentMiddleware):
        def after_model(self, state, runtime):
            raise GraphBubbleUp()

        async def abefore_model(self, state, runtime):
            raise GraphBubbleUp()

    wrapped = IsolatedMiddleware(_Interrupting(), "hitl:install", lambda d: None)
    with pytest.raises(GraphBubbleUp):
        wrapped.after_model("state", "runtime")
    with pytest.raises(GraphBubbleUp):
        asyncio.run(wrapped.abefore_model("state", "runtime"))


def test_middleware_implements_agrees_with_the_wrapper():
    """Placement-guarantee checks reason about hook participation through
    middleware_implements(); the wrapper must not distort it."""
    from deerflow.extensions.stack import middleware_implements

    wrapped = IsolatedMiddleware(_LifecycleObserver(), "obs:install", lambda d: None)
    for hook in _LIFECYCLE_HOOKS:
        assert middleware_implements(wrapped, hook), hook
    assert not middleware_implements(wrapped, "wrap_model_call")


def test_create_agent_runs_the_wrapped_hooks_and_registers_the_wrapped_tools():
    """End to end through a real langchain.agents.create_agent graph: the
    wrapped middleware's before_model must actually execute and its tools must
    actually be callable."""
    from _agent_e2e_helpers import build_single_tool_call_model
    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage
    from langchain_core.tools import tool

    tool_calls: list[str] = []

    @tool
    def ext_echo(text: str) -> str:
        """Echo the text back."""
        tool_calls.append(text)
        return f"echo:{text}"

    class _Contributing(AgentMiddleware):
        def __init__(self) -> None:
            super().__init__()
            self.tools = [ext_echo]
            self.before_model_calls = 0

        def before_model(self, state, runtime):
            self.before_model_calls += 1
            return None

    inner = _Contributing()
    wrapped = IsolatedMiddleware(inner, "contrib:install", lambda d: None)

    model = build_single_tool_call_model(tool_name="ext_echo", tool_args={"text": "hello"})
    agent = create_agent(model=model, tools=[], middleware=[wrapped])
    result = agent.invoke({"messages": [HumanMessage(content="say hello")]})

    assert inner.before_model_calls > 0, "the wrapped before_model hook never entered the graph"
    assert tool_calls == ["hello"], "the wrapped middleware's tool was never registered"
    assert any(getattr(m, "content", "") == "echo:hello" for m in result["messages"])
