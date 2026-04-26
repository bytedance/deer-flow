"""Assistants compatibility endpoints.

Provides LangGraph Platform-compatible assistants API backed by the
``langgraph.json`` graph registry and ``config.yaml`` agent definitions.

This is a minimal stub that satisfies the ``useStream`` React hook's
initialization requirements (``assistants.search()`` and ``assistants.get()``).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/assistants", tags=["assistants-compat"])


class AssistantResponse(BaseModel):
    assistant_id: str
    graph_id: str
    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None
    created_at: str = ""
    updated_at: str = ""
    version: int = 1


class AssistantSearchRequest(BaseModel):
    graph_id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] | None = None
    limit: int = 10
    offset: int = 0


def _get_default_assistant() -> AssistantResponse:
    """Return the default lead_agent assistant."""
    now = datetime.now(UTC).isoformat()
    return AssistantResponse(
        assistant_id="lead_agent",
        graph_id="lead_agent",
        name="lead_agent",
        config={},
        metadata={"created_by": "system"},
        description="DeerFlow lead agent",
        created_at=now,
        updated_at=now,
        version=1,
    )


def _list_assistants() -> list[AssistantResponse]:
    """List all available assistants from config."""
    assistants = [_get_default_assistant()]

    # Also include custom agents from config.yaml agents directory
    try:
        from deerflow.config.agents_config import list_custom_agents

        for agent_cfg in list_custom_agents():
            now = datetime.now(UTC).isoformat()
            assistants.append(
                AssistantResponse(
                    assistant_id=agent_cfg.name,
                    graph_id="lead_agent",  # All agents use the same graph
                    name=agent_cfg.name,
                    config={},
                    metadata={"created_by": "user"},
                    description=agent_cfg.description or "",
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
            )
    except Exception:
        logger.debug("Could not load custom agents for assistants list")

    return assistants


@router.post("/search", response_model=list[AssistantResponse])
async def search_assistants(body: AssistantSearchRequest | None = None) -> list[AssistantResponse]:
    """Search assistants.

    Returns all registered assistants (lead_agent + custom agents from config).
    """
    assistants = _list_assistants()

    if body and body.graph_id:
        assistants = [a for a in assistants if a.graph_id == body.graph_id]
    if body and body.name:
        assistants = [a for a in assistants if body.name.lower() in a.name.lower()]

    offset = body.offset if body else 0
    limit = body.limit if body else 10
    return assistants[offset : offset + limit]


@router.get("/{assistant_id}", response_model=AssistantResponse)
async def get_assistant_compat(assistant_id: str) -> AssistantResponse:
    """Get an assistant by ID."""
    for a in _list_assistants():
        if a.assistant_id == assistant_id:
            return a
    raise HTTPException(status_code=404, detail=f"Assistant {assistant_id} not found")


@router.get("/{assistant_id}/graph")
async def get_assistant_graph(assistant_id: str) -> dict:
    """Get the graph structure for an assistant.

    Returns a minimal graph description. Full graph introspection is
    not supported in the Gateway — this stub satisfies SDK validation.
    """
    found = any(a.assistant_id == assistant_id for a in _list_assistants())
    if not found:
        raise HTTPException(status_code=404, detail=f"Assistant {assistant_id} not found")

    return {
        "graph_id": "lead_agent",
        "nodes": [],
        "edges": [],
    }


@router.get("/{assistant_id}/schemas")
async def get_assistant_schemas(assistant_id: str) -> dict:
    """Get JSON schemas for an assistant's input/output/state.

    Returns empty schemas — full introspection not supported in Gateway.
    """
    found = any(a.assistant_id == assistant_id for a in _list_assistants())
    if not found:
        raise HTTPException(status_code=404, detail=f"Assistant {assistant_id} not found")

    return {
        "graph_id": "lead_agent",
        "input_schema": {},
        "output_schema": {},
        "state_schema": {},
        "config_schema": {},
    }
