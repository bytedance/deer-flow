"""Derived run summaries exclude leading reasoning without rewriting messages."""

from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_openai import ChatOpenAI

from app.scheduler.notification_text import render_notification_text
from deerflow.persistence.scheduled_task_runs.sql import run_summary
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal

ANSWER = "The release checklist is complete."


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (f"<think>Compare candidates.</think>{ANSWER}", ANSWER),
        (f"\n<think>\nCompare candidates.\n</think>\n{ANSWER}", ANSWER),
        (f'<THINK class="reasoning">Compare candidates.</THINK >\n{ANSWER}', ANSWER),
        (f"<think>First.</think>\n<think>Second.</think>\n{ANSWER}", ANSWER),
        (f"<think>First.</think>    <think>Second.</think>{ANSWER}", ANSWER),
        ("<think>" + "r" * 2400 + f"</think>\n{ANSWER}", ANSWER),
        ("<think>Only reasoning.</think>", None),
        ("<think>Unfinished reasoning.", None),
        ("<think", None),
        (ANSWER, ANSWER),
        ("```xml\n<think>literal example</think>\n```", "```xml\n<think>literal example</think>\n```"),
        ("`<think>literal example</think>`", "`<think>literal example</think>`"),
        ("Use <think>literal example</think> in this document.", "Use <think>literal example</think> in this document."),
        ("    <think>indented code</think>", "<think>indented code</think>"),
        ("<thinker>ordinary XML</thinker>", "<thinker>ordinary XML</thinker>"),
        ("<think>Reasoning.</think>\n`<think>literal example</think>`", "`<think>literal example</think>`"),
        ([{"type": "text", "text": "<think>Reasoning.</think>"}, {"type": "text", "text": ANSWER}], ANSWER),
        (f"<think>Reasoning.</think>{'a' * 2500}", "a" * 2000),
    ],
    ids=[
        "short",
        "multiline",
        "attributes",
        "two-blocks",
        "same-line-blocks",
        "long-reasoning",
        "only-reasoning",
        "unclosed",
        "partial-tag",
        "plain",
        "fenced-literal",
        "inline-literal",
        "prose-literal",
        "indented-literal",
        "not-tag",
        "literal-after-reasoning",
        "content-blocks",
        "long-answer",
    ],
)
async def test_visible_summary_preserves_original_response(content, expected):
    store = MemoryRunEventStore()
    journal = RunJournal("run-visible", "thread-visible", store)
    message = AIMessage(content=content, usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    original = message.model_dump()
    journal.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=uuid4(), tags=["lead_agent"])
    await journal.flush()

    completion = journal.get_completion_data()
    assert completion["last_ai_message"] == expected
    assert completion["message_count"] == 1
    assert completion["total_tokens"] == 15
    events = await store.list_events("thread-visible", "run-visible")
    response = next(event for event in events if event["event_type"] == "llm.ai.response")
    assert response["content"]["content"] == content
    assert message.model_dump() == original


@pytest.mark.anyio
async def test_thought_only_response_keeps_previous_useful_summary():
    journal = RunJournal("run-visible", "thread-visible", MemoryRunEventStore())
    for content in (ANSWER, "<think>Unfinished reasoning."):
        journal.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content=content))]]), run_id=uuid4(), tags=["lead_agent"])
        await journal.flush()
    assert journal.get_completion_data()["last_ai_message"] == ANSWER
    assert journal.get_completion_data()["message_count"] == 2


@pytest.mark.anyio
async def test_openai_compatible_reply_reaches_notice_without_inline_reasoning():
    content = "<think>" + "r" * 2400 + f"</think>\n{ANSWER}"
    requests = []

    def respond(request):
        assert request.method == "POST" and request.url.path == "/v1/chat/completions"
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "offline-response",
                "object": "chat.completion",
                "created": 0,
                "model": "reasoning-model",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    store = MemoryRunEventStore()
    journal = RunJournal("run-visible", "thread-visible", store)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(model="reasoning-model", api_key="offline-test-key", base_url="https://model.invalid/v1", http_async_client=client)
        message = await model.ainvoke([HumanMessage(content="Check the release checklist")], config={"callbacks": [journal], "tags": ["lead_agent"]})
    await journal.flush()
    summary = journal.get_completion_data()["last_ai_message"]
    notice = render_notification_text({"event": "run_completed", "run_id": "run-visible", "payload": {"run_status": "success", "task_title": "Check release", "result_summary": run_summary(summary)}})

    assert len(requests) == 1
    assert message.content == content
    assert run_summary(summary) == ANSWER
    assert f"Result: {ANSWER}" in notice
    assert "<think>" not in notice and "rrrr" not in notice
    events = await store.list_events("thread-visible", "run-visible")
    assert any(event["content"].get("content") == content for event in events if event["event_type"] == "llm.ai.response")
