"""Late results from an earlier graph entry cannot poison its successor."""

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
