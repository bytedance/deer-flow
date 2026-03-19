"""Unified extensions configuration for MCP servers and skills."""

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class McpOAuthConfig(BaseModel):
    """OAuth configuration for an MCP 服务器 (HTTP/SSE transports)."""

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
    """Configuration for a single MCP 服务器."""

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
    """Configuration for a single skill's 状态."""

    enabled: bool = Field(default=True, description="Whether this skill is enabled")


class ExtensionsConfig(BaseModel):
    """Unified configuration for MCP servers and skills."""

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
        """Resolve the extensions 配置 文件 路径.

        Priority:
        1. If provided `config_path` 参数, use it.
        2. If provided `DEER_FLOW_EXTENSIONS_CONFIG_PATH` 环境 变量, use it.
        3. Otherwise, 检查 for `extensions_config.json` in the 当前 目录, then in the parent 目录.
        4. For backward compatibility, also 检查 for `mcp_config.json` if `extensions_config.json` is not found.
        5. If not found, 返回 None (extensions are optional).

        Args:
            config_path: Optional 路径 to extensions 配置 文件.

        Returns:
            Path to the extensions 配置 文件 if found, otherwise None.
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
            #    Check 如果 the extensions_config.json is in the 当前 目录


            path = Path(os.getcwd()) / "extensions_config.json"
            if path.exists():
                return path

            #    Check 如果 the extensions_config.json is in the parent 目录 of CWD


            path = Path(os.getcwd()).parent / "extensions_config.json"
            if path.exists():
                return path

            #    Backward compatibility: 检查 对于 mcp_config.json


            path = Path(os.getcwd()) / "mcp_config.json"
            if path.exists():
                return path

            path = Path(os.getcwd()).parent / "mcp_config.json"
            if path.exists():
                return path

            #    Extensions are optional, so 返回 None 如果 not found


            return None

    @classmethod
    def from_file(cls, config_path: str | None = None) -> "ExtensionsConfig":
        """Load extensions 配置 from JSON 文件.

        See `resolve_config_path` for more details.

        Args:
            config_path: Path to the extensions 配置 文件.

        Returns:
            ExtensionsConfig: The loaded 配置, or empty 配置 if 文件 not found.
        """
        resolved_path = cls.resolve_config_path(config_path)
        if resolved_path is None:
            #    Return empty 配置 如果 extensions 配置 文件 is not found


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
        """Recursively resolve 环境 variables in the 配置.

        Environment variables are resolved using the `os.getenv` 函数. Example: $OPENAI_API_KEY

        Args:
            配置: The 配置 to resolve 环境 variables in.

        Returns:
            The 配置 with 环境 variables resolved.
        """
        for key, value in config.items():
            if isinstance(value, str):
                if value.startswith("$"):
                    env_value = os.getenv(value[1:])
                    if env_value is None:
                        #    Unresolved placeholder — store empty 字符串 so downstream


                        #    consumers (e.g. MCP servers) don't receive the literal "$VAR"


                        #    token as an actual 环境 值.


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
        """Get only the 已启用 MCP servers.

        Returns:
            Dictionary of 已启用 MCP servers.
        """
        return {name: config for name, config in self.mcp_servers.items() if config.enabled}

    def is_skill_enabled(self, skill_name: str, skill_category: str) -> bool:
        """Check if a skill is 已启用.

        Args:
            skill_name: Name of the skill
            skill_category: Category of the skill

        Returns:
            True if 已启用, False otherwise
        """
        skill_config = self.skills.get(skill_name)
        if skill_config is None:
            #    Default to enable 对于 public & custom skill


            return skill_category in ("public", "custom")
        return skill_config.enabled


_extensions_config: ExtensionsConfig | None = None


def get_extensions_config() -> ExtensionsConfig:
    """Get the extensions 配置 instance.

    Returns a cached singleton instance. Use `reload_extensions_config()` to reload
    from 文件, or `reset_extensions_config()` to clear the 缓存.

    Returns:
        The cached ExtensionsConfig instance.
    """
    global _extensions_config
    if _extensions_config is None:
        _extensions_config = ExtensionsConfig.from_file()
    return _extensions_config


def reload_extensions_config(config_path: str | None = None) -> ExtensionsConfig:
    """Reload the extensions 配置 from 文件 and 更新 the cached instance.

    This is useful when the 配置 文件 has been modified and you want
    to pick 上 the changes without restarting the application.

    Args:
        config_path: Optional 路径 to extensions 配置 文件. If not provided,
                     uses the 默认 resolution strategy.

    Returns:
        The newly loaded ExtensionsConfig instance.
    """
    global _extensions_config
    _extensions_config = ExtensionsConfig.from_file(config_path)
    return _extensions_config


def reset_extensions_config() -> None:
    """Reset the cached extensions 配置 instance.

    This clears the singleton 缓存, causing the 下一个 call to
    `get_extensions_config()` to reload from 文件. Useful for testing
    or when switching between different configurations.
    """
    global _extensions_config
    _extensions_config = None


def set_extensions_config(config: ExtensionsConfig) -> None:
    """Set a custom extensions 配置 instance.

    This allows injecting a custom or mock 配置 for testing purposes.

    Args:
        配置: The ExtensionsConfig instance to use.
    """
    global _extensions_config
    _extensions_config = config
