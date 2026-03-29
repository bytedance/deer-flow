import logging

from fastapi import APIRouter
from langchain.tools import BaseTool
from pydantic import BaseModel, Field

from sim_data_agent.config import get_app_config
from sim_data_agent.reflection import resolve_variable

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["tools"])


# Built-in tool Chinese translations
TOOL_TRANSLATIONS = {
    "web_search": {
        "name_zh": "网络搜索",
        "group_zh": "网络",
        "description_zh": "在网络上搜索信息。使用此工具查找最新资讯、新闻、文章和互联网上的事实。",
    },
    "web_fetch": {
        "name_zh": "网页抓取",
        "group_zh": "网络",
        "description_zh": "获取指定 URL 的网页内容。",
    },
    "image_search": {
        "name_zh": "图片搜索",
        "group_zh": "网络",
        "description_zh": "在网上搜索图片。在生成图片前使用此工具查找参考图片。",
    },
    "ls": {
        "name_zh": "列出文件",
        "group_zh": "文件读取",
        "description_zh": "以树形格式列出目录内容（最多 2 层）。",
    },
    "read_file": {
        "name_zh": "读取文件",
        "group_zh": "文件读取",
        "description_zh": "读取文本文件内容。用于查看源代码、配置文件、日志或任何文本文件。",
    },
    "write_file": {
        "name_zh": "写入文件",
        "group_zh": "文件写入",
        "description_zh": "将文本内容写入文件。",
    },
    "str_replace": {
        "name_zh": "替换文本",
        "group_zh": "文件写入",
        "description_zh": "替换文件中的子字符串。",
    },
    "bash": {
        "name_zh": "命令行执行",
        "group_zh": "命令行",
        "description_zh": "在 Linux 环境中执行 bash 命令。使用 python 运行 Python 代码。",
    },
    "pgsql_query": {
        "name_zh": "PostgreSQL 查询",
        "group_zh": "数据库",
        "description_zh": "执行 PostgreSQL 数据库查询。",
    },
    "python_exec": {
        "name_zh": "Python 执行",
        "group_zh": "代码执行",
        "description_zh": "执行 Python 代码。",
    },
}


class ToolResponse(BaseModel):
    """Response model for a configured tool."""

    name: str = Field(..., description="Unique name of the tool")
    name_zh: str | None = Field(None, description="Chinese name of the tool")
    group: str = Field(..., description="Tool group name")
    group_zh: str | None = Field(None, description="Chinese tool group name")
    description: str = Field(default="", description="Tool description")
    description_zh: str | None = Field(None, description="Chinese tool description")


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

        # Get Chinese translations
        translation = TOOL_TRANSLATIONS.get(tool_cfg.name, {})

        tools.append(
            ToolResponse(
                name=tool_cfg.name,
                name_zh=translation.get("name_zh"),
                group=tool_cfg.group,
                group_zh=translation.get("group_zh"),
                description=description,
                description_zh=translation.get("description_zh"),
            )
        )
    return ToolsListResponse(tools=tools)
