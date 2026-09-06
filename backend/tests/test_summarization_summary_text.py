from __future__ import annotations

from types import SimpleNamespace

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage
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

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.prompts.append("\n".join(str(getattr(message, "content", message)) for message in messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _big_history(n: int = 12) -> list:
    messages = []
    for i in range(n):
        messages.append(HumanMessage(content=f"user turn {i} " * 20))
        messages.append(AIMessage(content=f"assistant turn {i} " * 20))
    return messages


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

    def test_previous_summary_is_trimmed_with_summary_prompt_input(self):
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

        assert prompt is not None
        assert previous_summary not in prompt
        assert "NEW_MESSAGE_SENTINEL" in prompt

    def test_new_message_summary_prompt_trim_uses_token_counter_budget(self):
        middleware = DeerFlowSummarizationMiddleware(
            model=_StaticChatModel(text="UPDATED_SUMMARY"),
            trigger=("messages", 4),
            keep=("messages", 2),
            token_counter=_char_count,
            trim_tokens_to_summarize=40,
        )

        body = middleware._build_summary_input_text("Human: NEW_MESSAGE_SENTINEL " + ("N" * 200))

        assert body is not None
        new_messages = body.split("<new_messages>\n", 1)[1].split("\n</new_messages>", 1)[0]
        assert len(new_messages) <= 40
        assert "NEW_MESSAGE_SENTINEL" in new_messages

    def test_summary_prompt_fallback_bound_respects_small_budget(self):
        middleware = DeerFlowSummarizationMiddleware(
            model=_StaticChatModel(text="UPDATED_SUMMARY"),
            trigger=("messages", 4),
            keep=("messages", 2),
            token_counter=_raising_count,
            trim_tokens_to_summarize=2,
        )

        text = middleware._trim_summary_section_text("abcdef", 2, strategy="first")

        assert len(text) <= 2
