"""Tests for the skill_manage tool."""

import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deerflow.skills.security_scanner import ScanDecision, ScanVerdict

skill_manage_module = importlib.import_module("deerflow.tools.skill_manage_tool")


def _write_skill(skill_dir: Path, name: str, description: str) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


def _runtime(thread_id: str = "thread-1") -> SimpleNamespace:
    return SimpleNamespace(context={"thread_id": thread_id}, config={}, state={})


async def _run_tool(**kwargs) -> str:
    coroutine = getattr(skill_manage_module.skill_manage_tool, "coroutine", None)
    if coroutine is not None:
        return await coroutine(**kwargs)
    return skill_manage_module.skill_manage_tool.func(**kwargs)


@pytest.fixture()
def skills_root(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    (root / "public").mkdir(parents=True)
    (root / "custom").mkdir(parents=True)
    _write_skill(root / "public" / "deep-research", "deep-research", "Built-in research skill")
    return root


@pytest.fixture(autouse=True)
def patch_skills_root(monkeypatch, skills_root: Path):
    monkeypatch.setattr(skill_manage_module, "_get_skills_root_dir", lambda: skills_root)


@pytest.fixture(autouse=True)
def patch_scanner(monkeypatch):
    monkeypatch.setattr(
        skill_manage_module,
        "scan_content",
        AsyncMock(return_value=ScanVerdict(decision=ScanDecision.ALLOW, reason="approved")),
    )


def test_validate_skill_name():
    assert skill_manage_module._validate_skill_name("my-skill") is None
    assert skill_manage_module._validate_skill_name("MySkill") is not None


def test_validate_file_path():
    assert skill_manage_module._validate_file_path("references/guide.md") is None
    assert skill_manage_module._validate_file_path("assets/logo.png") is not None
    assert skill_manage_module._validate_file_path("../etc/passwd") is not None


def test_create_custom_skill_writes_history(skills_root: Path):
    result = asyncio.run(_run_tool(
        runtime=_runtime("thread-42"),
        action="create",
        name="my-skill",
        content="---\nname: my-skill\ndescription: A test skill\n---\n\n# My Skill\n",
    ))

    assert "created" in result.lower()
    skill_file = skills_root / "custom" / "my-skill" / "SKILL.md"
    assert skill_file.exists()

    history_file = skill_file.parent / "HISTORY.jsonl"
    record = json.loads(history_file.read_text(encoding="utf-8").strip())
    assert record["action"] == "create"
    assert record["thread_id"] == "thread-42"


def test_create_requires_matching_frontmatter_name():
    result = asyncio.run(_run_tool(
        runtime=_runtime(),
        action="create",
        name="my-skill",
        content="---\nname: other-skill\ndescription: A test skill\n---\n\n# My Skill\n",
    ))

    assert "must match tool name" in result


def test_create_override_mentions_built_in():
    result = asyncio.run(_run_tool(
        runtime=_runtime(),
        action="create",
        name="deep-research",
        content="---\nname: deep-research\ndescription: Override\n---\n\n# Override\n",
    ))

    assert "overrides the built-in version" in result


def test_patch_public_skill_is_blocked():
    result = asyncio.run(_run_tool(
        runtime=_runtime(),
        action="patch",
        name="deep-research",
        old_str="Built-in",
        new_str="Custom",
    ))

    assert "built-in skill" in result
    assert "action='create'" in result


def test_patch_custom_skill(skills_root: Path):
    _write_skill(skills_root / "custom" / "patchable", "patchable", "Original description")

    result = asyncio.run(_run_tool(
        runtime=_runtime(),
        action="patch",
        name="patchable",
        old_str="Original description",
        new_str="Updated description",
    ))

    assert "patched" in result.lower()
    content = (skills_root / "custom" / "patchable" / "SKILL.md").read_text(encoding="utf-8")
    assert "Updated description" in content


def test_write_reference_file(skills_root: Path):
    _write_skill(skills_root / "custom" / "my-skill", "my-skill", "Test")

    result = asyncio.run(_run_tool(
        runtime=_runtime(),
        action="write_file",
        name="my-skill",
        file_path="references/guide.md",
        file_content="# Guide\n\nSome content.\n",
    ))

    assert "written" in result.lower()
    assert (skills_root / "custom" / "my-skill" / "references" / "guide.md").exists()


def test_write_script_blocks_warn(monkeypatch, skills_root: Path):
    _write_skill(skills_root / "custom" / "my-skill", "my-skill", "Test")
    monkeypatch.setattr(
        skill_manage_module,
        "scan_content",
        AsyncMock(return_value=ScanVerdict(decision=ScanDecision.WARN, reason="manual review")),
    )

    result = asyncio.run(_run_tool(
        runtime=_runtime(),
        action="write_file",
        name="my-skill",
        file_path="scripts/helper.py",
        file_content="print('hello')\n",
    ))

    assert "script blocked" in result.lower()


def test_remove_file(skills_root: Path):
    _write_skill(skills_root / "custom" / "my-skill", "my-skill", "Test")
    target = skills_root / "custom" / "my-skill" / "templates" / "snippet.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("hello", encoding="utf-8")

    result = asyncio.run(_run_tool(
        runtime=_runtime(),
        action="remove_file",
        name="my-skill",
        file_path="templates/snippet.md",
    ))

    assert "removed" in result.lower()
    assert not target.exists()
