"""With pii_redaction enabled, the hidden goal continuation reaches the agent redacted."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.agents.middlewares import pii_redaction_middleware
from deerflow.agents.middlewares.pii_redaction_middleware import redact_text
from deerflow.config.app_config import AppConfig
from deerflow.config.pii_redaction_config import PiiRedactionConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.runtime import goal
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor, build_state_mutation_graph
from deerflow.runtime.runs import worker

_PII = PiiRedactionConfig(enabled=True, token_secret="unit-test-deployment-secret-0123456789")
_ENABLED = AppConfig(sandbox=SandboxConfig(use="test"), pii_redaction=_PII)
_DISABLED = AppConfig(sandbox=SandboxConfig(use="test"), pii_redaction=PiiRedactionConfig(enabled=False))
_OBJECTIVE = "Draft a reply to carol@example.com and text 13800138000 when it is sent"
_REASON = "The reply to carol@example.com is drafted, not sent; 13800138000 has not been texted."
_SUMMARY = "outputs/reply.md is addressed to carol@example.com."
_VERDICT = {"satisfied": False, "blocker": "goal_not_met_yet", "reason": _REASON, "evidence_summary": _SUMMARY, "relied_on_assumption": False}


def _evaluation(reason=_REASON, evidence_summary=_SUMMARY):
    return goal.GoalEvaluation(satisfied=False, blocker="goal_not_met_yet", reason=reason, evidence_summary=evidence_summary)


def _plain_content(objective, reason, evidence_summary):
    return (
        "<goal_continuation>\n"
        f"Active goal: {objective}\n"
        f"Evaluator result: not satisfied. Blocker: goal_not_met_yet. Reason: {reason or 'No reason provided.'}\n"
        f"Visible evidence: {evidence_summary or 'No evidence summary provided.'}\n"
        "Continue working toward the active goal. Use the available tools and conversation context. Do not ask the user to continue unless you are genuinely blocked.\n"
        "</goal_continuation>"
    )


def test_continuation_redacts_the_objective_reason_and_evidence():
    message = goal.make_goal_continuation_message(goal.build_goal_state(_OBJECTIVE), _evaluation(), pii_redaction=_PII)

    # Only the identifiers change, each to the token the user's own message gets for it.
    expected = _plain_content(_OBJECTIVE, _REASON, _SUMMARY)
    for value in ("carol@example.com", "13800138000"):
        expected = expected.replace(value, redact_text(value, _PII))
    assert message.content == expected
    assert message.additional_kwargs == {"hide_from_ui": True, "deerflow_goal_continuation": True}


@pytest.mark.parametrize("pii_redaction", [None, PiiRedactionConfig(enabled=False)], ids=["no config", "disabled"])
def test_continuation_is_unchanged_when_redaction_is_off(pii_redaction):
    message = goal.make_goal_continuation_message(goal.build_goal_state(_OBJECTIVE), _evaluation(), pii_redaction=pii_redaction)

    assert message.content == _plain_content(_OBJECTIVE, _REASON, _SUMMARY)
    # Enabled, a continuation without identifiers is unchanged too.
    clean = goal.make_goal_continuation_message(goal.build_goal_state("Write outputs/notes.md"), _evaluation(reason="Not written yet.", evidence_summary=""), pii_redaction=_PII)
    assert clean.content == _plain_content("Write outputs/notes.md", "Not written yet.", "")


class _Bridge:
    async def publish(self, _run_id, _event, _payload):
        pass


async def _continue_in_worker(app_config):
    checkpointer = InMemorySaver()
    thread_id = "continuation-pii-thread"
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {"messages": [HumanMessage(content="Draft a reply to carol@example.com."), AIMessage(content="I drafted outputs/reply.md.")]}
    checkpoint["channel_versions"] = {"messages": 1}
    checkpointer.put({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}, checkpoint, {"step": 1}, {"messages": 1})
    await goal.write_thread_goal(checkpointer, thread_id, goal.build_goal_state(_OBJECTIVE))
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps(_VERDICT))))

    continuation = await worker._prepare_goal_continuation_input(
        accessor=CheckpointStateAccessor.bind(build_state_mutation_graph("goal_evaluator", "full"), checkpointer, mode="full"),
        bridge=_Bridge(),
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-1",
        model_name="test-model",
        app_config=app_config,
        evaluator_model_factory=lambda: model,
    )
    return continuation, await goal.read_thread_goal(checkpointer, thread_id), model


@pytest.mark.asyncio
async def test_worker_continuation_is_redacted_under_the_run_config():
    continuation, latest_goal, _ = await _continue_in_worker(_ENABLED)

    [message] = continuation["messages"]
    assert message.content == goal.make_goal_continuation_message(goal.build_goal_state(_OBJECTIVE), _evaluation(), pii_redaction=_PII).content
    assert "carol@example.com" not in message.content
    assert "13800138000" not in message.content
    # Goal state keeps the raw objective, and the continuation is counted.
    assert latest_goal["objective"] == _OBJECTIVE
    assert latest_goal["continuation_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("app_config", [None, _DISABLED], ids=["no config", "disabled"])
async def test_worker_continuation_is_unchanged_when_redaction_is_off(app_config):
    continuation, _, _ = await _continue_in_worker(app_config)

    [message] = continuation["messages"]
    assert message.content == _plain_content(_OBJECTIVE, _REASON, _SUMMARY)


@pytest.mark.asyncio
async def test_redaction_error_fails_the_check_instead_of_sending_raw_text(monkeypatch):
    redact = pii_redaction_middleware.redact_text

    def fail_on_the_reason(text, config):
        # Only the continuation redacts the evaluator's reason alone; the evaluator's own input redacts as usual.
        if isinstance(text, str) and _REASON in text:
            raise RuntimeError(f"cannot redact {text}")
        return redact(text, config)

    monkeypatch.setattr(pii_redaction_middleware, "redact_text", fail_on_the_reason)

    continuation, latest_goal, model = await _continue_in_worker(_ENABLED)

    model.ainvoke.assert_awaited_once()
    assert continuation is None
    # As when the evaluator's input cannot be redacted: the goal stays active, and the check failed.
    assert latest_goal["status"] == "active"
    assert latest_goal["last_evaluation"]["stand_down_reason"] == "evaluator_failed"
    assert latest_goal["last_evaluation"]["blocker"] == "run_failed"
    assert latest_goal["last_evaluation"]["reason"] == "The goal continuation could not be redacted (RuntimeError)."
    # No continuation was sent, so none is counted, and the error's text is not stored.
    assert latest_goal["continuation_count"] == 0
    assert "carol" not in json.dumps(latest_goal["last_evaluation"])
