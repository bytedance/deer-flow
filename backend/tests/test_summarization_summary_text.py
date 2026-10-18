from __future__ import annotations

import html
import re
from types import SimpleNamespace

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage, get_buffer_string
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from deerflow.agents.middlewares.dynamic_context_middleware import _DYNAMIC_CONTEXT_REMINDER_KEY
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware


def _char_count(messages) -> int:
    return sum(len(str(getattr(message, "content", ""))) for message in messages)


def _raising_count(messages) -> int:
    raise RuntimeError("token counter unavailable")


class _RaisingChatModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "raising-summary-test-chat-model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("summary model boom")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class _StaticChatModel(BaseChatModel):
    text: str = "COMPRESSED_SUMMARY"

    @property
    def _llm_type(self) -> str:
        return "static-summary-test-chat-model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.text))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class _RecordingSummaryModel(_StaticChatModel):
    prompts: list[str] = Field(default_factory=list)
    vary_responses: bool = False

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.prompts.append("\n".join(str(getattr(message, "content", message)) for message in messages))
        if self.vary_responses:
            # Coverage tests must observe each input rather than exercising the
            # separately tested exact-prompt/no-op cache with repetitive padding.
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=f"summary step {len(self.prompts)}"))])
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _big_history(n: int = 12) -> list:
    messages = []
    for i in range(n):
        messages.append(HumanMessage(content=f"user turn {i} " * 20))
        messages.append(AIMessage(content=f"assistant turn {i} " * 20))
    return messages


def _assert_complete_inputs(model, selected, budget=None) -> str:
    assert model.prompts
    captured = []
    for prompt in model.prompts:
        sections = re.findall(r"<(existing_summary|new_messages)>\n(.*?)\n</\1>", prompt, re.DOTALL)
        assert sections
        raw = [(name, html.unescape(body)) for name, body in sections]
        captured.extend(body for name, body in raw if name == "new_messages")
        if budget is not None:
            assert sum(len(body) for _, body in raw) <= budget
    new_text = "".join(captured)
    assert new_text == get_buffer_string(selected)
    return new_text


class TestSummaryFailureSafety:
    def test_summary_model_failure_does_not_destroy_history(self):
        middleware = DeerFlowSummarizationMiddleware(
            model=_RaisingChatModel(),
            trigger=("messages", 4),
            keep=("messages", 2),
            token_counter=len,
        )

        out = middleware._maybe_summarize({"messages": _big_history()}, None)

        assert out is None


class TestSummaryWritesChannel:
    @pytest.mark.parametrize("async_mode", [False, True])
    @pytest.mark.asyncio
    async def test_rescued_user_does_not_drop_earlier_tool_exchanges(self, async_mode):
        model = _RecordingSummaryModel()
        middleware = DeerFlowSummarizationMiddleware(
            model=model,
            trigger=("messages", 4),
            keep=("messages", 2),
            token_counter=_char_count,
            trim_tokens_to_summarize=4000,
        )
        user = HumanMessage(content="CURRENT_REQUEST", id="user")
        history = [user]
        for i in range(3):
            history.extend(
                [
                    AIMessage(content=f"PLAN_{i}", id=f"ai-{i}", tool_calls=[{"name": "bash", "args": {}, "id": f"call-{i}"}]),
                    ToolMessage(content=f"RESULT_{i}", id=f"tool-{i}", tool_call_id=f"call-{i}"),
                ]
            )
        runtime = SimpleNamespace(context={})
        if async_mode:
            result = await middleware.acompact_state({"messages": history}, runtime, force=True)
        else:
            result = middleware.compact_state({"messages": history}, runtime, force=True)

        assert result is not None
        assert user in result.preserved_messages
        assert list(result.messages_to_summarize) == history[1:5]
        new_text = _assert_complete_inputs(model, result.messages_to_summarize, 4000)
        for sentinel in ("PLAN_0", "RESULT_0", "PLAN_1", "RESULT_1"):
            assert sentinel in new_text
        assert "CURRENT_REQUEST" not in new_text
        assert "RESULT_2" not in new_text

    @pytest.mark.parametrize("async_mode", [False, True])
    @pytest.mark.parametrize("previous_summary", [None, "PRIOR_SUMMARY OLD_END"], ids=["without-summary", "with-summary"])
    @pytest.mark.parametrize("trim_limit", [120, None], ids=["bounded", "untrimmed"])
    @pytest.mark.asyncio
    async def test_oversized_rescued_user_window_keeps_recent_exchanges(self, async_mode, previous_summary, trim_limit):
        model = _RecordingSummaryModel()
        middleware = DeerFlowSummarizationMiddleware(
            model=model,
            trigger=("messages", 4),
            keep=("messages", 2),
            token_counter=_char_count,
            trim_tokens_to_summarize=trim_limit,
        )
        user = HumanMessage(content="CURRENT_REQUEST", id="user")
        history = [user]
        for i in range(7):
            history.extend(
                [
                    AIMessage(content=f"PLAN_{i}", id=f"ai-{i}", tool_calls=[{"name": "bash", "args": {}, "id": f"call-{i}"}]),
                    ToolMessage(content=f"RESULT_{i}", id=f"tool-{i}", tool_call_id=f"call-{i}"),
                ]
            )
        state = {"messages": history, "summary_text": previous_summary}
        runtime = SimpleNamespace(context={})
        if async_mode:
            result = await middleware.acompact_state(state, runtime, force=True)
        else:
            result = middleware.compact_state(state, runtime, force=True)

        assert result is not None
        assert user in result.preserved_messages
        assert list(result.messages_to_summarize) == history[1:13]
        new_text = _assert_complete_inputs(model, result.messages_to_summarize, trim_limit)
        assert "RESULT_5" in new_text
        for i in range(6):
            assert f"PLAN_{i}" in new_text
            assert f"RESULT_{i}" in new_text
        if trim_limit is None:
            assert len(model.prompts) == 1
            assert len(new_text) > 120
            if previous_summary:
                assert previous_summary in model.prompts[0]
        assert "CURRENT_REQUEST" not in new_text
        assert "RESULT_6" not in new_text
        if previous_summary:
            assert "OLD_END" in model.prompts[0]
        else:
            assert "PLAN_5" in new_text

    @pytest.mark.parametrize("async_mode", [False, True])
    @pytest.mark.asyncio
    async def test_mixed_history_covers_old_request_and_tool_results(self, async_mode):
        model = _RecordingSummaryModel(vary_responses=True)
        middleware = DeerFlowSummarizationMiddleware(
            model=model,
            trigger=("messages", 4),
            keep=("messages", 2),
            token_counter=_char_count,
            trim_tokens_to_summarize=120,
        )
        user = HumanMessage(content="CURRENT_REQUEST", id="user")
        history = [HumanMessage(content="OLD_REQUEST " + "x" * 1000, id="old-user"), user]
        for i in range(6):
            history.extend(
                [
                    AIMessage(content=f"PLAN_{i}", id=f"ai-{i}", tool_calls=[{"name": "bash", "args": {}, "id": f"call-{i}"}]),
                    ToolMessage(content=f"RESULT_{i}", id=f"tool-{i}", tool_call_id=f"call-{i}"),
                ]
            )
        runtime = SimpleNamespace(context={})
        if async_mode:
            result = await middleware.acompact_state({"messages": history}, runtime, force=True)
        else:
            result = middleware.compact_state({"messages": history}, runtime, force=True)

        assert result is not None
        assert list(result.messages_to_summarize) == [history[0], *history[2:12]]
        assert list(result.preserved_messages) == [user, *history[12:]]
        new_text = _assert_complete_inputs(model, result.messages_to_summarize, 120)
        assert "OLD_REQUEST " + "x" * 1000 in new_text
        for i in range(5):
            assert f"PLAN_{i}" in new_text
            assert f"RESULT_{i}" in new_text
        assert "CURRENT_REQUEST" not in new_text
        assert "RESULT_5" not in new_text

    def test_tool_source_coverage_applies_budget_before_escaping(self):
        model = _RecordingSummaryModel(vary_responses=True)
        middleware = DeerFlowSummarizationMiddleware(
            model=model,
            trigger=("messages", 4),
            keep=("messages", 2),
            token_counter=_char_count,
            trim_tokens_to_summarize=80,
        )
        selected = [
            AIMessage(content="read", id="plan", tool_calls=[{"name": "read_file", "args": {}, "id": "call"}]),
            ToolMessage(content="<" * 1000 + " TOOL_END", tool_call_id="call", id="tool"),
        ]
        tail = [HumanMessage(content="current", id="current"), AIMessage(content="recent", id="recent")]
        previous = "&" * 16 + " OLD_END"
        result = middleware.compact_state({"messages": [*selected, *tail], "summary_text": previous}, SimpleNamespace(context={}), force=True)

        assert result is not None
        assert list(result.messages_to_summarize) == selected
        assert list(result.preserved_messages) == tail
        new_text = _assert_complete_inputs(model, selected, 80)
        assert "TOOL_END" in new_text
        assert html.escape(previous, quote=False) in model.prompts[0]
        assert any("&lt;" in prompt for prompt in model.prompts)
        encoded_sections = [re.findall(r"<(existing_summary|new_messages)>\n(.*?)\n</\1>", prompt, re.DOTALL) for prompt in model.prompts]
        assert any(sum(len(body) for _, body in sections) > 80 for sections in encoded_sections)

    def _middleware(self) -> DeerFlowSummarizationMiddleware:
        return DeerFlowSummarizationMiddleware(
            model=_StaticChatModel(text="COMPRESSED_SUMMARY"),
            trigger=("messages", 4),
            keep=("messages", 2),
            token_counter=len,
        )

    def test_summary_goes_to_summary_text_not_messages(self):
        out = self._middleware()._maybe_summarize({"messages": _big_history()}, None)

        assert out is not None
        assert out["summary_text"] == "COMPRESSED_SUMMARY"
        injected = [message for message in out["messages"] if isinstance(message, HumanMessage) and message.name == "summary"]
        assert injected == []
        assert any(isinstance(message, RemoveMessage) for message in out["messages"])

    def test_empty_summary_window_after_rescue_does_not_overwrite_existing_summary(self):
        middleware = DeerFlowSummarizationMiddleware(
            model=_StaticChatModel(text="SHOULD_NOT_BE_USED"),
            trigger=("messages", 2),
            keep=("messages", 1),
            token_counter=len,
        )
        reminder = SystemMessage(
            content="<system-reminder>date</system-reminder>",
            additional_kwargs={_DYNAMIC_CONTEXT_REMINDER_KEY: True},
        )
        out = middleware._maybe_summarize(
            {
                "messages": [
                    reminder,
                    HumanMessage(content="latest user message"),
                ],
                "summary_text": "EXISTING_SUMMARY",
            },
            None,
        )

        assert out is None

    def test_existing_summary_is_included_when_creating_next_summary(self):
        model = _RecordingSummaryModel(text="UPDATED_SUMMARY")
        middleware = DeerFlowSummarizationMiddleware(
            model=model,
            trigger=("messages", 4),
            keep=("messages", 2),
            token_counter=len,
        )

        out = middleware._maybe_summarize(
            {
                "messages": _big_history(),
                "summary_text": "OLD_SUMMARY_SENTINEL",
            },
            None,
        )

        assert out is not None
        assert out["summary_text"] == "UPDATED_SUMMARY"
        assert model.prompts
        assert "OLD_SUMMARY_SENTINEL" in model.prompts[-1]

    def test_summary_text_counts_toward_summarization_trigger(self):
        middleware = DeerFlowSummarizationMiddleware(
            model=_StaticChatModel(text="UPDATED_SUMMARY"),
            trigger=("tokens", 80),
            keep=("messages", 2),
            token_counter=_char_count,
        )

        out = middleware._maybe_summarize(
            {
                "messages": [
                    HumanMessage(content="old"),
                    AIMessage(content="older"),
                    HumanMessage(content="latest"),
                ],
                "summary_text": "S" * 120,
            },
            None,
        )

        assert out is not None
        assert out["summary_text"] == "UPDATED_SUMMARY"

    def test_compact_state_force_ignores_trigger_threshold(self):
        middleware = DeerFlowSummarizationMiddleware(
            model=_StaticChatModel(text="FORCED_SUMMARY"),
            trigger=("messages", 100),
            keep=("messages", 2),
            token_counter=len,
        )

        result = middleware.compact_state({"messages": _big_history(3)}, SimpleNamespace(context={}), force=True)

        assert result is not None
        assert result.summary_text == "FORCED_SUMMARY"
        assert len(result.preserved_messages) == 2
        assert len(result.messages_to_summarize) > 0

    def test_single_prompt_builder_rejects_previous_summary_requiring_clipping(self):
        middleware = DeerFlowSummarizationMiddleware(
            model=_StaticChatModel(text="UPDATED_SUMMARY"),
            trigger=("messages", 4),
            keep=("messages", 2),
            token_counter=_char_count,
            trim_tokens_to_summarize=80,
        )
        previous_summary = "OLD_SUMMARY_START " + ("S" * 240) + " OLD_SUMMARY_END"

        prompt = middleware._build_summary_prompt(
            [HumanMessage(content="NEW_MESSAGE_SENTINEL " + ("N" * 240))],
            previous_summary=previous_summary,
        )

        assert prompt is None

    def test_single_prompt_builder_rejects_source_exceeding_budget(self):
        middleware = DeerFlowSummarizationMiddleware(
            model=_StaticChatModel(text="UPDATED_SUMMARY"),
            trigger=("messages", 4),
            keep=("messages", 2),
            token_counter=_char_count,
            trim_tokens_to_summarize=40,
        )

        body = middleware._build_summary_input_text("Human: NEW_MESSAGE_SENTINEL " + ("N" * 200))

        assert body is None

    @pytest.mark.parametrize("async_mode", [False, True])
    @pytest.mark.asyncio
    async def test_summary_input_counter_failure_preserves_complete_sources(self, async_mode):
        def counter(messages):
            if len(messages) == 1 and isinstance(messages[0], HumanMessage):
                return _raising_count(messages)
            return _char_count(messages)

        model = _RecordingSummaryModel(vary_responses=True)
        middleware = DeerFlowSummarizationMiddleware(
            model=model,
            trigger=("messages", 4),
            keep=("messages", 2),
            token_counter=counter,
            trim_tokens_to_summarize=90,
        )
        history = _big_history(4)
        state = {"messages": history, "summary_text": "PRIOR_SUMMARY"}
        runtime = SimpleNamespace(context={})
        result = await middleware.acompact_state(state, runtime, force=True) if async_mode else middleware.compact_state(state, runtime, force=True)

        assert result is not None
        assert list(result.messages_to_summarize) == history[:-2]
        assert list(result.preserved_messages) == history[-2:]
        _assert_complete_inputs(model, result.messages_to_summarize, 90)
