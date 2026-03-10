import logging
import os
import threading

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
_config_lock = threading.Lock()


class TracingConfig(BaseModel):
    """Configuration for LangSmith tracing."""

    enabled: bool = Field(...)
    api_key: str | None = Field(...)
    project: str = Field(...)
    endpoint: str = Field(...)

    @property
    def is_configured(self) -> bool:
        """Check if tracing is fully configured (enabled and has API key)."""
        return self.enabled and bool(self.api_key)


_tracing_config: TracingConfig | None = None


def _env_flag_true(*names: str) -> bool:
    """Return True when any provided env var is set to a truthy value."""
    truthy_values = {"1", "true", "yes", "on"}
    for name in names:
        value = os.environ.get(name)
        if value and value.strip().lower() in truthy_values:
            return True
    return False


def _first_env_value(*names: str) -> str | None:
    """Return the first non-empty environment value from candidate names."""
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def get_tracing_config() -> TracingConfig:
    """Get the current tracing configuration from environment variables.
    Returns:
        TracingConfig with current settings.
    """
    global _tracing_config
    if _tracing_config is not None:
        return _tracing_config
    with _config_lock:
        if _tracing_config is not None:  # Double-check after acquiring lock
            return _tracing_config
        _tracing_config = TracingConfig(
            # Keep compatibility with both legacy LANGCHAIN_* and newer LANGSMITH_* variables.
            enabled=_env_flag_true("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING"),
            api_key=_first_env_value("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"),
            project=_first_env_value("LANGSMITH_PROJECT", "LANGCHAIN_PROJECT") or "deer-flow",
            endpoint=_first_env_value("LANGSMITH_ENDPOINT", "LANGCHAIN_ENDPOINT") or "https://api.smith.langchain.com",
        )
        return _tracing_config


def is_tracing_enabled() -> bool:
    """Check if LangSmith tracing is enabled and configured.
    Returns:
        True if tracing is enabled and has an API key.
    """
    return get_tracing_config().is_configured
