"""Sectioned long-form writing plugin through the real plugin tool path."""

import asyncio
from pathlib import Path

import pytest
from deerflow_extension_api.auth import ExtensionPrincipal
from deerflow_extension_api.plugins import ToolContext

from deerflow.extensions.loader import ExtensionSpec, load_extensions
from deerflow.extensions.plugin_tools import build_plugin_tools

EXAMPLE = Path(__file__).resolve().parents[2] / "examples/deerflow-extension-report-sections"

OUTLINE = "# 2026 年新能源汽车行业研究报告\n\n本报告分五章。"
SECTION_WITH_TITLE = "# 一、行业概述与研究方法\n\n行业概述正文。"
SECTION_HASH_SUFFIX = "### 二、市场格局与竞争态势 ###\n\n竞争态势正文。"


@pytest.fixture
def syspath(monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLE))


@pytest.fixture
def load(syspath, tmp_path):
    def _load(**config):
        loaded, diagnostics = load_extensions(
            [
                ExtensionSpec(
                    use="deerflow_extension_report_sections:install",
                    config={"enabled": True, "storage_path": str(tmp_path / "sections.sqlite"), **config},
                )
            ]
        )
        assert not diagnostics, diagnostics
        return loaded

    return _load


def handler(loaded):
    ((_, plugin),) = loaded.plugins
    (tool,) = plugin.tools
    assert tool.name == "save_section"
    assert tool.response_format == "content_and_artifact"
    return tool.handler


def context(user="alice", thread="thread-1"):
    return ToolContext(ExtensionPrincipal(user), {"enabled": True}, thread)


def save(handle, section_index, title, content, user="alice", thread="thread-1"):
    return asyncio.run(handle({"section_index": section_index, "title": title, "content": content}, context(user, thread)))


def assemble(handle, user="alice", thread="thread-1"):
    return asyncio.run(handle({"section_index": 999, "title": "__assemble__", "content": ""}, context(user, thread)))


def seed(handle):
    save(handle, 0, "2026 年新能源汽车行业研究报告", OUTLINE)
    save(handle, 1, "一、行业概述与研究方法", SECTION_WITH_TITLE)
    save(handle, 2, "二、市场格局与竞争态势", SECTION_HASH_SUFFIX)


def test_registration_exposes_one_assembling_tool(load):
    handle = handler(load())
    status = save(handle, 1, "一、章节", "正文内容。")
    assert status.content.startswith("OK section 1")
    assert status.artifact is None


def test_assembly_strips_duplicate_headings_and_keeps_unique_ones(load):
    handle = handler(load())
    seed(handle)
    result = assemble(handle)
    assert result.content.startswith("OK assembled 3 sections")
    document = result.artifact["document"]
    # The assembler's own heading is the only occurrence for each section.
    assert document.count("一、行业概述与研究方法") == 1
    assert document.count("二、市场格局与竞争态势") == 1
    assert "### 二、市场格局与竞争态势 ###" not in document
    assert document.count("## 一、行业概述与研究方法") == 1
    # The outline passes through unwrapped and keeps its own opening heading.
    assert document.startswith("# 2026 年新能源汽车行业研究报告")
    assert result.artifact["filename"].startswith("report-")
    assert result.artifact["sections"] == 3


def test_strip_duplicate_title_heading_variants(syspath):
    from deerflow_extension_report_sections.sections import strip_duplicate_title_heading

    assert strip_duplicate_title_heading("# 摘要\n正文", "摘要") == "正文"
    assert strip_duplicate_title_heading("### 摘要 ###\n正文", "  摘要  ") == "正文"
    assert strip_duplicate_title_heading("正文没有标题", "摘要") == "正文没有标题"
    # A heading that does not restate the title is content, not a duplicate.
    assert strip_duplicate_title_heading("# 其他标题\n正文", "摘要") == "# 其他标题\n正文"


def test_assemble_document_counts_stripped_bodies(syspath):
    from deerflow_extension_report_sections.sections import assemble_document

    rows = [
        {"section_index": 0, "title": "大纲", "content": "# 大纲\n引言。"},
        {"section_index": 1, "title": "一、背景", "content": "# 一、背景\n背景正文。"},
    ]
    document, total_chars = assemble_document(rows)
    # The outline keeps its own heading (it becomes the document title);
    # wrapped sections drop their duplicate opening heading.
    assert total_chars == len("# 大纲\n引言。") + len("背景正文。")
    assert document.startswith("# 大纲")
    assert "\n\n## 一、背景\n\n背景正文。" in document


def test_sections_are_scoped_per_user_and_thread(load):
    handle = handler(load())
    seed(handle)
    for user, thread in (("bob", "thread-1"), ("alice", "thread-2")):
        empty = assemble(handle, user=user, thread=thread)
        assert empty.content.startswith("ERROR: no sections saved yet")


def test_empty_section_content_is_refused(load):
    handle = handler(load())
    refused = save(handle, 1, "一、章节", "  \n")
    assert refused.content.startswith("ERROR: content is empty")


def test_missing_thread_context_is_refused(load):
    handle = handler(load())
    no_thread = ToolContext(ExtensionPrincipal("alice"), {"enabled": True}, None)
    refused = asyncio.run(handle({"section_index": 1, "title": "一", "content": "正文"}, no_thread))
    assert refused.content.startswith("ERROR: no user or thread context")


def test_resaving_a_section_replaces_it(load):
    handle = handler(load())
    save(handle, 1, "一、章节", "第一版正文。")
    save(handle, 1, "一、章节", "第二版正文。")
    result = assemble(handle)
    assert result.artifact["sections"] == 1
    assert "第一版" not in result.artifact["document"]
    assert "第二版正文。" in result.artifact["document"]


def test_oversized_assembly_is_refused_but_sections_remain(load):
    handle = handler(load())
    body = "字" * 20_000
    for index in range(1, 5):
        save(handle, index, f"第{index}章", body)
    refused = assemble(handle)
    assert "over the" in refused.content
    assert refused.artifact is None
    # The stored sections are intact for a replacement save.
    trimmed = save(handle, 1, "第1章", "短正文。")
    assert trimmed.content.startswith("OK section 1")


def test_disabled_contribution_builds_no_tool(load):
    loaded = load(enabled=False)
    tools = build_plugin_tools(loaded, groups=("extensions",))
    assert tools == []


def test_real_tool_dispatch_delivers_document_as_artifact(load):
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    (tool,) = build_plugin_tools(load(), groups=("extensions",))
    graph = StateGraph(MessagesState)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    compiled = graph.compile()

    def dispatch(section_index, title, content):
        return asyncio.run(
            compiled.ainvoke(
                {"messages": [AIMessage(content="", tool_calls=[{"id": "c", "name": tool.name, "args": {"section_index": section_index, "title": title, "content": content}}])]},
                context={"user_id": "alice", "thread_id": "thread-1"},
            )
        )["messages"][-1]

    saved = dispatch(1, "一、章节", "正文。")
    assert saved.status != "error"
    assert saved.content.startswith("OK section 1")
    assert getattr(saved, "artifact", None) is None

    assembled = dispatch(999, "__assemble__", "")
    assert assembled.status != "error"
    assert assembled.content.startswith("OK assembled 1 sections")
    artifact = assembled.artifact
    assert artifact["filename"].startswith("report-")
    assert artifact["document"].endswith("\n")
    assert "## 一、章节" in artifact["document"]
