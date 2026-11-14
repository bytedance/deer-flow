"""Late results from an earlier graph entry cannot poison its successor."""

import gc
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.messages import ToolMessage

from deerflow.agents.middlewares.tool_progress_middleware import ToolProgressMiddleware
from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY


def _result(failed):
    return ToolMessage(
        content="credential rejected" if failed else "fresh useful result",
        tool_call_id="call",
        additional_kwargs={
            TOOL_META_KEY: {
                "status": "error" if failed else "success",
                "error_type": "auth" if failed else None,
                "recoverable_by_model": not failed,
                "recommended_next_action": "stop" if failed else "continue",
                "source": "tool_return",
            }
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("next_run", ["new-run", "old-run", None])
async def test_late_failure_does_not_block_next_graph_entry(asynchronous, next_run):
    middleware = ToolProgressMiddleware()
    old = SimpleNamespace(context={"thread_id": "thread", "run_id": "old-run" if next_run else None})
    new = SimpleNamespace(context={"thread_id": "thread", "run_id": next_run})
    middleware.before_agent({}, old)
    request = SimpleNamespace(tool_call={"name": "lookup", "id": "call"}, runtime=old)
    late = _result(True)

    def handler(_):
        # The old tool started before a new invocation reset the thread guard.
        middleware.before_agent({}, new)
        return late

    async def ahandler(_):
        await middleware.abefore_agent({}, new)
        return late

    returned = await middleware.awrap_tool_call(request, ahandler) if asynchronous else middleware.wrap_tool_call(request, handler)
    assert returned is late  # Keep the old run's real outcome for its caller.
    request.runtime = new
    fresh = _result(False)
    executed = []

    def succeeding(_):
        executed.append(True)
        return fresh

    async def asucceeding(_):
        return succeeding(_)

    returned = await middleware.awrap_tool_call(request, asucceeding) if asynchronous else middleware.wrap_tool_call(request, succeeding)
    assert executed == [True]
    assert returned is fresh
    assert middleware._drain_pending(new) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_failed_model_call_cannot_restore_hints_into_new_entry(asynchronous):
    middleware = ToolProgressMiddleware(stagnation_threshold=1)
    runtime = SimpleNamespace(context={"thread_id": "thread", "run_id": "run"})
    middleware.before_agent({}, runtime)
    request = SimpleNamespace(tool_call={"name": "lookup", "id": "call"}, runtime=runtime)
    message = _result(True)
    message.additional_kwargs[TOOL_META_KEY].update(error_type="no_results", recoverable_by_model=True, recommended_next_action="rewrite_query")
    middleware.wrap_tool_call(request, lambda _: message)
    model_request = Mock(runtime=runtime, messages=[])

    def handler(_):
        middleware.before_agent({}, runtime)
        assert middleware._drain_pending(runtime) == []
        raise RuntimeError("old request failed after re-entry")

    async def ahandler(_):
        return handler(_)

    with pytest.raises(RuntimeError, match="old request failed"):
        if asynchronous:
            await middleware.awrap_model_call(model_request, ahandler)
        else:
            middleware.wrap_model_call(model_request, handler)
    assert middleware._drain_pending(runtime) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("other_uses_tool", [False, True], ids=["model-only", "history-eviction"])
async def test_unrelated_entry_only_invalidates_result_on_history_eviction(asynchronous, other_uses_tool):
    middleware = ToolProgressMiddleware(max_tracked_threads=1)
    tracked = SimpleNamespace(context={"thread_id": "tracked", "run_id": "run-a"})
    other = SimpleNamespace(context={"thread_id": "other", "run_id": "run-b"})
    middleware.before_agent({}, tracked)
    request = SimpleNamespace(tool_call={"name": "lookup", "id": "call"}, runtime=tracked)
    fresh = _result(False)
    middleware.wrap_tool_call(request, lambda _: fresh)  # Establish real tracked tool history.

    current_failure = _result(True)

    other_request = SimpleNamespace(tool_call={"name": "lookup", "id": "call"}, runtime=other)

    def handler(_):
        middleware.before_agent({}, other)
        if other_uses_tool:
            middleware.wrap_tool_call(other_request, lambda _: fresh)
        return current_failure

    async def ahandler(_):
        await middleware.abefore_agent({}, other)
        if other_uses_tool:

            async def other_succeeds(_):
                return fresh

            await middleware.awrap_tool_call(other_request, other_succeeds)
        return current_failure

    if asynchronous:
        assert await middleware.awrap_tool_call(request, ahandler) is current_failure
    else:
        assert middleware.wrap_tool_call(request, handler) is current_failure

    retry = SimpleNamespace(tool_call={"name": "lookup", "id": "retry"}, runtime=tracked)
    executed = []

    def succeeding(_):
        executed.append(True)
        return fresh

    async def asucceeding(_):
        return succeeding(_)

    result = await middleware.awrap_tool_call(retry, asucceeding) if asynchronous else middleware.wrap_tool_call(retry, succeeding)
    if other_uses_tool:
        # A real history eviction still drops the old result's assessment.
        assert executed == [True]
        assert result is fresh
    else:
        assert executed == []
        assert result.status == "error"
        assert result.tool_call_id == "retry"


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_model_only_entry_does_not_discard_failed_model_call_hints(asynchronous):
    middleware = ToolProgressMiddleware(max_tracked_threads=1, stagnation_threshold=1)
    tracked = SimpleNamespace(context={"thread_id": "tracked", "run_id": "run-a"})
    other = SimpleNamespace(context={"thread_id": "other", "run_id": "run-b"})
    middleware.before_agent({}, tracked)
    tool_request = SimpleNamespace(tool_call={"name": "lookup", "id": "call"}, runtime=tracked)
    message = _result(True)
    message.additional_kwargs[TOOL_META_KEY].update(error_type="no_results", recoverable_by_model=True, recommended_next_action="rewrite_query")
    middleware.wrap_tool_call(tool_request, lambda _: message)
    model_request = Mock(runtime=tracked, messages=[])
    model_request.override.side_effect = lambda **updates: SimpleNamespace(**updates)

    def handler(request):
        assert len(request.messages) == 1
        middleware.before_agent({}, other)
        raise RuntimeError("model request failed")

    async def ahandler(request):
        return handler(request)

    with pytest.raises(RuntimeError, match="model request failed"):
        if asynchronous:
            await middleware.awrap_model_call(model_request, ahandler)
        else:
            middleware.wrap_model_call(model_request, handler)
    assert len(middleware._drain_pending(tracked)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_completed_model_only_wrappers_leave_no_epoch_history(asynchronous):
    middleware = ToolProgressMiddleware(max_tracked_threads=1)
    response = object()

    async def ahandler(_):
        return response

    for index in range(3):
        runtime = SimpleNamespace(context={"thread_id": f"model-only-{index}", "run_id": f"run-{index}"})
        request = Mock(runtime=runtime, messages=[])
        middleware.before_agent({}, runtime)
        returned = await middleware.awrap_model_call(request, ahandler) if asynchronous else middleware.wrap_model_call(request, lambda _: response)
        assert returned is response

    gc.collect()
    assert not middleware._entry_epochs
