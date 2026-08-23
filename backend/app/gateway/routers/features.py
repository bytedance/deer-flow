"""Read-only feature-flag endpoint for the frontend bootstrap.

Reports which optional features are exposed over HTTP so the frontend can gate
UI and avoid firing requests that the backend would reject. Config-only flags
read through ``get_config`` so edits to ``config.yaml`` take effect on the next
request, while startup-scoped capabilities report the runtime that actually
started.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.gateway.browser_capability import browser_capability
from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig

router = APIRouter(prefix="/api", tags=["features"])


class AgentsApiFeature(BaseModel):
    """Availability of the custom-agent management API."""

    enabled: bool = Field(..., description="Whether the agents_api routes are exposed over HTTP")


class BrowserControlFeature(BaseModel):
    """Availability of live agentic browser control."""

    enabled: bool = Field(..., description="Whether the live browser routes and UI are available")


class McpTasksFeature(BaseModel):
    """Availability of the durable MCP task runtime."""

    enabled: bool = Field(..., description="Whether durable MCP task APIs and UI are available")


class FeaturesResponse(BaseModel):
    """Frontend-facing feature availability flags."""

    agents_api: AgentsApiFeature
    browser_control: BrowserControlFeature
    mcp_tasks: McpTasksFeature


@router.get(
    "/features",
    response_model=FeaturesResponse,
    summary="List Feature Flags",
    description="Report which optional features are available, so the frontend can gate UI before issuing requests.",
)
async def list_features(request: Request, config: AppConfig = Depends(get_config)) -> FeaturesResponse:
    """Return availability of optional frontend features."""
    browser = browser_capability(config)
    return FeaturesResponse(
        agents_api=AgentsApiFeature(enabled=config.agents_api.enabled),
        browser_control=BrowserControlFeature(enabled=browser.available),
        # MCP task bindings and the submitter are startup-scoped. Report the
        # capability that actually started rather than a hot-reloaded config
        # value that would require a Gateway restart to take effect.
        mcp_tasks=McpTasksFeature(enabled=bool(getattr(request.app.state, "mcp_tasks_available", False))),
    )
