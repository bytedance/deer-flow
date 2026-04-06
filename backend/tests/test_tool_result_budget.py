import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.community.firecrawl import tools as firecrawl_tools
from deerflow.community.infoquest import tools as infoquest_tools
from deerflow.community.jina_ai import tools as jina_tools
from deerflow.community.tavily import tools as tavily_tools
from deerflow.config.context_management_config import ContextManagementConfig, ToolResultBudgetConfig, set_context_management_config
from deerflow.context.tool_output_budget import prepare_tool_output_for_context, prepare_tool_result_value_for_context


@pytest.fixture(autouse=True)
def _reset_context_management_config():
    set_context_management_config(ContextManagementConfig())
    yield
    set_context_management_config(ContextManagementConfig())


def test_prepare_tool_output_externalizes_oversized_result(tmp_path: Path):
    set_context_management_config(
        ContextManagementConfig(
            tool_result_budget=ToolResultBudgetConfig(
                enabled=True,
                externalize_min_chars=20,
                preview_head_chars=5,
                preview_tail_chars=4,
            )
        )
    )
    outputs_dir = tmp_path / "outputs"
    thread_data = {"outputs_path": str(outputs_dir)}

    result = prepare_tool_output_for_context("abcdefghijklmnopqrstuvwxyz", tool_name="bash", thread_data=thread_data)

    assert "Full bash output saved to /mnt/user-data/outputs/.context/tool-results/" in result
    assert "abcde" in result
    assert "wxyz" in result
    saved_files = list((outputs_dir / ".context" / "tool-results").glob("bash-*.log"))
    assert len(saved_files) == 1
    assert saved_files[0].read_text(encoding="utf-8") == "abcdefghijklmnopqrstuvwxyz"


@pytest.mark.parametrize("storage_subdir", ["/tmp/outside", "../outside", ".context/../outside"])
def test_prepare_tool_output_rejects_unsafe_storage_subdir(tmp_path: Path, storage_subdir: str):
    set_context_management_config(
        ContextManagementConfig(
            tool_result_budget=ToolResultBudgetConfig(
                enabled=True,
                externalize_min_chars=20,
                preview_head_chars=5,
                preview_tail_chars=4,
                storage_subdir=storage_subdir,
            )
        )
    )
    outputs_dir = tmp_path / "outputs"
    thread_data = {"outputs_path": str(outputs_dir)}

    result = prepare_tool_output_for_context("abcdefghijklmnopqrstuvwxyz", tool_name="bash", thread_data=thread_data)

    assert "Full bash output saved to" not in result
    assert "characters omitted from bash output" not in result
    assert list(tmp_path.glob("outside*")) == []
    assert not (outputs_dir / ".context" / "tool-results").exists()


def test_prepare_tool_output_falls_back_to_truncation_when_budget_disabled():
    set_context_management_config(
        ContextManagementConfig(
            tool_result_budget=ToolResultBudgetConfig(
                enabled=False,
            )
        )
    )

    content = "x" * 30010
    result = prepare_tool_output_for_context(content, tool_name="read_file", thread_data=None)

    assert "characters omitted from read_file output" in result
    assert "Full read_file output saved to" not in result


def test_prepare_tool_output_externalizes_web_search_results(tmp_path: Path):
    set_context_management_config(
        ContextManagementConfig(
            tool_result_budget=ToolResultBudgetConfig(
                enabled=True,
                externalize_min_chars=20,
                preview_head_chars=8,
                preview_tail_chars=5,
            )
        )
    )
    outputs_dir = tmp_path / "outputs"
    thread_data = {"outputs_path": str(outputs_dir)}

    result = prepare_tool_output_for_context(
        "search-result-payload-with-many-lines",
        tool_name="web_search",
        thread_data=thread_data,
    )

    assert "Full web_search output saved to /mnt/user-data/outputs/.context/tool-results/" in result
    saved_files = list((outputs_dir / ".context" / "tool-results").glob("web_search-*.txt"))
    assert len(saved_files) == 1


def test_prepare_tool_result_value_externalizes_large_structured_result(tmp_path: Path):
    set_context_management_config(
        ContextManagementConfig(
            tool_result_budget=ToolResultBudgetConfig(
                enabled=True,
                externalize_min_chars=20,
                preview_head_chars=12,
                preview_tail_chars=8,
            )
        )
    )
    outputs_dir = tmp_path / "outputs"
    thread_data = {"outputs_path": str(outputs_dir)}

    result = prepare_tool_result_value_for_context(
        {"content": "x" * 80, "url": "https://example.com"},
        tool_name="x-reader_read_url",
        thread_data=thread_data,
    )

    assert isinstance(result, str)
    assert "Full x-reader_read_url output saved to /mnt/user-data/outputs/.context/tool-results/" in result
    saved_files = list((outputs_dir / ".context" / "tool-results").glob("x-reader_read_url-*.txt"))
    assert len(saved_files) == 1


@pytest.mark.parametrize(
    ("tool_fn", "client_patch_target", "thread_data_patch_target", "readability_patch_target", "mock_value"),
    [
        (
            firecrawl_tools.web_fetch_tool.run,
            "deerflow.community.firecrawl.tools._get_firecrawl_client",
            "deerflow.community.firecrawl.tools.resolve_thread_data_from_config",
            None,
            ("firecrawl", "# Title\n\n" + ("x" * 80)),
        ),
        (
            infoquest_tools.web_fetch_tool.run,
            "deerflow.community.infoquest.tools._get_infoquest_client",
            "deerflow.community.infoquest.tools.resolve_thread_data_from_config",
            "deerflow.community.infoquest.tools.readability_extractor",
            ("infoquest", "<html><body>" + ("x" * 120) + "</body></html>"),
        ),
        (
            tavily_tools.web_fetch_tool.run,
            "deerflow.community.tavily.tools._get_tavily_client",
            "deerflow.community.tavily.tools.resolve_thread_data_from_config",
            None,
            ("tavily", {"results": [{"title": "Title", "raw_content": "x" * 120}]}),
        ),
    ],
)
def test_web_fetch_tools_externalize_large_payloads(
    tmp_path: Path,
    tool_fn,
    client_patch_target: str,
    thread_data_patch_target: str,
    readability_patch_target: str | None,
    mock_value,
):
    set_context_management_config(
        ContextManagementConfig(
            tool_result_budget=ToolResultBudgetConfig(
                enabled=True,
                externalize_min_chars=20,
                preview_head_chars=10,
                preview_tail_chars=8,
            )
        )
    )
    outputs_dir = tmp_path / "outputs"

    with patch(thread_data_patch_target, return_value={"outputs_path": str(outputs_dir)}):
        kind, payload = mock_value
        if kind == "firecrawl":
            mock_client = MagicMock()
            mock_client.scrape.return_value = MagicMock(markdown=payload, metadata=MagicMock(title="Title"))
            with patch(client_patch_target, return_value=mock_client):
                result = tool_fn("https://example.com")
        elif kind == "infoquest":
            mock_client = MagicMock()
            mock_client.fetch.return_value = payload
            mock_article = MagicMock()
            mock_article.to_markdown.return_value = "# Untitled\n\n" + ("x" * 120)
            with patch(client_patch_target, return_value=mock_client), patch(readability_patch_target, MagicMock(extract_article=MagicMock(return_value=mock_article))):
                result = tool_fn("https://example.com")
        else:
            mock_client = MagicMock()
            mock_client.extract.return_value = payload
            with patch(client_patch_target, return_value=mock_client):
                result = tool_fn("https://example.com")

    assert "Full web_fetch output saved to /mnt/user-data/outputs/.context/tool-results/" in result
    saved_files = list((outputs_dir / ".context" / "tool-results").glob("web_fetch-*.log"))
    assert len(saved_files) == 1


def test_jina_web_fetch_passes_full_content_to_budget_helper():
    html_payload = "<html><body>" + ("x" * 5000) + "</body></html>"
    mock_article = MagicMock()
    mock_article.to_markdown.return_value = "# Untitled\n\n" + ("x" * 5000)

    with (
        patch("deerflow.community.jina_ai.tools.JinaClient") as mock_client_cls,
        patch("deerflow.community.jina_ai.tools.get_app_config", return_value=MagicMock(get_tool_config=MagicMock(return_value=None))),
        patch("deerflow.community.jina_ai.tools.readability_extractor", MagicMock(extract_article=MagicMock(return_value=mock_article))),
        patch("deerflow.community.jina_ai.tools.resolve_thread_data_from_config", return_value={"outputs_path": "/tmp/jina-out"}),
        patch("deerflow.community.jina_ai.tools.prepare_tool_output_for_context", return_value="budgeted") as mock_budget,
    ):
        mock_client = MagicMock()
        mock_client.crawl = AsyncMock(return_value=html_payload)
        mock_client_cls.return_value = mock_client

        result = asyncio.run(jina_tools.web_fetch_tool.ainvoke({"url": "https://example.com"}))

    assert result == "budgeted"
    passed_content = mock_budget.call_args.kwargs["content"]
    assert len(passed_content) > 4096
