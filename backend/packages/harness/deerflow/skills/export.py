"""Bounded custom-skill export; snapshots never activate or execute a skill."""

from __future__ import annotations

import codecs
import errno
import hashlib
import os
import re
import stat
import struct
import tempfile
import time
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import yaml

from deerflow.skills.frontmatter import _FRONTMATTER_RE, split_skill_markdown
from deerflow.skills.installer import is_executable_binary_prefix
from deerflow.skills.parser import parse_allowed_tools
from deerflow.skills.projection import skill_projection_read_lock
from deerflow.skills.validation import validate_skill_frontmatter_text

MAX_ENTRIES = 4096
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_ZIP_BYTES = 100 * 1024 * 1024
MAX_PATH_BYTES = 1024
MAX_DEPTH = 32
MAX_FRONTMATTER_BYTES = 1024 * 1024
MAX_YAML_EVENTS = 16384
MAX_YAML_DEPTH = 32
DEADLINE_SECONDS = 60.0
LOCK_TIMEOUT_SECONDS = 5.0
CHUNK_SIZE = 65536
_REVISION = re.compile(r"^[a-f0-9]{64}$")
_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)", re.IGNORECASE)
_SENSITIVE = {".env", ".npmrc", ".pypirc", ".netrc", ".git", ".svn", ".hg", "credentials.json", "id_rsa", "id_ed25519"}


class SkillExportError(Exception):
    """Safe public diagnostics, with no host paths or source text."""

    def __init__(self, status: int, code: str, message: str, path: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.path = path


@dataclass
class SkillExportArchive:
    file: BinaryIO
    size: int

    def close(self):
        self.file.close()


@dataclass(frozen=True)
class _Entry:
    path: str
    type: str
    size: int
    executable: bool
    digest: bytes = b""
    offset: int = 0
    identity: tuple = ()


class _Budget:
    def __init__(self, cancel_event):
        self.deadline = time.monotonic() + DEADLINE_SECONDS
        self.cancel_event = cancel_event

    def check(self):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise SkillExportError(503, "skill_export_cancelled", "Skill export was cancelled.")
        if time.monotonic() >= self.deadline:
            raise SkillExportError(503, "skill_export_timeout", "Skill export timed out.")


def _limit():
    raise SkillExportError(413, "skill_export_limit_exceeded", "Skill exceeds an export resource limit.")


def _changed():
    raise SkillExportError(409, "skill_changed", "Skill changed; refresh the file manifest.")


def _issue(code, message, path=None):
    result = {"code": code, "message": message}
    if path is not None:
        # Invalid filenames may contain control chars; never echo those diagnostics.
        result["path"] = "".join(c if c.isprintable() else "\ufffd" for c in path)[:1024]
    return result


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _link(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _invalid_path(path):
    return any(p in ("", ".", "..") or p.endswith((" ", ".")) or _RESERVED.match(p) or any(unicodedata.category(c) == "Cc" or c in '\\<>:"|?*' for c in p) for p in path.split("/"))


def _walk(root_fd, root_stat, snapshot, budget, skill_name):
    entries = [_Entry("", "directory", 0, False, identity=_identity(root_stat))]
    blockers = []
    warnings = []
    folded = set()
    total = 0
    visited = 1

    def visit(directory_fd, parent):
        nonlocal total, visited
        budget.check()
        # scandir iterator prevents allocating an unbounded directory listing.
        children = []
        with os.scandir(directory_fd) as iterator:
            for child in iterator:
                budget.check()
                if visited + len(children) >= MAX_ENTRIES:
                    _limit()
                children.append(child.name)
        for name in sorted(children, key=lambda s: s.encode("utf-8", "surrogatepass")):
            budget.check()
            visited += 1
            if visited > MAX_ENTRIES:
                _limit()
            path = parent + "/" + name if parent else name
            try:
                encoded = path.encode("utf-8")
            except UnicodeEncodeError:
                blockers.append(_issue("skill_export_invalid_path", "Path is not valid Unicode.", path))
                continue
            if len(skill_name.encode("utf-8")) + 1 + len(encoded) > MAX_PATH_BYTES or len(path.split("/")) > MAX_DEPTH:
                _limit()
            if len(entries) >= MAX_ENTRIES:
                _limit()
            key = unicodedata.normalize("NFC", path).casefold()
            if _invalid_path(path) or key in folded:
                blockers.append(_issue("skill_export_invalid_path", "Path is not portable or conflicts with another path.", path))
            folded.add(key)
            lower = name.casefold()
            if lower in _SENSITIVE or lower.startswith(".env."):
                warnings.append(_issue("skill_export_sensitive_filename", "This filename may contain local credentials or repository metadata; review it before sharing.", path))
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            identity = _identity(info)
            if _link(info):
                blockers.append(_issue("skill_export_link", "Linked files or directories cannot be exported.", path))
                entries.append(_Entry(path, "file", 0, False, identity=identity))
                continue
            if stat.S_ISDIR(info.st_mode):
                if len(skill_name.encode("utf-8")) + 2 + len(encoded) > MAX_PATH_BYTES:
                    _limit()
                entries.append(_Entry(path, "directory", 0, False, identity=identity))
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                try:
                    if _identity(os.fstat(fd)) != identity:
                        _changed()
                    visit(fd, path)
                    if _identity(os.fstat(fd)) != identity:
                        _changed()
                finally:
                    os.close(fd)
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                blockers.append(_issue("skill_export_unsupported_node", "Only regular files with one link are supported.", path))
                entries.append(_Entry(path, "file", 0, False, identity=identity))
                continue
            if info.st_size > MAX_FILE_BYTES or total + info.st_size > MAX_TOTAL_BYTES:
                _limit()
            if name == "SKILL.md" and parent:
                blockers.append(_issue("skill_export_nested_skill", "Nested SKILL.md files are not accepted by the installer.", path))
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
            try:
                if _identity(os.fstat(fd)) != identity:
                    _changed()
                digest = hashlib.sha256()
                length = 0
                decoder = codecs.getincrementaldecoder("utf-8")() if path == "SKILL.md" else None
                offset = snapshot.tell() if snapshot is not None else 0
                while True:
                    budget.check()
                    chunk = os.read(fd, CHUNK_SIZE)
                    if not chunk:
                        break
                    if length == 0 and is_executable_binary_prefix(chunk):
                        blockers.append(_issue("skill_export_executable_binary", "Executable binary files are not accepted by the installer.", path))
                    if decoder is not None:
                        try:
                            decoder.decode(chunk, final=False)
                        except UnicodeError:
                            blockers.append(_issue("skill_export_invalid_frontmatter", "SKILL.md must be valid UTF-8.", path))
                            decoder = None
                    length += len(chunk)
                    total += len(chunk)
                    if length > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                        _limit()
                    digest.update(chunk)
                    if snapshot is not None:
                        snapshot.write(chunk)
                if decoder is not None:
                    try:
                        decoder.decode(b"", final=True)
                    except UnicodeError:
                        blockers.append(_issue("skill_export_invalid_frontmatter", "SKILL.md must be valid UTF-8.", path))
                if length != info.st_size or _identity(os.fstat(fd)) != identity:
                    _changed()
                entries.append(_Entry(path, "file", length, bool(info.st_mode & 0o111), digest.digest(), offset, identity))
            finally:
                os.close(fd)

    visit(root_fd, "")
    if _identity(os.fstat(root_fd)) != _identity(root_stat):
        _changed()
    return sorted(entries, key=lambda e: e.path.encode("utf-8", "surrogatepass")), blockers, warnings


def _revision(name, entries):
    digest = hashlib.sha256()

    def field(value):
        digest.update(struct.pack(">Q", len(value)))
        digest.update(value)

    field(b"deerflow-skill-export-v1")
    field(name.encode("utf-8"))
    for entry in entries:
        for value in (entry.path.encode("utf-8"), entry.type.encode("ascii"), str(entry.size).encode("ascii"), entry.digest, b"1" if entry.executable else b"0"):
            field(value)
    return digest.hexdigest()


class _UnsupportedFrontmatter(ValueError):
    """Contains only constant public explanations, never parser exceptions."""

    def __init__(self, message, code="skill_export_yaml_complexity"):
        super().__init__(message)
        self.code = code


def _guard_frontmatter(source, budget):
    """Inspect events without constructing aliases or expanding YAML merge keys."""
    budget.check()
    depth = 0
    events = yaml.parse(source, Loader=yaml.SafeLoader)
    try:
        for count, event in enumerate(events, start=1):
            budget.check()
            if count > MAX_YAML_EVENTS:
                raise _UnsupportedFrontmatter("YAML frontmatter exceeds the supported structural complexity.")
            if isinstance(event, yaml.events.AliasEvent):
                raise _UnsupportedFrontmatter("YAML aliases are not supported for skill export.", "skill_export_yaml_alias")
            if isinstance(event, (yaml.events.MappingStartEvent, yaml.events.SequenceStartEvent)):
                depth += 1
                if depth > MAX_YAML_DEPTH:
                    raise _UnsupportedFrontmatter("YAML frontmatter exceeds the supported nesting depth.")
            elif isinstance(event, (yaml.events.MappingEndEvent, yaml.events.SequenceEndEvent)):
                depth -= 1
    finally:
        events.close()
    budget.check()


def _manifest(name, entries, blockers, warnings, snapshot, budget):
    if _invalid_path(name):
        blockers.append(_issue("skill_export_invalid_path", "Skill root name is not portable.", "."))
    requirements = {"compatibility": None, "allowed_tools": None, "required_secrets": None}
    skill = next((entry for entry in entries if entry.path == "SKILL.md" and entry.type == "file" and entry.digest), None)
    if skill is None:
        blockers.append(_issue("skill_export_invalid_frontmatter", "A regular root SKILL.md is required.", "SKILL.md"))
    else:
        snapshot.seek(skill.offset)
        try:
            prefix = snapshot.read(min(skill.size, MAX_FRONTMATTER_BYTES + 1))
            content = codecs.getincrementaldecoder("utf-8")().decode(prefix, final=skill.size <= len(prefix))
            match = _FRONTMATTER_RE.match(content)
            if len(prefix) > MAX_FRONTMATTER_BYTES and (match is None or len(match.group(1).encode("utf-8")) > MAX_FRONTMATTER_BYTES):
                _limit()
            # Validation only uses frontmatter; a large body stays in the raw snapshot.
            if match is not None:
                content = content[: match.end()]
                _guard_frontmatter(match.group(1), budget)
            valid, _, declared_name = validate_skill_frontmatter_text(content)
            if not valid or declared_name != name:
                blockers.append(_issue("skill_export_invalid_frontmatter", "SKILL.md frontmatter must be valid and its name must match the directory.", "SKILL.md"))
            else:
                parts, _ = split_skill_markdown(content)
                metadata = parts.metadata
                compatibility = metadata.get("compatibility")
                requirements["compatibility"] = compatibility if isinstance(compatibility, str) else None
                tools = metadata.get("allowed-tools")
                requirements["allowed_tools"] = list(parse_allowed_tools(tools, Path("SKILL.md"))) if tools is not None else None
                secrets = metadata.get("required-secrets")
                if secrets is not None:
                    requirements["required_secrets"] = []
                    seen = set()
                    for secret in secrets:
                        if isinstance(secret, str):
                            secret = {"name": secret, "optional": False}
                        if isinstance(secret, dict):
                            raw_name = secret.get("name")
                            secret_name = raw_name.strip() if isinstance(raw_name, str) else ""
                            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", secret_name) and secret_name not in seen:
                                seen.add(secret_name)
                                requirements["required_secrets"].append({"name": secret_name, "optional": bool(secret.get("optional", False))})
                            elif not secret_name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", secret_name):
                                warnings.append(_issue("skill_export_invalid_declaration", "A malformed required-secrets declaration was omitted; inspect SKILL.md.", "SKILL.md"))
                        else:
                            warnings.append(_issue("skill_export_invalid_declaration", "A malformed required-secrets declaration was omitted; inspect SKILL.md.", "SKILL.md"))
                if any(key in metadata for key in ("required-secrets", "secrets-autonomous", "allowed-tools")):
                    warnings.append(_issue("skill_export_platform_declarations", "Declared tools and secrets require configuration in the target environment.", "SKILL.md"))
        except _UnsupportedFrontmatter as error:
            blockers.append(_issue(error.code, str(error), "SKILL.md"))
        except (UnicodeError, ValueError, TypeError, RecursionError, yaml.YAMLError):
            blockers.append(_issue("skill_export_invalid_frontmatter", "SKILL.md frontmatter is not supported.", "SKILL.md"))
    return {
        "skill_name": name,
        "revision": None if blockers else _revision(name, entries),
        "can_export": not blockers,
        "file_count": sum(e.type == "file" for e in entries),
        "directory_count": sum(e.type == "directory" for e in entries),
        "total_bytes": sum(e.size for e in entries),
        "files": [{"path": e.path or ".", "type": e.type, "size": e.size, "executable": e.executable} for e in entries],
        "requirements": requirements,
        "warnings": warnings,
        "blockers": blockers,
    }


class _LinkedDirectory(Exception):
    pass


def _open_directory_chain(path, budget):
    """Anchor every component, including custom-root ancestors, without following links."""
    path = path.absolute()
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:]:
            budget.check()
            info = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
            if _link(info):
                raise _LinkedDirectory()
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            if _identity(os.fstat(descriptor)) != _identity(info):
                _changed()
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _capture(storage, name, snapshot, budget):
    if not isinstance(name, str) or len(name) > 64 or not _NAME.fullmatch(name):
        raise SkillExportError(422, "skill_export_unsupported", "Invalid skill name.")
    root = storage.get_custom_skill_dir(name)
    budget.check()
    try:
        with skill_projection_read_lock(storage, timeout=LOCK_TIMEOUT_SECONDS, check=budget.check):
            if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd or os.scandir not in os.supports_fd:
                raise SkillExportError(422, "skill_export_unsupported", "This platform cannot safely capture skill files.")
            parent_fd = _open_directory_chain(root.parent, budget)
            try:
                info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if _link(info):
                    return [], [_issue("skill_export_link", "Linked skill directories cannot be exported.")], []
                if not stat.S_ISDIR(info.st_mode):
                    return [], [_issue("skill_export_unsupported_node", "Skill root must be a directory.")], []
                root_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                try:
                    if _identity(os.fstat(root_fd)) != _identity(info):
                        _changed()
                    entries, blockers, warnings = _walk(root_fd, info, snapshot, budget, name)
                    checked, checked_blockers, _ = _walk(root_fd, info, None, budget, name)
                    if [(e.path, e.identity, e.digest) for e in entries] != [(e.path, e.identity, e.digest) for e in checked] or checked_blockers != blockers:
                        _changed()
                    if _identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False)) != _identity(info):
                        _changed()
                    if _identity(root.parent.lstat()) != _identity(os.fstat(parent_fd)):
                        _changed()
                    return entries, blockers, warnings
                finally:
                    os.close(root_fd)
            finally:
                os.close(parent_fd)
    except _LinkedDirectory:
        return [], [_issue("skill_export_link", "Linked skill directories cannot be exported.")], []
    except FileNotFoundError:
        if not root.exists():
            raise SkillExportError(404, "skill_not_found", "Custom skill not found.") from None
        _changed()
    except TimeoutError:
        raise SkillExportError(503, "skill_export_timeout", "Skill export lock timed out.") from None
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            _changed()
        raise SkillExportError(500, "skill_export_failed", "Unable to read skill files.") from None


class _LimitedWriter:
    def __init__(self, file, budget):
        self.file = file
        self.budget = budget

    def write(self, data):
        self.budget.check()
        if self.file.tell() + len(data) > MAX_ZIP_BYTES:
            _limit()
        return self.file.write(data)

    def __getattr__(self, name):
        return getattr(self.file, name)


def export_manifest(storage, skill_name, cancel_event=None):
    budget = _Budget(cancel_event)
    with tempfile.TemporaryFile("w+b") as snapshot:
        entries, blockers, warnings = _capture(storage, skill_name, snapshot, budget)
        result = _manifest(skill_name, entries, blockers, warnings, snapshot, budget)
        budget.check()
        return result


def build_skill_export(storage, skill_name, expected_revision, cancel_event=None):
    if not isinstance(expected_revision, str) or not _REVISION.fullmatch(expected_revision):
        raise SkillExportError(422, "skill_export_unsupported", "A valid expected revision is required.")
    budget = _Budget(cancel_event)
    with tempfile.TemporaryFile("w+b") as snapshot:
        entries, blockers, warnings = _capture(storage, skill_name, snapshot, budget)
        manifest = _manifest(skill_name, entries, blockers, warnings, snapshot, budget)
        if blockers:
            raise SkillExportError(422, "skill_export_unsupported", "Skill contains unsupported files or structure.", blockers[0].get("path"))
        if manifest["revision"] != expected_revision:
            _changed()
        output = tempfile.TemporaryFile("w+b")
        try:
            with zipfile.ZipFile(_LimitedWriter(output, budget), "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for entry in entries:
                    budget.check()
                    name = skill_name + "/" + entry.path
                    directory = entry.type == "directory"
                    if directory and not name.endswith("/"):
                        name += "/"
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    info.compress_type = zipfile.ZIP_DEFLATED
                    mode = (stat.S_IFDIR | 0o755) if directory else (stat.S_IFREG | (0o755 if entry.executable else 0o644))
                    info.external_attr = (mode << 16) | (0x10 if directory else 0)
                    with archive.open(info, "w") as target:
                        snapshot.seek(entry.offset)
                        remaining = entry.size
                        while remaining:
                            budget.check()
                            chunk = snapshot.read(min(CHUNK_SIZE, remaining))
                            if not chunk:
                                raise SkillExportError(500, "skill_export_failed", "Unable to build skill archive.")
                            target.write(chunk)
                            remaining -= len(chunk)
            size = output.tell()
            if size > MAX_ZIP_BYTES:
                _limit()
            budget.check()
            output.seek(0)
            return SkillExportArchive(output, size)
        except BaseException:
            output.close()
            raise
