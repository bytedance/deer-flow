"""Read-only Agent tools for RAGFlow knowledge retrieval."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping

from langchain.tools import tool
from pydantic import SecretStr

from deerflow.config import get_app_config
from deerflow.config.knowledge_base_config import KnowledgeBaseConfig

from .client import RAGFlowAPIError, RAGFlowClient, RAGFlowConnectionError, RAGFlowProtocolError
from .formatting import format_retrieval_result

logger = logging.getLogger(__name__)

_warned: set[str] = set()
_RAGFLOW_UUID_PATTERN = re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{32}|[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12})(?![0-9A-Fa-f])")


def _api_key(settings: KnowledgeBaseConfig) -> str | None:
    value = settings.api_key
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _redact(value: object, api_key: str | None) -> str:
    text = str(value)
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    return _RAGFLOW_UUID_PATTERN.sub("[DATASET_ID]", text)


def _settings_or_error() -> tuple[KnowledgeBaseConfig | None, str | None]:
    settings = get_app_config().knowledge_base
    if not settings.enabled:
        return None, "Error: 知识库功能未启用，请在 config.yaml 中设置 knowledge_base.enabled: true。"
    if not _api_key(settings):
        if "api_key" not in _warned:
            _warned.add("api_key")
            logger.warning("RAGFlow API Key 未配置；请设置 knowledge_base.api_key，建议使用 $RAGFLOW_API_KEY 环境变量引用。")
        return None, "Error: 未配置 RAGFlow API Key，请设置 knowledge_base.api_key（建议使用 $RAGFLOW_API_KEY）。"
    return settings, None


def _build_client(settings: KnowledgeBaseConfig) -> RAGFlowClient:
    api_key = _api_key(settings)
    if api_key is None:  # Guarded by _settings_or_error; keeps this helper total.
        raise ValueError("RAGFlow API Key is missing")
    return RAGFlowClient(
        base_url=str(settings.base_url).rstrip("/"),
        api_key=api_key,
        timeout=settings.timeout,
    )


def _tool_error(exc: Exception, settings: KnowledgeBaseConfig) -> str:
    key = _api_key(settings)
    safe_detail = _redact(exc, key)
    base_url = _redact(str(settings.base_url).rstrip("/"), key)

    if isinstance(exc, RAGFlowAPIError):
        logger.warning("RAGFlow API rejected a read-only tool request (code=%s)", exc.code)
        return f"Error: {safe_detail}"
    if isinstance(exc, RAGFlowConnectionError):
        logger.warning("RAGFlow connection failed for %s (%s)", base_url, type(exc).__name__)
        return f"Error: 无法连接 RAGFlow ({base_url}): {safe_detail}"
    if isinstance(exc, RAGFlowProtocolError):
        logger.warning("RAGFlow returned an invalid response for a read-only tool request (%s)", type(exc).__name__)
        return f"Error: RAGFlow 请求失败: {safe_detail}"

    logger.warning("Unexpected RAGFlow read-only tool failure (%s)", type(exc).__name__)
    return "Error: RAGFlow 检索发生未知错误，请稍后重试。"


def _valid_datasets(datasets: list[dict]) -> list[tuple[str, str, Mapping[str, object]]]:
    valid: list[tuple[str, str, Mapping[str, object]]] = []
    for dataset in datasets:
        dataset_id = dataset.get("id")
        name = dataset.get("name")
        if not isinstance(dataset_id, str) or not dataset_id or not isinstance(name, str) or not name.strip():
            continue
        valid.append((dataset_id, name.strip(), dataset))
    return valid


async def list_knowledge_bases() -> str:
    """List accessible RAGFlow knowledge bases without exposing their UUIDs."""
    settings, error = _settings_or_error()
    if settings is None:
        return error or "Error: 知识库配置无效。"

    try:
        datasets = _valid_datasets(await _build_client(settings).list_datasets())
    except Exception as exc:
        return _tool_error(exc, settings)

    if not datasets:
        return "当前没有可用的知识库。"

    lines = ["可用知识库："]
    for _, name, dataset in datasets:
        description = dataset.get("description")
        description_text = f" — {description.strip()}" if isinstance(description, str) and description.strip() else ""
        document_count = dataset.get("document_count")
        count_text = f"（{document_count} 个文档）" if isinstance(document_count, int) and not isinstance(document_count, bool) else ""
        lines.append(f"- {name}{description_text}{count_text}")
    return _redact("\n".join(lines), _api_key(settings))


async def knowledge_search(query: str, knowledge_bases: list[str] | None = None) -> str:
    """Search RAGFlow and return compact chunks with stable citation markers."""
    query = query.strip()
    if not query:
        return "Error: 查询内容不能为空。"
    if knowledge_bases is not None and not any(isinstance(name, str) and name.strip() for name in knowledge_bases):
        return "Error: knowledge_bases 为空；请至少指定一个知识库，或省略该参数进行全库兜底检索。"

    settings, error = _settings_or_error()
    if settings is None:
        return error or "Error: 知识库配置无效。"

    client = _build_client(settings)
    try:
        datasets = _valid_datasets(await client.list_datasets())
        names_by_id = {dataset_id: name for dataset_id, name, _ in datasets}

        retrieve_options: dict[str, object] = {
            "page_size": settings.page_size,
            "similarity_threshold": settings.similarity_threshold,
            "vector_similarity_weight": settings.vector_similarity_weight,
            "top_k": settings.top_k,
        }
        if knowledge_bases is not None:
            ids_by_casefolded_name = {name.casefold(): dataset_id for dataset_id, name, _ in datasets}
            requested_names = [name.strip() for name in knowledge_bases if isinstance(name, str) and name.strip()]
            unknown_names = [name for name in requested_names if name.casefold() not in ids_by_casefolded_name]
            if unknown_names:
                available = ", ".join(name for _, name, _ in datasets) or "（无）"
                return _redact(
                    f"Error: 未知知识库：{', '.join(unknown_names)}。当前可用知识库：{available}。",
                    _api_key(settings),
                )

            dataset_ids: list[str] = []
            for name in requested_names:
                dataset_id = ids_by_casefolded_name[name.casefold()]
                if dataset_id not in dataset_ids:
                    dataset_ids.append(dataset_id)
            retrieve_options["dataset_ids"] = dataset_ids

        result = await client.retrieve(query, **retrieve_options)
        formatted = format_retrieval_result(
            result,
            dataset_names_by_id=names_by_id,
            max_chars_per_chunk=settings.max_chars_per_chunk,
            max_total_chars=settings.max_total_chars,
        )
        return _redact(formatted, _api_key(settings))
    except Exception as exc:
        return _tool_error(exc, settings)


@tool("list_knowledge_bases", parse_docstring=True)
async def list_knowledge_bases_tool() -> str:
    """List all private knowledge bases available to this DeerFlow deployment."""
    return await list_knowledge_bases()


@tool("knowledge_search", parse_docstring=True)
async def knowledge_search_tool(query: str, knowledge_bases: list[str] | None = None) -> str:
    """Search private RAGFlow knowledge bases for relevant source chunks.

    If you are unsure which knowledge bases exist, call
    ``list_knowledge_bases`` first. Prefer explicit knowledge-base names because
    searching all bases can fail when they use different embedding models.

    Args:
        query: Specific question or search terms to retrieve from private documents.
        knowledge_bases: Knowledge-base names to search. Omit only as a fallback search across all bases.
    """
    return await knowledge_search(query, knowledge_bases)
