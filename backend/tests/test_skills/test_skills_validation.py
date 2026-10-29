"""Tests for skill frontmatter validation.

Consolidates all _validate_skill_frontmatter tests (previously split across
test_skills_router.py and this module) into a single dedicated module.
"""

from pathlib import Path

import pytest

from deerflow.skills.frontmatter import split_skill_markdown
from deerflow.skills.validation import ALLOWED_FRONTMATTER_PROPERTIES, _validate_skill_frontmatter


def _write_skill(tmp_path: Path, content: str, encoding: str = "utf-8") -> Path:
    """Write a SKILL.md file and return its parent directory."""
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(content, encoding=encoding)
    return tmp_path


class TestValidateSkillFrontmatter:
    def test_valid_minimal_skill(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "---\nname: my-skill\ndescription: A valid skill\n---\n\nBody\n",
        )
        valid, msg, name = _validate_skill_frontmatter(skill_dir)
        assert valid is True
        assert msg == "Skill is valid!"
        assert name == "my-skill"

    def test_valid_with_all_allowed_fields(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "---\nname: my-skill\ndescription: A skill\nlicense: MIT\nversion: '1.0'\nauthor: test\nallowed-tools: [bash, read_file]\n---\n\nBody\n",
        )
        valid, msg, name = _validate_skill_frontmatter(skill_dir)
        assert valid is True
        assert msg == "Skill is valid!"
        assert name == "my-skill"

    def test_allows_empty_allowed_tools(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "---\nname: my-skill\ndescription: A skill\nallowed-tools: []\n---\n\nBody\n",
        )
        valid, msg, name = _validate_skill_frontmatter(skill_dir)
        assert valid is True
        assert msg == "Skill is valid!"
        assert name == "my-skill"

    @pytest.mark.parametrize("optional", ["", "    optional: false\n", "    optional: true\n"])
    def test_required_secrets_optional_boolean_values(self, tmp_path, optional):
        skill_dir = _write_skill(
            tmp_path,
            f"---\nname: my-skill\ndescription: A skill\nrequired-secrets:\n  - name: ERP_TOKEN\n{optional}---\n\nBody\n",
        )
        valid, msg, name = _validate_skill_frontmatter(skill_dir)
        assert valid is True
        assert msg == "Skill is valid!"
        assert name == "my-skill"

    @pytest.mark.parametrize("optional", ['"false"', '"true"', '"no"', "1", "[]", "{}", "null"])
    def test_required_secrets_optional_rejects_non_booleans(self, tmp_path, optional):
        skill_dir = _write_skill(
            tmp_path,
            f"---\nname: my-skill\ndescription: A skill\nrequired-secrets:\n  - name: ERP_TOKEN\n    optional: {optional}\n---\n\nBody\n",
        )
        valid, msg, name = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert msg == "required-secrets entry 'ERP_TOKEN' optional must be a boolean"
        assert name is None

    def test_required_secrets_optional_error_identifies_unnamed_entry(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            '---\nname: my-skill\ndescription: A skill\nrequired-secrets:\n  - optional: "true"\n---\n\nBody\n',
        )
        valid, msg, name = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert msg == "required-secrets entry without a name has an optional field that must be a boolean"
        assert name is None

    def test_allows_argument_hint(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "---\nname: my-skill\ndescription: A skill\nargument-hint: '[issue-number]'\n---\n\nBody\n",
        )
        valid, msg, name = _validate_skill_frontmatter(skill_dir)
        assert valid is True
        assert msg == "Skill is valid!"
        assert name == "my-skill"

    def test_allows_allowed_tools_string(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "---\nname: my-skill\ndescription: A skill\nallowed-tools: Bash(tvly *) Bash(playwright-cli:*)\n---\n\nBody\n",
        )
        valid, msg, name = _validate_skill_frontmatter(skill_dir)
        assert valid is True
        assert msg == "Skill is valid!"
        assert name == "my-skill"

    def test_rejects_allowed_tools_non_string_entry(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "---\nname: my-skill\ndescription: A skill\nallowed-tools: [bash, 1]\n---\n\nBody\n",
        )
        valid, msg, name = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert "allowed-tools" in msg
        assert str(tmp_path) not in msg
        assert "SKILL.md" in msg
        assert name is None

    def test_missing_skill_md(self, tmp_path):
        valid, msg, name = _validate_skill_frontmatter(tmp_path)
        assert valid is False
        assert "not found" in msg
        assert name is None

    def test_no_frontmatter(self, tmp_path):
        skill_dir = _write_skill(tmp_path, "# Just markdown\n\nNo front matter.\n")
        valid, msg, _ = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert "frontmatter" in msg.lower()

    def test_invalid_yaml(self, tmp_path):
        skill_dir = _write_skill(tmp_path, "---\n[invalid yaml: {{\n---\n\nBody\n")
        valid, msg, _ = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert "YAML" in msg

    def test_missing_name(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "---\ndescription: A skill without a name\n---\n\nBody\n",
        )
        valid, msg, _ = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert "name" in msg.lower()

    def test_missing_description(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "---\nname: my-skill\n---\n\nBody\n",
        )
        valid, msg, _ = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert "description" in msg.lower()

    def test_unexpected_keys_rejected(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "---\nname: my-skill\ndescription: test\ncustom-field: bad\n---\n\nBody\n",
        )
        valid, msg, _ = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert "custom-field" in msg

    def test_non_string_frontmatter_key_reports_cleanly_instead_of_crashing(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "---\nname: my-skill\ndescription: test\n42: bad\ncustom-field: bad\n---\n\nBody\n",
        )
        valid, msg, name = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert "custom-field" in msg
        assert "42" in msg
        assert name is None

    def test_name_must_be_hyphen_case(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "---\nname: MySkill\ndescription: test\n---\n\nBody\n",
        )
        valid, msg, _ = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert "hyphen-case" in msg

    def test_name_no_leading_hyphen(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "---\nname: -my-skill\ndescription: test\n---\n\nBody\n",
        )
        valid, msg, _ = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert "hyphen" in msg

    def test_name_no_trailing_hyphen(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "---\nname: my-skill-\ndescription: test\n---\n\nBody\n",
        )
        valid, msg, _ = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert "hyphen" in msg

    def test_name_no_consecutive_hyphens(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "---\nname: my--skill\ndescription: test\n---\n\nBody\n",
        )
        valid, msg, _ = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert "hyphen" in msg

    def test_name_too_long(self, tmp_path):
        long_name = "a" * 65
        skill_dir = _write_skill(
            tmp_path,
            f"---\nname: {long_name}\ndescription: test\n---\n\nBody\n",
        )
        valid, msg, _ = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert "too long" in msg.lower()

    def test_description_no_angle_brackets(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "---\nname: my-skill\ndescription: Has <html> tags\n---\n\nBody\n",
        )
        valid, msg, _ = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert "angle brackets" in msg.lower()

    def test_description_too_long(self, tmp_path):
        long_desc = "a" * 1025
        skill_dir = _write_skill(
            tmp_path,
            f"---\nname: my-skill\ndescription: {long_desc}\n---\n\nBody\n",
        )
        valid, msg, _ = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert "too long" in msg.lower()

    def test_description_at_max_length_accepted(self, tmp_path):
        max_desc = "a" * 1024
        skill_dir = _write_skill(
            tmp_path,
            f"---\nname: my-skill\ndescription: {max_desc}\n---\n\nBody\n",
        )
        valid, msg, name = _validate_skill_frontmatter(skill_dir)
        assert valid is True
        assert msg == "Skill is valid!"
        assert name == "my-skill"

    def test_empty_description_rejected(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "---\nname: my-skill\ndescription: ''\n---\n\nBody\n",
        )
        valid, msg, name = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert "empty" in msg.lower()
        assert name is None

    def test_whitespace_only_description_rejected(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "---\nname: my-skill\ndescription: '   '\n---\n\nBody\n",
        )
        valid, msg, name = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert "empty" in msg.lower()
        assert name is None

    def test_empty_name_rejected(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "---\nname: ''\ndescription: test\n---\n\nBody\n",
        )
        valid, msg, _ = _validate_skill_frontmatter(skill_dir)
        assert valid is False
        assert "empty" in msg.lower()

    def test_allowed_properties_constant(self):
        assert "name" in ALLOWED_FRONTMATTER_PROPERTIES
        assert "description" in ALLOWED_FRONTMATTER_PROPERTIES
        assert "license" in ALLOWED_FRONTMATTER_PROPERTIES

    def test_reads_utf8_on_windows_locale(self, tmp_path, monkeypatch):
        skill_dir = _write_skill(
            tmp_path,
            '---\nname: demo-skill\ndescription: "Curly quotes: \u201cutf8\u201d"\n---\n\n# Demo Skill\n',
        )
        original_read_text = Path.read_text

        def read_text_with_gbk_default(self, *args, **kwargs):
            kwargs.setdefault("encoding", "gbk")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", read_text_with_gbk_default)

        valid, msg, name = _validate_skill_frontmatter(skill_dir)
        assert valid is True
        assert msg == "Skill is valid!"
        assert name == "demo-skill"

    def test_valid_when_saved_with_utf8_bom(self, tmp_path):
        """A SKILL.md saved as "UTF-8 with BOM" installs like any other file.

        Windows Notepad and PowerShell's ``Set-Content -Encoding UTF8`` prepend U+FEFF,
        which used to fall outside the ``^---`` anchor and report "No YAML frontmatter
        found" for a file that is byte-for-byte a valid skill.
        """
        skill_dir = _write_skill(
            tmp_path,
            "---\nname: my-skill\ndescription: A valid skill\n---\n\nBody\n",
            encoding="utf-8-sig",
        )
        assert (skill_dir / "SKILL.md").read_bytes().startswith(b"\xef\xbb\xbf"), "fixture must carry a real BOM"

        valid, msg, name = _validate_skill_frontmatter(skill_dir)
        assert valid is True
        assert msg == "Skill is valid!"
        assert name == "my-skill"


class TestSplitSkillMarkdownBom:
    def test_bom_is_consumed_and_reaches_neither_metadata_nor_body(self):
        """The mark is swallowed by the anchor instead of leaking into the parsed parts."""
        parts, error = split_skill_markdown("\ufeff---\nname: my-skill\ndescription: A valid skill\n---\nBody\n")

        assert error is None
        assert parts is not None
        assert parts.metadata["name"] == "my-skill"
        assert parts.frontmatter_text == "name: my-skill\ndescription: A valid skill"
        assert parts.body == "Body\n"

    def test_control_document_without_bom_is_parsed_identically(self):
        parts, error = split_skill_markdown("---\nname: my-skill\ndescription: A valid skill\n---\nBody\n")

        assert error is None
        assert parts is not None
        assert parts.metadata["name"] == "my-skill"
        assert parts.frontmatter_text == "name: my-skill\ndescription: A valid skill"
        assert parts.body == "Body\n"
