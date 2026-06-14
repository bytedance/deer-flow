"""Tests for deerflow.skills.registry."""

import subprocess
from pathlib import Path
from unittest.mock import patch

from deerflow.skills.registry import install_skill_from_repo, search_registry


def test_search_registry():
    entries = [
        {"name": "deep-research", "description": "Deep research using web search", "tags": ["research", "web"]},
        {"name": "image-generation", "description": "Generate AI images", "tags": ["image", "art"]},
    ]

    with patch("deerflow.skills.registry.fetch_registry", return_value=entries):
        by_name = search_registry("deep")
        by_tag = search_registry("art")

    assert [entry["name"] for entry in by_name] == ["deep-research"]
    assert [entry["name"] for entry in by_tag] == ["image-generation"]


def test_install_skill_from_repo(tmp_path: Path):
    skills_root = tmp_path / "skills"
    expected_skill = "community-skill"

    def fake_run(args, **kwargs):
        clone_dir = Path(args[-1])
        clone_dir.mkdir(parents=True, exist_ok=True)
        (clone_dir / "SKILL.md").write_text("---\nname: test\ndescription: test\n---\n", encoding="utf-8")
        (clone_dir / "README.md").write_text("hello", encoding="utf-8")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    with (
        patch("deerflow.skills.registry.subprocess.run", side_effect=fake_run),
        patch("deerflow.skills.registry._validate_skill_frontmatter", return_value=(True, "OK", expected_skill)),
    ):
        result = install_skill_from_repo("https://github.com/example/skill", skills_root=skills_root)

    target = skills_root / "community" / expected_skill
    assert result["success"] is True
    assert result["skill_name"] == expected_skill
    assert target.exists()
    assert (target / "SKILL.md").exists()


def test_install_skill_normalizes_url(tmp_path: Path):
    skills_root = tmp_path / "skills"

    def fake_run(args, **kwargs):
        clone_dir = Path(args[-1])
        clone_dir.mkdir(parents=True, exist_ok=True)
        (clone_dir / "SKILL.md").write_text("---\nname: test\ndescription: test\n---\n", encoding="utf-8")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    with (
        patch("deerflow.skills.registry.subprocess.run", side_effect=fake_run) as mock_run,
        patch("deerflow.skills.registry._validate_skill_frontmatter", return_value=(True, "OK", "normalized-skill")),
    ):
        install_skill_from_repo("owner/repo", skills_root=skills_root)

    called_args = mock_run.call_args.args[0]
    assert called_args[4] == "https://github.com/owner/repo.git"
