from langchain_core.messages import AIMessage, HumanMessage

from deerflow.models.patched_gemini import PatchedChatOpenAI


def _model() -> PatchedChatOpenAI:
    return PatchedChatOpenAI(model="gemini-test", api_key="test-key")


def test_replays_gemini_thought_signature_from_raw_tool_call() -> None:
    raw_tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "default_api:web_fetch",
            "arguments": '{"url":"https://example.com"}',
        },
        "extra_content": {
            "google": {"thought_signature": "opaque-signature"}
        },
    }
    assistant = AIMessage(
        content="",
        additional_kwargs={"tool_calls": [raw_tool_call]},
        tool_calls=[
            {
                "id": "call_1",
                "name": "default_api:web_fetch",
                "args": {"url": "https://example.com"},
                "type": "tool_call",
            }
        ],
    )

    payload = _model()._get_request_payload(
        [HumanMessage(content="Fetch the page"), assistant]
    )

    assistant_payload = payload["messages"][1]
    assert assistant_payload["tool_calls"][0]["extra_content"] == {
        "google": {"thought_signature": "opaque-signature"}
    }


def test_replays_direct_thought_signature_used_by_compatible_gateways() -> None:
    assistant = AIMessage(
        content="",
        additional_kwargs={
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "web_fetch", "arguments": "{}"},
                    "thought_signature": "opaque-signature",
                }
            ]
        },
        tool_calls=[
            {
                "id": "call_1",
                "name": "web_fetch",
                "args": {},
                "type": "tool_call",
            }
        ],
    )

    payload = _model()._get_request_payload([assistant])

    assert payload["messages"][0]["tool_calls"][0]["thought_signature"] == (
        "opaque-signature"
    )


def test_leaves_standard_openai_tool_calls_unchanged() -> None:
    assistant = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_1",
                "name": "web_fetch",
                "args": {},
                "type": "tool_call",
            }
        ],
    )

    payload = _model()._get_request_payload([assistant])
    tool_call = payload["messages"][0]["tool_calls"][0]

    assert "extra_content" not in tool_call
    assert "thought_signature" not in tool_call
