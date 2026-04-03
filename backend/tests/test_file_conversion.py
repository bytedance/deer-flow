"""Tests for extract_outline() in file_conversion utilities (PR2: document outline injection)."""

from __future__ import annotations

from deerflow.utils.file_conversion import (
    MAX_OUTLINE_ENTRIES,
    extract_outline,
)

# ---------------------------------------------------------------------------
# extract_outline
# ---------------------------------------------------------------------------


class TestExtractOutline:
    """Tests for extract_outline()."""

    def test_empty_file_returns_empty(self, tmp_path):
        """Empty markdown file yields no outline entries."""
        md = tmp_path / "empty.md"
        md.write_text("", encoding="utf-8")
        assert extract_outline(md) == []

    def test_missing_file_returns_empty(self, tmp_path):
        """Non-existent path returns [] without raising."""
        assert extract_outline(tmp_path / "nonexistent.md") == []

    def test_standard_markdown_headings(self, tmp_path):
        """# / ## / ### headings are all recognised."""
        md = tmp_path / "doc.md"
        md.write_text(
            "# Chapter One\n\nSome text.\n\n## Section 1.1\n\nMore text.\n\n### Sub 1.1.1\n",
            encoding="utf-8",
        )
        outline = extract_outline(md)
        assert len(outline) == 3
        assert outline[0] == {"title": "Chapter One", "line": 1}
        assert outline[1] == {"title": "Section 1.1", "line": 5}
        assert outline[2] == {"title": "Sub 1.1.1", "line": 9}

    def test_bold_sec_item_heading(self, tmp_path):
        """**ITEM N. TITLE** lines in SEC filings are recognised."""
        md = tmp_path / "10k.md"
        md.write_text(
            "Cover page text.\n\n**ITEM 1. BUSINESS**\n\nBody.\n\n**ITEM 1A. RISK FACTORS**\n",
            encoding="utf-8",
        )
        outline = extract_outline(md)
        assert len(outline) == 2
        assert outline[0] == {"title": "ITEM 1. BUSINESS", "line": 3}
        assert outline[1] == {"title": "ITEM 1A. RISK FACTORS", "line": 7}

    def test_bold_part_heading(self, tmp_path):
        """**PART I** / **PART II** headings are recognised."""
        md = tmp_path / "10k.md"
        md.write_text("**PART I**\n\n**PART II**\n\n**PART III**\n", encoding="utf-8")
        outline = extract_outline(md)
        assert len(outline) == 3
        titles = [e["title"] for e in outline]
        assert "PART I" in titles
        assert "PART II" in titles
        assert "PART III" in titles

    def test_sec_cover_page_boilerplate_excluded(self, tmp_path):
        """Address lines and short cover boilerplate must NOT appear in outline."""
        md = tmp_path / "8k.md"
        md.write_text(
            "## **UNITED STATES SECURITIES AND EXCHANGE COMMISSION**\n\n**WASHINGTON, DC 20549**\n\n**CURRENT REPORT**\n\n**SIGNATURES**\n\n**TESLA, INC.**\n\n**ITEM 2.02. RESULTS OF OPERATIONS**\n",
            encoding="utf-8",
        )
        outline = extract_outline(md)
        titles = [e["title"] for e in outline]
        # Cover-page boilerplate should be excluded
        assert "WASHINGTON, DC 20549" not in titles
        assert "CURRENT REPORT" not in titles
        assert "SIGNATURES" not in titles
        assert "TESLA, INC." not in titles
        # Real SEC heading must be included
        assert "ITEM 2.02. RESULTS OF OPERATIONS" in titles

    def test_chinese_headings_via_standard_markdown(self, tmp_path):
        """Chinese annual report headings emitted as # by pymupdf4llm are captured."""
        md = tmp_path / "annual.md"
        md.write_text(
            "# 第一节 公司简介\n\n内容。\n\n## 第三节 管理层讨论与分析\n\n分析内容。\n",
            encoding="utf-8",
        )
        outline = extract_outline(md)
        assert len(outline) == 2
        assert outline[0]["title"] == "第一节 公司简介"
        assert outline[1]["title"] == "第三节 管理层讨论与分析"

    def test_outline_capped_at_max_entries(self, tmp_path):
        """When truncated, result has MAX_OUTLINE_ENTRIES real entries + 1 sentinel."""
        lines = [f"# Heading {i}" for i in range(MAX_OUTLINE_ENTRIES + 10)]
        md = tmp_path / "long.md"
        md.write_text("\n".join(lines), encoding="utf-8")
        outline = extract_outline(md)
        # Last entry is the truncation sentinel
        assert outline[-1] == {"truncated": True}
        # Visible entries are exactly MAX_OUTLINE_ENTRIES
        visible = [e for e in outline if not e.get("truncated")]
        assert len(visible) == MAX_OUTLINE_ENTRIES

    def test_no_truncation_sentinel_when_under_limit(self, tmp_path):
        """Short documents produce no sentinel entry."""
        lines = [f"# Heading {i}" for i in range(5)]
        md = tmp_path / "short.md"
        md.write_text("\n".join(lines), encoding="utf-8")
        outline = extract_outline(md)
        assert len(outline) == 5
        assert not any(e.get("truncated") for e in outline)

    def test_blank_lines_and_whitespace_ignored(self, tmp_path):
        """Blank lines between headings do not produce empty entries."""
        md = tmp_path / "spaced.md"
        md.write_text("\n\n# Title One\n\n\n\n# Title Two\n\n", encoding="utf-8")
        outline = extract_outline(md)
        assert len(outline) == 2
        assert all(e["title"] for e in outline)

    def test_inline_bold_not_confused_with_heading(self, tmp_path):
        """Mid-sentence bold text must not be mistaken for a heading."""
        md = tmp_path / "prose.md"
        md.write_text(
            "This sentence has **bold words** inside it.\n\nAnother with **MULTIPLE CAPS** inline.\n",
            encoding="utf-8",
        )
        outline = extract_outline(md)
        assert outline == []
