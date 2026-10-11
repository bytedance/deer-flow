"""Indented bold examples must not displace document headings in outlines."""

import pytest

from deerflow.uploads.companions import register_companion
from deerflow.utils.file_outline import MAX_OUTLINE_ENTRIES, extract_outline, extract_outline_for_file


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
