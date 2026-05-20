"""Unified extensions configuration for MCP servers and skills."""

import copy
import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from deerflow.config.runtime_paths import existing_project_file, runtime_home

USER_MCP_SETTINGS_FILENAME = "mcp_settings.json"


def _validate_user_id_for_path(user_id: str) -> str:
    """Validate a user id before using it as a path segment."""
    normalized = user_id.strip()
    if not normalized or normalized in {".", ".."} or "/" in normalized or "\\" in normalized or "\x00" in normalized:
        raise ValueError(f"Invalid user_id {user_id!r}: user ids used in paths cannot be empty or contain path separators.")
    return normalized


class McpOAuthConfig(BaseModel):
    """OAuth configuration for an MCP server (HTTP/SSE transports)."""

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
    """Configuration for a single MCP server."""

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
    """Configuration for a single skill's state."""

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
    def user_mcp_settings_path(cls, user_id: str) -> Path:
        """Return the user-level MCP settings path for a user id.

        The file is intentionally separate from the global `extensions_config.json`
        so future call sites can load per-user MCP settings without changing the
        existing global configuration behavior.
        """
        safe_user_id = _validate_user_id_for_path(user_id)
        return runtime_home() / "users" / safe_user_id / USER_MCP_SETTINGS_FILENAME

    @classmethod
    def resolve_user_mcp_settings_path(cls, user_id: str | None = None, user_config_path: str | None = None) -> Path | None:
        """Resolve an existing user-level MCP settings file.

        Args:
            user_id: User id whose settings should be loaded from
                     `{runtime_home}/users/{user_id}/mcp_settings.json`.
            user_config_path: Optional explicit settings file path, mainly useful
                              for tests and future API call sites.

        Returns:
            Path to an existing user MCP settings file, or None if no user file
            should be loaded.
        """
        if user_config_path:
            path = Path(user_config_path)
            if not path.exists():
                raise FileNotFoundError(f"User MCP settings file specified by param `user_config_path` not found at {path}")
            return path
        if user_id is None:
            return None

        path = cls.user_mcp_settings_path(user_id)
        if path.is_file():
            return path
        return None

    @classmethod
    def resolve_config_path(cls, config_path: str | None = None) -> Path | None:
        """Resolve the extensions config file path.

        Priority:
        1. If provided `config_path` argument, use it.
        2. If provided `DEER_FLOW_EXTENSIONS_CONFIG_PATH` environment variable, use it.
        3. Otherwise, search the caller project root for `extensions_config.json`, then `mcp_config.json`.
        4. For backward compatibility, also search legacy backend/repository-root defaults.
        5. If not found, return None (extensions are optional).

        Args:
            config_path: Optional path to extensions config file.

        Resolution order:
            1. If provided `config_path` argument, use it.
            2. If provided `DEER_FLOW_EXTENSIONS_CONFIG_PATH` environment variable, use it.
            3. Otherwise, search the caller project root for
               `extensions_config.json`, then legacy `mcp_config.json`.
            4. Finally, search backend/repository-root defaults for monorepo compatibility.

        Returns:
            Path to the extensions config file if found, otherwise None.
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
            project_config = existing_project_file(("extensions_config.json", "mcp_config.json"))
            if project_config is not None:
                return project_config

            backend_dir = Path(__file__).resolve().parents[4]
            repo_root = backend_dir.parent
            for path in (
                backend_dir / "extensions_config.json",
                repo_root / "extensions_config.json",
                backend_dir / "mcp_config.json",
                repo_root / "mcp_config.json",
            ):
                if path.exists():
                    return path

            # Extensions are optional, so return None if not found
            return None

    @classmethod
    def from_file(cls, config_path: str | None = None, *, user_id: str | None = None, user_config_path: str | None = None) -> "ExtensionsConfig":
        """Load extensions config from JSON file.

        See `resolve_config_path` for more details.

        Args:
            config_path: Path to the extensions config file.
            user_id: Optional user id used to load and merge user-level MCP settings.
            user_config_path: Optional explicit user MCP settings file path.

        Returns:
            ExtensionsConfig: The loaded config, or empty config if file not found.
        """
        resolved_path = cls.resolve_config_path(config_path)
        if resolved_path is None:
            # Return empty config if extensions config file is not found
            config_data: dict[str, Any] = {"mcpServers": {}, "skills": {}}
        else:
            config_data = cls._load_config_data(resolved_path, description="Extensions config file")

        resolved_user_path = cls.resolve_user_mcp_settings_path(user_id=user_id, user_config_path=user_config_path)
        if resolved_user_path is not None:
            user_config_data = cls._load_config_data(resolved_user_path, description="User MCP settings file")
            config_data = cls.merge_user_mcp_settings_data(config_data, user_config_data)

        try:
            cls.resolve_env_variables(config_data)
            return cls.model_validate(config_data)
        except Exception as e:
            source = resolved_path or "empty extensions config"
            raise RuntimeError(f"Failed to load extensions config from {source}: {e}") from e

    @classmethod
    def _load_config_data(cls, path: Path, *, description: str) -> dict[str, Any]:
        """Load raw JSON config data from a file."""
        try:
            with open(path, encoding="utf-8") as f:
                config_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"{description} at {path} is not valid JSON: {e}") from e

        if not isinstance(config_data, dict):
            raise ValueError(f"{description} at {path} must contain a JSON object")
        return config_data

    @classmethod
    def merge_user_mcp_settings_data(cls, base_config: dict[str, Any], user_config: dict[str, Any]) -> dict[str, Any]:
        """Merge user-level MCP server settings into a global extensions config.

        Only `mcpServers` is merged from the user config. Global skills and other
        extension-level fields remain owned by the global config. For an MCP
        server with the same name, user-provided fields override the global server
        fields while unspecified fields are inherited from the global server.
        """
        merged = copy.deepcopy(base_config)
        base_servers_raw = merged.get("mcpServers")
        user_servers_raw = user_config.get("mcpServers")
        base_servers = copy.deepcopy(base_servers_raw) if base_servers_raw is not None else {}
        user_servers = user_servers_raw if user_servers_raw is not None else {}

        if not isinstance(base_servers, dict):
            raise ValueError("Global extensions config field `mcpServers` must be an object")
        if not isinstance(user_servers, dict):
            raise ValueError("User MCP settings field `mcpServers` must be an object")

        for server_name, user_server in user_servers.items():
            base_server = base_servers.get(server_name)
            if isinstance(base_server, dict) and isinstance(user_server, dict):
                base_servers[server_name] = {**base_server, **copy.deepcopy(user_server)}
            else:
                base_servers[server_name] = copy.deepcopy(user_server)

        merged["mcpServers"] = base_servers
        return merged

    @classmethod
    def resolve_env_variables(cls, config: dict[str, Any]) -> dict[str, Any]:
        """Recursively resolve environment variables in the config.

        Environment variables are resolved using the `os.getenv` function. Example: $OPENAI_API_KEY

        Args:
            config: The config to resolve environment variables in.

        Returns:
            The config with environment variables resolved.
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
        """Get only the enabled MCP servers.

        Returns:
            Dictionary of enabled MCP servers.
        """
        return {name: config for name, config in self.mcp_servers.items() if config.enabled}

    def is_skill_enabled(self, skill_name: str, skill_category: str) -> bool:
        """Check if a skill is enabled.

        Args:
            skill_name: Name of the skill
            skill_category: Category of the skill

        Returns:
            True if enabled, False otherwise
        """
        skill_config = self.skills.get(skill_name)
        if skill_config is None:
            # Default to enable for public & custom skill
            return skill_category in ("public", "custom")
        return skill_config.enabled


_extensions_config: ExtensionsConfig | None = None


def get_extensions_config() -> ExtensionsConfig:
    """Get the extensions config instance.

    Returns a cached singleton instance. Use `reload_extensions_config()` to reload
    from file, or `reset_extensions_config()` to clear the cache.

    Returns:
        The cached ExtensionsConfig instance.
    """
    global _extensions_config
    if _extensions_config is None:
        _extensions_config = ExtensionsConfig.from_file()
    return _extensions_config


def reload_extensions_config(config_path: str | None = None) -> ExtensionsConfig:
    """Reload the extensions config from file and update the cached instance.

    This is useful when the config file has been modified and you want
    to pick up the changes without restarting the application.

    Args:
        config_path: Optional path to extensions config file. If not provided,
                     uses the default resolution strategy.

    Returns:
        The newly loaded ExtensionsConfig instance.
    """
    global _extensions_config
    _extensions_config = ExtensionsConfig.from_file(config_path)
    return _extensions_config


def reset_extensions_config() -> None:
    """Reset the cached extensions config instance.

    This clears the singleton cache, causing the next call to
    `get_extensions_config()` to reload from file. Useful for testing
    or when switching between different configurations.
    """
    global _extensions_config
    _extensions_config = None


def set_extensions_config(config: ExtensionsConfig) -> None:
    """Set a custom extensions config instance.

    This allows injecting a custom or mock config for testing purposes.

    Args:
        config: The ExtensionsConfig instance to use.
    """
    global _extensions_config
    _extensions_config = config
