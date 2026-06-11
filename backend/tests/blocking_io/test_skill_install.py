"""Regression anchor: installing a skill must not block the event loop.

``LocalSkillStorage.ainstall_skill_from_archive`` probes the archive, creates a
tempdir, extracts the zip, and ``shutil.copytree``s the staged skill into place —
all blocking filesystem IO. The async method offloads each phase via
``asyncio.to_thread``; if any regresses back onto the event loop, the strict
Blockbuster gate raises ``BlockingError`` and this test fails.

The security scanner (``_scan_skill_archive_contents_or_raise``) is patched to a
no-op here: it has its own, separate ``rglob`` enumeration on the event loop
(out of scope for this anchor), which locks the extract/copytree offload
specifically.
"""

from __future__ import annotations

import asyncio
import tempfile
import zipfile
from pathlib import Path

import pytest

from deerflow.skills.storage.local_skill_storage import LocalSkillStorage

pytestmark = pytest.mark.asyncio


async def test_install_skill_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    # Test-side seeding (test-module stack → not gated): a minimal .skill zip.
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    archive = tmp_path / "demo.skill"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("demo/SKILL.md", "---\nname: demo\ndescription: regression anchor\n---\n# demo\n")

    # Isolate the extract/copytree offload under test: the security scanner has a
    # separate (unaddressed) blocking rglob that is out of scope for this anchor.
    async def _noop_scan(skill_dir: Path, skill_name: str) -> None:
        return None

    monkeypatch.setattr("deerflow.skills.installer._scan_skill_archive_contents_or_raise", _noop_scan)

    # LocalSkillStorage.__init__ resolves paths synchronously, so build it off-loop.
    storage = await asyncio.to_thread(LocalSkillStorage, host_path=str(skills_root))

    result = await storage.ainstall_skill_from_archive(str(archive))

    assert result["success"] is True
    assert result["skill_name"] == "demo"
    assert (skills_root / "custom" / "demo" / "SKILL.md").exists()


async def test_install_cleans_up_extraction_tempdir_on_failure(tmp_path: Path, monkeypatch) -> None:
    """A failure after extraction must still remove the extraction tempdir.

    The refactor manages the extraction dir manually (``mkdtemp`` + a ``finally``
    ``rmtree``) so it survives the ``await`` scan; this locks that it does not
    leak a temp directory when a later step raises.
    """
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    archive = tmp_path / "demo.skill"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("demo/SKILL.md", "---\nname: demo\ndescription: regression anchor\n---\n# demo\n")

    created: list[str] = []
    real_mkdtemp = tempfile.mkdtemp

    def _tracking_mkdtemp(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        created.append(path)
        return path

    async def _failing_scan(skill_dir: Path, skill_name: str) -> None:
        raise RuntimeError("scan boom")

    monkeypatch.setattr("tempfile.mkdtemp", _tracking_mkdtemp)
    monkeypatch.setattr("deerflow.skills.installer._scan_skill_archive_contents_or_raise", _failing_scan)

    storage = await asyncio.to_thread(LocalSkillStorage, host_path=str(skills_root))
    with pytest.raises(RuntimeError, match="scan boom"):
        await storage.ainstall_skill_from_archive(str(archive))

    assert created, "install should have created an extraction tempdir"
    assert not any(Path(d).exists() for d in created), "extraction tempdir leaked after failure"
