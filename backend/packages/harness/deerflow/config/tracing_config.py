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


_TRUTHY_VALUES = {"1", "true", "yes", "on"}


def _env_flag_preferred(*names: str) -> bool:
    """Return the boolean value of the first env var that is present and non-empty.

    Accepted truthy values (case-insensitive): ``1``, ``true``, ``yes``, ``on``.
    Any other non-empty value is treated as falsy.  If none of the named
    variables is set, returns ``False``.
    """
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return value.strip().lower() in _TRUTHY_VALUES
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

    ``LANGSMITH_*`` variables take precedence over their legacy ``LANGCHAIN_*``
    counterparts.  For boolean flags (``enabled``), the *first* variable that is
    present and non-empty in the priority list is the sole authority – its value
    is parsed and returned without consulting the remaining candidates.  Accepted
    truthy values are ``1``, ``true``, ``yes``, and ``on`` (case-insensitive);
    any other non-empty value is treated as falsy.

    Priority order:
        enabled  : LANGSMITH_TRACING > LANGCHAIN_TRACING_V2 > LANGCHAIN_TRACING
        api_key  : LANGSMITH_API_KEY  > LANGCHAIN_API_KEY
        project  : LANGSMITH_PROJECT  > LANGCHAIN_PROJECT   (default: "deer-flow")
        endpoint : LANGSMITH_ENDPOINT > LANGCHAIN_ENDPOINT  (default: https://api.smith.langchain.com)

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
            enabled=_env_flag_preferred("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING"),
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
