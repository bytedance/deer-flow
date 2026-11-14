"""A skill name is a directory component, so creation rejects Windows device names."""

import asyncio
import zipfile
from pathlib import Path

import pytest

from deerflow.skills.storage.local_skill_storage import LocalSkillStorage
from deerflow.skills.storage.skill_storage import SkillStorage

RESERVED_DEVICE_NAMES = ["nul", "con", "prn", "aux", "com1", "com9", "lpt1", "lpt9"]


def _build_archive(tmp_path: Path, name: str) -> Path:
    archive = tmp_path / f"{name}.skill"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            f"{name}/SKILL.md",
            f"---\nname: {name}\ndescription: portability probe\n---\n\n# probe\n",
        )
        zf.writestr(f"{name}/references/note.md", "support file\n")
    return archive


class TestValidateSkillNameForCreation:
    @pytest.mark.parametrize("name", RESERVED_DEVICE_NAMES)
    def test_creation_rejects_windows_device_names(self, name):
        with pytest.raises(ValueError, match="not portable to Windows"):
            SkillStorage.validate_skill_name(name, for_creation=True)

    @pytest.mark.parametrize("name", RESERVED_DEVICE_NAMES)
    def test_reads_and_deletes_stay_permissive(self, name):
        # A skill an older release created on a Linux host must stay readable
        # and deletable; only creation refuses the name.
        assert SkillStorage.validate_skill_name(name) == name

    @pytest.mark.parametrize("name", ["my-skill", "skill2", "a-b-c"])
    def test_creation_still_accepts_ordinary_names(self, name):
        assert SkillStorage.validate_skill_name(name, for_creation=True) == name

    def test_creation_keeps_the_existing_shape_errors(self):
        with pytest.raises(ValueError, match="hyphen-case"):
            SkillStorage.validate_skill_name("Not Portable", for_creation=True)
        with pytest.raises(ValueError, match="64 characters"):
            SkillStorage.validate_skill_name("a" * 65, for_creation=True)


class TestArchiveInstallRejectsDeviceNames:
    @pytest.mark.parametrize("name", RESERVED_DEVICE_NAMES)
    def test_prepare_rejects_before_creating_the_target(self, tmp_path, name):
        storage = LocalSkillStorage(host_path=str(tmp_path / "skills"))
        archive = _build_archive(tmp_path, name)
        custom_dir = tmp_path / "skills" / "custom"
        custom_dir.mkdir(parents=True)

        with pytest.raises(ValueError, match="not portable to Windows"):
            storage._prepare_skill_archive(archive, tmp_path / "extract", custom_dir, archive)

        # ``nul`` resolves to the NUL device on Windows, so ``exists()`` is
        # true there even though nothing was created: assert on ``is_dir``.
        assert not (custom_dir / name).is_dir()

    @pytest.mark.parametrize("name", ["my-skill"])
    def test_prepare_accepts_an_ordinary_name(self, tmp_path, name):
        storage = LocalSkillStorage(host_path=str(tmp_path / "skills"))
        archive = _build_archive(tmp_path, name)
        custom_dir = tmp_path / "skills" / "custom"
        custom_dir.mkdir(parents=True)

        skill_dir, installed_name, target = storage._prepare_skill_archive(archive, tmp_path / "extract", custom_dir, archive)

        assert installed_name == name
        assert target == custom_dir / name
        assert (skill_dir / "SKILL.md").is_file()

    def test_install_from_archive_rejects_a_device_name(self, tmp_path, monkeypatch):
        async def _skip_scan(*_args, **_kwargs):
            return []

        monkeypatch.setattr("deerflow.skills.installer._scan_skill_archive_contents_or_raise", _skip_scan)
        storage = LocalSkillStorage(host_path=str(tmp_path / "skills"))
        archive = _build_archive(tmp_path, "nul")

        with pytest.raises(ValueError, match="not portable to Windows"):
            asyncio.run(storage.ainstall_skill_from_archive(archive))

        assert not (tmp_path / "skills" / "custom" / "nul").is_dir()

    def test_prepare_rejects_a_frontmatter_name_that_differs_from_the_folder(self, tmp_path):
        # The installed directory is named by the frontmatter, not by the
        # archive folder, so a portable folder name does not make the skill
        # name portable.
        storage = LocalSkillStorage(host_path=str(tmp_path / "skills"))
        archive = tmp_path / "device-name.skill"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("portable-folder/SKILL.md", "---\nname: nul\ndescription: probe\n---\n")
        custom_dir = tmp_path / "skills" / "custom"
        custom_dir.mkdir(parents=True)

        with pytest.raises(ValueError, match="not portable to Windows"):
            storage._prepare_skill_archive(archive, tmp_path / "extract", custom_dir, archive)

        assert not (custom_dir / "nul").is_dir()

    def test_prepare_rejects_a_device_named_member_segment(self, tmp_path):
        # Portable archive folder and portable frontmatter name: only a support
        # file's segment is unusable, so this pins the extraction guard itself
        # rather than the frontmatter name check.
        storage = LocalSkillStorage(host_path=str(tmp_path / "skills"))
        archive = tmp_path / "member-segment.skill"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("my-skill/SKILL.md", "---\nname: my-skill\ndescription: probe\n---\n")
            zf.writestr("my-skill/references/nul.md", "support file\n")
        custom_dir = tmp_path / "skills" / "custom"
        custom_dir.mkdir(parents=True)

        with pytest.raises(ValueError, match="Archive member path"):
            storage._prepare_skill_archive(archive, tmp_path / "extract", custom_dir, archive)

        assert not (custom_dir / "my-skill").is_dir()
