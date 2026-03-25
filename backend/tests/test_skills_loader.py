"""Tests for skills loader module."""

import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

from deerflow.skills.loader import get_skills_root_path, load_skills
from deerflow.skills.types import Skill


class TestGetSkillsRootPath:
    """Tests for get_skills_root_path function."""

    def test_returns_path_to_skills_directory(self):
        """Should return the correct path to the skills directory."""
        result = get_skills_root_path()
        
        assert isinstance(result, Path)
        assert result.name == "skills"
        # Should be relative to backend directory
        assert "deer-flow" in str(result)


class TestLoadSkills:
    """Tests for load_skills function."""

    def test_returns_empty_list_when_path_does_not_exist(self, tmp_path):
        """Should return empty list when skills path doesn't exist."""
        nonexistent = tmp_path / "nonexistent"
        
        result = load_skills(skills_path=nonexistent, use_config=False)
        
        assert result == []

    def test_returns_empty_list_for_empty_directory(self, tmp_path):
        """Should return empty list when skills directory is empty."""
        skills_path = tmp_path / "skills"
        skills_path.mkdir()
        (skills_path / "public").mkdir()
        
        result = load_skills(skills_path=skills_path, use_config=False)
        
        assert result == []

    @patch("deerflow.skills.loader.parse_skill_file")
    def test_loads_skills_from_public_directory(self, mock_parse, tmp_path):
        """Should load skills from public directory."""
        skills_path = tmp_path / "skills"
        public_dir = skills_path / "public"
        public_dir.mkdir(parents=True)
        
        # Create a skill directory with SKILL.md
        skill_dir = public_dir / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: test-skill\ndescription: Test skill\n---\n")
        
        mock_skill = Mock(spec=Skill)
        mock_skill.name = "test-skill"
        mock_skill.category = "public"
        mock_skill.enabled = True
        mock_parse.return_value = mock_skill
        
        with patch("deerflow.skills.loader.ExtensionsConfig"):
            result = load_skills(skills_path=skills_path, use_config=False)
        
        assert len(result) == 1
        assert result[0].name == "test-skill"
        mock_parse.assert_called_once()

    @patch("deerflow.skills.loader.parse_skill_file")
    def test_skips_directories_without_skill_md(self, mock_parse, tmp_path):
        """Should skip directories that don't contain SKILL.md."""
        skills_path = tmp_path / "skills"
        public_dir = skills_path / "public"
        public_dir.mkdir(parents=True)
        
        # Create directories without SKILL.md
        (public_dir / "no-skill").mkdir()
        (public_dir / "also-no-skill").mkdir()
        
        with patch("deerflow.skills.loader.ExtensionsConfig"):
            result = load_skills(skills_path=skills_path, use_config=False)
        
        assert result == []
        mock_parse.assert_not_called()

    @patch("deerflow.skills.loader.parse_skill_file")
    def test_filters_disabled_skills_when_enabled_only(self, mock_parse, tmp_path):
        """Should filter out disabled skills when enabled_only=True."""
        skills_path = tmp_path / "skills"
        public_dir = skills_path / "public"
        public_dir.mkdir(parents=True)
        
        skill_dir = public_dir / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("test")
        
        mock_skill = Mock(spec=Skill)
        mock_skill.name = "test-skill"
        mock_skill.enabled = False
        mock_parse.return_value = mock_skill
        
        with patch("deerflow.skills.loader.ExtensionsConfig"):
            result = load_skills(skills_path=skills_path, use_config=False, enabled_only=True)
        
        assert result == []

    @patch("deerflow.skills.loader.parse_skill_file")
    def test_returns_both_enabled_and_disabled_by_default(self, mock_parse, tmp_path):
        """Should return both enabled and disabled skills by default."""
        skills_path = tmp_path / "skills"
        public_dir = skills_path / "public"
        public_dir.mkdir(parents=True)
        
        skill_dir = public_dir / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("test")
        
        mock_skill = Mock(spec=Skill)
        mock_skill.name = "test-skill"
        mock_skill.enabled = False
        mock_parse.return_value = mock_skill
        
        with patch("deerflow.skills.loader.ExtensionsConfig"):
            result = load_skills(skills_path=skills_path, use_config=False, enabled_only=False)
        
        assert len(result) == 1

    @patch("deerflow.skills.loader.parse_skill_file")
    def test_skills_sorted_by_name(self, mock_parse, tmp_path):
        """Should return skills sorted by name."""
        skills_path = tmp_path / "skills"
        public_dir = skills_path / "public"
        public_dir.mkdir(parents=True)
        
        # Create multiple skills
        for name in ["zebra-skill", "alpha-skill", "beta-skill"]:
            skill_dir = public_dir / name
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("test")
        
        def side_effect(*args, **kwargs):
            mock_skill = Mock(spec=Skill)
            mock_skill.name = args[0].parent.name
            mock_skill.enabled = True
            return mock_skill
        
        mock_parse.side_effect = side_effect
        
        with patch("deerflow.skills.loader.ExtensionsConfig"):
            result = load_skills(skills_path=skills_path, use_config=False)
        
        names = [s.name for s in result]
        assert names == sorted(names)

    def test_skips_hidden_directories(self, tmp_path):
        """Should skip hidden directories (starting with .)."""
        skills_path = tmp_path / "skills"
        public_dir = skills_path / "public"
        public_dir.mkdir(parents=True)
        
        # Create hidden directory
        hidden_dir = public_dir / ".hidden"
        hidden_dir.mkdir()
        (hidden_dir / "SKILL.md").write_text("test")
        
        with patch("deerflow.skills.loader.ExtensionsConfig"):
            result = load_skills(skills_path=skills_path, use_config=False)
        
        assert result == []

    def test_follows_symlinks(self, tmp_path):
        """Should follow symbolic links when scanning directories."""
        skills_path = tmp_path / "skills"
        public_dir = skills_path / "public"
        public_dir.mkdir(parents=True)
        
        # Create actual skill directory elsewhere
        actual_dir = tmp_path / "actual-skill"
        actual_dir.mkdir()
        (actual_dir / "SKILL.md").write_text("---\nname: linked-skill\ndescription: Linked\n---")
        
        # Create symlink in public directory
        link_dir = public_dir / "linked-skill"
        link_dir.symlink_to(actual_dir)
        
        with patch("deerflow.skills.loader.ExtensionsConfig"):
            with patch("deerflow.skills.loader.parse_skill_file") as mock_parse:
                mock_skill = Mock(spec=Skill)
                mock_skill.name = "linked-skill"
                mock_skill.enabled = True
                mock_parse.return_value = mock_skill
                
                result = load_skills(skills_path=skills_path, use_config=False)
        
        assert len(result) == 1
