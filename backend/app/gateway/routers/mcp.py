"""
MCP配置API路由 — 管理Model Context Protocol服务器配置

===================
设计思路说明
===================

**为什么需要MCP配置API**：
1. MCP（Model Context Protocol）是DeerFlow扩展AI能力的关键机制
2. 用户需要通过API动态配置MCP服务器，无需重启服务
3. 提供统一的配置管理接口，支持多种传输方式（stdio/sse/http）

**核心设计模式**：
- RESTful API：GET获取配置，PUT更新配置
- 配置持久化：修改后自动保存到文件
- 自动热重载：LangGraph Server会检测文件变化并重新初始化

**为什么支持多种传输类型**：
- stdio：本地进程通信，适合npm/npx启动的服务器
- sse：服务器发送事件，适合实时数据流
- http：标准HTTP请求，适合远程MCP服务器

**OAuth支持的设计**：
- 为什么需要OAuth：某些MCP服务器（如企业内部服务）需要认证
- 为什么支持多种grant_type：client_credentials适合服务间认证，refresh_token适合长期访问
- 为什么需要token_field配置：不同OAuth服务器的响应格式可能不同

**配置文件结构**：
{
    "mcpServers": {
        "server_name": {
            "enabled": true,
            "type": "stdio|sse|http",
            "command": "npx",  // stdio专用
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": {"GITHUB_TOKEN": "..."},
            "url": "...",  // sse/http专用
            "headers": {...},
            "oauth": {...},
            "description": "..."
        }
    },
    "skills": {...}  // 保留，不修改
}
"""

import json
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deerflow.config.extensions_config import ExtensionsConfig, get_extensions_config, reload_extensions_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["mcp"])


class McpOAuthConfigResponse(BaseModel):
    """
    MCP服务器的OAuth配置

    ===================
    设计思路说明
    ===================

    **为什么需要这么详细的OAuth配置**：
    - 不同OAuth服务器的实现差异很大
    - 需要灵活适配各种OAuth 2.0流程
    - 字段映射能力支持非标准响应格式

    **为什么需要token_field等映射字段**：
    - 标准OAuth响应包含access_token，但某些服务可能使用不同字段名
    - token_type_field同理，某些服务可能返回非标准字段
    - expires_in_field支持响应中时间戳字段名的定制

    **为什么需要refresh_skew_seconds**：
    - 提前刷新token可以避免请求时token已过期
    - 网络延迟可能导致token在传输过程中过期
    - 默认60秒是合理的提前量
    """

    enabled: bool = Field(default=True, description="是否启用OAuth token注入")
    token_url: str = Field(default="", description="OAuth token端点URL")
    grant_type: Literal["client_credentials", "refresh_token"] = Field(
        default="client_credentials",
        description="OAuth授权类型：client_credentials用于服务间认证，refresh_token用于刷新访问令牌"
    )
    client_id: str | None = Field(default=None, description="OAuth客户端ID")
    client_secret: str | None = Field(default=None, description="OAuth客户端密钥")
    refresh_token: str | None = Field(default=None, description="OAuth刷新令牌")
    scope: str | None = Field(default=None, description="OAuth权限范围")
    audience: str | None = Field(default=None, description="OAuth受众（某些OAuth服务器需要）")
    token_field: str = Field(default="access_token", description="包含访问令牌的响应字段名")
    token_type_field: str = Field(default="token_type", description="包含令牌类型的响应字段名")
    expires_in_field: str = Field(default="expires_in", description="包含过期时间的响应字段名")
    default_token_type: str = Field(default="Bearer", description="响应省略token_type时使用的默认令牌类型")
    refresh_skew_seconds: int = Field(
        default=60,
        description="提前多少秒刷新令牌（避免令牌在请求过程中过期）"
    )
    extra_token_params: dict[str, str] = Field(
        default_factory=dict,
        description="发送到token端点的额外表单参数"
    )


class McpServerConfigResponse(BaseModel):
    """
    MCP服务器配置响应

    **为什么command/args和url/headers分开**：
    - stdio类型需要command和args来启动进程
    - sse/http类型需要url和headers来建立连接
    - 分开设计避免混淆，提高配置清晰度
    """

    enabled: bool = Field(default=True, description="是否启用此MCP服务器")
    type: str = Field(
        default="stdio",
        description="传输类型：'stdio'（本地进程）、'sse'（服务器发送事件）或'http'（标准HTTP）"
    )
    command: str | None = Field(default=None, description="启动MCP服务器的命令（stdio类型专用）")
    args: list[str] = Field(default_factory=list, description="传递给命令的参数（stdio类型专用）")
    env: dict[str, str] = Field(default_factory=dict, description="MCP服务器的环境变量")
    url: str | None = Field(default=None, description="MCP服务器的URL（sse或http类型专用）")
    headers: dict[str, str] = Field(default_factory=dict, description="要发送的HTTP头（sse或http类型专用）")
    oauth: McpOAuthConfigResponse | None = Field(default=None, description="MCP HTTP/SSE服务器的OAuth配置")
    description: str = Field(default="", description="MCP服务器提供功能的人类可读描述")


class McpConfigResponse(BaseModel):
    """MCP配置响应"""

    mcp_servers: dict[str, McpServerConfigResponse] = Field(
        default_factory=dict,
        description="MCP服务器名称到配置的映射",
    )


class McpConfigUpdateRequest(BaseModel):
    """
    MCP配置更新请求

    **为什么使用独立的请求模型**：
    - 请求和响应可能有不同的验证规则
    - 便于未来添加更新相关的额外字段（如force标志）
    - 明确区分输入输出契约
    """

    mcp_servers: dict[str, McpServerConfigResponse] = Field(
        ...,
        description="MCP服务器名称到配置的映射",
    )


@router.get(
    "/mcp/config",
    response_model=McpConfigResponse,
    summary="Get MCP Configuration",
    description="Retrieve the current Model Context Protocol (MCP) server configurations.",
)
async def get_mcp_configuration() -> McpConfigResponse:
    """
    获取当前MCP配置

    **为什么需要这个端点**：
    - 前端需要展示当前配置的MCP服务器列表
    - 用户需要查看哪些服务器已启用
    - 调试时需要确认配置是否正确加载

    **返回值**：
        当前所有MCP服务器的配置

    **示例响应**：
        ```json
        {
            "mcp_servers": {
                "github": {
                    "enabled": true,
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": "ghp_xxx"},
                    "description": "GitHub MCP server for repository operations"
                }
            }
        }
        ```
    """
    config = get_extensions_config()

    return McpConfigResponse(
        mcp_servers={name: McpServerConfigResponse(**server.model_dump()) for name, server in config.mcp_servers.items()}
    )


@router.put(
    "/mcp/config",
    response_model=McpConfigResponse,
    summary="Update MCP Configuration",
    description="Update Model Context Protocol (MCP) server configurations and save to file.",
)
async def update_mcp_configuration(request: McpConfigUpdateRequest) -> McpConfigResponse:
    """
    更新MCP配置

    **为什么使用PUT而不是PATCH**：
    - PUT替换整个配置，更符合语义
    - 避免部分更新的复杂性
    - 确保配置的一致性

    **更新流程**：
    1. 确定配置文件路径（创建或使用现有）
    2. 加载当前配置以保留skills设置
    3. 合并新的MCP配置
    4. 写入文件
    5. 重新加载配置到内存

    **为什么需要保留skills配置**：
    - 配置文件包含mcpServers和skills两部分
    - 更新MCP不应影响skills
    - 避免配置丢失

    **为什么不需要在这里重置缓存**：
    - LangGraph Server是独立进程
    - 它会通过文件修改时间（mtime）检测配置变化
    - 自动重新初始化MCP工具
    - 避免跨进程通信的复杂性

    **参数说明**：
        request: 新的MCP配置

    **返回值**：
        更新后的MCP配置

    **异常**：
        HTTPException 500: 配置文件写入失败

    **示例请求**：
        ```json
        {
            "mcp_servers": {
                "github": {
                    "enabled": true,
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"},
                    "description": "GitHub MCP server for repository operations"
                }
            }
        }
        ```
    """
    try:
        # 获取当前配置路径（或确定保存位置）
        config_path = ExtensionsConfig.resolve_config_path()

        # 如果配置文件不存在，在父目录（项目根目录）创建一个
        if config_path is None:
            config_path = Path.cwd().parent / "extensions_config.json"
            logger.info(f"No existing extensions config found. Creating new config at: {config_path}")

        # 加载当前配置以保留skills配置
        current_config = get_extensions_config()

        # 将请求转换为JSON序列化格式
        # 为什么需要转换：Pydantic模型不能直接序列化为JSON
        config_data = {
            "mcpServers": {name: server.model_dump() for name, server in request.mcp_servers.items()},
            "skills": {name: {"enabled": skill.enabled} for name, skill in current_config.skills.items()},
        }

        # 将配置写入文件
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)

        logger.info(f"MCP configuration updated and saved to: {config_path}")

        # 注意：这里不需要重载/重置缓存 - LangGraph Server（独立进程）
        # 会通过mtime检测配置文件变化并自动重新初始化MCP工具

        # 重新加载配置并更新全局缓存
        reloaded_config = reload_extensions_config()
        return McpConfigResponse(
            mcp_servers={name: McpServerConfigResponse(**server.model_dump()) for name, server in reloaded_config.mcp_servers.items()}
        )

    except Exception as e:
        logger.error(f"Failed to update MCP configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update MCP configuration: {str(e)}")
