"""Result changes distinguish useful repeated calls from stalled tool loops."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.content import create_text_block
from langchain_core.tools import tool
from pydantic import PrivateAttr

from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
from deerflow.agents.middlewares.read_before_write_middleware import READ_MARK_KEY, ReadBeforeWriteMiddleware
from deerflow.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware
from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware
from deerflow.agents.thread_state import ThreadState


class _ScriptedModel(FakeMessagesListChatModel):
    _requests: list[list[Any]] = PrivateAttr(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._requests.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _call(name, args, call_id="call_0"):
    # Providers may reuse the same ID in every response.
    return {"name": name, "args": args, "id": call_id}


async def _invoke(graph, async_mode, context, **extra_state):
    state = {"messages": [("user", "Continue until the requested work is complete.")], **extra_state}
    if async_mode:
        return await graph.ainvoke(state, context=context, config={"recursion_limit": 100})
    return graph.invoke(state, context=context, config={"recursion_limit": 100})


def _warnings(model):
    return [message for messages in model._requests for message in messages if isinstance(message, HumanMessage) and message.name == "loop_warning"]


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("ranged_read", [False, True])
async def test_read_modify_reread_keeps_making_progress(tmp_path, async_mode, ranged_read):
    report = tmp_path / "report.md"
    report.write_text("Report\nv1\n", encoding="utf-8", newline="\n")
    edits = []

    @tool
    def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
        """Read the requested lines of the temporary report."""
        return "".join(Path(path).read_text(encoding="utf-8").splitlines(keepends=True)[start_line - 1 : end_line])

    @tool
    def str_replace(path: str, old_str: str, new_str: str) -> str:
        """Apply one edit to the temporary report."""
        target = Path(path)
        content = target.read_text(encoding="utf-8")
        assert old_str in content
        target.write_text(content.replace(old_str, new_str), encoding="utf-8", newline="\n")
        edits.append(new_str)
        return "Successfully replaced the requested text."

    responses = []
    for version in range(1, 7):
        read_args = {"path": str(report), **({"start_line": 1, "end_line": 1} if ranged_read else {})}
        responses.append(AIMessage(content="", tool_calls=[_call("read_file", read_args)]))
        responses.append(AIMessage(content="", tool_calls=[_call("str_replace", {"path": str(report), "old_str": f"v{version}", "new_str": f"v{version + 1}"})]))
    responses.append(AIMessage(content="Done."))
    model = _ScriptedModel(responses=responses)
    loop = LoopDetectionMiddleware()
    gate = ReadBeforeWriteMiddleware(content_reader=lambda _runtime, path: Path(path).read_text(encoding="utf-8"))
    graph = create_agent(model=model, tools=[read_file, str_replace], middleware=[gate, loop])
    context = {"thread_id": "editing", "run_id": "editing"}

    result = await _invoke(graph, async_mode, context)

    assert edits == [f"v{version}" for version in range(2, 8)]
    assert report.read_text(encoding="utf-8") == "Report\nv7\n"
    tool_results = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    reads = [message for message in tool_results if message.name == "read_file"]
    assert len({message.additional_kwargs[READ_MARK_KEY]["hash"] for message in reads}) == 6
    if ranged_read:
        # The visible first line stays identical; the full-file version changes.
        assert {message.content for message in reads} == {"Report\n"}
    assert all(message.status == "success" for message in tool_results)
    assert result["messages"][-1].content == "Done."
    assert not _warnings(model)
    assert context.get("stop_reason") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("edit_result", ["same_file", "other_file", "failed"])
async def test_reread_near_limit_after_file_edit(tmp_path, async_mode, edit_result):
    report = tmp_path / "report.md"
    other = tmp_path / "other.md"
    report.write_text("v1", encoding="utf-8")
    reads = []

    @tool
    def read_file(path: str) -> str:
        """Read the report."""
        content = Path(path).read_text(encoding="utf-8")
        reads.append(content)
        return content

    @tool
    def str_replace(path: str) -> ToolMessage:
        """Apply a test edit."""
        if edit_result == "failed":
            return ToolMessage(content="Edit failed", status="error", tool_call_id="call_0")
        Path(path).write_text("v2", encoding="utf-8")
        return ToolMessage(content="Edited", tool_call_id="call_0")

    read = _call("read_file", {"path": str(report)})
    edit = _call("str_replace", {"path": str(other if edit_result == "other_file" else report)})
    responses = [AIMessage(content="", tool_calls=[call]) for call in [read, read, read, read, edit, read]]
    model = _ScriptedModel(responses=[*responses, AIMessage(content="Done.")])
    graph = create_agent(model=model, tools=[read_file, str_replace], middleware=[LoopDetectionMiddleware()])
    context = {"thread_id": "edit-at-limit", "run_id": "edit-at-limit"}
    result = await _invoke(graph, async_mode, context)

    if edit_result == "same_file":
        assert reads == ["v1"] * 4 + ["v2"]
        assert result["messages"][-1].content == "Done."
        assert context.get("stop_reason") is None
    else:
        assert reads == ["v1"] * 4
        assert context["stop_reason"] == "loop_capped"


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_trimmed_delegations_preserve_progress_in_admitted_batch(async_mode):
    from deerflow.agents.lead_agent.agent import build_middlewares
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig

    observed = []
    delegated = []

    @tool
    def inspect_job() -> str:
        """Return the next observed job state."""
        observed.append(len(observed) + 1)
        return str(observed[-1])

    @tool
    def task(description: str) -> str:
        """Record the admitted delegation."""
        delegated.append(description)
        return "Done."

    config = {"configurable": {"subagent_enabled": True, "max_concurrent_subagents": 1}}
    app_config = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
    chain = build_middlewares(config, model_name=None, app_config=app_config, memory_enabled=False, available_skills=set())
    middlewares = [mw for mw in chain if isinstance(mw, (LoopDetectionMiddleware, SubagentLimitMiddleware))]
    calls = [
        _call("inspect_job", {}),
        _call("task", {"description": "admitted"}, "task-1"),
        _call("task", {"description": "trimmed"}, "task-2"),
    ]
    model = _ScriptedModel(responses=[AIMessage(content="", tool_calls=calls) for _ in range(6)] + [AIMessage(content="Done.")])
    graph = create_agent(model=model, tools=[inspect_job, task], middleware=middlewares)
    context = {"thread_id": "admitted-batch", "run_id": "admitted-batch"}
    result = await _invoke(graph, async_mode, context)

    assert observed == list(range(1, 7))
    assert delegated == ["admitted"] * 6
    assert result["messages"][-1].content == "Done."
    assert context.get("stop_reason") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("batched", [False, True])
async def test_changing_results_work_for_arbitrary_tools(async_mode, batched):
    observations = []

    @tool
    def inspect_job(job: str) -> list[dict]:
        """Return the next observed job state."""
        observations.append(len(observations) + 1)
        return [{"type": "text", "text": f"Completed {observations[-1]} steps"}]

    @tool
    def lookup_owner(job: str) -> str:
        """Return the stable owner of the job."""
        return "owner"

    responses = []
    for index in range(6):
        calls = [_call("inspect_job", {"job": "demo"})]
        if batched:
            calls.append(_call("lookup_owner", {"job": "demo"}, "call_1"))
            if index % 2:
                calls.reverse()
        responses.append(AIMessage(content="", tool_calls=calls))
    responses.append(AIMessage(content="Done."))
    model = _ScriptedModel(responses=responses)
    loop = LoopDetectionMiddleware()
    graph = create_agent(model=model, tools=[inspect_job, lookup_owner], middleware=[loop])

    result = await _invoke(graph, async_mode, {"thread_id": "jobs", "run_id": "jobs"})

    assert observations == list(range(1, 7))
    assert result["messages"][-1].content == "Done."
    assert not _warnings(model)
    assert loop.consume_stop_reason("jobs") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("failure", [None, "native", "metadata"])
async def test_unchanged_results_and_changing_errors_still_stop(async_mode, failure):
    executions = []

    @tool
    def inspect_job(job: str) -> ToolMessage:
        """Inspect the same stalled job through the tool boundary."""
        executions.append(len(executions) + 1)
        metadata = {"receipt": {"id": len(executions)}}
        if failure == "metadata":
            metadata["deerflow_tool_meta"] = {"status": "error", "error_type": "transient"}
        return ToolMessage(
            content=f"Attempt {executions[-1]} failed" if failure else "No change",
            status="error" if failure == "native" else "success",
            additional_kwargs=metadata,
            tool_call_id="call_0",
        )

    model = _ScriptedModel(responses=[AIMessage(content="", tool_calls=[_call("inspect_job", {"job": "demo"})]) for _ in range(6)])
    loop = LoopDetectionMiddleware()
    graph = create_agent(model=model, tools=[inspect_job], middleware=[loop])
    context = {"thread_id": "stalled", "run_id": "stalled"}

    result = await _invoke(graph, async_mode, context)

    assert len(executions) == 4
    assert len(model._requests) == 5
    assert len(_warnings(model)) == 1
    assert not result["messages"][-1].tool_calls
    assert context["stop_reason"] == "loop_capped"


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_unchanged_block_results_stop_despite_fresh_block_ids(async_mode):
    executions = []

    @tool
    def browser_snapshot() -> list[dict]:
        """Return the same page snapshot on every call."""
        executions.append(len(executions) + 1)
        # MCP result conversion builds blocks with create_text_block, which
        # stamps a fresh lc_<uuid> id on every block.
        return [create_text_block("- button 'Next' [ref=e12]")]

    responses = [AIMessage(content="", tool_calls=[_call("browser_snapshot", {}, f"call_{index}")]) for index in range(6)]
    model = _ScriptedModel(responses=responses)
    graph = create_agent(model=model, tools=[browser_snapshot], middleware=[LoopDetectionMiddleware()])
    context = {"thread_id": "snapshots", "run_id": "snapshots"}

    result = await _invoke(graph, async_mode, context)

    tool_results = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    assert len({message.content[0]["id"] for message in tool_results}) == len(tool_results)
    assert len(executions) == 4
    assert len(_warnings(model)) == 1
    assert not result["messages"][-1].tool_calls
    assert context["stop_reason"] == "loop_capped"


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("page_changes", [False, True])
async def test_externalized_results_compare_the_output_not_the_preview(tmp_path, async_mode, page_changes):
    fetches = []

    @tool
    def web_fetch(url: str) -> str:
        """Fetch a page large enough to be externalized."""
        fetches.append(url)
        revision = len(fetches) if page_changes else 1
        return f"Revision {revision}\n" + "Lorem ipsum dolor sit amet.\n" * 1000

    responses = [AIMessage(content="", tool_calls=[_call("web_fetch", {"url": "https://example.com"}, f"call_{index}")]) for index in range(6)]
    model = _ScriptedModel(responses=[*responses, AIMessage(content="Done.")])
    graph = create_agent(model=model, tools=[web_fetch], middleware=[ToolOutputBudgetMiddleware(), LoopDetectionMiddleware()], state_schema=ThreadState)
    context = {"thread_id": "fetches", "run_id": "fetches"}

    result = await _invoke(graph, async_mode, context, thread_data={"outputs_path": str(tmp_path)})

    # Every preview names a per-call file, so the visible results always differ.
    previews = [message.content for message in result["messages"] if isinstance(message, ToolMessage)]
    assert all("output saved to" in preview for preview in previews)
    assert len(set(previews)) == len(previews)
    if page_changes:
        assert len(fetches) == 6
        assert result["messages"][-1].content == "Done."
        assert not _warnings(model)
        assert context.get("stop_reason") is None
    else:
        assert len(fetches) == 4
        assert len(_warnings(model)) == 1
        assert context["stop_reason"] == "loop_capped"


@pytest.mark.asyncio
async def test_repeated_result_cycle_still_stops():
    executions = []

    @tool
    def inspect_job(job: str) -> str:
        """Observe a job oscillating between two states."""
        executions.append(len(executions) % 2)
        return str(executions[-1])

    model = _ScriptedModel(responses=[AIMessage(content="", tool_calls=[_call("inspect_job", {"job": "demo"})]) for _ in range(12)])
    graph = create_agent(model=model, tools=[inspect_job], middleware=[LoopDetectionMiddleware()])
    context = {"thread_id": "cycling", "run_id": "cycling"}

    await _invoke(graph, True, context)

    # Four observed zeroes plus the next predicted zero reach the hard limit.
    assert executions == [0, 1, 0, 1, 0, 1, 0]
    assert context["stop_reason"] == "loop_capped"


@pytest.mark.asyncio
async def test_changing_results_are_not_stopped_by_tool_frequency_metrics():
    executions = []

    @tool
    def inspect_job(job: str) -> str:
        """Observe a job that always returns a new state."""
        executions.append(len(executions))
        return str(executions[-1])

    model = _ScriptedModel(responses=[AIMessage(content="", tool_calls=[_call("inspect_job", {"job": "demo"})]) for _ in range(8)] + [AIMessage(content="Done.")])
    loop = LoopDetectionMiddleware(tool_freq_warn=4, tool_freq_hard_limit=6)
    graph = create_agent(model=model, tools=[inspect_job], middleware=[loop])
    context = {"thread_id": "budget", "run_id": "budget"}

    result = await _invoke(graph, True, context)

    assert len(executions) == 8
    assert result["messages"][-1].content == "Done."
    assert not _warnings(model)
    assert context.get("stop_reason") is None


@pytest.mark.asyncio
async def test_noop_writes_still_hit_the_loop_limit(tmp_path):
    report = tmp_path / "report.md"
    report.write_text("unchanged", encoding="utf-8", newline="\n")
    reads, writes = [], []

    @tool
    def read_file(path: str) -> str:
        """Read the temporary report."""
        reads.append(path)
        return Path(path).read_text(encoding="utf-8")

    @tool
    def write_file(path: str, content: str) -> str:
        """Write the same report contents."""
        writes.append(path)
        Path(path).write_text(content, encoding="utf-8", newline="\n")
        return "Saved."

    calls = [AIMessage(content="", tool_calls=[_call(name, args)]) for _ in range(6) for name, args in [("read_file", {"path": str(report)}), ("write_file", {"path": str(report), "content": "unchanged"})]]
    model = _ScriptedModel(responses=calls)
    loop = LoopDetectionMiddleware()
    gate = ReadBeforeWriteMiddleware(content_reader=lambda _runtime, path: Path(path).read_text(encoding="utf-8"))
    graph = create_agent(model=model, tools=[read_file, write_file], middleware=[gate, loop])
    context = {"thread_id": "noop", "run_id": "noop"}

    await _invoke(graph, True, context)

    # The last successful write warrants one more read. Its result settles to
    # the old version, and the unchanged write loop still reaches the cap.
    assert len(reads) == 5
    assert len(writes) == 4
    assert report.read_text(encoding="utf-8") == "unchanged"
    assert context["stop_reason"] == "loop_capped"


def _runtime():
    return SimpleNamespace(context={"thread_id": "history", "run_id": "history"})


@pytest.mark.parametrize("metadata", [None, [], {"deerflow_tool_meta": ["error"]}, {READ_MARK_KEY: {"path": [], "hash": {}}}, {READ_MARK_KEY: {"path": "/report", "hash": "not-a-digest"}}])
def test_malformed_persisted_metadata_cannot_disable_loop_protection(metadata):
    loop = LoopDetectionMiddleware()
    messages = []
    for index in range(5):
        messages.append(AIMessage(id=f"turn-{index}", content="", tool_calls=[_call("inspect_job", {})]))
        update = loop.after_model({"messages": messages}, _runtime())
        if index < 4:
            result = ToolMessage(content="unchanged", tool_call_id="call_0").model_copy(update={"additional_kwargs": metadata})
            messages.append(result)

    assert not update["messages"][0].tool_calls
    assert loop.consume_stop_reason("history") == "loop_capped"


@pytest.mark.parametrize("malformation", ["missing", "duplicate_id", "unserializable"])
def test_incomplete_batches_do_not_borrow_results_from_reused_call_ids(malformation):
    loop = LoopDetectionMiddleware()
    messages = []
    for index in range(5):
        calls = [_call("inspect_job", {}), _call("lookup_owner", {}, "call_0" if malformation == "duplicate_id" else "call_1")]
        messages.append(AIMessage(id=f"turn-{index}", content="", tool_calls=calls))
        update = loop.after_model({"messages": messages}, _runtime())
        if index < 4:
            messages.append(ToolMessage(content=f"state {index}", tool_call_id="call_0"))
            if malformation != "missing":
                result = ToolMessage(content="owner", tool_call_id=calls[1]["id"])
                if malformation == "unserializable":
                    cyclic = []
                    cyclic.append(cyclic)
                    result = result.model_copy(update={"content": cyclic})
                messages.append(result)

    assert not update["messages"][0].tool_calls
    assert loop.consume_stop_reason("history") == "loop_capped"


def test_compacted_history_cannot_settle_a_different_call_occurrence():
    loop = LoopDetectionMiddleware(hard_limit=3)
    call = _call("inspect_job", {})
    latest = AIMessage(id="current", content="", tool_calls=[call])
    loop.after_model({"messages": [latest]}, _runtime())
    for index in range(2):
        # A stale checkpoint retains the same call ID, but a different AIMessage.
        stale = AIMessage(id="old", content="", tool_calls=[call])
        result = ToolMessage(content=f"old state {index}", tool_call_id="call_0")
        latest = AIMessage(id=f"next-{index}", content="", tool_calls=[call])
        update = loop.after_model({"messages": [stale, result, latest]}, _runtime())

    assert not update["messages"][0].tool_calls
    assert loop.consume_stop_reason("history") == "loop_capped"
