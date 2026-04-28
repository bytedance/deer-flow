"""Shared skill archive installation logic.

Pure business logic — no FastAPI/HTTP dependencies.
Both Gateway and Client delegate to these functions.
"""

import logging
import posixpath
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from deerflow.skills.loader import get_skills_root_path
from deerflow.skills.validation import _validate_skill_frontmatter

logger = logging.getLogger(__name__)

MAX_ARCHIVE_SIZE_BYTES = 50 * 1024 * 1024
MAX_COMPRESSED_ARCHIVE_SIZE_BYTES = 25 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 500
MAX_ARCHIVE_MEMBER_SIZE_BYTES = 5 * 1024 * 1024
MAX_ARCHIVE_MEMBER_NAME_BYTES = 255
NESTED_ARCHIVE_EXTENSIONS = (".zip", ".skill", ".tar", ".tgz", ".gz", ".7z", ".rar")


class SkillAlreadyExistsError(ValueError):
    """Raised when a skill with the same name is already installed."""


def is_unsafe_zip_member(info: zipfile.ZipInfo) -> bool:
    """Return True if the zip member path is absolute or attempts directory traversal."""
    name = info.filename
    if not name:
        return False
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        return True
    path = PurePosixPath(normalized)
    if path.is_absolute():
        return True
    if PureWindowsPath(name).is_absolute():
        return True
    if ".." in path.parts:
        return True
    return False


def is_symlink_member(info: zipfile.ZipInfo) -> bool:
    """Detect symlinks based on the external attributes stored in the ZipInfo."""
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def has_control_characters(name: str) -> bool:
    """Return True if a zip member name contains NUL or control characters."""
    return any(ord(char) < 32 or ord(char) == 127 for char in name)


def has_too_long_path_component(name: str) -> bool:
    """Return True if any path component exceeds common filesystem name limits."""
    return any(len(part.encode("utf-8")) > MAX_ARCHIVE_MEMBER_NAME_BYTES for part in PurePosixPath(name).parts)


def is_nested_archive_member(info: zipfile.ZipInfo) -> bool:
    """Return True if the member is itself an archive payload."""
    if info.is_dir():
        return False
    normalized = posixpath.normpath(info.filename.replace("\\", "/")).rstrip("/")
    return normalized.lower().endswith(NESTED_ARCHIVE_EXTENSIONS)


def should_ignore_archive_entry(path: Path) -> bool:
    """Return True for macOS metadata dirs and dotfiles."""
    return path.name.startswith(".") or path.name == "__MACOSX"


def resolve_skill_dir_from_archive(temp_path: Path) -> Path:
    """Locate the skill root directory from extracted archive contents.

    Filters out macOS metadata (__MACOSX) and dotfiles (.DS_Store).

    Returns:
        Path to the skill directory.

    Raises:
        ValueError: If the archive is empty after filtering.
    """
    items = [p for p in temp_path.iterdir() if not should_ignore_archive_entry(p)]
    if not items:
        raise ValueError("Skill archive is empty")
    if len(items) == 1 and items[0].is_dir():
        return items[0]
    return temp_path


def safe_extract_skill_archive(
    zip_ref: zipfile.ZipFile,
    dest_path: Path,
    max_total_size: int = MAX_ARCHIVE_SIZE_BYTES,
    max_entries: int = MAX_ARCHIVE_ENTRIES,
    max_member_size: int = MAX_ARCHIVE_MEMBER_SIZE_BYTES,
) -> None:
    """Safely extract a skill archive with security protections.

    Protections:
    - Reject absolute paths and directory traversal (..).
    - Reject symlink entries instead of materialising them.
    - Enforce hard limits on entry count and uncompressed sizes.
    - Reject nested archives and unsafe member names.

    Raises:
        ValueError: If unsafe members or size limit exceeded.
    """
    dest_root = dest_path.resolve()
    total_written = 0
    infos = zip_ref.infolist()

    if len(infos) > max_entries:
        raise ValueError(f"Skill archive contains too many entries ({len(infos)} > {max_entries})")

    declared_size = sum(info.file_size for info in infos)
    if declared_size > max_total_size:
        raise ValueError("Skill archive is too large or appears highly compressed.")

    for info in infos:
        if is_unsafe_zip_member(info):
            raise ValueError(f"Archive contains unsafe member path: {info.filename!r}")

        if is_symlink_member(info):
            raise ValueError(f"Archive contains symlink member: {info.filename!r}")

        normalized_name = posixpath.normpath(info.filename.replace("\\", "/"))
        if normalized_name in {"", "."} or has_control_characters(info.filename):
            raise ValueError(f"Archive contains unsafe member name: {info.filename!r}")
        if has_too_long_path_component(normalized_name):
            raise ValueError(f"Archive member name is too long: {info.filename!r}")
        if is_nested_archive_member(info):
            raise ValueError(f"Archive contains nested archive member: {info.filename!r}")
        if info.file_size > max_member_size:
            raise ValueError(f"Archive member is too large: {info.filename!r}")

        member_path = dest_root.joinpath(*PurePosixPath(normalized_name).parts)
        if not member_path.resolve().is_relative_to(dest_root):
            raise ValueError(f"Zip entry escapes destination: {info.filename!r}")
        member_path.parent.mkdir(parents=True, exist_ok=True)

        if info.is_dir():
            member_path.mkdir(parents=True, exist_ok=True)
            continue

        with zip_ref.open(info) as src, member_path.open("wb") as dst:
            while chunk := src.read(65536):
                total_written += len(chunk)
                if total_written > max_total_size:
                    raise ValueError("Skill archive is too large or appears highly compressed.")
                dst.write(chunk)


def install_skill_from_archive(
    zip_path: str | Path,
    *,
    skills_root: Path | None = None,
) -> dict[str, bool | str]:
    """Install a skill from a .skill archive (ZIP).

    Args:
        zip_path: Path to the .skill file.
        skills_root: Override the skills root directory. If None, uses
            the default from config.

    Returns:
        Dict with success, skill_name, message.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is invalid (wrong extension, bad ZIP,
            invalid frontmatter, duplicate name).
    """
    logger.info("Installing skill from %s", zip_path)
    path = Path(zip_path)
    if not path.is_file():
        if not path.exists():
            raise FileNotFoundError(f"Skill file not found: {zip_path}")
        raise ValueError(f"Path is not a file: {zip_path}")
    if path.suffix != ".skill":
        raise ValueError("File must have .skill extension")
    if path.stat().st_size > MAX_COMPRESSED_ARCHIVE_SIZE_BYTES:
        raise ValueError("Skill archive file is too large.")

    if skills_root is None:
        skills_root = get_skills_root_path()
    custom_dir = skills_root / "custom"
    custom_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        try:
            zf = zipfile.ZipFile(path, "r")
        except FileNotFoundError:
            raise FileNotFoundError(f"Skill file not found: {zip_path}") from None
        except (zipfile.BadZipFile, IsADirectoryError):
            raise ValueError("File is not a valid ZIP archive") from None

        with zf:
            safe_extract_skill_archive(zf, tmp_path)

        skill_dir = resolve_skill_dir_from_archive(tmp_path)

        is_valid, message, skill_name = _validate_skill_frontmatter(skill_dir)
        if not is_valid:
            raise ValueError(f"Invalid skill: {message}")
        if not skill_name or "/" in skill_name or "\\" in skill_name or ".." in skill_name:
            raise ValueError(f"Invalid skill name: {skill_name}")

        target = custom_dir / skill_name
        if target.exists():
            raise SkillAlreadyExistsError(f"Skill '{skill_name}' already exists")

        shutil.copytree(skill_dir, target)
        logger.info("Skill %r installed to %s", skill_name, target)

    return {
        "success": True,
        "skill_name": skill_name,
        "message": f"Skill '{skill_name}' installed successfully",
    }
