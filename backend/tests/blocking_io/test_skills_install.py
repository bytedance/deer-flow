"""Regression anchor: skill archive installation must not block the event loop.

``LocalSkillStorage.ainstall_skill_from_archive`` is the async entry point the
gateway ``POST /skills/install`` route awaits. It extracts the archive,
validates frontmatter, security-scans every installable file, and stages the
skill into the custom directory — all filesystem work that previously ran
inline on the event loop (zip extract, ``rglob`` enumeration, ``read_text``,
``shutil.copytree``). The fix offloads those phases via ``asyncio.to_thread``
while keeping the per-file LLM security scan as the only awaited work; if any
phase regresses back onto the loop, the strict Blockbuster gate raises
``BlockingError`` and this test fails.

Only the external LLM boundary (``scan_skill_content``) is stubbed — the
archive, extraction, validation, and staging all run against the real local
filesystem. Test-side setup IO is itself offloaded with ``asyncio.to_thread``
(matching ``test_agents_router``) so only the production path is exercised on
the loop.

``UserScopedSkillStorage`` overrides the same entry point and is what the route
actually awaits once per-user skill isolation is on, so it gets its own anchor
rather than inheriting the host-scoped one.
"""

from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.skills.storage.local_skill_storage import LocalSkillStorage

pytestmark = pytest.mark.asyncio

_SKILL_MD = """---
name: loop-skill
description: Anchor fixture skill for the blocking-IO gate.
---

# Loop Skill

Drives the full install pipeline under the Blockbuster gate.
"""

_SUPPORT_MD = "Reference notes scanned by the per-file security pass.\n"


def _build_archive(archive: Path) -> None:
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("loop-skill/SKILL.md", _SKILL_MD)
        zf.writestr("loop-skill/references/usage.md", _SUPPORT_MD)


async def test_install_skill_archive_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "loop-skill.skill"
    await asyncio.to_thread(_build_archive, archive)

    async def _allow_scan(content: str, *, executable: bool = False, location: str = "SKILL.md", app_config=None, static_findings=None):
        return SimpleNamespace(decision="allow", reason="anchor stub")

    # External dependency boundary only: the security scanner is an LLM call.
    monkeypatch.setattr("deerflow.skills.installer.scan_skill_content", _allow_scan)

    # Constructor resolves paths (one-time, cached in production via
    # get_or_new_skill_storage); offloaded here so the anchor exercises only
    # the install pipeline itself on the loop.
    storage = await asyncio.to_thread(LocalSkillStorage, host_path=str(tmp_path / "skills"))

    result = await storage.ainstall_skill_from_archive(archive)

    assert result["success"] is True
    assert result["skill_name"] == "loop-skill"
    installed_md = tmp_path / "skills" / "custom" / "loop-skill" / "SKILL.md"
    assert await asyncio.to_thread(installed_md.exists)
    assert await asyncio.to_thread((tmp_path / "skills" / "custom" / "loop-skill" / "references" / "usage.md").exists)


async def test_user_scoped_install_skill_archive_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    """The override the install route actually awaits must offload its own setup too.

    ``UserScopedSkillStorage.ainstall_skill_from_archive`` re-implements the
    pipeline with a per-user custom root and creates that root inside the
    coroutine, so the host-scoped anchor above cannot catch a regression there.
    """
    from deerflow.config import paths as paths_mod
    from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage

    archive = tmp_path / "loop-skill.skill"
    await asyncio.to_thread(_build_archive, archive)

    async def _allow_scan(content: str, *, executable: bool = False, location: str = "SKILL.md", app_config=None, static_findings=None):
        return SimpleNamespace(decision="allow", reason="anchor stub")

    monkeypatch.setattr("deerflow.skills.installer.scan_skill_content", _allow_scan)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths_mod, "_paths", None)

    # Constructor resolves per-user paths; offloaded so the only production
    # work on the loop is the install pipeline itself.
    storage = await asyncio.to_thread(UserScopedSkillStorage, "anchoruser", host_path=str(tmp_path / "skills"))

    result = await storage.ainstall_skill_from_archive(archive)

    assert result["success"] is True
    assert result["skill_name"] == "loop-skill"
    installed_md = tmp_path / "users" / "anchoruser" / "skills" / "custom" / "loop-skill" / "SKILL.md"
    assert await asyncio.to_thread(installed_md.is_file)
    installed_support = tmp_path / "users" / "anchoruser" / "skills" / "custom" / "loop-skill" / "references" / "usage.md"
    assert await asyncio.to_thread(installed_support.is_file)
