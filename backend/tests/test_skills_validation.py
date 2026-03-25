"""Tests for skills validation module."""

import pytest

from deerflow.skills.validation import (
    _validate_skill_frontmatter,
    ALLOWED_FRONTMATTER_PROPERTIES,
)


class TestValidateSkillFrontmatter:
    """Tests for _validate_skill_frontmatter function."""

    def test_valid_skill_passes(self, tmp_path):
        """Should return valid for properly formatted SKILL.md."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: test-skill
description: A test skill description
license: MIT
---

# Test Skill

This is the skill content.
""")
        
        is_valid, message, name = _validate_skill_frontmatter(skill_dir)
        
        assert is_valid is True
        assert name == "test-skill"

    def test_missing_skill_md_fails(self, tmp_path):
        """Should fail when SKILL.md doesn't exist."""
        skill_dir = tmp_path / "empty-dir"
        skill_dir.mkdir()
        
        is_valid, message, name = _validate_skill_frontmatter(skill_dir)
        
        assert is_valid is False
        assert "SKILL.md not found" in message
        assert name is None

    def test_missing_frontmatter_fails(self, tmp_path):
        """Should fail when SKILL.md has no frontmatter."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("# Just a markdown file\n\nNo frontmatter here.")
        
        is_valid, message, name = _validate_skill_frontmatter(skill_dir)
        
        assert is_valid is False
        assert "No YAML frontmatter found" in message

    def test_invalid_frontmatter_format_fails(self, tmp_path):
        """Should fail with invalid frontmatter format."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("---\nInvalid frontmatter without closing")
        
        is_valid, message, name = _validate_skill_frontmatter(skill_dir)
        
        assert is_valid is False
        assert "Invalid frontmatter format" in message

    def test_invalid_yaml_fails(self, tmp_path):
        """Should fail with invalid YAML syntax."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: test-skill
  invalid yaml: [
description: test
---
""")
        
        is_valid, message, name = _validate_skill_frontmatter(skill_dir)
        
        assert is_valid is False
        assert "Invalid YAML" in message

    def test_missing_name_fails(self, tmp_path):
        """Should fail when name is missing."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
description: A test skill
---
""")
        
        is_valid, message, name = _validate_skill_frontmatter(skill_dir)
        
        assert is_valid is False
        assert "Missing 'name'" in message

    def test_missing_description_fails(self, tmp_path):
        """Should fail when description is missing."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: test-skill
---
""")
        
        is_valid, message, name = _validate_skill_frontmatter(skill_dir)
        
        assert is_valid is False
        assert "Missing 'description'" in message

    def test_empty_name_fails(self, tmp_path):
        """Should fail when name is empty."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: ""
description: A test skill
---
""")
        
        is_valid, message, name = _validate_skill_frontmatter(skill_dir)
        
        assert is_valid is False
        assert "Name cannot be empty" in message

    def test_name_with_uppercase_fails(self, tmp_path):
        """Should fail when name contains uppercase letters."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: TestSkill
description: A test skill
---
""")
        
        is_valid, message, name = _validate_skill_frontmatter(skill_dir)
        
        assert is_valid is False
        assert "hyphen-case" in message

    def test_name_with_underscore_fails(self, tmp_path):
        """Should fail when name contains underscores."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: test_skill
description: A test skill
---
""")
        
        is_valid, message, name = _validate_skill_frontmatter(skill_dir)
        
        assert is_valid is False
        assert "hyphen-case" in message

    def test_name_starting_with_hyphen_fails(self, tmp_path):
        """Should fail when name starts with hyphen."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: -test-skill
description: A test skill
---
""")
        
        is_valid, message, name = _validate_skill_frontmatter(skill_dir)
        
        assert is_valid is False
        assert "cannot start/end with hyphen" in message

    def test_name_with_consecutive_hyphens_fails(self, tmp_path):
        """Should fail when name has consecutive hyphens."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: test--skill
description: A test skill
---
""")
        
        is_valid, message, name = _validate_skill_frontmatter(skill_dir)
        
        assert is_valid is False
        assert "consecutive hyphens" in message

    def test_name_too_long_fails(self, tmp_path):
        """Should fail when name exceeds 64 characters."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        long_name = "a" * 65
        skill_md.write_text(f"""---
name: {long_name}
description: A test skill
---
""")
        
        is_valid, message, name = _validate_skill_frontmatter(skill_dir)
        
        assert is_valid is False
        assert "too long" in message
        assert "64" in message

    def test_description_with_angle_brackets_fails(self, tmp_path):
        """Should fail when description contains angle brackets."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: test-skill
description: A skill with <script> tags
---
""")
        
        is_valid, message, name = _validate_skill_frontmatter(skill_dir)
        
        assert is_valid is False
        assert "angle brackets" in message

    def test_description_too_long_fails(self, tmp_path):
        """Should fail when description exceeds 1024 characters."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        long_desc = "a" * 1025
        skill_md.write_text(f"""---
name: test-skill
description: {long_desc}
---
""")
        
        is_valid, message, name = _validate_skill_frontmatter(skill_dir)
        
        assert is_valid is False
        assert "too long" in message
        assert "1024" in message

    def test_unexpected_keys_fails(self, tmp_path):
        """Should fail when frontmatter has unexpected keys."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: test-skill
description: A test skill
invalid-key: value
---
""")
        
        is_valid, message, name = _validate_skill_frontmatter(skill_dir)
        
        assert is_valid is False
        assert "Unexpected key" in message

    def test_non_dict_frontmatter_fails(self, tmp_path):
        """Should fail when frontmatter is not a dictionary."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
- just a list
- not a dict
---
""")
        
        is_valid, message, name = _validate_skill_frontmatter(skill_dir)
        
        assert is_valid is False
        assert "must be a YAML dictionary" in message

    def test_frontmatter_not_string_fails(self, tmp_path):
        """Should fail when frontmatter properties are not strings."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: 123
description: A test skill
---
""")
        
        is_valid, message, name = _validate_skill_frontmatter(skill_dir)
        
        assert is_valid is False
        assert "Name must be a string" in message


class TestAllowedFrontmatterProperties:
    """Tests for ALLOWED_FRONTMATTER_PROPERTIES constant."""

    def test_contains_expected_properties(self):
        """Should contain expected frontmatter properties."""
        expected = {
            "name",
            "description", 
            "license",
            "allowed-tools",
            "metadata",
            "compatibility",
            "version",
            "author",
        }
        assert ALLOWED_FRONTMATTER_PROPERTIES == expected
