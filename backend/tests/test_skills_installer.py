"""Tests for deerflow.skills.installer — shared skill installation logic."""

import shutil
import stat
import zipfile
from pathlib import Path

import pytest

from deerflow.skills.installer import (
    SkillSecurityScanError,
    install_skill_from_archive,
    is_symlink_member,
    is_unsafe_zip_member,
    resolve_skill_dir_from_archive,
    safe_extract_skill_archive,
    should_ignore_archive_entry,
)
from deerflow.skills.security_scanner import ScanResult

# ---------------------------------------------------------------------------
# is_unsafe_zip_member
# ---------------------------------------------------------------------------


class TestIsUnsafeZipMember:
    def test_absolute_path(self):
        info = zipfile.ZipInfo("/etc/passwd")
        assert is_unsafe_zip_member(info) is True

    def test_windows_absolute_path(self):
        info = zipfile.ZipInfo("C:\\Windows\\system32\\drivers\\etc\\hosts")
        assert is_unsafe_zip_member(info) is True

    def test_dotdot_traversal(self):
        info = zipfile.ZipInfo("foo/../../../etc/passwd")
        assert is_unsafe_zip_member(info) is True

    def test_safe_member(self):
        info = zipfile.ZipInfo("my-skill/SKILL.md")
        assert is_unsafe_zip_member(info) is False

    def test_empty_filename(self):
        info = zipfile.ZipInfo("")
        assert is_unsafe_zip_member(info) is False


# ---------------------------------------------------------------------------
# is_symlink_member
# ---------------------------------------------------------------------------


class TestIsSymlinkMember:
    def test_detects_symlink(self):
        info = zipfile.ZipInfo("link.txt")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        assert is_symlink_member(info) is True

    def test_regular_file(self):
        info = zipfile.ZipInfo("file.txt")
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        assert is_symlink_member(info) is False


# ---------------------------------------------------------------------------
# should_ignore_archive_entry
# ---------------------------------------------------------------------------


class TestShouldIgnoreArchiveEntry:
    def test_macosx_ignored(self):
        assert should_ignore_archive_entry(Path("__MACOSX")) is True

    def test_dotfile_ignored(self):
        assert should_ignore_archive_entry(Path(".DS_Store")) is True

    def test_normal_dir_not_ignored(self):
        assert should_ignore_archive_entry(Path("my-skill")) is False


# ---------------------------------------------------------------------------
# resolve_skill_dir_from_archive
# ---------------------------------------------------------------------------


class TestResolveSkillDir:
    def test_single_dir(self, tmp_path):
        (tmp_path / "my-skill").mkdir()
        (tmp_path / "my-skill" / "SKILL.md").write_text("content")
        assert resolve_skill_dir_from_archive(tmp_path) == tmp_path / "my-skill"

    def test_with_macosx(self, tmp_path):
        (tmp_path / "my-skill").mkdir()
        (tmp_path / "my-skill" / "SKILL.md").write_text("content")
        (tmp_path / "__MACOSX").mkdir()
        assert resolve_skill_dir_from_archive(tmp_path) == tmp_path / "my-skill"

    def test_empty_after_filter(self, tmp_path):
        (tmp_path / "__MACOSX").mkdir()
        (tmp_path / ".DS_Store").write_text("meta")
        with pytest.raises(ValueError, match="empty"):
            resolve_skill_dir_from_archive(tmp_path)


# ---------------------------------------------------------------------------
# safe_extract_skill_archive
# ---------------------------------------------------------------------------


class TestSafeExtract:
    def _make_zip(self, tmp_path, members: dict[str, str | bytes]) -> Path:
        """Create a zip with given filename->content entries."""
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for name, content in members.items():
                if isinstance(content, str):
                    content = content.encode()
                zf.writestr(name, content)
        return zip_path

    def test_rejects_zip_bomb(self, tmp_path):
        zip_path = self._make_zip(tmp_path, {"big.txt": "x" * 1000})
        dest = tmp_path / "out"
        dest.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            with pytest.raises(ValueError, match="too large"):
                safe_extract_skill_archive(zf, dest, max_total_size=100)

    def test_rejects_absolute_path(self, tmp_path):
        zip_path = tmp_path / "abs.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("/etc/passwd", "root:x:0:0")
        dest = tmp_path / "out"
        dest.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            with pytest.raises(ValueError, match="unsafe"):
                safe_extract_skill_archive(zf, dest)

    def test_skips_symlinks(self, tmp_path):
        zip_path = tmp_path / "sym.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            info = zipfile.ZipInfo("link.txt")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
            zf.writestr("normal.txt", "hello")
        dest = tmp_path / "out"
        dest.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            safe_extract_skill_archive(zf, dest)
        assert (dest / "normal.txt").exists()
        assert not (dest / "link.txt").exists()

    def test_normal_archive(self, tmp_path):
        zip_path = self._make_zip(
            tmp_path,
            {
                "my-skill/SKILL.md": "---\nname: test\ndescription: x\n---\n# Test",
                "my-skill/README.md": "readme",
            },
        )
        dest = tmp_path / "out"
        dest.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            safe_extract_skill_archive(zf, dest)
        assert (dest / "my-skill" / "SKILL.md").exists()
        assert (dest / "my-skill" / "README.md").exists()


# ---------------------------------------------------------------------------
# install_skill_from_archive (full integration)
# ---------------------------------------------------------------------------


class TestInstallSkillFromArchive:
    @pytest.fixture(autouse=True)
    def _allow_security_scan(self, monkeypatch):
        async def _scan(*args, **kwargs):
            return ScanResult(decision="allow", reason="ok")

        monkeypatch.setattr("deerflow.skills.installer.scan_skill_content", _scan)

    def _make_skill_zip(self, tmp_path: Path, skill_name: str = "test-skill") -> Path:
        """Create a valid .skill archive."""
        zip_path = tmp_path / f"{skill_name}.skill"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(
                f"{skill_name}/SKILL.md",
                f"---\nname: {skill_name}\ndescription: A test skill\n---\n\n# {skill_name}\n",
            )
        return zip_path

    def test_success(self, tmp_path):
        zip_path = self._make_skill_zip(tmp_path)
        skills_root = tmp_path / "skills"
        skills_root.mkdir()
        result = install_skill_from_archive(zip_path, skills_root=skills_root)
        assert result["success"] is True
        assert result["skill_name"] == "test-skill"
        assert (skills_root / "custom" / "test-skill" / "SKILL.md").exists()

    def test_scans_skill_markdown_before_install(self, tmp_path, monkeypatch):
        zip_path = self._make_skill_zip(tmp_path)
        skills_root = tmp_path / "skills"
        skills_root.mkdir()
        calls = []

        async def _scan(content, *, executable, location):
            calls.append({"content": content, "executable": executable, "location": location})
            return ScanResult(decision="allow", reason="ok")

        monkeypatch.setattr("deerflow.skills.installer.scan_skill_content", _scan)

        install_skill_from_archive(zip_path, skills_root=skills_root)

        assert calls == [
            {
                "content": "---\nname: test-skill\ndescription: A test skill\n---\n\n# test-skill\n",
                "executable": False,
                "location": "test-skill/SKILL.md",
            }
        ]

    def test_scans_support_files_and_scripts_before_install(self, tmp_path, monkeypatch):
        zip_path = tmp_path / "test-skill.skill"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("test-skill/SKILL.md", "---\nname: test-skill\ndescription: A test skill\n---\n\n# test-skill\n")
            zf.writestr("test-skill/references/guide.md", "# Guide\n")
            zf.writestr("test-skill/templates/prompt.txt", "Use care.\n")
            zf.writestr("test-skill/scripts/run.sh", "#!/bin/sh\necho ok\n")
            zf.writestr("test-skill/assets/logo.png", b"\x89PNG\r\n\x1a\n")
            zf.writestr("test-skill/references/.env", "TOKEN=secret\n")
            zf.writestr("test-skill/templates/config.cfg", "TOKEN=secret\n")
        skills_root = tmp_path / "skills"
        skills_root.mkdir()
        calls = []

        async def _scan(content, *, executable, location):
            calls.append({"content": content, "executable": executable, "location": location})
            return ScanResult(decision="allow", reason="ok")

        monkeypatch.setattr("deerflow.skills.installer.scan_skill_content", _scan)

        install_skill_from_archive(zip_path, skills_root=skills_root)

        assert calls == [
            {
                "content": "---\nname: test-skill\ndescription: A test skill\n---\n\n# test-skill\n",
                "executable": False,
                "location": "test-skill/SKILL.md",
            },
            {
                "content": "# Guide\n",
                "executable": False,
                "location": "test-skill/references/guide.md",
            },
            {
                "content": "#!/bin/sh\necho ok\n",
                "executable": True,
                "location": "test-skill/scripts/run.sh",
            },
            {
                "content": "Use care.\n",
                "executable": False,
                "location": "test-skill/templates/prompt.txt",
            },
        ]
        assert all("secret" not in call["content"] for call in calls)

    def test_nested_skill_markdown_prevents_install(self, tmp_path):
        zip_path = tmp_path / "test-skill.skill"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("test-skill/SKILL.md", "---\nname: test-skill\ndescription: A test skill\n---\n\n# test-skill\n")
            zf.writestr("test-skill/references/other/SKILL.md", "# Nested skill\n")
        skills_root = tmp_path / "skills"
        skills_root.mkdir()

        with pytest.raises(SkillSecurityScanError, match="nested SKILL.md"):
            install_skill_from_archive(zip_path, skills_root=skills_root)

        assert not (skills_root / "custom" / "test-skill").exists()

    def test_script_warn_prevents_install(self, tmp_path, monkeypatch):
        zip_path = tmp_path / "test-skill.skill"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("test-skill/SKILL.md", "---\nname: test-skill\ndescription: A test skill\n---\n\n# test-skill\n")
            zf.writestr("test-skill/scripts/run.sh", "#!/bin/sh\necho ok\n")
        skills_root = tmp_path / "skills"
        skills_root.mkdir()

        async def _scan(*args, executable, **kwargs):
            if executable:
                return ScanResult(decision="warn", reason="script needs review")
            return ScanResult(decision="allow", reason="ok")

        monkeypatch.setattr("deerflow.skills.installer.scan_skill_content", _scan)

        with pytest.raises(SkillSecurityScanError, match="rejected executable.*script needs review"):
            install_skill_from_archive(zip_path, skills_root=skills_root)

        assert not (skills_root / "custom" / "test-skill").exists()

    def test_security_scan_block_prevents_install(self, tmp_path, monkeypatch):
        zip_path = self._make_skill_zip(tmp_path, skill_name="blocked-skill")
        skills_root = tmp_path / "skills"
        skills_root.mkdir()

        async def _scan(*args, **kwargs):
            return ScanResult(decision="block", reason="prompt injection")

        monkeypatch.setattr("deerflow.skills.installer.scan_skill_content", _scan)

        with pytest.raises(SkillSecurityScanError, match="Security scan blocked.*prompt injection"):
            install_skill_from_archive(zip_path, skills_root=skills_root)

        assert not (skills_root / "custom" / "blocked-skill").exists()

    def test_copy_failure_does_not_leave_partial_install(self, tmp_path, monkeypatch):
        zip_path = self._make_skill_zip(tmp_path)
        skills_root = tmp_path / "skills"
        skills_root.mkdir()

        def _copytree(src, dst):
            partial = Path(dst)
            partial.mkdir(parents=True)
            (partial / "partial.txt").write_text("partial", encoding="utf-8")
            raise OSError("copy failed")

        monkeypatch.setattr("deerflow.skills.installer.shutil.copytree", _copytree)

        with pytest.raises(OSError, match="copy failed"):
            install_skill_from_archive(zip_path, skills_root=skills_root)

        custom_dir = skills_root / "custom"
        assert not (custom_dir / "test-skill").exists()
        assert not [path for path in custom_dir.iterdir() if path.name.startswith(".installing-test-skill-")]

    def test_concurrent_target_creation_does_not_get_clobbered(self, tmp_path, monkeypatch):
        zip_path = self._make_skill_zip(tmp_path)
        skills_root = tmp_path / "skills"
        skills_root.mkdir()
        target = skills_root / "custom" / "test-skill"
        original_copytree = shutil.copytree

        def _copytree(src, dst):
            target.mkdir(parents=True)
            (target / "marker.txt").write_text("external", encoding="utf-8")
            return original_copytree(src, dst)

        monkeypatch.setattr("deerflow.skills.installer.shutil.copytree", _copytree)

        with pytest.raises(ValueError, match="already exists"):
            install_skill_from_archive(zip_path, skills_root=skills_root)

        assert (target / "marker.txt").read_text(encoding="utf-8") == "external"
        assert not (target / "SKILL.md").exists()

    def test_move_failure_cleans_reserved_target(self, tmp_path, monkeypatch):
        zip_path = self._make_skill_zip(tmp_path)
        skills_root = tmp_path / "skills"
        skills_root.mkdir()

        def _move(src, dst):
            Path(dst).write_text("partial", encoding="utf-8")
            raise OSError("move failed")

        monkeypatch.setattr("deerflow.skills.installer.shutil.move", _move)

        with pytest.raises(OSError, match="move failed"):
            install_skill_from_archive(zip_path, skills_root=skills_root)

        assert not (skills_root / "custom" / "test-skill").exists()

    def test_duplicate_raises(self, tmp_path):
        zip_path = self._make_skill_zip(tmp_path)
        skills_root = tmp_path / "skills"
        (skills_root / "custom" / "test-skill").mkdir(parents=True)
        with pytest.raises(ValueError, match="already exists"):
            install_skill_from_archive(zip_path, skills_root=skills_root)

    def test_invalid_extension(self, tmp_path):
        bad_path = tmp_path / "bad.zip"
        bad_path.write_text("not a skill")
        with pytest.raises(ValueError, match=".skill"):
            install_skill_from_archive(bad_path)

    def test_bad_frontmatter(self, tmp_path):
        zip_path = tmp_path / "bad.skill"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("bad/SKILL.md", "no frontmatter here")
        skills_root = tmp_path / "skills"
        skills_root.mkdir()
        with pytest.raises(ValueError, match="Invalid skill"):
            install_skill_from_archive(zip_path, skills_root=skills_root)

    def test_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            install_skill_from_archive(Path("/nonexistent/path.skill"))

    def test_macosx_filtered_during_resolve(self, tmp_path):
        """Archive with __MACOSX dir still installs correctly."""
        zip_path = tmp_path / "mac.skill"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("my-skill/SKILL.md", "---\nname: my-skill\ndescription: desc\n---\n# My Skill\n")
            zf.writestr("__MACOSX/._my-skill", "meta")
        skills_root = tmp_path / "skills"
        skills_root.mkdir()
        result = install_skill_from_archive(zip_path, skills_root=skills_root)
        assert result["success"] is True
        assert result["skill_name"] == "my-skill"
