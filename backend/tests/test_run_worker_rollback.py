import asyncio
import copy
from contextlib import suppress
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, call

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY
from deerflow.runtime.runs.manager import ConflictError, RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.worker import (
    RunContext,
    _agent_factory_supports_app_config,
    _build_runtime_context,
    _bump_channel_version,
    _collect_pre_existing_message_ids,
    _ensure_interrupted_title,
    _extract_llm_error_fallback_message,
    _install_runtime_context,
    _rollback_to_pre_run_checkpoint,
    _try_extract_from_message,
    run_agent,
)


class FakeCheckpointer:
    def __init__(self, *, put_result):
        self.adelete_thread = AsyncMock()
        self.aput = AsyncMock(return_value=put_result)
        self.aput_writes = AsyncMock()


def _make_checkpoint(checkpoint_id: str, messages: list[str], version: int):
    checkpoint = empty_checkpoint()
    checkpoint["id"] = checkpoint_id
    checkpoint["channel_values"] = {"messages": messages}
    checkpoint["channel_versions"] = {"messages": version}
    return checkpoint


def test_build_runtime_context_includes_app_config_when_present():
    app_config = object()

    context = _build_runtime_context("thread-1", "run-1", None, app_config)

    assert context["thread_id"] == "thread-1"
    assert context["run_id"] == "run-1"
    assert context["app_config"] is app_config


def test_install_runtime_context_preserves_existing_thread_id_and_threads_app_config():
    app_config = object()
    config = {"context": {"thread_id": "caller-thread"}}

    _install_runtime_context(
        config,
        {
            "thread_id": "record-thread",
            "run_id": "run-1",
            "app_config": app_config,
        },
    )

    assert config["context"]["thread_id"] == "caller-thread"
    assert config["context"]["run_id"] == "run-1"
    assert config["context"]["app_config"] is app_config


def test_install_runtime_context_overrides_internal_pre_existing_message_ids():
    config = {"context": {CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: {"spoofed"}}}

    _install_runtime_context(
        config,
        {
            "thread_id": "record-thread",
            "run_id": "run-1",
            CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset({"old-ai"}),
        },
    )

    assert config["context"][CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY] == frozenset({"old-ai"})


@pytest.mark.anyio
async def test_run_agent_threads_explicit_app_config_into_config_only_factory():
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    app_config = object()
    captured: dict[str, object] = {}

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            captured["astream_context"] = config["context"]
            yield {"messages": []}

    def factory(*, config):
        captured["factory_context"] = config["context"]
        return DummyAgent()

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, app_config=app_config),
        agent_factory=factory,
        graph_input={},
        config={},
    )
    await asyncio.sleep(0)

    assert captured["factory_context"]["app_config"] is app_config
    assert captured["astream_context"]["app_config"] is app_config
    fetched = await run_manager.get(record.run_id)
    assert fetched is not None
    assert fetched.status == RunStatus.success
    bridge.publish_end.assert_awaited_once_with(record.run_id)
    bridge.cleanup.assert_awaited_once_with(record.run_id, delay=60)


@pytest.mark.anyio
async def test_run_agent_threads_pre_existing_message_ids_into_runtime_context():
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    captured: dict[str, object] = {}

    class DummyCheckpointer:
        async def aget_tuple(self, _config):
            return SimpleNamespace(
                config={"configurable": {"checkpoint_id": "checkpoint-1"}},
                checkpoint={"channel_values": {"messages": [AIMessage(id="old-ai", content="old")]}},
                metadata={},
                pending_writes=[],
            )

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            captured["context"] = config["context"]
            yield {"messages": []}

    def factory(*, config):
        return DummyAgent()

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=DummyCheckpointer()),
        agent_factory=factory,
        graph_input={},
        config={},
    )

    context = captured["context"]
    assert context[CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY] == frozenset({"old-ai"})


@pytest.mark.anyio
async def test_run_agent_overrides_spoofed_pre_existing_message_ids_without_snapshot():
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    captured: dict[str, object] = {}

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            captured["context"] = config["context"]
            yield {"messages": []}

    def factory(*, config):
        return DummyAgent()

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=None),
        agent_factory=factory,
        graph_input={},
        config={"context": {CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: {"spoofed"}}},
    )

    context = captured["context"]
    assert context[CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY] == frozenset()


@pytest.mark.anyio
async def test_run_agent_marks_llm_error_fallback_as_error_status():
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            yield {
                "messages": [
                    AIMessage(
                        content="The configured LLM provider is temporarily unavailable after multiple retries.",
                        additional_kwargs={
                            "deerflow_error_fallback": True,
                            "error_type": "APIConnectionError",
                            "error_reason": "transient",
                            "error_detail": "Connection error.",
                        },
                    )
                ]
            }

    def factory(*, config):
        return DummyAgent()

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=None),
        agent_factory=factory,
        graph_input={},
        config={},
    )

    fetched = await run_manager.get(record.run_id)
    assert fetched is not None
    assert fetched.status == RunStatus.error
    assert fetched.error == "Connection error."
    bridge.publish_end.assert_awaited_once_with(record.run_id)


@pytest.mark.anyio
async def test_run_agent_defaults_root_run_name_from_assistant_id():
    run_manager = RunManager()
    record = await run_manager.create("thread-1", assistant_id="lead_agent")
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    captured: dict[str, object] = {}

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            captured["astream_run_name"] = config["run_name"]
            yield {"messages": []}

    def factory(*, config):
        captured["factory_run_name"] = config["run_name"]
        return DummyAgent()

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=None),
        agent_factory=factory,
        graph_input={},
        config={},
    )

    assert captured["factory_run_name"] == "lead_agent"
    assert captured["astream_run_name"] == "lead_agent"


@pytest.mark.anyio
async def test_run_agent_defaults_root_run_name_from_context_agent_name():
    run_manager = RunManager()
    record = await run_manager.create("thread-1", assistant_id="lead_agent")
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    captured: dict[str, object] = {}

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            captured["astream_run_name"] = config["run_name"]
            yield {"messages": []}

    def factory(*, config):
        captured["factory_run_name"] = config["run_name"]
        return DummyAgent()

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=None),
        agent_factory=factory,
        graph_input={},
        config={"context": {"agent_name": "finalis"}},
    )

    assert captured["factory_run_name"] == "finalis"
    assert captured["astream_run_name"] == "finalis"


@pytest.mark.anyio
async def test_run_agent_defaults_root_run_name_from_configurable_agent_name():
    run_manager = RunManager()
    record = await run_manager.create("thread-1", assistant_id="lead_agent")
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    captured: dict[str, object] = {}

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            captured["astream_run_name"] = config["run_name"]
            yield {"messages": []}

    def factory(*, config):
        captured["factory_run_name"] = config["run_name"]
        return DummyAgent()

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=None),
        agent_factory=factory,
        graph_input={},
        config={"configurable": {"agent_name": "finalis"}},
    )

    assert captured["factory_run_name"] == "finalis"
    assert captured["astream_run_name"] == "finalis"


@pytest.mark.anyio
async def test_rollback_restores_snapshot_without_deleting_thread():
    checkpointer = FakeCheckpointer(put_result={"configurable": {"thread_id": "thread-1", "checkpoint_ns": "", "checkpoint_id": "restored-1"}})

    await _rollback_to_pre_run_checkpoint(
        checkpointer=checkpointer,
        thread_id="thread-1",
        run_id="run-1",
        pre_run_checkpoint_id="ckpt-1",
        pre_run_snapshot={
            "checkpoint_ns": "",
            "checkpoint": {
                "id": "ckpt-1",
                "channel_versions": {"messages": 3},
                "channel_values": {"messages": ["before"]},
            },
            "metadata": {"source": "input"},
            "pending_writes": [
                ("task-a", "messages", {"content": "first"}),
                ("task-a", "status", "done"),
                ("task-b", "events", {"type": "tool"}),
            ],
        },
        snapshot_capture_failed=False,
    )

    checkpointer.adelete_thread.assert_not_awaited()
    checkpointer.aput.assert_awaited_once()
    restore_config, restored_checkpoint, restored_metadata, new_versions = checkpointer.aput.await_args.args
    assert restore_config == {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}
    assert restored_checkpoint["id"] != "ckpt-1"
    assert "channel_versions" in restored_checkpoint
    assert "channel_values" in restored_checkpoint
    assert restored_checkpoint["channel_versions"] == {"messages": 3}
    assert restored_checkpoint["channel_values"] == {"messages": ["before"]}
    assert restored_metadata == {"source": "input"}
    assert new_versions == {"messages": 3}
    assert checkpointer.aput_writes.await_args_list == [
        call(
            {"configurable": {"thread_id": "thread-1", "checkpoint_ns": "", "checkpoint_id": "restored-1"}},
            [("messages", {"content": "first"}), ("status", "done")],
            task_id="task-a",
        ),
        call(
            {"configurable": {"thread_id": "thread-1", "checkpoint_ns": "", "checkpoint_id": "restored-1"}},
            [("events", {"type": "tool"})],
            task_id="task-b",
        ),
    ]


@pytest.mark.anyio
async def test_rollback_restored_checkpoint_becomes_latest_with_real_checkpointer():
    checkpointer = InMemorySaver()
    thread_config = {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}
    before_checkpoint = _make_checkpoint("0001", ["before"], 1)
    before_config = checkpointer.put(thread_config, before_checkpoint, {"step": 1}, {"messages": 1})
    after_checkpoint = _make_checkpoint("0002", ["after"], 2)
    after_config = checkpointer.put(before_config, after_checkpoint, {"step": 2}, {"messages": 2})
    checkpointer.put_writes(after_config, [("messages", "pending-after")], task_id="task-after")

    await _rollback_to_pre_run_checkpoint(
        checkpointer=checkpointer,
        thread_id="thread-1",
        run_id="run-1",
        pre_run_checkpoint_id="0001",
        pre_run_snapshot={
            "checkpoint_ns": "",
            "checkpoint": before_checkpoint,
            "metadata": {"step": 1},
            "pending_writes": [("task-before", "messages", "pending-before")],
        },
        snapshot_capture_failed=False,
    )

    latest = checkpointer.get_tuple(thread_config)

    assert latest is not None
    assert latest.config["configurable"]["checkpoint_id"] != "0001"
    assert latest.config["configurable"]["checkpoint_id"] != "0002"
    assert latest.checkpoint["channel_values"] == {"messages": ["before"]}
    assert latest.pending_writes == [("task-before", "messages", "pending-before")]
    assert ("task-after", "messages", "pending-after") not in latest.pending_writes


@pytest.mark.anyio
async def test_rollback_deletes_thread_when_no_snapshot_exists():
    checkpointer = FakeCheckpointer(put_result=None)

    await _rollback_to_pre_run_checkpoint(
        checkpointer=checkpointer,
        thread_id="thread-1",
        run_id="run-1",
        pre_run_checkpoint_id=None,
        pre_run_snapshot=None,
        snapshot_capture_failed=False,
    )

    checkpointer.adelete_thread.assert_awaited_once_with("thread-1")
    checkpointer.aput.assert_not_awaited()
    checkpointer.aput_writes.assert_not_awaited()


@pytest.mark.anyio
async def test_rollback_raises_when_restore_config_has_no_checkpoint_id():
    checkpointer = FakeCheckpointer(put_result={"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}})

    with pytest.raises(RuntimeError, match="did not return checkpoint_id"):
        await _rollback_to_pre_run_checkpoint(
            checkpointer=checkpointer,
            thread_id="thread-1",
            run_id="run-1",
            pre_run_checkpoint_id="ckpt-1",
            pre_run_snapshot={
                "checkpoint_ns": "",
                "checkpoint": {"id": "ckpt-1", "channel_versions": {}},
                "metadata": {},
                "pending_writes": [("task-a", "messages", "value")],
            },
            snapshot_capture_failed=False,
        )

    checkpointer.adelete_thread.assert_not_awaited()
    checkpointer.aput.assert_awaited_once()
    checkpointer.aput_writes.assert_not_awaited()


@pytest.mark.anyio
async def test_rollback_normalizes_none_checkpoint_ns_to_root_namespace():
    checkpointer = FakeCheckpointer(put_result={"configurable": {"thread_id": "thread-1", "checkpoint_ns": "", "checkpoint_id": "restored-1"}})

    await _rollback_to_pre_run_checkpoint(
        checkpointer=checkpointer,
        thread_id="thread-1",
        run_id="run-1",
        pre_run_checkpoint_id="ckpt-1",
        pre_run_snapshot={
            "checkpoint_ns": None,
            "checkpoint": {"id": "ckpt-1", "channel_versions": {}},
            "metadata": {},
            "pending_writes": [],
        },
        snapshot_capture_failed=False,
    )

    checkpointer.aput.assert_awaited_once()
    restore_config, restored_checkpoint, restored_metadata, new_versions = checkpointer.aput.await_args.args
    assert restore_config == {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}
    assert restored_checkpoint["id"] != "ckpt-1"
    assert restored_checkpoint["channel_versions"] == {}
    assert restored_metadata == {}
    assert new_versions == {}


@pytest.mark.anyio
async def test_rollback_raises_on_malformed_pending_write_not_a_tuple():
    """pending_writes containing a non-3-tuple item should raise RuntimeError."""
    checkpointer = FakeCheckpointer(put_result={"configurable": {"thread_id": "thread-1", "checkpoint_ns": "", "checkpoint_id": "restored-1"}})

    with pytest.raises(RuntimeError, match="rollback failed: pending_write is not a 3-tuple"):
        await _rollback_to_pre_run_checkpoint(
            checkpointer=checkpointer,
            thread_id="thread-1",
            run_id="run-1",
            pre_run_checkpoint_id="ckpt-1",
            pre_run_snapshot={
                "checkpoint_ns": "",
                "checkpoint": {"id": "ckpt-1", "channel_versions": {}},
                "metadata": {},
                "pending_writes": [
                    ("task-a", "messages", "valid"),  # valid
                    ["only", "two"],  # malformed: only 2 elements
                ],
            },
            snapshot_capture_failed=False,
        )

    # aput succeeded but aput_writes should not be called due to malformed data
    checkpointer.aput.assert_awaited_once()
    checkpointer.aput_writes.assert_not_awaited()


@pytest.mark.anyio
async def test_rollback_raises_on_malformed_pending_write_non_string_channel():
    """pending_writes containing a non-string channel should raise RuntimeError."""
    checkpointer = FakeCheckpointer(put_result={"configurable": {"thread_id": "thread-1", "checkpoint_ns": "", "checkpoint_id": "restored-1"}})

    with pytest.raises(RuntimeError, match="rollback failed: pending_write has non-string channel"):
        await _rollback_to_pre_run_checkpoint(
            checkpointer=checkpointer,
            thread_id="thread-1",
            run_id="run-1",
            pre_run_checkpoint_id="ckpt-1",
            pre_run_snapshot={
                "checkpoint_ns": "",
                "checkpoint": {"id": "ckpt-1", "channel_versions": {}},
                "metadata": {},
                "pending_writes": [
                    ("task-a", 123, "value"),  # malformed: channel is not a string
                ],
            },
            snapshot_capture_failed=False,
        )

    checkpointer.aput.assert_awaited_once()
    checkpointer.aput_writes.assert_not_awaited()


@pytest.mark.anyio
async def test_rollback_propagates_aput_writes_failure():
    """If aput_writes fails, the exception should propagate (not be swallowed)."""
    checkpointer = FakeCheckpointer(put_result={"configurable": {"thread_id": "thread-1", "checkpoint_ns": "", "checkpoint_id": "restored-1"}})
    # Simulate aput_writes failure
    checkpointer.aput_writes.side_effect = RuntimeError("Database connection lost")

    with pytest.raises(RuntimeError, match="Database connection lost"):
        await _rollback_to_pre_run_checkpoint(
            checkpointer=checkpointer,
            thread_id="thread-1",
            run_id="run-1",
            pre_run_checkpoint_id="ckpt-1",
            pre_run_snapshot={
                "checkpoint_ns": "",
                "checkpoint": {"id": "ckpt-1", "channel_versions": {}},
                "metadata": {},
                "pending_writes": [
                    ("task-a", "messages", "value"),
                ],
            },
            snapshot_capture_failed=False,
        )

    # aput succeeded, aput_writes was called but failed
    checkpointer.aput.assert_awaited_once()
    checkpointer.aput_writes.assert_awaited_once()


def test_agent_factory_supports_app_config_detects_supported_signature():
    def factory(*, config, app_config=None):
        return (config, app_config)

    assert _agent_factory_supports_app_config(factory) is True


def test_build_runtime_context_defaults_to_thread_and_run_id():
    ctx = _build_runtime_context("thread-1", "run-1", None)
    assert ctx == {"thread_id": "thread-1", "run_id": "run-1"}


def test_build_runtime_context_merges_caller_context():
    """Regression for issue #2677: keys from ``config['context']`` (e.g. ``agent_name``)
    must be merged into the Runtime's context so that ``ToolRuntime.context`` — which
    is what ``setup_agent`` reads — can see them."""
    caller_context = {"agent_name": "my-agent", "is_bootstrap": True, "model_name": "gpt-4"}

    ctx = _build_runtime_context("thread-1", "run-1", caller_context)

    assert ctx["thread_id"] == "thread-1"
    assert ctx["run_id"] == "run-1"
    assert ctx["agent_name"] == "my-agent"
    assert ctx["is_bootstrap"] is True
    assert ctx["model_name"] == "gpt-4"


def test_build_runtime_context_caller_cannot_override_thread_id_or_run_id():
    """A malicious or buggy caller must not be able to overwrite the worker-assigned
    ``thread_id`` / ``run_id`` by stuffing them into ``config['context']``."""
    caller_context = {"thread_id": "spoofed", "run_id": "spoofed", "agent_name": "ok"}

    ctx = _build_runtime_context("real-thread", "real-run", caller_context)

    assert ctx["thread_id"] == "real-thread"
    assert ctx["run_id"] == "real-run"
    assert ctx["agent_name"] == "ok"


def test_build_runtime_context_ignores_caller_pre_existing_message_ids():
    caller_context = {CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: {"spoofed"}}

    ctx = _build_runtime_context("thread-1", "run-1", caller_context)

    assert CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY not in ctx


def test_build_runtime_context_ignores_non_dict_caller_context():
    ctx = _build_runtime_context("thread-1", "run-1", "not-a-dict")
    assert ctx == {"thread_id": "thread-1", "run_id": "run-1"}


def test_agent_factory_supports_app_config_returns_false_when_signature_lookup_fails(monkeypatch):
    class BrokenCallable:
        def __call__(self, **kwargs):
            return kwargs

    monkeypatch.setattr("deerflow.runtime.runs.worker.inspect.signature", lambda _obj: (_ for _ in ()).throw(ValueError("boom")))

    assert _agent_factory_supports_app_config(BrokenCallable()) is False


# ---------------------------------------------------------------------------
# _extract_llm_error_fallback_message coverage
# ---------------------------------------------------------------------------


def test_try_extract_from_message_finds_fallback_on_message_object():
    msg = AIMessage(
        content="fallback",
        additional_kwargs={
            "deerflow_error_fallback": True,
            "error_detail": "Connection error.",
            "error_reason": "transient",
        },
    )
    assert _try_extract_from_message(msg) == "Connection error."


def test_try_extract_from_message_finds_fallback_on_dict():
    msg = {
        "content": "fallback",
        "additional_kwargs": {
            "deerflow_error_fallback": True,
            "error_detail": "Quota exceeded.",
        },
    }
    assert _try_extract_from_message(msg) == "Quota exceeded."


def test_try_extract_from_message_returns_none_for_normal_message():
    msg = AIMessage(content="hello")
    assert _try_extract_from_message(msg) is None


def test_extract_llm_error_fallback_message_large_state_chunk_no_fallback():
    """Normal-size state dict without fallback markers must not raise and should return None."""
    large_state = {
        "messages": [
            AIMessage(content="Hello!"),
            {"role": "user", "content": "Hi there"},
        ],
        "foo": "x" * 10_000,
        "bar": {"nested": {"deep": {"data": list(range(1000))}}},
        "baz": [{"id": i, "payload": "y" * 1000} for i in range(500)],
    }
    assert _extract_llm_error_fallback_message(large_state) is None


def test_extract_llm_error_fallback_message_finds_fallback_in_messages_list():
    state = {
        "messages": [
            AIMessage(content="Hello!"),
            AIMessage(
                content="Unavailable.",
                additional_kwargs={
                    "deerflow_error_fallback": True,
                    "error_detail": "Connection error.",
                },
            ),
        ],
        "other_state": "large_value" * 1000,
    }
    assert _extract_llm_error_fallback_message(state) == "Connection error."


def test_extract_llm_error_fallback_message_finds_fallback_in_raw_message():
    msg = AIMessage(
        content="Unavailable.",
        additional_kwargs={
            "deerflow_error_fallback": True,
            "error_reason": "quota",
        },
    )
    assert _extract_llm_error_fallback_message(msg) == "quota"


def test_extract_llm_error_fallback_message_finds_fallback_in_tuple():
    item = (
        "messages",
        AIMessage(
            content="Unavailable.",
            additional_kwargs={
                "deerflow_error_fallback": True,
                "error_detail": "Circuit open.",
            },
        ),
    )
    assert _extract_llm_error_fallback_message(item) == "Circuit open."


def test_extract_llm_error_fallback_message_returns_none_for_empty_values():
    assert _extract_llm_error_fallback_message({}) is None
    assert _extract_llm_error_fallback_message([]) is None
    assert _extract_llm_error_fallback_message(None) is None
    assert _extract_llm_error_fallback_message("string") is None


def test_extract_llm_error_fallback_message_finds_fallback_in_updates_mode():
    """stream_mode='updates' yields dicts keyed by node name (e.g. {'call_model': {...}}).
    Fallback marker is nested inside the node's state update, not at the top level."""
    update_chunk = {
        "call_model": {
            "messages": [
                AIMessage(
                    content="Unavailable.",
                    additional_kwargs={
                        "deerflow_error_fallback": True,
                        "error_detail": "Connection error.",
                    },
                )
            ]
        }
    }
    assert _extract_llm_error_fallback_message(update_chunk) == "Connection error."


def test_extract_llm_error_fallback_message_updates_mode_no_fallback():
    """Normal updates chunk without any fallback should return None safely."""
    update_chunk = {
        "__interrupt__": [
            {
                "value": "ask_human",
                "resumable": True,
                "ns": ["agent"],
                "when": "during",
            }
        ]
    }
    assert _extract_llm_error_fallback_message(update_chunk) is None


# ---------------------------------------------------------------------------
# pre_existing_ids filtering — stale fallback markers from prior runs
# ---------------------------------------------------------------------------


def test_try_extract_skips_message_with_pre_existing_id():
    """Fallback marker on a message whose id is in pre_existing_ids must be ignored."""
    msg = AIMessage(
        id="stale-1",
        content="Unavailable.",
        additional_kwargs={
            "deerflow_error_fallback": True,
            "error_detail": "Connection error.",
        },
    )
    assert _try_extract_from_message(msg, {"stale-1"}) is None
    # Without the filter, the same message would still surface the marker.
    assert _try_extract_from_message(msg) == "Connection error."


def test_try_extract_still_finds_fresh_message_when_others_are_stale():
    """A non-stale message with a fallback marker must still match."""
    msg = AIMessage(
        id="fresh-1",
        content="Unavailable.",
        additional_kwargs={
            "deerflow_error_fallback": True,
            "error_detail": "Connection error.",
        },
    )
    assert _try_extract_from_message(msg, {"stale-1", "stale-2"}) == "Connection error."


def test_try_extract_skips_dict_message_with_pre_existing_id():
    msg = {
        "id": "stale-2",
        "content": "Unavailable.",
        "additional_kwargs": {
            "deerflow_error_fallback": True,
            "error_detail": "Quota exceeded.",
        },
    }
    assert _try_extract_from_message(msg, {"stale-2"}) is None
    assert _try_extract_from_message(msg) == "Quota exceeded."


def test_extract_llm_error_fallback_message_skips_stale_history():
    """A state chunk replaying a stale fallback marker from a prior run must return None."""
    state = {
        "messages": [
            AIMessage(id="stale-1", content="Hi"),
            AIMessage(
                id="stale-fallback",
                content="Unavailable.",
                additional_kwargs={
                    "deerflow_error_fallback": True,
                    "error_detail": "Connection error.",
                },
            ),
        ]
    }
    assert _extract_llm_error_fallback_message(state, {"stale-1", "stale-fallback"}) is None


def test_extract_llm_error_fallback_message_returns_fresh_marker_alongside_stale_history():
    """Stale history is ignored, but a brand-new fallback in the same chunk is reported."""
    state = {
        "messages": [
            AIMessage(id="stale-1", content="Hi"),
            AIMessage(
                id="stale-fallback",
                content="Old failure.",
                additional_kwargs={
                    "deerflow_error_fallback": True,
                    "error_detail": "Old error.",
                },
            ),
            AIMessage(
                id="fresh-fallback",
                content="New failure.",
                additional_kwargs={
                    "deerflow_error_fallback": True,
                    "error_detail": "Fresh error.",
                },
            ),
        ]
    }
    assert _extract_llm_error_fallback_message(state, {"stale-1", "stale-fallback"}) == "Fresh error."


def test_extract_llm_error_fallback_message_default_filter_is_empty():
    """Passing no pre_existing_ids must preserve the original (pre-fix) behavior."""
    state = {
        "messages": [
            AIMessage(
                id="any",
                content="Unavailable.",
                additional_kwargs={
                    "deerflow_error_fallback": True,
                    "error_detail": "Connection error.",
                },
            )
        ]
    }
    assert _extract_llm_error_fallback_message(state) == "Connection error."


def test_collect_pre_existing_message_ids_pulls_ids_from_snapshot():
    snapshot = {
        "checkpoint": {
            "channel_values": {
                "messages": [
                    AIMessage(id="a", content="x"),
                    AIMessage(id="b", content="y"),
                    AIMessage(content="no-id-here"),  # ignored
                ]
            }
        }
    }
    assert _collect_pre_existing_message_ids(snapshot) == {"a", "b"}


def test_collect_pre_existing_message_ids_handles_missing_pieces():
    assert _collect_pre_existing_message_ids(None) == set()
    assert _collect_pre_existing_message_ids({}) == set()
    assert _collect_pre_existing_message_ids({"checkpoint": None}) == set()
    assert _collect_pre_existing_message_ids({"checkpoint": {}}) == set()
    assert _collect_pre_existing_message_ids({"checkpoint": {"channel_values": None}}) == set()
    assert _collect_pre_existing_message_ids({"checkpoint": {"channel_values": {"messages": None}}}) == set()


@pytest.mark.anyio
async def test_run_agent_ignores_stale_llm_error_fallback_from_prior_run():
    """A stale fallback marker checkpointed by an earlier run on the same thread
    must NOT cause a successful current run to be reported as ``error``.

    This guards against the regression where one IndexError-driven failure (now
    classified transient and surfaced as a ``deerflow_error_fallback`` AIMessage)
    persisted in thread history and tripped ``RunStatus.error`` on every
    subsequent run that re-played the messages channel via ``stream_mode="values"``.
    """
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )

    stale_fallback = AIMessage(
        id="stale-fallback",
        content="Old failure.",
        additional_kwargs={
            "deerflow_error_fallback": True,
            "error_type": "IndexError",
            "error_reason": "transient",
            "error_detail": "list index out of range",
        },
    )

    class StaleHistoryCheckpointer:
        async def aget_tuple(self, config):
            checkpoint = empty_checkpoint()
            checkpoint["id"] = "ckpt-stale"
            checkpoint["channel_values"] = {"messages": [stale_fallback]}
            return SimpleNamespace(
                config={"configurable": {"thread_id": "thread-1", "checkpoint_ns": "", "checkpoint_id": "ckpt-stale"}},
                checkpoint=checkpoint,
                metadata={},
                pending_writes=[],
            )

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            # Replay the prior fallback message (as LangGraph would when using
            # stream_mode="values") and then yield a fresh successful AIMessage.
            yield {
                "messages": [
                    stale_fallback,
                    AIMessage(id="fresh-ok", content="Hello — the run succeeded."),
                ]
            }

    def factory(*, config):
        return DummyAgent()

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=StaleHistoryCheckpointer()),
        agent_factory=factory,
        graph_input={},
        config={},
    )

    fetched = await run_manager.get(record.run_id)
    assert fetched is not None
    assert fetched.status == RunStatus.success, f"Stale fallback marker from prior run should not flip current run to error, got status={fetched.status} error={fetched.error!r}"
    bridge.publish_end.assert_awaited_once_with(record.run_id)


class _FakeCheckpointTuple:
    """Minimal stand-in for ``CheckpointTuple`` used by ``_ensure_interrupted_title``."""

    def __init__(self, *, checkpoint: dict, metadata: dict, config: dict | None = None):
        self.checkpoint = checkpoint
        self.metadata = metadata
        self.config = config or {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}


class _TitleCheckpointer:
    """Captures ``aput`` arguments and exposes ``get_next_version`` like DB savers."""

    def __init__(self, *, tuple_value: _FakeCheckpointTuple | None, put_result: dict | None = None):
        self.aget_tuple = AsyncMock(return_value=tuple_value)
        self.aput = AsyncMock(return_value=put_result or {})

    def get_next_version(self, current, _channel):
        if current is None:
            return 1
        if isinstance(current, int):
            return current + 1
        if isinstance(current, str):
            try:
                return str(int(current) + 1)
            except ValueError:
                return f"{current}.1"
        return 1


@pytest.mark.anyio
async def test_interrupted_title_finalization_blocks_new_same_thread_run(monkeypatch):
    """A cancelled run must remain active while its title-only checkpoint is finalizing."""
    from deerflow.agents.middlewares.title_middleware import TitleMiddleware

    monkeypatch.setattr(
        TitleMiddleware,
        "_generate_title_result",
        lambda self, state, allow_partial_exchange=False: {"title": "Old Prompt"},
    )

    initial_checkpoint = {
        "id": "ckpt-old",
        "ts": "2026-06-29T00:00:00Z",
        "channel_values": {"messages": [{"type": "human", "content": "old prompt"}]},
        "channel_versions": {"messages": 1},
    }

    class _BlockingTitleCheckpointer:
        def __init__(self) -> None:
            self.latest_checkpoint = copy.deepcopy(initial_checkpoint)
            self.latest_metadata = {"source": "loop", "step": 1}
            self.title_write_started = asyncio.Event()
            self.release_title_write = asyncio.Event()

        async def aget_tuple(self, config):
            del config
            return _FakeCheckpointTuple(
                checkpoint=copy.deepcopy(self.latest_checkpoint),
                metadata=dict(self.latest_metadata),
                config={
                    "configurable": {
                        "thread_id": "thread-1",
                        "checkpoint_ns": "",
                        "checkpoint_id": self.latest_checkpoint["id"],
                    }
                },
            )

        async def aput(self, config, checkpoint, metadata, new_versions):
            del config, new_versions
            self.title_write_started.set()
            await self.release_title_write.wait()
            self.latest_checkpoint = copy.deepcopy(checkpoint)
            self.latest_metadata = dict(metadata)
            return {
                "configurable": {
                    "thread_id": "thread-1",
                    "checkpoint_ns": "",
                    "checkpoint_id": checkpoint["id"],
                }
            }

        def get_next_version(self, current, _channel):
            return (current or 0) + 1

    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    checkpointer = _BlockingTitleCheckpointer()

    class _AbortingAgent:
        metadata = {"model_name": "fake-test-model"}
        checkpointer: Any | None = None
        store: Any | None = None
        interrupt_before_nodes = None
        interrupt_after_nodes = None

        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            del graph_input, config, stream_mode, subgraphs
            record.abort_event.set()
            if False:
                yield  # pragma: no cover

    def factory(*, config):
        del config
        return _AbortingAgent()

    task = asyncio.create_task(
        run_agent(
            bridge,
            run_manager,
            record,
            ctx=RunContext(checkpointer=checkpointer),
            agent_factory=factory,
            graph_input={"messages": [{"role": "user", "content": "old prompt"}]},
            config={},
        )
    )
    record.task = task

    try:
        await asyncio.wait_for(checkpointer.title_write_started.wait(), timeout=1.0)
        with pytest.raises(ConflictError, match="active run"):
            await run_manager.create_or_reject("thread-1", multitask_strategy="reject")
    finally:
        checkpointer.release_title_write.set()
        await task

    records = await run_manager.list_by_thread("thread-1")
    assert [item.run_id for item in records] == [record.run_id]
    assert checkpointer.latest_checkpoint["channel_values"]["messages"] == [{"type": "human", "content": "old prompt"}]


@pytest.mark.anyio
async def test_finalizing_run_only_blocks_reject_strategy():
    """A finalizing run must not break interrupt/rollback superseding semantics."""

    async def _seed_finalizing_run():
        run_manager = RunManager()
        record = await run_manager.create("thread-1")
        release_cleanup = asyncio.Event()
        cleanup_cancelled = asyncio.Event()

        async def _cleanup_task():
            try:
                await release_cleanup.wait()
            except asyncio.CancelledError:
                cleanup_cancelled.set()
                raise

        task = asyncio.create_task(_cleanup_task())
        record.task = task
        await run_manager.set_status(record.run_id, RunStatus.interrupted)
        await run_manager.set_finalizing(record.run_id, True)
        return run_manager, record, task, release_cleanup, cleanup_cancelled

    for strategy in ("interrupt", "rollback"):
        run_manager, record, task, release_cleanup, cleanup_cancelled = await _seed_finalizing_run()
        try:
            replacement = await run_manager.create_or_reject("thread-1", multitask_strategy=strategy)
            await asyncio.sleep(0)

            assert replacement.run_id != record.run_id
            assert record.status == RunStatus.interrupted
            assert record.finalizing is True
            assert not cleanup_cancelled.is_set()
            assert not task.done()
        finally:
            release_cleanup.set()
            with suppress(asyncio.CancelledError):
                await task

    run_manager, _record, task, release_cleanup, _cleanup_cancelled = await _seed_finalizing_run()
    try:
        with pytest.raises(ConflictError, match="active run"):
            await run_manager.create_or_reject("thread-1", multitask_strategy="reject")
    finally:
        release_cleanup.set()
        with suppress(asyncio.CancelledError):
            await task


@pytest.mark.anyio
async def test_admitted_pending_replacement_does_not_steal_interrupted_title_recovery(monkeypatch):
    """The old run must still write the fallback title before releasing a serialized replacement."""
    from deerflow.agents.middlewares.title_middleware import TitleMiddleware

    monkeypatch.setattr(
        TitleMiddleware,
        "_generate_title_result",
        lambda self, state, allow_partial_exchange=False: {"title": "Old Prompt"},
    )

    initial_checkpoint = {
        "id": "ckpt-old",
        "ts": "2026-06-29T00:00:00Z",
        "channel_values": {"messages": [{"type": "human", "content": "Old prompt"}]},
        "channel_versions": {"messages": 1},
    }

    run_manager = RunManager()
    old_record = await run_manager.create("thread-1")
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    checkpointer = _TitleCheckpointer(
        tuple_value=_FakeCheckpointTuple(
            checkpoint=initial_checkpoint,
            metadata={"source": "loop", "step": 1},
            config={
                "configurable": {
                    "thread_id": "thread-1",
                    "checkpoint_ns": "",
                    "checkpoint_id": "ckpt-old",
                }
            },
        ),
    )

    old_title_gate_entered = asyncio.Event()
    release_old_title_gate = asyncio.Event()
    original_wait_for_prior_finalizing = run_manager.wait_for_prior_finalizing

    async def _wait_for_prior_finalizing(thread_id, run_id, **kwargs):
        if run_id == old_record.run_id and old_record.status == RunStatus.interrupted and old_record.finalizing:
            old_title_gate_entered.set()
            await release_old_title_gate.wait()
        return await original_wait_for_prior_finalizing(thread_id, run_id, **kwargs)

    run_manager.wait_for_prior_finalizing = _wait_for_prior_finalizing  # type: ignore[method-assign]

    class _AbortingAgent:
        metadata = {"model_name": "fake-test-model"}
        checkpointer: Any | None = None
        store: Any | None = None
        interrupt_before_nodes = None
        interrupt_after_nodes = None

        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            del graph_input, config, stream_mode, subgraphs
            old_record.abort_event.set()
            if False:
                yield  # pragma: no cover

    def factory(*, config):
        del config
        return _AbortingAgent()

    old_task = asyncio.create_task(
        run_agent(
            bridge,
            run_manager,
            old_record,
            ctx=RunContext(checkpointer=checkpointer),
            agent_factory=factory,
            graph_input={"messages": [{"role": "user", "content": "Old prompt"}]},
            config={},
        )
    )
    old_record.task = old_task

    try:
        await asyncio.wait_for(old_title_gate_entered.wait(), timeout=1.0)
        replacement_record = await run_manager.create_or_reject("thread-1", multitask_strategy="interrupt")
        assert replacement_record.status == RunStatus.pending

        release_old_title_gate.set()
        await old_task
    finally:
        release_old_title_gate.set()
        if not old_task.done():
            old_task.cancel()
            with suppress(asyncio.CancelledError):
                await old_task

    checkpointer.aput.assert_awaited_once()
    _, written_checkpoint, _, _ = checkpointer.aput.await_args.args
    assert written_checkpoint["channel_values"]["title"] == "Old Prompt"


@pytest.mark.anyio
async def test_interrupted_title_does_not_overwrite_checkpoint_from_admitted_replacement(monkeypatch):
    """A replacement run admitted by multitask interrupt must not lose its newer checkpoint."""
    from deerflow.agents.middlewares.title_middleware import TitleMiddleware

    monkeypatch.setattr(
        TitleMiddleware,
        "_generate_title_result",
        lambda self, state, allow_partial_exchange=False: {"title": "Old prompt"},
    )

    old_checkpoint = {
        "id": "ckpt-old",
        "ts": "2026-06-29T00:00:00Z",
        "channel_values": {"messages": [{"type": "human", "content": "Old prompt"}]},
        "channel_versions": {"messages": 1},
    }
    replacement_messages = [
        {"type": "human", "content": "Old prompt"},
        {"type": "human", "content": "Replacement prompt"},
    ]
    replacement_checkpoint = {
        "id": "ckpt-replacement",
        "ts": "2026-06-29T00:00:01Z",
        "channel_values": {"messages": replacement_messages},
        "channel_versions": {"messages": 2},
    }

    class _ReplacementRaceCheckpointer:
        def __init__(self) -> None:
            self.latest_checkpoint = copy.deepcopy(old_checkpoint)
            self.latest_metadata = {"source": "loop", "step": 1}
            self.title_write_started = asyncio.Event()
            self.replacement_checkpoint_written = asyncio.Event()

        async def aget_tuple(self, config):
            del config
            return _FakeCheckpointTuple(
                checkpoint=copy.deepcopy(self.latest_checkpoint),
                metadata=dict(self.latest_metadata),
                config={
                    "configurable": {
                        "thread_id": "thread-1",
                        "checkpoint_ns": "",
                        "checkpoint_id": self.latest_checkpoint["id"],
                    }
                },
            )

        async def aput(self, config, checkpoint, metadata, new_versions):
            del config, new_versions
            self.title_write_started.set()
            await self.replacement_checkpoint_written.wait()
            self.latest_checkpoint = copy.deepcopy(checkpoint)
            self.latest_metadata = dict(metadata)
            return {
                "configurable": {
                    "thread_id": "thread-1",
                    "checkpoint_ns": "",
                    "checkpoint_id": checkpoint["id"],
                }
            }

        def get_next_version(self, current, _channel):
            return (current or 0) + 1

    run_manager = RunManager()
    old_record = await run_manager.create("thread-1")
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    checkpointer = _ReplacementRaceCheckpointer()
    old_agent_started = asyncio.Event()

    class _BlockingAgent:
        metadata = {"model_name": "fake-test-model"}
        checkpointer: Any | None = None
        store: Any | None = None
        interrupt_before_nodes = None
        interrupt_after_nodes = None

        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            del graph_input, config, stream_mode, subgraphs
            old_agent_started.set()
            while True:
                await asyncio.sleep(0.05)
            if False:
                yield  # pragma: no cover

    def factory(*, config):
        del config
        return _BlockingAgent()

    old_task = asyncio.create_task(
        run_agent(
            bridge,
            run_manager,
            old_record,
            ctx=RunContext(checkpointer=checkpointer),
            agent_factory=factory,
            graph_input={"messages": [{"role": "user", "content": "Old prompt"}]},
            config={},
        )
    )
    old_record.task = old_task

    try:
        await asyncio.wait_for(old_agent_started.wait(), timeout=1.0)
        replacement_record = await run_manager.create_or_reject("thread-1", multitask_strategy="interrupt")
        assert replacement_record.run_id != old_record.run_id
        await run_manager.set_status(replacement_record.run_id, RunStatus.running)

        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(checkpointer.title_write_started.wait(), timeout=0.25)

        checkpointer.latest_checkpoint = copy.deepcopy(replacement_checkpoint)
        checkpointer.latest_metadata = {"source": "loop", "step": 2}
        checkpointer.replacement_checkpoint_written.set()
        await old_task
    finally:
        checkpointer.replacement_checkpoint_written.set()
        if not old_task.done():
            old_task.cancel()
            with suppress(asyncio.CancelledError):
                await old_task

    assert checkpointer.latest_checkpoint["channel_values"]["messages"] == replacement_messages


@pytest.mark.anyio
async def test_replacement_run_waits_for_prior_finalizing_run():
    """Replacement workers must not enter the graph while an older run is finalizing."""
    run_manager = RunManager()
    old_record = await run_manager.create("thread-1")
    replacement_record = await run_manager.create("thread-1")
    await run_manager.set_finalizing(old_record.run_id, True)

    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    replacement_started = asyncio.Event()

    class _ReplacementAgent:
        metadata = {"model_name": "fake-test-model"}
        checkpointer: Any | None = None
        store: Any | None = None
        interrupt_before_nodes = None
        interrupt_after_nodes = None

        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            del graph_input, config, stream_mode, subgraphs
            replacement_started.set()
            if False:
                yield  # pragma: no cover

    def factory(*, config):
        del config
        return _ReplacementAgent()

    task = asyncio.create_task(
        run_agent(
            bridge,
            run_manager,
            replacement_record,
            ctx=RunContext(checkpointer=None),
            agent_factory=factory,
            graph_input={"messages": [{"role": "user", "content": "Replacement prompt"}]},
            config={},
        )
    )
    replacement_record.task = task

    try:
        await asyncio.sleep(0.1)
        assert not replacement_started.is_set()

        await run_manager.set_finalizing(old_record.run_id, False)
        await asyncio.wait_for(replacement_started.wait(), timeout=1.0)
        await task
    finally:
        await run_manager.set_finalizing(old_record.run_id, False)
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


@pytest.mark.anyio
async def test_ensure_interrupted_title_reloads_latest_checkpoint_before_write():
    """If the checkpoint advances before the title write, preserve the newer messages."""
    from deerflow.config.title_config import TitleConfig

    old_checkpoint = {
        "id": "ckpt-old",
        "ts": "2026-06-29T00:00:00Z",
        "channel_values": {"messages": [{"type": "human", "content": "Old prompt"}]},
        "channel_versions": {"messages": 1},
    }
    new_messages = [{"type": "human", "content": "New prompt"}]
    new_checkpoint = {
        "id": "ckpt-new",
        "ts": "2026-06-29T00:00:01Z",
        "channel_values": {"messages": new_messages},
        "channel_versions": {"messages": 2},
    }

    class _AdvancingTitleCheckpointer:
        def __init__(self) -> None:
            self.read_count = 0
            self.aput = AsyncMock(return_value={})

        async def aget_tuple(self, config):
            del config
            self.read_count += 1
            checkpoint = old_checkpoint if self.read_count == 1 else new_checkpoint
            return _FakeCheckpointTuple(
                checkpoint=copy.deepcopy(checkpoint),
                metadata={"source": "loop", "step": self.read_count},
                config={
                    "configurable": {
                        "thread_id": "thread-1",
                        "checkpoint_ns": "",
                        "checkpoint_id": checkpoint["id"],
                    }
                },
            )

        def get_next_version(self, current, _channel):
            return (current or 0) + 1

    checkpointer = _AdvancingTitleCheckpointer()
    app_config = SimpleNamespace(title=TitleConfig(enabled=True, max_chars=40, max_words=20))

    title = await _ensure_interrupted_title(checkpointer=checkpointer, thread_id="thread-1", app_config=app_config)

    assert title == "New prompt"
    _, written_checkpoint, _, _ = checkpointer.aput.await_args.args
    assert written_checkpoint["channel_values"]["messages"] == new_messages
    assert written_checkpoint["channel_values"]["title"] == "New prompt"


@pytest.mark.anyio
async def test_ensure_interrupted_title_bumps_channel_version_and_declares_it_in_new_versions(monkeypatch):
    """Regression for #3859 review: DB-backed savers (Sqlite/Postgres) strip inline
    ``channel_values`` from ``put`` and only persist blobs for channels listed in
    ``new_versions``. The helper must therefore bump ``channel_versions["title"]``
    and pass ``{"title": next_version}`` so the fallback title actually survives
    a fresh ``aget_tuple`` after the worker's finally hook.
    """
    from deerflow.agents.middlewares.title_middleware import TitleMiddleware

    monkeypatch.setattr(
        TitleMiddleware,
        "_generate_title_result",
        lambda self, state, allow_partial_exchange=False: {"title": "Generated Title"},
    )

    initial_checkpoint = {
        "id": "ckpt-1",
        "ts": "2026-06-29T00:00:00Z",
        "channel_values": {"messages": [{"type": "human", "content": "hi"}]},
        "channel_versions": {"messages": 5},
    }
    checkpointer = _TitleCheckpointer(
        tuple_value=_FakeCheckpointTuple(
            checkpoint=initial_checkpoint,
            metadata={"source": "loop", "step": 7},
        ),
    )

    title = await _ensure_interrupted_title(checkpointer=checkpointer, thread_id="thread-1", app_config=None)

    assert title == "Generated Title"
    checkpointer.aput.assert_awaited_once()
    write_config, written_checkpoint, written_metadata, new_versions = checkpointer.aput.await_args.args

    # The title channel must be declared in new_versions — without this, DB
    # savers drop the inline channel_values["title"] from the persisted blob.
    assert new_versions == {"title": 1}
    # Channel versions on the checkpoint itself must also reflect the bump,
    # so a subsequent aget_tuple reconstructs channel_values with the title.
    assert written_checkpoint["channel_versions"]["title"] == 1
    # Pre-existing channel versions must be preserved.
    assert written_checkpoint["channel_versions"]["messages"] == 5
    # The fallback title rides into channel_values for the (legacy / single-table)
    # savers that inline the snapshot.
    assert written_checkpoint["channel_values"]["title"] == "Generated Title"
    assert written_metadata["source"] == "update"
    assert written_metadata["step"] == 8
    assert written_metadata["writes"] == {"runtime_interrupt_title": {"title": "Generated Title"}}
    assert write_config == {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}


@pytest.mark.anyio
async def test_ensure_interrupted_title_writes_graph_input_fallback_without_checkpoint(monkeypatch):
    """When no checkpoint exists, graph_input should still seed the fallback title write."""
    from deerflow.agents.middlewares.title_middleware import TitleMiddleware

    captured_state: dict[str, Any] = {}

    def _generate(self, state, allow_partial_exchange=False):
        del self
        captured_state.update(state)
        assert allow_partial_exchange is True
        return {"title": "Graph Input Title"}

    monkeypatch.setattr(TitleMiddleware, "_generate_title_result", _generate)

    checkpointer = _TitleCheckpointer(tuple_value=None)

    title = await _ensure_interrupted_title(
        checkpointer=checkpointer,
        thread_id="thread-1",
        app_config=None,
        graph_input={"messages": [{"role": "user", "content": "Please name this thread"}]},
    )

    assert title == "Graph Input Title"
    assert captured_state["messages"] == [{"role": "user", "content": "Please name this thread"}]
    checkpointer.aput.assert_awaited_once()
    _, written_checkpoint, written_metadata, new_versions = checkpointer.aput.await_args.args
    assert written_checkpoint["channel_values"]["title"] == "Graph Input Title"
    assert written_metadata["writes"] == {"runtime_interrupt_title": {"title": "Graph Input Title"}}
    assert set(new_versions.keys()) == {"title"}


@pytest.mark.anyio
async def test_ensure_interrupted_title_bumps_existing_string_version(monkeypatch):
    """When the checkpointer lacks ``get_next_version`` and the prior title
    version is a string (some savers use UUID-shaped versions), the helper must
    still produce a strictly different value rather than overwriting in place.
    """
    from deerflow.agents.middlewares.title_middleware import TitleMiddleware

    monkeypatch.setattr(
        TitleMiddleware,
        "_generate_title_result",
        lambda self, state, allow_partial_exchange=False: {"title": "T"},
    )

    initial_checkpoint = {
        "id": "ckpt-1",
        "ts": "2026-06-29T00:00:00Z",
        "channel_values": {"messages": [{"type": "human", "content": "hi"}]},
        "channel_versions": {"title": "v3"},
    }

    class _NoGetNextVersion:
        def __init__(self):
            self.aget_tuple = AsyncMock(
                return_value=_FakeCheckpointTuple(
                    checkpoint=initial_checkpoint,
                    metadata={},
                ),
            )
            self.aput = AsyncMock(return_value={})

    checkpointer = _NoGetNextVersion()
    await _ensure_interrupted_title(checkpointer=checkpointer, thread_id="thread-1", app_config=None)

    _, written_checkpoint, _, new_versions = checkpointer.aput.await_args.args
    bumped = written_checkpoint["channel_versions"]["title"]
    assert bumped != "v3", "title version must change so DB savers persist the update"
    assert new_versions == {"title": bumped}


@pytest.mark.anyio
async def test_ensure_interrupted_title_skips_when_title_already_set():
    """If the checkpoint already carries a title, no new checkpoint is written."""
    checkpointer = _TitleCheckpointer(
        tuple_value=_FakeCheckpointTuple(
            checkpoint={
                "id": "ckpt-1",
                "channel_values": {"messages": [], "title": "Already there"},
                "channel_versions": {"title": 1},
            },
            metadata={},
        ),
    )

    title = await _ensure_interrupted_title(checkpointer=checkpointer, thread_id="thread-1", app_config=None)

    assert title == "Already there"
    checkpointer.aput.assert_not_awaited()


@pytest.mark.anyio
async def test_ensure_interrupted_title_round_trip_with_real_sqlite_checkpointer(tmp_path):
    """Full round-trip against a real ``AsyncSqliteSaver`` on a disk-backed DB.

    Mirrors what Gateway constructs in production via ``make_checkpointer`` when
    ``database.backend == "sqlite"``, then closes and re-opens the saver to
    simulate a fresh connection. The fallback title must survive that boundary —
    this is the scenario the #3874 review flagged as broken before the
    ``new_versions={"title": ...}`` fix.
    """
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.base import empty_checkpoint
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from deerflow.config.title_config import TitleConfig

    db_path = str(tmp_path / "ckpt.db")
    thread_cfg = {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}

    # 1. Seed a first-turn checkpoint that has a human message and NO title —
    #    the same shape the agent leaves behind when interrupted mid-stream.
    async with AsyncSqliteSaver.from_conn_string(db_path) as writer:
        await writer.setup()
        ck = empty_checkpoint()
        ck["channel_values"] = {
            "messages": [HumanMessage(content="Why is the sky blue?").model_dump()],
        }
        ck["channel_versions"] = {"messages": 1}
        await writer.aput(thread_cfg, ck, {"source": "loop", "step": 1, "writes": {}}, {"messages": 1})

    # 2. Run the worker helper through a *fresh* saver instance — this is what
    #    the lifespan-owned checkpointer pool does for each request.
    title_config = TitleConfig(enabled=True, max_chars=40, max_words=20)
    app_config = SimpleNamespace(title=title_config)
    async with AsyncSqliteSaver.from_conn_string(db_path) as worker_saver:
        title = await _ensure_interrupted_title(
            checkpointer=worker_saver,
            thread_id="thread-1",
            app_config=app_config,
        )
    assert title, "fallback title must be generated from the seeded user message"

    # 3. Open ANOTHER fresh saver and confirm the title survives — this is the
    #    invariant the #3874 review was guarding: ``new_versions={}`` would
    #    cause DB savers to drop the title blob, so a fresh aget_tuple would
    #    read back without it.
    async with AsyncSqliteSaver.from_conn_string(db_path) as reader:
        tup = await reader.aget_tuple(thread_cfg)
    assert tup is not None
    persisted = tup.checkpoint.get("channel_values", {}).get("title")
    assert persisted == title


# ---------------------------------------------------------------------------
# _bump_channel_version — invariant: the returned version MUST differ from
# the prior value, no matter the checkpointer's versioning scheme.
# ---------------------------------------------------------------------------


class _CheckpointerWithIntVersion:
    """A checkpointer whose ``get_next_version`` increments integers (default LangGraph behavior)."""

    @staticmethod
    def get_next_version(current, _channel):
        return (current or 0) + 1


class _CheckpointerWithBrokenGetNextVersion:
    """A checkpointer whose ``get_next_version`` raises — must fall back, not propagate."""

    @staticmethod
    def get_next_version(current, _channel):
        raise RuntimeError("simulated saver bug")


def test_bump_channel_version_uses_checkpointer_get_next_version_when_available():
    """Happy path — saver's ``get_next_version`` result is preferred over our fallback."""
    assert _bump_channel_version(_CheckpointerWithIntVersion(), 5) == 6


def test_bump_channel_version_falls_back_on_broken_get_next_version():
    """A raising ``get_next_version`` must not propagate; the defensive path bumps from prior.

    Without this, a saver bug would leave ``new_versions={"title": v}`` no-op
    on DB savers — the very class of bug the #3874 review flagged.
    """
    bumped = _bump_channel_version(_CheckpointerWithBrokenGetNextVersion(), 7)
    assert bumped == 8


# ---------------------------------------------------------------------------
# _ensure_interrupted_title — additional defensive boundaries
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ensure_interrupted_title_handles_none_messages_channel(monkeypatch):
    """A partially-initialized checkpoint with ``messages=None`` must not crash."""
    from deerflow.config.title_config import TitleConfig

    initial_checkpoint = {
        "id": "ckpt-1",
        "channel_values": {"messages": None},
        "channel_versions": {},
    }
    checkpointer = _TitleCheckpointer(
        tuple_value=_FakeCheckpointTuple(checkpoint=initial_checkpoint, metadata={}),
    )
    app_config = SimpleNamespace(title=TitleConfig(enabled=True, max_chars=40, max_words=20))

    assert await _ensure_interrupted_title(checkpointer=checkpointer, thread_id="thread-1", app_config=app_config) is None
    checkpointer.aput.assert_not_awaited()


@pytest.mark.anyio
async def test_ensure_interrupted_title_propagates_aput_error_to_caller(monkeypatch):
    """Exceptions from ``aput`` propagate — the caller (worker.run_agent finally block) is responsible for swallowing them.

    This test pins the contract: the helper itself does NOT silently eat saver errors,
    so a structural saver regression remains visible in the logs at the call site.
    """
    from deerflow.agents.middlewares.title_middleware import TitleMiddleware

    monkeypatch.setattr(
        TitleMiddleware,
        "_generate_title_result",
        lambda self, state, allow_partial_exchange=False: {"title": "Generated"},
    )

    initial_checkpoint = {
        "id": "ckpt-1",
        "channel_values": {"messages": [{"type": "human", "content": "hi"}]},
        "channel_versions": {"messages": 1},
    }
    checkpointer = _TitleCheckpointer(
        tuple_value=_FakeCheckpointTuple(checkpoint=initial_checkpoint, metadata={}),
    )
    checkpointer.aput.side_effect = RuntimeError("simulated DB write failure")

    with pytest.raises(RuntimeError, match="simulated DB write failure"):
        await _ensure_interrupted_title(checkpointer=checkpointer, thread_id="thread-1", app_config=None)


@pytest.mark.anyio
async def test_ensure_interrupted_title_idempotent_across_repeated_calls(monkeypatch):
    """Second invocation against the now-titled checkpoint must not re-write.

    Regression anchor for the case where a brittle helper might re-trigger
    on subsequent finally-hook runs (e.g. retries) and rewrite the title.
    """
    from langgraph.checkpoint.memory import InMemorySaver

    from deerflow.agents.middlewares.title_middleware import TitleMiddleware

    monkeypatch.setattr(
        TitleMiddleware,
        "_generate_title_result",
        lambda self, state, allow_partial_exchange=False: {"title": "First Title"},
    )

    checkpointer = InMemorySaver()
    cfg = {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}
    ck = empty_checkpoint()
    ck["channel_values"] = {"messages": [{"type": "human", "content": "hi"}]}
    ck["channel_versions"] = {"messages": 1}
    await checkpointer.aput(cfg, ck, {"source": "loop", "step": 1, "writes": {}}, {"messages": 1})

    first = await _ensure_interrupted_title(checkpointer=checkpointer, thread_id="thread-1", app_config=None)
    assert first == "First Title"

    # Second call: title is now present, so the helper short-circuits without
    # rewriting — even if the middleware were to suggest a different title.
    monkeypatch.setattr(
        TitleMiddleware,
        "_generate_title_result",
        lambda self, state, allow_partial_exchange=False: {"title": "Different Title"},
    )
    second = await _ensure_interrupted_title(checkpointer=checkpointer, thread_id="thread-1", app_config=None)
    assert second == "First Title"

    tup = await checkpointer.aget_tuple(cfg)
    assert tup.checkpoint["channel_values"]["title"] == "First Title"


@pytest.mark.anyio
async def test_ensure_interrupted_title_preserves_non_title_channel_versions(monkeypatch):
    """Bumping ``channel_versions["title"]`` must not modify other channels' versions.

    Regression anchor: an earlier draft built ``new_versions`` from
    ``dict(channel_versions)`` and would have erroneously declared every
    channel as "needs new blob" on DB savers.
    """
    from deerflow.agents.middlewares.title_middleware import TitleMiddleware

    monkeypatch.setattr(
        TitleMiddleware,
        "_generate_title_result",
        lambda self, state, allow_partial_exchange=False: {"title": "Generated"},
    )

    initial_checkpoint = {
        "id": "ckpt-1",
        "channel_values": {
            "messages": [{"type": "human", "content": "hi"}],
            "artifacts": [],
            "todos": None,
        },
        "channel_versions": {"messages": 5, "artifacts": 3, "todos": 1},
    }
    checkpointer = _TitleCheckpointer(
        tuple_value=_FakeCheckpointTuple(checkpoint=initial_checkpoint, metadata={}),
    )

    await _ensure_interrupted_title(checkpointer=checkpointer, thread_id="thread-1", app_config=None)

    _, written_checkpoint, _, new_versions = checkpointer.aput.await_args.args
    # Only the title channel is declared in new_versions.
    assert set(new_versions.keys()) == {"title"}
    # Other channel versions are preserved verbatim on the written checkpoint.
    assert written_checkpoint["channel_versions"]["messages"] == 5
    assert written_checkpoint["channel_versions"]["artifacts"] == 3
    assert written_checkpoint["channel_versions"]["todos"] == 1


@pytest.mark.anyio
async def test_worker_finally_block_swallows_helper_exceptions(monkeypatch):
    """The worker's interrupted-title hook must remain non-fatal — any exception
    from the helper (DB saver bug, middleware bug, etc.) must not propagate past
    the run boundary or prevent the subsequent threads_meta sync block from
    running. This pins the integration of helper + finally try/except, not just
    the helper itself.
    """
    import deerflow.runtime.runs.worker as worker_module

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("forced helper failure")

    monkeypatch.setattr(worker_module, "_ensure_interrupted_title", _boom)

    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    record.status = RunStatus.interrupted

    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )

    class _MinimalCheckpointer:
        async def aget_tuple(self, config):
            return None

        async def aput(self, *args, **kwargs):
            return {}

    captured_status: dict[str, Any] = {}

    class _ThreadStore:
        async def update_display_name(self, thread_id, title):
            captured_status["display_name"] = (thread_id, title)

        async def update_status(self, thread_id, status):
            captured_status["status"] = (thread_id, status)

    class _AbortingAgent:
        def __init__(self) -> None:
            self.metadata = {"model_name": "fake-test-model"}
            self.checkpointer: Any | None = None
            self.store: Any | None = None
            self.interrupt_before_nodes = None
            self.interrupt_after_nodes = None

        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            # Abort immediately so the run lands in the interrupted branch.
            record.abort_event.set()
            if False:
                yield  # pragma: no cover — make this an async generator
            return

    def factory(*, config):
        del config
        return _AbortingAgent()

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=_MinimalCheckpointer(), thread_store=_ThreadStore()),
        agent_factory=factory,
        graph_input={"messages": []},
        config={},
    )

    # The helper raised, but the run still reaches the threads_meta status sync
    # and ``publish_end`` — i.e. the SSE stream is closed cleanly and the row
    # reflects the run outcome.
    assert captured_status.get("status") == ("thread-1", "interrupted")
    bridge.publish_end.assert_awaited_once_with(record.run_id)
