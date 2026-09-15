from __future__ import annotations

import logging
from typing import Any

from deerflow.config import (
    get_enabled_tracing_providers,
    get_tracing_config,
    is_monocle_tracing_enabled,
    validate_enabled_tracing_providers,
)
from deerflow.tracing.monocle import is_monocle_setup_completed

logger = logging.getLogger(__name__)


def _create_langsmith_tracer(config) -> Any:
    from langchain_core.tracers.langchain import LangChainTracer

    return LangChainTracer(project_name=config.project)


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


def build_tracing_callbacks() -> list[Any]:
    """Build callbacks for all explicitly enabled tracing providers."""
    validate_enabled_tracing_providers()
    # Monocle is not a callback provider; this per-run path is just where an
    # embedded process that skipped Gateway-lifespan setup can be told about it.
    if is_monocle_tracing_enabled() and not is_monocle_setup_completed():
        logger.debug(
            "MONOCLE_TRACING is set but Monocle is not initialized in this process — only the Gateway lifespan runs setup automatically; embedded/TUI callers must call deerflow.tracing.setup_monocle_tracing_if_enabled() themselves."
        )
    enabled_providers = get_enabled_tracing_providers()
    if not enabled_providers:
        return []

    tracing_config = get_tracing_config()
    callbacks: list[Any] = []

    for provider in enabled_providers:
        if provider == "langsmith":
            try:
                callbacks.append(_create_langsmith_tracer(tracing_config.langsmith))
            except Exception as exc:  # pragma: no cover - exercised via tests with monkeypatch
                raise RuntimeError(f"LangSmith tracing initialization failed: {exc}") from exc
        elif provider == "langfuse":
            try:
                callbacks.append(_create_langfuse_handler(tracing_config.langfuse))
            except Exception as exc:  # pragma: no cover - exercised via tests with monkeypatch
                raise RuntimeError(f"Langfuse tracing initialization failed: {exc}") from exc

    return callbacks
