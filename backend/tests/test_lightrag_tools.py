import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import deerflow.community.lightrag.tools as lightrag_tools
from deerflow.community.lightrag.client import LightRAGAPIError, LightRAGConnectionError
from deerflow.community.lightrag.formatting import format_retrieval_result
from deerflow.config.tool_config import ToolConfig
from deerflow.tools.tools import get_available_tools

CHUNK_ID = "71a4613a-e91b-4d3b-bdff-6f45d9ac1f80"


def _data(
    *,
    chunks: list[dict[str, Any]] | None = None,
    references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "chunks": chunks if chunks is not None else [],
        "references": references if references is not None else [],
        "entities": [],
        "relationships": [],
    }


class FakeLightRAGClient:
    def __init__(self, *, data: dict | None = None, error: Exception | None = None) -> None:
        self.data = data if data is not None else _data()
        self.error = error
        self.query_calls: list[tuple[str, dict]] = []

    async def query_data(self, query: str, **kwargs: object) -> dict:
        if self.error is not None:
            raise self.error
        self.query_calls.append((query, kwargs))
        return self.data


def _config(
    *,
    configured: bool = True,
    api_key: str | None = "lightrag-secret",
    base_url: str = "http://lightrag.test",
    mode: str = "mix",
    extra: dict[str, object] | None = None,
) -> SimpleNamespace:
    settings: dict[str, object] = {
        "base_url": base_url,
        "api_key": api_key,
        "mode": mode,
        "timeout": 30,
        "top_k": 60,
        "max_chars_per_chunk": 800,
        "max_total_chars": 8000,
    }
    settings.update(extra or {})
    search_config = ToolConfig(
        name="knowledge_search",
        group="knowledge",
        use="deerflow.community.lightrag.tools:knowledge_search_tool",
        **settings,
    )
    return SimpleNamespace(
        get_tool_config=lambda name: search_config if configured and name == "knowledge_search" else None,
    )


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeLightRAGClient, *, config: SimpleNamespace | None = None) -> None:
    monkeypatch.setattr(lightrag_tools, "get_app_config", lambda: config or _config())
    monkeypatch.setattr(lightrag_tools, "_build_client", lambda settings: fake)


@pytest.mark.anyio
async def test_knowledge_search_formats_citation_numbered_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLightRAGClient(
        data=_data(
            chunks=[
                {
                    "content": "Annual leave is based on years of service.",
                    "file_path": "documents/handbook.md",
                    "chunk_id": CHUNK_ID,
                    "reference_id": "3",
                },
                {
                    "content": "Sick leave requires a medical certificate.",
                    "file_path": "documents/handbook.md",
                    "chunk_id": "71a4613a-e91b-4d3b-bdff-6f45d9ac1f81",
                    "reference_id": "3",
                },
            ],
            references=[{"reference_id": "3", "file_path": "documents/handbook.md"}],
        )
    )
    _install(monkeypatch, fake)

    result = await lightrag_tools.knowledge_search("annual leave")

    assert fake.query_calls == [("annual leave", {"mode": "mix", "top_k": 60, "chunk_top_k": None})]
    assert "[1] documents/handbook.md\nAnnual leave is based on years of service." in result
    assert "[2] documents/handbook.md\nSick leave requires a medical certificate." in result
    assert "Matched documents: documents/handbook.md (2 chunks)" in result
    assert CHUNK_ID not in result


@pytest.mark.anyio
async def test_knowledge_search_resolves_missing_chunk_file_path_from_references(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLightRAGClient(
        data=_data(
            chunks=[{"content": "Graph-reconstructed context.", "chunk_id": CHUNK_ID, "reference_id": "7"}],
            references=[{"reference_id": "7", "file_path": "documents/graph-notes.md"}],
        )
    )
    _install(monkeypatch, fake)

    result = await lightrag_tools.knowledge_search("graph")

    assert "[1] documents/graph-notes.md\nGraph-reconstructed context." in result
    assert "Unknown document" not in result


@pytest.mark.anyio
async def test_knowledge_search_sends_configured_retrieval_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLightRAGClient(data=_data(chunks=[{"content": "Guide.", "file_path": "docs/guide.md"}]))
    _install(monkeypatch, fake, config=_config(mode="local", extra={"top_k": 12, "chunk_top_k": 6}))

    result = await lightrag_tools.knowledge_search("guide")

    assert fake.query_calls == [("guide", {"mode": "local", "top_k": 12, "chunk_top_k": 6})]
    assert "Guide." in result


@pytest.mark.anyio
async def test_knowledge_search_works_without_api_key_for_unauthenticated_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeLightRAGClient(data=_data(chunks=[{"content": "Open knowledge.", "file_path": "docs/open.md"}]))
    _install(monkeypatch, fake, config=_config(api_key=None))

    result = await lightrag_tools.knowledge_search("open")

    assert "Open knowledge." in result
    assert fake.query_calls


@pytest.mark.anyio
async def test_blank_api_key_is_treated_as_unauthenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLightRAGClient(data=_data(chunks=[{"content": "Open knowledge.", "file_path": "docs/open.md"}]))
    _install(monkeypatch, fake, config=_config(api_key="   "))

    result = await lightrag_tools.knowledge_search("open")

    assert "Open knowledge." in result
    assert fake.query_calls


@pytest.mark.anyio
async def test_missing_knowledge_search_config_returns_english_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLightRAGClient()
    _install(monkeypatch, fake, config=_config(configured=False))

    result = await lightrag_tools.knowledge_search("leave")

    assert result == "Error: knowledge_search is not configured; add its LightRAG settings to the tools list in config.yaml."
    assert fake.query_calls == []


@pytest.mark.anyio
async def test_invalid_settings_return_english_guidance_without_leaking_values(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeLightRAGClient()
    _install(monkeypatch, fake, config=_config(mode="vector"))

    with caplog.at_level(logging.WARNING, logger="deerflow.community.lightrag.tools"):
        result = await lightrag_tools.knowledge_search("leave")

    assert result == "Error: Invalid LightRAG settings for knowledge_search; check config.yaml."
    assert "vector" not in caplog.text
    assert fake.query_calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    "base_url",
    [
        "http://lightrag-secret@lightrag.test",
        "http://lightrag%2Dsecret@lightrag.test",
        "http://user:lightrag-secret@lightrag.test",
    ],
)
async def test_base_url_with_plain_or_encoded_userinfo_is_rejected_without_leaking_credentials(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    base_url: str,
) -> None:
    fake = FakeLightRAGClient()
    _install(monkeypatch, fake, config=_config(base_url=base_url))

    with caplog.at_level(logging.WARNING, logger="deerflow.community.lightrag.tools"):
        result = await lightrag_tools.knowledge_search("leave")

    assert result == "Error: Invalid LightRAG settings for knowledge_search; check config.yaml."
    assert "lightrag-secret" not in result
    assert "lightrag-secret" not in caplog.text
    assert "lightrag%2Dsecret" not in caplog.text
    assert fake.query_calls == []


@pytest.mark.anyio
async def test_empty_query_has_english_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLightRAGClient()
    _install(monkeypatch, fake)

    result = await lightrag_tools.knowledge_search("   ")

    assert result == "Error: query must not be empty."
    assert fake.query_calls == []


@pytest.mark.anyio
async def test_empty_retrieval_has_explicit_english_message(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLightRAGClient()
    _install(monkeypatch, fake)

    result = await lightrag_tools.knowledge_search("nothing")

    assert result == "No relevant content found."


@pytest.mark.anyio
async def test_api_error_is_returned_as_readable_text_and_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeLightRAGClient(error=LightRAGAPIError("RAG query is too short"))
    _install(monkeypatch, fake)

    with caplog.at_level(logging.WARNING, logger="deerflow.community.lightrag.tools"):
        result = await lightrag_tools.knowledge_search("ab")

    assert result == "Error: RAG query is too short"
    assert "too short" in caplog.text


@pytest.mark.anyio
async def test_connection_error_is_english_and_does_not_leak_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeLightRAGClient(error=LightRAGConnectionError("ConnectError: refused lightrag-secret"))
    _install(monkeypatch, fake)

    with caplog.at_level(logging.WARNING, logger="deerflow.community.lightrag.tools"):
        result = await lightrag_tools.knowledge_search("leave")

    assert result == "Error: Unable to connect to LightRAG (http://lightrag.test): ConnectError: refused [REDACTED]"
    assert "lightrag-secret" not in result
    assert "lightrag-secret" not in caplog.text


@pytest.mark.anyio
async def test_success_path_still_redacts_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLightRAGClient(data=_data(chunks=[{"content": "Accidental echo: lightrag-secret", "file_path": "docs/secret.md"}]))
    _install(monkeypatch, fake)

    result = await lightrag_tools.knowledge_search("secret")

    assert "lightrag-secret" not in result
    assert "[REDACTED]" in result


def test_formatting_uses_only_documented_chunk_fields() -> None:
    result = format_retrieval_result(
        {
            "chunks": [
                {
                    "content": "abcdefghij",
                    "file_path": "docs/policy.md",
                    "chunk_id": CHUNK_ID,
                    "reference_id": "1",
                    "unexpected_future_field": "ignored",
                }
            ],
            "references": [{"reference_id": "1", "file_path": "docs/policy.md"}],
        },
        max_chars_per_chunk=5,
        max_total_chars=1000,
    )

    assert "[1] docs/policy.md" in result
    assert "abcd…" in result
    assert "abcdefghij" not in result
    assert CHUNK_ID not in result


def test_formatting_without_chunk_file_path_or_reference_labels_unknown_document() -> None:
    result = format_retrieval_result({"chunks": [{"content": "Orphan chunk.", "chunk_id": CHUNK_ID}]})

    assert "[1] Unknown document\nOrphan chunk." in result
    assert CHUNK_ID not in result


def test_formatting_applies_total_response_truncation_in_english() -> None:
    result = format_retrieval_result(
        {"chunks": [{"content": "content " * 20, "file_path": f"documents/document-{index}.md"} for index in range(4)]},
        max_chars_per_chunk=100,
        max_total_chars=120,
    )

    assert len(result) <= 120
    assert result.endswith("… (response truncated)")


def test_retrieval_settings_load_provider_fields_and_hide_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lightrag_tools, "get_app_config", lambda: _config(mode="mix", extra={"top_k": 12, "chunk_top_k": 6}))

    config, error = lightrag_tools._settings_or_error()

    assert error is None
    assert config is not None
    assert str(config.base_url).rstrip("/") == "http://lightrag.test"
    assert config.mode == "mix"
    assert config.top_k == 12
    assert config.chunk_top_k == 6
    assert config.max_chars_per_chunk == 800
    assert config.max_total_chars == 8000
    assert "lightrag-secret" not in repr(config)


def test_retrieval_settings_allow_omitting_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lightrag_tools, "get_app_config", lambda: _config(api_key=None))

    config, error = lightrag_tools._settings_or_error()

    assert error is None
    assert config is not None
    assert config.api_key is None


def test_agent_exposes_only_query_on_single_search_tool() -> None:
    assert not hasattr(lightrag_tools, "list_knowledge_bases_tool")
    assert not hasattr(lightrag_tools, "list_knowledge_bases")
    assert lightrag_tools.knowledge_search_tool.name == "knowledge_search"
    assert lightrag_tools.knowledge_search_tool.coroutine is not None
    assert set(lightrag_tools.knowledge_search_tool.tool_call_schema.model_fields) == {"query"}


def test_tool_assembly_hides_credentials_without_network_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lightrag_tools, "_build_client", lambda settings: pytest.fail("tool assembly must not perform network IO"))
    tool_config = ToolConfig(
        name="knowledge_search",
        group="knowledge",
        use="deerflow.community.lightrag.tools:knowledge_search_tool",
        base_url="http://lightrag.test",
        api_key="lightrag-secret",
        mode="hybrid",
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

    assert "LightRAG" in assembled.description
    assert "lightrag-secret" not in assembled.description
    assert {tool.name for tool in tools}.isdisjoint({"list_knowledge_bases"})


def test_retrieval_settings_default_mode_matches_lightrag_request_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lightrag_tools, "get_app_config", lambda: _config(mode="mix"))

    config, error = lightrag_tools._settings_or_error()

    assert error is None
    assert config is not None
    assert config.mode == "mix"


def test_shared_knowledge_search_name_keeps_first_configured_entry() -> None:
    """RAGFlow and LightRAG share the ``knowledge_search`` tool name.

    This pins the config-layer behavior for that shared name so an operator
    accidentally configuring both entries gets a documented outcome (the
    first entry wins) instead of silent provider swapping.
    """
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig

    ragflow_entry = ToolConfig(
        name="knowledge_search",
        group="knowledge",
        use="deerflow.community.ragflow.tools:knowledge_search_tool",
    )
    lightrag_entry = ToolConfig(
        name="knowledge_search",
        group="knowledge",
        use="deerflow.community.lightrag.tools:knowledge_search_tool",
    )

    config = AppConfig(tools=[ragflow_entry, lightrag_entry], sandbox=SandboxConfig(use="example.remote:Sandbox"))

    assert config.get_tool_config("knowledge_search") is ragflow_entry


def test_lightrag_package_has_explicit_init_file() -> None:
    package_dir = Path(lightrag_tools.__file__).resolve().parent

    assert (package_dir / "__init__.py").is_file()
