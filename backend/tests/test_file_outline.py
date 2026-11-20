"""Behavioral and boundary suite for model-visible document outlines (`deerflow.utils.file_outline`)."""

import subprocess
import sys
from pathlib import Path

import pytest

from deerflow.uploads.companions import register_companion
from deerflow.utils.file_outline import MAX_OUTLINE_ENTRIES, extract_outline, extract_outline_for_file

# --- test_file_outline ---


@pytest.mark.parametrize("fence", ["```", "~~~"])
@pytest.mark.parametrize("indent", ["", " ", "  ", "   "])
def test_fenced_code_is_excluded_from_all_heading_styles(tmp_path: Path, fence: str, indent: str) -> None:
    document = tmp_path / "guide.md"
    document.write_text(
        f"# Setup\n{indent}{fence}python\n# Code comment\n**ITEM 1. NOT A SECTION**\n**2** **Not a section**\n{indent}{fence}\n## Results\n",
        encoding="utf-8",
    )

    assert extract_outline(document) == [{"title": "Setup", "line": 1}, {"title": "Results", "line": 7}]


@pytest.mark.parametrize(
    ("opening", "non_closing"),
    [
        ("````", "```"),
        ("~~~~", "~~~"),
        ("```", "~~~"),
        ("~~~", "```"),
        ("```", "```python"),
        ("~~~", "~~~text"),
        ("```", "    ```"),
    ],
)
def test_only_a_matching_closing_fence_ends_code(tmp_path: Path, opening: str, non_closing: str) -> None:
    document = tmp_path / "guide.md"
    document.write_text(f"{opening}\n{non_closing}\n# Still code\n{opening}\n# Real section\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": "Real section", "line": 5}]


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_longer_closing_fence_with_trailing_whitespace(tmp_path: Path, fence: str) -> None:
    document = tmp_path / "guide.md"
    document.write_text(f"{fence}\n# Code\n{fence * 2} \t\n# Section\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": "Section", "line": 4}]


def test_unclosed_code_fence_excludes_remaining_lines(tmp_path: Path) -> None:
    document = tmp_path / "guide.md"
    document.write_text("# Overview\n```python\n# Code\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": "Overview", "line": 1}]


@pytest.mark.parametrize("non_opening", ["``", "~~", "```bad`info", "    ```"])
def test_invalid_opening_fence_does_not_hide_subsequent_headings(tmp_path: Path, non_opening: str) -> None:
    document = tmp_path / "guide.md"
    document.write_text(f"{non_opening}\n# Section\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": "Section", "line": 2}]


def test_tilde_fence_allows_backticks_in_info_string(tmp_path: Path) -> None:
    document = tmp_path / "guide.md"
    document.write_text("~~~example `code`\n# Code\n~~~\n# Section\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": "Section", "line": 4}]


def test_code_comments_do_not_exhaust_outline_budget(tmp_path: Path) -> None:
    document = tmp_path / "guide.md"
    comments = "".join(f"# Code comment {index}\n" for index in range(MAX_OUTLINE_ENTRIES + 1))
    document.write_text("```python\n" + comments + "```\n# Actual findings\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": "Actual findings", "line": MAX_OUTLINE_ENTRIES + 4}]


def test_real_headings_after_code_still_obey_outline_budget(tmp_path: Path) -> None:
    document = tmp_path / "guide.md"
    headings = "".join(f"# Section {index}\n" for index in range(MAX_OUTLINE_ENTRIES + 1))
    document.write_text("```python\n# Code\n```\n" + headings, encoding="utf-8")

    expected = [{"title": f"Section {index}", "line": index + 4} for index in range(MAX_OUTLINE_ENTRIES)]
    assert extract_outline(document) == expected + [{"truncated": True}]


def test_pdf_bold_headings_outside_code_remain_supported(tmp_path: Path) -> None:
    document = tmp_path / "guide.md"
    document.write_text("```\n**ITEM 1. CODE**\n```\n**PART I**\n**2** **Results**\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": "PART I", "line": 4}, {"title": "2 Results", "line": 5}]


# --- test_file_outline_atx ---


@pytest.mark.parametrize("line", ["#tag", "##tag", "####### Too many", "    # Code comment", "\t# Code comment", "#\u00a0Not a separator", "\\# Escaped"])
def test_non_headings_do_not_hide_real_sections(tmp_path, line):
    path = tmp_path / "guide.md"
    path.write_text((line + "\n") * (MAX_OUTLINE_ENTRIES + 1) + "# Real section\n", encoding="utf-8")
    assert extract_outline(path) == [{"title": "Real section", "line": MAX_OUTLINE_ENTRIES + 2}]


@pytest.mark.parametrize(
    ("line", "title"),
    [
        ("# Title", "Title"),
        ("   ###### Title", "Title"),
        ("##\tTitle", "Title"),
        ("## Title ###  ", "Title"),
        ("## Title\t###\t", "Title"),
        ("# **Overview** ###", "Overview"),
        ("# Title###", "Title###"),
        ("# Title ### suffix", "Title ### suffix"),
        ("# Title \\###", "Title \\###"),
        ("# 标题 ###", "标题"),
    ],
)
def test_atx_titles_and_physical_lines(tmp_path, line, title):
    path = tmp_path / "guide.md"
    path.write_text("Intro\n\n" + line + "\n", encoding="utf-8")
    assert extract_outline(path) == [{"title": title, "line": 3}]


@pytest.mark.parametrize("line", ["#", "###   ", "## ###", "#\t###\t"])
def test_empty_atx_headings_do_not_create_entries(tmp_path, line):
    path = tmp_path / "guide.md"
    path.write_text(line + "\n", encoding="utf-8")
    assert extract_outline(path) == []


def test_long_whitespace_without_closing_hashes_finishes_promptly(tmp_path):
    """Exercise heading recognition under a generous process deadline."""
    path = tmp_path / "long-heading.md"
    path.write_text("# Title" + " " * 262144 + "suffix\n", encoding="utf-8")
    # Recognition must survive long whitespace; summary budgets may clip titles.
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; from deerflow.utils.file_outline import extract_outline; result = extract_outline(Path(sys.argv[1])); "
            "assert len(result) == 1 and result[0]['line'] == 1 and result[0]['title'].startswith('Title')",
            str(path),
        ],
        check=True,
        timeout=10,
        capture_output=True,
        text=True,
    )


# --- test_file_outline_bold_wrappers ---


@pytest.mark.parametrize(
    ("heading", "title"),
    [
        ("**Revenue** and **Profit**", "**Revenue** and **Profit**"),
        ("**收入**与**利润**", "**收入**与**利润**"),
        ("**Before** / **After**", "**Before** / **After**"),
        ("**Overview**", "Overview"),
        ("**UNITED STATES** **SECURITIES**", "UNITED STATES SECURITIES"),
        ("**A**\t**B**", "A B"),
        ("Revenue and **Profit**", "Revenue and **Profit**"),
        ("**Revenue** and Profit", "**Revenue** and Profit"),
        ("Plain title", "Plain title"),
    ],
)
@pytest.mark.parametrize("converted", [False, True])
def test_upload_outline_only_unwraps_a_whole_bold_title(tmp_path: Path, heading: str, title: str, converted: bool) -> None:
    markdown = tmp_path / "report.md"
    original = f"Introduction\r\n\r\n## {heading} ###\r\n# Next section\r\n".encode()
    markdown.write_bytes(original)
    source = markdown
    if converted:
        source = tmp_path / "report.pdf"
        source.write_bytes(b"synthetic source; conversion not invoked")
        register_companion(source, markdown)

    assert extract_outline_for_file(source) == ([{"title": title, "line": 3}, {"title": "Next section", "line": 4}], [])
    assert markdown.read_bytes() == original


# --- test_file_outline_encoding ---


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
@pytest.mark.parametrize(
    ("heading", "title"),
    [("# 概述", "概述"), ("**PART I**", "PART I"), ("**1** **Introduction**", "1 Introduction")],
)
def test_first_heading_is_preserved_with_or_without_bom(tmp_path: Path, encoding: str, heading: str, title: str) -> None:
    document = tmp_path / "report.md"
    document.write_text(heading + "\n\n## Next section\n", encoding=encoding)

    assert extract_outline(document) == [{"title": title, "line": 1}, {"title": "Next section", "line": 3}]


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_first_code_fence_is_recognized_with_or_without_bom(tmp_path: Path, encoding: str, fence: str) -> None:
    document = tmp_path / "guide.md"
    document.write_text(f"{fence}python\n# Code comment\n{fence}\n# Actual section\n", encoding=encoding)

    assert extract_outline_for_file(document) == ([{"title": "Actual section", "line": 4}], [])


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_preview_skips_bom_only_line_and_preserves_embedded_character(tmp_path: Path, encoding: str) -> None:
    document = tmp_path / "notes.md"
    document.write_text("\nFirst paragraph\nSecond\ufeffparagraph\n", encoding=encoding)
    original = document.read_bytes()

    assert extract_outline_for_file(document) == ([], ["First paragraph", "Second\ufeffparagraph"])
    assert document.read_bytes() == original


# --- test_file_outline_html_comments ---


@pytest.mark.parametrize("indent", ["", " ", "  ", "   "])
def test_html_comments_exclude_all_heading_styles(tmp_path: Path, indent: str) -> None:
    document = tmp_path / "guide.md"
    document.write_text(
        f"# Overview\n{indent}<!--\n## Hidden draft\n**ITEM 1. HIDDEN**\n**2** **Hidden results**\n-->\n## Results\n",
        encoding="utf-8",
    )

    assert extract_outline(document) == [{"title": "Overview", "line": 1}, {"title": "Results", "line": 7}]


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_fence_inside_comment_does_not_hide_later_headings(tmp_path: Path, fence: str) -> None:
    document = tmp_path / "guide.md"
    document.write_text(f"<!--\n{fence}python\n# Hidden example\n-->\n# Results\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": "Results", "line": 5}]


@pytest.mark.parametrize("comment", ["<!-- note -->", "<!-- --> # Not a heading", "<!-- first --><!-- second", "<!-- note\n\n--> # Not a heading"])
def test_comment_ends_on_first_closing_marker_line(tmp_path: Path, comment: str) -> None:
    document = tmp_path / "guide.md"
    document.write_text(comment + "\n# Results\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": "Results", "line": comment.count("\n") + 2}]


def test_unclosed_comment_excludes_remaining_headings(tmp_path: Path) -> None:
    document = tmp_path / "guide.md"
    document.write_text("# Overview\n<!--\n\n## Hidden draft\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": "Overview", "line": 1}]


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_comment_markers_inside_code_do_not_open_comment_block(tmp_path: Path, fence: str) -> None:
    document = tmp_path / "guide.md"
    document.write_text(f"{fence}html\n<!--\n# Code\n{fence}\n# Results\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": "Results", "line": 5}]


@pytest.mark.parametrize("non_opening", ["    <!--", "\t<!--", "text <!--", "&lt;!--"])
def test_non_block_comment_marker_does_not_hide_headings(tmp_path: Path, non_opening: str) -> None:
    document = tmp_path / "guide.md"
    document.write_text(non_opening + "\n# Results\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": "Results", "line": 2}]


def test_commented_headings_do_not_exhaust_outline_limit(tmp_path: Path) -> None:
    document = tmp_path / "guide.md"
    hidden = "".join(f"# Hidden {index}\n" for index in range(MAX_OUTLINE_ENTRIES + 1))
    document.write_text("<!--\n" + hidden + "-->\n# Results\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": "Results", "line": MAX_OUTLINE_ENTRIES + 4}]


def test_real_headings_after_comment_still_obey_outline_limit(tmp_path: Path) -> None:
    document = tmp_path / "guide.md"
    headings = "".join(f"# Section {index}\n" for index in range(MAX_OUTLINE_ENTRIES + 1))
    document.write_text("<!--\n# Hidden\n-->\n" + headings, encoding="utf-8")

    expected = [{"title": f"Section {index}", "line": index + 4} for index in range(MAX_OUTLINE_ENTRIES)]
    assert extract_outline(document) == expected + [{"truncated": True}]


@pytest.mark.parametrize("converted", [False, True])
def test_upload_summary_ignores_comments_without_changing_file_bytes(tmp_path: Path, converted: bool) -> None:
    uploads = tmp_path / "thread/user-data/uploads"
    uploads.mkdir(parents=True)
    markdown = uploads / "report.md"
    content = b"\xef\xbb\xbf<!--\r\n# Hidden\r\n```python\r\n-->\r\n# Results\r\n"
    markdown.write_bytes(content)
    source = markdown
    if converted:
        source = uploads / "report.pdf"
        source.write_bytes(b"synthetic source; conversion not invoked")
        register_companion(source, markdown)

    assert extract_outline_for_file(source) == ([{"title": "Results", "line": 5}], [])
    assert markdown.read_bytes() == content


# --- test_file_outline_indented_bold ---


@pytest.mark.parametrize("indent", ["    ", "\t", " \t", "  \t", "   \t"])
@pytest.mark.parametrize("text", ["**PART II**", "**1** **Code example**"])
def test_indented_bold_code_preserves_real_heading_lines(tmp_path, indent, text):
    path = tmp_path / "guide.md"
    path.write_text(f"# Overview\n\n{indent}{text}\n\n## Findings\n", encoding="utf-8")

    assert extract_outline(path) == [{"title": "Overview", "line": 1}, {"title": "Findings", "line": 5}]


@pytest.mark.parametrize("indent", ["    ", "\t"])
@pytest.mark.parametrize("text", ["**PART II**", "**1** **Code example**"])
def test_indented_bold_examples_cannot_exhaust_outline_slots(tmp_path, indent, text):
    path = tmp_path / "guide.md"
    path.write_text((indent + text + "\n") * (MAX_OUTLINE_ENTRIES + 1) + "\n# Actual findings\n", encoding="utf-8")

    assert extract_outline(path) == [{"title": "Actual findings", "line": MAX_OUTLINE_ENTRIES + 3}]


@pytest.mark.parametrize("indent", ["", " ", "  ", "   "])
def test_bold_headings_with_up_to_three_spaces_are_preserved(tmp_path, indent):
    path = tmp_path / "report.md"
    path.write_text(f"{indent}**PART II**\n{indent}**1** **概述**\n", encoding="utf-8")

    assert extract_outline(path) == [{"title": "PART II", "line": 1}, {"title": "1 概述", "line": 2}]


def test_owned_conversion_uses_the_same_indentation_rule(tmp_path):
    uploads = tmp_path / "thread/user-data/uploads"
    uploads.mkdir(parents=True)
    original = uploads / "report.pdf"
    markdown = uploads / "report.md"
    original.write_bytes(b"synthetic source fixture; converter not invoked")
    markdown.write_text("    **PART II**\n\n# Actual section\n", encoding="utf-8")
    register_companion(original, markdown)

    assert extract_outline_for_file(original) == ([{"title": "Actual section", "line": 3}], [])


def test_existing_fenced_code_and_heading_styles_are_preserved(tmp_path):
    path = tmp_path / "guide.md"
    path.write_text("~~~\n**PART II**\n~~~\n# Section\n**PART III**\n**2** **Details**\n", encoding="utf-8")

    assert extract_outline(path) == [{"title": "Section", "line": 4}, {"title": "PART III", "line": 5}, {"title": "2 Details", "line": 6}]


# --- test_file_outline_split_bold ---


@pytest.mark.parametrize("column", ["(2023)", "-12.5", "–12", "+12", "/2023", "(12%)", "---", "%", " 2023", "2023", "$1,234", "€100", "£1,234.50", "¥100", "(€100)", " $100", "$"])
def test_numeric_or_punctuation_columns_are_not_headings(tmp_path: Path, column: str) -> None:
    document = tmp_path / "annual.md"
    document.write_text(f"# Financial Summary\n**2024** **{column}**\n## Results\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": "Financial Summary", "line": 1}, {"title": "Results", "line": 3}]


@pytest.mark.parametrize("title", ["(Introduction)", "- Results", "2023 Results", "概述", "Évaluation", "(概述)", "$ Revenue", "€ Marché", "£成本", "¥価格"])
def test_punctuated_or_non_ascii_section_titles_remain_supported(tmp_path: Path, title: str) -> None:
    document = tmp_path / "paper.md"
    document.write_text(f"**3.2** **{title}**\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": f"3.2 {title}", "line": 1}]


@pytest.mark.parametrize(
    "row",
    [
        "**2024** **Revenue** **2023**",
        "**2024** **Revenue** **(2023)**",
        "**2024** **Revenue** **-12.5**",
        "**2024** **Revenue** **$1,234**",
        "**2024** **Revenue** **Growth** **€100**",
        "**2024** **Revenue** **(2023)** **-12.5**",
    ],
)
def test_later_numeric_columns_are_not_headings(tmp_path: Path, row: str) -> None:
    document = tmp_path / "annual.md"
    document.write_text(f"# Financial Summary\n{row}\n## Results\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": "Financial Summary", "line": 1}, {"title": "Results", "line": 3}]


@pytest.mark.parametrize("blocks", ["**Results** **and discussion**", "**Results** **and** **discussion**", "**Revenue** **(2023 Results)**", "**Revenue** **$ Outlook** **概述**"])
def test_text_bearing_later_blocks_remain_headings(tmp_path: Path, blocks: str) -> None:
    document = tmp_path / "paper.md"
    document.write_text(f"**3.2** {blocks}\n", encoding="utf-8")

    title = blocks.replace("**", "")
    assert extract_outline(document) == [{"title": f"3.2 {title}", "line": 1}]


def test_split_bold_headings_keep_four_block_limit(tmp_path: Path) -> None:
    document = tmp_path / "paper.md"
    document.write_text("**3.2** **Results** **and** **discussion** **continued**\n", encoding="utf-8")

    assert extract_outline(document) == []


@pytest.mark.parametrize("row", ["**2024** **(2023)**", "**2024** **$1,234**", "**2024** **Revenue** **(2023)** **-12.5**"])
def test_numeric_table_rows_do_not_exhaust_outline_budget(tmp_path: Path, row: str) -> None:
    document = tmp_path / "annual.md"
    rows = f"{row}\n" * (MAX_OUTLINE_ENTRIES + 1)
    document.write_text(rows + "**1** **Actual findings**\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": "1 Actual findings", "line": MAX_OUTLINE_ENTRIES + 2}]


@pytest.mark.parametrize("row", ["**2024** **(2023)**", "**2024** **€100**", "**2024** **Revenue** **Growth** **¥100**"])
def test_numeric_only_document_uses_fallback_preview(tmp_path: Path, row: str) -> None:
    document = tmp_path / "annual.md"
    document.write_text(f"{row}\nRevenue 100 90\n", encoding="utf-8")

    assert extract_outline_for_file(document) == ([], [row, "Revenue 100 90"])


# --- test_file_outline_text_budget ---


@pytest.mark.parametrize("heading", ["# {text}", "**SECTION {text}**", "**1** **{text}**"])
def test_long_heading_titles_are_bounded_with_original_line_numbers(tmp_path: Path, heading: str) -> None:
    document = tmp_path / "report.md"
    original = "Introduction\n\n" + heading.format(text="A" * 200_000) + "\n# Next section\n"
    document.write_text(original, encoding="utf-8")
    outline = extract_outline(document)
    assert len(outline[0]["title"]) <= 200
    assert outline[0]["title"].endswith("… (truncated)")
    assert outline[0]["line"] == 3
    assert outline[1] == {"title": "Next section", "line": 4}
    assert document.read_text(encoding="utf-8") == original


def test_single_long_paragraph_has_a_bounded_preview(tmp_path: Path) -> None:
    document = tmp_path / "report.md"
    original = "word " * 40_000
    document.write_text(original, encoding="utf-8")
    outline, preview = extract_outline_for_file(document)
    assert outline == []
    assert len(preview) == 1
    assert len(preview[0]) <= 2000
    assert preview[0].endswith("… (truncated)")
    assert document.read_text(encoding="utf-8") == original


def test_preview_budget_is_shared_across_nonempty_lines(tmp_path: Path) -> None:
    document = tmp_path / "report.md"
    document.write_text("\n".join(["A" * 800, "", "B" * 800, "C" * 800, "D" * 800]), encoding="utf-8")
    _, preview = extract_outline_for_file(document)
    assert preview[:2] == ["A" * 800, "B" * 800]
    assert sum(map(len, preview)) <= 2000
    assert preview[-1].endswith("… (truncated)")


@pytest.mark.parametrize("length", [199, 200])
def test_heading_at_or_below_budget_is_unchanged(tmp_path: Path, length: int) -> None:
    document = tmp_path / "report.md"
    document.write_text("# " + "字" * length, encoding="utf-8")
    assert extract_outline(document) == [{"title": "字" * length, "line": 1}]


@pytest.mark.parametrize("length", [1999, 2000])
def test_preview_at_or_below_budget_is_unchanged(tmp_path: Path, length: int) -> None:
    document = tmp_path / "report.md"
    document.write_text("字" * length, encoding="utf-8")
    assert extract_outline_for_file(document) == ([], ["字" * length])


def test_preview_still_limits_nonempty_line_count(tmp_path: Path) -> None:
    document = tmp_path / "report.md"
    document.write_text("\n\n".join(f"Line {i}" for i in range(7)), encoding="utf-8")
    assert extract_outline_for_file(document) == ([], [f"Line {i}" for i in range(5)])


def test_long_headings_preserve_entry_count_and_truncation_sentinel(tmp_path: Path) -> None:
    document = tmp_path / "report.md"
    document.write_text("\n".join("# " + "A" * 300 for _ in range(MAX_OUTLINE_ENTRIES + 1)), encoding="utf-8")
    outline = extract_outline(document)
    assert len(outline) == MAX_OUTLINE_ENTRIES + 1
    assert outline[-1] == {"truncated": True}
    assert all(len(entry["title"]) <= 200 for entry in outline[:-1])


def test_tiny_remaining_preview_budget_still_marks_omission(tmp_path: Path) -> None:
    document = tmp_path / "report.md"
    document.write_text("字" * 1999 + "\n" + "文" * 100, encoding="utf-8")
    _, preview = extract_outline_for_file(document)
    assert sum(map(len, preview)) <= 2000
    assert preview[-1] == "…"


def test_long_unicode_heading_preserves_readable_prefix(tmp_path: Path) -> None:
    document = tmp_path / "report.md"
    document.write_text("# " + "研究" * 200, encoding="utf-8")
    title = extract_outline(document)[0]["title"]
    assert title.startswith("研究研究")
    assert title.endswith("… (truncated)")
    assert len(title) <= 200


def test_exact_fit_preview_stops_before_following_content(tmp_path: Path) -> None:
    document = tmp_path / "report.md"
    original = "Z" * 2000 + "\nACTUAL CONTENT\n"
    document.write_text(original, encoding="utf-8")
    # Markers describe truncation within an included line. Reaching the total
    # budget stops the preview, just like reaching its five-line limit.
    assert extract_outline_for_file(document) == ([], ["Z" * 2000])
    assert document.read_text(encoding="utf-8") == original
