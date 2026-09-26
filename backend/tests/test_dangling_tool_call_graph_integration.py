"""Interrupted graph turns must not acquire evidence from a later reused call id."""

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai.chat_models.base import _convert_message_to_dict
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import PrivateAttr

from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware


class _RecordingModel(FakeMessagesListChatModel):
    _requests: list[list] = PrivateAttr(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._requests.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
@pytest.mark.asyncio
async def test_new_turn_with_reused_call_id_keeps_the_real_result_in_model_request(async_mode):
    executed: list[str] = []

    @tool
    def lookup(subject: str) -> str:
        """Look up a subject in the local test fixture."""
        executed.append(subject)
        return f"RESULT FOR {subject}"

    model = _RecordingModel(
        responses=[
            AIMessage(id="interrupted", content="", tool_calls=[{"id": "call_1", "name": "lookup", "args": {"subject": "old subject"}}]),
            AIMessage(id="retried", content="", tool_calls=[{"id": "call_1", "name": "lookup", "args": {"subject": "new subject"}}]),
            AIMessage(id="done", content="Finished."),
        ]
    )
    saver = InMemorySaver()
    config = {"configurable": {"thread_id": "reused-tool-id"}}
    interrupted = create_agent(model=model, tools=[lookup], middleware=[DanglingToolCallMiddleware()], checkpointer=saver, interrupt_before=["tools"])
    resumed = create_agent(model=model, tools=[lookup], middleware=[DanglingToolCallMiddleware()], checkpointer=saver)

    if async_mode:
        await interrupted.ainvoke({"messages": [HumanMessage(content="Look up the old subject.")]}, config)
        assert executed == []
        state = await resumed.ainvoke({"messages": [HumanMessage(content="Instead, look up the new subject.")]}, config)
    else:
        interrupted.invoke({"messages": [HumanMessage(content="Look up the old subject.")]}, config)
        assert executed == []
        state = resumed.invoke({"messages": [HumanMessage(content="Instead, look up the new subject.")]}, config)

    assert executed == ["new subject"]
    final_request = model._requests[-1]
    old_index = next(index for index, message in enumerate(final_request) if message.id == "interrupted")
    new_index = next(index for index, message in enumerate(final_request) if message.id == "retried")
    assert final_request[old_index + 1].status == "error"
    assert final_request[new_index + 1].content == "RESULT FOR new subject"
    assert final_request[new_index + 1].status == "success"

    # Exercise the real provider serializer, not only the in-memory message shape.
    wire = [_convert_message_to_dict(message) for message in final_request]
    assert wire[old_index + 1]["content"] != "RESULT FOR new subject"
    assert wire[new_index]["tool_calls"][0]["function"]["arguments"] == '{"subject": "new subject"}'
    assert wire[new_index + 1]["content"] == "RESULT FOR new subject"
    assert wire[new_index + 1]["tool_call_id"] == "call_1"

    # Repairs belong to the model request; the checkpoint keeps the original history.
    saved_results = [message for message in state["messages"] if isinstance(message, ToolMessage)]
    assert len(saved_results) == 1
    assert saved_results[0].content == "RESULT FOR new subject"
    assert saved_results[0].status == "success"
