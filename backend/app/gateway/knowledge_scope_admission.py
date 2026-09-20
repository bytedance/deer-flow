"""Gateway trust-boundary checks for per-message knowledge scope."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import ValidationError

from deerflow.knowledge_scope import (
    KNOWLEDGE_SCOPE_KEY,
    canonicalize_knowledge_scope,
    execution_scope,
)

RAGFLOW_KNOWLEDGE_SEARCH_PROVIDER = "deerflow.community.ragflow.tools:knowledge_search_tool"


def assistant_supports_knowledge_scope(
    *,
    assistant_id: str | None,
    app_config: Any,
    agent_config: Any | None,
) -> bool:
    """Return whether this exact assistant/provider pairing is supported."""
    if not assistant_id:
        return False
    knowledge_base = getattr(app_config, "knowledge_base", None)
    if not getattr(knowledge_base, "enabled", False):
        return False
    get_tool_config = getattr(app_config, "get_tool_config", None)
    tool = get_tool_config("knowledge_search") if callable(get_tool_config) else None
    if getattr(tool, "use", None) != RAGFLOW_KNOWLEDGE_SEARCH_PROVIDER:
        return False
    # The main assistant has no custom-agent config row. Its knowledge tool is
    # controlled solely by the app-level provider configuration.
    if assistant_id == "lead_agent":
        return True
    if agent_config is None:
        return False
    tool_groups = getattr(agent_config, "tool_groups", None)
    return tool_groups is None or "knowledge" in tool_groups


def _replace_scope(message: HumanMessage, scope: dict[str, Any] | None) -> HumanMessage:
    additional_kwargs = dict(message.additional_kwargs or {})
    if scope is None:
        additional_kwargs.pop(KNOWLEDGE_SCOPE_KEY, None)
    else:
        additional_kwargs[KNOWLEDGE_SCOPE_KEY] = scope
    return message.model_copy(update={"additional_kwargs": additional_kwargs})


def admit_message_knowledge_scope(
    graph_input: dict[str, Any],
    *,
    assistant_id: str | None,
    app_config: Any,
    agent_config: Any | None,
    recovery_scope: object | None = None,
    recovery: bool = False,
) -> dict[str, Any] | None:
    """Canonicalize the sole eligible HumanMessage and return execution scope.

    During regenerate/resume recovery, the server-resolved source snapshot is
    authoritative and replaces any client-supplied value.
    """
    messages = graph_input.get("messages")
    if not isinstance(messages, list):
        return None

    scoped_indexes: list[int] = []
    for index, message in enumerate(messages):
        if not isinstance(message, BaseMessage):
            continue
        additional_kwargs = message.additional_kwargs
        if KNOWLEDGE_SCOPE_KEY not in additional_kwargs:
            continue
        if not isinstance(message, HumanMessage):
            raise HTTPException(
                status_code=422,
                detail="knowledge_scope is allowed only on the current HumanMessage",
            )
        scoped_indexes.append(index)
    if len(scoped_indexes) > 1:
        raise HTTPException(
            status_code=422,
            detail="knowledge_scope is allowed on only one new HumanMessage",
        )

    target_indexes = [index for index, message in enumerate(messages) if isinstance(message, HumanMessage)]
    target_index = target_indexes[-1] if target_indexes else None
    if scoped_indexes and scoped_indexes[0] != target_index:
        raise HTTPException(
            status_code=422,
            detail="knowledge_scope is allowed only on the current HumanMessage",
        )
    if recovery:
        raw_scope = recovery_scope
    elif scoped_indexes:
        target_index = scoped_indexes[0]
        raw_scope = messages[target_index].additional_kwargs[KNOWLEDGE_SCOPE_KEY]
    else:
        return None

    canonical: dict[str, Any] | None = None
    if raw_scope is not None:
        if not assistant_supports_knowledge_scope(
            assistant_id=assistant_id,
            app_config=app_config,
            agent_config=agent_config,
        ):
            raise HTTPException(
                status_code=422,
                detail="knowledge_scope is not supported by this assistant or knowledge provider",
            )
        try:
            canonical = canonicalize_knowledge_scope(raw_scope)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid knowledge_scope: {exc.errors()[0]['msg']}",
            ) from exc
    elif scoped_indexes and not recovery:
        raise HTTPException(status_code=422, detail="knowledge_scope must be an object")

    if target_index is not None:
        messages[target_index] = _replace_scope(messages[target_index], canonical)
    return execution_scope(canonical) if canonical is not None else None
