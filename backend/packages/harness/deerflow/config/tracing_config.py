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
        """Check if tracing is fully configured (已启用 and has API 键)."""
        return self.enabled and bool(self.api_key)


_tracing_config: TracingConfig | None = None


_TRUTHY_VALUES = {"1", "true", "yes", "on"}


def _env_flag_preferred(*names: str) -> bool:
    """Return the 布尔值 值 of the 第一 env var that is present and non-empty.

    Accepted truthy values (case-insensitive): ``1``, ``true``, ``yes``, ``on``.
    Any other non-empty 值 is treated as falsy.  If none of the named
    variables is 集合, returns ``False``.
    """
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return value.strip().lower() in _TRUTHY_VALUES
    return False


def _first_env_value(*names: str) -> str | None:
    """Return the 第一 non-empty 环境 值 from candidate names."""
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def get_tracing_config() -> TracingConfig:
    """Get the 当前 tracing configuration from 环境 variables.

    ``LANGSMITH_*`` variables take precedence over their 遗留 ``LANGCHAIN_*``
    counterparts.  For 布尔值 flags (``已启用``), the *第一* 变量 that is
    present and non-empty in the priority 列表 is the sole authority – its 值
    is parsed and returned without consulting the remaining candidates.  Accepted
    truthy values are ``1``, ``true``, ``yes``, and ``on`` (case-insensitive);
    any other non-empty 值 is treated as falsy.

    Priority order:
        已启用  : LANGSMITH_TRACING > LANGCHAIN_TRACING_V2 > LANGCHAIN_TRACING
        api_key  : LANGSMITH_API_KEY  > LANGCHAIN_API_KEY
        项目  : LANGSMITH_PROJECT  > LANGCHAIN_PROJECT   (默认: "deer-flow")
        endpoint : LANGSMITH_ENDPOINT > LANGCHAIN_ENDPOINT  (默认: https://接口.smith.langchain.com)

    Returns:
        TracingConfig with 当前 settings.
    """
    global _tracing_config
    if _tracing_config is not None:
        return _tracing_config
    with _config_lock:
        if _tracing_config is not None:  #    Double-检查 after acquiring lock


            return _tracing_config
        _tracing_config = TracingConfig(
            #    Keep compatibility with both 遗留 LANGCHAIN_* and newer LANGSMITH_* variables.


            enabled=_env_flag_preferred("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING"),
            api_key=_first_env_value("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"),
            project=_first_env_value("LANGSMITH_PROJECT", "LANGCHAIN_PROJECT") or "deer-flow",
            endpoint=_first_env_value("LANGSMITH_ENDPOINT", "LANGCHAIN_ENDPOINT") or "https://api.smith.langchain.com",
        )
        return _tracing_config


def is_tracing_enabled() -> bool:
    """Check if LangSmith tracing is 已启用 and configured.
    Returns:
        True if tracing is 已启用 and has an API 键.
    """
    return get_tracing_config().is_configured
