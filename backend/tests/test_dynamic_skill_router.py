"""Unit tests for DynamicSkillRouter (Route C / RFC-003 Pillar 2)."""

from pathlib import Path

import pytest

from deerflow.skills.router import DynamicSkillRouter, _extract_intent_tokens
from deerflow.skills.types import Skill, SkillCategory


@pytest.fixture
def sample_skills():
    dummy_dir = Path("/mnt/skills/dummy")
    return [
        Skill(
            name="pptx-generator",
            description="Generate, format, and export PowerPoint presentations and slide decks",
            license="MIT",
            skill_dir=dummy_dir / "pptx",
            skill_file=dummy_dir / "pptx" / "SKILL.md",
            relative_path=Path("pptx"),
            category=SkillCategory.PUBLIC,
            enabled=True,
            allowed_tools=("write_file", "bash"),
        ),
        Skill(
            name="pdf-parser",
            description="Extract text, tables, and structured data from PDF files and invoices",
            license="MIT",
            skill_dir=dummy_dir / "pdf",
            skill_file=dummy_dir / "pdf" / "SKILL.md",
            relative_path=Path("pdf"),
            category=SkillCategory.PUBLIC,
            enabled=True,
            allowed_tools=("read_file", "bash"),
        ),
        Skill(
            name="github-manager",
            description="Manage GitHub repositories, issues, pull requests, and workflows",
            license="MIT",
            skill_dir=dummy_dir / "github",
            skill_file=dummy_dir / "github" / "SKILL.md",
            relative_path=Path("github"),
            category=SkillCategory.PUBLIC,
            enabled=True,
            allowed_tools=("bash",),
        ),
        Skill(
            name="legacy-tool",
            description="Deprecated tool that should not be matched",
            license="MIT",
            skill_dir=dummy_dir / "legacy",
            skill_file=dummy_dir / "legacy" / "SKILL.md",
            relative_path=Path("legacy"),
            category=SkillCategory.PUBLIC,
            enabled=False,
        ),
    ]


class TestDynamicSkillRouter:
    def test_extract_intent_tokens(self):
        text = "Please help me generate a PowerPoint presentation with Python!"
        tokens = _extract_intent_tokens(text)
        assert "generate" in tokens
        assert "powerpoint" in tokens
        assert "presentation" in tokens
        assert "python" in tokens
        assert "please" not in tokens  # Stop word removed
        assert "me" not in tokens  # Stop word removed

    def test_name_and_keyword_match(self, sample_skills):
        router = DynamicSkillRouter(sample_skills)
        query = "I need to create a pptx deck for our weekly team sync"
        matches = router.route_intent(query, threshold=0.3)
        assert len(matches) >= 1
        top = matches[0]
        assert top.skill.name == "pptx-generator"
        assert top.is_name_match is True
        assert top.score >= 0.5

    def test_description_semantic_match(self, sample_skills):
        router = DynamicSkillRouter(sample_skills)
        query = "Can you extract financial tables from this vendor invoice?"
        matches = router.route_intent(query, threshold=0.2)
        assert len(matches) >= 1
        top = matches[0]
        assert top.skill.name == "pdf-parser"
        assert "tables" in top.matched_tokens or "invoice" in top.matched_tokens

    def test_irrelevant_query_returns_empty(self, sample_skills):
        router = DynamicSkillRouter(sample_skills)
        query = "What is the square root of 144?"
        matches = router.route_intent(query, threshold=0.3)
        assert len(matches) == 0

    def test_disabled_skill_excluded(self, sample_skills):
        router = DynamicSkillRouter(sample_skills)
        query = "Use the legacy tool to inspect code"
        matches = router.route_intent(query, threshold=0.1)
        matched_names = [m.skill.name for m in matches]
        assert "legacy-tool" not in matched_names

    def test_render_jit_skill_context(self, sample_skills):
        router = DynamicSkillRouter(sample_skills)
        matches = router.route_intent("Build a slide deck using pptx-generator")
        rendered = router.render_jit_skill_context(matches)
        assert "<activated_skills>" in rendered
        assert "Skill: pptx-generator" in rendered
        assert "Allowed Tools: write_file, bash" in rendered
        assert "</activated_skills>" in rendered
