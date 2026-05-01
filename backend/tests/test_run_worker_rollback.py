from unittest.mock import AsyncMock, call

import pytest

from deerflow.runtime.runs.worker import _agent_factory_supports_app_config, _build_runtime_context, _rollback_to_pre_run_checkpoint


class FakeCheckpointer:
    def __init__(self, *, put_result):
        self.adelete_thread = AsyncMock()
        self.aput = AsyncMock(return_value=put_result)
        self.aput_writes = AsyncMock()


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
    checkpointer.aput.assert_awaited_once_with(
        {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}},
        {
            "id": "ckpt-1",
            "channel_versions": {"messages": 3},
            "channel_values": {"messages": ["before"]},
        },
        {"source": "input"},
        {"messages": 3},
    )
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

    checkpointer.aput.assert_awaited_once_with(
        {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}},
        {"id": "ckpt-1", "channel_versions": {}},
        {},
        {},
    )


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


def test_build_runtime_context_ignores_non_dict_caller_context():
    ctx = _build_runtime_context("thread-1", "run-1", "not-a-dict")
    assert ctx == {"thread_id": "thread-1", "run_id": "run-1"}


def test_agent_factory_supports_app_config_returns_false_when_signature_lookup_fails(monkeypatch):
    class BrokenCallable:
        def __call__(self, **kwargs):
            return kwargs

    monkeypatch.setattr("deerflow.runtime.runs.worker.inspect.signature", lambda _obj: (_ for _ in ()).throw(ValueError("boom")))

    assert _agent_factory_supports_app_config(BrokenCallable()) is False
