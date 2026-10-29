"""Factory-level wiring test for ClarificationMiddleware sibling-tool dropping.

Unit tests in ``test_clarification_middleware.py`` call ``after_model``
directly. This file builds a real ``langchain.agents.create_agent`` graph
so a langchain hook-dispatch regression or a same-id ``add_messages``
replacement failure would reintroduce #4906 instead of staying green.
A second graph path covers malformed ``ask_clarification`` parked on
``invalid_tool_calls`` beside a valid sibling.
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
from deerflow.tools.builtins.clarification_tool import ask_clarification_tool

_BASH_INVOCATIONS: list[str] = []
_MIXED_MESSAGE_ID = "ai-clarification-with-sibling"
_INVALID_MIXED_MESSAGE_ID = "ai-invalid-clarification-with-sibling"


@tool
def bash(command: str) -> str:
    """Pretend to run a shell command. Records the call for assertion."""
    _BASH_INVOCATIONS.append(command)
    return f"ran: {command}"


class _MixedBatchModel(BaseChatModel):
    """First call emits ``ask_clarification`` plus ``bash``; a second call is a wiring failure."""

    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-clarification-mixed-batch"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            message = AIMessage(
                id=_MIXED_MESSAGE_ID,
                content="",
                tool_calls=[
                    {
                        "id": "call_clarify_1",
                        "name": "ask_clarification",
                        "args": {
                            "question": "Which directory should I use?",
                            "clarification_type": "missing_info",
                        },
                    },
                    {
                        "id": "call_bash_1",
                        "name": "bash",
                        "args": {"command": "rm -rf /tmp/foo"},
                    },
                ],
            )
        else:
            message = AIMessage(content="should-not-happen")
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class _InvalidClarificationMixedBatchModel(BaseChatModel):
    """First call emits a malformed ask_clarification plus a valid bash sibling."""

    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-invalid-clarification-mixed-batch"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            message = AIMessage(
                id=_INVALID_MIXED_MESSAGE_ID,
                content="",
                tool_calls=[
                    {
                        "id": "call_bash_1",
                        "name": "bash",
                        "args": {"command": "rm -rf /tmp/foo"},
                    },
                ],
                invalid_tool_calls=[
                    {
                        "id": "call_clarify_1",
                        "name": "ask_clarification",
                        "args": "{",
                        "error": "Failed to parse tool arguments",
                        "type": "invalid_tool_call",
                    },
                ],
            )
        else:
            message = AIMessage(content="should-not-happen")
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def test_mixed_clarification_batch_does_not_execute_siblings_or_loop():
    """after_model must be dispatched and replace the AIMessage in place.

    (a) the bash handler never runs
    (b) the run ends without a second model call
    """
    _BASH_INVOCATIONS.clear()
    model = _MixedBatchModel()
    agent = create_agent(
        model=model,
        tools=[ask_clarification_tool, bash],
        middleware=[ClarificationMiddleware()],
    )

    result = agent.invoke(
        {"messages": [HumanMessage(content="clean up the temp dir")]},
        config={"recursion_limit": 8},
    )

    assert _BASH_INVOCATIONS == [], f"bash ran before the user answered: {_BASH_INVOCATIONS}"
    assert model.call_count == 1

    ai_messages = [message for message in result["messages"] if isinstance(message, AIMessage)]
    assert len(ai_messages) == 1
    patched = ai_messages[0]
    assert patched.id == _MIXED_MESSAGE_ID
    assert [tc["name"] for tc in patched.tool_calls] == ["ask_clarification"]

    tool_messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    assert [message.name for message in tool_messages] == ["ask_clarification"]
    assert tool_messages[0].tool_call_id == "call_clarify_1"


def test_mixed_invalid_clarification_batch_does_not_execute_siblings_or_loop():
    """Malformed ask_clarification is still a stop signal for executable siblings.

    LangChain parks the broken call on ``invalid_tool_calls`` while the valid
    bash sibling stays on ``tool_calls``. after_model must still rewrite the
    AIMessage so:
    (a) the bash handler never runs
    (b) the run ends without a second model call
    """
    _BASH_INVOCATIONS.clear()
    model = _InvalidClarificationMixedBatchModel()
    agent = create_agent(
        model=model,
        tools=[ask_clarification_tool, bash],
        middleware=[ClarificationMiddleware()],
    )

    result = agent.invoke(
        {"messages": [HumanMessage(content="clean up the temp dir")]},
        config={"recursion_limit": 8},
    )

    assert _BASH_INVOCATIONS == [], f"bash ran before the user answered: {_BASH_INVOCATIONS}"
    assert model.call_count == 1

    ai_messages = [message for message in result["messages"] if isinstance(message, AIMessage)]
    assert len(ai_messages) == 1
    patched = ai_messages[0]
    assert patched.id == _INVALID_MIXED_MESSAGE_ID
    assert patched.tool_calls == []
    assert [tc["name"] for tc in patched.invalid_tool_calls] == ["ask_clarification"]
    assert patched.invalid_tool_calls[0]["id"] == "call_clarify_1"

    tool_messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    assert tool_messages == []
