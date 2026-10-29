from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware, SummaryGenerationError

# A template shaped like a real custom prompt: the operator wants a JSON-shaped
# summary back, so the body carries literal braces alongside the {messages} slot.
_BRACE_TEMPLATE = 'Summarize as JSON: {"summary": "..."} {messages}'


class _NeverInvokedModel(BaseChatModel):
    """Fails loudly if the summary path reaches the model."""

    @property
    def _llm_type(self) -> str:
        return "never-invoked-test-chat-model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise AssertionError("the model must not be reached for an unrenderable template")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class _StaticChatModel(BaseChatModel):
    text: str = "ok"

    @property
    def _llm_type(self) -> str:
        return "static-test-chat-model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.outputs import ChatGeneration, ChatResult

        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.text))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _middleware(model, summary_prompt: str, **kwargs):
    options = {
        "trigger": ("messages", 4),
        "keep": ("messages", 2),
        "summary_prompt": summary_prompt,
        "token_counter": lambda ms: sum(len(str(m.content)) for m in ms),
        "trim_tokens_to_summarize": 9999,
    }
    options.update(kwargs)
    return DeerFlowSummarizationMiddleware(model=model, **options)


def _state() -> dict:
    return {
        "messages": [
            HumanMessage(content="a" * 50, id="h1"),
            AIMessage(content="b" * 50, id="a1"),
            HumanMessage(content="c" * 50, id="h2"),
            AIMessage(content="d" * 50, id="a2"),
        ],
        "summary_text": None,
    }


def _runtime():
    return SimpleNamespace(context={})


def test_brace_bearing_template_does_not_fail_the_run():
    """A literal brace in summary_prompt must not escape as a KeyError.

    The middleware documents that the automatic path swallows a summary failure
    and leaves compaction state unchanged. The render happens outside the
    generation try, so an unescaped brace used to propagate out of
    ``abefore_model`` and take the whole run down instead.
    """
    middleware = _middleware(_NeverInvokedModel(), _BRACE_TEMPLATE)

    result = middleware.compact_state(_state(), _runtime(), force=True)

    assert result is None


@pytest.mark.asyncio
async def test_brace_bearing_template_does_not_fail_the_run_async():
    middleware = _middleware(_NeverInvokedModel(), _BRACE_TEMPLATE)

    result = await middleware.acompact_state(_state(), _runtime(), force=True)

    assert result is None


def test_brace_bearing_template_reports_summary_generation_error_on_manual_compact():
    """/compact must see SummaryGenerationError, not a bare KeyError.

    ``raise_on_failure`` exists so a real failure is reported distinctly from
    "nothing to compact". A raw format exception bypasses that and surfaces as
    an internal error instead.
    """
    middleware = _middleware(_NeverInvokedModel(), _BRACE_TEMPLATE)

    with pytest.raises(SummaryGenerationError):
        middleware.compact_state(_state(), _runtime(), force=True, raise_on_failure=True)


@pytest.mark.asyncio
async def test_brace_bearing_template_reports_summary_generation_error_on_manual_compact_async():
    middleware = _middleware(_NeverInvokedModel(), _BRACE_TEMPLATE)

    with pytest.raises(SummaryGenerationError):
        await middleware.acompact_state(_state(), _runtime(), force=True, raise_on_failure=True)


def test_unrenderable_template_never_reaches_the_model():
    """A failed render must not fall through to a model call on a malformed prompt."""
    middleware = _middleware(_NeverInvokedModel(), _BRACE_TEMPLATE)

    assert middleware._build_summary_prompt([HumanMessage(content="hi", id="h1")], previous_summary=None) is None


def test_doubled_literal_braces_still_render():
    """The supported escape form must keep working, not get swallowed by the guard."""
    middleware = _middleware(_NeverInvokedModel(), 'JSON: {{"a": 1}} {messages}')

    prompt = middleware._build_summary_prompt([HumanMessage(content="hi", id="h1")], previous_summary=None)

    assert prompt is not None
    assert 'JSON: {"a": 1}' in prompt
    assert "hi" in prompt


def test_valid_template_still_compacts():
    """No regression: a well-formed template compacts and calls the model."""
    middleware = _middleware(_StaticChatModel(text="SUMMARY"), "{messages}")

    result = middleware.compact_state(_state(), _runtime(), force=True)

    assert result is not None
    assert result.summary_text == "SUMMARY"


def test_unknown_placeholder_is_treated_as_unrenderable():
    """A stray placeholder is the same class of failure as a literal brace."""
    middleware = _middleware(_NeverInvokedModel(), "{messages} {nope}")

    assert middleware._build_summary_prompt([HumanMessage(content="hi", id="h1")], previous_summary=None) is None
