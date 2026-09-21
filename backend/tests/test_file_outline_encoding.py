"""UTF-8 signatures must not change model-visible document summaries."""

from pathlib import Path

import pytest

from deerflow.utils.file_outline import extract_outline, extract_outline_for_file


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


def test_outline_comes_from_the_companion_named_after_the_document(tmp_path):
    """a.pdf reads a.pdf.md, not the companion of a.docx sharing its stem."""
    (tmp_path / "a.docx").write_bytes(b"DOCX")
    (tmp_path / "a.docx.md").write_text("# From the DOCX\n", encoding="utf-8")
    (tmp_path / "a.pdf").write_bytes(b"PDF")
    (tmp_path / "a.pdf.md").write_text("# From the PDF\n", encoding="utf-8")

    docx_outline, _ = extract_outline_for_file(tmp_path / "a.docx")
    pdf_outline, _ = extract_outline_for_file(tmp_path / "a.pdf")

    assert [entry["title"] for entry in docx_outline] == ["From the DOCX"]
    assert [entry["title"] for entry in pdf_outline] == ["From the PDF"]


def test_an_uploaded_markdown_file_is_its_own_outline_source(tmp_path):
    notes = tmp_path / "notes.md"
    notes.write_text("# Notes heading\n", encoding="utf-8")

    outline, _ = extract_outline_for_file(notes)

    assert [entry["title"] for entry in outline] == ["Notes heading"]
