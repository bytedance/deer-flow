"""Unit tests for subagent recovery, transcript sanitization, and resumption."""

import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from deerflow.subagents.config import SubagentConfig
from deerflow.subagents.recovery import (
    INTERRUPTED_TOOL_RESULT_CONTENT,
    dict_to_message,
    extract_resumable_messages,
    filter_empty_assistant_messages,
    filter_unresolved_tool_calls,
    get_resumable_subagent_task,
    sanitize_subagent_history,
)

_MOCKED_MODULE_NAMES = [
    "deerflow.agents",
    "deerflow.agents.thread_state",
    "deerflow.agents.middlewares",
    "deerflow.agents.middlewares.thread_data_middleware",
    "deerflow.sandbox",
    "deerflow.sandbox.middleware",
    "deerflow.sandbox.security",
    "deerflow.models",
    "deerflow.skills.storage",
]


@pytest.fixture(autouse=True)
def _setup_executor_classes():
    """Un-mock executor module and import real implementation (matching test_subagent_executor pattern)."""
    original_modules = {name: sys.modules.get(name) for name in _MOCKED_MODULE_NAMES}
    original_executor = sys.modules.get("deerflow.subagents.executor")

    audit_context_module = importlib.import_module("deerflow.agents.middlewares.audit_context")
    tool_declarations_module = importlib.import_module("deerflow.agents.middlewares.tool_declarations")
    tool_search_module = importlib.import_module("deerflow.tools.builtins.tool_search")
    sandbox_provider_module = importlib.import_module("deerflow.sandbox.sandbox_provider")
    sandbox_overwrite_module = importlib.import_module("deerflow.sandbox.overwrite")
    sandbox_prewarm_module = importlib.import_module("deerflow.sandbox.prewarm")

    if "deerflow.subagents.executor" in sys.modules:
        del sys.modules["deerflow.subagents.executor"]
    subagents_pkg = sys.modules.get("deerflow.subagents")
    if subagents_pkg is not None and hasattr(subagents_pkg, "executor"):
        delattr(subagents_pkg, "executor")

    for name in _MOCKED_MODULE_NAMES:
        sys.modules[name] = MagicMock()
    storage_module = ModuleType("deerflow.skills.storage")
    storage_module.get_or_new_skill_storage = lambda **kwargs: SimpleNamespace(load_skills=lambda *, enabled_only: [])
    storage_module.get_or_new_user_skill_storage = lambda user_id, **kwargs: SimpleNamespace(load_skills=lambda *, enabled_only: [])
    sys.modules["deerflow.skills.storage"] = storage_module
    sys.modules["deerflow.agents.middlewares.audit_context"] = audit_context_module
    sys.modules["deerflow.agents.middlewares.tool_declarations"] = tool_declarations_module
    sys.modules["deerflow.tools.builtins.tool_search"] = tool_search_module
    sys.modules["deerflow.sandbox.sandbox_provider"] = sandbox_provider_module
    sys.modules["deerflow.sandbox.overwrite"] = sandbox_overwrite_module
    sys.modules["deerflow.sandbox.prewarm"] = sandbox_prewarm_module

    from deerflow.subagents.executor import (
        SubagentExecutor,
        SubagentResult,
        SubagentStatus,
        _background_tasks,
        _background_tasks_lock,
    )

    yield {
        "SubagentExecutor": SubagentExecutor,
        "SubagentResult": SubagentResult,
        "SubagentStatus": SubagentStatus,
        "_background_tasks": _background_tasks,
        "_background_tasks_lock": _background_tasks_lock,
    }

    for name, mod in original_modules.items():
        if mod is not None:
            sys.modules[name] = mod
        elif name in sys.modules:
            del sys.modules[name]
    if original_executor is not None:
        sys.modules["deerflow.subagents.executor"] = original_executor
    elif "deerflow.subagents.executor" in sys.modules:
        del sys.modules["deerflow.subagents.executor"]


def test_dict_to_message_conversions():
    """Verify dict-to-BaseMessage deserialization for all message types."""
    # AI message with tool calls
    ai_dict = {
        "type": "ai",
        "content": "Let me search for that.",
        "tool_calls": [{"name": "web_search", "args": {"query": "pytest"}, "id": "call_1"}],
        "id": "ai_1",
    }
    ai_msg = dict_to_message(ai_dict)
    assert isinstance(ai_msg, AIMessage)
    assert ai_msg.content == "Let me search for that."
    assert len(ai_msg.tool_calls) == 1
    assert ai_msg.tool_calls[0]["id"] == "call_1"
    assert ai_msg.id == "ai_1"

    # Tool message
    tool_dict = {
        "type": "tool",
        "content": "Search results found",
        "tool_call_id": "call_1",
        "status": "success",
        "id": "tool_1",
    }
    tool_msg = dict_to_message(tool_dict)
    assert isinstance(tool_msg, ToolMessage)
    assert tool_msg.content == "Search results found"
    assert tool_msg.tool_call_id == "call_1"
    assert tool_msg.status == "success"

    # Human and System messages
    human_msg = dict_to_message({"type": "human", "content": "hello", "id": "h1"})
    assert isinstance(human_msg, HumanMessage)
    assert human_msg.content == "hello"

    sys_msg = dict_to_message({"type": "system", "content": "system prompt", "id": "s1"})
    assert isinstance(sys_msg, SystemMessage)
    assert sys_msg.content == "system prompt"


def test_filter_empty_assistant_messages():
    """Verify empty/whitespace-only assistant messages are stripped."""
    messages: list[BaseMessage] = [
        HumanMessage(content="Start"),
        AIMessage(content=""),  # Should be dropped
        AIMessage(content="   \n\t  "),  # Should be dropped
        AIMessage(content="", tool_calls=[{"name": "bash", "args": {}, "id": "c1"}]),  # Kept: has tool call
        AIMessage(content="Valid thought"),  # Kept: has text
    ]

    filtered = filter_empty_assistant_messages(messages)
    assert len(filtered) == 3
    assert filtered[0].content == "Start"
    assert getattr(filtered[1], "tool_calls", None) is not None
    assert filtered[2].content == "Valid thought"


def test_filter_unresolved_tool_calls_heals_dangling_calls():
    """Verify synthetic ToolMessages are generated for unfulfilled tool calls."""
    messages: list[BaseMessage] = [
        HumanMessage(content="Run both tasks"),
        AIMessage(
            content="Running tasks",
            tool_calls=[
                {"name": "task_a", "args": {}, "id": "call_a"},
                {"name": "task_b", "args": {}, "id": "call_b"},
            ],
        ),
        # Only task_a completed before crash/timeout
        ToolMessage(content="Task A completed", tool_call_id="call_a", status="success"),
    ]

    healed = filter_unresolved_tool_calls(messages)
    assert len(healed) == 4

    # Verify last message is synthetic ToolMessage for call_b
    synthetic = healed[3]
    assert isinstance(synthetic, ToolMessage)
    assert synthetic.tool_call_id == "call_b"
    assert synthetic.status == "error"
    assert INTERRUPTED_TOOL_RESULT_CONTENT in synthetic.content


def test_filter_unresolved_tool_calls_noop_when_all_resolved():
    """Verify no extra ToolMessages are injected when all tool calls are resolved."""
    messages: list[BaseMessage] = [
        AIMessage(
            content="Thinking",
            tool_calls=[{"name": "tool_x", "args": {}, "id": "call_x"}],
        ),
        ToolMessage(content="Done", tool_call_id="call_x", status="success"),
    ]
    healed = filter_unresolved_tool_calls(messages)
    assert len(healed) == 2
    assert healed == messages


def test_sanitize_subagent_history_end_to_end():
    """Verify full sanitization pipeline with dict inputs and mixed errors."""
    raw_history = [
        {"type": "system", "content": "You are a subagent."},
        {"type": "human", "content": "Please analyze this code."},
        {"type": "ai", "content": ""},  # Aborted empty message
        {
            "type": "ai",
            "content": "I will examine the directory.",
            "tool_calls": [{"name": "list_dir", "args": {"path": "."}, "id": "c_list"}],
        },
        # Missing tool result for c_list
    ]

    sanitized = sanitize_subagent_history(raw_history)
    assert len(sanitized) == 4
    assert isinstance(sanitized[0], SystemMessage)
    assert isinstance(sanitized[1], HumanMessage)
    assert isinstance(sanitized[2], AIMessage)
    assert isinstance(sanitized[3], ToolMessage)
    assert sanitized[3].tool_call_id == "c_list"
    assert sanitized[3].status == "error"


def test_extract_resumable_messages_from_subagent_result(_setup_executor_classes):
    """Verify extraction and healing from a SubagentResult with ai_messages."""
    classes = _setup_executor_classes
    result = classes["SubagentResult"](
        task_id="task_fail_1",
        trace_id="trace_123",
        status=classes["SubagentStatus"].FAILED,
        error="Process killed by timeout",
    )
    result.ai_messages = [
        {
            "type": "ai",
            "content": "Processing data",
            "tool_calls": [{"name": "compute", "args": {}, "id": "call_calc"}],
            "id": "msg_step_1",
        }
    ]

    extracted = extract_resumable_messages(result)
    assert len(extracted) == 2
    assert isinstance(extracted[0], AIMessage)
    assert isinstance(extracted[1], ToolMessage)
    assert extracted[1].tool_call_id == "call_calc"


def _dummy_app_config():
    return SimpleNamespace(
        models={"mock-model": SimpleNamespace(provider="test", model="test")},
        tool_search=SimpleNamespace(enabled=False),
        authorization=SimpleNamespace(enabled=False),
        skills=SimpleNamespace(
            deferred_discovery=False,
            container_path="/mnt/skills",
        ),
        skill_evolution=SimpleNamespace(enabled=False),
        verification=SimpleNamespace(receipts_enabled=False),
    )


@pytest.mark.asyncio
async def test_subagent_executor_resumes_from_initial_messages(_setup_executor_classes):
    """Verify SubagentExecutor._build_initial_state seeds from sanitized initial_messages."""
    classes = _setup_executor_classes
    cfg = SubagentConfig(name="resume-test", description="Test subagent", model="mock-model", system_prompt="Base prompt")
    initial_history: list[BaseMessage] = [
        SystemMessage(content="Existing system context"),
        HumanMessage(content="Previous prompt"),
        AIMessage(
            content="Working on it",
            tool_calls=[{"name": "fetch", "args": {}, "id": "c_fetch"}],
        ),
        # Dangling tool call
    ]

    executor = classes["SubagentExecutor"](
        config=cfg,
        tools=[],
        app_config=_dummy_app_config(),
        initial_messages=initial_history,
        resumed_from="task_prev_99",
    )
    assert executor.resumed_from == "task_prev_99"

    state, _, _ = await executor._build_initial_state("Continue with next step")
    messages = state["messages"]

    # Fresh SystemMessage(Base prompt) + HumanMessage(prev) + AIMessage + Synthetic ToolMessage + HumanMessage(continue)
    assert len(messages) == 5
    assert isinstance(messages[0], SystemMessage)
    assert "Base prompt" in messages[0].content
    assert isinstance(messages[1], HumanMessage)
    assert messages[1].content == "Previous prompt"
    assert isinstance(messages[3], ToolMessage)
    assert messages[3].tool_call_id == "c_fetch"
    assert isinstance(messages[4], HumanMessage)
    assert "Continue with next step" in messages[4].content


@pytest.mark.asyncio
async def test_task_tool_resumes_missing_task_id_fails_cleanly(monkeypatch):
    """Verify task_tool with non-existent resume_task_id returns clean failure."""
    import importlib

    task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")

    runtime = SimpleNamespace(
        config={"metadata": {"model_name": "mock-model", "trace_id": "trace-1"}},
        context={"thread_id": "thread-1"},
        state={},
    )
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    coroutine = getattr(task_tool_module.task_tool, "coroutine", None) or task_tool_module.task_tool.func
    cmd = await coroutine(
        runtime=runtime,
        prompt="continue",
        subagent_type="general-purpose",
        tool_call_id="call_mock_1",
        resume_task_id="nonexistent_task_123",
    )
    messages = cmd.update["messages"]
    assert len(messages) == 1
    assert isinstance(messages[0], ToolMessage)
    assert "nonexistent_task_123" in messages[0].content
    assert messages[0].additional_kwargs["subagent_status"] == "failed"


def test_get_resumable_subagent_task_lookup(_setup_executor_classes):
    """Verify task lookup by task_id and external_task_id."""
    classes = _setup_executor_classes
    _background_tasks = classes["_background_tasks"]
    _background_tasks_lock = classes["_background_tasks_lock"]

    test_res = classes["SubagentResult"](
        task_id="exec_uuid_1234",
        external_task_id="tool_call_external_5678",
        trace_id="tr_1",
        status=classes["SubagentStatus"].FAILED,
    )

    with _background_tasks_lock:
        _background_tasks["exec_uuid_1234"] = test_res

    try:
        # Lookup by execution ID
        found_by_exec = get_resumable_subagent_task("exec_uuid_1234")
        assert found_by_exec is test_res

        # Lookup by external tool_call ID
        found_by_ext = get_resumable_subagent_task("tool_call_external_5678")
        assert found_by_ext is test_res

        # Non-existent lookup
        assert get_resumable_subagent_task("nonexistent") is None
    finally:
        with _background_tasks_lock:
            _background_tasks.pop("exec_uuid_1234", None)


@pytest.mark.asyncio
async def test_task_tool_resumes_existing_task_seeds_executor(monkeypatch, _setup_executor_classes):
    """Verify task_tool loads previous result, sanitizes messages, and passes them to SubagentExecutor."""
    import importlib

    classes = _setup_executor_classes
    task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")

    captured = {}

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            captured["prompt"] = prompt
            return task_id or "new_exec_id"

    # Seed previous failed task into background tasks
    prev_result = classes["SubagentResult"](
        task_id="old_exec_123",
        external_task_id="call_old_subagent",
        trace_id="tr_prev",
        status=classes["SubagentStatus"].FAILED,
        initial_task="Original mission prompt",
        subagent_type="general-purpose",
    )
    prev_result.ai_messages = [{"type": "ai", "content": "I was checking files", "tool_calls": [{"name": "read", "args": {}, "id": "call_dangling"}]}]

    with classes["_background_tasks_lock"]:
        classes["_background_tasks"]["old_exec_123"] = prev_result

    try:
        monkeypatch.setattr(task_tool_module, "SubagentStatus", classes["SubagentStatus"])
        monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
        monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])
        monkeypatch.setattr(
            task_tool_module,
            "get_background_task_result",
            lambda _: classes["SubagentResult"](
                task_id="new_exec_id",
                trace_id="tr_new",
                status=classes["SubagentStatus"].COMPLETED,
                result="Successfully resumed and completed",
            ),
        )
        monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)

        async def _instant_sleep(_s):
            return

        monkeypatch.setattr(task_tool_module.asyncio, "sleep", _instant_sleep)

        runtime = SimpleNamespace(
            config={"metadata": {"model_name": "mock-model", "trace_id": "trace-1"}},
            context={"thread_id": "thread-1"},
            state={},
        )
        coroutine = getattr(task_tool_module.task_tool, "coroutine", None) or task_tool_module.task_tool.func
        cmd = await coroutine(
            runtime=runtime,
            prompt="continue from where you stopped",
            subagent_type="general-purpose",
            tool_call_id="call_resume_now",
            resume_task_id="old_exec_123",
        )

        assert "kwargs" in captured
        assert captured["kwargs"]["resumed_from"] == "old_exec_123"
        initial_msgs = captured["kwargs"]["initial_messages"]
        # HumanMessage(Original mission prompt) + AIMessage + ToolMessage(dangling)
        assert len(initial_msgs) == 3
        assert isinstance(initial_msgs[0], HumanMessage)
        assert initial_msgs[0].content == "Original mission prompt"
        assert isinstance(initial_msgs[1], AIMessage)
        assert isinstance(initial_msgs[2], ToolMessage)
        assert initial_msgs[2].tool_call_id == "call_dangling"

        message = cmd.update["messages"][0]
        assert message.additional_kwargs["subagent_status"] == "completed"
        assert "Successfully resumed" in message.content
    finally:
        with classes["_background_tasks_lock"]:
            classes["_background_tasks"].pop("old_exec_123", None)


def test_dict_to_message_synthesizes_id_when_missing():
    """Verify tool_calls missing an id are normalized without raising TypeError (Comment 4)."""
    raw = [{"type": "ai", "content": "running", "tool_calls": [{"name": "bash", "args": {}}]}]
    sanitized = sanitize_subagent_history(raw)
    assert len(sanitized) == 2  # AIMessage + synthetic ToolMessage
    ai_msg = sanitized[0]
    assert isinstance(ai_msg, AIMessage)
    assert len(ai_msg.tool_calls) == 1
    call_id = ai_msg.tool_calls[0]["id"]
    assert call_id.startswith("synth_call_")
    assert isinstance(sanitized[1], ToolMessage)
    assert sanitized[1].tool_call_id == call_id


def test_filter_unresolved_tool_calls_drops_idless_tools_and_scopes_per_turn():
    """Verify id-less ToolMessages are dropped and tool_call resolution is turn-scoped (Comment 5)."""
    raw = [
        # Turn 1: call_1 is resolved
        {"type": "ai", "content": "Turn 1", "tool_calls": [{"name": "tool_a", "args": {}, "id": "call_1"}]},
        {"type": "tool", "content": "orphan tool result with empty id", "tool_call_id": ""},
        {"type": "tool", "content": "Result 1", "tool_call_id": "call_1"},
        # Turn 2: same call_1 repeats from provider and is NOT resolved before next turn
        {"type": "ai", "content": "Turn 2", "tool_calls": [{"name": "tool_a", "args": {}, "id": "call_1"}]},
    ]
    sanitized = sanitize_subagent_history(raw)
    assert len(sanitized) == 4
    assert sanitized[0].content == "Turn 1"
    assert sanitized[1].tool_call_id == "call_1"
    assert sanitized[1].content == "Result 1"
    assert sanitized[2].content == "Turn 2"
    assert sanitized[3].tool_call_id == "call_1"
    assert INTERRUPTED_TOOL_RESULT_CONTENT in sanitized[3].content


def test_subagent_result_holding_area_and_supersede(_setup_executor_classes):
    """Verify terminal non-completed tasks are parked in holding area and supersede stops double-resumes (Comment 1)."""
    from deerflow.subagents.executor import (
        cleanup_background_task,
        get_resumable_holding_task,
    )
    from deerflow.subagents.recovery import supersede_and_claim_resumable_task

    classes = _setup_executor_classes
    _background_tasks = classes["_background_tasks"]
    _background_tasks_lock = classes["_background_tasks_lock"]

    task = classes["SubagentResult"](
        task_id="exec_hold_1",
        external_task_id="call_hold_1",
        trace_id="tr_hold",
        status=classes["SubagentStatus"].TIMED_OUT,
        error="Timeout exceeded",
        subagent_type="general-purpose",
    )
    task.execution_done_event.set()

    with _background_tasks_lock:
        _background_tasks["exec_hold_1"] = task

    # Cleanup should remove from _background_tasks but park into holding area
    cleanup_background_task("exec_hold_1")
    with _background_tasks_lock:
        assert "exec_hold_1" not in _background_tasks

    held = get_resumable_holding_task("exec_hold_1")
    assert held is task

    # First claim succeeds and marks superseded
    claimed = supersede_and_claim_resumable_task("exec_hold_1")
    assert claimed is task
    assert claimed.is_superseded is True

    # Second claim fails
    assert supersede_and_claim_resumable_task("exec_hold_1") is None


@pytest.mark.asyncio
async def test_subagent_type_mismatch_fails_cleanly(monkeypatch, _setup_executor_classes):
    """Verify resume with mismatched subagent_type returns clear error (Comment 2)."""
    import importlib

    classes = _setup_executor_classes
    task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")

    task = classes["SubagentResult"](
        task_id="exec_bash_task",
        external_task_id="call_bash",
        trace_id="tr_b",
        status=classes["SubagentStatus"].FAILED,
        subagent_type="bash",
    )
    with classes["_background_tasks_lock"]:
        classes["_background_tasks"]["exec_bash_task"] = task

    try:
        monkeypatch.setattr(task_tool_module, "SubagentStatus", classes["SubagentStatus"])
        monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

        runtime = SimpleNamespace(
            config={"metadata": {"model_name": "mock-model", "trace_id": "trace-1"}},
            context={"thread_id": "thread-1"},
            state={},
        )
        coroutine = getattr(task_tool_module.task_tool, "coroutine", None) or task_tool_module.task_tool.func
        cmd = await coroutine(
            runtime=runtime,
            prompt="continue",
            subagent_type="general-purpose",  # Mismatched!
            tool_call_id="call_resume_mismatch",
            resume_task_id="exec_bash_task",
        )
        message = cmd.update["messages"][0]
        assert "does not match requested 'general-purpose'" in message.content
        assert message.additional_kwargs["subagent_status"] == "failed"
    finally:
        with classes["_background_tasks_lock"]:
            classes["_background_tasks"].pop("exec_bash_task", None)


def test_extract_resumable_messages_includes_initial_task_human_message(_setup_executor_classes):
    """Verify initial_task prompt is preserved as the leading HumanMessage on resume (Comment 6)."""
    classes = _setup_executor_classes
    result = classes["SubagentResult"](
        task_id="task_with_prompt",
        trace_id="tr_p",
        status=classes["SubagentStatus"].FAILED,
        initial_task="Please count occurrences of word foo",
        subagent_type="general-purpose",
    )
    result.ai_messages = [{"type": "ai", "content": "I started searching", "tool_calls": []}]

    extracted = extract_resumable_messages(result)
    assert len(extracted) == 2
    assert isinstance(extracted[0], HumanMessage)
    assert extracted[0].content == "Please count occurrences of word foo"
    assert isinstance(extracted[1], AIMessage)
    assert extracted[1].content == "I started searching"


def test_task_result_command_surfaces_resume_task_id():
    """Verify resume_task_id is placed in additional_kwargs without corrupting error content (Comment 1)."""
    from deerflow.tools.builtins.task_tool import _task_result_command

    cmd = _task_result_command(
        tool_call_id="call-fail-1",
        status="failed",
        error="subagent crashed",
        resume_task_id="exec-fail-123",
    )
    msg = cmd.update["messages"][0]
    assert msg.content == "Task failed. Error: subagent crashed"
    assert msg.additional_kwargs.get("resume_task_id") == "exec-fail-123"
