"""Middleware to inject deep-link passthrough parameters into agent context."""

import logging
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)

# Keys in additional_kwargs that are for internal infra use and should NOT be
# exposed to the LLM as deep-link parameters.
_INTERNAL_KWARGS_KEYS = frozenset({"files", "hide_from_ui", "element"})


class PassthroughParamsMiddleware(AgentMiddleware):
    """Middleware to inject deep-link passthrough parameters into message content.

    Reads non-internal keys from the first HumanMessage's ``additional_kwargs``
    (set by the frontend from deep-link URL query parameters) and prepends a
    ``<deep_link_params>`` block to the message content so the LLM can read them.

    Internal keys (``files``, ``hide_from_ui``, ``element``) are excluded.
    The original ``additional_kwargs`` dict is preserved on the message unchanged
    for frontend stream consumers.
    """

    @override
    def before_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        messages = list(state.get("messages", []))
        if not messages:
            return None

        first_message = messages[0]
        if not isinstance(first_message, HumanMessage):
            return None

        additional_kwargs = first_message.additional_kwargs or {}
        passthrough = {
            k: v
            for k, v in additional_kwargs.items()
            if k not in _INTERNAL_KWARGS_KEYS and v is not None
        }
        if not passthrough:
            return None

        block_lines = ["<deep_link_params>"]
        for k, v in passthrough.items():
            block_lines.append(f"  {k}: {v}")
        block_lines.append("</deep_link_params>")
        block = "\n".join(block_lines)

        original_content = first_message.content
        if isinstance(original_content, str):
            updated_content = f"{block}\n\n{original_content}"
        elif isinstance(original_content, list):
            text_block = {"type": "text", "text": f"{block}\n\n"}
            updated_content = [text_block, *original_content]
        else:
            updated_content = original_content

        updated_message = HumanMessage(
            content=updated_content,
            id=first_message.id,
            name=first_message.name,
            additional_kwargs=first_message.additional_kwargs,
        )

        messages[0] = updated_message
        return {"messages": messages}
