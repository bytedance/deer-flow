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
            enabled=os.environ.get("LANGSMITH_TRACING", "").lower() == "true",
            api_key=os.environ.get("LANGSMITH_API_KEY"),
            project=os.environ.get("LANGSMITH_PROJECT", "deer-flow"),
            endpoint=os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
        )
        return _tracing_config


def is_tracing_enabled() -> bool:
    """Check if LangSmith tracing is enabled and configured.
    Returns:
        True if tracing is enabled and has an API key.
    """
    return get_tracing_config().is_configured
