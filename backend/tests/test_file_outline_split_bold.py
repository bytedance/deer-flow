"""Split-bold outlines must distinguish section titles from numeric table rows."""

from pathlib import Path

import pytest

from deerflow.utils.file_outline import MAX_OUTLINE_ENTRIES, extract_outline, extract_outline_for_file


@pytest.mark.parametrize("column", ["(2023)", "-12.5", "–12", "+12", "/2023", "(12%)", "---", "%", " 2023", "2023"])
def test_numeric_or_punctuation_columns_are_not_headings(tmp_path: Path, column: str) -> None:
    document = tmp_path / "annual.md"
    document.write_text(f"# Financial Summary\n**2024** **{column}** **2022**\n## Results\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": "Financial Summary", "line": 1}, {"title": "Results", "line": 3}]


@pytest.mark.parametrize("title", ["(Introduction)", "- Results", "2023 Results", "概述", "Évaluation", "(概述)"])
def test_punctuated_or_non_ascii_section_titles_remain_supported(tmp_path: Path, title: str) -> None:
    document = tmp_path / "paper.md"
    document.write_text(f"**3.2** **{title}**\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": f"3.2 {title}", "line": 1}]


def test_numeric_table_rows_do_not_exhaust_outline_budget(tmp_path: Path) -> None:
    document = tmp_path / "annual.md"
    rows = "**2024** **(2023)**\n" * (MAX_OUTLINE_ENTRIES + 1)
    document.write_text(rows + "**1** **Actual findings**\n", encoding="utf-8")

    assert extract_outline(document) == [{"title": "1 Actual findings", "line": MAX_OUTLINE_ENTRIES + 2}]


def test_numeric_only_document_uses_fallback_preview(tmp_path: Path) -> None:
    document = tmp_path / "annual.md"
    document.write_text("**2024** **(2023)**\nRevenue 100 90\n", encoding="utf-8")

    assert extract_outline_for_file(document) == ([], ["**2024** **(2023)**", "Revenue 100 90"])
