"""Shared skill archive installation logic.

Pure business logic — no FastAPI/HTTP dependencies.
Both Gateway and Client delegate to these functions.
"""

import asyncio
import concurrent.futures
import logging
import posixpath
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from deerflow.skills.permissions import make_skill_tree_sandbox_readable
from deerflow.skills.security_scanner import scan_skill_content

logger = logging.getLogger(__name__)

_PROMPT_INPUT_DIRS = {"references", "templates"}
_PROMPT_INPUT_SUFFIXES = frozenset({".json", ".markdown", ".md", ".rst", ".txt", ".yaml", ".yml"})
_CODE_SUFFIXES = frozenset({".bash", ".cjs", ".js", ".mjs", ".php", ".pl", ".ps1", ".py", ".rb", ".sh", ".ts", ".zsh"})
# Full magics per variant — a shorter shared prefix would also match
# non-executable data files.
_EXECUTABLE_MAGIC_PREFIXES = (
    b"\x7fELF",  # ELF
    b"MZ",  # PE/DOS
    b"\xfe\xed\xfa\xce",  # Mach-O 32-bit big-endian
    b"\xfe\xed\xfa\xcf",  # Mach-O 64-bit big-endian
    b"\xce\xfa\xed\xfe",  # Mach-O 32-bit little-endian
    b"\xcf\xfa\xed\xfe",  # Mach-O 64-bit little-endian
    b"\xca\xfe\xba\xbe",  # Mach-O fat binary big-endian
    b"\xbe\xba\xfe\xca",  # Mach-O fat binary little-endian
    b"\xca\xfe\xba\xbf",  # Mach-O fat64 binary big-endian
    b"\xbf\xba\xfe\xca",  # Mach-O fat64 binary little-endian
)


class SkillAlreadyExistsError(ValueError):
    """Raised when a skill with the same name is already installed."""


class SkillSecurityScanError(ValueError):
    """Raised when a skill archive fails security scanning."""


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


def is_executable_binary_prefix(prefix: bytes) -> bool:
    """Detect ELF, PE, and Mach-O executables by magic bytes."""
    return prefix.startswith(_EXECUTABLE_MAGIC_PREFIXES)


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
    max_total_size: int = 512 * 1024 * 1024,
) -> None:
    """Safely extract a skill archive with security protections.

    Protections:
    - Reject absolute paths and directory traversal (..).
    - Skip symlink entries instead of materialising them.
    - Enforce a hard limit on total uncompressed size (zip bomb defence).
    - Reject executable binaries (ELF/PE/Mach-O) by magic bytes.

    Raises:
        ValueError: If unsafe members, executable binaries, or size limit exceeded.
    """
    dest_root = dest_path.resolve()
    total_written = 0

    for info in zip_ref.infolist():
        if is_unsafe_zip_member(info):
            raise ValueError(f"Archive contains unsafe member path: {info.filename!r}")

        if is_symlink_member(info):
            logger.warning("Skipping symlink entry in skill archive: %s", info.filename)
            continue

        normalized_name = posixpath.normpath(info.filename.replace("\\", "/"))
        member_path = dest_root.joinpath(*PurePosixPath(normalized_name).parts)
        if not member_path.resolve().is_relative_to(dest_root):
            raise ValueError(f"Zip entry escapes destination: {info.filename!r}")
        member_path.parent.mkdir(parents=True, exist_ok=True)

        if info.is_dir():
            member_path.mkdir(parents=True, exist_ok=True)
            continue

        with zip_ref.open(info) as src, member_path.open("wb") as dst:
            first_chunk = True
            while chunk := src.read(65536):
                if first_chunk and is_executable_binary_prefix(chunk):
                    raise ValueError(f"Archive contains executable binary member: {info.filename!r}")
                first_chunk = False
                total_written += len(chunk)
                if total_written > max_total_size:
                    raise ValueError("Skill archive is too large or appears highly compressed.")
                dst.write(chunk)


def _is_script_support_file(rel_path: Path) -> bool:
    return bool(rel_path.parts) and rel_path.parts[0] == "scripts"


def _should_scan_support_file(rel_path: Path) -> bool:
    if _is_script_support_file(rel_path):
        return True
    return bool(rel_path.parts) and rel_path.parts[0] in _PROMPT_INPUT_DIRS and rel_path.suffix.lower() in _PROMPT_INPUT_SUFFIXES


def _has_shebang(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(2) == b"#!"
    except OSError:
        return False


def _is_code_file_by_name(rel_path: Path) -> bool:
    """Pure name-based code classification: scripts/ members and code suffixes."""
    if _is_script_support_file(rel_path):
        return True
    return rel_path.suffix.lower() in _CODE_SUFFIXES


async def _is_code_file(path: Path, rel_path: Path) -> bool:
    """Classify code files anywhere in the tree for the executable scan policy.

    Name checks are pure and stay on the event loop; only the shebang
    sniff for extensionless files reads the file and is offloaded.
    """
    if _is_code_file_by_name(rel_path):
        return True
    return not rel_path.suffix and await asyncio.to_thread(_has_shebang, path)


def _move_staged_skill_into_reserved_target(staging_target: Path, target: Path) -> None:
    installed = False
    reserved = False
    try:
        target.mkdir(mode=0o700)
        reserved = True
        for child in staging_target.iterdir():
            shutil.move(str(child), target / child.name)
        make_skill_tree_sandbox_readable(target)
        installed = True
    except FileExistsError as e:
        raise SkillAlreadyExistsError(f"Skill '{target.name}' already exists") from e
    finally:
        if reserved and not installed and target.exists():
            shutil.rmtree(target)


async def _scan_skill_file_or_raise(skill_dir: Path, path: Path, skill_name: str, *, executable: bool) -> None:
    rel_path = path.relative_to(skill_dir).as_posix()
    location = f"{skill_name}/{rel_path}"
    try:
        content = await asyncio.to_thread(path.read_text, encoding="utf-8")
    except UnicodeDecodeError as e:
        raise SkillSecurityScanError(f"Security scan failed for skill '{skill_name}': {location} must be valid UTF-8") from e

    try:
        result = await scan_skill_content(content, executable=executable, location=location)
    except Exception as e:
        raise SkillSecurityScanError(f"Security scan failed for {location}: {e}") from e

    decision = getattr(result, "decision", None)
    reason = str(getattr(result, "reason", "") or "No reason provided.")
    if decision == "block":
        if rel_path == "SKILL.md":
            raise SkillSecurityScanError(f"Security scan blocked skill '{skill_name}': {reason}")
        raise SkillSecurityScanError(f"Security scan blocked {location}: {reason}")
    if executable and decision != "allow":
        raise SkillSecurityScanError(f"Security scan rejected executable {location}: {reason}")
    if decision not in {"allow", "warn"}:
        raise SkillSecurityScanError(f"Security scan failed for {location}: invalid scanner decision {decision!r}")


def _collect_scannable_files(skill_dir: Path) -> list[Path]:
    """Enumerate archive files for scanning (blocking; run off the event loop)."""
    return [candidate for candidate in sorted(skill_dir.rglob("*")) if candidate.is_file()]


async def _scan_skill_archive_contents_or_raise(skill_dir: Path, skill_name: str) -> None:
    """Run the skill security scanner against all installable text and script files."""
    skill_md = skill_dir / "SKILL.md"
    await _scan_skill_file_or_raise(skill_dir, skill_md, skill_name, executable=False)

    for path in await asyncio.to_thread(_collect_scannable_files, skill_dir):
        rel_path = path.relative_to(skill_dir)
        if rel_path == Path("SKILL.md"):
            continue
        if path.name == "SKILL.md":
            raise SkillSecurityScanError(f"Security scan failed for skill '{skill_name}': nested SKILL.md is not allowed at {skill_name}/{rel_path.as_posix()}")
        if await _is_code_file(path, rel_path):
            await _scan_skill_file_or_raise(skill_dir, path, skill_name, executable=True)
        elif _should_scan_support_file(rel_path):
            await _scan_skill_file_or_raise(skill_dir, path, skill_name, executable=False)


def _run_async_install(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    return asyncio.run(coro)
