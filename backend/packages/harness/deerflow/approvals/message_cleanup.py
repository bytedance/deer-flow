"""Remove rejected calls and their colliding provider representations together."""

from typing import Any

from langchain_core.messages import AIMessage

from deerflow.agents.middlewares.tool_call_metadata import clone_ai_message_with_tool_calls


def reject_tool_calls(last: AIMessage, calls: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    """Return a copied message with rejected ID groups removed and a visible note.

    Invalid calls sharing a rejected ID cannot retain raw provider blocks or
    receive placeholder results. Unrelated calls remain with their normal owner.
    An ID-less legacy function_call cannot prove it represents a retained call.
    """
    dropped_ids = [call.get("id") for call in calls]
    kept = [call for call in last.tool_calls if call.get("id") not in dropped_ids]
    additional_kwargs = dict(last.additional_kwargs)
    additional_kwargs.pop("function_call", None)
    cleaned = last.model_copy(update={"invalid_tool_calls": [call for call in last.invalid_tool_calls if call.get("id") not in dropped_ids], "additional_kwargs": additional_kwargs})
    content = [*last.content, {"type": "text", "text": reason}] if isinstance(last.content, list) else f"{last.content}\n\n{reason}" if last.content else reason
    return {"messages": [clone_ai_message_with_tool_calls(cleaned, kept, content=content)]}
