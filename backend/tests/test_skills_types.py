"""Tests for deerflow.skills.types — Skill dataclass and path computation.

Tests the Skill dataclass properties including skill_path, container
path resolution, container file path, and repr formatting.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Ensure heavy dependencies are mocked before importing deerflow modules.
# ---------------------------------------------------------------------------
for _mod in ("yaml", "dotenv", "langchain", "langchain_core", "langchain_core.tools"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

_harness_path = str(Path(__file__).resolve().parents[1] / "packages" / "harness")
if _harness_path not in sys.path:
    sys.path.insert(0, _harness_path)

from deerflow.skills.types import Skill  # noqa: E402


def _make_skill(**overrides) -> Skill:
    defaults = dict(
        name="test-skill",
        description="A test skill",
        license="MIT",
        skill_dir=Path("/skills/public/test-skill"),
        skill_file=Path("/skills/public/test-skill/SKILL.md"),
        relative_path=Path("test-skill"),
        category="public",
        enabled=True,
    )
    defaults.update(overrides)
    return Skill(**defaults)


# ---------------------------------------------------------------------------
# Skill — basic properties
# ---------------------------------------------------------------------------


class TestSkillBasic:
    def test_name(self):
        s = _make_skill(name="my-skill")
        assert s.name == "my-skill"

    def test_description(self):
        s = _make_skill(description="Does things")
        assert s.description == "Does things"

    def test_license(self):
        s = _make_skill(license="Apache-2.0")
        assert s.license == "Apache-2.0"

    def test_license_none(self):
        s = _make_skill(license=None)
        assert s.license is None

    def test_category(self):
        s = _make_skill(category="custom")
        assert s.category == "custom"

    def test_enabled_default_false(self):
        s = Skill(
            name="x",
            description="x",
            license=None,
            skill_dir=Path("."),
            skill_file=Path("SKILL.md"),
            relative_path=Path("."),
            category="public",
        )
        assert s.enabled is False

    def test_enabled_explicit(self):
        s = _make_skill(enabled=True)
        assert s.enabled is True

    def test_skill_dir_and_file(self):
        s = _make_skill(
            skill_dir=Path("/opt/skills/public/my-skill"),
            skill_file=Path("/opt/skills/public/my-skill/SKILL.md"),
        )
        assert s.skill_dir == Path("/opt/skills/public/my-skill")
        assert s.skill_file == Path("/opt/skills/public/my-skill/SKILL.md")


# ---------------------------------------------------------------------------
# Skill — skill_path property
# ---------------------------------------------------------------------------


class TestSkillPath:
    def test_normal_path(self):
        s = _make_skill(relative_path=Path("web-design/responsive"))
        assert s.skill_path == "web-design/responsive"

    def test_dot_path_returns_empty(self):
        s = _make_skill(relative_path=Path("."))
        assert s.skill_path == ""

    def test_single_level(self):
        s = _make_skill(relative_path=Path("video-generation"))
        assert s.skill_path == "video-generation"

    def test_deeply_nested(self):
        s = _make_skill(relative_path=Path("a/b/c/d"))
        assert s.skill_path == "a/b/c/d"


# ---------------------------------------------------------------------------
# Skill — get_container_path
# ---------------------------------------------------------------------------


class TestGetContainerPath:
    def test_default_base_path(self):
        s = _make_skill(relative_path=Path("my-skill"), category="public")
        assert s.get_container_path() == "/mnt/skills/public/my-skill"

    def test_custom_base_path(self):
        s = _make_skill(relative_path=Path("my-skill"), category="custom")
        result = s.get_container_path("/opt/skills")
        assert result == "/opt/skills/custom/my-skill"

    def test_dot_relative_path(self):
        s = _make_skill(relative_path=Path("."), category="public")
        result = s.get_container_path()
        assert result == "/mnt/skills/public"

    def test_nested_path(self):
        s = _make_skill(relative_path=Path("category/sub/skill"), category="public")
        result = s.get_container_path()
        assert result == "/mnt/skills/public/category/sub/skill"

    def test_custom_category(self):
        s = _make_skill(relative_path=Path("tool"), category="custom")
        assert s.get_container_path() == "/mnt/skills/custom/tool"


# ---------------------------------------------------------------------------
# Skill — get_container_file_path
# ---------------------------------------------------------------------------


class TestGetContainerFilePath:
    def test_default(self):
        s = _make_skill(relative_path=Path("my-skill"), category="public")
        assert s.get_container_file_path() == "/mnt/skills/public/my-skill/SKILL.md"

    def test_custom_base(self):
        s = _make_skill(relative_path=Path("my-skill"), category="custom")
        result = s.get_container_file_path("/opt/skills")
        assert result == "/opt/skills/custom/my-skill/SKILL.md"

    def test_dot_path(self):
        s = _make_skill(relative_path=Path("."), category="public")
        result = s.get_container_file_path()
        assert result == "/mnt/skills/public/SKILL.md"

    def test_nested_path(self):
        s = _make_skill(relative_path=Path("a/b"), category="public")
        assert s.get_container_file_path() == "/mnt/skills/public/a/b/SKILL.md"


# ---------------------------------------------------------------------------
# Skill — __repr__
# ---------------------------------------------------------------------------


class TestSkillRepr:
    def test_repr_contains_key_fields(self):
        s = _make_skill(name="web-design", description="Designs websites", category="public")
        r = repr(s)
        assert "web-design" in r
        assert "Designs websites" in r
        assert "public" in r
        assert r.startswith("Skill(")

    def test_repr_custom_category(self):
        s = _make_skill(name="my-tool", description="A tool", category="custom")
        r = repr(s)
        assert "custom" in r
        assert "my-tool" in r
