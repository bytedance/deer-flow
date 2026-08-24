"""Read-only Agent tool for operator-scoped RAGFlow knowledge retrieval."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping

from langchain_core.tools import StructuredTool
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from deerflow.config import get_app_config

from .client import RAGFlowAPIError, RAGFlowClient, RAGFlowConnectionError, RAGFlowProtocolError
from .formatting import format_retrieval_result

logger = logging.getLogger(__name__)

_warned: set[str] = set()
_RAGFLOW_UUID_PATTERN = re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{32}|[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12})(?![0-9A-Fa-f])")


class _RAGFlowRetrievalSettings(BaseModel):
    """Validated provider settings stored on the knowledge_search tool entry."""

    model_config = ConfigDict(validate_default=True)

    datasets: list[str] | None = Field(default=None, max_length=100)
    base_url: AnyHttpUrl = Field(default="http://localhost:9380")
    api_key: SecretStr | None = Field(default=None)
    timeout: float = Field(default=30, gt=0, le=600)
    page_size: int = Field(default=8, ge=1, le=100)
    similarity_threshold: float = Field(default=0.2, ge=0, le=1)
    vector_similarity_weight: float = Field(default=0.3, ge=0, le=1)
    top_k: int = Field(default=256, ge=1, le=1024)
    max_chars_per_chunk: int = Field(default=800, ge=1, le=100_000)
    max_total_chars: int = Field(default=8000, ge=1, le=1_000_000)

    @field_validator("datasets")
    @classmethod
    def _normalize_dataset_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for dataset_id in value:
            clean_id = dataset_id.strip()
            if not clean_id or len(clean_id) > 256:
                raise ValueError("dataset IDs must contain between 1 and 256 characters")
            if clean_id not in seen:
                normalized.append(clean_id)
                seen.add(clean_id)
        return normalized or None

    @field_validator("base_url")
    @classmethod
    def _reject_url_userinfo(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.username is not None or value.password is not None:
            raise ValueError("base_url must not contain username or password information")
        return value


def _api_key(settings: _RAGFlowRetrievalSettings) -> str | None:
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


def _redact_error(value: object, api_key: str | None) -> str:
    """Redact provider credentials and opaque dataset IDs on error paths."""
    return _RAGFLOW_UUID_PATTERN.sub("[DATASET_ID]", _redact_api_key(value, api_key))


def _settings_from_extra(extra: Mapping[str, object]) -> _RAGFlowRetrievalSettings:
    return _RAGFlowRetrievalSettings.model_validate(dict(extra))


def _settings_or_error() -> tuple[_RAGFlowRetrievalSettings | None, str | None]:
    tool_config = get_app_config().get_tool_config("knowledge_search")
    if tool_config is None:
        return None, "Error: knowledge_search is not configured; add its RAGFlow settings to the tools list in config.yaml."
    try:
        settings = _settings_from_extra(tool_config.model_extra or {})
    except ValidationError:
        logger.warning("RAGFlow knowledge_search tool configuration is invalid")
        return None, "Error: Invalid RAGFlow settings for knowledge_search; check config.yaml."
    if not _api_key(settings):
        if "api_key" not in _warned:
            _warned.add("api_key")
            logger.warning("RAGFlow API key is not configured; set knowledge_search.api_key in config.yaml, preferably via $RAGFLOW_API_KEY.")
        return None, "Error: RAGFlow API key is not configured; set knowledge_search.api_key in config.yaml (prefer $RAGFLOW_API_KEY)."
    return settings, None


def _build_client(settings: _RAGFlowRetrievalSettings) -> RAGFlowClient:
    api_key = _api_key(settings)
    if api_key is None:  # Guarded by _settings_or_error; keeps this helper total.
        raise ValueError("RAGFlow API key is missing")
    return RAGFlowClient(
        base_url=str(settings.base_url).rstrip("/"),
        api_key=api_key,
        timeout=settings.timeout,
    )


def _tool_error(exc: Exception, settings: _RAGFlowRetrievalSettings) -> str:
    key = _api_key(settings)
    safe_detail = _redact_error(exc, key)
    base_url = _redact_error(str(settings.base_url).rstrip("/"), key)

    if isinstance(exc, RAGFlowAPIError):
        logger.warning("RAGFlow API rejected a read-only tool request (code=%s)", exc.code)
        return f"Error: {safe_detail}"
    if isinstance(exc, RAGFlowConnectionError):
        logger.warning("RAGFlow connection failed for %s (%s)", base_url, type(exc).__name__)
        return f"Error: Unable to connect to RAGFlow ({base_url}): {safe_detail}"
    if isinstance(exc, RAGFlowProtocolError):
        logger.warning("RAGFlow returned an invalid response for a read-only tool request (%s)", type(exc).__name__)
        return f"Error: RAGFlow request failed: {safe_detail}"

    logger.warning("Unexpected RAGFlow read-only tool failure (%s)", type(exc).__name__)
    return "Error: An unexpected RAGFlow retrieval error occurred; try again later."


def _current_dataset_name(datasets: list[dict], bound_id: str) -> str | None:
    for dataset in datasets:
        dataset_id = dataset.get("id")
        name = dataset.get("name")
        if dataset_id == bound_id:
            return str(name).strip() if name else "Unknown dataset"
    return None


def _missing_dataset_error() -> str:
    return "Error: A configured RAGFlow dataset was not found or is inaccessible; check knowledge_search.datasets in config.yaml."


async def _resolve_datasets(
    client: RAGFlowClient,
    settings: _RAGFlowRetrievalSettings,
) -> tuple[list[str] | None, dict[str, str] | None, str | None]:
    if settings.datasets is None:
        datasets = await client.list_datasets()
        names_by_id: dict[str, str] = {}
        for dataset in datasets:
            dataset_id = dataset.get("id")
            if not isinstance(dataset_id, str) or not dataset_id.strip():
                continue
            clean_id = dataset_id.strip()
            name = dataset.get("name")
            names_by_id.setdefault(clean_id, str(name).strip() if name else "Unknown dataset")

        if not names_by_id:
            return (
                None,
                None,
                "Error: No accessible RAGFlow datasets were found; configure knowledge_search.datasets or add a dataset in RAGFlow.",
            )
        return list(names_by_id), names_by_id, None

    batches = await asyncio.gather(*(client.list_datasets(dataset_id=dataset_id) for dataset_id in settings.datasets))

    names_by_id: dict[str, str] = {}
    for bound_id, datasets in zip(settings.datasets, batches, strict=True):
        current_name = _current_dataset_name(datasets, bound_id)
        if current_name is None:
            return None, None, _missing_dataset_error()
        names_by_id[bound_id] = current_name

    return list(settings.datasets), names_by_id, None


async def knowledge_search(query: str) -> str:
    """Search the configured RAGFlow scope, defaulting to every accessible dataset."""
    query = query.strip()
    if not query:
        return "Error: query must not be empty."

    settings, error = _settings_or_error()
    if settings is None:
        return error or "Error: Invalid RAGFlow settings for knowledge_search; check config.yaml."

    client = _build_client(settings)
    try:
        dataset_ids, names_by_id, resolution_error = await _resolve_datasets(client, settings)
        if resolution_error is not None:
            return resolution_error
        if not dataset_ids or names_by_id is None:  # Defensive; both resolution paths return a non-empty scope.
            return "Error: No RAGFlow datasets could be resolved; check knowledge_search in config.yaml."

        result = await client.retrieve(
            query,
            dataset_ids=dataset_ids,
            page_size=settings.page_size,
            similarity_threshold=settings.similarity_threshold,
            vector_similarity_weight=settings.vector_similarity_weight,
            top_k=settings.top_k,
        )
        formatted = format_retrieval_result(
            result,
            dataset_names_by_id=names_by_id,
            max_chars_per_chunk=settings.max_chars_per_chunk,
            max_total_chars=settings.max_total_chars,
        )
        # API-key redaction remains mandatory on success. UUID redaction is
        # deliberately error-only so valid checksums and trace IDs survive.
        return _redact_api_key(formatted, _api_key(settings))
    except Exception as exc:
        return _tool_error(exc, settings)


def _tool_description() -> str:
    base = "Search the operator-approved RAGFlow datasets and return compact, citation-numbered source chunks."
    return f"{base} If knowledge_search.datasets is omitted, all datasets accessible to the configured RAGFlow API key are searched. Dataset IDs are never shown to the model."


async def _knowledge_search_entrypoint(query: str) -> str:
    """Search the configured RAGFlow datasets, or every accessible dataset by default.

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
