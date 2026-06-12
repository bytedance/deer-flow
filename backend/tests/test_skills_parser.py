"""Tests for the SKILL.md parser regression introduced in issue #1803.

The previous hand-rolled YAML parser stored quoted string values with their
surrounding quotes intact (e.g. ``name: "my-skill"`` → ``'"my-skill"'``).
This caused a mismatch with ``_validate_skill_frontmatter`` (which uses
``yaml.safe_load``) and broke skill lookup after installation.

The parser now uses ``yaml.safe_load`` consistently with ``validation.py``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from deerflow.skills.parser import parse_skill_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_skill(tmp_path: Path, front_matter: str, body: str = "# My Skill\n") -> Path:
    """Write a minimal SKILL.md and return the path."""
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(f"---\n{front_matter}\n---\n{body}", encoding="utf-8")
    return skill_file


# ---------------------------------------------------------------------------
# Basic parsing
# ---------------------------------------------------------------------------


def test_parse_plain_name(tmp_path):
    """Unquoted name is parsed correctly."""
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: A test skill")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.name == "my-skill"


def test_parse_quoted_name_no_quotes_in_result(tmp_path):
    """Quoted name (YAML string) must not include surrounding quotes in result.

    Regression: the old hand-rolled parser stored ``'"my-skill"'`` instead of
    ``'my-skill'`` when the YAML value was wrapped in double-quotes.
    """
    skill_file = _write_skill(tmp_path, 'name: "my-skill"\ndescription: A test skill')
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.name == "my-skill", f"Expected 'my-skill', got {skill.name!r}"


def test_parse_single_quoted_name(tmp_path):
    """Single-quoted YAML strings are also handled correctly."""
    skill_file = _write_skill(tmp_path, "name: 'my-skill'\ndescription: A test skill")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.name == "my-skill"


def test_parse_description_returned(tmp_path):
    """Description field is correctly extracted."""
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: Does amazing things")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.description == "Does amazing things"


def test_parse_multiline_description(tmp_path):
    """Multi-line YAML descriptions are collapsed correctly by yaml.safe_load."""
    front_matter = "name: my-skill\ndescription: >\n  A folded\n  description"
    skill_file = _write_skill(tmp_path, front_matter)
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert "folded" in skill.description


def test_parse_license_field(tmp_path):
    """Optional license field is captured when present."""
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: Test\nlicense: MIT")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.license == "MIT"


def test_parse_missing_allowed_tools_returns_none(tmp_path):
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: Test")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.allowed_tools is None


def test_parse_allowed_tools_list(tmp_path):
    skill_file = _write_skill(tmp_path, 'name: my-skill\ndescription: Test\nallowed-tools: ["bash", "read_file"]')
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.allowed_tools == ["bash", "read_file"]


def test_parse_empty_allowed_tools_list(tmp_path):
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: Test\nallowed-tools: []")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.allowed_tools == []


def test_parse_invalid_allowed_tools_returns_none(tmp_path):
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: Test\nallowed-tools: bash")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is None


def test_parse_missing_name_returns_none(tmp_path):
    """Skills missing a name field are rejected."""
    skill_file = _write_skill(tmp_path, "description: A test skill")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is None


def test_parse_missing_description_returns_none(tmp_path):
    """Skills missing a description field are rejected."""
    skill_file = _write_skill(tmp_path, "name: my-skill")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is None


def test_parse_no_front_matter_returns_none(tmp_path):
    """Files without YAML front-matter delimiters return None."""
    skill_dir = tmp_path / "no-fm"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# No front matter here\n", encoding="utf-8")
    skill = parse_skill_file(skill_file, category="public")
    assert skill is None


def test_parse_invalid_yaml_returns_none(tmp_path):
    """Malformed YAML front-matter is handled gracefully (returns None)."""
    skill_file = _write_skill(tmp_path, "name: [unclosed")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is None


def test_parse_category_stored(tmp_path):
    """Category is propagated into the returned Skill object."""
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: Test")
    skill = parse_skill_file(skill_file, category="public")
    assert skill is not None
    assert skill.category == "public"


def test_parse_nonexistent_file_returns_none(tmp_path):
    """Non-existent files are handled gracefully."""
    skill = parse_skill_file(tmp_path / "ghost" / "SKILL.md", category="custom")
    assert skill is None


# ---------------------------------------------------------------------------
# Friendly YAML error reporting
# ---------------------------------------------------------------------------


def test_parse_unquoted_colon_value_logs_line_and_hint(tmp_path, caplog):
    """Unquoted value with ': ' produces a log that exposes the full offending line
    (PyYAML truncates long lines with `...`) and a copy-pasteable quoting hint.

    Regression for issue #3333: SKILL.md authored by an LLM frequently
    contains ``description: foo: bar`` which PyYAML rejects with
    ``mapping values are not allowed here``. The skill is correctly skipped
    (the file is not silently accepted). Before this change the only
    diagnostic was PyYAML's own message, which (a) numbers lines within
    the front-matter body rather than the file and (b) truncates long
    values with '...'. The new behaviour pins:
      * the line number an author sees in their editor (file-line, not
        front-matter-line),
      * the *full* offending line (no '...' truncation), and
      * a copy-pasteable `key: "value"` hint.
    """

    # The description value is intentionally long enough to trigger
    # PyYAML's own '...' truncation in the rendered str(exc); our hint
    # must echo the *full* value regardless.
    long_value = "StarRun collector: progress, errors, tables out, plus assorted diagnostic notes"
    front_matter = f"name: collect-startrun\ndescription: {long_value}"
    skill_file = _write_skill(tmp_path, front_matter)

    with caplog.at_level(logging.ERROR, logger="deerflow.skills.parser"):
        skill = parse_skill_file(skill_file, category="custom")

    assert skill is None
    combined = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "Invalid YAML front-matter" in combined

    # 1. File-line, not front-matter-line. `description` is the 2nd line
    #    of the front-matter body, which is line 3 of the file (line 1
    #    is the leading `---` fence). Before this PR the log said
    #    `line 2`, which sent authors to the wrong row.
    assert f"line 3: description: {long_value}" in combined

    # 2. The full value is preserved -- PyYAML's own message truncates
    #    long values with '...', so the presence of the un-truncated tail
    #    proves we are reading the source line ourselves, not echoing
    #    PyYAML's snippet.
    assert "plus assorted diagnostic notes" in combined
    assert "..." not in [line for line in combined.splitlines() if line.startswith("  line ")][0]

    # 3. The copy-pasteable quoting hint is the actually-new diagnostic.
    assert f'hint: values containing ":" must be quoted, e.g. description: "{long_value}"' in combined


def test_parse_unquoted_colon_value_preserves_nested_key_indent(tmp_path, caplog):
    """Nested keys must keep their leading indentation in the quoting hint.

    Regression guard for CR feedback on PR #3335: an earlier version of
    the hint called ``key.strip()``, which turned ``  author: foo: bar``
    into ``author: "foo: bar"``. Pasting that back under a parent mapping
    silently moved the field to the top level. The hint must preserve
    the original indentation so authors can copy-paste-fix in place.
    """

    # A two-space-indented nested key triggers the same scanner error,
    # but its hint must keep the indentation.
    front_matter = "name: nested-skill\nmetadata:\n  author: Jane: Doe"
    skill_file = _write_skill(tmp_path, front_matter)

    with caplog.at_level(logging.ERROR, logger="deerflow.skills.parser"):
        skill = parse_skill_file(skill_file, category="custom")

    assert skill is None
    combined = "\n".join(rec.getMessage() for rec in caplog.records)
    # Two leading spaces in front of `author` are preserved.
    assert 'hint: values containing ":" must be quoted, e.g.   author: "Jane: Doe"' in combined


def test_parse_unrelated_yaml_error_omits_quoting_hint(tmp_path, caplog):
    """Errors other than 'mapping values are not allowed' must NOT carry the quoting hint."""

    # Unclosed flow sequence is a scanner error of a different shape; the
    # quoting hint would be misleading and must be suppressed.
    skill_file = _write_skill(tmp_path, "name: [unclosed\ndescription: x")

    with caplog.at_level(logging.ERROR, logger="deerflow.skills.parser"):
        skill = parse_skill_file(skill_file, category="custom")

    assert skill is None
    combined = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "Invalid YAML front-matter" in combined
    assert "hint:" not in combined


def test_parse_valid_skill_emits_no_error_log(tmp_path, caplog):
    """Sanity check: a valid SKILL.md must not produce any error logs."""

    skill_file = _write_skill(tmp_path, 'name: ok-skill\ndescription: "Foo: bar"')

    with caplog.at_level(logging.ERROR, logger="deerflow.skills.parser"):
        skill = parse_skill_file(skill_file, category="custom")

    assert skill is not None
    assert skill.description == "Foo: bar"
    assert not caplog.records, "valid SKILL.md must not log errors"


def test_parse_unquoted_colon_value_escapes_backslashes_in_hint(tmp_path, caplog):
    """Backslashes in the offending value must be doubled in the hint.

    Regression guard for CR feedback on PR #3335: an earlier version of
    the hint only escaped ``"`` but left ``\\`` untouched. Pasting the
    suggested ``key: "..."`` back into the file would then be reparsed
    as an escape sequence by PyYAML's double-quoted scalar rules and
    either fail to load or silently change meaning (e.g. ``C:\\Temp``
    becoming ``C:<TAB>emp``). The hint must double the backslash so the
    suggested scalar is valid YAML when pasted back.
    """

    # The second ``: `` (after ``path``) is what trips PyYAML's
    # "mapping values are not allowed here"; the ``C:\Temp`` segment
    # carries the backslash that the hint must escape.
    front_matter = "name: path-skill\ndescription: Windows path: C:\\Temp"
    skill_file = _write_skill(tmp_path, front_matter)

    with caplog.at_level(logging.ERROR, logger="deerflow.skills.parser"):
        skill = parse_skill_file(skill_file, category="custom")

    assert skill is None
    combined = "\n".join(rec.getMessage() for rec in caplog.records)
    assert r'description: "Windows path: C:\\Temp"' in combined


def test_parse_unquoted_colon_value_escapes_regex_in_hint(tmp_path, caplog):
    """Regex-style ``\\d`` must also be escaped in the hint.

    Same root cause as the Windows-path guard above, but with a
    regex-style escape that is even more likely to appear in
    LLM-authored skills (e.g. a ``description`` that quotes a regex).
    PyYAML rejects ``\\d`` in double-quoted scalars, so the hint must
    emit ``\\\\d`` to remain valid.
    """

    front_matter = "name: regex-skill\ndescription: match: \\d+ digits"
    skill_file = _write_skill(tmp_path, front_matter)

    with caplog.at_level(logging.ERROR, logger="deerflow.skills.parser"):
        skill = parse_skill_file(skill_file, category="custom")

    assert skill is None
    combined = "\n".join(rec.getMessage() for rec in caplog.records)
    assert r'description: "match: \\d+ digits"' in combined
