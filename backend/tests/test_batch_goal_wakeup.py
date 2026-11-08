"""A confirmed result can resolve external waiting without resetting Goal limits."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.runtime.goal import build_goal_state, read_thread_goal, wake_goal_after_external_wait, write_thread_goal


async def waiting_goal(**changes):
    goal = build_goal_state("Combine the completed batch", max_continuations=2)
    goal["last_evaluation"] = {"satisfied": False, "blocker": "external_wait", "stand_down_reason": "blocked:external_wait"}
    goal.update(changes)
    saver = InMemorySaver()
    await write_thread_goal(saver, "thread", goal, create_if_missing=True)
    return saver, goal


@pytest.mark.asyncio
async def test_external_result_consumes_one_continuation_and_run_recovery_does_not_charge_it_twice():
    saver, goal = await waiting_goal()
    assert await wake_goal_after_external_wait(saver, "thread", "wake-run", goal)
    assert await wake_goal_after_external_wait(saver, "thread", "wake-run", goal)
    current = await read_thread_goal(saver, "thread")
    assert current["continuation_count"] == 1
    assert current["no_progress_count"] == 0
    assert current["last_batch_wakeup_run_id"] == "wake-run"
    assert current["last_evaluation"] == goal["last_evaluation"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"continuation_count": 2},
        {"no_progress_count": 2},
        {"last_evaluation": {"blocker": "needs_user_input", "stand_down_reason": "blocked:needs_user_input"}},
        {"last_evaluation": {"blocker": "external_wait", "stand_down_reason": "token_capped"}},
    ],
)
async def test_external_result_does_not_bypass_existing_limits_or_other_blockers(changes):
    saver, goal = await waiting_goal(**changes)
    assert not await wake_goal_after_external_wait(saver, "thread", "wake-run", goal)
    assert await read_thread_goal(saver, "thread") == goal


@pytest.mark.asyncio
async def test_changed_goal_cannot_be_resumed_by_an_old_batch_event():
    saver, goal = await waiting_goal()
    replacement = build_goal_state("A different task")
    await write_thread_goal(saver, "thread", replacement)
    assert not await wake_goal_after_external_wait(saver, "thread", "wake-run", goal)
    assert await read_thread_goal(saver, "thread") == replacement


def test_external_goal_input_cannot_forge_the_wakeup_receipt():
    from app.gateway.services import normalize_input

    value = normalize_input({"goal": {"objective": "A task", "last_batch_wakeup_run_id": "forged"}})
    assert "last_batch_wakeup_run_id" not in value["goal"]
