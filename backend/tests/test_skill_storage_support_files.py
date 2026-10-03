"""Support-file removal must work for binary members and reject directories.

``.skill`` archives may carry binary support files (``assets/logo.png``): the
installer only rejects executable binaries by magic bytes. The storage's
``remove_custom_skill_file`` read the file as UTF-8 text *before* unlinking
it, purely to hand the previous content to the history record, so a binary
member raised ``UnicodeDecodeError`` and was never removed, and a support
*directory* (which ``ensure_safe_support_path`` let through because a bare
``assets`` resolves to its own allowed root) raised ``IsADirectoryError``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from deerflow.skills.storage import get_or_new_skill_storage, reset_skill_storage
from deerflow.skills.storage.skill_storage import read_text_or_none

PNG_BYTES = b"\x89PNG\r\n\x1a\n\xff\xfe\x00"


@pytest.fixture(autouse=True)
def _reset_storages():
    reset_skill_storage()
    yield
    reset_skill_storage()


@pytest.fixture()
def storage(tmp_path: Path):
    return get_or_new_skill_storage(skills_path=str(tmp_path))


@pytest.fixture()
def skill_dir(tmp_path: Path, storage) -> Path:
    d = tmp_path / "custom" / "demo-skill"
    (d / "assets" / "nested").mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: demo-skill\ndescription: x\n---\nbody\n", encoding="utf-8")
    (d / "assets" / "logo.png").write_bytes(PNG_BYTES)
    (d / "assets" / "notes.md").write_text("notes", encoding="utf-8")
    (d / "assets" / "nested" / "inner.txt").write_text("inner", encoding="utf-8")
    return d


def test_remove_binary_support_file_removes_it_and_reports_no_text(storage, skill_dir):
    previous = storage.remove_custom_skill_file("demo-skill", "assets/logo.png")

    assert previous is None
    assert not (skill_dir / "assets" / "logo.png").exists()


def test_remove_text_support_file_still_returns_its_content(storage, skill_dir):
    previous = storage.remove_custom_skill_file("demo-skill", "assets/notes.md")

    assert previous == "notes"
    assert not (skill_dir / "assets" / "notes.md").exists()


@pytest.mark.parametrize("path", ["assets", "assets/", "assets/nested"], ids=["bare-subdir", "bare-subdir-slash", "nested-dir"])
def test_remove_rejects_a_directory_and_leaves_it_in_place(storage, skill_dir, path):
    with pytest.raises(ValueError, match="file"):
        storage.remove_custom_skill_file("demo-skill", path)

    assert (skill_dir / "assets" / "nested" / "inner.txt").read_text(encoding="utf-8") == "inner"
    assert (skill_dir / "assets" / "logo.png").read_bytes() == PNG_BYTES


def test_ensure_safe_support_path_requires_a_filename_below_the_subdir(storage, skill_dir):
    with pytest.raises(ValueError, match="file"):
        storage.ensure_safe_support_path("demo-skill", "assets")
    assert storage.ensure_safe_support_path("demo-skill", "assets/logo.png") == (skill_dir / "assets" / "logo.png").resolve()


@pytest.mark.parametrize("path", ["assets/CON", "assets/nul.txt", "assets/com¹.txt", "assets/LPT²", "assets/LPT³/icon.png", "assets/logo.png.", "assets/notes.md "])
def test_ensure_safe_support_path_rejects_windows_incompatible_names(storage, skill_dir, path):
    with pytest.raises(ValueError, match="not portable to Windows"):
        storage.ensure_safe_support_path("demo-skill", path)


def test_read_text_or_none_decodes_text_and_returns_none_for_binary(tmp_path: Path):
    text = tmp_path / "t.md"
    text.write_text("héllo", encoding="utf-8")
    binary = tmp_path / "b.png"
    binary.write_bytes(PNG_BYTES)

    assert read_text_or_none(text) == "héllo"
    assert read_text_or_none(binary) is None


def test_read_text_or_none_only_masks_undecodable_content(tmp_path: Path):
    """``None`` means "not text", never "could not read": IO errors still propagate."""
    with pytest.raises(FileNotFoundError):
        read_text_or_none(tmp_path / "missing.md")


def _windows_extended(path: Path) -> str:
    return (chr(92) * 2) + "?" + chr(92) + str(path)


def _write_literal(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        fd = os.open(_windows_extended(path), os.O_CREAT | os.O_WRONLY | getattr(os, "O_BINARY", 0))
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    else:
        path.write_bytes(data)


def test_remove_preexisting_nonportable_support_file(storage, skill_dir):
    """Deletion of a stored non-portable name succeeds; creating one still fails."""
    target = skill_dir / "scripts" / "AUX.py"
    _write_literal(target, b"print('aux')\n")
    with pytest.raises(ValueError, match="not portable to Windows"):
        storage.ensure_safe_support_path("demo-skill", "scripts/AUX.py")

    previous = storage.remove_custom_skill_file("demo-skill", "scripts/AUX.py")

    assert previous == "print('aux')\n"
    assert not target.exists()

    if os.name != "nt":
        dotted = skill_dir / "assets" / "logo.png."
        _write_literal(dotted, b"dot")
        with pytest.raises(ValueError, match="not portable to Windows"):
            storage.ensure_safe_support_path("demo-skill", "assets/logo.png.")
        removed = storage.remove_custom_skill_file("demo-skill", "assets/logo.png.")
        assert removed == "dot"
        assert not dotted.exists()
