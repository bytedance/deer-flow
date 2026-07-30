"""The probes, driven directly -- including the case the placement exists for."""

from __future__ import annotations

import pytest
from conftest import FakeModelRequest, FakeToolRequest, task_scope
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow_extension_example.probes import (
    LogicalModelProbe,
    PhysicalModelProbe,
    RawToolProbe,
    VisibleToolProbe,
)
from deerflow_extension_example.stats import TaskRecord


def _record(task_store) -> TaskRecord:
    record = TaskRecord(task_id="task-1", kind="lead", thread_id="thread-1")
    task_store.set(record)
    return record


async def test_one_logical_decision_can_cost_several_physical_calls() -> None:
    """The guarantee the model-axis pair encodes, observed end to end.

    The physical probe sits inner of retry; the logical probe sits outer of it.
    So a retried decision must count once logically and twice physically -- this
    is the assertion that would fail if either placement were misdeclared.
    """
    task_store, runtime = task_scope()
    record = _record(task_store)
    logical = LogicalModelProbe()
    physical = PhysicalModelProbe()
    request = FakeModelRequest(runtime=runtime)

    async def provider(_request: FakeModelRequest) -> str:
        return "response"

    async def retrying_handler(inner: FakeModelRequest) -> str:
        await physical.awrap_model_call(inner, provider)
        return await physical.awrap_model_call(inner, provider)

    result = await logical.awrap_model_call(request, retrying_handler)

    assert result == "response"
    assert record.logical_model_calls == 1
    assert record.physical_model_calls == 2
    assert record.model_seconds >= 0.0


async def test_a_failed_attempt_still_counts_and_still_raises() -> None:
    task_store, runtime = task_scope()
    record = _record(task_store)

    async def failing(_request: FakeModelRequest) -> str:
        raise RuntimeError("provider is down")

    with pytest.raises(RuntimeError, match="provider is down"):
        await PhysicalModelProbe().awrap_model_call(FakeModelRequest(runtime=runtime), failing)

    assert record.physical_model_calls == 1


async def test_tool_probes_measure_both_ends_of_the_same_call() -> None:
    task_store, runtime = task_scope()
    record = _record(task_store)
    request = FakeToolRequest(tool_call={"name": "web_fetch"}, runtime=runtime)
    raw = RawToolProbe()
    visible = VisibleToolProbe()

    async def tool(_request: FakeToolRequest) -> ToolMessage:
        return ToolMessage(content="x" * 100, tool_call_id="call-1")

    async def truncating_handler(inner: FakeToolRequest) -> ToolMessage:
        # Stands in for the host's output budget: the raw probe is inner of it,
        # the visible probe is outer of it.
        result = await raw.awrap_tool_call(inner, tool)
        return ToolMessage(content=result.content[:10], tool_call_id="call-1")

    result = await visible.awrap_tool_call(request, truncating_handler)

    assert len(result.content) == 10
    assert record.raw_result_chars == 100
    assert record.visible_result_chars == 10
    assert record.tool_calls == 1
    assert record.tools_used == {"web_fetch": 1}


async def test_a_command_wrapped_result_is_unwrapped_not_counted_as_zero() -> None:
    """The production shape: the host's SandboxMiddleware sits between the two
    probes and rewraps the ToolMessage into a Command so the sandbox id reaches
    state. The outer probe therefore sees a Command, and counting that as zero
    would make the raw/visible pair measure different things — which reads as
    "the host truncated everything" instead of "I failed to unwrap"."""
    task_store, runtime = task_scope()
    record = _record(task_store)
    request = FakeToolRequest(tool_call={"name": "bash"}, runtime=runtime)
    raw = RawToolProbe()
    visible = VisibleToolProbe()

    async def tool(_request: FakeToolRequest) -> ToolMessage:
        return ToolMessage(content="200000\n", tool_call_id="call-1")

    async def sandbox_wrapping_handler(inner: FakeToolRequest) -> Command:
        result = await raw.awrap_tool_call(inner, tool)
        return Command(update={"sandbox": {"sandbox_id": "local:t1"}, "messages": [result]})

    await visible.awrap_tool_call(request, sandbox_wrapping_handler)

    assert record.raw_result_chars == 7
    assert record.visible_result_chars == 7, "the outer probe must see through the Command wrapper"
    assert record.tool_calls == 1


async def test_a_pure_control_flow_command_measures_as_zero() -> None:
    """A Command with no messages carries no content — zero is correct there."""
    task_store, runtime = task_scope()
    record = _record(task_store)

    async def tool(_request: FakeToolRequest) -> Command:
        return Command(goto="__end__")

    await VisibleToolProbe().awrap_tool_call(FakeToolRequest(tool_call={"name": "ask_clarification"}, runtime=runtime), tool)

    assert record.tool_calls == 1
    assert record.visible_result_chars == 0


async def test_a_result_with_neither_content_nor_update_measures_as_zero() -> None:
    task_store, runtime = task_scope()
    record = _record(task_store)

    async def tool(_request: FakeToolRequest) -> object:
        return object()

    await VisibleToolProbe().awrap_tool_call(FakeToolRequest(tool_call={"name": "task"}, runtime=runtime), tool)

    assert record.tool_calls == 1
    assert record.visible_result_chars == 0


async def test_unnamed_tool_calls_do_not_break_the_breakdown() -> None:
    task_store, runtime = task_scope()
    record = _record(task_store)

    async def tool(_request: FakeToolRequest) -> ToolMessage:
        return ToolMessage(content="ok", tool_call_id="call-1")

    await VisibleToolProbe().awrap_tool_call(FakeToolRequest(tool_call={}, runtime=runtime), tool)

    assert record.tools_used == {"<unknown>": 1}


@pytest.mark.parametrize("runtime", [None, "no-context"])
async def test_probes_pass_through_when_there_is_no_task_scope(runtime: object) -> None:
    """A directly invoked subagent has no parent task, so it gets no task store.

    Every probe must degrade to a plain pass-through there. This is the test
    that catches an extension assuming the store is always present.
    """

    async def provider(_request: object) -> str:
        return "response"

    async def tool(_request: object) -> ToolMessage:
        return ToolMessage(content="ok", tool_call_id="call-1")

    model_request = FakeModelRequest(runtime=None if runtime is None else runtime)
    tool_request = FakeToolRequest(tool_call={"name": "bash"}, runtime=None if runtime is None else runtime)

    assert await LogicalModelProbe().awrap_model_call(model_request, provider) == "response"
    assert await PhysicalModelProbe().awrap_model_call(model_request, provider) == "response"
    assert (await VisibleToolProbe().awrap_tool_call(tool_request, tool)).content == "ok"
    assert (await RawToolProbe().awrap_tool_call(tool_request, tool)).content == "ok"


async def test_probes_pass_through_when_the_task_store_holds_no_record() -> None:
    task_store, runtime = task_scope()  # store exists, on_task_start never ran

    async def provider(_request: FakeModelRequest) -> str:
        return "response"

    assert await LogicalModelProbe().awrap_model_call(FakeModelRequest(runtime=runtime), provider) == "response"
    assert task_store.get(TaskRecord) is None
