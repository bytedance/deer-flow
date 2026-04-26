"""
统一扩展配置模块（MCP服务器和技能）

====================
设计思路说明
====================

**核心职责**：
1. 管理MCP（Model Context Protocol）服务器配置
2. 管理技能（Skills）启用状态
3. 支持OAuth认证的MCP服务器
4. 环境变量替换

**为什么需要MCP服务器**：
- 扩展AI能力边界（连接外部服务）
- 标准化工具调用协议
- 社区生态共享工具

**为什么需要技能状态管理**：
- 不同场景需要不同技能
- 动态启用/禁用技能
- A/B测试新功能

**为什么使用单独的JSON文件**：
- extensions_config.json可能由外部系统生成
- JSON更适合程序化编辑
- 可能包含敏感信息，独立存储更安全
- 频繁变化，与主配置分离

**传输类型说明**：
- stdio: 通过标准输入输出通信（本地进程）
- sse: 通过Server-Sent Events通信（单向流）
- http: 通过HTTP/WebSocket通信（双向）
"""

"""Unified extensions configuration for MCP servers and skills."""

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class McpOAuthConfig(BaseModel):
    """MCP服务器的OAuth配置（用于HTTP/SSE传输）

    **OAuth支持两种授权类型**：

    **client_credentials**：
    - 机器对机器认证
    - 使用client_id和client_secret
    - 适合后台服务

    **refresh_token**：
    - 用户授权场景
    - 使用refresh_token刷新访问令牌
    - 适合需要用户上下文的场景

    **为什么需要这么多字段**：
    - 不同OAuth提供者使用不同字段名
    - 灵活适配各种OAuth实现
    - 支持自定义参数

    **refresh_skew_seconds的作用**：
    - 提前刷新令牌，避免使用过期令牌
    - 考虑网络延迟和时钟偏差
    - 默认60秒提前量
    """

    enabled: bool = Field(default=True, description="Whether OAuth token injection is enabled")
    token_url: str = Field(description="OAuth token endpoint URL")
    grant_type: Literal["client_credentials", "refresh_token"] = Field(
        default="client_credentials",
        description="OAuth grant type",
    )
    client_id: str | None = Field(default=None, description="OAuth client ID")
    client_secret: str | None = Field(default=None, description="OAuth client secret")
    refresh_token: str | None = Field(default=None, description="OAuth refresh token (for refresh_token grant)")
    scope: str | None = Field(default=None, description="OAuth scope")
    audience: str | None = Field(default=None, description="OAuth audience (provider-specific)")
    token_field: str = Field(default="access_token", description="Field name containing access token in token response")
    token_type_field: str = Field(default="token_type", description="Field name containing token type in token response")
    expires_in_field: str = Field(default="expires_in", description="Field name containing expiry (seconds) in token response")
    default_token_type: str = Field(default="Bearer", description="Default token type when missing in token response")
    refresh_skew_seconds: int = Field(default=60, description="Refresh token this many seconds before expiry")
    extra_token_params: dict[str, str] = Field(default_factory=dict, description="Additional form params sent to token endpoint")
    model_config = ConfigDict(extra="allow")


class McpServerConfig(BaseModel):
    """单个MCP服务器配置

    **传输类型对应字段**：

    **stdio类型**：
    - command: 启动命令（如"node"、"python"）
    - args: 命令参数
    - env: 环境变量

    **sse/http类型**：
    - url: 服务器URL
    - headers: HTTP请求头
    - oauth: OAuth认证配置

    **为什么需要enabled字段**：
    - 临时禁用服务器而不删除配置
    - A/B测试不同配置
    - 快速切换服务器

    **description的作用**：
    - UI展示服务器功能
    - 帮助用户理解工具来源
    - 文档化作用
    """

    enabled: bool = Field(default=True, description="Whether this MCP server is enabled")
    type: str = Field(default="stdio", description="Transport type: 'stdio', 'sse', or 'http'")
    command: str | None = Field(default=None, description="Command to execute to start the MCP server (for stdio type)")
    args: list[str] = Field(default_factory=list, description="Arguments to pass to the command (for stdio type)")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables for the MCP server")
    url: str | None = Field(default=None, description="URL of the MCP server (for sse or http type)")
    headers: dict[str, str] = Field(default_factory=dict, description="HTTP headers to send (for sse or http type)")
    oauth: McpOAuthConfig | None = Field(default=None, description="OAuth configuration (for sse or http type)")
    description: str = Field(default="", description="Human-readable description of what this MCP server provides")
    model_config = ConfigDict(extra="allow")


class SkillStateConfig(BaseModel):
    """单个技能的状态配置

    **为什么只有enabled字段**：
    - 技能启用/禁用是唯一需要配置的状态
    - 其他元数据在技能定义中
    - 保持配置简洁

    **默认启用策略**：
    - 新发现的技能默认启用
    - 减少配置工作量
    - 可以通过配置显式禁用
    """

    enabled: bool = Field(default=True, description="Whether this skill is enabled")


class ExtensionsConfig(BaseModel):
    """统一扩展配置（MCP服务器和技能）

    **配置结构**：
    - mcp_servers: MCP服务器配置映射（别名mcpServers）
    - skills: 技能状态配置映射

    **为什么使用别名（alias）**：
    - JSON文件使用camelCase（JavaScript惯例）
    - Python使用snake_case（PEP8）
    - Pydantic自动转换，两边都用各自风格

    **为什么扩展是可选的**：
    - 核心功能不依赖扩展
    - 轻量级部署不需要MCP服务器
    - 技能系统可以独立使用
    """

    mcp_servers: dict[str, McpServerConfig] = Field(
        default_factory=dict,
        description="Map of MCP server name to configuration",
        alias="mcpServers",
    )
    skills: dict[str, SkillStateConfig] = Field(
        default_factory=dict,
        description="Map of skill name to state configuration",
    )
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    @classmethod
    def resolve_config_path(cls, config_path: str | None = None) -> Path | None:
        """解析扩展配置文件路径

        **解析优先级**（从高到低）：
        1. 显式传入的config_path参数
        2. DEER_FLOW_EXTENSIONS_CONFIG_PATH环境变量
        3. 当前目录的extensions_config.json
        4. 父目录的extensions_config.json
        5. 当前目录的mcp_config.json（向后兼容）
        6. 父目录的mcp_config.json（向后兼容）
        7. 未找到返回None（扩展是可选的）

        **为什么向后兼容mcp_config.json**：
        - 历史原因，最初叫mcp_config.json
        - 重命名为extensions_config.json更准确
        - 平滑迁移，不破坏现有部署
        - 最终会废弃对mcp_config.json的支持

        **为什么返回None而不是抛出异常**：
        - 扩展是可选功能
        - 不应该因为缺少配置而阻止启动
        - 返回空配置更合理

        Args:
            config_path: 可选的扩展配置文件路径

        Returns:
            扩展配置文件路径，未找到返回None
        """
        if config_path:
            path = Path(config_path)
            if not path.exists():
                raise FileNotFoundError(f"Extensions config file specified by param `config_path` not found at {path}")
            return path
        elif os.getenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH"):
            path = Path(os.getenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH"))
            if not path.exists():
                raise FileNotFoundError(f"Extensions config file specified by environment variable `DEER_FLOW_EXTENSIONS_CONFIG_PATH` not found at {path}")
            return path
        else:
            # Check if the extensions_config.json is in the current directory
            path = Path(os.getcwd()) / "extensions_config.json"
            if path.exists():
                return path

            # Check if the extensions_config.json is in the parent directory of CWD
            path = Path(os.getcwd()).parent / "extensions_config.json"
            if path.exists():
                return path

            # Backward compatibility: check for mcp_config.json
            path = Path(os.getcwd()) / "mcp_config.json"
            if path.exists():
                return path

            path = Path(os.getcwd()).parent / "mcp_config.json"
            if path.exists():
                return path

            # Extensions are optional, so return None if not found
            return None

    @classmethod
    def from_file(cls, config_path: str | None = None) -> "ExtensionsConfig":
        """从JSON文件加载扩展配置

        **加载流程**：
        1. 解析配置文件路径
        2. 读取并解析JSON
        3. 递归替换环境变量
        4. 验证并返回配置对象

        **为什么文件不存在时返回空配置**：
        - 扩展是可选的
        - 不应该阻止系统启动
        - 空配置表示"无扩展"

        **为什么环境变量未解析时存储空字符串**：
        - 下游消费者不应收到$VAR字面值
        - 空字符串是明确的"无值"信号
        - 比抛出异常更宽容

        Args:
            config_path: 扩展配置文件路径

        Returns:
            加载的ExtensionsConfig，文件不存在返回空配置
        """
        resolved_path = cls.resolve_config_path(config_path)
        if resolved_path is None:
            # Return empty config if extensions config file is not found
            return cls(mcp_servers={}, skills={})

        try:
            with open(resolved_path, encoding="utf-8") as f:
                config_data = json.load(f)
            cls.resolve_env_variables(config_data)
            return cls.model_validate(config_data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Extensions config file at {resolved_path} is not valid JSON: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to load extensions config from {resolved_path}: {e}") from e

    @classmethod
    def resolve_env_variables(cls, config: dict[str, Any]) -> dict[str, Any]:
        """递归解析配置中的环境变量

        **环境变量语法**：$VAR_NAME
        - 递归处理字典和列表
        - 未找到的环境变量替换为空字符串
        - 原地修改字典

        **为什么与AppConfig实现不同**：
        - AppConfig抛出异常（配置是必需的）
        - 这里返回空字符串（扩展是可选的）
        - 更宽容的错误处理

        **使用场景**：
        - OAuth密钥通过环境变量注入
        - MCP服务器URL可配置
        - 避免硬编码敏感信息

        Args:
            config: 需要解析环境变量的配置字典

        Returns:
            解析后的配置字典（原地修改）
        """
        for key, value in config.items():
            if isinstance(value, str):
                if value.startswith("$"):
                    env_value = os.getenv(value[1:])
                    if env_value is None:
                        # Unresolved placeholder — store empty string so downstream
                        # consumers (e.g. MCP servers) don't receive the literal "$VAR"
                        # token as an actual environment value.
                        config[key] = ""
                    else:
                        config[key] = env_value
                else:
                    config[key] = value
            elif isinstance(value, dict):
                config[key] = cls.resolve_env_variables(value)
            elif isinstance(value, list):
                config[key] = [cls.resolve_env_variables(item) if isinstance(item, dict) else item for item in value]
        return config

    def get_enabled_mcp_servers(self) -> dict[str, McpServerConfig]:
        """获取所有启用的MCP服务器

        **为什么需要过滤**：
        - 配置可能包含禁用的服务器
        - 只连接启用的服务器
        - 节省资源

        **使用场景**：
        - 初始化MCP客户端
        - 显示可用服务器列表
        - UI渲染

        Returns:
            启用的MCP服务器字典
        """
        return {name: config for name, config in self.mcp_servers.items() if config.enabled}

    def is_skill_enabled(self, skill_name: str, skill_category: str) -> bool:
        """检查技能是否启用

        **默认启用策略**：
        - public技能：默认启用（社区贡献）
        - custom技能：默认启用（用户自定义）
        - 其他技能：需要显式配置

        **为什么按类别区分**：
        - public和custom是可信来源
    - 避免配置膨胀
    - 新技能自动可用

        Args:
            skill_name: 技能名称
            skill_category: 技能类别

        Returns:
            启用返回True，否则返回False
        """
        skill_config = self.skills.get(skill_name)
        if skill_config is None:
            # Default to enable for public & custom skill
            return skill_category in ("public", "custom")
        return skill_config.enabled


_extensions_config: ExtensionsConfig | None = None


def get_extensions_config() -> ExtensionsConfig:
    """获取扩展配置实例

    **单例模式**：
    - 首次调用时从文件加载
    - 后续调用返回缓存实例
    - 使用reload强制重载

    **为什么使用单例**：
    - 扩展配置是全局资源
    - 避免重复读取文件
    - 确保一致性

    Returns:
        缓存的ExtensionsConfig实例
    """
    global _extensions_config
    if _extensions_config is None:
        _extensions_config = ExtensionsConfig.from_file()
    return _extensions_config


def reload_extensions_config(config_path: str | None = None) -> ExtensionsConfig:
    """从文件重新加载扩展配置

    **使用场景**：
    - 配置文件被修改后立即生效
    - 不重启服务更新扩展
    - 测试时切换配置

    Args:
        config_path: 可选的配置文件路径

    Returns:
        新加载的ExtensionsConfig实例
    """
    global _extensions_config
    _extensions_config = ExtensionsConfig.from_file(config_path)
    return _extensions_config


def reset_extensions_config() -> None:
    """重置缓存的扩展配置实例

    **使用场景**：
    - 测试后清理状态
    - 强制下次重新加载
    - 切换配置前重置

    **为什么需要重置**：
    - 单例模式需要清理机制
    - 测试隔离需要
    - 调试时可能需要
    """
    global _extensions_config
    _extensions_config = None


def set_extensions_config(config: ExtensionsConfig) -> None:
    """设置自定义扩展配置实例

    **使用场景**：
    - 单元测试注入mock配置
    - 绕过文件系统
    - 动态配置

    Args:
        config: 要使用的ExtensionsConfig实例
    """
    global _extensions_config
    _extensions_config = config
