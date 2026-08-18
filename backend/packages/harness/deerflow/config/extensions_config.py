"""Unified extensions configuration for MCP servers and skills."""

import errno
import json
import logging
import os
import stat
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from deerflow.config.runtime_paths import existing_project_file
from deerflow.constants import (
    DEFAULT_MCP_SESSION_INIT_TIMEOUT,
    MCP_TASK_NAME_MAX_LENGTH,
    MCP_TASK_SERVER_NAME_MAX_LENGTH,
)

logger = logging.getLogger(__name__)

_non_atomic_fallback_targets: set[Path] = set()
_non_atomic_fallback_targets_lock = threading.Lock()


def normalize_mcp_transport_alias(data: Any) -> Any:
    """Promote MCP-spec ``transport`` to ``type`` when ``type`` is absent."""
    if isinstance(data, dict):
        transport = data.get("transport")
        if transport and not data.get("type"):
            return {**data, "type": transport}
    return data


class McpRoutingConfig(BaseModel):
    """Soft routing hints for MCP tool preference."""

    mode: Literal["off", "prefer"] = Field(
        default="off",
        description="Whether to emit prompt hints preferring this MCP tool for matching requests.",
    )
    priority: int = Field(
        default=0,
        description="Ordering key for routing hints. Higher values are rendered first.",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Operator-authored keywords that describe when this MCP tool should be preferred.",
    )
    model_config = ConfigDict(extra="forbid")

    @field_validator("priority")
    @classmethod
    def _clamp_priority(cls, value: int) -> int:
        if value < 0:
            logger.warning("MCP routing priority %s is below 0; clamping to 0.", value)
            return 0
        if value > 100:
            logger.warning("MCP routing priority %s is above 100; clamping to 100.", value)
            return 100
        return value


class McpToolOverride(BaseModel):
    """Per-tool MCP configuration overrides."""

    routing: McpRoutingConfig = Field(default_factory=McpRoutingConfig)
    model_config = ConfigDict(extra="allow")


class McpTaskToolsetConfig(BaseModel):
    """One ordinary submit/status/cancel contract exposed by an MCP server.

    Tool names are the exact raw names advertised by that server. The
    presentation prefix added by ``langchain-mcp-adapters`` is deliberately not
    part of this durable binding.
    """

    name: str = Field(
        min_length=1,
        max_length=MCP_TASK_NAME_MAX_LENGTH,
        description="Stable local name shown for tasks from this toolset",
    )
    submit_tool: str = Field(min_length=1, description="Raw MCP tool name used to submit work")
    status_tool: str = Field(min_length=1, description="Raw MCP tool name used to poll work")
    cancel_tool: str = Field(min_length=1, description="Raw MCP tool name used to cancel work")
    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def _validate_name_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("MCP task toolset name must not be empty")
        return value


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
    routing: McpRoutingConfig = Field(default_factory=McpRoutingConfig, description="Soft routing hints for tools from this MCP server")
    tools: dict[str, McpToolOverride] = Field(default_factory=dict, description="Per-original-tool MCP configuration overrides")
    tool_name_prefix: bool = Field(
        default=True,
        description="Whether to prefix discovered tool names with the MCP server name to avoid cross-server collisions",
    )
    tool_call_timeout: float | None = Field(
        default=None,
        description=("Timeout in seconds for individual stdio MCP tool calls and durable-task calls on every transport. Other HTTP/SSE tools use transport-level timeouts. None means no call-level timeout."),
    )
    session_init_timeout: float | None = Field(
        default=DEFAULT_MCP_SESSION_INIT_TIMEOUT,
        description=(
            "Timeout in seconds for MCP server bring-up: tool discovery (subprocess spawn + initialize + tools/list) "
            "and persistent stdio session initialization, plus ephemeral HTTP/SSE durable-task session "
            "initialization. Defaults to DEFAULT_MCP_SESSION_INIT_TIMEOUT so a hung server cannot block agent "
            "construction or the task poller indefinitely. None means no timeout."
        ),
    )
    task_toolsets: list[McpTaskToolsetConfig] = Field(
        default_factory=list,
        description="Ordinary submit/status/cancel tool groups managed by the durable MCP task runtime",
    )
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _accept_transport_alias(cls, data: Any) -> Any:
        """Accept the MCP-spec ``transport`` field as an alias for ``type``.

        The official MCP configuration schema uses ``transport`` to indicate
        the transport mechanism (``stdio``/``sse``/``http``). Earlier versions
        of this project only honored ``type``, which caused remote SSE/HTTP
        servers configured with just ``transport`` to be incorrectly treated as
        ``stdio`` (the default). This validator normalizes the two so either
        spelling works, with ``type`` taking precedence when both are provided.
        """
        return normalize_mcp_transport_alias(data)

    @model_validator(mode="after")
    def _validate_task_tool_bindings(self) -> "McpServerConfig":
        claimed: dict[str, str] = {}
        for toolset in self.task_toolsets:
            for role in ("submit_tool", "status_tool", "cancel_tool"):
                raw_name = getattr(toolset, role)
                previous = claimed.get(raw_name)
                if previous is not None:
                    raise ValueError(f"MCP task tool {raw_name!r} must be unique across task_toolsets and roles; it is configured as both {previous} and {toolset.name}.{role}")
                claimed[raw_name] = f"{toolset.name}.{role}"
        return self


def resolve_effective_mcp_routing(server_config: McpServerConfig | None, original_tool_name: str) -> dict[str, Any]:
    """Merge server-level routing with per-tool overrides for one MCP tool."""
    if server_config is None:
        return McpRoutingConfig().model_dump(mode="json")

    effective = server_config.routing.model_dump(mode="json")
    override = server_config.tools.get(original_tool_name)
    if override is not None and "routing" in override.model_fields_set:
        effective.update(override.routing.model_dump(mode="json", exclude_unset=True))
    return effective


class SkillStateConfig(BaseModel):
    """Configuration for a single skill's state."""

    enabled: bool = Field(default=True, description="Whether this skill is enabled")


class ExtensionsConfig(BaseModel):
    """Unified configuration for MCP servers and skills."""

    middlewares: list[str] = Field(
        default_factory=list,
        description="AgentMiddleware class paths loaded into the lead-agent middleware chain. Each entry uses 'module.path:ClassName'.",
    )
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

    @model_validator(mode="after")
    def _validate_task_server_names_fit_storage(self) -> "ExtensionsConfig":
        for server_name, server in self.mcp_servers.items():
            if not server.task_toolsets:
                continue
            if not server_name.strip() or len(server_name) > MCP_TASK_SERVER_NAME_MAX_LENGTH:
                raise ValueError(f"MCP task server name must contain 1 to {MCP_TASK_SERVER_NAME_MAX_LENGTH} characters")
        return self

    def to_file_dict(self) -> dict[str, Any]:
        """Serialize in the public extensions_config.json shape."""
        return self.model_dump(by_alias=True)

    @classmethod
    def resolve_config_path(cls, config_path: str | None = None) -> Path | None:
        """Resolve the extensions config file path.

        Priority:
        1. If provided `config_path` argument, use it.
        2. If provided `DEER_FLOW_EXTENSIONS_CONFIG_PATH` environment variable, use it.
        3. Otherwise, search the caller project root for `extensions_config.json`, then `mcp_config.json`.
        4. For backward compatibility, also search legacy backend/repository-root defaults.
        5. If not found via search, return None (extensions are optional).

        Args:
            config_path: Optional path to extensions config file.

        Resolution order:
            1. If provided `config_path` argument, use it.
            2. If provided `DEER_FLOW_EXTENSIONS_CONFIG_PATH` environment variable, use it.
            3. Otherwise, search the caller project root for
               `extensions_config.json`, then legacy `mcp_config.json`.
            4. Finally, search backend/repository-root defaults for monorepo compatibility.

        Returns:
            Path to the extensions config file if found via the resolution
            order above.

            An explicit `config_path` argument or a set
            `DEER_FLOW_EXTENSIONS_CONFIG_PATH` is an operator assertion that
            one particular file must be used, so a missing file in either of
            those two modes raises ``FileNotFoundError`` (see Raises below)
            instead of degrading to "no config" — a bad Docker mount, typo,
            or deleted production config should surface as a loud, actionable
            error rather than silently starting with every MCP server and
            skill absent.

            Only the fallback *search* mode (no explicit argument and no env
            var set) returns ``None`` when nothing is found: that case means
            extensions were never configured in the first place, which is the
            legitimate "extensions are optional" case some callers (e.g. the
            MCP tools-cache staleness check in `deerflow.mcp.cache`) rely on
            as a clean, expected signal.

        Raises:
            FileNotFoundError: If `config_path` is given, or
                `DEER_FLOW_EXTENSIONS_CONFIG_PATH` is set, and the resolved
                path does not exist.
        """
        if config_path:
            path = Path(config_path)
            if not path.exists():
                raise FileNotFoundError(f"Extensions config file specified by param `config_path` not found at {path}")
            return path
        elif env_path := os.getenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH"):
            path = Path(env_path)
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

            # Extensions are optional: unlike the explicit config_path/env-var
            # branches above, finding nothing here is the expected case, so
            # return None rather than raising.
            return None

    @classmethod
    def from_file(cls, config_path: str | None = None) -> "ExtensionsConfig":
        """Load extensions config from JSON file.

        See `resolve_config_path` for more details.

        Args:
            config_path: Path to the extensions config file.

        Returns:
            ExtensionsConfig: The loaded config, or empty config if file not found.
        """
        resolved_path = cls.resolve_config_path(config_path)
        if resolved_path is None:
            # Return empty config if extensions config file is not found
            return cls(mcp_servers={}, skills={})

        try:
            with open(resolved_path, encoding="utf-8") as f:
                config_data = json.load(f)
            config_data = cls.resolve_env_variables(config_data)
            return cls.model_validate(config_data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Extensions config file at {resolved_path} is not valid JSON: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to load extensions config from {resolved_path}: {e}") from e

    @classmethod
    def resolve_env_variables(cls, config: Any) -> Any:
        """Recursively resolve environment variables in the config.

        Environment variables are resolved using the `os.getenv` function. Example: $OPENAI_API_KEY

        Args:
            config: The config to resolve environment variables in.

        Returns:
            The config with environment variables resolved.
        """
        if isinstance(config, str):
            if not config.startswith("$"):
                return config
            env_value = os.getenv(config[1:])
            if env_value is None:
                # Unresolved placeholder — store empty string so downstream
                # consumers (e.g. MCP servers) don't receive the literal "$VAR"
                # token as an actual environment value.
                return ""
            return env_value

        if isinstance(config, dict):
            return {key: cls.resolve_env_variables(value) for key, value in config.items()}

        if isinstance(config, list):
            return [cls.resolve_env_variables(item) for item in config]

        if isinstance(config, tuple):
            return tuple(cls.resolve_env_variables(item) for item in config)

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
            skill_category: Category of the skill (public, custom, or legacy)

        Returns:
            True if enabled, False otherwise.

        Note:
            All skill categories (public, custom, legacy) respect the
            extensions_config enabled/disabled state.  When no explicit
            entry exists, skills default to enabled.
        """
        skill_config = self.skills.get(skill_name)
        if skill_config is None:
            # Default to enabled for all skill categories
            return skill_category in ("public", "custom", "legacy", "integrations")
        return skill_config.enabled


_extensions_config: ExtensionsConfig | None = None


def _fsync_directory_best_effort(directory: Path) -> None:
    """Persist a directory entry update where the platform supports it."""
    if os.name == "nt":
        return

    try:
        directory_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return

    try:
        os.fsync(directory_fd)
    except OSError:
        logger.debug("Could not fsync extensions config directory: %s", directory, exc_info=True)
    finally:
        try:
            os.close(directory_fd)
        except OSError:
            logger.debug("Could not close extensions config directory: %s", directory, exc_info=True)


def _overwrite_in_place(target_path: Path, source_path: Path) -> None:
    """Copy *source_path* onto *target_path* without unlinking the destination inode.

    Fallback for destinations that cannot be replaced by rename — see
    :func:`atomic_write_extensions_config`. This deliberately truncates the
    live file, so a crash mid-write leaves it short; the caller only reaches
    this path when the atomic route is impossible.
    """
    payload = source_path.read_bytes()
    with open(target_path, "wb") as target_file:
        target_file.write(payload)
        target_file.flush()
        os.fsync(target_file.fileno())


def _log_non_atomic_fallback(target_path: Path) -> None:
    """Warn once per target when a bind mount forces the unsafe write path."""
    warning_key = target_path.resolve(strict=False)
    with _non_atomic_fallback_targets_lock:
        first_fallback = warning_key not in _non_atomic_fallback_targets
        _non_atomic_fallback_targets.add(warning_key)

    logger.log(
        logging.WARNING if first_fallback else logging.DEBUG,
        "Cannot atomically replace %s (it is a bind-mount point); overwriting in place. A crash during this write can leave the file truncated.",
        target_path,
    )


def atomic_write_extensions_config(path: Path, data: dict[str, Any]) -> None:
    """Write extensions config without exposing a truncated or partial file.

    Falls back to a non-atomic in-place overwrite when the destination is a
    bind-mounted file: Docker mounts ``extensions_config.json`` as its own
    mount point, and the kernel refuses to rename over a mount point with
    ``EBUSY`` regardless of whether the mount is read-only. Without the
    fallback every Gateway write to this file fails in the production
    compose stack (MCP enable/disable, ``PUT``/``PATCH /api/mcp/config``,
    skill updates), contradicting the documented promise that the file is
    editable at runtime through the API.
    """
    path = Path(path)
    target_path = path.resolve(strict=False) if path.is_symlink() else path
    target_path.parent.mkdir(parents=True, exist_ok=True)

    existing_mode: int | None = None
    try:
        existing_mode = stat.S_IMODE(target_path.stat().st_mode)
    except FileNotFoundError:
        pass

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(data, temporary_file, indent=2)
            if existing_mode is not None:
                temporary_path.chmod(existing_mode)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        try:
            os.replace(temporary_path, target_path)
        except OSError as exc:
            if exc.errno != errno.EBUSY:
                raise
            _log_non_atomic_fallback(target_path)
            _overwrite_in_place(target_path, temporary_path)
        _fsync_directory_best_effort(target_path.parent)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Could not remove temporary extensions config file: %s",
                    temporary_path,
                    exc_info=True,
                )


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


#: Serializes read-modify-write cycles on ``extensions_config.json`` across every
#: writer. Both the skills router (skill enable/disable) and the MCP router
#: (server config updates) read this file, merge a change and write it back.
#: While each RMW ran inline on the event loop they were implicitly serialized;
#: once a writer offloads its RMW to a worker thread the loop is free to
#: interleave the other writer inside the read->write window, and the second
#: write silently drops the first one's change.
#:
#: This is a ``threading.Lock`` rather than an ``asyncio.Lock``, and it must be
#: acquired *inside* the worker that performs the RMW. An asyncio lock held
#: around ``await asyncio.to_thread(...)`` protects only the awaiting task: if
#: that task is cancelled the context manager releases immediately while the
#: worker thread keeps writing, letting a second writer in. Owning the lock from
#: the worker keeps it held until the write and reload actually finish. It also
#: has no event-loop affinity, so writers running on different loops still
#: exclude each other.
extensions_config_write_lock = threading.Lock()


@contextmanager
def extensions_config_file_lock(path: Path) -> Iterator[None]:
    """Exclude read-modify-write cycles in other Gateway processes.

    ``extensions_config_write_lock`` serializes threads in this process. This
    sidecar advisory lock extends the same critical section across worker
    processes and separate embedded clients that share the config directory.
    Callers must hold both locks around the complete read, merge, write, and
    reload cycle; locking only the final atomic replace still permits lost
    updates.
    """
    target_path = Path(path)
    target_path = target_path.resolve(strict=False) if target_path.is_symlink() else target_path.absolute()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target_path.parent / f".{target_path.name}.lock"

    with open(lock_path, "a+b") as lock_file:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

        try:
            yield
        finally:
            if os.name == "nt":
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


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
