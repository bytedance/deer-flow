from __future__ import annotations

from typing import Any

from deerflow.config import (
    get_enabled_tracing_providers,
    get_tracing_config,
    validate_enabled_tracing_providers,
)


def _create_langfuse_handler(config) -> Any:
    from langfuse import Langfuse
    from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

    # langfuse>=4 initializes project-specific credentials through the client
    # singleton; the LangChain callback then attaches to that configured client.
    Langfuse(
        secret_key=config.secret_key,
        public_key=config.public_key,
        host=config.host,
    )
    return LangfuseCallbackHandler(public_key=config.public_key)


def build_langfuse_handler() -> Any | None:
    """Build a Langfuse LangChain CallbackHandler if Langfuse tracing is enabled.

    Returns ``None`` when Langfuse is not configured. Raises ``ValueError`` via
    ``validate_enabled_tracing_providers()`` when a tracing provider is
    explicitly enabled but its required environment variables are missing.
    Raises ``RuntimeError`` when Langfuse is enabled and configured but the
    ``CallbackHandler`` construction itself fails (e.g. unreachable host or
    incompatible ``langfuse`` package version).

    LangSmith is intentionally not handled here: when ``LANGSMITH_TRACING`` is
    set, ``langchain_core.callbacks.manager`` auto-injects ``LangChainTracer``
    into the root callback manager of every run, so it does not need an
    application-level callback wiring.
    """
    validate_enabled_tracing_providers()
    if "langfuse" not in get_enabled_tracing_providers():
        return None

    tracing_config = get_tracing_config()
    try:
        return _create_langfuse_handler(tracing_config.langfuse)
    except Exception as exc:  # pragma: no cover - exercised via tests with monkeypatch
        raise RuntimeError(f"Langfuse tracing initialization failed: {exc}") from exc
