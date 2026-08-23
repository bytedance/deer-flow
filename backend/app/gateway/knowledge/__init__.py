"""Shared helpers for the stateless RAGFlow Gateway integration."""

from pydantic import SecretStr

from deerflow.community.ragflow.client import RAGFlowClient
from deerflow.config.knowledge_base_config import KnowledgeBaseConfig


def ragflow_api_key(settings: KnowledgeBaseConfig) -> str | None:
    """Return the configured key without ever serializing it implicitly."""
    value = settings.api_key
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def build_ragflow_client(settings: KnowledgeBaseConfig) -> RAGFlowClient:
    """Build a short-lived client from the current hot-reloaded settings."""
    api_key = ragflow_api_key(settings)
    if api_key is None:
        raise RuntimeError("RAGFlow API key is unavailable")
    return RAGFlowClient(
        base_url=str(settings.base_url).rstrip("/"),
        api_key=api_key,
        timeout=settings.timeout,
    )


__all__ = ["build_ragflow_client", "ragflow_api_key"]
