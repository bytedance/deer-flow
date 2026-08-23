import logging
from types import SimpleNamespace

import pytest

import deerflow.community.ragflow.tools as ragflow_tools
from deerflow.community.ragflow.client import RAGFlowAPIError, RAGFlowConnectionError
from deerflow.community.ragflow.formatting import format_retrieval_result
from deerflow.config.knowledge_base_config import KnowledgeBaseConfig
from deerflow.config.tool_config import ToolConfig
from deerflow.tools.tools import get_available_tools


class FakeRAGFlowClient:
    def __init__(self, *, datasets: list[dict] | None = None, retrieval: dict | None = None, error: Exception | None = None) -> None:
        self.datasets = datasets or []
        self.retrieval = retrieval or {"chunks": [], "doc_aggs": [], "total": 0}
        self.error = error
        self.retrieve_calls: list[tuple[str, dict]] = []

    async def list_datasets(self) -> list[dict]:
        if self.error is not None:
            raise self.error
        return self.datasets

    async def retrieve(self, query: str, **kwargs: object) -> dict:
        if self.error is not None:
            raise self.error
        self.retrieve_calls.append((query, kwargs))
        return self.retrieval


@pytest.fixture(autouse=True)
def reset_warning_deduplication() -> None:
    ragflow_tools._warned.clear()


def _config(
    *,
    enabled: bool = True,
    api_key: str | None = "ragflow-secret",
    base_url: str = "http://ragflow.test",
) -> SimpleNamespace:
    return SimpleNamespace(
        knowledge_base=SimpleNamespace(
            enabled=enabled,
            base_url=base_url,
            api_key=api_key,
            timeout=30,
            page_size=8,
            similarity_threshold=0.2,
            vector_similarity_weight=0.3,
            top_k=256,
            max_chars_per_chunk=800,
            max_total_chars=8000,
        )
    )


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeRAGFlowClient, *, config: SimpleNamespace | None = None) -> None:
    monkeypatch.setattr(ragflow_tools, "get_app_config", lambda: config or _config())
    monkeypatch.setattr(ragflow_tools, "_build_client", lambda settings: fake)


@pytest.mark.anyio
async def test_list_knowledge_bases_returns_names_without_uuids(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient(
        datasets=[
            {"id": "dataset-secret-1", "name": "HR Policies", "description": "Employee handbook", "document_count": 3},
            {"id": "dataset-secret-2", "name": "Engineering", "description": "", "document_count": 7},
        ]
    )
    _install(monkeypatch, fake)

    result = await ragflow_tools.list_knowledge_bases()

    assert "HR Policies" in result
    assert "Employee handbook" in result
    assert "3 个文档" in result
    assert "Engineering" in result
    assert "dataset-secret" not in result


@pytest.mark.anyio
async def test_knowledge_search_resolves_names_to_ids_and_formats_citations(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient(
        datasets=[{"id": "dataset-1", "name": "HR Policies", "description": "", "document_count": 1}],
        retrieval={
            "chunks": [
                {
                    "dataset_id": "dataset-1",
                    "document_id": "doc-1",
                    "document_keyword": "handbook.pdf",
                    "content": "Annual leave is based on years of service.",
                    "similarity": 0.874,
                }
            ],
            "doc_aggs": [{"doc_id": "doc-1", "doc_name": "handbook.pdf", "count": 1}],
            "total": 1,
        },
    )
    _install(monkeypatch, fake)

    result = await ragflow_tools.knowledge_search("annual leave", ["HR Policies"])

    assert fake.retrieve_calls == [
        (
            "annual leave",
            {
                "dataset_ids": ["dataset-1"],
                "page_size": 8,
                "similarity_threshold": 0.2,
                "vector_similarity_weight": 0.3,
                "top_k": 256,
            },
        )
    ]
    assert "[1] HR Policies / handbook.pdf  (相关度 0.87)" in result
    assert "Annual leave" in result
    assert "命中文档：handbook.pdf (1 段)" in result
    assert "dataset-1" not in result


@pytest.mark.anyio
async def test_knowledge_search_accepts_case_insensitive_dataset_names(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient(datasets=[{"id": "dataset-1", "name": "HR Policies"}])
    _install(monkeypatch, fake)

    await ragflow_tools.knowledge_search("leave", ["hr policies"])

    assert fake.retrieve_calls[0][1]["dataset_ids"] == ["dataset-1"]


@pytest.mark.anyio
async def test_knowledge_search_unknown_name_returns_available_names(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient(datasets=[{"id": "dataset-1", "name": "HR Policies"}])
    _install(monkeypatch, fake)

    result = await ragflow_tools.knowledge_search("leave", ["Finance"])

    assert "Finance" in result
    assert "HR Policies" in result
    assert fake.retrieve_calls == []


@pytest.mark.anyio
async def test_unknown_dataset_error_redacts_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient(datasets=[{"id": "dataset-1", "name": "HR Policies"}])
    _install(monkeypatch, fake)

    result = await ragflow_tools.knowledge_search("leave", ["ragflow-secret"])

    assert "ragflow-secret" not in result
    assert "[REDACTED]" in result


@pytest.mark.anyio
async def test_knowledge_search_without_names_does_not_pass_dataset_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient(datasets=[{"id": "dataset-1", "name": "HR Policies"}])
    _install(monkeypatch, fake)

    await ragflow_tools.knowledge_search("fallback", None)

    assert "dataset_ids" not in fake.retrieve_calls[0][1]


@pytest.mark.anyio
async def test_knowledge_search_rejects_explicit_empty_dataset_list(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient(datasets=[{"id": "dataset-1", "name": "HR Policies"}])
    _install(monkeypatch, fake)

    result = await ragflow_tools.knowledge_search("leave", [])

    assert "至少指定一个知识库" in result
    assert fake.retrieve_calls == []


@pytest.mark.anyio
async def test_missing_api_key_returns_guidance_and_warns_only_once(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeRAGFlowClient()
    _install(monkeypatch, fake, config=_config(api_key=None))

    with caplog.at_level(logging.WARNING, logger="deerflow.community.ragflow.tools"):
        first = await ragflow_tools.list_knowledge_bases()
        second = await ragflow_tools.knowledge_search("leave")

    assert "未配置 RAGFlow API Key" in first
    assert "未配置 RAGFlow API Key" in second
    assert caplog.text.count("RAGFlow API Key") == 1
    assert fake.retrieve_calls == []


@pytest.mark.anyio
async def test_disabled_feature_returns_guidance_without_calling_ragflow(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient()
    _install(monkeypatch, fake, config=_config(enabled=False))

    result = await ragflow_tools.list_knowledge_bases()

    assert "knowledge_base.enabled: true" in result


@pytest.mark.anyio
async def test_api_error_is_returned_as_readable_text(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient(error=RAGFlowAPIError("embedding models do not match", code=102))
    _install(monkeypatch, fake)

    result = await ragflow_tools.knowledge_search("leave", ["HR Policies"])

    assert result == "Error: embedding models do not match"


@pytest.mark.anyio
async def test_api_error_cannot_expose_dataset_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_id = "0123456789abcdef0123456789abcdef"
    fake = FakeRAGFlowClient(error=RAGFlowAPIError(f"dataset {dataset_id} failed", code=102))
    _install(monkeypatch, fake)

    result = await ragflow_tools.list_knowledge_bases()

    assert dataset_id not in result
    assert "[DATASET_ID]" in result


@pytest.mark.anyio
async def test_connection_error_is_recoverable_and_does_not_leak_key(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeRAGFlowClient(error=RAGFlowConnectionError("ConnectError: refused ragflow-secret"))
    _install(monkeypatch, fake)

    with caplog.at_level(logging.WARNING, logger="deerflow.community.ragflow.tools"):
        result = await ragflow_tools.list_knowledge_bases()

    assert result.startswith("Error: 无法连接 RAGFlow (http://ragflow.test):")
    assert "ragflow-secret" not in result
    assert "ragflow-secret" not in caplog.text


@pytest.mark.anyio
async def test_connection_error_redacts_key_embedded_in_base_url(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeRAGFlowClient(error=RAGFlowConnectionError("connection refused"))
    _install(
        monkeypatch,
        fake,
        config=_config(base_url="http://ragflow-secret@ragflow.test"),
    )

    with caplog.at_level(logging.WARNING, logger="deerflow.community.ragflow.tools"):
        result = await ragflow_tools.list_knowledge_bases()

    assert "ragflow-secret" not in result
    assert "ragflow-secret" not in caplog.text


@pytest.mark.anyio
async def test_empty_retrieval_has_explicit_message(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient(datasets=[{"id": "dataset-1", "name": "HR Policies"}])
    _install(monkeypatch, fake)

    result = await ragflow_tools.knowledge_search("nothing", ["HR Policies"])

    assert result == "未检索到相关内容。"


def test_formatting_applies_per_chunk_truncation_and_supports_kb_id() -> None:
    result = format_retrieval_result(
        {
            "chunks": [
                {
                    "kb_id": "dataset-1",
                    "document_keyword": "handbook.pdf",
                    "content": "abcdefghij",
                    "similarity": 0.5,
                }
            ]
        },
        dataset_names_by_id={"dataset-1": "HR Policies"},
        max_chars_per_chunk=5,
        max_total_chars=1000,
    )

    assert "abcd…" in result
    assert "abcdefghij" not in result
    assert "dataset-1" not in result


def test_formatting_applies_total_response_truncation() -> None:
    result = format_retrieval_result(
        {
            "chunks": [
                {
                    "dataset_id": "dataset-1",
                    "document_keyword": f"document-{index}.txt",
                    "content": "content " * 20,
                    "similarity": 0.5,
                }
                for index in range(4)
            ]
        },
        dataset_names_by_id={"dataset-1": "Policies"},
        max_chars_per_chunk=100,
        max_total_chars=120,
    )

    assert len(result) <= 120
    assert result.endswith("…（响应已截断）")


def test_knowledge_base_config_has_safe_defaults_and_secret_repr() -> None:
    config = KnowledgeBaseConfig(api_key="ragflow-secret")

    assert config.enabled is False
    assert str(config.base_url).rstrip("/") == "http://localhost:9380"
    assert config.page_size == 8
    assert config.max_chars_per_chunk == 800
    assert config.max_total_chars == 8000
    assert "ragflow-secret" not in repr(config)


def test_agent_tool_contracts_are_async_and_model_facing() -> None:
    assert ragflow_tools.list_knowledge_bases_tool.name == "list_knowledge_bases"
    assert ragflow_tools.list_knowledge_bases_tool.coroutine is not None
    assert ragflow_tools.knowledge_search_tool.name == "knowledge_search"
    assert ragflow_tools.knowledge_search_tool.coroutine is not None
    assert set(ragflow_tools.knowledge_search_tool.tool_call_schema.model_fields) == {"query", "knowledge_bases"}
    assert "list_knowledge_bases" in ragflow_tools.knowledge_search_tool.description


@pytest.mark.parametrize("enabled", [False, True])
def test_tool_assembly_gates_knowledge_group_with_feature_flag(enabled: bool) -> None:
    config = SimpleNamespace(
        tools=[
            ToolConfig(
                name="knowledge_search",
                group="knowledge",
                use="deerflow.community.ragflow.tools:knowledge_search_tool",
            ),
            ToolConfig(
                name="list_knowledge_bases",
                group="knowledge",
                use="deerflow.community.ragflow.tools:list_knowledge_bases_tool",
            ),
        ],
        knowledge_base=SimpleNamespace(enabled=enabled),
        sandbox=SimpleNamespace(use="example.remote:Sandbox"),
        skill_evolution=SimpleNamespace(enabled=False),
        models=[],
        acp_agents={},
        get_model_config=lambda name: None,
    )

    names = {tool.name for tool in get_available_tools(include_mcp=False, app_config=config)}

    assert ("knowledge_search" in names) is enabled
    assert ("list_knowledge_bases" in names) is enabled
