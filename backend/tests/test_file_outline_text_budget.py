"""Uploaded document summaries must stay compact even for very long lines."""

from pathlib import Path

import pytest

from deerflow.utils.file_outline import MAX_OUTLINE_ENTRIES, extract_outline, extract_outline_for_file


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
