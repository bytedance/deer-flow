"""Repository for report templates — file-system backed (MVP) per §7.1.

Layout:
    {DEER_FLOW_HOME}/report-templates/
      users/{user_id}/
        index.json
        {template_id}/
          template.json
          versions/v{N}.json
          runs/{rr_id}.json
      tenants/{tenant_id}/
        index.json
        {template_id}/...

Concurrency (§7.1.3):
    1. Atomic rename (tmp → final)
    2. ETag optimistic lock on template.json writes
    3. Per-file lock (fcntl on POSIX, ``.lock`` sentinel fallback on Windows)
    4. index.json updates happen inside the same critical section as the
       template write that triggered them

Path safety (§7.1.4):
    All IDs (template_id / report_run_id / user_id / tenant_id) are
    re-validated at repository entry — never trust the caller.

Scope:
    - private  → ``users/{user_id}/{template_id}/...``
    - tenant   → ``tenants/{tenant_id}/{template_id}/...``
    - builtin  → read-only, in-memory index built from
                 ``agents/builtin/report-templates/`` at process start
                 (this module only exposes the read path)
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal

from deerflow.report_templates.records import (
    IndexEntry,
    ReportRunRecord,
    ReportTemplateRecord,
    ReportTemplateVersionRecord,
    TemplateIndex,
    TemplateStatus,
    Visibility,
    new_report_run_id,
    new_template_id,
    now_iso,
    validate_report_run_id,
    validate_template_id,
    validate_user_tenant_id,
)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RepositoryError(Exception):
    """Base class for repository failures."""


class TemplateNotFoundError(RepositoryError):
    def __init__(self, template_id: str) -> None:
        super().__init__(f"template {template_id!r} not found")
        self.template_id = template_id


class VersionNotFoundError(RepositoryError):
    def __init__(self, template_id: str, version: int) -> None:
        super().__init__(f"version {version} of {template_id!r} not found")
        self.template_id = template_id
        self.version = version


class EtagMismatchError(RepositoryError):
    """Raised when the caller's expected_etag does not match current state (HTTP 409)."""

    def __init__(self, template_id: str, *, expected: str, actual: str) -> None:
        super().__init__(
            f"etag mismatch on template {template_id!r}: expected {expected!r}, current {actual!r}"
        )
        self.template_id = template_id


class ImmutablePublishedError(RepositoryError):
    """Raised when an attempt is made to mutate a published template in place."""


class BuiltinNotWritableError(RepositoryError):
    """Raised when a writer is invoked on a builtin-scoped path."""


class PathTraversalError(RepositoryError):
    """Raised when ``Path.resolve()`` lands outside the expected root subtree."""


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scope:
    """A (visibility, owner) pair used to resolve filesystem roots."""

    visibility: Visibility
    user_id: str | None = None
    tenant_id: str | None = None

    @staticmethod
    def private(user_id: str) -> "Scope":
        return Scope("private", user_id=validate_user_tenant_id(user_id))

    @staticmethod
    def tenant(tenant_id: str) -> "Scope":
        return Scope("tenant", tenant_id=validate_user_tenant_id(tenant_id))

    @staticmethod
    def builtin() -> "Scope":
        return Scope("builtin")


class FileSystemReportTemplateRepository:
    """File-system backed repository — single MVP implementation.

    Constructor takes the **report-templates root** directory; the caller
    decides where to place it (typically ``{DEER_FLOW_HOME}/report-templates``).
    The builtin scope is fed a separate read-only directory at construction.
    """

    def __init__(
        self,
        *,
        runtime_root: Path,
        builtin_root: Path | None = None,
    ) -> None:
        self._runtime_root = Path(runtime_root).resolve()
        self._builtin_root = (
            Path(builtin_root).resolve() if builtin_root is not None else None
        )
        # Per-template locks for fcntl-style serialisation. Keyed by absolute
        # path. We keep the dict small via weak references via a simple
        # eviction policy (not needed at MVP scale).
        self._lock_table_lock = threading.Lock()
        self._lock_table: dict[str, threading.Lock] = {}

    # -------- Paths ----------------------------------------------------

    def _scope_root(self, scope: Scope) -> Path:
        if scope.visibility == "private":
            assert scope.user_id
            return self._runtime_root / "users" / scope.user_id
        if scope.visibility == "tenant":
            assert scope.tenant_id
            return self._runtime_root / "tenants" / scope.tenant_id
        if scope.visibility == "builtin":
            if self._builtin_root is None:
                raise BuiltinNotWritableError("no builtin_root configured")
            return self._builtin_root
        raise ValueError(f"unknown visibility {scope.visibility!r}")

    def _template_dir(self, scope: Scope, template_id: str) -> Path:
        validate_template_id(template_id)
        root = self._scope_root(scope)
        candidate = (root / template_id).resolve()
        # Path traversal: ensure resolved path is inside the scope root.
        try:
            candidate.relative_to(root)
        except ValueError as e:
            raise PathTraversalError(
                f"template path escapes scope root: {candidate}"
            ) from e
        return candidate

    def _versions_dir(self, scope: Scope, template_id: str) -> Path:
        return self._template_dir(scope, template_id) / "versions"

    def _runs_dir(self, scope: Scope, template_id: str) -> Path:
        return self._template_dir(scope, template_id) / "runs"

    def _index_path(self, scope: Scope) -> Path:
        return self._scope_root(scope) / "index.json"

    def _template_json(self, scope: Scope, template_id: str) -> Path:
        return self._template_dir(scope, template_id) / "template.json"

    def _version_json(self, scope: Scope, template_id: str, version: int) -> Path:
        return self._versions_dir(scope, template_id) / f"v{version}.json"

    def _run_json(self, scope: Scope, template_id: str, run_id: str) -> Path:
        validate_report_run_id(run_id)
        return self._runs_dir(scope, template_id) / f"{run_id}.json"

    # -------- Locking --------------------------------------------------

    @contextmanager
    def _lock_path(self, lock_key: Path) -> Iterator[None]:
        """Per-path threading lock — coarse-grained, MVP-scale.

        Cross-process locking is provided by ``fcntl`` on POSIX, falling back
        to a ``.lock`` sentinel file on Windows. Both are wrapped here so the
        same context manager works on every platform.
        """
        key = str(lock_key.resolve())
        with self._lock_table_lock:
            lock = self._lock_table.setdefault(key, threading.Lock())

        with lock:
            sentinel = lock_key.with_suffix(lock_key.suffix + ".lock")
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            with _process_lock(sentinel):
                yield

    # -------- Atomic I/O ----------------------------------------------

    def _atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # tmp file in the same dir guarantees rename is atomic on POSIX/NTFS.
        tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise RepositoryError(f"cannot read {path}: {e}") from e

    # -------- Public: template lifecycle ------------------------------

    def create_template(
        self,
        *,
        scope: Scope,
        name: str,
        display_name: str,
        owner_user_id: str,
        tenant_id: str,
        description: str = "",
        tags: list[str] | None = None,
    ) -> ReportTemplateRecord:
        """Create a new draft template under ``scope``."""
        if scope.visibility == "builtin":
            raise BuiltinNotWritableError("builtin templates cannot be created via API")

        template_id = new_template_id()
        validate_user_tenant_id(owner_user_id)
        validate_user_tenant_id(tenant_id)

        now = now_iso()
        record = ReportTemplateRecord(
            id=template_id,
            name=name,
            display_name=display_name,
            description=description,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            visibility=scope.visibility,
            status="draft",
            current_version=0,
            tags=tags or [],
            created_at=now,
            updated_at=now,
            etag=uuid.uuid4().hex,
        )

        template_json = self._template_json(scope, template_id)
        with self._lock_path(template_json):
            self._atomic_write_json(template_json, record.model_dump())
            self._update_index(scope, record, removed=False)

        return record

    def save_draft(
        self,
        *,
        scope: Scope,
        template_id: str,
        dsl: dict[str, Any],
        dsl_yaml: str,
        display_name: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        expected_etag: str,
    ) -> ReportTemplateRecord:
        """Update an existing draft template's metadata + staged DSL.

        Note: the staged DSL is stored as ``versions/v0.json`` (working copy);
        ``publish`` snapshots it into the next immutable version.
        """
        if scope.visibility == "builtin":
            raise BuiltinNotWritableError("builtin templates cannot be edited via API")

        template_json = self._template_json(scope, template_id)
        with self._lock_path(template_json):
            current = self._must_read_template(template_json, template_id)
            if current.status == "published":
                raise ImmutablePublishedError(
                    f"template {template_id!r} is published; create a new draft first"
                )
            if current.etag != expected_etag:
                raise EtagMismatchError(
                    template_id, expected=expected_etag, actual=current.etag
                )

            updated = current.model_copy(
                update={
                    "display_name": display_name if display_name is not None else current.display_name,
                    "description": description if description is not None else current.description,
                    "tags": tags if tags is not None else current.tags,
                    "updated_at": now_iso(),
                    "etag": uuid.uuid4().hex,
                }
            )

            # Working copy of the DSL — overwritten on every save_draft.
            version0 = ReportTemplateVersionRecord(
                template_id=template_id,
                version=0,
                dsl=dsl,
                dsl_yaml=dsl_yaml,
                checksum=_sha256(dsl_yaml),
                created_by=current.owner_user_id,
                created_at=now_iso(),
                changelog="working draft",
            )
            self._atomic_write_json(self._version_json(scope, template_id, 0), version0.model_dump())
            self._atomic_write_json(template_json, updated.model_dump())
            self._update_index(scope, updated, removed=False)
            return updated

    def publish(
        self,
        *,
        scope: Scope,
        template_id: str,
        expected_current_version: int,
        changelog: str = "",
    ) -> ReportTemplateRecord:
        """Snapshot the working draft as a new immutable version and bump status."""
        if scope.visibility == "builtin":
            raise BuiltinNotWritableError("builtin templates cannot be published via API")

        template_json = self._template_json(scope, template_id)
        with self._lock_path(template_json):
            current = self._must_read_template(template_json, template_id)
            if current.current_version != expected_current_version:
                raise EtagMismatchError(
                    template_id,
                    expected=f"current_version={expected_current_version}",
                    actual=f"current_version={current.current_version}",
                )

            working_path = self._version_json(scope, template_id, 0)
            working_raw = self._read_json(working_path)
            if working_raw is None:
                raise RepositoryError(
                    f"template {template_id!r} has no working draft to publish; call save_draft first"
                )
            working = ReportTemplateVersionRecord.model_validate(working_raw)

            new_version_n = current.current_version + 1
            snapshot = working.model_copy(
                update={
                    "version": new_version_n,
                    "created_at": now_iso(),
                    "changelog": changelog,
                }
            )
            self._atomic_write_json(
                self._version_json(scope, template_id, new_version_n), snapshot.model_dump()
            )

            updated = current.model_copy(
                update={
                    "status": "published",
                    "current_version": new_version_n,
                    "updated_at": now_iso(),
                    "etag": uuid.uuid4().hex,
                }
            )
            self._atomic_write_json(template_json, updated.model_dump())
            self._update_index(scope, updated, removed=False)
            return updated

    def fork(
        self,
        *,
        source_scope: Scope,
        source_template_id: str,
        source_version: int,
        target_scope: Scope,
        target_owner_user_id: str,
        target_tenant_id: str,
        new_name: str,
        new_display_name: str,
    ) -> ReportTemplateRecord:
        """Copy a published template's snapshot into a new draft under target scope.

        Records ``source_template_id`` and ``source_version`` on the new version's
        working copy (v0) for provenance.
        """
        if target_scope.visibility == "builtin":
            raise BuiltinNotWritableError("fork target cannot be builtin")

        # Read source — could be builtin/tenant/private; just need readable.
        snapshot_raw = self._read_json(
            self._version_json(source_scope, source_template_id, source_version)
        )
        if snapshot_raw is None:
            raise VersionNotFoundError(source_template_id, source_version)
        snapshot = ReportTemplateVersionRecord.model_validate(snapshot_raw)

        # Read source metadata for description default.
        source_meta = self._read_json(self._template_json(source_scope, source_template_id))
        description = (source_meta or {}).get("description", "")

        # Create target template (draft).
        new_record = self.create_template(
            scope=target_scope,
            name=new_name,
            display_name=new_display_name,
            owner_user_id=target_owner_user_id,
            tenant_id=target_tenant_id,
            description=description,
        )

        # Stage forked DSL as the working copy with provenance markers.
        new_v0 = ReportTemplateVersionRecord(
            template_id=new_record.id,
            version=0,
            dsl=snapshot.dsl,
            dsl_yaml=snapshot.dsl_yaml,
            checksum=snapshot.checksum,
            source_template_id=source_template_id,
            source_template_version=source_version,
            created_by=target_owner_user_id,
            created_at=now_iso(),
            changelog=f"forked from {source_template_id} v{source_version}",
        )
        target_v0_path = self._version_json(target_scope, new_record.id, 0)
        self._atomic_write_json(target_v0_path, new_v0.model_dump())

        return new_record

    def archive(
        self,
        *,
        scope: Scope,
        template_id: str,
        expected_etag: str,
    ) -> ReportTemplateRecord:
        if scope.visibility == "builtin":
            raise BuiltinNotWritableError("builtin templates cannot be archived")
        return self._set_status(scope, template_id, "archived", expected_etag)

    def delete(
        self,
        *,
        scope: Scope,
        template_id: str,
        expected_etag: str,
    ) -> None:
        """Hard-delete a template directory and prune its index entry."""
        if scope.visibility == "builtin":
            raise BuiltinNotWritableError("builtin templates cannot be deleted")
        template_json = self._template_json(scope, template_id)
        template_dir = self._template_dir(scope, template_id)

        with self._lock_path(template_json):
            current = self._must_read_template(template_json, template_id)
            if current.etag != expected_etag:
                raise EtagMismatchError(
                    template_id, expected=expected_etag, actual=current.etag
                )
            self._update_index(scope, current, removed=True)

        # Removing the directory *after* releasing the lock so the sentinel
        # file (which lives inside template_dir) is gone before we rmdir.
        _rm_dir(template_dir)

    # -------- Public: reads -------------------------------------------

    def get_template(self, scope: Scope, template_id: str) -> ReportTemplateRecord:
        record = self._read_template_record(scope, template_id)
        if record is None:
            raise TemplateNotFoundError(template_id)
        return record

    def get_version(
        self, scope: Scope, template_id: str, version: int
    ) -> ReportTemplateVersionRecord:
        raw = self._read_json(self._version_json(scope, template_id, version))
        if raw is None:
            raise VersionNotFoundError(template_id, version)
        return ReportTemplateVersionRecord.model_validate(raw)

    def list_versions(self, scope: Scope, template_id: str) -> list[int]:
        versions_dir = self._versions_dir(scope, template_id)
        if not versions_dir.exists():
            return []
        out: list[int] = []
        for entry in versions_dir.iterdir():
            if not entry.is_file() or not entry.name.startswith("v") or not entry.name.endswith(".json"):
                continue
            stem = entry.name[1:-5]
            if not stem.isdigit():
                continue
            n = int(stem)
            if n >= 1:  # v0 is working copy — skip in public listing
                out.append(n)
        return sorted(out)

    def list_templates(self, scope: Scope) -> list[IndexEntry]:
        idx_raw = self._read_json(self._index_path(scope))
        if not idx_raw:
            return []
        idx = TemplateIndex.model_validate(idx_raw)
        return list(idx.templates)

    # -------- Public: report runs -------------------------------------

    def create_report_run(
        self,
        *,
        scope: Scope,
        record: ReportRunRecord,
    ) -> ReportRunRecord:
        path = self._run_json(scope, record.template_id, record.id)
        with self._lock_path(path):
            if path.exists():
                raise RepositoryError(
                    f"report_run {record.id!r} already exists for {record.template_id!r}"
                )
            self._atomic_write_json(path, record.model_dump())
        return record

    def update_report_run(
        self,
        *,
        scope: Scope,
        record: ReportRunRecord,
    ) -> ReportRunRecord:
        path = self._run_json(scope, record.template_id, record.id)
        with self._lock_path(path):
            self._atomic_write_json(path, record.model_dump())
        return record

    def get_report_run(
        self, scope: Scope, template_id: str, run_id: str
    ) -> ReportRunRecord | None:
        raw = self._read_json(self._run_json(scope, template_id, run_id))
        return ReportRunRecord.model_validate(raw) if raw else None

    def list_report_runs(
        self, scope: Scope, template_id: str
    ) -> list[ReportRunRecord]:
        runs_dir = self._runs_dir(scope, template_id)
        if not runs_dir.exists():
            return []
        out: list[ReportRunRecord] = []
        for entry in sorted(runs_dir.iterdir()):
            if entry.is_file() and entry.suffix == ".json":
                raw = self._read_json(entry)
                if raw is not None:
                    out.append(ReportRunRecord.model_validate(raw))
        return out

    # -------- Internal helpers ----------------------------------------

    def _set_status(
        self,
        scope: Scope,
        template_id: str,
        status: TemplateStatus,
        expected_etag: str,
    ) -> ReportTemplateRecord:
        path = self._template_json(scope, template_id)
        with self._lock_path(path):
            current = self._must_read_template(path, template_id)
            if current.etag != expected_etag:
                raise EtagMismatchError(
                    template_id, expected=expected_etag, actual=current.etag
                )
            updated = current.model_copy(
                update={"status": status, "updated_at": now_iso(), "etag": uuid.uuid4().hex}
            )
            self._atomic_write_json(path, updated.model_dump())
            self._update_index(scope, updated, removed=False)
            return updated

    def _read_template_record(
        self, scope: Scope, template_id: str
    ) -> ReportTemplateRecord | None:
        raw = self._read_json(self._template_json(scope, template_id))
        return ReportTemplateRecord.model_validate(raw) if raw else None

    def _must_read_template(
        self, template_json: Path, template_id: str
    ) -> ReportTemplateRecord:
        raw = self._read_json(template_json)
        if raw is None:
            raise TemplateNotFoundError(template_id)
        return ReportTemplateRecord.model_validate(raw)

    def _update_index(
        self,
        scope: Scope,
        record: ReportTemplateRecord,
        *,
        removed: bool,
    ) -> None:
        """Refresh ``index.json`` to reflect the latest record state."""
        path = self._index_path(scope)
        existing = self._read_json(path)
        if existing is None:
            idx = TemplateIndex(schema_version="1", updated_at=now_iso(), templates=[])
        else:
            idx = TemplateIndex.model_validate(existing)

        idx.templates = [t for t in idx.templates if t.id != record.id]
        if not removed:
            idx.templates.append(
                IndexEntry(
                    id=record.id,
                    name=record.name,
                    display_name=record.display_name,
                    visibility=record.visibility,
                    status=record.status,
                    current_version=record.current_version,
                    tags=record.tags,
                    updated_at=record.updated_at,
                )
            )
        idx.updated_at = now_iso()
        self._atomic_write_json(path, idx.model_dump())


# ---------------------------------------------------------------------------
# Cross-platform process-level lock
# ---------------------------------------------------------------------------


@contextmanager
def _process_lock(sentinel: Path, *, timeout_s: float = 30.0) -> Iterator[None]:
    """Acquire a process-level lock on ``sentinel``.

    On POSIX uses fcntl.flock; on Windows falls back to an O_EXCL creation loop
    with a small sleep. The sentinel is removed when released.
    """
    deadline = time.time() + timeout_s
    fd = None

    # Detect platform up-front so we never half-open on systems without fcntl.
    try:
        import fcntl  # type: ignore[import-not-found]
        has_fcntl = True
    except ImportError:
        fcntl = None  # type: ignore[assignment]
        has_fcntl = False

    try:
        if has_fcntl:
            fd = os.open(sentinel, os.O_RDWR | os.O_CREAT, 0o644)
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.time() > deadline:
                        raise RepositoryError(
                            f"timed out waiting for lock {sentinel}"
                        )
                    time.sleep(0.05)
            yield
        else:
            # Windows / no-fcntl branch — O_EXCL spinlock.
            while True:
                try:
                    fd = os.open(sentinel, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o644)
                    break
                except FileExistsError:
                    if time.time() > deadline:
                        raise RepositoryError(
                            f"timed out waiting for lock {sentinel}"
                        )
                    time.sleep(0.05)
            yield
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            sentinel.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rm_dir(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_dir():
            _rm_dir(child)
        else:
            try:
                child.unlink()
            except OSError:
                pass
    try:
        path.rmdir()
    except OSError:
        pass
