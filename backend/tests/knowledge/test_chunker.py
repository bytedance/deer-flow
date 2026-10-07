"""Tests for the structure-aware markdown chunker (spec §3.2).

Strategy under test: H1/H2 heading-boundary splits; blocks > 1024 tokens are
subdivided by paragraph; blocks < 100 tokens merge into the previous sibling
(only when the merged block stays within the size cap); every chunk carries
``heading_path`` / ``chunk_index`` / ``token_count``; target 512±256.

Fixture token distribution (cl100k_base, measured):
- 第一章 block: 449 tokens
- 1.1 block: 32 tokens  → merged forward into the 第一章 block (≈481)
- 1.2 block: 1055 tokens → paragraph-packed into 1016 + 38 (code fence tail)
- 第二章 block: 236 tokens
"""

from __future__ import annotations

from pathlib import Path

from deerflow_knowledge.chunker import MAX_CHUNK_TOKENS, chunk_markdown, count_tokens

FIXTURE_MD = (Path(__file__).parent / "fixtures" / "sample.md").read_text(encoding="utf-8")


class TestHeadingBoundarySplits:
    def test_splits_on_h1_h2_boundaries(self):
        chunks = chunk_markdown(FIXTURE_MD, "doc-1")
        assert len(chunks) == 4
        assert chunks[0].heading_path == ["第一章 知识库概述"]
        assert chunks[1].heading_path == ["第一章 知识库概述", "1.2 大规模语料处理"]
        assert chunks[3].heading_path == ["第二章 检索架构"]

    def test_h3_does_not_split_but_stays_in_text(self):
        md = "# 章\n\n" + "正文。" * 30 + "\n\n### 小节标题\n\n" + "更多正文。" * 20
        chunks = chunk_markdown(md, "doc-1")
        assert len(chunks) == 1
        assert "### 小节标题" in chunks[0].text

    def test_code_fence_hash_comment_is_not_a_boundary(self):
        chunks = chunk_markdown(FIXTURE_MD, "doc-1")
        fence_chunks = [c for c in chunks if "```python" in c.text]
        assert len(fence_chunks) == 1
        assert "# 这是一行代码注释，不是标题，绝不能触发切块" in fence_chunks[0].text

    def test_content_before_first_heading_gets_empty_path(self):
        md = "前言段落，没有任何标题。\n\n# 第一章\n\n" + "正文。" * 40
        chunks = chunk_markdown(md, "doc-1")
        assert chunks[0].heading_path == []
        assert "前言段落" in chunks[0].text

    def test_empty_markdown_returns_no_chunks(self):
        assert chunk_markdown("", "doc-1") == []
        assert chunk_markdown("   \n\n  ", "doc-1") == []


class TestOversizedSubdivision:
    def test_oversized_block_subdivided_by_paragraph(self):
        chunks = chunk_markdown(FIXTURE_MD, "doc-1")
        oversized_children = [c for c in chunks if c.heading_path == ["第一章 知识库概述", "1.2 大规模语料处理"]]
        # 1055-token block packs by paragraph into 1016 + 38.
        assert len(oversized_children) == 2
        for chunk in oversized_children:
            assert chunk.token_count <= MAX_CHUNK_TOKENS
        # Paragraph packing keeps the heading text with the first child.
        assert oversized_children[0].text.startswith("## 1.2 大规模语料处理")
        # The short tail (code fence, 38 tokens) stays its own block because
        # merging it back would exceed the 1024 cap.
        assert oversized_children[1].token_count < 100

    def test_single_oversized_paragraph_hard_split(self):
        one_long_paragraph = "# 章\n\n" + "无换行长句。" * 400  # single paragraph, >1024 tokens
        chunks = chunk_markdown(one_long_paragraph, "doc-1")
        assert len(chunks) >= 2
        for chunk in chunks:
            assert chunk.token_count <= MAX_CHUNK_TOKENS


class TestSmallBlockMerge:
    def test_small_block_merged_into_previous_sibling(self):
        chunks = chunk_markdown(FIXTURE_MD, "doc-1")
        first = chunks[0]
        # The 32-token 1.1 block merges into the 449-token 第一章 block.
        assert "1.1 设计目标" in first.text
        assert "一期聚焦私有知识库" in first.text
        assert first.heading_path == ["第一章 知识库概述"]
        assert 440 <= first.token_count <= 520

    def test_consecutive_small_blocks_merge_together(self):
        md = "# 章\n\n" + "正文。" * 80 + "\n\n## 小节一\n\n很短。\n\n## 小节二\n\n也很短。"
        chunks = chunk_markdown(md, "doc-1")
        assert len(chunks) == 1
        assert "小节一" in chunks[0].text and "小节二" in chunks[0].text


class TestChunkSchema:
    def test_chunk_ids_and_index_are_sequential(self):
        chunks = chunk_markdown(FIXTURE_MD, "doc-1")
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
        assert [c.chunk_id for c in chunks] == [f"doc-1#{i:04d}" for i in range(len(chunks))]

    def test_every_chunk_carries_schema_fields(self):
        for chunk in chunk_markdown(FIXTURE_MD, "doc-1"):
            assert chunk.doc_id == "doc-1"
            assert chunk.text.strip()
            assert isinstance(chunk.heading_path, list)
            assert chunk.token_count > 0
            assert chunk.page is None  # full.md carries no page markers (Phase 1)
            assert chunk.entities == []  # backfilled later by the graph path

    def test_token_count_matches_actual_encoding(self):
        for chunk in chunk_markdown(FIXTURE_MD, "doc-1"):
            assert chunk.token_count == count_tokens(chunk.text)


# ── Task 4：表格感知切分（spec §6/§7） ─────────────────────────


def _gfm_table(rows: list[list[str]], header: list[str] | None = None) -> str:
    """构造 GFM 管道表（测试辅助）：header + 分隔 + rows。"""
    hdr = header or rows[0]
    data = rows[1:] if header is None else rows
    lines = ["| " + " | ".join(hdr) + " |", "| " + " | ".join(["---"] * len(hdr)) + " |"]
    for r in data:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


# Task 0 实测形态 A：整张表压在一行的 HTML（归一失败时作为残留到达 chunker）。
_MINERU_RESIDUAL_TABLE = (
    "<table><tr><td>Product</td><td>Region</td><td>Q1</td><td>Q2</td><td>Total</td></tr>"
    "<tr><td>Widget A</td><td>North</td><td>100</td><td>110</td><td>210</td></tr>"
    "<tr><td>Widget A</td><td>South</td><td>80</td><td>85</td><td>165</td></tr>"
    "<tr><td>Gadget B</td><td>Europe</td><td>60</td><td>75</td><td>135</td></tr></table>"
)


def test_gfm_table_detected_as_atomic_block():
    """GFM 管道表被识别为单一原子块，不被段落/标题逻辑中切（§7.1 修复）。"""
    from deerflow_knowledge.chunker import _split_by_headings

    md = "# 标题\n\n前言文字。\n\n" + _gfm_table([["a", "b"], ["1", "2"], ["3", "4"]]) + "\n\n后记。"
    blocks = _split_by_headings(md)
    table_blocks = [b for b in blocks if b.is_table]
    assert len(table_blocks) == 1
    assert "| a | b |" in table_blocks[0].text
    assert "| 1 | 2 |" in table_blocks[0].text
    assert "| 3 | 4 |" in table_blocks[0].text


def test_gfm_table_in_fence_not_detected():
    """代码 fence 内的 `|` 不被误判为表格（复用现有 in_fence 跟踪）。"""
    from deerflow_knowledge.chunker import _split_by_headings

    md = "前言\n\n```\n| a | b |\n| --- | --- |\n| 1 | 2 |\n```\n\n后记"
    blocks = _split_by_headings(md)
    assert not any(b.is_table for b in blocks)


def test_lone_pipe_line_without_delimiter_not_a_table():
    """散文里孤立的 `|` 行（次行非分隔行）不被误判为表格（防 shell 管道误伤）。"""
    from deerflow_knowledge.chunker import _split_by_headings

    md = "运行 cat sales.csv | grep north | wc -l 得到结果。\n\n普通段落。"
    blocks = _split_by_headings(md)
    assert not any(b.is_table for b in blocks)


def test_residual_html_table_is_atomic():
    """残留 HTML `<table>`（嵌套/畸形未归一）整段作原子块（§7.3）。"""
    from deerflow_knowledge.chunker import _split_by_headings

    html = "<table><tr><td><table><tr><td>内层</td></tr></table></td></tr></table>"
    blocks = _split_by_headings(f"前言\n\n{html}\n\n后记")
    html_blocks = [b for b in blocks if "<table" in b.text]
    assert len(html_blocks) == 1  # 整段原子，未被 `<` 中切
    assert "内层" in html_blocks[0].text


def test_residual_html_table_oversized_not_hard_split():
    """超 cap 的残留 HTML 表整块保留，绝不进 `_hard_split_tokens` 从 `<td>` 中切（§7.3）。"""
    big = "<table>" + "".join(f"<tr><td>row{i}</td><td>{'v' * 30}</td></tr>" for i in range(200)) + "</table>"
    assert count_tokens(big) > MAX_CHUNK_TOKENS  # 确实超 cap
    chunks = chunk_markdown(f"# 残留\n\n{big}", "doc:1")
    table_chunks = [c for c in chunks if "<table" in c.text]
    assert len(table_chunks) == 1  # 整块，未被硬切成多块
    assert "</table>" in table_chunks[0].text  # 闭合标签在同块（未从中间截断）


def test_residual_html_table_from_mineru_fixture_is_one_block():
    """Task 0 实测单行 HTML 表作残留时整块保留、完整闭合。"""
    from deerflow_knowledge.chunker import _split_by_headings

    blocks = _split_by_headings(f"Prose before.\n\n{_MINERU_RESIDUAL_TABLE}\n\nProse after.")
    html_blocks = [b for b in blocks if b.is_table and "<table" in b.text]
    assert len(html_blocks) == 1
    assert "Europe" in html_blocks[0].text
    assert html_blocks[0].text.rstrip().endswith("</table>")


def test_chunk_table_block_small_single():
    """小表（表头+全部行 ≤ cap）→ 单块，表头保留，无溯源行（§6 步3a）。"""
    from deerflow_knowledge.chunker import _chunk_table_block

    header = "| Region | Q1 |"
    delim = "| --- | --- |"
    rows = ["| North | 100 |", "| South | 200 |"]
    blocks = _chunk_table_block(["销售"], header, delim, rows, max_tokens=1024, card_mode="markdown")
    assert len(blocks) == 1
    assert header in blocks[0].text and delim in blocks[0].text
    assert "| North | 100 |" in blocks[0].text and "| South | 200 |" in blocks[0].text
    assert "表格：" not in blocks[0].text  # 单块无需溯源行


def test_chunk_table_block_large_repeats_header_per_group():
    """大表贪心行组：每组 ≤ cap，**每块重复表头+分隔**（§6 步3b，检索自解释）。"""
    from deerflow_knowledge.chunker import _chunk_table_block, count_tokens

    header = "| id | value |"
    delim = "| --- | --- |"
    rows = [f"| r{i} | {'x' * 40} |" for i in range(50)]
    blocks = _chunk_table_block(["大表"], header, delim, rows, max_tokens=200, card_mode="markdown")
    assert len(blocks) > 1
    for b in blocks:
        assert header in b.text and delim in b.text  # 每块都含表头
        assert count_tokens(b.text) <= 200 + 128  # 软上限（溯源行宽容边界）


def test_chunk_table_block_provenance_line_on_split():
    """大表拆分时每块顶加溯源行 `表格：{名}（第 {起}-{止} 行 / 共 {N} 行）`（§6）。"""
    from deerflow_knowledge.chunker import _chunk_table_block

    header = "| id | v |"
    delim = "| --- | --- |"
    rows = [f"| r{i} | {'y' * 40} |" for i in range(40)]
    blocks = _chunk_table_block(["季度销售"], header, delim, rows, max_tokens=200, card_mode="markdown")
    assert len(blocks) > 1
    for b in blocks:
        assert "表格：季度销售" in b.text
        assert "共 40 行" in b.text
    assert "第 1-" in blocks[0].text


def test_chunk_table_block_single_oversized_row_not_mid_split():
    """退化：单行 + 表头已超 cap → 该行整块保留，**绝不行中切**（§6 步3b 退化）。"""
    from deerflow_knowledge.chunker import _chunk_table_block

    header = "| id | payload |"
    delim = "| --- | --- |"
    huge = "| r1 | " + ("z" * 5000) + " |"
    rows = [huge, "| r2 | small |"]
    blocks = _chunk_table_block(["表"], header, delim, rows, max_tokens=100, card_mode="markdown")
    assert sum(1 for b in blocks if huge in b.text) == 1  # 巨行完整出现在恰好一块，未被切碎


def test_chunk_table_block_linearized_mode():
    """card_mode="linearized"：每行转 `列名: 值 | 列名: 值`，表头仍随块重复（§4 card_mode）。"""
    from deerflow_knowledge.chunker import _chunk_table_block

    header = "| Region | Q1 |"
    delim = "| --- | --- |"
    rows = ["| North | 100 |", "| South | 200 |"]
    blocks = _chunk_table_block(["销售"], header, delim, rows, max_tokens=1024, card_mode="linearized")
    text = blocks[0].text
    assert "Region: North" in text and "Q1: 100" in text
    assert "Region: South" in text and "Q2" not in text


def test_chunk_markdown_card_mode_param_passthrough():
    """`chunk_markdown(..., card_mode=)` 可选参透传到表格切分（默认 markdown 不破坏现签名）。"""
    md = "# 表\n\n" + _gfm_table([["Region", "Q1"], ["North", "100"]])
    chunks_md = chunk_markdown(md, "doc:1")
    assert any("Region" in c.text and "| North | 100 |" in c.text for c in chunks_md)
    chunks_lin = chunk_markdown(md, "doc:1", card_mode="linearized")
    assert any("Region: North" in c.text for c in chunks_lin)


def test_chunk_markdown_table_metadata_page():
    """表格 chunk 的 `page`：GFM 表无页信息时为 None（不伪造）（spec §6 数据契约）。"""
    md = "# 表\n\n" + _gfm_table([["a", "b"], ["1", "2"]])
    chunks = chunk_markdown(md, "doc:1")
    table_chunks = [c for c in chunks if "| 1 | 2 |" in c.text]
    assert table_chunks and all(c.page is None for c in table_chunks)


def test_table_chunk_inherits_heading_path():
    """内嵌表继承所在标题的 heading_path（§6）；Excel sheet 名同理进 heading_path。"""
    md = "# 年报\n\n## 季度销售\n\n" + _gfm_table([["Region", "Q1"], ["North", "100"]])
    chunks = chunk_markdown(md, "doc:1")
    table_chunks = [c for c in chunks if "| North | 100 |" in c.text]
    assert table_chunks
    assert table_chunks[0].heading_path == ["年报", "季度销售"]


def test_excel_sheet_name_in_heading_path():
    """Excel 每 sheet 的 `## {sheet}` 标题 → 表块 heading_path 含 sheet 名（Task 3 衔接）。"""
    md = "## Sheet1\n\n" + _gfm_table([["a", "b"], ["1", "2"]]) + "\n\n## Sheet2\n\n" + _gfm_table([["c"], ["3"]])
    chunks = chunk_markdown(md, "doc:1")
    sheet1 = [c for c in chunks if "| 1 | 2 |" in c.text]
    sheet2 = [c for c in chunks if "| 3 |" in c.text]
    assert sheet1 and sheet1[0].heading_path == ["Sheet1"]
    assert sheet2 and sheet2[0].heading_path == ["Sheet2"]


def test_table_chunks_have_continuous_index_and_ids():
    """含表文档的 chunk_index 连续、chunk_id={doc_id}#NNNN 合规（无跳号）。"""
    md = "# 报告\n\n前言。\n\n" + _gfm_table([["id", "v"], *[f"| r{i} | {'x' * 40} |" for i in range(40)]]) + "\n\n后记。"
    chunks = chunk_markdown(md, "doc:1", max_tokens=200)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert [c.chunk_id for c in chunks] == [f"doc:1#{i:04d}" for i in range(len(chunks))]


def test_non_table_prose_regression_unchanged():
    """非表格散文回归：无表文档不误判为表、heading 仍在 text（守实际语义）。"""
    from deerflow_knowledge.chunker import _split_by_headings

    md = "# 章\n\n" + "正文。" * 30 + "\n\n## 小节\n\n" + "更多正文。" * 20
    blocks = _split_by_headings(md)
    assert not any(b.is_table for b in blocks)  # 散文不误判为表
    chunks = chunk_markdown(md, "doc:1")
    assert chunks[0].heading_path == ["章"]
    assert chunks[0].text.startswith("# 章")  # heading 仍在 text（保留实际语义）
    assert any("## 小节" in c.text for c in chunks)


def test_sheet_heading_not_isolated_into_own_chunk():
    """Excel sheet 标题（`## {sheet}`）后紧跟表 → 不孤立成空卡，整 sheet 一卡（缺陷修复）。

    复现生产：测试.xlsx 单 sheet 产出 2 卡（3-token 孤立 '## Sheet1' + 表卡）；
    标题信息已在 heading_path，无需再占一卡。
    """
    md = "## Sheet1\n\n" + _gfm_table([["a", "b"], ["1", "2"]])
    chunks = chunk_markdown(md, "doc:1")
    assert len(chunks) == 1  # 修复前为 2（孤立标题卡 + 表卡）
    assert chunks[0].heading_path == ["Sheet1"]
    assert "| 1 | 2 |" in chunks[0].text
    assert not chunks[0].text.lstrip().startswith("## Sheet1")  # 表卡正文非孤立标题


def test_nested_headings_not_isolated_before_table():
    """多层标题（H1+H2）后紧跟表 → 标题只进 heading_path，不产孤立卡。"""
    md = "# 年报\n\n## 季度销售\n\n" + _gfm_table([["Region", "Q1"], ["North", "100"]])
    chunks = chunk_markdown(md, "doc:1")
    assert len(chunks) == 1
    assert chunks[0].heading_path == ["年报", "季度销售"]
    assert "| North | 100 |" in chunks[0].text


def test_heading_followed_by_prose_keeps_heading_in_text():
    """标题后跟正文（非表）→ heading-in-text 语义不变（散文回归守卫）。"""
    md = "# 章\n\n## 小节\n\n正文内容。"
    chunks = chunk_markdown(md, "doc:1")
    assert chunks[0].text.startswith("# 章")
    assert "## 小节" in chunks[0].text and "正文内容。" in chunks[0].text
