"""Shared helpers for user-isolation e2e tests on the custom-agent tooling.

Centralises the small fake-LLM shim and a few test-data builders that the
three e2e files in this PR (``test_setup_agent_e2e_user_isolation``,
``test_update_agent_e2e_user_isolation``, ``test_setup_agent_http_e2e_real_server``)
all need. The shim is what lets a real ``langchain.agents.create_agent``
graph run without an API key — every other layer in those tests is real
production code, which is the entire point of the test design.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable


class FakeToolCallingModel(FakeMessagesListChatModel):
    """FakeMessagesListChatModel plus a no-op ``bind_tools`` for create_agent.

    ``langchain.agents.create_agent`` calls ``model.bind_tools(...)`` to
    expose the tool schemas to the model; the upstream fake raises
    ``NotImplementedError`` there. We just return ``self`` because we
    drive deterministic tool_call output via ``responses=...``, no schema
    handling needed.
    """

    def bind_tools(  # type: ignore[override]
        self,
        tools: Any,
        *,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> Runnable:
        return self


def build_single_tool_call_model(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    tool_call_id: str = "call_e2e_1",
    final_text: str = "done",
) -> FakeToolCallingModel:
    """Build a fake model that emits exactly one tool_call then finishes.

    Two-turn behaviour, identical across our e2e tests:
      turn 1 → AIMessage with a single tool_call for *tool_name*
      turn 2 → AIMessage with *final_text* (terminates the agent loop)
    """
    return FakeToolCallingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": tool_name,
                        "args": tool_args,
                        "id": tool_call_id,
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content=final_text),
        ]
    )
