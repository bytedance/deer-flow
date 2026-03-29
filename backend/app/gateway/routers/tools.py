import logging

from fastapi import APIRouter
from langchain.tools import BaseTool
from pydantic import BaseModel, Field

from sim_data_agent.config import get_app_config
from sim_data_agent.reflection import resolve_variable

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["tools"])


class ToolResponse(BaseModel):
    """Response model for a configured tool."""

    name: str = Field(..., description="Unique name of the tool")
    group: str = Field(..., description="Tool group name")
    description: str = Field(default="", description="Tool description")


class ToolsListResponse(BaseModel):
    """Response model for listing all configured tools."""

    tools: list[ToolResponse]


@router.get(
    "/tools",
    response_model=ToolsListResponse,
    summary="List Configured Tools",
    description="Retrieve a list of all tools configured in config.yaml.",
)
async def list_tools() -> ToolsListResponse:
    config = get_app_config()
    tools = []
    for tool_cfg in config.tools:
        description = ""
        try:
            tool_instance = resolve_variable(tool_cfg.use, BaseTool)
            description = tool_instance.description or ""
        except Exception:
            logger.debug("Could not resolve tool %s for description", tool_cfg.name)
        tools.append(
            ToolResponse(
                name=tool_cfg.name,
                group=tool_cfg.group,
                description=description,
            )
        )
    return ToolsListResponse(tools=tools)
