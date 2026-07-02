import asyncio
import copy

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import empty_checkpoint, uuid6
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.runtime.goal import GoalEvaluation, attach_goal_evaluation, build_goal_state, latest_visible_assistant_signature, read_thread_goal, write_thread_goal
from deerflow.runtime.runs import worker
from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus


class _CollectingBridge:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    async def publish(self, _run_id: str, event: str, payload: object) -> None:
        self.events.append((event, payload))


class _ClearBeforeSecondGoalReadCheckpointer:
    """Wrap a saver and clear the goal just before the evaluator write rereads.

    The first ``aget_tuple`` is the evaluator's current-goal read. The second is
    ``write_thread_goal`` preparing its read-modify-write. Clearing at that point
    models a user ``/goal clear`` landing between those two operations.
    """

    def __init__(self, inner: InMemorySaver, thread_id: str) -> None:
        self.inner = inner
        self.thread_id = thread_id
        self.read_count = 0
        self.cleared = False

    def get_next_version(self, current, channel):
        return self.inner.get_next_version(current, channel)

    async def aget_tuple(self, config):
        self.read_count += 1
        if self.read_count == 2 and not self.cleared:
            self.cleared = True
            await write_thread_goal(self.inner, self.thread_id, None, as_node="test_clear")
        return await self.inner.aget_tuple(config)

    async def aput(self, *args, **kwargs):
        return await self.inner.aput(*args, **kwargs)


async def _seed_goal_thread(
    checkpointer: InMemorySaver,
    *,
    thread_id: str,
    goal_text: str,
    messages: list | None = None,
) -> None:
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {
        "messages": messages
        or [
            HumanMessage(content="Please finish this task."),
            AIMessage(content="I made a start, but I am not done."),
        ]
    }
    checkpoint["channel_versions"] = {"messages": 1}
    checkpointer.put(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        checkpoint,
        {"step": 1},
        {"messages": 1},
    )
    await write_thread_goal(checkpointer, thread_id, build_goal_state(goal_text, max_continuations=2))


async def _write_messages(checkpointer: InMemorySaver, *, thread_id: str, messages: list) -> None:
    checkpoint_tuple = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    assert checkpoint_tuple is not None
    checkpoint = copy.deepcopy(getattr(checkpoint_tuple, "checkpoint", {}) or {})
    metadata = copy.deepcopy(getattr(checkpoint_tuple, "metadata", {}) or {})
    channel_values = dict(checkpoint.get("channel_values", {}) or {})
    channel_values["messages"] = messages
    checkpoint["channel_values"] = channel_values
    channel_versions = dict(checkpoint.get("channel_versions", {}) or {})
    current_version = channel_versions.get("messages")
    channel_versions["messages"] = checkpointer.get_next_version(current_version, None)
    checkpoint["channel_versions"] = channel_versions
    checkpoint["id"] = str(uuid6())
    metadata["step"] = metadata.get("step", 0) + 1
    metadata["writes"] = {"test": {"messages": messages}}
    await checkpointer.aput(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        checkpoint,
        metadata,
        {"messages": channel_versions["messages"]},
    )


@pytest.mark.asyncio
async def test_goal_worker_returns_hidden_continuation_when_goal_is_unmet(monkeypatch):
    checkpointer = InMemorySaver()
    thread_id = "goal-thread"
    await _seed_goal_thread(checkpointer, thread_id=thread_id, goal_text="Finish all tests")
    bridge = _CollectingBridge()

    async def fake_evaluate_goal_completion(goal, messages, **_kwargs):
        assert goal["objective"] == "Finish all tests"
        assert [message.content for message in messages][-1] == "I made a start, but I am not done."
        return GoalEvaluation(
            satisfied=False,
            blocker="goal_not_met_yet",
            reason="Tests have not passed yet.",
            evidence_summary="Implementation is incomplete.",
        )

    monkeypatch.setattr(worker, "evaluate_goal_completion", fake_evaluate_goal_completion)

    continuation = await worker._prepare_goal_continuation_input(
        bridge=bridge,
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-1",
        model_name="test-model",
        app_config=None,
    )

    assert continuation is not None
    [message] = continuation["messages"]
    assert message.additional_kwargs["hide_from_ui"] is True
    assert "Finish all tests" in message.content
    assert "Tests have not passed yet." in message.content
    latest_goal = await read_thread_goal(checkpointer, thread_id)
    assert latest_goal is not None
    assert latest_goal["continuation_count"] == 1
    assert latest_goal["last_evaluation"]["run_id"] == "run-1"
    assert latest_goal["last_evaluation"]["blocker"] == "goal_not_met_yet"
    assert "stand_down_reason" not in latest_goal["last_evaluation"]
    assert bridge.events[0][0] == "values"


@pytest.mark.asyncio
async def test_goal_worker_clears_goal_when_evaluator_is_satisfied(monkeypatch):
    checkpointer = InMemorySaver()
    thread_id = "done-goal-thread"
    await _seed_goal_thread(checkpointer, thread_id=thread_id, goal_text="Finish all tests")
    bridge = _CollectingBridge()

    async def fake_evaluate_goal_completion(_goal, _messages, **_kwargs):
        return GoalEvaluation(
            satisfied=True,
            blocker="none",
            reason="The visible conversation says the task is done.",
            evidence_summary="Done.",
        )

    monkeypatch.setattr(worker, "evaluate_goal_completion", fake_evaluate_goal_completion)

    continuation = await worker._prepare_goal_continuation_input(
        bridge=bridge,
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-2",
        model_name="test-model",
        app_config=None,
    )

    assert continuation is None
    assert await read_thread_goal(checkpointer, thread_id) is None
    assert bridge.events[0][0] == "values"


@pytest.mark.asyncio
async def test_goal_worker_stands_down_for_non_continuable_blocker(monkeypatch):
    checkpointer = InMemorySaver()
    thread_id = "blocked-goal-thread"
    await _seed_goal_thread(checkpointer, thread_id=thread_id, goal_text="Finish all tests")
    bridge = _CollectingBridge()

    async def fake_evaluate_goal_completion(_goal, _messages, **_kwargs):
        return GoalEvaluation(
            satisfied=False,
            blocker="missing_evidence",
            reason="The transcript does not prove any verification.",
            evidence_summary="No test result is visible.",
        )

    monkeypatch.setattr(worker, "evaluate_goal_completion", fake_evaluate_goal_completion)

    continuation = await worker._prepare_goal_continuation_input(
        bridge=bridge,
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-3",
        model_name="test-model",
        app_config=None,
    )

    assert continuation is None
    latest_goal = await read_thread_goal(checkpointer, thread_id)
    assert latest_goal is not None
    assert latest_goal["continuation_count"] == 0
    assert latest_goal["last_evaluation"]["blocker"] == "missing_evidence"
    assert latest_goal["last_evaluation"]["stand_down_reason"] == "blocked:missing_evidence"


@pytest.mark.asyncio
async def test_goal_worker_stands_down_when_no_progress_repeats(monkeypatch):
    checkpointer = InMemorySaver()
    thread_id = "no-progress-goal-thread"
    messages = [HumanMessage(content="Please finish this task."), AIMessage(content="I made a start, but I am not done.")]
    await _seed_goal_thread(checkpointer, thread_id=thread_id, goal_text="Finish all tests", messages=messages)
    previous_goal = await read_thread_goal(checkpointer, thread_id)
    assert previous_goal is not None
    repeated_evaluation = GoalEvaluation(
        satisfied=False,
        blocker="goal_not_met_yet",
        reason="The same work remains.",
        evidence_summary="No new verification evidence.",
    )
    # Seed the prior evaluation with the SAME visible assistant evidence the worker
    # will recompute, so the no-progress breaker recognises the stalled turn even
    # though the evaluator may reword its free-text reason.
    evidence_signature = latest_visible_assistant_signature(messages)
    await write_thread_goal(
        checkpointer,
        thread_id,
        attach_goal_evaluation(previous_goal, repeated_evaluation, run_id="previous-run", no_progress_count=1, evidence_signature=evidence_signature),
    )
    bridge = _CollectingBridge()

    async def fake_evaluate_goal_completion(_goal, _messages, **_kwargs):
        return repeated_evaluation

    monkeypatch.setattr(worker, "evaluate_goal_completion", fake_evaluate_goal_completion)

    continuation = await worker._prepare_goal_continuation_input(
        bridge=bridge,
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-4",
        model_name="test-model",
        app_config=None,
    )

    assert continuation is None
    latest_goal = await read_thread_goal(checkpointer, thread_id)
    assert latest_goal is not None
    assert latest_goal["no_progress_count"] == 2
    assert latest_goal["last_evaluation"]["stand_down_reason"] == "no_progress_detected"


@pytest.mark.asyncio
async def test_goal_worker_does_not_resurrect_goal_cleared_during_evaluation(monkeypatch):
    checkpointer = InMemorySaver()
    thread_id = "clear-during-eval-thread"
    await _seed_goal_thread(checkpointer, thread_id=thread_id, goal_text="Finish all tests")
    bridge = _CollectingBridge()

    async def fake_evaluate_goal_completion(_goal, _messages, **_kwargs):
        await write_thread_goal(checkpointer, thread_id, None, as_node="test")
        return GoalEvaluation(
            satisfied=False,
            blocker="goal_not_met_yet",
            reason="More work remains.",
            evidence_summary="Work remains.",
        )

    monkeypatch.setattr(worker, "evaluate_goal_completion", fake_evaluate_goal_completion)

    continuation = await worker._prepare_goal_continuation_input(
        bridge=bridge,
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-5",
        model_name="test-model",
        app_config=None,
    )

    assert continuation is None
    assert await read_thread_goal(checkpointer, thread_id) is None


@pytest.mark.asyncio
async def test_goal_worker_does_not_resurrect_goal_cleared_during_persist():
    checkpointer = InMemorySaver()
    thread_id = "clear-during-persist-thread"
    await _seed_goal_thread(checkpointer, thread_id=thread_id, goal_text="Finish all tests")
    existing_goal = await read_thread_goal(checkpointer, thread_id)
    assert existing_goal is not None
    wrapped_checkpointer = _ClearBeforeSecondGoalReadCheckpointer(checkpointer, thread_id)
    bridge = _CollectingBridge()

    result = await worker._persist_goal_evaluation(
        bridge=bridge,
        checkpointer=wrapped_checkpointer,
        thread_id=thread_id,
        run_id="run-clear-during-persist",
        goal=existing_goal,
        evaluation=GoalEvaluation(
            satisfied=False,
            blocker="goal_not_met_yet",
            reason="More work remains.",
            evidence_summary="Work remains.",
        ),
        no_progress_count=0,
    )

    assert result is None
    assert wrapped_checkpointer.cleared is True
    assert await read_thread_goal(checkpointer, thread_id) is None


@pytest.mark.asyncio
async def test_goal_worker_stops_when_abort_is_requested_during_evaluation(monkeypatch):
    checkpointer = InMemorySaver()
    thread_id = "abort-during-eval-thread"
    await _seed_goal_thread(checkpointer, thread_id=thread_id, goal_text="Finish all tests")
    bridge = _CollectingBridge()
    abort_event = asyncio.Event()

    async def fake_evaluate_goal_completion(_goal, _messages, **_kwargs):
        abort_event.set()
        return GoalEvaluation(
            satisfied=False,
            blocker="goal_not_met_yet",
            reason="More work remains.",
            evidence_summary="Work remains.",
        )

    monkeypatch.setattr(worker, "evaluate_goal_completion", fake_evaluate_goal_completion)

    continuation = await worker._prepare_goal_continuation_input(
        bridge=bridge,
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-abort",
        model_name="test-model",
        app_config=None,
        abort_event=abort_event,
    )

    assert continuation is None
    latest_goal = await read_thread_goal(checkpointer, thread_id)
    assert latest_goal is not None
    assert latest_goal["continuation_count"] == 0
    assert "last_evaluation" not in latest_goal


@pytest.mark.asyncio
async def test_goal_worker_stands_down_when_thread_changes_after_evaluation(monkeypatch):
    checkpointer = InMemorySaver()
    thread_id = "user-wins-thread"
    await _seed_goal_thread(checkpointer, thread_id=thread_id, goal_text="Finish all tests")
    bridge = _CollectingBridge()

    async def fake_evaluate_goal_completion(_goal, messages, **_kwargs):
        await _write_messages(
            checkpointer,
            thread_id=thread_id,
            messages=[*messages, HumanMessage(content="Actually, stop and wait.")],
        )
        return GoalEvaluation(
            satisfied=False,
            blocker="goal_not_met_yet",
            reason="More work remains.",
            evidence_summary="Work remains.",
        )

    monkeypatch.setattr(worker, "evaluate_goal_completion", fake_evaluate_goal_completion)

    continuation = await worker._prepare_goal_continuation_input(
        bridge=bridge,
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-6",
        model_name="test-model",
        app_config=None,
    )

    assert continuation is None
    latest_goal = await read_thread_goal(checkpointer, thread_id)
    assert latest_goal is not None
    assert latest_goal["continuation_count"] == 0
    assert latest_goal["last_evaluation"]["stand_down_reason"] == "thread_changed_after_evaluation"


@pytest.mark.asyncio
async def test_goal_worker_stands_down_without_durable_assistant_receipt():
    checkpointer = InMemorySaver()
    thread_id = "no-receipt-thread"
    await _seed_goal_thread(
        checkpointer,
        thread_id=thread_id,
        goal_text="Finish all tests",
        messages=[HumanMessage(content="Please finish this task.")],
    )
    bridge = _CollectingBridge()

    continuation = await worker._prepare_goal_continuation_input(
        bridge=bridge,
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-7",
        model_name="test-model",
        app_config=None,
    )

    assert continuation is None
    latest_goal = await read_thread_goal(checkpointer, thread_id)
    assert latest_goal is not None
    assert latest_goal["last_evaluation"]["blocker"] == "run_failed"
    assert latest_goal["last_evaluation"]["stand_down_reason"] == "no_durable_end_of_turn"


def test_stand_down_reason_uses_documented_default_caps_when_missing():
    """_stand_down_reason must fall back to the same default caps as
    should_continue_goal (8 / 2). A bare goal dict missing the cap fields must
    not be reported as 'max reached' / 'no progress' when it has not actually
    exhausted the documented defaults.
    """
    bare_goal = {"objective": "x", "status": "active", "continuation_count": 0}
    unmet = GoalEvaluation(satisfied=False, blocker="goal_not_met_yet", reason="", evidence_summary="")

    assert worker._stand_down_reason(bare_goal, unmet, no_progress_count=0) is None
    # And the two gate functions agree on the same bare goal.
    from deerflow.runtime.goal import should_continue_goal

    assert should_continue_goal(bare_goal, unmet, no_progress_count=0) is True


@pytest.mark.asyncio
async def test_run_agent_does_not_stream_continuation_after_abort(monkeypatch):
    class FakeAgent:
        def __init__(self) -> None:
            self.inputs = []
            self.metadata = {}
            self.checkpointer = None
            self.store = None
            self.interrupt_before_nodes = []
            self.interrupt_after_nodes = []

        def astream(self, input_payload, **_kwargs):
            self.inputs.append(input_payload)

            async def _gen():
                yield {"messages": []}

            return _gen()

    class FakeRunManager:
        async def set_status(self, _run_id, status, **_kwargs):
            record.status = status

        async def update_model_name(self, *_args, **_kwargs):
            return None

        async def update_run_completion(self, *_args, **_kwargs):
            return None

        async def wait_for_prior_finalizing(self, *_args, **_kwargs):
            return None

        async def set_finalizing(self, _run_id, finalizing):
            record.finalizing = finalizing

    class FakeBridge:
        async def publish(self, *_args, **_kwargs):
            return None

        async def publish_end(self, *_args, **_kwargs):
            return None

        async def cleanup(self, *_args, **_kwargs):
            return None

    async def fake_prepare(**kwargs):
        kwargs["abort_event"].set()
        return {"messages": [HumanMessage(content="continue", additional_kwargs={"hide_from_ui": True})]}

    monkeypatch.setattr(worker, "_prepare_goal_continuation_input", fake_prepare)

    fake_agent = FakeAgent()
    record = RunRecord(
        run_id="run-abort-loop",
        thread_id="thread-abort-loop",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
        model_name="test-model",
    )
    record.abort_event = asyncio.Event()

    await worker.run_agent(
        FakeBridge(),
        FakeRunManager(),
        record,
        ctx=worker.RunContext(checkpointer=None),
        agent_factory=lambda config: fake_agent,
        graph_input={"messages": [HumanMessage(content="start")]},
        config={"configurable": {"thread_id": "thread-abort-loop"}},
    )

    assert len(fake_agent.inputs) == 1
    assert fake_agent.inputs[0] == {"messages": [HumanMessage(content="start")]}
    assert record.status == RunStatus.interrupted


@pytest.mark.asyncio
async def test_run_agent_reuses_goal_evaluator_model_for_goal_loop(monkeypatch):
    class FakeAgent:
        def __init__(self) -> None:
            self.inputs = []
            self.metadata = {}
            self.checkpointer = None
            self.store = None
            self.interrupt_before_nodes = []
            self.interrupt_after_nodes = []

        def astream(self, input_payload, **_kwargs):
            self.inputs.append(input_payload)

            async def _gen():
                yield {"messages": []}

            return _gen()

    class FakeRunManager:
        async def set_status(self, _run_id, status, **_kwargs):
            record.status = status

        async def update_model_name(self, *_args, **_kwargs):
            return None

        async def update_run_completion(self, *_args, **_kwargs):
            return None

        async def wait_for_prior_finalizing(self, *_args, **_kwargs):
            return None

        async def set_finalizing(self, _run_id, finalizing):
            record.finalizing = finalizing

    class FakeBridge:
        async def publish(self, *_args, **_kwargs):
            return None

        async def publish_end(self, *_args, **_kwargs):
            return None

        async def cleanup(self, *_args, **_kwargs):
            return None

    evaluator_model = object()
    create_calls = []

    def fake_create_goal_evaluator_model(**kwargs):
        create_calls.append(kwargs)
        return evaluator_model

    prepare_models = []

    async def fake_prepare(**kwargs):
        prepare_models.append(kwargs["evaluator_model_factory"]())
        if len(prepare_models) == 1:
            return {"messages": [HumanMessage(content="continue", additional_kwargs={"hide_from_ui": True})]}
        return None

    monkeypatch.setattr(worker, "create_goal_evaluator_model", fake_create_goal_evaluator_model)
    monkeypatch.setattr(worker, "_prepare_goal_continuation_input", fake_prepare)

    fake_agent = FakeAgent()
    record = RunRecord(
        run_id="run-model-cache",
        thread_id="thread-model-cache",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
        model_name="test-model",
    )
    record.abort_event = asyncio.Event()

    await worker.run_agent(
        FakeBridge(),
        FakeRunManager(),
        record,
        ctx=worker.RunContext(checkpointer=None, app_config=object()),
        agent_factory=lambda config: fake_agent,
        graph_input={"messages": [HumanMessage(content="start")]},
        config={"configurable": {"thread_id": "thread-model-cache"}},
    )

    assert len(fake_agent.inputs) == 2
    assert prepare_models == [evaluator_model, evaluator_model]
    assert len(create_calls) == 1
    assert create_calls[0]["model_name"] == "test-model"
    assert record.status == RunStatus.success


@pytest.mark.asyncio
async def test_run_agent_strips_branch_checkpoint_for_goal_continuation(monkeypatch):
    class FakeAgent:
        def __init__(self) -> None:
            self.calls = []
            self.metadata = {}
            self.checkpointer = None
            self.store = None
            self.interrupt_before_nodes = []
            self.interrupt_after_nodes = []

        def astream(self, input_payload, **kwargs):
            configurable = dict(kwargs["config"].get("configurable", {}))
            self.calls.append((input_payload, configurable))

            async def _gen():
                yield {"messages": []}

            return _gen()

    class FakeRunManager:
        async def set_status(self, _run_id, status, **_kwargs):
            record.status = status

        async def update_model_name(self, *_args, **_kwargs):
            return None

        async def update_run_completion(self, *_args, **_kwargs):
            return None

        async def wait_for_prior_finalizing(self, *_args, **_kwargs):
            return None

        async def set_finalizing(self, _run_id, finalizing):
            record.finalizing = finalizing

    class FakeBridge:
        async def publish(self, *_args, **_kwargs):
            return None

        async def publish_end(self, *_args, **_kwargs):
            return None

        async def cleanup(self, *_args, **_kwargs):
            return None

    async def fake_prepare(**_kwargs):
        if len(fake_agent.calls) == 1:
            return {"messages": [HumanMessage(content="continue", additional_kwargs={"hide_from_ui": True})]}
        return None

    monkeypatch.setattr(worker, "_prepare_goal_continuation_input", fake_prepare)

    fake_agent = FakeAgent()
    record = RunRecord(
        run_id="run-branch-continuation",
        thread_id="thread-branch-continuation",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
        model_name="test-model",
    )
    record.abort_event = asyncio.Event()

    await worker.run_agent(
        FakeBridge(),
        FakeRunManager(),
        record,
        ctx=worker.RunContext(checkpointer=None),
        agent_factory=lambda config: fake_agent,
        graph_input={"messages": [HumanMessage(content="start")]},
        config={
            "configurable": {
                "thread_id": "thread-branch-continuation",
                "checkpoint_ns": "branch",
                "checkpoint_id": "old-checkpoint",
                "checkpoint_map": {"": "old-checkpoint"},
            }
        },
    )

    assert len(fake_agent.calls) == 2
    first_config = fake_agent.calls[0][1]
    second_config = fake_agent.calls[1][1]
    assert first_config["checkpoint_ns"] == "branch"
    assert first_config["checkpoint_id"] == "old-checkpoint"
    assert first_config["checkpoint_map"] == {"": "old-checkpoint"}
    assert second_config["checkpoint_ns"] == ""
    assert "checkpoint_id" not in second_config
    assert "checkpoint_map" not in second_config
    assert second_config["thread_id"] == "thread-branch-continuation"
