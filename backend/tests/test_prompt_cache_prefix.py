"""Receipt rendering must keep the request history append-only.

Some providers only reuse a cached prompt when the new request starts with the
entire previous request. Receipts therefore render as a pure function of each
tool result instead of a ledger re-rendered at a fixed position.
"""

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from test_durable_context_middleware import RecordingFakeModel, fake_read_file

from deerflow.agents.middlewares.tool_receipt_middleware import ToolReceiptMiddleware
from deerflow.agents.thread_state import ThreadState


def _fingerprint(message) -> tuple:
    return (
        type(message).__name__,
        str(message.content),
        tuple(call["id"] for call in getattr(message, "tool_calls", None) or []),
        getattr(message, "tool_call_id", None),
    )


def _read(call_id: str, path: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": path}, "id": call_id, "type": "tool_call"}])


def test_each_request_starts_with_the_entire_previous_request():
    model = RecordingFakeModel(responses=[_read("r1", "/a"), _read("r2", "/b"), _read("r3", "/c"), AIMessage(content="done [r3 read_file]")])
    agent = create_agent(model=model, tools=[fake_read_file], middleware=[ToolReceiptMiddleware(render_mode="always")], state_schema=ThreadState)

    agent.invoke({"messages": [HumanMessage(content="start")]})

    calls = [[_fingerprint(m) for m in call] for call in model.received]
    assert len(calls) == 4
    assert "- [r3] read_file" in calls[-1][-1][1], "the newest tool result carries its receipt"
    for previous, current in zip(calls, calls[1:]):
        assert current[: len(previous)] == previous
