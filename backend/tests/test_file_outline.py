"""Regression tests for fenced code in model-visible document outlines."""

from pathlib import Path

import pytest

from deerflow.utils.file_outline import MAX_OUTLINE_ENTRIES, extract_outline


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
