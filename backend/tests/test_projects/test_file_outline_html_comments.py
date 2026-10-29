"""Regression tests for HTML comment blocks in uploaded-document outlines."""

from pathlib import Path

import pytest

from deerflow.uploads.companions import register_companion
from deerflow.utils.file_outline import MAX_OUTLINE_ENTRIES, extract_outline, extract_outline_for_file


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
