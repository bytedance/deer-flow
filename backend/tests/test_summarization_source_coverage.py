"""A successful compaction must actually send every selected source to its model."""

from __future__ import annotations

import copy
import html
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, get_buffer_string
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware, SummaryGenerationError
from deerflow.config.task_continuity_config import TaskContinuityConfig
from deerflow.extensions import ExtensionRegistry

_RAW_BUDGET = 1200
_OLD_MEMORY = "PREVIOUS_DURABLE_MEMORY: preserve the user's release requirements. " + "Already verified context. " * 8


def _char_count(messages) -> int:
    """A deterministic test budget in raw text characters, without a tokenizer."""
    return sum(len(str(message.content)) for message in messages)


class RecordingSummaryModel(BaseChatModel):
    prompts: list[str] = Field(default_factory=list)
    fail_after: int | None = None
    output_text: str | None = None

    @property
    def _llm_type(self) -> str:
        return "source-coverage-offline-summary"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.prompts.append("\n".join(str(message.content) for message in messages))
        if self.fail_after is not None and len(self.prompts) > self.fail_after:
            raise RuntimeError("offline provider failed after a successful summary step")
        # Deliberately short: the configured budget leaves room for this rolling
        # summary and progress instructions, rather than creating a no-progress case.
        answer = self.output_text if self.output_text is not None else f"DIGEST_STEP_{len(self.prompts):03d}: remembered prior evidence."
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=answer))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _payload(label: str, padding: int = 500) -> tuple[str, tuple[str, ...]]:
    markers = (f"{label}_BEGIN", f"{label}_MIDDLE", f"{label}_END")
    # HTML-sensitive text exercises the raw-before-escaping budget as well.
    filler = " factual <value> & " * (padding // 18 + 1)
    return f"{markers[0]} {filler} {markers[1]} {filler} {markers[2]}", markers


def _history(case: str):
    selected = []
    markers = []
    current = HumanMessage(content="CURRENT_REQUEST_STAYS_RAW", id="current-user")
    tail = AIMessage(content="RECENT_ANSWER_STAYS_RAW", id="recent-answer")

    if case == "many-turns":
        for index in range(4):
            for role, message_class in (("USER", HumanMessage), ("ANSWER", AIMessage)):
                text, labels = _payload(f"TURN_{index}_{role}")
                selected.append(message_class(content=text, id=f"old-{index}-{role}"))
                markers.extend(labels)
        messages = [*selected, current, tail]
    elif case == "first-turn":
        for index in range(3):
            plan, plan_labels = _payload(f"FIRST_PLAN_{index}")
            result, result_labels = _payload(f"FIRST_RESULT_{index}")
            selected.extend(
                [
                    AIMessage(content=plan, id=f"plan-{index}", tool_calls=[{"name": "read_file", "args": {}, "id": f"call-{index}"}]),
                    ToolMessage(content=result, id=f"result-{index}", tool_call_id=f"call-{index}"),
                ]
            )
            markers.extend((*plan_labels, *result_labels))
        # Preserve the final complete AI/Tool exchange. The first real user
        # request is rescued independently of the selected older exchanges.
        recent = [
            AIMessage(content="RECENT_PLAN_STAYS_RAW", id="recent-plan", tool_calls=[{"name": "read_file", "args": {}, "id": "recent-call"}]),
            ToolMessage(content="RECENT_RESULT_STAYS_RAW", id="recent-result", tool_call_id="recent-call"),
        ]
        messages = [current, *selected, *recent]
    elif case == "oversized-message":
        text, labels = _payload("ONE_OVERSIZED_MESSAGE", padding=6500)
        selected = [HumanMessage(content=text, id="oversized-user"), AIMessage(content="old response", id="old-response")]
        markers.extend(labels)
        messages = [*selected, current, tail]
    else:
        assert case == "before-first-human"
        plan, plan_labels = _payload("BEFORE_HUMAN_PLAN")
        result, result_labels = _payload("BEFORE_HUMAN_TOOL")
        selected = [
            AIMessage(content=plan, id="leading-ai", tool_calls=[{"name": "read_file", "args": {}, "id": "leading-call"}]),
            ToolMessage(content=result, id="leading-tool", tool_call_id="leading-call"),
        ]
        markers.extend((*plan_labels, *result_labels))
        messages = [*selected, current, tail]
    return {"messages": messages}, selected, markers


def _raw_sections(prompt: str) -> list[tuple[str, str]]:
    # These are the documented model-facing source sections, not an internal
    # chunk planner. Decode after extraction so escaped source text cannot forge
    # a section boundary. No assertion depends on how many chunks are produced.
    matches = re.findall(r"<(existing_summary|new_messages)>\n(.*?)\n</\1>", prompt, re.DOTALL)
    assert matches, "the captured model input must contain the actual source text"
    return [(name, html.unescape(body)) for name, body in matches]


def _middleware(model, *, raw_budget=_RAW_BUDGET, **kwargs):
    return DeerFlowSummarizationMiddleware(
        model=model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=_char_count,
        trim_tokens_to_summarize=raw_budget,
        summary_prompt="{messages}",
        run_model_name="offline-summary",
        anchor_model_name="offline-summary",
        **kwargs,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("previous_summary", [None, _OLD_MEMORY], ids=["first-summary", "existing-summary"])
@pytest.mark.parametrize("case", ["many-turns", "first-turn", "oversized-message", "before-first-human"])
async def test_every_selected_source_reaches_bounded_summary_input(case, previous_summary, asynchronous):
    state, selected, markers = _history(case)
    state["summary_text"] = previous_summary
    original = copy.deepcopy(state)
    model = RecordingSummaryModel()
    hooks = []
    middleware = _middleware(model, before_summarization=[hooks.append])
    runtime = SimpleNamespace(context={"thread_id": "source-coverage"})

    result = await middleware.acompact_state(state, runtime) if asynchronous else middleware.compact_state(state, runtime)

    assert result is not None
    assert {message.id for message in result.messages_to_summarize} == {message.id for message in selected}
    assert "current-user" in {message.id for message in result.preserved_messages}
    assert model.prompts
    sections = [_raw_sections(prompt) for prompt in model.prompts]
    # Only new source participates in this stream: inserting the rolling
    # existing_summary between chunks would break a marker at a valid edge.
    captured_source = "".join(body for prompt_sections in sections for name, body in prompt_sections if name == "new_messages")
    missing = [marker for marker in markers if marker not in captured_source]
    assert not missing, f"sources were removed without reaching the summary model: {missing}"
    assert captured_source == get_buffer_string(selected), "every selected raw source character must reach the model without omissions or duplication"
    for raw in sections:
        assert sum(len(body) for _, body in raw) <= _RAW_BUDGET
    if previous_summary:
        assert dict(sections[0])["existing_summary"] == previous_summary
    assert len(hooks) == 1
    assert state == original


async def _assert_failed_compaction_is_atomic(monkeypatch, model, *, asynchronous, manual, previous_summary=_OLD_MEMORY, raw_budget=_RAW_BUDGET):
    from deerflow.agents.task_continuity import archive

    state, _, _ = _history("many-turns")
    state.update(summary_text=previous_summary, task_history={"existing": "untouched"})
    original = copy.deepcopy(state)
    hooks = []
    observed = []
    registry = ExtensionRegistry()
    with registry.attributed_to("test-source-coverage"):
        registry.context_compaction_observer(lambda event, context=None: observed.append(event))
    capture = Mock(return_value={"unexpected": "archive commit"})
    acapture = AsyncMock(return_value={"unexpected": "archive commit"})
    monkeypatch.setattr(archive, "capture", capture)
    monkeypatch.setattr(archive, "acapture", acapture)
    middleware = _middleware(
        model,
        raw_budget=raw_budget,
        before_summarization=[hooks.append],
        task_continuity_config=TaskContinuityConfig(enabled=True),
        extensions=registry.build(),
    )
    runtime = SimpleNamespace(context={"thread_id": "source-coverage"})

    if manual:
        with pytest.raises(SummaryGenerationError):
            if asynchronous:
                await middleware.acompact_state(state, runtime, force=True, raise_on_failure=True)
            else:
                middleware.compact_state(state, runtime, force=True, raise_on_failure=True)
    else:
        result = await middleware.abefore_model(state, runtime) if asynchronous else middleware.before_model(state, runtime)
        assert result is None, "automatic failure may not return a removal or partial summary update"

    assert state == original
    assert hooks == []
    assert observed == []
    capture.assert_not_called()
    acapture.assert_not_awaited()
    assert middleware.summary_call_count == 0
    for prompt in model.prompts:
        assert sum(len(body) for _, body in _raw_sections(prompt)) <= raw_budget


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("manual", [False, True], ids=["automatic", "manual"])
async def test_midway_provider_failure_cannot_commit_partial_compaction(monkeypatch, asynchronous, manual):
    model = RecordingSummaryModel(fail_after=1)
    await _assert_failed_compaction_is_atomic(monkeypatch, model, asynchronous=asynchronous, manual=manual)
    assert len(model.prompts) > 1, "the fault must occur after a successful provider step"


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("manual", [False, True], ids=["automatic", "manual"])
@pytest.mark.parametrize("boundary", ["oversized-previous", "previous-fills-budget", "tiny-budget", "oversized-model-output"])
async def test_unusable_carry_budget_cannot_commit_partial_compaction(monkeypatch, asynchronous, manual, boundary):
    model = RecordingSummaryModel()
    previous = _OLD_MEMORY
    budget = _RAW_BUDGET
    if boundary == "oversized-previous":
        previous = "P" * (_RAW_BUDGET + 1)
    elif boundary == "previous-fills-budget":
        previous = "P" * _RAW_BUDGET
    elif boundary == "tiny-budget":
        previous, budget = None, 1
    else:
        model.output_text = "MODEL_OUTPUT_TOO_LARGE " + "X" * _RAW_BUDGET

    await _assert_failed_compaction_is_atomic(monkeypatch, model, asynchronous=asynchronous, manual=manual, previous_summary=previous, raw_budget=budget)

    if boundary in {"oversized-previous", "previous-fills-budget"}:
        assert model.prompts == [], "a carry that cannot leave room for source must fail before invoking the provider"
    else:
        assert model.prompts, "an unusable model-generated carry must fail after actual provider progress"
