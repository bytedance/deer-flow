import logging
import os
from collections.abc import Mapping
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Self

import yaml
from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from deerflow.config.acp_config import ACPAgentConfig, load_acp_config_from_dict
from deerflow.config.agents_api_config import AgentsApiConfig, load_agents_api_config_from_dict
from deerflow.config.audio_input_config import AudioInputConfig, load_audio_input_config_from_dict
from deerflow.config.auth_config import AuthConfig, load_auth_config_from_dict
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.checkpointer_config import CheckpointerConfig, load_checkpointer_config_from_dict
from deerflow.config.content_safety_config import ContentSafetyConfig, load_content_safety_config_from_dict
from deerflow.config.cost_config import CostConfig, load_cost_config_from_dict
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.guardrails_config import GuardrailsConfig, load_guardrails_config_from_dict
from deerflow.config.http_connector_config import HttpConnectorConfig
from deerflow.config.memory_config import MemoryConfig, load_memory_config_from_dict
from deerflow.config.session_memory_config import SessionMemoryConfig, load_session_memory_config_from_dict
from deerflow.config.domain_memory_config import DomainMemoryConfig, load_domain_memory_config_from_dict
from deerflow.config.memory_api_config import MemoryApiConfig, load_memory_api_config_from_dict
from deerflow.config.model_config import ModelConfig
from deerflow.config.nacos_config import NacosConfig, load_nacos_config_from_dict
from deerflow.config.rag_config import RagConfig, load_rag_config_from_dict
from deerflow.config.rate_limit_config import RateLimitConfig, load_rate_limit_config_from_dict
from deerflow.config.rpc_config import RpcConfig, load_rpc_config_from_dict
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.skill_evolution_config import SkillEvolutionConfig
from deerflow.config.skills_config import SkillsConfig
from deerflow.config.stream_bridge_config import StreamBridgeConfig, load_stream_bridge_config_from_dict
from deerflow.config.subagents_config import SubagentsAppConfig, load_subagents_config_from_dict
from deerflow.config.summarization_config import SummarizationConfig, load_summarization_config_from_dict
from deerflow.config.title_config import TitleConfig, load_title_config_from_dict
from deerflow.config.token_usage_config import TokenUsageConfig
from deerflow.config.tool_config import ToolConfig, ToolGroupConfig
from deerflow.config.tool_search_config import ToolSearchConfig, load_tool_search_config_from_dict
from deerflow.config.runtime_paths import existing_project_file

load_dotenv(find_dotenv(usecwd=True))

logger = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    """Raised when configuration validation fails in production mode."""
    pass


CONFIG_FILE_DATABASE_DEFAULTS = {
    "backend": "sqlite",
    "sqlite_dir": ".deer-flow/data",
}


class CircuitBreakerConfig(BaseModel):
    """Configuration for the LLM Circuit Breaker."""

    failure_threshold: int = Field(default=5, description="Number of consecutive failures before tripping the circuit")
    recovery_timeout_sec: int = Field(default=60, description="Time in seconds before attempting to recover the circuit")


def _legacy_config_candidates() -> tuple[Path, ...]:
    """Return source-tree config.yaml locations for monorepo compatibility."""
    backend_dir = Path(__file__).resolve().parents[4]
    repo_root = backend_dir.parent
    return (backend_dir / "config.yaml", repo_root / "config.yaml")


def logging_level_from_config(name: str | None) -> int:
    """Map ``config.yaml`` ``log_level`` string to a :mod:`logging` level constant."""
    mapping = logging.getLevelNamesMapping()
    return mapping.get((name or "info").strip().upper(), logging.INFO)


def apply_logging_level(name: str | None) -> None:
    """Resolve *name* to a logging level and apply it to the ``deerflow``/``app`` logger hierarchies.

    Only the ``deerflow`` and ``app`` logger levels are changed so that
    third-party library verbosity (e.g. uvicorn, sqlalchemy) is not
    affected. Root handler levels are lowered (never raised) so that
    messages from the configured loggers can propagate through without
    being filtered, while preserving handler thresholds that may be
    intentionally restrictive for third-party log output.
    """
    level = logging_level_from_config(name)
    for logger_name in ("deerflow", "app"):
        logging.getLogger(logger_name).setLevel(level)
    for handler in logging.root.handlers:
        if level < handler.level:
            handler.setLevel(level)


class AppConfig(BaseModel):
    """Config for the DeerFlow application"""

    log_level: str = Field(default="info", description="Logging level for deerflow and app modules (debug/info/warning/error); third-party libraries are not affected")
    token_usage: TokenUsageConfig = Field(default_factory=TokenUsageConfig, description="Token usage tracking configuration")
    models: list[ModelConfig] = Field(default_factory=list, description="Available models")
    sandbox: SandboxConfig = Field(description="Sandbox configuration")
    tools: list[ToolConfig] = Field(default_factory=list, description="Available tools")
    tool_groups: list[ToolGroupConfig] = Field(default_factory=list, description="Available tool groups")
    skills: SkillsConfig = Field(default_factory=SkillsConfig, description="Skills configuration")
    skill_evolution: SkillEvolutionConfig = Field(default_factory=SkillEvolutionConfig, description="Agent-managed skill evolution configuration")
    extensions: ExtensionsConfig = Field(default_factory=ExtensionsConfig, description="Extensions configuration (MCP servers and skills state)")
    tool_search: ToolSearchConfig = Field(default_factory=ToolSearchConfig, description="Tool search / deferred loading configuration")
    title: TitleConfig = Field(default_factory=TitleConfig, description="Automatic title generation configuration")
    summarization: SummarizationConfig = Field(default_factory=SummarizationConfig, description="Conversation summarization configuration")
    memory: MemoryConfig = Field(default_factory=MemoryConfig, description="Memory subsystem configuration")
    session_memory: SessionMemoryConfig = Field(default_factory=SessionMemoryConfig, description="Session memory subsystem configuration (thread-scoped)")
    domain_memory: DomainMemoryConfig = Field(default_factory=DomainMemoryConfig, description="Domain memory subsystem configuration (entity-scoped)")
    memory_api: MemoryApiConfig = Field(default_factory=MemoryApiConfig, description="Memory API and UI configuration")
    rag: RagConfig = Field(default_factory=RagConfig, description="RAG (embedding + vector store) subsystem configuration")
    agents_api: AgentsApiConfig = Field(default_factory=AgentsApiConfig, description="Custom-agent management API configuration")
    acp_agents: dict[str, ACPAgentConfig] = Field(default_factory=dict, description="ACP-compatible agent configuration")
    subagents: SubagentsAppConfig = Field(default_factory=SubagentsAppConfig, description="Subagent runtime configuration")
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig, description="Guardrail middleware configuration")
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig, description="LLM circuit breaker configuration")
    auth: AuthConfig = Field(default_factory=AuthConfig, description="API authentication configuration")
    database: DatabaseConfig = Field(default_factory=DatabaseConfig, description="Database backend configuration")
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig, description="API rate limiting configuration")
    content_safety: ContentSafetyConfig = Field(default_factory=ContentSafetyConfig, description="Content safety moderation configuration")
    cost: CostConfig = Field(default_factory=CostConfig, description="Cost management and budget control configuration")
    audio_input: AudioInputConfig = Field(default_factory=AudioInputConfig, description="Chat audio input and transcription configuration")
    model_config = ConfigDict(extra="allow", frozen=False)
    checkpointer: CheckpointerConfig | None = Field(default=None, description="Checkpointer configuration")
    stream_bridge: StreamBridgeConfig | None = Field(default=None, description="Stream bridge configuration")
    http_connectors: dict[str, list[HttpConnectorConfig]] = Field(default_factory=dict, description="HTTP connectors keyed by tenant_id for external API integration")
    nacos: NacosConfig | None = Field(default=None, description="Nacos service discovery configuration (null = disabled)")
    rpc: RpcConfig | None = Field(default=None, description="Java RPC client configuration (null = disabled)")

    @classmethod
    def resolve_config_path(cls, config_path: str | None = None) -> Path:
        """Resolve the config file path.

        Priority:
        1. If provided `config_path` argument, use it.
        2. If provided `DEER_FLOW_CONFIG_PATH` environment variable, use it.
        3. Otherwise, search the caller project root.
        4. Finally, search legacy backend/repository-root defaults for monorepo compatibility.
        """
        if config_path:
            path = Path(config_path)
            if not Path.exists(path):
                raise FileNotFoundError(f"Config file specified by param `config_path` not found at {path}")
            return path
        elif os.getenv("DEER_FLOW_CONFIG_PATH"):
            path = Path(os.getenv("DEER_FLOW_CONFIG_PATH"))
            if not Path.exists(path):
                raise FileNotFoundError(f"Config file specified by environment variable `DEER_FLOW_CONFIG_PATH` not found at {path}")
            return path
        else:
            project_config = existing_project_file(("config.yaml",))
            if project_config is not None:
                return project_config

            for path in _legacy_config_candidates():
                if path.exists():
                    return path
            raise FileNotFoundError("`config.yaml` file not found in the project root or legacy backend/repository root locations")

    @classmethod
    def from_file(cls, config_path: str | None = None) -> Self:
        """Load config from YAML file.

        See `resolve_config_path` for more details.

        Args:
            config_path: Path to the config file.

        Returns:
            AppConfig: The loaded config.
        """
        resolved_path = cls.resolve_config_path(config_path)
        with open(resolved_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}

        # Check config version before processing
        cls._check_config_version(config_data, resolved_path)

        config_data = cls.resolve_env_variables(config_data)
        cls._apply_database_defaults(config_data)
        cls._validate_postgres_consistency(config_data)

        # Load circuit_breaker config if present
        if "circuit_breaker" in config_data:
            config_data["circuit_breaker"] = config_data["circuit_breaker"]

        # Load extensions config separately (it's in a different file)
        extensions_config = ExtensionsConfig.from_file()
        config_data["extensions"] = extensions_config.model_dump()

        result = cls.model_validate(config_data)
        acp_agents = cls._validate_acp_agents(config_data.get("acp_agents", {}))
        cls._apply_singleton_configs(result, acp_agents)
        return result

    @classmethod
    def _validate_acp_agents(
        cls,
        config_data: Mapping[str, Mapping[str, object]] | None,
    ) -> dict[str, ACPAgentConfig]:
        if config_data is None:
            config_data = {}
        return {name: ACPAgentConfig(**cfg) for name, cfg in config_data.items()}

    @classmethod
    def _apply_singleton_configs(cls, config: Self, acp_agents: dict[str, ACPAgentConfig]) -> None:
        from deerflow.config.checkpointer_config import (
            CheckpointerConfig,
            get_checkpointer_config,
        )

        previous_checkpointer_config = get_checkpointer_config()

        load_auth_config_from_dict(config.auth.model_dump())
        load_title_config_from_dict(config.title.model_dump())
        load_summarization_config_from_dict(config.summarization.model_dump())
        load_memory_config_from_dict(config.memory.model_dump())
        load_session_memory_config_from_dict(config.session_memory.model_dump())
        load_domain_memory_config_from_dict(config.domain_memory.model_dump())
        load_memory_api_config_from_dict(config.memory_api.model_dump())
        load_rag_config_from_dict(config.rag.model_dump())
        load_agents_api_config_from_dict(config.agents_api.model_dump())
        load_subagents_config_from_dict(config.subagents.model_dump())
        load_tool_search_config_from_dict(config.tool_search.model_dump())
        load_cost_config_from_dict(config.cost.model_dump())
        load_guardrails_config_from_dict(config.guardrails.model_dump())
        load_audio_input_config_from_dict(config.audio_input.model_dump())
        load_content_safety_config_from_dict(config.content_safety.model_dump())
        load_rate_limit_config_from_dict(config.rate_limit.model_dump())

        # Derive checkpointer config from database section if no standalone config.
        # This eliminates the need for a separate `checkpointer:` block in config.yaml.
        effective_checkpointer: CheckpointerConfig | None
        if config.checkpointer is not None:
            effective_checkpointer = config.checkpointer
        else:
            db = config.database
            if db.backend == "sqlite":
                effective_checkpointer = CheckpointerConfig(
                    type="sqlite",
                    connection_string=db.checkpointer_sqlite_path,
                )
            elif db.backend == "postgres":
                effective_checkpointer = CheckpointerConfig(
                    type="postgres",
                    connection_string=db.postgres_url,
                )
            else:
                effective_checkpointer = None

        load_checkpointer_config_from_dict(
            effective_checkpointer.model_dump() if effective_checkpointer is not None else None
        )

        load_stream_bridge_config_from_dict(config.stream_bridge.model_dump() if config.stream_bridge is not None else None)
        load_acp_config_from_dict({name: agent.model_dump() for name, agent in acp_agents.items()})
        load_nacos_config_from_dict(config.nacos.model_dump() if config.nacos is not None else None)
        load_rpc_config_from_dict(config.rpc.model_dump() if config.rpc is not None else None)

        if previous_checkpointer_config != effective_checkpointer:
            from deerflow.runtime.checkpointer import reset_checkpointer
            from deerflow.runtime.store import reset_store

            reset_checkpointer()
            reset_store()

    @classmethod
    def _apply_database_defaults(cls, config_data: dict[str, Any]) -> None:
        """Apply config.yaml defaults for persistence when the section is absent.

        When ``database.backend=postgres``, auto-default subsystem backends
        to PostgreSQL-compatible values if not explicitly configured.
        """
        database_config = config_data.get("database")
        if database_config is None:
            database_config = {}
            config_data["database"] = database_config
        if not isinstance(database_config, dict):
            return
        for key, value in CONFIG_FILE_DATABASE_DEFAULTS.items():
            database_config.setdefault(key, value)

        if database_config.get("backend") != "postgres":
            return

        # Auto-default subsystem backends when database.backend=postgres
        auto_defaults: list[tuple[str, str, str]] = []
        skipped: list[tuple[str, str, str]] = []

        # run_events.backend (stored as extra field on AppConfig)
        run_events_config = config_data.get("run_events")
        if run_events_config is None:
            run_events_config = {}
            config_data["run_events"] = run_events_config
        if isinstance(run_events_config, dict):
            if "backend" not in run_events_config:
                run_events_config["backend"] = "db"
                auto_defaults.append(("run_events.backend", "db", "database.backend=postgres"))
            else:
                skipped.append(("run_events.backend", run_events_config["backend"], "explicitly configured"))

        # memory.storage_class
        memory_config = config_data.get("memory")
        if memory_config is None:
            memory_config = {}
            config_data["memory"] = memory_config
        if isinstance(memory_config, dict):
            if "storage_class" not in memory_config:
                memory_config["storage_class"] = "deerflow.agents.memory.storage.StoreMemoryStorage"
                auto_defaults.append(("memory.storage_class", "StoreMemoryStorage", "database.backend=postgres"))
            else:
                skipped.append(("memory.storage_class", memory_config["storage_class"], "explicitly configured"))

        # rag.vector_store_backend
        rag_config = config_data.get("rag")
        if rag_config is None:
            rag_config = {}
            config_data["rag"] = rag_config
        if isinstance(rag_config, dict):
            if "vector_store_backend" not in rag_config:
                rag_config["vector_store_backend"] = "pgvector"
                auto_defaults.append(("rag.vector_store_backend", "pgvector", "database.backend=postgres"))
            else:
                skipped.append(("rag.vector_store_backend", rag_config["vector_store_backend"], "explicitly configured"))

        # cost.storage_backend
        cost_config = config_data.get("cost")
        if cost_config is None:
            cost_config = {}
            config_data["cost"] = cost_config
        if isinstance(cost_config, dict):
            if "storage_backend" not in cost_config:
                cost_config["storage_backend"] = "postgres"
                auto_defaults.append(("cost.storage_backend", "postgres", "database.backend=postgres"))
            else:
                skipped.append(("cost.storage_backend", cost_config["storage_backend"], "explicitly configured"))

        for field, value, reason in auto_defaults:
            logger.info("Auto-defaulted %s=%s from %s", field, value, reason)
        for field, value, reason in skipped:
            logger.info("%s=%s (%s, auto-default skipped)", field, value, reason)

    @classmethod
    def _validate_postgres_consistency(cls, config_data: dict[str, Any]) -> None:
        """Validate that subsystem backends are consistent with database.backend=postgres.

        In production mode (DEER_FLOW_ENV=production): raise ConfigValidationError on split backends.
        In development mode (default): log WARNING on split backends.
        """
        database_config = config_data.get("database")
        if not isinstance(database_config, dict):
            return
        if database_config.get("backend") != "postgres":
            return

        conflicts: list[tuple[str, str, str]] = []

        # Check run_events.backend
        run_events = config_data.get("run_events")
        if isinstance(run_events, dict):
            backend = run_events.get("backend")
            if backend and backend != "db":
                conflicts.append(("run_events.backend", backend, "Set run_events.backend=db or remove to auto-default"))

        # Check memory.storage_class
        memory = config_data.get("memory")
        if isinstance(memory, dict):
            storage_class = memory.get("storage_class", "")
            if storage_class and "FileMemoryStorage" in storage_class:
                conflicts.append(("memory.storage_class", storage_class, "Set memory.storage_class to StoreMemoryStorage or remove to auto-default"))

        # Check rag.vector_store_backend
        rag = config_data.get("rag")
        if isinstance(rag, dict):
            backend = rag.get("vector_store_backend")
            if backend and backend != "pgvector":
                conflicts.append(("rag.vector_store_backend", backend, "Set rag.vector_store_backend=pgvector or remove to auto-default"))

        # Check cost.storage_backend
        cost = config_data.get("cost")
        if isinstance(cost, dict):
            backend = cost.get("storage_backend")
            if backend and backend != "postgres":
                conflicts.append(("cost.storage_backend", backend, "Set cost.storage_backend=postgres or remove to auto-default"))

        if not conflicts:
            return

        env = os.getenv("DEER_FLOW_ENV", "development")
        conflict_details = "; ".join(f"{field}={value} → {fix}" for field, value, fix in conflicts)

        if env == "production":
            raise ConfigValidationError(
                f"Split backend configuration detected in production mode. "
                f"database.backend=postgres requires all subsystem backends to use PostgreSQL-compatible values. "
                f"Conflicts: {conflict_details}. "
                f"See docs/POSTGRESQL_MIGRATION.md#configuration for details."
            )
        else:
            logger.warning(
                "Split backend configuration detected: database.backend=postgres but subsystems use non-PostgreSQL backends. "
                "Conflicts: %s. This is acceptable in development mode but will fail in production (DEER_FLOW_ENV=production).",
                conflict_details,
            )

    @classmethod
    def _check_config_version(cls, config_data: dict, config_path: Path) -> None:
        """Check if the user's config.yaml is outdated compared to config.example.yaml.

        Emits a warning if the user's config_version is lower than the example's.
        Missing config_version is treated as version 0 (pre-versioning).
        """
        try:
            user_version = int(config_data.get("config_version", 0))
        except (TypeError, ValueError):
            user_version = 0

        # Find config.example.yaml by searching config.yaml's directory and its parents
        example_path = None
        search_dir = config_path.parent
        for _ in range(5):  # search up to 5 levels
            candidate = search_dir / "config.example.yaml"
            if candidate.exists():
                example_path = candidate
                break
            parent = search_dir.parent
            if parent == search_dir:
                break
            search_dir = parent
        if example_path is None:
            return

        try:
            with open(example_path, encoding="utf-8") as f:
                example_data = yaml.safe_load(f)
            raw = example_data.get("config_version", 0) if example_data else 0
            try:
                example_version = int(raw)
            except (TypeError, ValueError):
                example_version = 0
        except Exception:
            return

        if user_version < example_version:
            logger.warning(
                "Your config.yaml (version %d) is outdated — the latest version is %d. Run `make config-upgrade` to merge new fields into your config.",
                user_version,
                example_version,
            )

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
            if config.startswith("$"):
                env_value = os.getenv(config[1:])
                if env_value is None:
                    raise ValueError(f"Environment variable {config[1:]} not found for config value {config}")
                return env_value
            return config
        elif isinstance(config, dict):
            return {k: cls.resolve_env_variables(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [cls.resolve_env_variables(item) for item in config]
        return config

    def get_model_config(self, name: str) -> ModelConfig | None:
        """Get the model config by name.

        Args:
            name: The name of the model to get the config for.

        Returns:
            The model config if found, otherwise None.
        """
        return next((model for model in self.models if model.name == name), None)

    def get_tool_config(self, name: str) -> ToolConfig | None:
        """Get the tool config by name.

        Args:
            name: The name of the tool to get the config for.

        Returns:
            The tool config if found, otherwise None.
        """
        return next((tool for tool in self.tools if tool.name == name), None)

    def get_tool_group_config(self, name: str) -> ToolGroupConfig | None:
        """Get the tool group config by name.

        Args:
            name: The name of the tool group to get the config for.

        Returns:
            The tool group config if found, otherwise None.
        """
        return next((group for group in self.tool_groups if group.name == name), None)

    def get_http_connector(self, tenant_id: str, name: str) -> HttpConnectorConfig | None:
        """Get an HTTP connector config by tenant and name."""
        connectors = self.http_connectors.get(tenant_id, [])
        return next((c for c in connectors if c.name == name), None)

    def list_connector_names(self, tenant_id: str) -> list[str]:
        """List available HTTP connector names for a tenant."""
        return [c.name for c in self.http_connectors.get(tenant_id, [])]


# Compatibility singleton layer for code paths that have not yet been
# migrated to explicit ``AppConfig`` threading. New composition roots should
# prefer constructing ``AppConfig`` once and passing it down directly.
_app_config: AppConfig | None = None
_app_config_path: Path | None = None
_app_config_mtime: float | None = None
_app_config_is_custom = False
_current_app_config: ContextVar[AppConfig | None] = ContextVar("deerflow_current_app_config", default=None)
_current_app_config_stack: ContextVar[tuple[AppConfig | None, ...]] = ContextVar("deerflow_current_app_config_stack", default=())


def _get_config_mtime(config_path: Path) -> float | None:
    """Get the modification time of a config file if it exists."""
    try:
        return config_path.stat().st_mtime
    except OSError:
        return None


def _load_and_cache_app_config(config_path: str | None = None) -> AppConfig:
    """Load config from disk and refresh cache metadata."""
    global _app_config, _app_config_path, _app_config_mtime, _app_config_is_custom

    resolved_path = AppConfig.resolve_config_path(config_path)
    _app_config = AppConfig.from_file(str(resolved_path))
    _app_config_path = resolved_path
    _app_config_mtime = _get_config_mtime(resolved_path)
    _app_config_is_custom = False
    return _app_config


def get_app_config() -> AppConfig:
    """Get the DeerFlow config instance.

    Returns a cached singleton instance and automatically reloads it when the
    underlying config file path or modification time changes. Use
    `reload_app_config()` to force a reload, or `reset_app_config()` to clear
    the cache.
    """
    global _app_config, _app_config_path, _app_config_mtime

    runtime_override = _current_app_config.get()
    if runtime_override is not None:
        return runtime_override

    if _app_config is not None and _app_config_is_custom:
        return _app_config

    resolved_path = AppConfig.resolve_config_path()
    current_mtime = _get_config_mtime(resolved_path)

    should_reload = _app_config is None or _app_config_path != resolved_path or _app_config_mtime != current_mtime
    if should_reload:
        if _app_config_path == resolved_path and _app_config_mtime is not None and current_mtime is not None and _app_config_mtime != current_mtime:
            logger.info(
                "Config file has been modified (mtime: %s -> %s), reloading AppConfig",
                _app_config_mtime,
                current_mtime,
            )
        _load_and_cache_app_config(str(resolved_path))
    return _app_config


def reload_app_config(config_path: str | None = None) -> AppConfig:
    """Reload the config from file and update the cached instance.

    This is useful when the config file has been modified and you want
    to pick up the changes without restarting the application.

    Args:
        config_path: Optional path to config file. If not provided,
                     uses the default resolution strategy.

    Returns:
        The newly loaded AppConfig instance.
    """
    return _load_and_cache_app_config(config_path)


def reset_app_config() -> None:
    """Reset the cached config instance.

    This clears the singleton cache, causing the next call to
    `get_app_config()` to reload from file. Useful for testing
    or when switching between different configurations.
    """
    global _app_config, _app_config_path, _app_config_mtime, _app_config_is_custom
    _app_config = None
    _app_config_path = None
    _app_config_mtime = None
    _app_config_is_custom = False


def set_app_config(config: AppConfig) -> None:
    """Set a custom config instance.

    This allows injecting a custom or mock config for testing purposes.

    Args:
        config: The AppConfig instance to use.
    """
    global _app_config, _app_config_path, _app_config_mtime, _app_config_is_custom
    _app_config = config
    _app_config_path = None
    _app_config_mtime = None
    _app_config_is_custom = True


def peek_current_app_config() -> AppConfig | None:
    """Return the runtime-scoped AppConfig override, if one is active."""
    return _current_app_config.get()


def push_current_app_config(config: AppConfig) -> None:
    """Push a runtime-scoped AppConfig override for the current execution context."""
    stack = _current_app_config_stack.get()
    _current_app_config_stack.set(stack + (_current_app_config.get(),))
    _current_app_config.set(config)


def pop_current_app_config() -> None:
    """Pop the latest runtime-scoped AppConfig override for the current execution context."""
    stack = _current_app_config_stack.get()
    if not stack:
        _current_app_config.set(None)
        return
    previous = stack[-1]
    _current_app_config_stack.set(stack[:-1])
    _current_app_config.set(previous)
