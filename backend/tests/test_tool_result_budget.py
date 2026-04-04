from pathlib import Path

import pytest

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
