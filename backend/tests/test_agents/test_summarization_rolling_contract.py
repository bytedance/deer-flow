"""Rolling compaction preserves candidate, cache, observation and PII contracts."""

from __future__ import annotations

import copy
import html
import re
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from deerflow_extension_api import SystemOperationKind
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, get_buffer_string
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from deerflow.agents.middlewares.pii_redaction_middleware import redact_text
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.config.pii_redaction_config import PiiRedactionConfig
from deerflow.extensions import ExtensionRegistry


class RecordingModel(BaseChatModel):
    answers: list[Any] = Field(default_factory=list)
    prompts: list[str] = Field(default_factory=list)
    default_answer: str = "S"

    @property
    def _llm_type(self) -> str:
        return "rolling-contract-offline"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.prompts.append("\n".join(str(message.content) for message in messages))
        answer = self.answers.pop(0) if self.answers else self.default_answer
        if isinstance(answer, Exception):
            raise answer
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=answer))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _char_count(messages):
    return sum(len(message.content) for message in messages)


def _sections(prompt):
    return {name: html.unescape(body) for name, body in re.findall(r"<(existing_summary|new_messages)>\n(.*?)\n</\1>", prompt, re.DOTALL)}


def _source(prompts):
    return "".join(_sections(prompt)["new_messages"] for prompt in prompts)


def _state(text=None):
    if text is None:
        text = " ".join(f"fact_{index:03d}: distinct evidence" for index in range(24))
    selected = [HumanMessage(content=text, id="old-user"), AIMessage(content="old answer", id="old-ai")]
    return {
        "messages": [*selected, HumanMessage(content="current request", id="current-user"), AIMessage(content="current answer", id="current-ai")],
        "summary_text": "S",
    }, selected


def _middleware(model, *, default_counter=False, **kwargs):
    options = {
        "trigger": ("messages", 4),
        "keep": ("messages", 2),
        "trim_tokens_to_summarize": 96,
        "summary_prompt": "{messages}",
        "anchor_model_name": "primary",
        "run_model_name": "primary",
    }
    if not default_counter:
        options["token_counter"] = _char_count
    options.update(kwargs)
    return DeerFlowSummarizationMiddleware(model=model, **options)


async def _compact(middleware, state, asynchronous, runtime=None):
    runtime = runtime or SimpleNamespace(context={})
    if asynchronous:
        return await middleware.acompact_state(state, runtime, force=True)
    return middleware.compact_state(state, runtime, force=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_middle_chunk_fallback_becomes_the_next_full_carry(asynchronous):
    primary = RecordingModel(answers=["PRIMARY_ONE", RuntimeError("primary unavailable")], default_answer="PRIMARY_LATER")
    fallback = RecordingModel(default_answer="FALLBACK_TWO")
    middleware = _middleware(primary, configured_model_name="primary", run_model_name="fallback", prebuilt_models={"fallback": fallback})
    state, selected = _state()
    original = copy.deepcopy(state)

    result = await _compact(middleware, state, asynchronous)

    assert result is not None
    assert len(primary.prompts) > 2
    assert len(fallback.prompts) == 1
    assert fallback.prompts[0] == primary.prompts[1]
    assert _sections(primary.prompts[1])["existing_summary"] == "PRIMARY_ONE"
    assert _sections(primary.prompts[2])["existing_summary"] == "FALLBACK_TWO"
    assert _source(primary.prompts) == get_buffer_string(selected)
    assert middleware.summary_call_count == 1
    assert middleware.summary_skip_count == 0
    assert state == original


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_only_a_fully_cached_rolling_pass_counts_as_skipped(asynchronous):
    model = RecordingModel()
    middleware = _middleware(model)
    state, _ = _state()

    first = await _compact(middleware, state, asynchronous)
    first_calls = len(model.prompts)
    assert first is not None and first_calls > 2
    second = await _compact(middleware, state, asynchronous)
    assert second is not None
    assert len(model.prompts) == first_calls
    assert middleware.summary_skip_count == 1

    changed = copy.deepcopy(state)
    changed["messages"][0] = changed["messages"][0].model_copy(update={"content": state["messages"][0].content.replace("fact_012", "FACT_012")})
    third = await _compact(middleware, changed, asynchronous)
    assert third is not None
    fresh_calls = len(model.prompts) - first_calls
    assert 0 < fresh_calls < first_calls, "cached prefix and suffix may not hide a model call for the changed middle"
    assert middleware.summary_call_count == 3
    assert middleware.summary_noop_count == 3
    assert middleware.summary_skip_count == 1, "a partly reused pass still made an LLM call"


@pytest.mark.asyncio
async def test_async_observer_counts_actual_attempts_and_telemetry_counts_whole_passes():
    observations = []

    class Observer:
        async def on_system_model_call(self, app_store, task_store, kind, request, result):
            observations.append((kind, request, result))

    registry = ExtensionRegistry()
    with registry.attributed_to("rolling-contract"):
        registry.system_model_observer(Observer())
    primary = RecordingModel(answers=["S", RuntimeError("middle primary failure")])
    fallback = RecordingModel()
    middleware = _middleware(primary, configured_model_name="primary", run_model_name="fallback", prebuilt_models={"fallback": fallback}, extensions=registry.build())
    state, _ = _state()
    journal = SimpleNamespace(record_middleware=Mock())
    runtime = SimpleNamespace(context={"__run_journal": journal})

    first = await _compact(middleware, state, True, runtime)

    assert first is not None
    attempts = len(primary.prompts) + len(fallback.prompts)
    assert attempts > 3 and len(observations) == attempts
    assert all(kind == SystemOperationKind.SUMMARIZATION for kind, _, _ in observations)
    assert sum(result.error is not None for _, _, result in observations) == 1
    assert [request.model_name for _, request, result in observations if result.error is not None] == ["primary"]
    assert [request.model_name for _, request, _ in observations].count("fallback") == 1
    assert all(len(request.messages) == 1 for _, request, _ in observations)
    assert journal.record_middleware.call_count == 1
    assert journal.record_middleware.call_args.kwargs["changes"]["call_count"] == 1
    assert journal.record_middleware.call_args.kwargs["changes"]["summarized_message_count"] == 2

    # The failed primary's fallback no-op was not cached. Prefix and suffix
    # cache hits must still allow that primary candidate to recover next time.
    second = await _compact(middleware, state, True, runtime)
    assert second is not None
    assert len(observations) == attempts + 1
    assert middleware.summary_skip_count == 0
    third = await _compact(middleware, state, True, runtime)
    assert third is not None
    assert len(observations) == attempts + 1
    assert middleware.summary_call_count == journal.record_middleware.call_count == 3
    assert middleware.summary_skip_count == 1
    assert journal.record_middleware.call_args.kwargs["changes"]["llm_call_skipped"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_pii_spanning_a_source_chunk_boundary_is_redacted_before_splitting(asynchronous):
    email = "boundary.user@example.com"
    state, selected = _state("x" * 60 + " " + email + " trailing evidence " * 10)
    source = get_buffer_string(selected)
    control_model = RecordingModel()
    control = _middleware(control_model, trim_tokens_to_summarize=80)
    assert await _compact(control, state, asynchronous) is not None
    first_edge = len(_sections(control_model.prompts[0])["new_messages"])
    assert source.index(email) < first_edge < source.index(email) + len(email), "the raw identifier must straddle a real model-input boundary"

    config = PiiRedactionConfig(enabled=True, token_secret="rolling-contract-test-secret-0123456789")
    model = RecordingModel()
    middleware = _middleware(model, trim_tokens_to_summarize=80, app_config=SimpleNamespace(pii_redaction=config))

    assert await _compact(middleware, state, asynchronous) is not None

    captured = _source(model.prompts)
    assert captured == redact_text(source, config)
    assert email not in captured
    assert "boundary.user" not in captured and "example.com" not in captured
    assert all(email not in prompt for prompt in model.prompts)
    replacement = redact_text(email, config)
    first_redacted_edge = len(_sections(model.prompts[0])["new_messages"])
    assert captured.index(replacement) < first_redacted_edge < captured.index(replacement) + len(replacement)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_default_approximate_counter_keeps_unicode_source_and_each_raw_budget(asynchronous):
    text = " ".join(f"条例{index:03d}：中文🦉e\u0301 <字段>& 完整记录" for index in range(100))
    state, selected = _state(text)
    model = RecordingModel()
    budget = 100
    middleware = _middleware(model, default_counter=True, trim_tokens_to_summarize=budget)

    result = await _compact(middleware, state, asynchronous)

    assert result is not None and len(model.prompts) > 1
    captured = _source(model.prompts)
    assert captured.encode("utf-8") == get_buffer_string(selected).encode("utf-8")
    assert "🦉e\u0301" in captured
    for prompt in model.prompts:
        raw = _sections(prompt)
        assert sum(middleware.token_counter([HumanMessage(content=section)]) for section in raw.values()) <= budget
    assert middleware.summary_call_count == 1
