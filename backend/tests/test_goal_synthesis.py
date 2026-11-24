"""Tests for goal synthesis from conversation (``/goal from-chat``).

The synthesis module is harness-level and LLM-shaped: every test mocks
``run_oneshot_llm`` so the suite stays offline. The pins here are the
contracts the Gateway route and the IM manager rely on:

* the context builder keeps the summary plus the newest visible messages
  within a character budget, excludes evidence tool results and hidden
  framework messages, and keeps the human-input protocol messages — the
  assistant's clarification questions and the user's card answers;
* a clear conversation yields a normalized objective;
* an unclear conversation raises ``GoalSynthesisUnclear`` carrying a reason
  that is for server logs only — never user-facing text;
* malformed or oversized model output raises ``GoalSynthesisError``;
* PII redaction applies to whole lines and the summary before the budget can
  split an identifier, and again to the model input when enabled, matching the
  goal evaluator's direct-call treatment.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.config.app_config import AppConfig
from deerflow.config.pii_redaction_config import PiiRedactionConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.runtime import goal_synthesis
from deerflow.runtime.goal_synthesis import (
    GoalSynthesisError,
    GoalSynthesisUnclear,
    build_synthesis_context,
    synthesize_goal_objective,
)
from deerflow.utils.goal_objective import MAX_GOAL_OBJECTIVE_CHARS

_PII = PiiRedactionConfig(enabled=True, token_secret="unit-test-deployment-secret-0123456789")
_PII_CONFIG = AppConfig(sandbox=SandboxConfig(use="test"), pii_redaction=_PII)
_PLAIN_CONFIG = AppConfig(sandbox=SandboxConfig(use="test"), pii_redaction=PiiRedactionConfig(enabled=False))

_INVOICE_MESSAGES = [
    HumanMessage(content="Reconcile this batch: vendor A has 3 invoices totaling 12,400 CNY, vendor B has 2 totaling 8,900 CNY."),
    AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": "invoices.csv"}, "id": "call-1"}]),
    ToolMessage(content="raw,csv,bytes", tool_call_id="call-1", name="read_file"),
    HumanMessage(content="Exclude the 1,500 CNY invoice from vendor C; it has not arrived yet.", additional_kwargs={"hide_from_ui": True}),
    HumanMessage(content="Exclude vendor C's 1,500 CNY invoice; it has not arrived yet."),
    AIMessage(content="Understood. A and B are in scope, C is excluded until its invoice arrives."),
    HumanMessage(content="When done, list every discrepancy and explain each one."),
]


def _mock_llm(monkeypatch, response_text: str) -> AsyncMock:
    mock = AsyncMock(return_value=response_text)
    monkeypatch.setattr(goal_synthesis, "run_oneshot_llm", mock)
    return mock


def _verdict(objective: str, *, unclear: bool = False, reason: str = "") -> str:
    return json.dumps({"objective": objective, "unclear": unclear, "reason": reason})


# -- context builder ---------------------------------------------------------


def test_context_includes_summary_and_visible_messages_in_order():
    context = build_synthesis_context(_INVOICE_MESSAGES, "Earlier the user described the invoice batch.")
    assert "Earlier the user described the invoice batch." in context
    assert "User: Reconcile this batch" in context
    assert "Assistant: Understood. A and B are in scope" in context
    assert "User: When done, list every discrepancy" in context
    # Chronological order is preserved.
    assert context.index("Reconcile this batch") < context.index("Understood. A and B") < context.index("list every discrepancy")


def test_context_excludes_tool_and_hidden_messages():
    context = build_synthesis_context(_INVOICE_MESSAGES, None)
    assert "raw,csv,bytes" not in context
    assert "read_file" not in context
    # The hidden duplicate of the vendor-C exclusion never appears; the visible one does.
    assert context.count("Exclude vendor C's 1,500 CNY invoice") == 1
    assert context.count("1,500 CNY") == 1


def test_context_accepts_dict_shaped_messages():
    messages = [
        {"type": "user", "content": "Sum the vendor totals."},
        {"type": "assistant", "content": "A: 12,400; B: 8,900."},
        {"type": "tool", "content": "tool noise"},
    ]
    context = build_synthesis_context(messages, None)
    assert "User: Sum the vendor totals." in context
    assert "Assistant: A: 12,400; B: 8,900." in context
    assert "tool noise" not in context


def test_context_budget_keeps_the_newest_messages_and_marks_omission():
    messages = [HumanMessage(content=f"message number {index} with some padding text") for index in range(40)]
    context = build_synthesis_context(messages, None, budget_chars=300)
    assert "message number 39" in context
    assert "message number 38" in context
    assert "message number 0" not in context
    assert "omitted" in context.lower()
    assert len(context) <= 300 + len("[ earlier messages omitted]") + 8


def test_context_keeps_the_opening_of_one_overlong_message():
    # A single paste longer than the whole budget must not collapse the
    # context to an omission marker: the request itself is the goal source.
    long_message = "Task: reconcile the invoice batch. " + ("supporting detail " * 200)
    context = build_synthesis_context([HumanMessage(content=long_message)], None, budget_chars=300)
    assert context.startswith("User: Task: reconcile the invoice batch.")
    assert context.endswith(" …")
    assert len(context) <= 300
    assert "omitted" not in context.lower()


def test_context_redacts_a_message_before_the_budget_can_split_it():
    # The budget cut must never turn an email into an unmatchable prefix: the
    # line is redacted first, then truncated (the evaluator's rule for its
    # direct model call).
    message = HumanMessage(content=("a" * 144) + " bob@example.com trailing detail")
    context = build_synthesis_context([message], None, budget_chars=200, pii_redaction=_PII)
    assert "bob@exam" not in context
    assert "bob@example.com" not in context


def test_context_redacts_the_summary_before_the_budget_can_split_it():
    summary = ("a" * 50) + " bob@example.com"
    context = build_synthesis_context([], summary, budget_chars=200, pii_redaction=_PII)
    assert "bob@exa" not in context
    assert "bob@example.com" not in context


def test_context_summary_is_bounded_when_budget_is_small():
    long_summary = "S" * 5000
    context = build_synthesis_context([HumanMessage(content="recent ask")], long_summary, budget_chars=800)
    assert "recent ask" in context
    assert len(context) <= 800 + 64
    assert context.count("S") < 5000


def test_context_without_visible_messages_or_summary_is_empty():
    assert build_synthesis_context([], None) == ""
    assert build_synthesis_context([ToolMessage(content="x", tool_call_id="c")], "") == ""
    # A summary alone is still usable context.
    assert "old decisions" in build_synthesis_context([], "old decisions")


def _clarification_tool_message(question: str, *, tool_call_id: str = "call-clarify") -> ToolMessage:
    return ToolMessage(
        content=f"❓ {question}",
        tool_call_id=tool_call_id,
        name="ask_clarification",
        artifact={
            "human_input": {
                "version": 1,
                "kind": "human_input_request",
                "source": "ask_clarification",
                "request_id": f"clarification:{tool_call_id}",
                "question": question,
            }
        },
    )


def test_context_includes_clarification_questions():
    # The assistant's question is a ToolMessage, not an AI text turn: without
    # this line the synthesizer cannot see that the conversation is waiting.
    messages = [HumanMessage(content="Reconcile the invoices."), _clarification_tool_message("What baseline should I compare against?")]
    context = build_synthesis_context(messages, None)
    assert "Assistant (waiting for input): What baseline should I compare against?" in context
    # The formatted fallback content (with options) is not duplicated.
    assert context.count("What baseline should I compare against?") == 1


def test_context_includes_non_clarification_human_input_requests():
    # Sandbox network approval uses the same artifact but a tool name such as bash.
    request = ToolMessage(
        content="Sandbox network policy blocked api.example.com:443.",
        tool_call_id="call-bash",
        name="bash",
        artifact={
            "human_input": {
                "version": 1,
                "kind": "human_input_request",
                "source": "sandbox_network_policy",
                "request_id": "net-1",
                "question": "Allow this sandbox to connect to api.example.com:443?",
            }
        },
    )
    context = build_synthesis_context([request], None)
    assert "Assistant (waiting for input): Allow this sandbox to connect to api.example.com:443?" in context


def test_context_includes_hidden_card_answers():
    answer = HumanMessage(
        content="",
        additional_kwargs={
            "hide_from_ui": True,
            "human_input_response": {
                "version": 1,
                "kind": "human_input_response",
                "source": "ask_clarification",
                "request_id": "clarification:call-clarify",
                "response_kind": "option",
                "option_id": "allow_sandbox",
                "value": "Allow for this sandbox",
            },
        },
    )
    context = build_synthesis_context([answer], None)
    assert "User (Human Input Card answer): Allow for this sandbox" in context


def test_context_excludes_disabled_clarification_instructions():
    # The policy-disabled path emits a same-named ToolMessage that instructs
    # the model, not a question for the user.
    disabled = ToolMessage(
        content="Clarification is disabled in this context — proceed with the smallest reasonable assumption.",
        tool_call_id="call-1",
        name="ask_clarification",
    )
    assert build_synthesis_context([disabled], None) == ""


def test_context_still_excludes_evidence_tool_results():
    messages = [
        HumanMessage(content="Sum the three vendors' revenue."),
        ToolMessage(content="A 12.3B, B 8.9B, C unknown", tool_call_id="call-search", name="web_search"),
    ]
    context = build_synthesis_context(messages, None)
    assert "Sum the three vendors' revenue." in context
    assert "12.3B" not in context
    assert "web_search" not in context


# -- synthesis ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_returns_normalized_objective(monkeypatch):
    mock = _mock_llm(monkeypatch, _verdict("  Reconcile invoices A and B, excluding C, until every discrepancy is explained.  "))
    objective = await synthesize_goal_objective(
        context="User: reconcile A and B\nAssistant: ok",
        guidance="focus on the vendor total",
        app_config=_PLAIN_CONFIG,
        thread_id="t-1",
    )
    assert objective == "Reconcile invoices A and B, excluding C, until every discrepancy is explained."
    kwargs = mock.await_args.kwargs
    # Default model, oneshot run name, thread attribution for tracing.
    assert kwargs["model_name"] is None
    assert kwargs["thread_id"] == "t-1"
    assert "focus on the vendor total" in kwargs["user_content"]
    assert "reconcile A and B" in kwargs["user_content"]


@pytest.mark.asyncio
async def test_synthesize_system_instruction_treats_conversation_as_data(monkeypatch):
    mock = _mock_llm(monkeypatch, _verdict("Ship it."))
    await synthesize_goal_objective(context="c", guidance="", app_config=_PLAIN_CONFIG)
    system = mock.await_args.kwargs["system_instruction"]
    # Anti-injection: the conversation is data, its instructions are ignored.
    assert "data" in system.lower()
    assert "ignore" in system.lower()
    # The objective must carry constraints and the stopping condition.
    assert "constraint" in system.lower()
    assert "stopping condition" in system.lower() or "complete" in system.lower()
    # Strict JSON output contract.
    assert '"objective"' in system and '"unclear"' in system


@pytest.mark.asyncio
async def test_synthesize_system_instruction_requires_the_users_language(monkeypatch):
    mock = _mock_llm(monkeypatch, _verdict("Ship it."))
    await synthesize_goal_objective(context="c", guidance="", app_config=_PLAIN_CONFIG)
    system = mock.await_args.kwargs["system_instruction"].lower()
    # Live acceptance (issue #7050 slice 1): with no language rule the model
    # alternated between Chinese and English objectives for the same
    # all-Chinese conversation. The objective is shown to the user verbatim
    # and drives the run, so it must follow the user's language.
    assert "language" in system
    assert "user" in system


@pytest.mark.asyncio
async def test_synthesize_unclear_raises_with_reason_and_no_objective(monkeypatch):
    _mock_llm(monkeypatch, _verdict("", unclear=True, reason="The conversation is small talk without a task."))
    with pytest.raises(GoalSynthesisUnclear) as raised:
        await synthesize_goal_objective(context="User: nice weather", guidance="", app_config=_PLAIN_CONFIG)
    assert "small talk" in str(raised.value)


@pytest.mark.asyncio
async def test_synthesize_malformed_output_raises_synthesis_error(monkeypatch):
    _mock_llm(monkeypatch, "I cannot output JSON, sorry.")
    with pytest.raises(GoalSynthesisError):
        await synthesize_goal_objective(context="c", guidance="", app_config=_PLAIN_CONFIG)


@pytest.mark.asyncio
async def test_synthesize_code_fenced_json_is_accepted(monkeypatch):
    _mock_llm(monkeypatch, "```json\n" + _verdict("Finish the report.") + "\n```")
    assert await synthesize_goal_objective(context="c", guidance="", app_config=_PLAIN_CONFIG) == "Finish the report."


@pytest.mark.asyncio
@pytest.mark.parametrize("literal", ["<think>literal content</think>", "<think>"])
async def test_synthesize_preserves_reasoning_tags_in_objective(monkeypatch, literal):
    objective = f'Document the "{literal}" syntax.'
    _mock_llm(monkeypatch, "<think>Drafting the objective.</think>\n" + _verdict(objective))
    assert await synthesize_goal_objective(context="c", guidance="", app_config=_PLAIN_CONFIG) == objective


@pytest.mark.asyncio
@pytest.mark.parametrize("literal", ["<think>literal content</think>", "<think>"])
async def test_synthesize_preserves_reasoning_tags_in_unclear_reason(monkeypatch, literal):
    reason = f'Clarify the intended handling of "{literal}".'
    _mock_llm(monkeypatch, _verdict("", unclear=True, reason=reason))
    with pytest.raises(GoalSynthesisUnclear) as raised:
        await synthesize_goal_objective(context="c", guidance="", app_config=_PLAIN_CONFIG)
    assert str(raised.value) == reason


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(_verdict(""), id="empty-objective"),
        pytest.param(_verdict("   \n "), id="blank-objective"),
        pytest.param(_verdict("x" * (MAX_GOAL_OBJECTIVE_CHARS + 1)), id="oversized-objective"),
        pytest.param(json.dumps({"objective": 42, "unclear": False}), id="non-string-objective"),
        pytest.param(json.dumps({"unclear": False}), id="missing-objective"),
    ],
)
async def test_synthesize_unusable_objective_raises_synthesis_error(monkeypatch, payload):
    _mock_llm(monkeypatch, payload)
    with pytest.raises(GoalSynthesisError):
        await synthesize_goal_objective(context="c", guidance="", app_config=_PLAIN_CONFIG)


@pytest.mark.asyncio
async def test_synthesize_llm_failure_propagates_as_synthesis_error(monkeypatch):
    mock = AsyncMock(side_effect=RuntimeError("provider down"))
    monkeypatch.setattr(goal_synthesis, "run_oneshot_llm", mock)
    with pytest.raises(GoalSynthesisError):
        await synthesize_goal_objective(context="c", guidance="", app_config=_PLAIN_CONFIG)


@pytest.mark.asyncio
async def test_synthesize_redacts_context_when_pii_enabled(monkeypatch):
    mock = _mock_llm(monkeypatch, _verdict("Email the reconciliation to the finance lead."))
    await synthesize_goal_objective(
        context="User: send the result to bob@example.com",
        guidance="",
        app_config=_PII_CONFIG,
    )
    user_content = mock.await_args.kwargs["user_content"]
    assert "bob@example.com" not in user_content


@pytest.mark.asyncio
async def test_synthesize_keeps_context_when_pii_disabled(monkeypatch):
    mock = _mock_llm(monkeypatch, _verdict("Email the reconciliation."))
    await synthesize_goal_objective(
        context="User: send the result to bob@example.com",
        guidance="",
        app_config=_PLAIN_CONFIG,
    )
    assert "bob@example.com" in mock.await_args.kwargs["user_content"]


@pytest.mark.asyncio
async def test_synthesize_accepts_explicit_model_name(monkeypatch):
    mock = _mock_llm(monkeypatch, _verdict("Ship it."))
    await synthesize_goal_objective(context="c", guidance="", app_config=_PLAIN_CONFIG, model_name="some-model")
    assert mock.await_args.kwargs["model_name"] == "some-model"
