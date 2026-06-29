import copy

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import empty_checkpoint, uuid6
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.runtime.goal import GoalEvaluation, attach_goal_evaluation, build_goal_state, latest_visible_assistant_signature, read_thread_goal, write_thread_goal
from deerflow.runtime.runs import worker


class _CollectingBridge:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    async def publish(self, _run_id: str, event: str, payload: object) -> None:
        self.events.append((event, payload))


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
