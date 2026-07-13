"""Read-only package readers for skill review snapshots."""

from __future__ import annotations

import hashlib
import os
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from deerflow.skills.review.models import (
    DEFAULT_PACKAGE_LIMITS,
    PACKAGE_SNAPSHOT_SCHEMA_VERSION,
    PackageLimits,
    normalize_relative_path,
)

_TEXT_EXTENSIONS = {
    ".css",
    ".csv",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".svg",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}
_ZIP_READ_CHUNK_BYTES = 1024 * 1024


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decode_text(data: bytes, path: str) -> str | None:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix not in _TEXT_EXTENSIONS and b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _truncate_utf8_bytes(content: str, max_bytes: int) -> tuple[str, bytes]:
    data = content.encode("utf-8")
    truncated = data[:max_bytes]
    text = truncated.decode("utf-8", errors="ignore")
    return text, text.encode("utf-8")


def _subject(
    *,
    source: str,
    display_ref: str,
    name_hint: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "category": category,
        "name_hint": name_hint,
        "display_ref": display_ref,
    }


def _empty_snapshot(subject: dict[str, Any], limits: PackageLimits) -> dict[str, Any]:
    return {
        "schema_version": PACKAGE_SNAPSHOT_SCHEMA_VERSION,
        "subject": subject,
        "limits": limits.to_dict(),
        "files": [],
        "truncated": False,
        "reader_errors": [],
    }


def build_inline_snapshot(
    content: str,
    *,
    name_hint: str | None = None,
    limits: PackageLimits = DEFAULT_PACKAGE_LIMITS,
) -> dict[str, Any]:
    data = content.encode("utf-8")
    snapshot = _empty_snapshot(
        _subject(source="inline", display_ref=name_hint or "inline://SKILL.md", name_hint=name_hint),
        limits,
    )
    if len(data) > limits.max_file_bytes:
        snapshot["truncated"] = True
        snapshot["reader_errors"].append(
            {
                "code": "file_too_large",
                "path": "SKILL.md",
                "message": "Inline SKILL.md exceeds the per-file review limit",
            }
        )
        content, data = _truncate_utf8_bytes(content, limits.max_file_bytes)

    snapshot["files"].append(
        {
            "path": "SKILL.md",
            "kind": "text",
            "size": len(data),
            "sha256": _sha256(data),
            "content": content,
        }
    )
    return snapshot


class LocalDirectoryReader:
    """Read a local skill directory without following symlink escapes."""

    def __init__(
        self,
        root: str | Path,
        *,
        subject: dict[str, Any] | None = None,
        limits: PackageLimits = DEFAULT_PACKAGE_LIMITS,
    ) -> None:
        self.root = Path(root)
        self.limits = limits
        self.subject = subject or _subject(
            source="local_directory",
            display_ref=self.root.name or str(self.root),
            name_hint=self.root.name or None,
        )

    def read(self) -> dict[str, Any]:
        root = self.root
        snapshot = _empty_snapshot(self.subject, self.limits)
        if not root.exists():
            snapshot["reader_errors"].append({"code": "root_not_found", "path": None, "message": "Package root does not exist"})
            return snapshot
        if not root.is_dir():
            snapshot["reader_errors"].append({"code": "root_not_directory", "path": None, "message": "Package root is not a directory"})
            return snapshot

        root_resolved = root.resolve()
        total_bytes = 0
        file_count = 0

        for current_root, dir_names, file_names in os.walk(root_resolved, followlinks=False):
            current = Path(current_root)
            dir_names[:] = sorted(dir_names)
            file_names = sorted(file_names)

            for dirname in list(dir_names):
                path = current / dirname
                if not path.is_symlink():
                    continue
                dir_names.remove(dirname)
                file_count = self._append_symlink(snapshot, path, root_resolved, file_count)

            for filename in file_names:
                path = current / filename
                if path.is_symlink():
                    file_count = self._append_symlink(snapshot, path, root_resolved, file_count)
                    continue

                rel_path = self._relative(path, root_resolved, snapshot)
                if rel_path is None:
                    continue
                file_count += 1
                if file_count > self.limits.max_files:
                    snapshot["truncated"] = True
                    snapshot["reader_errors"].append({"code": "too_many_files", "path": None, "message": "Package file count exceeds the review limit"})
                    return self._sort_snapshot(snapshot)

                try:
                    size = path.stat().st_size
                except OSError as exc:
                    snapshot["reader_errors"].append({"code": "stat_failed", "path": rel_path, "message": str(exc)})
                    continue

                total_bytes += max(size, 0)
                if total_bytes > self.limits.max_total_bytes:
                    snapshot["truncated"] = True
                    snapshot["reader_errors"].append({"code": "total_size_exceeded", "path": rel_path, "message": "Package total size exceeds the review limit"})
                    return self._sort_snapshot(snapshot)

                if size > self.limits.max_file_bytes:
                    snapshot["truncated"] = True
                    snapshot["files"].append({"path": rel_path, "kind": "binary", "size": size, "sha256": "", "content": None})
                    snapshot["reader_errors"].append({"code": "file_too_large", "path": rel_path, "message": "File exceeds the per-file review limit"})
                    continue

                try:
                    data = path.read_bytes()
                except OSError as exc:
                    snapshot["reader_errors"].append({"code": "read_failed", "path": rel_path, "message": str(exc)})
                    continue

                text = _decode_text(data, rel_path)
                entry: dict[str, Any] = {
                    "path": rel_path,
                    "kind": "text" if text is not None else "binary",
                    "size": len(data),
                    "sha256": _sha256(data),
                }
                if text is not None:
                    entry["content"] = text
                snapshot["files"].append(entry)

        return self._sort_snapshot(snapshot)

    def _append_symlink(self, snapshot: dict[str, Any], path: Path, root: Path, file_count: int) -> int:
        rel_path = self._relative(path, root, snapshot)
        if rel_path is None:
            return file_count
        file_count += 1
        if file_count > self.limits.max_files:
            snapshot["truncated"] = True
            snapshot["reader_errors"].append({"code": "too_many_files", "path": None, "message": "Package file count exceeds the review limit"})
            return file_count
        try:
            target = os.readlink(path)
        except OSError:
            target = ""
        snapshot["files"].append(
            {
                "path": rel_path,
                "kind": "symlink",
                "size": 0,
                "sha256": _sha256(target.encode("utf-8")),
                "target": target,
            }
        )
        return file_count

    @staticmethod
    def _relative(path: Path, root: Path, snapshot: dict[str, Any]) -> str | None:
        try:
            rel = path.relative_to(root).as_posix()
            return normalize_relative_path(rel)
        except ValueError:
            snapshot["reader_errors"].append({"code": "path_escaped", "path": None, "message": "Package entry escapes the root"})
            return None

    @staticmethod
    def _sort_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
        snapshot["files"] = sorted(snapshot["files"], key=lambda item: item["path"])
        snapshot["reader_errors"] = sorted(snapshot["reader_errors"], key=lambda item: (str(item.get("path") or ""), str(item.get("code") or "")))
        return snapshot


class ArchivePackageReader:
    """Inspect a .skill ZIP archive without installing it."""

    def __init__(
        self,
        archive_path: str | Path,
        *,
        limits: PackageLimits = DEFAULT_PACKAGE_LIMITS,
    ) -> None:
        self.archive_path = Path(archive_path)
        self.limits = limits

    def read(self) -> dict[str, Any]:
        snapshot = _empty_snapshot(
            _subject(source="archive", display_ref=str(self.archive_path.name), name_hint=self.archive_path.stem),
            self.limits,
        )
        try:
            with zipfile.ZipFile(self.archive_path, "r") as zf:
                total_bytes = 0
                members = sorted(zf.infolist(), key=lambda info: info.filename)
                if len(members) > self.limits.max_files:
                    snapshot["truncated"] = True
                    snapshot["reader_errors"].append({"code": "too_many_files", "path": None, "message": "Archive member count exceeds the review limit"})
                    members = members[: self.limits.max_files]
                for info in members:
                    if info.is_dir():
                        continue
                    rel_path = self._normalize_archive_name(info.filename, snapshot)
                    if rel_path is None:
                        continue

                    declared_size = max(info.file_size, 0)
                    if declared_size > self.limits.max_file_bytes:
                        snapshot["truncated"] = True
                        snapshot["files"].append({"path": rel_path, "kind": "binary", "size": declared_size, "sha256": "", "content": None})
                        snapshot["reader_errors"].append({"code": "file_too_large", "path": rel_path, "message": "Archive member exceeds the per-file review limit"})
                        continue

                    remaining_total_bytes = self.limits.max_total_bytes - total_bytes
                    if remaining_total_bytes <= 0:
                        snapshot["truncated"] = True
                        snapshot["reader_errors"].append({"code": "total_size_exceeded", "path": rel_path, "message": "Archive total size exceeds the review limit"})
                        break

                    member_budget = min(self.limits.max_file_bytes, remaining_total_bytes)
                    try:
                        data, actual_size, limit_exceeded = _read_zip_member_bounded(zf, info, max_bytes=member_budget)
                    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                        snapshot["reader_errors"].append({"code": "archive_member_read_failed", "path": rel_path, "message": str(exc)})
                        continue

                    if limit_exceeded:
                        snapshot["truncated"] = True
                        if actual_size > self.limits.max_file_bytes:
                            snapshot["files"].append({"path": rel_path, "kind": "binary", "size": actual_size, "sha256": "", "content": None})
                            snapshot["reader_errors"].append({"code": "file_too_large", "path": rel_path, "message": "Archive member exceeds the per-file review limit"})
                            continue
                        snapshot["reader_errors"].append({"code": "total_size_exceeded", "path": rel_path, "message": "Archive total size exceeds the review limit"})
                        break

                    total_bytes += actual_size
                    if _zip_member_is_symlink(info):
                        target = data.decode("utf-8", errors="replace")
                        snapshot["files"].append({"path": rel_path, "kind": "symlink", "size": 0, "sha256": _sha256(data), "target": target})
                        continue
                    text = _decode_text(data, rel_path)
                    entry: dict[str, Any] = {
                        "path": rel_path,
                        "kind": "text" if text is not None else "binary",
                        "size": actual_size,
                        "sha256": _sha256(data),
                    }
                    if text is not None:
                        entry["content"] = text
                    snapshot["files"].append(entry)
        except (OSError, zipfile.BadZipFile) as exc:
            snapshot["reader_errors"].append({"code": "archive_read_failed", "path": None, "message": str(exc)})

        snapshot["files"] = sorted(snapshot["files"], key=lambda item: item["path"])
        snapshot["reader_errors"] = sorted(snapshot["reader_errors"], key=lambda item: (str(item.get("path") or ""), str(item.get("code") or "")))
        return snapshot

    @staticmethod
    def _normalize_archive_name(filename: str, snapshot: dict[str, Any]) -> str | None:
        try:
            return normalize_relative_path(filename)
        except ValueError as exc:
            snapshot["reader_errors"].append({"code": "invalid_archive_path", "path": filename, "message": str(exc)})
            return None


def _zip_member_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def _read_zip_member_bounded(zf: zipfile.ZipFile, info: zipfile.ZipInfo, *, max_bytes: int) -> tuple[bytes, int, bool]:
    chunks: list[bytes] = []
    actual_size = 0
    with zf.open(info) as member:
        while True:
            read_size = min(_ZIP_READ_CHUNK_BYTES, max_bytes + 1 - actual_size)
            if read_size <= 0:
                return b"".join(chunks), actual_size, True
            chunk = member.read(read_size)
            if not chunk:
                return b"".join(chunks), actual_size, False
            actual_size += len(chunk)
            if actual_size > max_bytes:
                return b"".join(chunks), actual_size, True
            chunks.append(chunk)


class InstalledSkillReader(LocalDirectoryReader):
    """Resolve and read an installed skill by canonical skill:// identity."""

    @classmethod
    def from_target(
        cls,
        target: str,
        *,
        storage: Any,
        limits: PackageLimits = DEFAULT_PACKAGE_LIMITS,
    ) -> InstalledSkillReader:
        category, rel_path = parse_skill_uri(target)
        root = _installed_skill_root(storage, category, rel_path)
        return cls(
            root,
            subject=_subject(
                source="installed",
                category=category,
                name_hint=PurePosixPath(rel_path).name,
                display_ref=f"skill://{category}/{rel_path}",
            ),
            limits=limits,
        )


def parse_skill_uri(target: str) -> tuple[str, str]:
    if not target.startswith("skill://"):
        raise ValueError("Installed skill targets must use skill://<category>/<relative-path>")
    raw = target[len("skill://") :]
    category, sep, rel_path = raw.partition("/")
    if not sep or category not in {"public", "custom", "legacy"}:
        raise ValueError("Skill target must include category: public, custom, or legacy")
    rel_path = normalize_relative_path(rel_path)
    return category, rel_path


def _installed_skill_root(storage: Any, category: str, rel_path: str) -> Path:
    if category == "custom" and hasattr(storage, "get_user_custom_root"):
        return Path(storage.get_user_custom_root()) / rel_path
    if category == "legacy":
        return Path(storage.get_skills_root_path()) / "custom" / rel_path
    return Path(storage.get_skills_root_path()) / category / rel_path
