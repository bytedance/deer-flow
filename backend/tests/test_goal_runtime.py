import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from deerflow.runtime import goal


def test_build_goal_state_defaults_to_claude_stop_hook_cap():
    state = goal.build_goal_state("Finish the tests")

    assert state["objective"] == "Finish the tests"
    assert state["status"] == "active"
    assert state["continuation_count"] == 0
    assert state["max_continuations"] == 8
    assert state["no_progress_count"] == 0
    assert state["max_no_progress_continuations"] == 2
    assert state["created_at"]


def test_parse_goal_evaluation_extracts_json_object_from_fenced_response():
    parsed = goal.parse_goal_evaluation_response('```json\n{"satisfied": true, "reason": "All requested tests pass.", "evidence_summary": "pytest passed"}\n```')

    assert parsed["satisfied"] is True
    assert parsed["blocker"] == "none"
    assert parsed["reason"] == "All requested tests pass."
    assert parsed["evidence_summary"] == "pytest passed"


def test_parse_goal_evaluation_strips_think_blocks():
    parsed = goal.parse_goal_evaluation_response('<think>maybe {"satisfied": false}</think>\n{"satisfied": false, "reason": "Missing verification."}')

    assert parsed["satisfied"] is False
    assert parsed["blocker"] == "missing_evidence"
    assert parsed["reason"] == "Missing verification."


def test_parse_goal_evaluation_preserves_typed_blocker():
    parsed = goal.parse_goal_evaluation_response('{"satisfied": false, "blocker": "needs_user_input", "reason": "The user must choose a deployment target."}')

    assert parsed["satisfied"] is False
    assert parsed["blocker"] == "needs_user_input"


def test_format_visible_conversation_excludes_hidden_and_system_messages():
    messages = [
        SystemMessage(content="internal"),
        HumanMessage(content="visible user"),
        HumanMessage(content="hidden control", additional_kwargs={"hide_from_ui": True}),
        AIMessage(content="visible assistant"),
    ]

    formatted = goal.format_visible_conversation(messages)

    assert "visible user" in formatted
    assert "visible assistant" in formatted
    assert "hidden control" not in formatted
    assert "internal" not in formatted


def test_should_continue_goal_respects_completion_and_cap():
    active = goal.build_goal_state("Finish", max_continuations=2)
    unmet = goal.GoalEvaluation(satisfied=False, blocker="goal_not_met_yet", reason="not yet")
    met = goal.GoalEvaluation(satisfied=True, blocker="none", reason="done")
    missing_evidence = goal.GoalEvaluation(satisfied=False, blocker="missing_evidence", reason="weak transcript")

    assert goal.should_continue_goal(active, unmet) is True
    assert goal.should_continue_goal({**active, "continuation_count": 2}, unmet) is False
    assert goal.should_continue_goal(active, met) is False
    assert goal.should_continue_goal(active, missing_evidence) is False


def test_should_continue_goal_respects_no_progress_cap():
    active = goal.build_goal_state("Finish")
    unmet = goal.GoalEvaluation(satisfied=False, blocker="goal_not_met_yet", reason="same evidence")

    assert goal.should_continue_goal(active, unmet, no_progress_count=0) is True
    assert goal.should_continue_goal(active, unmet, no_progress_count=active["max_no_progress_continuations"]) is False


def test_make_goal_continuation_message_is_hidden_from_ui():
    state = goal.build_goal_state("Finish the implementation")
    evaluation = goal.GoalEvaluation(satisfied=False, blocker="goal_not_met_yet", reason="Tests have not run")

    message = goal.make_goal_continuation_message(state, evaluation)

    assert message.additional_kwargs["hide_from_ui"] is True
    assert "Finish the implementation" in message.content
    assert "Tests have not run" in message.content


def test_evaluate_goal_completion_uses_non_thinking_model(monkeypatch):
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=SimpleNamespace(content='{"satisfied": true, "reason": "Done", "evidence_summary": "Done"}'))
    captured = {}

    def fake_create_chat_model(**kwargs):
        captured.update(kwargs)
        return fake_model

    monkeypatch.setattr(goal, "create_chat_model", fake_create_chat_model)
    state = goal.build_goal_state("Finish")

    result = asyncio.run(
        goal.evaluate_goal_completion(
            state,
            [
                HumanMessage(content="Please finish this."),
                AIMessage(content="Done."),
            ],
            app_config=object(),
        )
    )

    assert result["satisfied"] is True
    assert result["blocker"] == "none"
    assert captured["thinking_enabled"] is False
    assert captured["attach_tracing"] is False
    fake_model.ainvoke.assert_awaited_once()
    assert fake_model.ainvoke.await_args.kwargs["config"] == {"run_name": "goal_evaluator"}


def test_evaluate_goal_completion_fails_closed_without_assistant_evidence(monkeypatch):
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock()
    monkeypatch.setattr(goal, "create_chat_model", lambda **_kwargs: fake_model)
    state = goal.build_goal_state("Finish")

    result = asyncio.run(goal.evaluate_goal_completion(state, [HumanMessage(content="please do it")], app_config=object()))

    assert result["satisfied"] is False
    assert result["blocker"] == "missing_evidence"
    fake_model.ainvoke.assert_not_called()


def test_attach_goal_evaluation_records_blocker_progress_and_stand_down_reason():
    state = goal.build_goal_state("Finish")
    evaluation = goal.GoalEvaluation(
        satisfied=False,
        blocker="external_wait",
        reason="Waiting for deployment",
        evidence_summary="Deploy is pending",
    )

    updated = goal.attach_goal_evaluation(
        state,
        evaluation,
        run_id="run-1",
        no_progress_count=1,
        stand_down_reason="blocked:external_wait",
    )

    assert updated["no_progress_count"] == 1
    assert updated["last_evaluation"]["blocker"] == "external_wait"
    assert updated["last_evaluation"]["evidence_summary"] == "Deploy is pending"
    assert updated["last_evaluation"]["stand_down_reason"] == "blocked:external_wait"
    assert updated["last_evaluation"]["progress_key"]
