"""Configuration for LLM I/O Trace — prints model request/response for dev debugging."""

import logging
import os

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_TRUTHY = frozenset(("1", "true", "yes", "on"))
_FALSY = frozenset(("0", "false", "no", "off"))


class LLMIOTraceConfig(BaseModel):
    """Dev-tool configuration for printing LLM request/response details.

    The middleware is disabled by default via ``enabled=False``.
    Enable ``llm_io_trace.enabled`` in ``config.yaml`` (or set
    ``DEERFLOW_LLM_IO_TRACE_ENABLED=true`` in the environment) to activate.
    """

    enabled: bool = Field(default=False, description="Master switch. When false the middleware is not mounted at all.")
    print_system_prompt: bool = Field(default=False, description="Print the system prompt.")
    print_messages: bool = Field(default=True, description="Print the conversation messages sent to the model.")
    print_tools: bool = Field(default=False, description="Print tool definitions / schemas.")
    print_response: bool = Field(default=True, description="Print the model response.")
    max_messages: int = Field(default=0, ge=0, description="When > 0, only the last N messages are printed (tail). 0 = print all.")

    @classmethod
    def with_env_override(cls, base: "LLMIOTraceConfig") -> "LLMIOTraceConfig":
        """Return a copy of *base* with ``enabled`` overridden by the env var.

        ``DEERFLOW_LLM_IO_TRACE_ENABLED``:
            - unset / empty → use *base* as-is
            - ``1/true/yes/on`` → force ``enabled=True``
            - ``0/false/no/off`` → force ``enabled=False``
        """
        raw = os.environ.get("DEERFLOW_LLM_IO_TRACE_ENABLED", "").strip().lower()
        if not raw:
            return base
        if raw in _TRUTHY:
            return base.model_copy(update={"enabled": True})
        if raw in _FALSY:
            return base.model_copy(update={"enabled": False})
        logger.warning("Unrecognised DEERFLOW_LLM_IO_TRACE_ENABLED=%r — ignoring", raw)
        return base
