"""With pii_redaction enabled, the goal evaluator's direct model call gets redacted input."""

import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.agents.middlewares import memory_middleware, pii_redaction_middleware
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
_OBJECTIVE = "Collect the contacts into outputs/contacts.md and send it to bob@example.com"


def _evaluator():
    verdict = {"satisfied": False, "blocker": "goal_not_met_yet", "reason": "Not sent yet.", "evidence_summary": "", "relied_on_assumption": False}
    return SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps(verdict))))


def _cut_identifiers(cuts, length=5000):
    # An email at each cut, so a value shortened there ends mid-address ("alice600@exa").
    text = ""
    for cut in cuts:
        start = cut - len(f"alice{cut}@exa")
        text += "x" * (start - len(text) - 1) + f" alice{cut}@example.com "
    return text + "x" * (length - len(text))


def _contacts_run():
    # A tool argument, a tool result and a card answer, each with an address where its evidence cap cuts it.
    answer = {"version": 1, "kind": "human_input_response", "source": "ask_clarification", "request_id": "req-1", "response_kind": "text", "value": _cut_identifiers([goal.MAX_GOAL_REQUEST_CHARS], length=2500)}
    return [
        HumanMessage(content="Collect the contacts into outputs/contacts.md."),
        AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"path": "/mnt/user-data/outputs/contacts.md", "content": _cut_identifiers([goal.MAX_GOAL_TOOL_VALUE_CHARS])}, "id": "call-write"}]),
        ToolMessage(content=_cut_identifiers([goal.MAX_GOAL_TOOL_STEP_CHARS]), tool_call_id="call-write", name="write_file"),
        HumanMessage(content="My answer is in the card.", additional_kwargs={"hide_from_ui": True, "human_input_response": answer}),
        AIMessage(content="outputs/contacts.md lists the contacts."),
    ]


async def _evaluator_input(messages, app_config, objective=_OBJECTIVE):
    model = _evaluator()
    await goal.evaluate_goal_completion(goal.build_goal_state(objective), messages, model=model, app_config=app_config)
    system_message, human_message = model.ainvoke.await_args.args[0]
    return system_message.content, human_message.content


@pytest.mark.asyncio
async def test_identifiers_are_redacted_before_the_evidence_cuts_them():
    messages = _contacts_run()
    before = [message.model_dump() for message in messages]

    _, raw = await _evaluator_input(messages, _DISABLED)
    _, redacted = await _evaluator_input(messages, _ENABLED)

    # Off, the argument, the result and the card answer are each cut inside an address,
    # where a pass over the assembled input no longer finds it.
    assert len(re.findall(r"alice\d+@exa(?!mple)", raw)) == 3
    assert "alice" not in redacted
    assert "@exa" not in redacted
    # Each value shows a placeholder where its first address was.
    for prefix in ('Assistant tool call: write_file {"path": "/mnt/user-data/outputs/contacts.md", "content": "', 'Tool result (write_file): "', goal.GOAL_CARD_ANSWER_PREFIX):
        assert re.search(re.escape(prefix) + r"x+ \[EMAIL_[a-z]", redacted)
    # Thread state keeps the raw text for display.
    assert [message.model_dump() for message in messages] == before


@pytest.mark.asyncio
async def test_goal_objective_is_redacted():
    _, raw = await _evaluator_input(_contacts_run(), _DISABLED)
    _, redacted = await _evaluator_input(_contacts_run(), _ENABLED)

    assert "send it to bob@example.com" in raw
    assert "bob@example.com" not in redacted
    assert f"Active goal:\nCollect the contacts into outputs/contacts.md and send it to {redact_text('bob@example.com', _PII)}\n\n" in redacted


@pytest.mark.asyncio
@pytest.mark.parametrize("app_config", [None, _DISABLED], ids=["no config", "disabled"])
async def test_evaluator_input_is_unchanged_when_redaction_is_off(app_config):
    messages = _contacts_run()
    system, human = await _evaluator_input(messages, app_config)
    enabled_system, _ = await _evaluator_input(messages, _ENABLED)

    assert human == f"Active goal:\n{_OBJECTIVE}\n\nVisible conversation evidence:\n{goal.format_visible_conversation(messages)}\n\nIs the active goal fully satisfied?"
    assert system == enabled_system
    # Enabled, input without identifiers is unchanged too.
    clean = [
        HumanMessage(content="Summarize notes.md."),
        AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": "notes.md"}, "id": "call-read"}]),
        ToolMessage(content="y" * 5000, tool_call_id="call-read", name="read_file"),
        AIMessage(content="Done."),
    ]
    assert await _evaluator_input(clean, _ENABLED, "Summarize notes.md") == await _evaluator_input(clean, app_config, "Summarize notes.md")


@pytest.mark.asyncio
async def test_only_the_evidence_window_is_redacted(monkeypatch):
    # The first exchange is outside the evaluator's window, so redacting it would only hold the event loop.
    early = [HumanMessage(content="Write to dave@example.com first."), AIMessage(content="Noted, dave@example.com.")]
    later = [message for index in range(goal.MAX_GOAL_CONVERSATION_MESSAGES // 2) for message in (HumanMessage(content=f"Step {index} for erin@example.com."), AIMessage(content=f"Step {index} done."))]
    messages = [*early, *later]
    redact_queued_messages = memory_middleware.redact_queued_messages
    redacted_batches = []

    def spy(batch, config):
        redacted_batches.append(list(batch))
        return redact_queued_messages(batch, config)

    monkeypatch.setattr(memory_middleware, "redact_queued_messages", spy)
    _, redacted = await _evaluator_input(messages, _ENABLED)

    assert redacted_batches == [later]
    # The evidence is the same as when the whole thread is redacted.
    assert f"Visible conversation evidence:\n{goal.format_visible_conversation(redact_queued_messages(messages, _PII))}\n\n" in redacted
    assert "erin@example.com" not in redacted


class _Bridge:
    async def publish(self, _run_id, _event, _payload):
        pass


async def _evaluate_in_worker(model):
    checkpointer = InMemorySaver()
    thread_id = "pii-thread"
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {"messages": [HumanMessage(content="Draft a reply to carol@example.com."), AIMessage(content="Drafted the reply to carol@example.com.")]}
    checkpoint["channel_versions"] = {"messages": 1}
    checkpointer.put({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}, checkpoint, {"step": 1}, {"messages": 1})
    await goal.write_thread_goal(checkpointer, thread_id, goal.build_goal_state("Draft a reply to carol@example.com"))

    await worker._prepare_goal_continuation_input(
        accessor=CheckpointStateAccessor.bind(build_state_mutation_graph("goal_evaluator", "full"), checkpointer, mode="full"),
        bridge=_Bridge(),
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-1",
        model_name="test-model",
        app_config=_ENABLED,
        evaluator_model_factory=lambda: model,
    )
    return await goal.read_thread_goal(checkpointer, thread_id)


@pytest.mark.asyncio
async def test_worker_evaluation_redacts_under_the_run_config():
    model = _evaluator()

    await _evaluate_in_worker(model)

    _, human_message = model.ainvoke.await_args.args[0]
    assert "carol@example.com" not in human_message.content
    assert human_message.content.count(redact_text("carol@example.com", _PII)) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("redactor", [(memory_middleware, "redact_queued_messages"), (pii_redaction_middleware, "redact_text")], ids=["messages", "input"])
async def test_redaction_error_fails_the_check_instead_of_sending_raw_text(monkeypatch, redactor):
    def fail(*_args, **_kwargs):
        raise RuntimeError("redactor unavailable")

    monkeypatch.setattr(*redactor, fail)
    model = _evaluator()

    latest_goal = await _evaluate_in_worker(model)

    model.ainvoke.assert_not_awaited()
    assert latest_goal["status"] == "active"
    assert latest_goal["last_evaluation"]["stand_down_reason"] == "evaluator_failed"
