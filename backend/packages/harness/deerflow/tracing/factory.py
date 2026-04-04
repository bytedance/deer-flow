from __future__ import annotations

from typing import Any

from deerflow.config import (
    get_enabled_tracing_providers,
    get_tracing_config,
    validate_enabled_tracing_providers,
)


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
