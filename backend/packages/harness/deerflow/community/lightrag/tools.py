"""Read-only Agent tool for operator-scoped LightRAG knowledge retrieval."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from deerflow.config import get_app_config

from .client import LightRAGAPIError, LightRAGClient, LightRAGConnectionError, LightRAGProtocolError
from .formatting import format_retrieval_result

logger = logging.getLogger(__name__)

_NO_RELEVANT_CONTENT = "No relevant content found."


class _LightRAGRetrievalSettings(BaseModel):
    """Validated provider settings stored on the knowledge_search tool entry."""

    model_config = ConfigDict(validate_default=True)

    base_url: AnyHttpUrl = Field(default="http://localhost:9621")
    api_key: SecretStr | None = Field(default=None)
    # LightRAG's QueryRequest also accepts "bypass", which skips the index and
    # answers straight from the LLM; that would defeat a retrieval tool, so it
    # is excluded on purpose. "mix" matches the LightRAG API's own default.
    mode: Literal["naive", "local", "global", "hybrid", "mix"] = Field(default="mix")
    timeout: float = Field(default=30, gt=0, le=600)
    # The server caps both fields at MAX_QUERY_TOP_K = 1000; match that limit
    # instead of inventing a tighter client-side one.
    top_k: int = Field(default=60, ge=1, le=1000)
    chunk_top_k: int | None = Field(default=None, ge=1, le=1000)
    max_chars_per_chunk: int = Field(default=800, ge=1, le=100_000)
    max_total_chars: int = Field(default=8000, ge=1, le=1_000_000)

    @field_validator("base_url")
    @classmethod
    def _reject_url_userinfo(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.username is not None or value.password is not None:
            raise ValueError("base_url must not contain username or password information")
        return value


def _api_key(settings: _LightRAGRetrievalSettings) -> str | None:
    # LightRAG may run without authentication, so a missing key stays valid;
    # blank values are treated as unconfigured rather than rejected.
    value = settings.api_key
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _redact_api_key(value: object, api_key: str | None) -> str:
    text = str(value)
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    return text


def _settings_from_extra(extra: Mapping[str, object]) -> _LightRAGRetrievalSettings:
    return _LightRAGRetrievalSettings.model_validate(dict(extra))


def _settings_or_error() -> tuple[_LightRAGRetrievalSettings | None, str | None]:
    tool_config = get_app_config().get_tool_config("knowledge_search")
    if tool_config is None:
        return None, "Error: knowledge_search is not configured; add its LightRAG settings to the tools list in config.yaml."
    try:
        settings = _settings_from_extra(tool_config.model_extra or {})
    except ValidationError:
        logger.warning("LightRAG knowledge_search tool configuration is invalid")
        return None, "Error: Invalid LightRAG settings for knowledge_search; check config.yaml."
    return settings, None


def _build_client(settings: _LightRAGRetrievalSettings) -> LightRAGClient:
    return LightRAGClient(
        base_url=str(settings.base_url).rstrip("/"),
        api_key=_api_key(settings),
        timeout=settings.timeout,
    )


def _tool_error(exc: Exception, settings: _LightRAGRetrievalSettings) -> str:
    key = _api_key(settings)
    safe_detail = _redact_api_key(exc, key)
    base_url = _redact_api_key(str(settings.base_url).rstrip("/"), key)

    if isinstance(exc, LightRAGAPIError):
        logger.warning("LightRAG API rejected a read-only tool request: %s", safe_detail)
        return f"Error: {safe_detail}"
    if isinstance(exc, LightRAGConnectionError):
        logger.warning("LightRAG connection failed for %s (%s)", base_url, type(exc).__name__)
        return f"Error: Unable to connect to LightRAG ({base_url}): {safe_detail}"
    if isinstance(exc, LightRAGProtocolError):
        logger.warning("LightRAG returned an invalid response for a read-only tool request (%s)", type(exc).__name__)
        return f"Error: LightRAG request failed: {safe_detail}"

    logger.warning("Unexpected LightRAG read-only tool failure (%s)", type(exc).__name__)
    return "Error: An unexpected LightRAG retrieval error occurred; try again later."


async def knowledge_search(query: str) -> str:
    """Search the operator-configured LightRAG instance.

    LightRAG has no dataset catalog to scope: the deployment's single indexed
    workspace is always searched with the configured retrieval mode, so no
    binding resolution happens before the one read-only request.
    """
    query = query.strip()
    if not query:
        return "Error: query must not be empty."

    settings, error = _settings_or_error()
    if settings is None:
        return error or "Error: Invalid LightRAG settings for knowledge_search; check config.yaml."

    client = _build_client(settings)
    try:
        result = await client.query_data(
            query,
            mode=settings.mode,
            top_k=settings.top_k,
            chunk_top_k=settings.chunk_top_k,
        )
        formatted = format_retrieval_result(
            result,
            max_chars_per_chunk=settings.max_chars_per_chunk,
            max_total_chars=settings.max_total_chars,
        )
        # API-key redaction remains mandatory on the success path; chunk and
        # reference identifiers never enter the formatted text at all.
        return _redact_api_key(formatted, _api_key(settings))
    except Exception as exc:
        return _tool_error(exc, settings)


def _tool_description() -> str:
    base = "Search the operator-approved LightRAG knowledge base and return compact, citation-numbered source chunks retrieved with the configured graph/vector mode."
    return f"{base} Internal identifiers are never shown to the model."


async def _knowledge_search_entrypoint(query: str) -> str:
    """Search the operator-configured LightRAG knowledge base.

    Args:
        query: Specific question or search terms to retrieve from the configured private documents.
    """
    return await knowledge_search(query)


knowledge_search_tool = StructuredTool.from_function(
    coroutine=_knowledge_search_entrypoint,
    name="knowledge_search",
    description=_tool_description(),
    parse_docstring=True,
)
