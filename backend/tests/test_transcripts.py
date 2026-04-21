from __future__ import annotations

from dataclasses import dataclass

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.gateway.transcripts import append_thread_transcript_messages, get_thread_transcript


@dataclass
class StoreItem:
    value: dict


class FakeStore:
    def __init__(self) -> None:
        self.items: dict[tuple[tuple[str, ...], str], dict] = {}

    async def aget(self, namespace: tuple[str, ...], key: str):
        value = self.items.get((namespace, key))
        return StoreItem(value=value) if value is not None else None

    async def aput(self, namespace: tuple[str, ...], key: str, value: dict) -> None:
        self.items[(namespace, key)] = value


@pytest.mark.anyio
async def test_transcript_appends_visible_messages_and_deduplicates() -> None:
    store = FakeStore()
    messages = [
        HumanMessage(id="human-1", content="hello"),
        AIMessage(id="ai-1", content="hi"),
        ToolMessage(id="tool-1", content="ok", tool_call_id="call-1"),
    ]

    await append_thread_transcript_messages(store, "thread-1", messages)
    await append_thread_transcript_messages(store, "thread-1", messages)

    transcript = await get_thread_transcript(store, "thread-1")

    assert [message["id"] for message in transcript] == ["human-1", "ai-1", "tool-1"]
    assert [message["type"] for message in transcript] == ["human", "ai", "tool"]


@pytest.mark.anyio
async def test_transcript_filters_hidden_and_summary_messages() -> None:
    store = FakeStore()

    await append_thread_transcript_messages(
        store,
        "thread-1",
        [
            HumanMessage(content="visible"),
            HumanMessage(
                content="hidden",
                additional_kwargs={"hide_from_ui": True},
            ),
            HumanMessage(
                content="summary",
                additional_kwargs={"deerflow_conversation_summary": True},
            ),
            HumanMessage(content="Here is a summary of the conversation to date: old"),
        ],
    )

    transcript = await get_thread_transcript(store, "thread-1")

    assert [message["content"] for message in transcript] == ["visible"]


@pytest.mark.anyio
async def test_transcript_deduplicates_submitted_message_after_checkpoint_assigns_id() -> None:
    store = FakeStore()

    await append_thread_transcript_messages(store, "thread-1", [HumanMessage(content="same question")])
    await append_thread_transcript_messages(store, "thread-1", [HumanMessage(id="human-1", content="same question")])

    transcript = await get_thread_transcript(store, "thread-1")

    assert [message["content"] for message in transcript] == ["same question"]
