import logging
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest

import deerflow.community.ragflow.tools as ragflow_tools
from deerflow.community.ragflow.client import RAGFlowAPIError, RAGFlowConnectionError
from deerflow.community.ragflow.formatting import format_retrieval_result
from deerflow.config.tool_config import ToolConfig
from deerflow.tools.tools import get_available_tools

DATASET_ID_1 = "0123456789abcdef0123456789abcdef"
DATASET_ID_2 = "fedcba9876543210fedcba9876543210"
MISSING_DATASET_ID = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


class FakeRAGFlowClient:
    def __init__(
        self,
        *,
        datasets_by_id: Mapping[str, list[dict]] | None = None,
        all_datasets: list[dict] | None = None,
        retrieval: dict | None = None,
        error: Exception | None = None,
    ) -> None:
        self.datasets_by_id = dict(datasets_by_id or {})
        self.all_datasets = list(all_datasets or [])
        self.retrieval = retrieval or {"chunks": [], "doc_aggs": [], "total": 0}
        self.error = error
        self.list_calls: list[str | None] = []
        self.retrieve_calls: list[tuple[str, dict]] = []

    async def list_datasets(self, *, dataset_id: str | None = None) -> list[dict]:
        if self.error is not None:
            raise self.error
        self.list_calls.append(dataset_id)
        if dataset_id is None:
            return self.all_datasets
        return self.datasets_by_id.get(dataset_id, [])

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
    configured: bool = True,
    api_key: str | None = "ragflow-secret",
    base_url: str = "http://ragflow.test",
    datasets: list[str] | None = None,
) -> SimpleNamespace:
    extra: dict[str, object] = {
        "base_url": base_url,
        "api_key": api_key,
        "timeout": 30,
        "page_size": 8,
        "similarity_threshold": 0.2,
        "vector_similarity_weight": 0.3,
        "top_k": 256,
        "max_chars_per_chunk": 800,
        "max_total_chars": 8000,
    }
    if datasets is not None:
        extra["datasets"] = datasets
    search_config = ToolConfig(
        name="knowledge_search",
        group="knowledge",
        use="deerflow.community.ragflow.tools:knowledge_search_tool",
        **extra,
    )
    return SimpleNamespace(
        get_tool_config=lambda name: search_config if configured and name == "knowledge_search" else None,
    )


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeRAGFlowClient, *, config: SimpleNamespace | None = None) -> None:
    monkeypatch.setattr(ragflow_tools, "get_app_config", lambda: config or _config(datasets=[DATASET_ID_1]))
    monkeypatch.setattr(ragflow_tools, "_build_client", lambda settings: fake)


@pytest.mark.anyio
async def test_knowledge_search_resolves_configured_ids_to_current_names(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient(
        datasets_by_id={
            DATASET_ID_1: [{"id": DATASET_ID_1, "name": "HR Policies"}],
            DATASET_ID_2: [{"id": DATASET_ID_2, "name": "Engineering"}],
        },
        retrieval={
            "chunks": [
                {
                    "dataset_id": DATASET_ID_1,
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
    _install(monkeypatch, fake, config=_config(datasets=[DATASET_ID_1, DATASET_ID_2]))

    result = await ragflow_tools.knowledge_search("annual leave")

    assert fake.list_calls == [DATASET_ID_1, DATASET_ID_2]
    assert fake.retrieve_calls == [
        (
            "annual leave",
            {
                "dataset_ids": [DATASET_ID_1, DATASET_ID_2],
                "page_size": 8,
                "similarity_threshold": 0.2,
                "vector_similarity_weight": 0.3,
                "top_k": 256,
            },
        )
    ]
    assert "[1] HR Policies / handbook.pdf  (score 0.87)" in result
    assert "Annual leave" in result
    assert "Matched documents: handbook.pdf (1 chunk)" in result
    assert DATASET_ID_1 not in result
    assert DATASET_ID_2 not in result


@pytest.mark.anyio
async def test_knowledge_search_uses_id_filter_and_survives_dataset_rename(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient(
        datasets_by_id={DATASET_ID_1: [{"id": DATASET_ID_1, "name": "Renamed Policies"}]},
        retrieval={"chunks": [{"dataset_id": DATASET_ID_1, "document_keyword": "policy.pdf", "content": "Current policy."}]},
    )
    _install(monkeypatch, fake)

    result = await ragflow_tools.knowledge_search("leave")

    assert fake.list_calls == [DATASET_ID_1]
    assert fake.retrieve_calls[0][1]["dataset_ids"] == [DATASET_ID_1]
    assert "Renamed Policies / policy.pdf" in result
    assert DATASET_ID_1 not in result


@pytest.mark.anyio
async def test_missing_bound_dataset_returns_operator_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient()
    _install(monkeypatch, fake, config=_config(datasets=[MISSING_DATASET_ID]))

    result = await ragflow_tools.knowledge_search("leave")

    assert result == "Error: A configured RAGFlow dataset was not found or is inaccessible; check knowledge_search.datasets in config.yaml."
    assert MISSING_DATASET_ID not in result
    assert fake.list_calls == [MISSING_DATASET_ID]
    assert fake.retrieve_calls == []


@pytest.mark.anyio
async def test_missing_bound_dataset_error_does_not_expose_configured_id(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient()
    _install(monkeypatch, fake, config=_config(datasets=[MISSING_DATASET_ID]))

    result = await ragflow_tools.knowledge_search("leave")

    assert MISSING_DATASET_ID not in result
    assert "[DATASET_ID]" not in result


@pytest.mark.anyio
async def test_mismatched_id_filtered_response_returns_operator_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient(datasets_by_id={DATASET_ID_1: [{"id": DATASET_ID_2, "name": "Wrong dataset"}]})
    _install(monkeypatch, fake, config=_config(datasets=[DATASET_ID_1]))

    result = await ragflow_tools.knowledge_search("leave")

    assert result == "Error: A configured RAGFlow dataset was not found or is inaccessible; check knowledge_search.datasets in config.yaml."
    assert fake.retrieve_calls == []


@pytest.mark.anyio
async def test_missing_dataset_binding_lists_all_and_passes_every_id(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient(
        all_datasets=[
            {"id": DATASET_ID_1, "name": "HR Policies"},
            {"id": DATASET_ID_2, "name": "Engineering"},
        ],
        retrieval={"chunks": [{"dataset_id": DATASET_ID_2, "document_keyword": "guide.pdf", "content": "Build guide."}]},
    )
    _install(monkeypatch, fake, config=_config(datasets=None))

    result = await ragflow_tools.knowledge_search("leave")

    assert fake.list_calls == [None]
    assert fake.retrieve_calls[0][1]["dataset_ids"] == [DATASET_ID_1, DATASET_ID_2]
    assert "Engineering / guide.pdf" in result
    assert DATASET_ID_1 not in result
    assert DATASET_ID_2 not in result


@pytest.mark.anyio
async def test_missing_dataset_binding_with_empty_catalog_returns_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient()
    _install(monkeypatch, fake, config=_config(datasets=None))

    result = await ragflow_tools.knowledge_search("leave")

    assert result == "Error: No accessible RAGFlow datasets were found; configure knowledge_search.datasets or add a dataset in RAGFlow."
    assert fake.list_calls == [None]
    assert fake.retrieve_calls == []


@pytest.mark.anyio
async def test_missing_api_key_returns_english_guidance_and_warns_only_once(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeRAGFlowClient()
    _install(monkeypatch, fake, config=_config(api_key=None, datasets=[DATASET_ID_1]))

    with caplog.at_level(logging.WARNING, logger="deerflow.community.ragflow.tools"):
        first = await ragflow_tools.knowledge_search("leave")
        second = await ragflow_tools.knowledge_search("benefits")

    assert first == "Error: RAGFlow API key is not configured; set knowledge_search.api_key in config.yaml (prefer $RAGFLOW_API_KEY)."
    assert second == first
    assert caplog.text.count("RAGFlow API key is not configured") == 1
    assert fake.list_calls == []


@pytest.mark.anyio
async def test_missing_knowledge_search_config_returns_english_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient()
    _install(monkeypatch, fake, config=_config(configured=False, datasets=[DATASET_ID_1]))

    result = await ragflow_tools.knowledge_search("leave")

    assert result == "Error: knowledge_search is not configured; add its RAGFlow settings to the tools list in config.yaml."
    assert fake.list_calls == []


@pytest.mark.anyio
async def test_api_error_is_returned_as_readable_text(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient(error=RAGFlowAPIError("embedding models do not match", code=102))
    _install(monkeypatch, fake)

    result = await ragflow_tools.knowledge_search("leave")

    assert result == "Error: embedding models do not match"


@pytest.mark.anyio
async def test_error_path_redacts_dataset_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_id = "0123456789abcdef0123456789abcdef"
    fake = FakeRAGFlowClient(error=RAGFlowAPIError(f"dataset {dataset_id} failed", code=102))
    _install(monkeypatch, fake)

    result = await ragflow_tools.knowledge_search("leave")

    assert dataset_id not in result
    assert "[DATASET_ID]" in result


@pytest.mark.anyio
async def test_success_path_preserves_legitimate_uuid_and_md5_text(monkeypatch: pytest.MonkeyPatch) -> None:
    uuid = "123e4567-e89b-12d3-a456-426614174000"
    md5 = "d41d8cd98f00b204e9800998ecf8427e"
    fake = FakeRAGFlowClient(
        datasets_by_id={DATASET_ID_1: [{"id": DATASET_ID_1, "name": "HR Policies"}]},
        retrieval={
            "chunks": [
                {
                    "dataset_id": DATASET_ID_1,
                    "document_keyword": "checksums.txt",
                    "content": f"Trace {uuid}; checksum {md5}.",
                }
            ]
        },
    )
    _install(monkeypatch, fake)

    result = await ragflow_tools.knowledge_search("trace")

    assert uuid in result
    assert md5 in result
    assert "[DATASET_ID]" not in result


@pytest.mark.anyio
async def test_success_path_still_redacts_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient(
        datasets_by_id={DATASET_ID_1: [{"id": DATASET_ID_1, "name": "HR Policies"}]},
        retrieval={
            "chunks": [
                {
                    "dataset_id": DATASET_ID_1,
                    "document_keyword": "secret.txt",
                    "content": "Accidental echo: ragflow-secret",
                }
            ]
        },
    )
    _install(monkeypatch, fake)

    result = await ragflow_tools.knowledge_search("secret")

    assert "ragflow-secret" not in result
    assert "[REDACTED]" in result


@pytest.mark.anyio
async def test_connection_error_is_english_and_does_not_leak_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeRAGFlowClient(error=RAGFlowConnectionError("ConnectError: refused ragflow-secret"))
    _install(monkeypatch, fake)

    with caplog.at_level(logging.WARNING, logger="deerflow.community.ragflow.tools"):
        result = await ragflow_tools.knowledge_search("leave")

    assert result == "Error: Unable to connect to RAGFlow (http://ragflow.test): ConnectError: refused [REDACTED]"
    assert "ragflow-secret" not in result
    assert "ragflow-secret" not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "base_url",
    [
        "http://ragflow-secret@ragflow.test",
        "http://ragflow%2Dsecret@ragflow.test",
        "http://user:ragflow-secret@ragflow.test",
    ],
)
async def test_base_url_with_plain_or_encoded_userinfo_is_rejected_without_leaking_credentials(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    base_url: str,
) -> None:
    fake = FakeRAGFlowClient()
    _install(monkeypatch, fake, config=_config(base_url=base_url, datasets=[DATASET_ID_1]))

    with caplog.at_level(logging.WARNING, logger="deerflow.community.ragflow.tools"):
        result = await ragflow_tools.knowledge_search("leave")

    assert result == "Error: Invalid RAGFlow settings for knowledge_search; check config.yaml."
    assert "ragflow-secret" not in result
    assert "ragflow-secret" not in caplog.text
    assert "ragflow%2Dsecret" not in caplog.text
    assert fake.list_calls == []


@pytest.mark.anyio
async def test_empty_query_has_english_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient()
    _install(monkeypatch, fake)

    result = await ragflow_tools.knowledge_search("   ")

    assert result == "Error: query must not be empty."
    assert fake.list_calls == []


@pytest.mark.anyio
async def test_empty_retrieval_has_explicit_english_message(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRAGFlowClient(datasets_by_id={DATASET_ID_1: [{"id": DATASET_ID_1, "name": "HR Policies"}]})
    _install(monkeypatch, fake)

    result = await ragflow_tools.knowledge_search("nothing")

    assert result == "No relevant content found."


def test_formatting_uses_only_normalized_chunk_fields() -> None:
    result = format_retrieval_result(
        {
            "chunks": [
                {
                    "kb_id": "dataset-1",
                    "doc_id": "doc-legacy",
                    "docnm_kwd": "legacy.pdf",
                    "content": "abcdefghij",
                    "similarity": 0.5,
                }
            ]
        },
        dataset_names_by_id={"dataset-1": "HR Policies"},
        max_chars_per_chunk=5,
        max_total_chars=1000,
    )

    assert "Unknown dataset / Unknown document" in result
    assert "HR Policies" not in result
    assert "legacy.pdf" not in result
    assert "abcd…" in result
    assert "abcdefghij" not in result
    assert "dataset-1" not in result


def test_formatting_applies_total_response_truncation_in_english() -> None:
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
    assert result.endswith("… (response truncated)")


def test_retrieval_settings_load_bound_dataset_ids_and_hide_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ragflow_tools, "get_app_config", lambda: _config(datasets=[DATASET_ID_1, DATASET_ID_2]))

    config, error = ragflow_tools._settings_or_error()

    assert error is None
    assert config is not None
    assert config.datasets == [DATASET_ID_1, DATASET_ID_2]
    assert str(config.base_url).rstrip("/") == "http://ragflow.test"
    assert config.page_size == 8
    assert config.max_chars_per_chunk == 800
    assert config.max_total_chars == 8000
    assert "ragflow-secret" not in repr(config)


def test_retrieval_settings_allow_omitting_dataset_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ragflow_tools, "get_app_config", lambda: _config(datasets=None))

    config, error = ragflow_tools._settings_or_error()

    assert error is None
    assert config is not None
    assert config.datasets is None


def test_agent_exposes_only_query_on_single_search_tool() -> None:
    assert not hasattr(ragflow_tools, "list_knowledge_bases_tool")
    assert not hasattr(ragflow_tools, "list_knowledge_bases")
    assert ragflow_tools.knowledge_search_tool.name == "knowledge_search"
    assert ragflow_tools.knowledge_search_tool.coroutine is not None
    assert set(ragflow_tools.knowledge_search_tool.tool_call_schema.model_fields) == {"query"}


def test_tool_assembly_hides_bound_dataset_ids_without_network_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ragflow_tools, "_build_client", lambda settings: pytest.fail("tool assembly must not perform network IO"))
    tool_config = ToolConfig(
        name="knowledge_search",
        group="knowledge",
        use="deerflow.community.ragflow.tools:knowledge_search_tool",
        base_url="http://ragflow.test",
        api_key="ragflow-secret",
        datasets=[DATASET_ID_1, DATASET_ID_2],
    )
    config = SimpleNamespace(
        tools=[tool_config],
        sandbox=SimpleNamespace(use="example.remote:Sandbox"),
        skill_evolution=SimpleNamespace(enabled=False),
        models=[],
        acp_agents={},
        get_model_config=lambda name: None,
    )

    tools = get_available_tools(include_mcp=False, app_config=config)
    assembled = next(tool for tool in tools if tool.name == "knowledge_search")

    assert "If knowledge_search.datasets is omitted" in assembled.description
    assert "all datasets accessible to the configured RAGFlow API key" in assembled.description
    assert DATASET_ID_1 not in assembled.description
    assert DATASET_ID_2 not in assembled.description
    assert "ragflow-secret" not in assembled.description
    assert {tool.name for tool in tools}.isdisjoint({"list_knowledge_bases"})


def test_ragflow_package_has_explicit_init_file() -> None:
    package_dir = Path(ragflow_tools.__file__).resolve().parent

    assert (package_dir / "__init__.py").is_file()
