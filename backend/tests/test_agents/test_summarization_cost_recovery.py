"""Cost guards and recoverable carries must never truncate selected source."""

from __future__ import annotations

import copy
import html
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, get_buffer_string
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from deerflow.agents.middlewares.pii_redaction_middleware import redact_text
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware, SummaryGenerationError
from deerflow.config.pii_redaction_config import PiiRedactionConfig
from deerflow.config.task_continuity_config import TaskContinuityConfig


def _text(length):
    return " ".join(f"evidence_{index:05d} remains relevant" for index in range(length // 20 + 2))[:length]


class FreeModel(BaseChatModel):
    reply: str = "S"
    hard_limit: int = 70
    prompts: list[str] = Field(default_factory=list)
    guard_hits: int = 0

    @property
    def _llm_type(self):
        return "free-cost-recovery-regression"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if len(self.prompts) >= self.hard_limit:
            self.guard_hits += 1
            raise RuntimeError("free regression model call limit reached")
        self.prompts.append("\n".join(str(message.content) for message in messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.reply))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class CountingChars:
    def __init__(self):
        self.input_characters = 0

    def __call__(self, messages):
        length = sum(len(message.content) for message in messages)
        self.input_characters += length
        return length


def _middleware(model, *, budget=512, default_counter=False, **kwargs):
    options = {
        "model": model,
        "trigger": ("messages", 4),
        "keep": ("messages", 2),
        "trim_tokens_to_summarize": budget,
        "summary_prompt": "{messages}",
        "anchor_model_name": "offline",
        "run_model_name": "offline",
    }
    if not default_counter:
        options["token_counter"] = CountingChars()
    options.update(kwargs)
    return DeerFlowSummarizationMiddleware(**options)


def _state(text, previous=None):
    selected = [HumanMessage(content=text, id="old-user"), AIMessage(content="old answer", id="old-ai")]
    state = {
        "messages": [*selected, HumanMessage(content="current request", id="current-user"), AIMessage(content="current answer", id="current-ai")],
        "summary_text": previous,
    }
    return state, selected


def _sections(prompt):
    return {name: html.unescape(body) for name, body in re.findall(r"<(existing_summary|new_messages)>\n(.*?)\n</\1>", prompt, re.DOTALL)}


def _assert_full_source_and_budget(model, selected, counter, budget, pii=None):
    sections = [_sections(prompt) for prompt in model.prompts]
    source = "".join(part["new_messages"] for part in sections)
    assert source == redact_text(get_buffer_string(selected), pii)
    for part in sections:
        assert sum(counter([HumanMessage(content=text)]) for text in part.values()) <= budget


def _assert_shortened(text, start, end):
    assert text.startswith(start) and text.endswith(end)
    assert re.search(r"shorten|truncat|omitt|缩短|省略|截断", text, re.IGNORECASE), "summary shortening needs an explicit marker"


async def _compact(middleware, state, asynchronous):
    runtime = SimpleNamespace(context={})
    return await middleware.acompact_state(state, runtime, force=True) if asynchronous else middleware.compact_state(state, runtime, force=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_near_budget_carry_recovers_with_default_counter_and_complete_source(asynchronous):
    model = FreeModel(hard_limit=8)
    middleware = _middleware(model, budget=4000, default_counter=True)
    # Default approximate counter, not a custom tiny-budget token model.
    low, high, previous = 0, 32000, ""
    while low <= high:
        middle = (low + high) // 2
        candidate = _text(middle)
        if middleware.token_counter([HumanMessage(content=candidate)]) <= 3990:
            previous, low = candidate, middle + 1
        else:
            high = middle - 1
    assert middleware.token_counter([HumanMessage(content=previous)]) == 3990
    model.reply = previous
    state, selected = _state(_text(780), previous)

    result = await _compact(middleware, state, asynchronous)

    assert result is not None, "a verbose carry must not consume all useful source progress"
    assert model.guard_hits == 0 and len(model.prompts) <= 4
    assert middleware.token_counter([HumanMessage(content=result.summary_text)]) <= 2000
    _assert_full_source_and_budget(model, selected, middleware.token_counter, 4000)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("manual", [False, True], ids=["automatic", "manual"])
async def test_64_chunk_policy_aborts_without_committing_any_partial_result(monkeypatch, asynchronous, manual):
    from deerflow.agents.middlewares import summarization_middleware as module
    from deerflow.agents.task_continuity import archive

    budget = 128
    model = FreeModel(hard_limit=70)
    hook = Mock()
    observed = Mock()
    capture, acapture = Mock(), AsyncMock()
    monkeypatch.setattr(module, "notify_context_compacted", observed)
    monkeypatch.setattr(archive, "capture", capture)
    monkeypatch.setattr(archive, "acapture", acapture)
    middleware = _middleware(model, budget=budget, before_summarization=[hook], task_continuity_config=TaskContinuityConfig(enabled=True))
    state, selected = _state(_text(budget * 80), "S")
    state["task_history"] = {"already": "captured"}
    original = copy.deepcopy(state)
    assert len(get_buffer_string(selected)) > 64 * budget
    runtime = SimpleNamespace(context={})

    if manual:
        with pytest.raises(SummaryGenerationError):
            if asynchronous:
                await middleware.acompact_state(state, runtime, force=True, raise_on_failure=True)
            else:
                middleware.compact_state(state, runtime, force=True, raise_on_failure=True)
    else:
        result = await middleware.abefore_model(state, runtime) if asynchronous else middleware.before_model(state, runtime)
        assert result is None

    # The fake has its own independent 70-call stop to keep a broken product
    # guard free and bounded; hitting that fake stop is NOT passing this test.
    assert 0 < len(model.prompts) <= 64
    assert model.guard_hits == 0
    assert state == original
    assert middleware.summary_call_count == middleware.summary_noop_count == middleware.summary_skip_count == 0
    hook.assert_not_called()
    observed.assert_not_called()
    capture.assert_not_called()
    acapture.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_final_generated_summary_is_shortened_and_next_turn_can_compact(asynchronous):
    reply = "GENERATED_START " + _text(1400) + " GENERATED_END"
    model = FreeModel(reply=reply)
    middleware = _middleware(model)
    state, selected = _state("a short older request")

    first = await _compact(middleware, state, asynchronous)

    assert first is not None
    assert middleware.token_counter([HumanMessage(content=first.summary_text)]) <= 256
    _assert_shortened(first.summary_text, "GENERATED_START", "GENERATED_END")
    _assert_full_source_and_budget(model, selected, middleware.token_counter, 512)
    followup = {
        "messages": [*first.preserved_messages, HumanMessage(content="next request", id="next-user"), AIMessage(content="next answer", id="next-ai")],
        "summary_text": first.summary_text,
    }
    model.reply = "S"
    calls_before = len(model.prompts)
    second = await _compact(middleware, followup, asynchronous)
    assert second is not None and len(model.prompts) > calls_before
    assert middleware.summary_call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_oversized_legacy_summary_recovers_without_clipping_new_source(asynchronous):
    previous = "LEGACY_START " + _text(1500) + " LEGACY_END"
    model = FreeModel(reply="A compact carry")
    middleware = _middleware(model)
    state, selected = _state(_text(2400), previous)

    result = await _compact(middleware, state, asynchronous)

    assert result is not None and model.guard_hits == 0
    first_carry = _sections(model.prompts[0])["existing_summary"]
    assert middleware.token_counter([HumanMessage(content=first_carry)]) <= 256
    _assert_shortened(first_carry, "LEGACY_START", "LEGACY_END")
    _assert_full_source_and_budget(model, selected, middleware.token_counter, 512)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_shortening_preserves_unicode_ends_and_redacts_pii_before_slicing(asynchronous):
    pii = PiiRedactionConfig(enabled=True, token_secret="carry-shortening-test-secret-0123456789")
    previous = "LEGACY_START中🦉e\u0301 alice@example.com " + "中文<字段>& " * 180 + " bob@example.org LEGACY_END火🦊"
    reply = "GENERATED_START中🦉e\u0301 " + "摘要<内容>& " * 180 + " GENERATED_END火🦊"
    model = FreeModel(reply=reply)
    middleware = _middleware(model, app_config=SimpleNamespace(pii_redaction=pii))
    state, selected = _state("source contact source.person@example.net " + "完整事实🧭<项目>& " * 120, previous)

    result = await _compact(middleware, state, asynchronous)

    assert result is not None and model.guard_hits == 0
    result.summary_text.encode("utf-8")
    _assert_shortened(result.summary_text, "GENERATED_START中🦉e\u0301", "GENERATED_END火🦊")
    _assert_shortened(_sections(model.prompts[0])["existing_summary"], "LEGACY_START中🦉e\u0301", "LEGACY_END火🦊")
    assert all(email not in prompt for email in ("alice@example.com", "bob@example.org", "source.person@example.net") for prompt in model.prompts)
    _assert_full_source_and_budget(model, selected, middleware.token_counter, 512, pii)


@pytest.mark.asyncio
async def test_unbounded_budget_keeps_full_carry_and_uses_one_step():
    previous = "LEGACY_START " + _text(1500) + " LEGACY_END"
    reply = "GENERATED_START " + _text(2000) + " GENERATED_END"
    model = FreeModel(reply=reply)
    middleware = _middleware(model, budget=None)
    state, selected = _state(_text(2400), previous)

    result = await _compact(middleware, state, True)

    assert result is not None and result.summary_text == reply
    assert len(model.prompts) == 1
    assert _sections(model.prompts[0])["existing_summary"] == previous
    assert _sections(model.prompts[0])["new_messages"] == get_buffer_string(selected)


@pytest.mark.asyncio
async def test_counter_input_work_grows_with_source_without_full_suffix_rescans():
    work = []
    for length in (2048, 8192):
        counter = CountingChars()
        model = FreeModel(reply="short carry")
        middleware = _middleware(model, token_counter=counter)
        state, selected = _state(_text(length), "S")
        result = await _compact(middleware, state, True)
        assert result is not None and model.guard_hits == 0
        input_characters = counter.input_characters
        _assert_full_source_and_budget(model, selected, CountingChars(), 512)
        work.append(input_characters)
    # Four times the source may have fixed overhead and chunk-boundary effects;
    # allow generous slack, while rejecting the old full-suffix quadratic term.
    assert work[1] <= work[0] * 5.5, f"counter input work grew superlinearly: {work}"


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_exactly_64_chunks_can_finish_with_an_extra_fallback_attempt(asynchronous):
    class FailFirstModel(FreeModel):
        failed: bool = False

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if not self.failed:
                self.failed = True
                self.prompts.append("\n".join(str(message.content) for message in messages))
                raise RuntimeError("one primary attempt needs the configured fallback")
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    primary, fallback = FailFirstModel(), FreeModel()
    budget = 64
    middleware = _middleware(primary, budget=budget, anchor_model_name="primary", configured_model_name="primary", run_model_name="fallback", prebuilt_models={"fallback": fallback})
    # A full one-character carry leaves 63 source characters per bounded call.
    # A single serialized line avoids optional newline boundary adjustments.
    text = _text((budget - 1) * 64 - len("Human: "))
    selected = [HumanMessage(content=text, id="old-user")]
    state = {"messages": [*selected, HumanMessage(content="current", id="current-user"), AIMessage(content="recent", id="current-ai")], "summary_text": "S"}
    assert len(get_buffer_string(selected)) == (budget - 1) * 64

    result = await _compact(middleware, state, asynchronous)

    assert result is not None, "the 64th completed chunk is permitted; the guard applies before a 65th chunk"
    assert len(primary.prompts) == 64
    assert len(fallback.prompts) == 1
    assert primary.guard_hits == fallback.guard_hits == 0
    assert fallback.prompts[0] == primary.prompts[0]
    _assert_full_source_and_budget(primary, selected, middleware.token_counter, budget)
    assert middleware.summary_call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_clamped_noop_cache_skips_calls_without_claiming_original_summary_unchanged(asynchronous):
    previous = "LEGACY_START " + _text(1400) + " LEGACY_END"
    model = FreeModel(reply=previous)
    middleware = _middleware(model)
    state, _ = _state("selected source remains present until a successful commit", previous)
    original = copy.deepcopy(state)

    first = await _compact(middleware, state, asynchronous)
    assert first is not None and first.summary_text != previous
    assert len(model.prompts) == 1
    assert middleware.summary_noop_count == middleware.summary_skip_count == 0

    second = await _compact(middleware, state, asynchronous)
    assert second is not None and second.summary_text == first.summary_text
    assert len(model.prompts) == 1
    assert middleware.summary_skip_count == 1
    assert middleware.summary_noop_count == 0, "cache reuse did not preserve the original oversized summary byte-for-byte"
    assert state == original

    changed = copy.deepcopy(state)
    changed["messages"][0] = changed["messages"][0].model_copy(update={"content": "a newly selected source"})
    third = await _compact(middleware, changed, asynchronous)
    assert third is not None
    assert len(model.prompts) == 2
    assert _sections(model.prompts[-1])["new_messages"] == get_buffer_string(changed["messages"][:2])
    assert middleware.summary_call_count == 3
    assert middleware.summary_skip_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_weighted_unicode_counter_can_exceed_character_count_without_losing_source(asynchronous):
    def weighted_tokens(messages):
        return sum(1 if character.isascii() else 5 for message in messages for character in message.content)

    # Unique numeric labels ensure every source fragment has a distinct prompt,
    # so no-op cache reuse cannot hide repeated source from the model recorder.
    text = " ".join(f"{index:03d}中🦉e\u0301火<{index:03d}>&" for index in range(40))
    state, selected = _state(text, "S")
    serialized = get_buffer_string(selected)
    assert weighted_tokens([HumanMessage(content=serialized)]) > len(serialized)
    assert weighted_tokens([HumanMessage(content="中🦉e\u0301火")]) > len("中🦉e\u0301火")
    model = FreeModel()
    budget = 256
    middleware = _middleware(model, budget=budget, token_counter=weighted_tokens)

    result = await _compact(middleware, state, asynchronous)

    assert result is not None and model.guard_hits == 0
    assert len(model.prompts) > 1
    assert len(set(model.prompts)) == len(model.prompts)
    _assert_full_source_and_budget(model, selected, weighted_tokens, budget)
    assert weighted_tokens([HumanMessage(content=result.summary_text)]) <= budget // 2
