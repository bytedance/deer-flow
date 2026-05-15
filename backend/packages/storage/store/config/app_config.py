import logging
import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Self

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from store.config.storage_config import StorageConfig

load_dotenv()

logger = logging.getLogger(__name__)


def _default_config_candidates() -> tuple[Path, ...]:
    """Return deterministic config.yaml locations without relying on cwd."""
    backend_dir = Path(__file__).resolve().parents[4]
    repo_root = backend_dir.parent
    cwd = Path.cwd().resolve()
    candidates = (
        cwd / "config.yaml",
        backend_dir / "config.yaml",
        repo_root / "config.yaml",
    )
    return tuple(dict.fromkeys(candidates))


def _storage_from_database_config(config_data: dict[str, Any]) -> None:
    """Keep the existing public `database:` config compatible with storage."""
    if "storage" in config_data:
        return

    database = config_data.get("database")
    if not isinstance(database, dict):
        return

    backend = database.get("backend")
    if backend == "memory":
        raise ValueError("database.backend='memory' is not supported by storage; handle memory mode before loading storage config")

    storage: dict[str, Any] = {
        "driver": "postgres" if backend == "postgres" else backend,
        "sqlite_dir": database.get("sqlite_dir", ".deer-flow/data"),
        "echo_sql": database.get("echo_sql", False),
        "pool_size": database.get("pool_size", 5),
    }

    postgres_url = database.get("postgres_url")
    if backend == "postgres" and isinstance(postgres_url, str) and postgres_url:
        from sqlalchemy.engine.url import make_url

        parsed = make_url(postgres_url)
        storage["database_url"] = postgres_url
        storage.update(
            {
                "username": parsed.username or "",
                "password": parsed.password or "",
                "host": parsed.host or "localhost",
                "port": parsed.port or 5432,
                "db_name": parsed.database or "deerflow",
            }
        )

    config_data["storage"] = storage


class AppConfig(BaseModel):
    """DeerFlow application configuration."""

    timezone: str = Field(default="UTC", description="Timezone for scheduling and timestamps (e.g. 'UTC', 'America/New_York')")
    log_level: str = Field(default="info", description="Logging level for deerflow modules (debug/info/warning/error)")
    storage: StorageConfig = Field(default=StorageConfig())
    model_config = ConfigDict(extra="allow", frozen=False)

    @classmethod
    def resolve_config_path(cls, config_path: str | None = None) -> Path:
        """Resolve the config file path.

        Priority:
        1. If provided `config_path` argument, use it.
        2. If provided `DEER_FLOW_CONFIG_PATH` environment variable, use it.
        3. Otherwise, search deterministic backend/repository-root defaults from `_default_config_candidates()`.
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
            for path in _default_config_candidates():
                if path.exists():
                    return path
            raise FileNotFoundError("`config.yaml` file not found at the default backend or repository root locations")

    @classmethod
    def from_file(cls, config_path: str | None = None) -> Self:
        """Load and validate config from YAML. See `resolve_config_path` for path resolution."""
        resolved_path = cls.resolve_config_path(config_path)
        with open(resolved_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}

        cls._check_config_version(config_data, resolved_path)

        config_data = cls.resolve_env_variables(config_data)
        _storage_from_database_config(config_data)

        if os.getenv("TIMEZONE"):
            config_data["timezone"] = os.getenv("TIMEZONE")

        result = cls.model_validate(config_data)
        return result

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
        """Recursively replace $VAR strings with their environment variable values (e.g. $OPENAI_API_KEY)."""
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
    """Force reload from file and update the cache."""
    return _load_and_cache_app_config(config_path)


def reset_app_config() -> None:
    """Clear the cache so the next `get_app_config()` reloads from file."""
    global _app_config, _app_config_path, _app_config_mtime, _app_config_is_custom
    _app_config = None
    _app_config_path = None
    _app_config_mtime = None
    _app_config_is_custom = False


def set_app_config(config: AppConfig) -> None:
    """Inject a config instance directly, bypassing file loading (for testing)."""
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
