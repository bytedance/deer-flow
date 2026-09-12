"""Only actual ATX headings should occupy uploaded-document outline slots."""

import subprocess
import sys

import pytest

from deerflow.utils.file_outline import MAX_OUTLINE_ENTRIES, extract_outline


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
            "from pathlib import Path; import sys; from deerflow.utils.file_outline import extract_outline; result = extract_outline(Path(sys.argv[1])); assert len(result) == 1 and result[0]['line'] == 1 and result[0]['title'].startswith('Title')",
            str(path),
        ],
        check=True,
        timeout=10,
        capture_output=True,
        text=True,
    )
