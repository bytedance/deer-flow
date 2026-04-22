"""Callback assembly for runs execution."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from ..store import RunEventStore
from ..types import RunRecord
from .events import RunEventCallback
from .title import RunTitleCallback
from .tokens import RunCompletionData, RunTokenCallback


@dataclass
class RunCallbackArtifacts:
    """Callbacks plus handles used by the executor after callbacks run."""

    callbacks: list[BaseCallbackHandler]
    event_callback: RunEventCallback | None = None
    token_callback: RunTokenCallback | None = None
    title_callback: RunTitleCallback | None = None

    async def flush(self) -> None:
        for callback in self.callbacks:
            flush = getattr(callback, "flush", None)
            if flush is None:
                continue
            result = flush()
            if hasattr(result, "__await__"):
                await result

    def completion_data(self) -> RunCompletionData:
        if self.token_callback is None:
            return RunCompletionData()
        return self.token_callback.completion_data()

    def title(self) -> str | None:
        if self.title_callback is None:
            return None
        return self.title_callback.title()


def build_run_callbacks(
    *,
    record: RunRecord,
    graph_input: dict[str, Any],
    event_store: RunEventStore | None,
    existing_callbacks: Iterable[BaseCallbackHandler] = (),
) -> RunCallbackArtifacts:
    """Build execution callbacks for a run.

    Reference callbacks are intentionally not assembled here yet; they remain
    in the existing artifacts path until that integration is migrated.
    """
    callbacks = list(existing_callbacks)

    event_callback = None
    if event_store is not None:
        event_callback = RunEventCallback(
            run_id=record.run_id,
            thread_id=record.thread_id,
            event_store=event_store,
        )
        callbacks.append(event_callback)

    token_callback = RunTokenCallback(track_token_usage=True)
    _set_first_human_message(token_callback, graph_input)
    callbacks.append(token_callback)

    title_callback = RunTitleCallback()
    callbacks.append(title_callback)

    return RunCallbackArtifacts(
        callbacks=callbacks,
        event_callback=event_callback,
        token_callback=token_callback,
        title_callback=title_callback,
    )


def _set_first_human_message(token_callback: RunTokenCallback, graph_input: dict[str, Any]) -> None:
    messages = graph_input.get("messages")
    if not isinstance(messages, list) or not messages:
        return

    first = messages[0]
    content = _extract_first_human_text(first)
    if content:
        token_callback.set_first_human_message(content)


def _extract_first_human_text(message: Any) -> str | None:
    if isinstance(message, str):
        return message

    content = getattr(message, "content", None)
    if content is not None:
        return _extract_text_content(content)

    if isinstance(message, dict):
        return _extract_text_content(message.get("content"))

    return None


def _extract_text_content(content: Any) -> str | None:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
                continue
            if isinstance(item.get("content"), str):
                parts.append(item["content"])
        joined = "".join(parts).strip()
        return joined or None

    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
        nested = content.get("content")
        if isinstance(nested, str):
            return nested

    return None
