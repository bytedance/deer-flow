"""Mixed bold spans must not be mistaken for a whole-title wrapper."""

from pathlib import Path

import pytest

from deerflow.uploads.companions import register_companion
from deerflow.utils.file_outline import extract_outline_for_file


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
