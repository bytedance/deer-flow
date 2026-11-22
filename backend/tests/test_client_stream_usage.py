"""Embedded stream usage must match LangChain's assembled message usage."""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from test_client import client as client
from test_client import mock_app_config as mock_app_config


@pytest.mark.parametrize(("last_text", "initial_input"), [(" world", 10), ("", 10), (" world", 12)])
def test_stream_accounts_native_gemini_usage(client, last_text, initial_input):
    from google.genai.types import Candidate, Content, GenerateContentResponse, GenerateContentResponseUsageMetadata, Part
    from langchain.agents import create_agent
    from langchain_google_genai import ChatGoogleGenerativeAI

    model = ChatGoogleGenerativeAI(model="gemini-2.5-flash", api_key="offline-placeholder")
    responses = [
        GenerateContentResponse(
            candidates=[Candidate(content=Content(role="model", parts=[Part(text=text)]), finish_reason="STOP" if index else None)],
            usage_metadata=GenerateContentResponseUsageMetadata(prompt_token_count=inputs, candidates_token_count=outputs, total_token_count=inputs + outputs),
        )
        for index, (text, inputs, outputs) in enumerate([("Hello", initial_input, 1), (last_text, 10, 4)])
    ]
    try:
        # Only replace the SDK transport; retain the real adapter and graph.
        with (
            patch.object(model.client.models, "generate_content_stream", return_value=iter(responses)) as transport,
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", create_agent(model, tools=[])),
        ):
            events = list(client.stream("Say hello", thread_id="gemini-usage"))
        transport.assert_called_once()
    finally:
        model.client.close()

    expected = {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}
    final_values = [event for event in events if event.type == "values"][-1]
    assembled = final_values.data["messages"][-1]
    assert {key: assembled["usage_metadata"][key] for key in expected} == expected
    assert assembled["content"] == "Hello" + last_text
    assert "".join(event.data["content"] for event in events if event.type == "messages-tuple") == assembled["content"]
    assert events[-1].type == "end"
    assert events[-1].data["usage"] == expected


@pytest.mark.parametrize("provider", ["openai", "vllm"])
def test_stream_accounts_openai_compatible_usage(client, provider):
    from langchain.agents import create_agent
    from langchain_openai import ChatOpenAI

    from deerflow.models.vllm_provider import VllmChatModel

    model_class = VllmChatModel if provider == "vllm" else ChatOpenAI
    model = model_class(
        model="offline-model",
        api_key="offline-placeholder",
        use_responses_api=False,
        stream_usage=True,
        **({"cumulative_stream_usage": True} if provider == "vllm" else {}),
    )
    responses = [
        {
            "id": "chatcmpl-usage",
            "model": "offline-model",
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": "stop" if index else None}],
            "usage": {"prompt_tokens": 10, "completion_tokens": output, "total_tokens": 10 + output} if provider == "vllm" else None,
        }
        for index, (text, output) in enumerate([("Hello", 1), (" world", 4)])
    ]
    responses.append(
        {
            "id": "chatcmpl-usage",
            "model": "offline-model",
            "choices": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        }
    )
    response_stream = MagicMock()
    response_stream.__enter__.return_value = iter(responses)
    try:
        with (
            patch.object(model.client, "create", return_value=response_stream) as transport,
            patch.object(client, "_ensure_agent"),
            patch.object(client, "_agent", create_agent(model, tools=[])),
        ):
            events = list(client.stream("Say hello", thread_id=f"{provider}-usage"))
        transport.assert_called_once()
    finally:
        model.root_client.close()

    expected = {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}
    assembled = [event for event in events if event.type == "values"][-1].data["messages"][-1]
    assert {key: assembled["usage_metadata"][key] for key in expected} == expected
    assert assembled["content"] == "Hello world"
    assert "".join(event.data["content"] for event in events if event.type == "messages-tuple") == "Hello world"
    assert events[-1].type == "end"
    assert events[-1].data["usage"] == expected


@pytest.mark.parametrize("include_snapshots", [False, True])
def test_stream_sums_usage_deltas_per_message(client, include_snapshots):
    chunks = [
        AIMessageChunk(id="a", content="A", usage_metadata={"input_tokens": 10, "output_tokens": 1, "total_tokens": 11}),
        AIMessageChunk(id="b", content="B", usage_metadata={"input_tokens": 20, "output_tokens": 2, "total_tokens": 22}),
        AIMessageChunk(id="a", content="C", usage_metadata={"input_tokens": 0, "output_tokens": 3, "total_tokens": 3}),
        AIMessageChunk(id="b", content="", usage_metadata={"input_tokens": 0, "output_tokens": 4, "total_tokens": 4}),
    ]
    items = [("messages", (chunk, {})) for chunk in chunks]
    if include_snapshots:
        messages = [
            AIMessage(id="a", content="AC", usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}),
            AIMessage(id="b", content="B", usage_metadata={"input_tokens": 20, "output_tokens": 6, "total_tokens": 26}),
        ]
        items.extend([("values", {"messages": messages}), ("values", {"messages": [message.model_copy() for message in messages]})])
    agent = MagicMock()
    agent.stream.return_value = iter(items)
    with patch.object(client, "_ensure_agent"), patch.object(client, "_agent", agent):
        events = list(client.stream("hi"))

    assert events[-1].data["usage"] == {"input_tokens": 30, "output_tokens": 10, "total_tokens": 40}
    text_events = [event for event in events if event.type == "messages-tuple"]
    assert [event.data["content"] for event in text_events] == ["A", "B", "C"]
    assert [event.data["usage_metadata"] for event in text_events] == [chunk.usage_metadata for chunk in chunks[:3]]


@pytest.mark.parametrize("snapshot_mode", ["messages", "values"])
@pytest.mark.parametrize("snapshot_first", [False, True])
def test_stream_reconciles_full_usage_without_double_counting(client, snapshot_mode, snapshot_first):
    full = AIMessage(id="a", content="Hello", usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14})
    partial = AIMessageChunk(id="a", content="Hello", usage_metadata={"input_tokens": 10, "output_tokens": 1, "total_tokens": 11})
    snapshot = (snapshot_mode, (full, {}) if snapshot_mode == "messages" else {"messages": [full]})
    items = [("messages", (partial, {}))]
    items.insert(0 if snapshot_first else 1, snapshot)
    items.append(snapshot)
    agent = MagicMock()
    agent.stream.return_value = iter(items)
    with patch.object(client, "_ensure_agent"), patch.object(client, "_agent", agent):
        events = list(client.stream("hi"))

    assert events[-1].data["usage"] == full.usage_metadata


def test_resumed_stream_sums_only_current_usage_deltas(client):
    old = AIMessage(id="old", content="Previous reply", usage_metadata={"input_tokens": 100, "output_tokens": 40, "total_tokens": 140})
    first = AIMessageChunk(id="new", content="Hello", usage_metadata={"input_tokens": 10, "output_tokens": 1, "total_tokens": 11})
    last = AIMessageChunk(id="new", content=" again", usage_metadata={"input_tokens": 0, "output_tokens": 3, "total_tokens": 3})
    full = AIMessage(id="new", content="Hello again", usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14})

    def stream(state, **kwargs):
        current = state["messages"][0]
        messages = [HumanMessage(id="previous-user", content="Previous request"), old, current]
        yield "values", {"messages": messages}
        yield "messages", (old, {})
        yield "messages", (first, {})
        yield "messages", (last, {})
        yield "values", {"messages": [*messages, full]}

    agent = MagicMock()
    agent.stream.side_effect = stream
    with patch.object(client, "_ensure_agent"), patch.object(client, "_agent", agent):
        events = list(client.stream("hi", thread_id="existing-thread"))

    assert events[-1].data["usage"] == full.usage_metadata
    assert [event.data["content"] for event in events if event.type == "messages-tuple"] == ["Hello", " again"]


def test_stream_keeps_no_id_usage_deltas(client):
    agent = MagicMock()
    agent.stream.return_value = iter(
        [
            ("messages", (AIMessageChunk(content="Hi", usage_metadata={"input_tokens": 10, "output_tokens": 1, "total_tokens": 11}), {})),
            ("messages", (AIMessageChunk(content="", usage_metadata={"input_tokens": 0, "output_tokens": 3, "total_tokens": 3}), {})),
        ]
    )
    with patch.object(client, "_ensure_agent"), patch.object(client, "_agent", agent):
        events = list(client.stream("hi"))

    assert events[-1].data["usage"] == {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}


@pytest.mark.parametrize("snapshot_mode", ["messages", "values"])
@pytest.mark.parametrize(
    ("final_usage", "expected"),
    [
        ({"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}, {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}),
        ({"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}),
        ({"input_tokens": 5, "output_tokens": 12, "total_tokens": 17}, {"input_tokens": 10, "output_tokens": 12, "total_tokens": 17}),
    ],
    ids=["lower", "zero", "mixed"],
)
def test_stream_snapshot_cannot_subtract_already_accounted_usage(client, snapshot_mode, final_usage, expected):
    # A middleware may rewrite usage in the completed message. Reconciliation
    # may add missing tokens, but must not retract usage already reported.
    partial = AIMessageChunk(id="a", content="Hello", usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14})
    full = AIMessage(id="a", content="Hello again", usage_metadata=final_usage)
    snapshot = (snapshot_mode, (full, {}) if snapshot_mode == "messages" else {"messages": [full]})
    duplicate = full.model_copy()
    duplicate_snapshot = (snapshot_mode, (duplicate, {}) if snapshot_mode == "messages" else {"messages": [duplicate]})
    other = AIMessage(id="b", content="Another reply", usage_metadata={"input_tokens": 3, "output_tokens": 1, "total_tokens": 4})
    agent = MagicMock()
    agent.stream.return_value = iter(
        [
            ("messages", (partial, {})),
            snapshot,
            duplicate_snapshot,
            ("messages", (partial.model_copy(update={"content": ""}), {})),
            ("messages", (other, {})),
        ]
    )
    with patch.object(client, "_ensure_agent"), patch.object(client, "_agent", agent):
        events = list(client.stream("hi"))

    assert events[-1].data["usage"] == {key: value + other.usage_metadata[key] for key, value in expected.items()}
    # Raw values remain faithful to state; only accounting is clamped.
    if snapshot_mode == "values":
        assert [event for event in events if event.type == "values"][-1].data["messages"][0]["usage_metadata"] == final_usage
    else:
        reconciled = next(event for event in events if event.type == "messages-tuple" and event.data["content"] == "Hello again")
        assert reconciled.data["usage_metadata"] == {key: max(final_usage[key] - partial.usage_metadata[key], 0) for key in expected}
