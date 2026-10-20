"""Packaging a skill must not read the output archive into itself."""

import runpy
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def package_script(monkeypatch):
    root = Path(__file__).resolve().parents[2] / "skills/public/skill-creator"
    monkeypatch.syspath_prepend(str(root))
    return runpy.run_path(str(root / "scripts/package_skill.py"))


@pytest.mark.parametrize("destination", ["root", "nested", "cwd", "aliased_cwd", "outside"])
def test_package_skips_its_own_archive(
    tmp_path, monkeypatch, package_script, destination
):
    skill = tmp_path / "example"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: example\ndescription: Example skill\n---\n# Example\n",
        encoding="utf-8",
    )
    # A different archive can be a legitimate resource and must not be omitted.
    (skill / "reference.skill").write_bytes(b"reference data")
    original_write = zipfile.ZipFile.write

    def guard_self_write(archive, filename, *args, **kwargs):
        # Fail safely before a broken implementation can grow its own output.
        assert Path(filename).resolve() != Path(archive.filename).resolve()
        return original_write(archive, filename, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "write", guard_self_write)
    output = {
        "root": skill,
        "nested": skill / "dist",
        "cwd": None,
        "aliased_cwd": None,
        "outside": tmp_path / "output",
    }[destination]
    if destination == "cwd":
        monkeypatch.chdir(skill)

    if destination == "aliased_cwd":
        # Model Windows cwd() retaining junction components without requiring
        # platform-specific symlink privileges in the test environment.
        alias = skill / "alias"
        alias.mkdir()
        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: alias / ".."))

    result = package_script["package_skill"](skill, output)

    assert result is not None
    with zipfile.ZipFile(result) as archive:
        assert set(archive.namelist()) == {
            "example/SKILL.md",
            "example/reference.skill",
        }
        assert archive.read("example/reference.skill") == b"reference data"
        assert archive.testzip() is None
