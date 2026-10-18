"""Read-only Agent tool for operator-scoped LightRAG knowledge retrieval."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from deerflow.community.provider_credentials import redact_secret, reject_url_userinfo, resolve_api_key
from deerflow.config import get_app_config
from deerflow.knowledge import format_result
from deerflow.knowledge.providers import validate_scope_capabilities
from deerflow.knowledge.sources import redact_strings, source_artifact
from deerflow.knowledge_scope import KNOWLEDGE_SCOPE_RUNTIME_KEY
from deerflow.tools.types import Runtime

from .client import LightRAGAPIError, LightRAGClient, LightRAGConnectionError, LightRAGProtocolError
from .formatting import CAPABILITIES, format_retrieval_result, normalize_retrieval_result

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
        return reject_url_userinfo(value)


def _api_key(settings: _LightRAGRetrievalSettings) -> str | None:
    # LightRAG may run without authentication, so a missing key stays valid;
    # blank values are treated as unconfigured rather than rejected.
    return resolve_api_key(settings.api_key)


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
    safe_detail = redact_secret(exc, key)
    base_url = redact_secret(str(settings.base_url).rstrip("/"), key)

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


async def _search(query: str, *, with_sources: bool = False) -> str | tuple[str, dict]:
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
        if with_sources:
            normalized = normalize_retrieval_result(redact_strings(result, _api_key(settings)))
            return format_result(normalized, max_chars_per_chunk=settings.max_chars_per_chunk, max_total_chars=settings.max_total_chars)
        formatted = format_retrieval_result(
            result,
            max_chars_per_chunk=settings.max_chars_per_chunk,
            max_total_chars=settings.max_total_chars,
        )
        # API-key redaction remains mandatory on the success path; chunk and
        # reference identifiers never enter the formatted text at all.
        return redact_secret(formatted, _api_key(settings))
    except Exception as exc:
        return _tool_error(exc, settings)


async def knowledge_search(query: str) -> str:
    """Legacy text-only API; graph tool calls additionally carry source artifacts."""
    result = await _search(query)
    assert isinstance(result, str)
    return result


def _tool_description() -> str:
    base = "Search the operator-approved LightRAG knowledge base and return compact, citation-numbered source chunks retrieved with the configured graph/vector mode."
    base += " Cite only returned evidence using the exact [citation:Title](#knowledge-source-ID) links supplied with each chunk; never invent source locators."
    return f"{base} Internal identifiers are never shown to the model."


async def _knowledge_search_entrypoint(query: str, runtime: Runtime = None) -> tuple[str, dict | None]:
    """Search the operator-configured LightRAG knowledge base.

    Args:
        query: Specific question or search terms to retrieve from the configured private documents.
    """
    context = getattr(runtime, "context", None)
    scope = context.get(KNOWLEDGE_SCOPE_RUNTIME_KEY) if isinstance(context, Mapping) else None
    try:
        validated = validate_scope_capabilities(scope, CAPABILITIES) if scope is not None else None
        if validated is not None and validated["mode"] == "disabled":
            return "Error: Knowledge retrieval is disabled for this turn.", None
    except ValueError:
        return "Error: LightRAG does not support the selected knowledge scope.", None
    result = await _search(query, with_sources=True)
    return result if isinstance(result, tuple) else (result, source_artifact([]))


knowledge_search_tool = StructuredTool.from_function(
    coroutine=_knowledge_search_entrypoint,
    name="knowledge_search",
    description=_tool_description(),
    parse_docstring=True,
    response_format="content_and_artifact",
    metadata={"knowledge_capabilities": CAPABILITIES.model_dump(mode="json")},
)
