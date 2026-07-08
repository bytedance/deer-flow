"""
Database Configuration Module.

Provides configuration loading and validation for external database connections.
Supports MySQL, PostgreSQL, and MongoDB with secure credential handling.

Configuration is loaded at three levels:

1. **Global** — ``references/db_connections.txt`` inside the skill root.
   Available to all projects that use this skill.
2. **Local/Project** — ``.echart-skill/db_connections.txt`` inside a project
   directory. Only effective when working inside that project tree.
3. **Legacy** — ``db_connections.txt`` in the current or parent directory.
   Auto-discovered for backward compatibility.

When loading **effective** config, local/project connections override global
connections with the same name. The most specific project wins.

Usage:
    from scripts.db_config import load_config, load_effective_config

    # Auto-discover (backward compatible)
    config = load_config()

    # Load effective merged config (global + current project)
    config = load_effective_config()

    # Load global only
    config = load_global_config()

    profile = config.connections["my_mysql"]
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, SecretStr, field_validator

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_config import get_logger
from scripts.text_config import parse_txt_config

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config file path resolution
# ---------------------------------------------------------------------------
SKILL_ROOT = Path(__file__).resolve().parent.parent
GLOBAL_CONFIG_FILENAME = "db_connections.txt"
GLOBAL_CONFIG_PATH = SKILL_ROOT / "references" / GLOBAL_CONFIG_FILENAME
LEGACY_FILENAME = "db_connections.txt"
PROJECT_DIRNAME = ".echart-skill"


class ConnectionProfile(BaseModel):
    """Single database connection configuration.
    
    Supports two modes:
    1. Full connection_string: "mysql://user:pass@host:port/db"
    2. Individual fields: host, port, database, username, password
    """
    type: Literal["mysql", "postgresql", "mongodb"] = Field(
        description="Database type"
    )
    
    # Either connection_string OR individual fields
    connection_string: Optional[str] = Field(
        default=None,
        description="Full connection string (alternative to individual fields)"
    )
    
    # Individual connection fields
    host: Optional[str] = Field(default=None, description="Database host")
    port: Optional[int] = Field(default=None, description="Database port")
    database: Optional[str] = Field(default=None, description="Database name or path")
    username: Optional[str] = Field(default=None, description="Username for authentication")
    password: Optional[SecretStr] = Field(default=None, description="Password (stored securely)")
    
    # Additional options
    db_schema: Optional[str] = Field(default=None, description="Schema name (PostgreSQL)")
    timeout: float = Field(default=30.0, ge=1.0, le=300.0, description="Connection timeout in seconds")
    
    # MongoDB-specific
    uri: Optional[str] = Field(default=None, description="MongoDB URI (alternative to connection_string)")
    
    model_config = {
        "extra": "forbid"  # Reject unknown fields
    }
    
    @field_validator("connection_string", "uri", mode="before")
    @classmethod
    def resolve_env_in_string(cls, v: Optional[str]) -> Optional[str]:
        """Resolve ${ENV_VAR} placeholders in connection strings."""
        if v is None:
            return None
        return resolve_env_vars(v)
    
    @field_validator("password", mode="before")
    @classmethod
    def resolve_env_in_password(cls, v: Any) -> Optional[SecretStr]:
        """Resolve ${ENV_VAR} placeholders in password."""
        if v is None:
            return None
        if isinstance(v, SecretStr):
            resolved = resolve_env_vars(v.get_secret_value())
            return SecretStr(resolved)
        resolved = resolve_env_vars(str(v))
        return SecretStr(resolved)
    
    def get_connection_string(self) -> str:
        """Build or return the connection string for this profile."""
        if self.connection_string:
            return self.connection_string
        
        if self.type == "mongodb":
            # MongoDB uses URI
            if self.uri:
                return self.uri
            # Build URI from components
            password = self.password.get_secret_value() if self.password else ""
            auth = f"{self.username}:{password}@" if self.username else ""
            return f"mongodb://{auth}{self.host}:{self.port or 27017}/{self.database}"
        
        # MySQL / PostgreSQL
        password = self.password.get_secret_value() if self.password else ""
        auth = f"{self.username}:{password}@" if self.username else ""
        
        if self.type == "mysql":
            return f"mysql+pymysql://{auth}{self.host}:{self.port or 3306}/{self.database}"
        elif self.type == "postgresql":
            return f"postgresql+psycopg2://{auth}{self.host}:{self.port or 5432}/{self.database}"
        
        raise ValueError(f"Unsupported database type: {self.type}")


class DatabaseConfig(BaseModel):
    """Root configuration containing multiple connection profiles."""
    connections: Dict[str, ConnectionProfile] = Field(
        default_factory=dict,
        description="Named connection profiles"
    )


def resolve_env_vars(value: str) -> str:
    """Resolve ${ENV_VAR} placeholders with environment variable values.
    
    Args:
        value: String potentially containing ${VAR} placeholders
        
    Returns:
        String with all placeholders replaced by their values.
        Missing env vars are replaced with empty string.
        
    Examples:
        >>> os.environ["DB_PASS"] = "secret123"
        >>> resolve_env_vars("${DB_PASS}")
        'secret123'
        >>> resolve_env_vars("prefix_${MISSING}_suffix")
        'prefix__suffix'
    """
    if not value:
        return value
    
    pattern = r'\$\{([^}]+)\}'
    
    def replace(match: re.Match) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name, "")
        if not env_value:
            logger.warning(f"Environment variable '{var_name}' not found, using empty string")
        return env_value
    
    return re.sub(pattern, replace, value)


def _discover_config_file() -> str:
    """Auto-discover db_connections.txt in standard locations.

    Search order:
    1. ``db_connections.txt`` in current directory
    2. ``db_connections.txt`` in parent directories (up to 5 levels)
    3. ``.echart-skill/db_connections.txt`` in current directory
    4. ``.echart-skill/db_connections.txt`` in parent directories
    5. ``references/db_connections.txt`` in skill root (global)

    Returns:
        Path to config file

    Raises:
        FileNotFoundError: If no config file found
    """
    candidates: List[Path] = []

    # Legacy locations: db_connections.txt in current and parents
    current = Path.cwd()
    for _ in range(6):
        candidate = current / LEGACY_FILENAME
        if candidate.exists():
            candidates.append(candidate)
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Project locations: .echart-skill/db_connections.txt
    current = Path.cwd()
    for _ in range(6):
        candidate = current / PROJECT_DIRNAME / LEGACY_FILENAME
        if candidate.exists():
            candidates.append(candidate)
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Global location
    if GLOBAL_CONFIG_PATH.exists():
        candidates.append(GLOBAL_CONFIG_PATH)

    if candidates:
        return str(candidates[0])

    raise FileNotFoundError(
        f"Could not find {LEGACY_FILENAME} in current/parent directories, "
        f"in .echart-skill/, or in the global skill config. "
        "Create a db_connections.txt file or use /db add to configure connections."
    )


def _find_all_config_files(cwd: Optional[str] = None) -> List[Path]:
    """Find all database config files that should be merged for effective config.

    Search order (most specific first):
    1. ``db_connections.txt`` in cwd/parent directories (legacy)
    2. ``.echart-skill/db_connections.txt`` in cwd/parent directories (project)
    3. ``references/db_connections.txt`` in skill root (global)

    Args:
        cwd: Current working directory (defaults to actual cwd).

    Returns:
        List of config file paths ordered from most specific to least.
    """
    result: List[Path] = []
    current = Path(cwd or os.getcwd()).resolve()

    # Project locations (most specific — first in list, last in reversed merge → wins)
    search = current
    for _ in range(6):
        candidate = search / PROJECT_DIRNAME / LEGACY_FILENAME
        if candidate.exists() and candidate not in result:
            result.append(candidate)
        parent = search.parent
        if parent == search:
            break
        search = parent

    # Legacy locations
    search = current
    for _ in range(6):
        candidate = search / LEGACY_FILENAME
        if candidate.exists() and candidate not in result:
            result.append(candidate)
        parent = search.parent
        if parent == search:
            break
        search = parent

    # Global (least specific — last in merge order)
    if GLOBAL_CONFIG_PATH.exists() and GLOBAL_CONFIG_PATH not in result:
        result.append(GLOBAL_CONFIG_PATH)

    return result


def load_config(config_path: Optional[str] = None) -> DatabaseConfig:
    """Load database configuration from txt file.

    Auto-discovers db_connections.txt if no path provided.
    Searches current directory, parent directories, .echart-skill/,
    and the skill global config.

    Args:
        config_path: Optional path to config file

    Returns:
        DatabaseConfig with validated connection profiles

    Raises:
        FileNotFoundError: If config file not found
        ValueError: If config validation fails
    """
    if config_path is None:
        config_path = _discover_config_file()

    if not Path(config_path).exists():
        raise FileNotFoundError(f"Database config not found: {config_path}")

    logger.info(f"Loading database config from: {config_path}")

    raw_data = parse_txt_config(config_path)

    # Validate with Pydantic
    config = DatabaseConfig(**raw_data)

    # Log loaded profiles (mask credentials)
    for name, profile in config.connections.items():
        masked_conn = _mask_connection_string(profile.get_connection_string())
        logger.info(f"Loaded connection profile '{name}': {profile.type} ({masked_conn})")

    return config


def load_global_config() -> DatabaseConfig:
    """Load the global database config from the skill root.

    Returns:
        DatabaseConfig from ``references/db_connections.txt``.
        Returns empty config if the file doesn't exist.
    """
    if not GLOBAL_CONFIG_PATH.exists():
        logger.info("Global database config not found, returning empty config")
        return DatabaseConfig()

    logger.info(f"Loading global database config from: {GLOBAL_CONFIG_PATH}")
    raw_data = parse_txt_config(GLOBAL_CONFIG_PATH)
    config = DatabaseConfig(**raw_data)

    for name, profile in config.connections.items():
        masked_conn = _mask_connection_string(profile.get_connection_string())
        logger.info(f"Global connection '{name}': {profile.type} ({masked_conn})")

    return config


def load_local_config(cwd: Optional[str] = None) -> DatabaseConfig:
    """Load local/project database config from ``.echart-skill/db_connections.txt``.

    Searches the current directory and parent directories for project configs.
    Only returns configs from the most specific (closest) project directory.

    Args:
        cwd: Current working directory (defaults to actual cwd).

    Returns:
        DatabaseConfig from the closest ``.echart-skill/db_connections.txt``.
        Returns empty config if not found.
    """
    current = Path(cwd or os.getcwd()).resolve()

    for _ in range(6):
        candidate = current / PROJECT_DIRNAME / LEGACY_FILENAME
        if candidate.exists():
            logger.info(f"Loading local database config from: {candidate}")
            raw_data = parse_txt_config(candidate)
            config = DatabaseConfig(**raw_data)

            for name, profile in config.connections.items():
                masked_conn = _mask_connection_string(profile.get_connection_string())
                logger.info(f"Local connection '{name}': {profile.type} ({masked_conn})")

            return config

        parent = current.parent
        if parent == current:
            break
        current = parent

    logger.info("Local database config not found, returning empty config")
    return DatabaseConfig()


def load_effective_config(cwd: Optional[str] = None) -> DatabaseConfig:
    """Load the effective database config (global + local merged).

    Merging strategy (most specific wins):
    1. Start with global connections (least specific)
    2. Overlay legacy ``db_connections.txt`` connections
    3. Overlay ``.echart-skill/db_connections.txt`` connections (most specific)

    When a connection name exists at multiple levels, the most specific
    (closest to cwd) definition wins.

    Args:
        cwd: Current working directory (defaults to actual cwd).

    Returns:
        DatabaseConfig with merged connection profiles.
    """
    config_files = _find_all_config_files(cwd)

    if not config_files:
        logger.info("No database config files found, returning empty config")
        return DatabaseConfig()

    # Merge from least specific to most specific
    # Last file found is most specific (global is last in the list)
    # Actually: reverse the list — merge from global (last) to most specific (first)
    merged: Dict[str, ConnectionProfile] = {}

    # Process global first (least specific), then parent dirs, then cwd (most specific)
    for config_path in reversed(config_files):
        logger.debug(f"Merging config from: {config_path}")
        try:
            raw_data = parse_txt_config(config_path)
            config = DatabaseConfig(**raw_data)
            merged.update(config.connections)
        except Exception as e:
            logger.warning(f"Failed to parse config {config_path}: {e}")

    result = DatabaseConfig(connections=merged)

    logger.info(
        "Effective database config loaded",
        file_count=len(config_files),
        connection_count=len(merged),
    )

    for name, profile in result.connections.items():
        masked_conn = _mask_connection_string(profile.get_connection_string())
        logger.debug(f"Effective connection '{name}': {profile.type} ({masked_conn})")

    return result


def _mask_connection_string(conn_str: str) -> str:
    """Mask password in connection string for logging.
    
    Args:
        conn_str: Full connection string
        
    Returns:
        Connection string with password replaced by ***
    """
    # Match pattern: user:password@
    pattern = r'(://[^:]+:)([^@]+)(@)'
    return re.sub(pattern, r'\1***\3', conn_str)


# Convenience function for quick profile access
def get_connection(name: str, config_path: Optional[str] = None) -> ConnectionProfile:
    """Get a specific connection profile by name.

    Uses effective config (global + local merged) when no config_path
    is specified.

    Args:
        name: Profile name from config
        config_path: Optional config file path (uses effective config if None)

    Returns:
        ConnectionProfile instance

    Raises:
        KeyError: If profile name not found
    """
    config = load_config(config_path) if config_path else load_effective_config()
    if name not in config.connections:
        available = list(config.connections.keys())
        raise KeyError(
            f"Connection profile '{name}' not found. "
            f"Available profiles: {available}"
        )
    return config.connections[name]
