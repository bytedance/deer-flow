from dataclasses import dataclass
import logging
from typing import Any, Iterable, override

from langchain.agents.middleware import SummarizationMiddleware as BaseSummarizationMiddleware
from langchain_core.messages.human import HumanMessage


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SummarizationEvent:
    """Payload emitted before summarization compacts historical messages."""

    thread_id: str | None
    messages_to_summarize: list[Any]
    preserved_messages: tuple[Any, ...] = ()
    agent_name: str | None = None
    runtime: Any | None = None


class SummarizationMiddleware(BaseSummarizationMiddleware):
    def __init__(self, *args: Any, before_summarization: Iterable[Any] | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._before_summarization_hooks = tuple(before_summarization or ())

    def _emit_before_summarization(
        self,
        *,
        messages_to_summarize: list[Any],
        preserved_messages: list[Any],
        runtime: Any,
    ) -> None:
        if not self._before_summarization_hooks:
            return

        context = getattr(runtime, "context", {}) or {}
        event = SummarizationEvent(
            thread_id=context.get("thread_id"),
            messages_to_summarize=messages_to_summarize,
            preserved_messages=tuple(preserved_messages),
            agent_name=context.get("agent_name"),
            runtime=runtime,
        )

        for hook in self._before_summarization_hooks:
            try:
                hook(event)
            except Exception:
                hook_name = getattr(hook, "__name__", repr(hook))
                logger.exception("before_summarization hook %s failed", hook_name)

    @override
    def before_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        messages = state["messages"]
        self._ensure_message_ids(messages)

        total_tokens = self.token_counter(messages)
        if not self._should_summarize(messages, total_tokens):
            return None

        cutoff_index = self._determine_cutoff_index(messages)
        if cutoff_index <= 0:
            return None

        messages_to_summarize, preserved_messages = self._partition_messages(messages, cutoff_index)
        self._emit_before_summarization(
            messages_to_summarize=messages_to_summarize,
            preserved_messages=preserved_messages,
            runtime=runtime,
        )

        summary = self._create_summary(messages_to_summarize)
        new_messages = self._build_new_messages(summary)

        return {"messages": [self._remove_all_message(), *new_messages, *preserved_messages]}

    @override
    async def abefore_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        messages = state["messages"]
        self._ensure_message_ids(messages)

        total_tokens = self.token_counter(messages)
        if not self._should_summarize(messages, total_tokens):
            return None

        cutoff_index = self._determine_cutoff_index(messages)
        if cutoff_index <= 0:
            return None

        messages_to_summarize, preserved_messages = self._partition_messages(messages, cutoff_index)
        self._emit_before_summarization(
            messages_to_summarize=messages_to_summarize,
            preserved_messages=preserved_messages,
            runtime=runtime,
        )

        summary = await self._acreate_summary(messages_to_summarize)
        new_messages = self._build_new_messages(summary)

        return {"messages": [self._remove_all_message(), *new_messages, *preserved_messages]}

    def _remove_all_message(self) -> Any:
        from langchain.agents.middleware.summarization import REMOVE_ALL_MESSAGES, RemoveMessage

        return RemoveMessage(id=REMOVE_ALL_MESSAGES)

    @override
    def _build_new_messages(self, summary: str) -> list[HumanMessage]:
        """Override the base implementation to let the human message with the special name 'summary'.
        And this message will be ignored to display in the frontend, but still can be used as context for the model.
        """
        return [HumanMessage(content=f"Here is a summary of the conversation to date:\n\n{summary}", name="summary")]


# Backward-compatible alias kept for tests and existing imports.
DeerFlowSummarizationMiddleware = SummarizationMiddleware
