"""Memory storage providers.

The file backend stores only project-independent user/history summaries in one
user-level ``memory.json``. Each fact is canonical in one Markdown file below
its required agent name. The
public ``load``/``save`` compatibility surface still exposes the historical
document shape (``facts`` is a list), so updater and gateway callers can move
to the fact repository API incrementally.
"""

from __future__ import annotations

import abc
import copy
import hashlib
import importlib
import json
import logging
import os
import shutil
import threading
import time
import uuid
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import yaml

from ..config import DeerMemConfig
from .paths import DEFAULT_AGENT_BUCKET, agent_facts_directory, fact_file_path, memory_file_path, safe_user_id, validate_agent_name

logger = logging.getLogger(__name__)

DOCUMENT_VERSION = "2.0"
CORE_CATEGORIES = frozenset({"preference", "correction", "context", "goal", "behavior", "identity", "constraint", "decision", "other"})


class MemoryStorageError(RuntimeError):
    """Base error for persistent memory failures."""


class MemoryStorageCorruption(MemoryStorageError):
    """The global memory JSON or a canonical fact cannot be parsed safely."""


class MemoryRevisionConflict(MemoryStorageError):
    """A stale writer attempted to overwrite a newer user-memory revision."""


class MemoryManifestRevisionConflict(MemoryRevisionConflict):
    """The shared user-memory revision changed before a transaction committed."""


class MemoryFactRevisionConflict(MemoryRevisionConflict):
    """A fact no longer satisfies its expected absence or revision."""


class RetrievalPort(Protocol):
    """Storage-facing adapter implemented by the independent retrieval module."""

    def upsert(self, fact: dict[str, Any], *, scope: dict[str, str | None], path: str) -> None: ...

    def remove(self, fact_id: str, *, scope: dict[str, str | None]) -> None: ...

    def search(self, query: str, *, scopes: list[dict[str, str | None]], top_k: int, mode: str, filters: dict[str, Any] | None) -> list[dict[str, Any]]: ...


RetrievalNotification = tuple[str, dict[str, Any] | str, str | None]
ScopedRetrievalNotifications = tuple[str, list[RetrievalNotification]]


def utc_now_iso_z() -> str:
    return datetime.now(UTC).isoformat().removesuffix("+00:00") + "Z"


def create_empty_memory() -> dict[str, Any]:
    """Return the compatibility document shape used by updater/injection."""
    return {
        "version": "1.0",
        "revision": 0,
        "lastUpdated": utc_now_iso_z(),
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": [],
    }


def _has_meaningful_data(value: Any) -> bool:
    """Return whether a legacy summary value contains anything worth preserving."""
    if isinstance(value, dict):
        return any(_has_meaningful_data(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_meaningful_data(item) for item in value)
    return value not in (None, "", False)


def _merge_legacy_summary_section(*, canonical: Any, legacy: Any, section: str, legacy_path: Path) -> Any:
    """Adopt a legacy section only when doing so cannot overwrite live data."""
    if canonical == legacy or not _has_meaningful_data(legacy):
        return copy.deepcopy(canonical)
    if not _has_meaningful_data(canonical):
        return copy.deepcopy(legacy)
    raise MemoryStorageCorruption(f"Legacy {section} summary migration conflict in {legacy_path}; the legacy file was kept")


def _scope_dict(user_id: str | None, agent_name: str | None) -> dict[str, str | None]:
    return {"userId": user_id, "agentName": agent_name}


def _content_hash(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _file_signature(path: Path) -> tuple[int, int] | None:
    """Use nanosecond mtime plus size so cache validation is not mtime-only."""
    try:
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None


def _ensure_migration_backup(source_path: Path) -> Path:
    """Durably preserve one immutable pre-migration JSON source beside it."""
    backup_path = source_path.with_name(f"{source_path.name}.v1.bak")
    try:
        source_bytes = source_path.read_bytes()
        if backup_path.exists():
            if backup_path.read_bytes() != source_bytes:
                raise MemoryStorageCorruption(f"Existing migration backup {backup_path} differs from source {source_path}; the original backup was kept and migration was stopped")
            return backup_path
        _atomic_write(backup_path, source_bytes)
        return backup_path
    except MemoryStorageCorruption:
        raise
    except OSError as exc:
        raise OSError(f"Failed to create durable migration backup {backup_path}: {exc}") from exc


def _normalize_category(fact: dict[str, Any]) -> None:
    raw_category = fact.get("category", "context")
    if not isinstance(raw_category, str):
        raise ValueError("fact.category must be a string")
    category = raw_category or "context"
    if category not in CORE_CATEGORIES:
        fact.setdefault("categoryExtension", category)
        fact["category"] = "other"


def _require_string_list(fact: dict[str, Any], field: str) -> None:
    value = fact.get(field, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"fact.{field} must be a list of strings")
    fact[field] = value


def _normalize_fact(
    fact: dict[str, Any],
    *,
    scope: dict[str, str | None],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one fact and derive its per-item revision.

    The shared JSON revision protects the multi-file transaction.  The fact's
    own revision protects one Markdown object when a disjoint transaction is
    safely rebased after that shared revision changed.
    """
    if not isinstance(fact, dict):
        raise ValueError("fact must be an object")
    normalized = copy.deepcopy(fact)
    normalized["id"] = str(normalized.get("id") or f"fact_{uuid.uuid4().hex}")
    # Validate the id through the canonical path builder's public contract.
    if not normalized["id"] or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for character in normalized["id"]):
        raise ValueError("fact.id may contain only letters, numbers, '_' and '-'")
    normalized["schemaVersion"] = 2
    if not isinstance(normalized.get("content"), str):
        raise ValueError("fact.content must be a string")
    normalized["content"] = normalized["content"].strip()
    if not normalized["content"]:
        raise ValueError("fact.content must not be empty")
    _normalize_category(normalized)
    confidence = normalized.get("confidence", 0.5)
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("fact.confidence must be a number between 0 and 1")
    normalized["confidence"] = float(confidence)
    status = normalized.get("status", "active")
    if status != "active":
        raise ValueError("fact.status must be 'active'; deletion is physical")
    normalized["status"] = "active"
    normalized["scope"] = copy.deepcopy(scope)
    _require_string_list(normalized, "topics")
    _require_string_list(normalized, "consolidatedFrom")
    revision = normalized.get("revision", 1)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("fact.revision must be an integer >= 1")
    source = normalized.get("source")
    if isinstance(source, str):
        if source in {"manual", "consolidation", "import", "unknown"}:
            normalized["source"] = {"type": source, "threadId": None}
        else:
            normalized["source"] = {"type": "conversation", "threadId": source}
    elif not isinstance(source, dict):
        normalized["source"] = {"type": "unknown", "threadId": None}
    else:
        normalized["source"].setdefault("type", "unknown")
        if not isinstance(normalized["source"].get("type"), str):
            raise ValueError("fact.source.type must be a string")
        if normalized["source"].get("threadId") is not None and not isinstance(normalized["source"].get("threadId"), str):
            raise ValueError("fact.source.threadId must be a string or null")
    normalized["title"] = _fact_title(normalized)
    now = utc_now_iso_z()
    if existing is None:
        normalized.setdefault("createdAt", now)
        normalized.setdefault("updatedAt", normalized["createdAt"])
        normalized["revision"] = revision
    else:
        existing_revision = existing.get("revision")
        if not isinstance(existing_revision, int) or existing_revision < 1:
            raise MemoryStorageCorruption(f"Stored fact {normalized['id']!r} has an invalid revision")
        if revision != existing_revision:
            raise MemoryFactRevisionConflict(f"Expected fact {normalized['id']!r} revision {revision}, found {existing_revision}")
        normalized["createdAt"] = existing.get("createdAt") or normalized.get("createdAt") or now
        comparison_keys = {"revision", "updatedAt"}
        incoming_material = {key: value for key, value in normalized.items() if key not in comparison_keys}
        existing_material = {key: value for key, value in existing.items() if key not in comparison_keys}
        if incoming_material == existing_material:
            normalized["revision"] = existing_revision
            normalized["updatedAt"] = existing.get("updatedAt") or normalized["createdAt"]
        else:
            normalized["revision"] = existing_revision + 1
            normalized["updatedAt"] = now
    if not isinstance(normalized.get("createdAt"), str) or not isinstance(normalized.get("updatedAt"), str):
        raise ValueError("fact.createdAt and fact.updatedAt must be strings")
    if normalized["consolidatedFrom"]:
        normalized.setdefault("consolidatedAt", normalized["updatedAt"])
    return normalized


def _safe_relative_path(root: Path, relative: str, *, label: str) -> Path:
    """Resolve an untrusted persisted relative path without leaving root."""
    candidate = Path(relative)
    if candidate.is_absolute():
        raise MemoryStorageCorruption(f"{label} path escapes the user memory directory: {relative!r}")
    root_resolved = root.resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise MemoryStorageCorruption(f"{label} path escapes the user memory directory: {relative!r}") from exc
    return resolved


def _fact_title(fact: dict[str, Any]) -> str:
    explicit = str(fact.get("title") or "").strip()
    if explicit:
        return explicit.replace("\n", " ")[:160]
    first = str(fact.get("content") or "Memory fact").splitlines()[0].strip()
    return (first or "Memory fact")[:160]


def _render_fact_markdown(fact: dict[str, Any]) -> bytes:
    metadata = {key: copy.deepcopy(value) for key, value in fact.items() if key not in {"content", "title"}}
    scope = metadata.pop("scope", {})
    if isinstance(scope, dict):
        metadata["user_id"] = scope.get("userId")
        metadata["agent_name"] = scope.get("agentName")
    front_matter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
    text = f"---\n{front_matter}\n---\n\n# {_fact_title(fact)}\n\n{fact['content'].rstrip()}\n"
    return text.encode("utf-8")


def _parse_fact_markdown(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise ValueError("missing YAML front matter")
        front, body = text[4:].split("\n---\n", 1)
        metadata = yaml.safe_load(front) or {}
        if not isinstance(metadata, dict):
            raise ValueError("front matter is not a mapping")
        body = body.lstrip("\n")
        lines = body.splitlines()
        title = ""
        if lines and lines[0].startswith("# "):
            title = lines.pop(0)[2:].strip()
            if lines and not lines[0].strip():
                lines.pop(0)
        metadata["title"] = title
        metadata["content"] = "\n".join(lines).rstrip("\n")
        metadata["scope"] = {
            "userId": metadata.pop("user_id", None),
            "agentName": metadata.pop("agent_name", None),
        }
        return metadata
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        raise MemoryStorageCorruption(f"Failed to parse canonical fact {path}: {exc}") from exc


def _fsync_parent_directory(directory: Path) -> None:
    """Make a completed rename durable on POSIX filesystems."""
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temp, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
        _fsync_parent_directory(path.parent)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


@contextmanager
def _process_file_lock(lock_path: Path, timeout_seconds: float) -> Iterator[None]:
    """Cross-process advisory lock for one scope, using only the stdlib."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    deadline = time.monotonic() + timeout_seconds
    acquired = False
    try:
        while not acquired:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0, os.SEEK_END)
                    if handle.tell() == 0:
                        handle.write(b"0")
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out acquiring memory scope lock {lock_path}")
                time.sleep(0.05)
        yield
    finally:
        if acquired:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                logger.warning("Failed to release memory scope lock %s", lock_path)
        handle.close()


class MemoryStorage(abc.ABC):
    @abc.abstractmethod
    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]: ...

    @abc.abstractmethod
    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]: ...

    @abc.abstractmethod
    def save(
        self,
        memory_data: dict[str, Any],
        agent_name: str | None = None,
        *,
        user_id: str | None = None,
        expected_revision: int | None = None,
    ) -> bool: ...

    def apply_changes(self, change_set: dict[str, Any], **scope: Any) -> dict[str, Any]:
        """Apply one repository change set; providers may override atomically."""
        raise NotImplementedError

    def clear_all(self, *, user_id: str | None = None) -> dict[str, Any]:
        """Clear global summaries and every agent fact bucket for one user."""
        raise NotImplementedError


class FileMemoryStorage(MemoryStorage):
    def __init__(self, config: DeerMemConfig, retrieval: RetrievalPort | None = None):
        self._config = config
        self._retrieval = retrieval
        self._memory_cache: dict[tuple[str | None, str | None], tuple[dict[str, Any], tuple[Any, ...]]] = {}
        self._cache_lock = threading.Lock()
        self._scope_locks: weakref.WeakValueDictionary[tuple[str | None, str | None], threading.RLock] = weakref.WeakValueDictionary()

    @staticmethod
    def _cache_key(agent_name: str | None = None, *, user_id: str | None = None) -> tuple[str | None, str | None]:
        return (user_id, agent_name)

    def _scope_lock(self, key: tuple[str | None, str | None]) -> threading.RLock:
        with self._cache_lock:
            return self._scope_locks.setdefault(key, threading.RLock())

    def _get_memory_file_path(self, agent_name: str | None = None, *, user_id: str | None = None) -> Path:
        return memory_file_path(self._config, agent_name, user_id=user_id)

    def _scope_signature(self, path: Path, agent_name: str | None) -> tuple[Any, ...]:
        """Track supported writes without scanning the agent's fact files.

        Every storage-managed fact mutation advances and atomically replaces
        the user-level JSON revision. Including that revision prevents stale
        cache hits when a coarse-mtime filesystem reports identical metadata
        for two same-size writes. Direct out-of-band Markdown edits require
        ``reload()``.
        """
        file_signature = _file_signature(path)
        if file_signature is None:
            return (None, None, None)
        memory_file = self._load_memory_file(path)
        revision = int((memory_file or {}).get("revision") or 0)
        return (*file_signature, revision)

    def _dispatch_retrieval_notifications(
        self,
        notifications: list[RetrievalNotification],
        *,
        user_id: str | None,
        agent_name: str | None,
    ) -> None:
        """Notify the optional index only after durable storage locks are released."""
        if self._retrieval is None:
            return
        scope = _scope_dict(user_id, agent_name)
        for action, value, fact_path in notifications:
            try:
                if action == "upsert":
                    self._retrieval.upsert(copy.deepcopy(value), scope=scope, path=fact_path or "")
                else:
                    self._retrieval.remove(str(value), scope=scope)
            except Exception:
                logger.exception("Retrieval notification failed for %s", value)

    @staticmethod
    def _validate_loaded_fact(
        fact: dict[str, Any],
        fact_path: Path,
        *,
        user_id: str | None,
        agent_name: str,
    ) -> dict[str, Any]:
        if str(fact.get("id")) != fact_path.stem:
            raise MemoryStorageCorruption(f"Fact id mismatch for {fact_path}")
        expected_scope = _scope_dict(user_id, agent_name)
        actual_scope = fact.get("scope")
        scope_matches = isinstance(actual_scope, dict) and actual_scope.get("userId") == user_id and isinstance(actual_scope.get("agentName"), str) and actual_scope["agentName"].lower() == agent_name.lower()
        if not scope_matches:
            raise MemoryStorageCorruption(f"Fact scope mismatch for {fact_path}: expected {expected_scope!r}, found {fact.get('scope')!r}")
        try:
            return _normalize_fact(fact, scope=copy.deepcopy(actual_scope))
        except ValueError as exc:
            raise MemoryStorageCorruption(f"Invalid canonical fact {fact_path}: {exc}") from exc

    def _load_agent_facts(self, path: Path, agent_name: str | None, *, user_id: str | None) -> list[dict[str, Any]]:
        if agent_name is None:
            return []
        facts: list[dict[str, Any]] = []
        for fact_path in sorted(agent_facts_directory(path, agent_name).glob("**/*.md")):
            fact = _parse_fact_markdown(fact_path)
            facts.append(self._validate_loaded_fact(fact, fact_path, user_id=user_id, agent_name=agent_name))
        # Shard directories are an internal layout detail and must not change
        # the stable fact order observed by callers.
        return sorted(facts, key=lambda fact: str(fact["id"]))

    def _read_fact(self, path: Path, fact_id: str, *, user_id: str | None, agent_name: str) -> tuple[dict[str, Any] | None, Path]:
        fact_path = fact_file_path(path, fact_id, agent_name=agent_name)
        if not fact_path.exists():
            return None, fact_path
        fact = _parse_fact_markdown(fact_path)
        return self._validate_loaded_fact(fact, fact_path, user_id=user_id, agent_name=agent_name), fact_path

    def _agent_entries(self, path: Path, agent_name: str | None, *, user_id: str | None) -> dict[str, dict[str, str]]:
        if agent_name is None:
            return {}
        entries: dict[str, dict[str, str]] = {}
        for fact_path in sorted(agent_facts_directory(path, agent_name).glob("**/*.md")):
            fact = _parse_fact_markdown(fact_path)
            self._validate_loaded_fact(fact, fact_path, user_id=user_id, agent_name=agent_name)
            fact_id = str(fact.get("id") or "")
            if not fact_id or fact_id != fact_path.stem:
                raise MemoryStorageCorruption(f"Fact id mismatch for {fact_path}")
            entries[fact_id] = {"path": fact_path.relative_to(path.parent).as_posix()}
        return entries

    def _legacy_agent_memory_path(self, path: Path, agent_name: str) -> Path:
        return path.parent / "agents" / agent_name.lower() / path.name

    def _global_json_needs_migration(self, path: Path) -> bool:
        memory_file = self._load_memory_file(path)
        return memory_file is not None and ("facts" in memory_file or memory_file.get("version") != DOCUMENT_VERSION)

    def _migrate_previous_default_bucket_locked(
        self,
        path: Path,
        *,
        user_id: str | None,
    ) -> tuple[bool, list[RetrievalNotification]]:
        """Move facts written by the earlier ``lead-agent`` default mapping.

        A real custom ``lead-agent`` owns a ``config.yaml`` and is never
        touched.  A directory with any other unexpected file is also preserved
        and rejected instead of being guessed at or recursively deleted.
        """
        legacy_agent_name = "lead-agent"
        legacy_agent_dir = path.parent / "agents" / legacy_agent_name
        if not legacy_agent_dir.exists() or (legacy_agent_dir / "config.yaml").is_file():
            return False, []
        unexpected = [child for child in legacy_agent_dir.iterdir() if child.name != "facts"]
        legacy_facts_dir = legacy_agent_dir / "facts"
        if legacy_facts_dir.exists():
            unexpected.extend(child for child in legacy_facts_dir.glob("**/*") if child.is_file() and child.suffix.lower() != ".md")
        if unexpected:
            names = ", ".join(sorted(child.name for child in unexpected))
            raise MemoryStorageCorruption(f"Cannot migrate previous default bucket {legacy_agent_dir}: unexpected entries {names}")

        legacy_facts = self._load_agent_facts(path, legacy_agent_name, user_id=user_id)
        upserts: list[dict[str, Any]] = []
        for legacy_fact in legacy_facts:
            candidate = _normalize_fact(legacy_fact, scope=_scope_dict(user_id, DEFAULT_AGENT_BUCKET))
            existing, _ = self._read_fact(
                path,
                candidate["id"],
                user_id=user_id,
                agent_name=DEFAULT_AGENT_BUCKET,
            )
            if existing is not None:
                if not self._migration_equivalent(candidate, existing):
                    raise MemoryStorageCorruption(f"Fact migration conflict for {candidate['id']!r}")
                continue
            upserts.append(candidate)

        current_memory = self._load_memory_file(path)
        _, notifications = self._commit_changes_locked(
            path,
            user_id=user_id,
            agent_name=DEFAULT_AGENT_BUCKET,
            upserts=upserts,
            deletes=[],
            summaries=None,
            expected_revision=int((current_memory or {}).get("revision") or 0),
        )
        # Delete only the source Markdown files that were parsed above. Never
        # recursively remove this directory: if an unexpected file appears
        # concurrently, the final rmdir simply leaves it in place.
        for fact_path in legacy_facts_dir.glob("**/*.md"):
            fact_path.unlink(missing_ok=True)
        directories = sorted(
            (child for child in legacy_agent_dir.glob("**/*") if child.is_dir()),
            key=lambda child: len(child.parts),
            reverse=True,
        )
        for directory in directories:
            try:
                directory.rmdir()
            except OSError:
                pass
        try:
            legacy_agent_dir.rmdir()
        except OSError:
            pass
        return True, notifications

    def _run_read_migrations_locked(
        self,
        path: Path,
        agent_name: str | None,
        *,
        user_id: str | None,
    ) -> list[ScopedRetrievalNotifications]:
        """Finish journal recovery and all migrations reachable from reads."""
        notifications_by_agent: list[ScopedRetrievalNotifications] = []
        self._recover_if_needed(path)
        if self._global_json_needs_migration(path):
            _, _, notifications = self._migrate_locked(
                path,
                DEFAULT_AGENT_BUCKET,
                user_id=user_id,
                include_global=True,
            )
            if notifications:
                notifications_by_agent.append((DEFAULT_AGENT_BUCKET, notifications))
        if agent_name is not None:
            legacy_path = self._legacy_agent_memory_path(path, agent_name)
            if legacy_path.exists():
                _, _, notifications = self._migrate_locked(path, agent_name, user_id=user_id, include_global=False)
                if notifications:
                    notifications_by_agent.append((agent_name, notifications))
        if agent_name == DEFAULT_AGENT_BUCKET:
            _, notifications = self._migrate_previous_default_bucket_locked(path, user_id=user_id)
            if notifications:
                notifications_by_agent.append((DEFAULT_AGENT_BUCKET, notifications))
        return notifications_by_agent

    @staticmethod
    def _migration_equivalent(left: dict[str, Any], right: dict[str, Any]) -> bool:
        ignored = {"revision", "createdAt", "updatedAt", "scope", "title", "schemaVersion"}
        return {key: value for key, value in left.items() if key not in ignored} == {key: value for key, value in right.items() if key not in ignored}

    def _load_memory_file(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeError) as exc:
            raise MemoryStorageCorruption(f"Failed to load global memory JSON {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise MemoryStorageCorruption(f"Global memory JSON {path} is not an object")
        return value

    def _recover_if_needed(self, path: Path) -> None:
        """Recover or clean a previously journaled multi-file operation.

        Callers hold the scope's in-process and cross-process locks.
        """
        journal_path = path.parent / ".memory.journal.json"
        if not journal_path.exists():
            return
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            operation_id = str(journal["operationId"])
            if not operation_id or Path(operation_id).name != operation_id:
                raise TypeError("operationId must be a plain path component")
            state = journal.get("state")
            old_entries = journal.get("oldEntries", {})
            agent_name = journal.get("agentName")
            if agent_name is not None and not isinstance(agent_name, str):
                raise TypeError("agentName must be a string or null")
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise MemoryStorageCorruption(f"Invalid memory operation journal {journal_path}: {exc}") from exc
        recovery_dir = path.parent / ".recovery" / operation_id
        if state == "prepared":
            backup_manifest = recovery_dir / "memory.json"
            if backup_manifest.exists():
                _atomic_write(path, backup_manifest.read_bytes())
            elif int(journal.get("expectedRevision") or 0) == 0:
                path.unlink(missing_ok=True)
            if isinstance(old_entries, dict):
                old_ids = set(old_entries)
                for fact_id in journal.get("factIds", []):
                    if fact_id not in old_ids:
                        if agent_name is None:
                            raise MemoryStorageCorruption(f"Journal {journal_path} contains facts without agentName")
                        fact_file_path(path, str(fact_id), agent_name=agent_name).unlink(missing_ok=True)
                for fact_id, entry in old_entries.items():
                    if not isinstance(fact_id, str) or not fact_id or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for character in fact_id):
                        raise MemoryStorageCorruption(f"Journal {journal_path} contains an invalid fact id")
                    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                        continue
                    backup = recovery_dir / f"{fact_id}.md"
                    if backup.exists():
                        _atomic_write(_safe_relative_path(path.parent, entry["path"], label="journal"), backup.read_bytes())
        elif state != "committed":
            raise MemoryStorageCorruption(f"Unknown journal state {state!r} in {journal_path}")
        if recovery_dir.exists():
            shutil.rmtree(recovery_dir)
        journal_path.unlink(missing_ok=True)

    def _commit_changes_locked(
        self,
        path: Path,
        *,
        user_id: str | None,
        agent_name: str | None,
        upserts: list[dict[str, Any]],
        deletes: list[str],
        summaries: dict[str, Any] | None,
        expected_revision: int | None,
        delete_revisions: dict[str, int] | None = None,
        upsert_revisions: dict[str, int | None] | None = None,
    ) -> tuple[dict[str, Any], list[RetrievalNotification]]:
        """Commit only the addressed fact files plus the shared summary JSON.

        Callers hold both locks and have already run journal recovery.  This is
        deliberately not implemented as load-all/replace-all: unchanged fact
        files are neither opened for backup nor rewritten nor re-indexed.
        """
        current_memory = self._load_memory_file(path)
        current_revision = int((current_memory or {}).get("revision") or 0)
        if expected_revision is not None and expected_revision != current_revision:
            raise MemoryManifestRevisionConflict(f"Expected user-memory revision {expected_revision}, found {current_revision}")
        if (upserts or deletes) and agent_name is None:
            raise ValueError("agent_name is required for fact repository changes")

        scope = _scope_dict(user_id, agent_name)
        prepared: dict[str, tuple[dict[str, Any], dict[str, Any] | None, Path]] = {}
        for incoming in upserts:
            if not isinstance(incoming, dict):
                raise ValueError("change_set.upserts must contain fact objects")
            candidate = copy.deepcopy(incoming)
            candidate["id"] = str(candidate.get("id") or f"fact_{uuid.uuid4().hex}")
            fact_id = candidate["id"]
            if fact_id in prepared:
                raise ValueError(f"Duplicate fact id {fact_id!r} in upserts")
            if agent_name is None:  # guarded above
                raise ValueError("agent_name is required for fact repository changes")
            existing, fact_path = self._read_fact(path, fact_id, user_id=user_id, agent_name=agent_name)
            if upsert_revisions is not None and fact_id in upsert_revisions:
                expected_fact_revision = upsert_revisions[fact_id]
                if expected_fact_revision is None and existing is not None:
                    raise MemoryFactRevisionConflict(f"Fact {fact_id!r} must not already exist")
                if expected_fact_revision is not None:
                    actual_fact_revision = None if existing is None else existing.get("revision")
                    if actual_fact_revision != expected_fact_revision:
                        raise MemoryFactRevisionConflict(f"Expected fact {fact_id!r} revision {expected_fact_revision}, found {actual_fact_revision}")
            normalized = _normalize_fact(candidate, scope=scope, existing=existing)
            if existing != normalized:
                prepared[fact_id] = (normalized, existing, fact_path)

        delete_ids = [str(fact_id) for fact_id in deletes]
        if len(delete_ids) != len(set(delete_ids)):
            raise ValueError("Duplicate fact ids are not allowed in deletes")
        removals: dict[str, tuple[dict[str, Any], Path]] = {}
        for fact_id in delete_ids:
            if fact_id in prepared:
                raise ValueError(f"Fact {fact_id!r} cannot be upserted and deleted together")
            if agent_name is None:  # guarded above
                raise ValueError("agent_name is required for fact repository changes")
            existing, fact_path = self._read_fact(path, fact_id, user_id=user_id, agent_name=agent_name)
            if existing is None:
                continue
            if delete_revisions and fact_id in delete_revisions and delete_revisions[fact_id] != existing.get("revision"):
                raise MemoryFactRevisionConflict(f"Expected fact {fact_id!r} revision {delete_revisions[fact_id]}, found {existing.get('revision')}")
            removals[fact_id] = (existing, fact_path)

        base = current_memory or create_empty_memory()
        user_section = copy.deepcopy(base.get("user", {}))
        history_section = copy.deepcopy(base.get("history", {}))
        if summaries is not None:
            if not isinstance(summaries, dict):
                raise ValueError("change_set.summaries must be an object")
            if "user" in summaries:
                if not isinstance(summaries["user"], dict):
                    raise ValueError("change_set.summaries.user must be an object")
                user_section.update(copy.deepcopy(summaries["user"]))
            if "history" in summaries:
                if not isinstance(summaries["history"], dict):
                    raise ValueError("change_set.summaries.history must be an object")
                history_section.update(copy.deepcopy(summaries["history"]))
        summaries_changed = user_section != base.get("user", {}) or history_section != base.get("history", {})
        needs_manifest_cleanup = current_memory is None or current_memory.get("version") != DOCUMENT_VERSION or "facts" in current_memory
        if not prepared and not removals and not summaries_changed and not needs_manifest_cleanup:
            memory_file = current_memory or {
                "version": DOCUMENT_VERSION,
                "revision": 0,
                "lastUpdated": base.get("lastUpdated", utc_now_iso_z()),
                "user": user_section,
                "history": history_section,
            }
            return memory_file, []

        next_revision = current_revision + 1
        old_entries: dict[str, dict[str, str]] = {}
        for fact_id, (_, existing, fact_path) in prepared.items():
            if existing is not None:
                old_entries[fact_id] = {"path": fact_path.relative_to(path.parent).as_posix()}
        for fact_id, (_, fact_path) in removals.items():
            old_entries[fact_id] = {"path": fact_path.relative_to(path.parent).as_posix()}
        fact_ids = list(prepared) + list(removals)
        journal = {
            "operationId": uuid.uuid4().hex,
            "state": "prepared",
            "agentName": agent_name,
            "expectedRevision": current_revision,
            "nextRevision": next_revision,
            "factIds": fact_ids,
            "oldEntries": old_entries,
        }
        journal_path = path.parent / ".memory.journal.json"
        recovery_dir = path.parent / ".recovery" / journal["operationId"]
        recovery_dir.mkdir(parents=True, exist_ok=True)
        if current_memory is not None:
            shutil.copy2(path, recovery_dir / "memory.json")
        for fact_id, entry in old_entries.items():
            old_path = _safe_relative_path(path.parent, entry["path"], label="journal")
            if old_path.exists():
                shutil.copy2(old_path, recovery_dir / f"{fact_id}.md")
        _atomic_write(journal_path, json.dumps(journal, ensure_ascii=False, indent=2).encode("utf-8"))

        notifications: list[RetrievalNotification] = []
        for fact_id, (fact, _, fact_path) in prepared.items():
            _atomic_write(fact_path, _render_fact_markdown(fact))
            notifications.append(("upsert", fact, str(fact_path)))
        for fact_id, (_, fact_path) in removals.items():
            fact_path.unlink(missing_ok=True)
            notifications.append(("remove", fact_id, None))

        memory_file = {
            "version": DOCUMENT_VERSION,
            "revision": next_revision,
            "lastUpdated": utc_now_iso_z(),
            "user": user_section,
            "history": history_section,
        }
        _atomic_write(path, json.dumps(memory_file, ensure_ascii=False, indent=2).encode("utf-8"))
        journal["state"] = "committed"
        _atomic_write(journal_path, json.dumps(journal, ensure_ascii=False, indent=2).encode("utf-8"))
        shutil.rmtree(recovery_dir, ignore_errors=True)
        journal_path.unlink(missing_ok=True)
        with self._cache_lock:
            for cache_key in [cache_key for cache_key in self._memory_cache if cache_key[0] == user_id]:
                self._memory_cache.pop(cache_key, None)
        return memory_file, notifications

    def _migrate_locked(
        self,
        path: Path,
        agent_name: str,
        *,
        user_id: str | None,
        include_global: bool,
        adopt_legacy_summaries: bool = True,
    ) -> tuple[bool, str | None, list[RetrievalNotification]]:
        """Merge legacy facts without overwriting an existing canonical fact."""
        sources: list[tuple[Path, dict[str, Any]]] = []
        legacy_path = self._legacy_agent_memory_path(path, agent_name)
        legacy_memory = self._load_memory_file(legacy_path)
        if legacy_memory is not None:
            sources.append((legacy_path, legacy_memory))
        global_memory = self._load_memory_file(path)
        from_version = None if global_memory is None else global_memory.get("version")
        if include_global and global_memory is not None and ("facts" in global_memory or global_memory.get("version") != DOCUMENT_VERSION):
            sources.append((path, global_memory))
        if not sources:
            return False, from_version, []

        base = global_memory or create_empty_memory()
        migrated_summaries = {
            "user": copy.deepcopy(base.get("user", {})),
            "history": copy.deepcopy(base.get("history", {})),
        }
        if legacy_memory is not None and adopt_legacy_summaries:
            for section in ("user", "history"):
                migrated_summaries[section] = _merge_legacy_summary_section(
                    canonical=migrated_summaries[section],
                    legacy=legacy_memory.get(section, {}),
                    section=section,
                    legacy_path=legacy_path,
                )

        upserts: list[dict[str, Any]] = []
        pending: dict[str, dict[str, Any]] = {}
        for source_path, source_memory in sources:
            source_document = self._document_from_memory_file(
                source_memory,
                source_path,
                agent_name,
                user_id=user_id,
                allow_legacy_facts=True,
            )
            for raw_fact in source_document.get("facts", []):
                if not isinstance(raw_fact, dict):
                    raise MemoryStorageCorruption(f"Legacy fact in {source_path} is not an object")
                candidate = _normalize_fact(raw_fact, scope=_scope_dict(user_id, agent_name))
                existing, _ = self._read_fact(path, candidate["id"], user_id=user_id, agent_name=agent_name)
                if existing is not None:
                    if not self._migration_equivalent(candidate, existing):
                        raise MemoryStorageCorruption(f"Fact migration conflict for {candidate['id']!r}")
                    continue
                previous = pending.get(candidate["id"])
                if previous is not None:
                    if not self._migration_equivalent(candidate, previous):
                        raise MemoryStorageCorruption(f"Fact migration conflict for {candidate['id']!r}")
                    continue
                pending[candidate["id"]] = candidate
                upserts.append(candidate)

        # Migration is intentionally one-way for the running application.
        # Preserve every destructive v1 JSON source before the first v2 write;
        # a failed/mismatched backup aborts while all source data is untouched.
        for source_path, _ in sources:
            _ensure_migration_backup(source_path)

        current_revision = int((global_memory or {}).get("revision") or 0)
        _, notifications = self._commit_changes_locked(
            path,
            user_id=user_id,
            agent_name=agent_name,
            upserts=upserts,
            deletes=[],
            summaries=migrated_summaries,
            expected_revision=current_revision,
        )
        if legacy_memory is not None:
            legacy_path.unlink(missing_ok=True)
        return True, from_version, notifications

    def _document_from_memory_file(
        self,
        memory_file: dict[str, Any],
        path: Path,
        agent_name: str | None,
        *,
        user_id: str | None,
        allow_legacy_facts: bool = False,
    ) -> dict[str, Any]:
        """Build the compatibility document without persisting facts in JSON."""
        legacy_facts = memory_file.get("facts")
        contains_owned_legacy_facts = isinstance(legacy_facts, dict) or (isinstance(legacy_facts, list) and bool(legacy_facts))
        if contains_owned_legacy_facts and not allow_legacy_facts:
            raise MemoryStorageCorruption(f"Legacy facts in {path} require explicit migrate(user_id=..., agent_name=...)")
        if isinstance(legacy_facts, list):
            facts = copy.deepcopy(legacy_facts) if agent_name is not None else []
        elif isinstance(legacy_facts, dict):
            facts = []
            if agent_name is not None:
                for fact_id, entry in legacy_facts.items():
                    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                        raise MemoryStorageCorruption(f"Invalid legacy manifest entry for fact {fact_id!r}")
                    fact_path = _safe_relative_path(path.parent, entry["path"], label="legacy fact")
                    fact = _parse_fact_markdown(fact_path)
                    if str(fact.get("id")) != str(fact_id):
                        raise MemoryStorageCorruption(f"Legacy manifest id mismatch for fact {fact_id!r}")
                    if entry.get("contentHash") and entry.get("contentHash") != _content_hash(fact_path.read_bytes()):
                        raise MemoryStorageCorruption(f"Hash mismatch for canonical fact {fact_id!r}")
                    facts.append(fact)
        elif legacy_facts is None:
            facts = self._load_agent_facts(path, agent_name, user_id=user_id)
        else:
            raise MemoryStorageCorruption(f"Legacy facts in {path} must be a list or mapping")
        result = {key: copy.deepcopy(value) for key, value in memory_file.items() if key != "facts"}
        result.setdefault("revision", 0)
        result["facts"] = facts
        return result

    def _read_document(self, path: Path, agent_name: str | None, *, user_id: str | None) -> dict[str, Any]:
        memory_file = self._load_memory_file(path)
        if memory_file is None:
            result = create_empty_memory()
            result["facts"] = self._load_agent_facts(path, agent_name, user_id=user_id)
            return result
        return self._document_from_memory_file(memory_file, path, agent_name, user_id=user_id)

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        path = self._get_memory_file_path(agent_name, user_id=user_id)
        key = self._cache_key(agent_name, user_id=user_id)
        journal_path = path.parent / ".memory.journal.json"
        legacy_path = self._legacy_agent_memory_path(path, agent_name) if agent_name is not None else None
        previous_default_dir = path.parent / "agents" / "lead-agent"
        needs_migration = (
            journal_path.exists()
            or (legacy_path is not None and legacy_path.exists())
            or self._global_json_needs_migration(path)
            or (agent_name == DEFAULT_AGENT_BUCKET and previous_default_dir.exists() and not (previous_default_dir / "config.yaml").is_file())
        )
        migration_notifications: list[ScopedRetrievalNotifications] = []
        if needs_migration:
            with self._scope_lock(key), _process_file_lock(path.parent / ".memory.lock", float(getattr(self._config, "file_lock_timeout_seconds", 10))):
                migration_notifications = self._run_read_migrations_locked(path, agent_name, user_id=user_id)
        for notification_agent, notifications in migration_notifications:
            self._dispatch_retrieval_notifications(notifications, user_id=user_id, agent_name=notification_agent)
        signature = self._scope_signature(path, agent_name)
        with self._cache_lock:
            cached = self._memory_cache.get(key)
            if cached is not None and cached[1] == signature:
                return copy.deepcopy(cached[0])
        document = self._read_document(path, agent_name, user_id=user_id)
        with self._cache_lock:
            self._memory_cache[key] = (copy.deepcopy(document), signature)
        return copy.deepcopy(document)

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        path = self._get_memory_file_path(agent_name, user_id=user_id)
        key = self._cache_key(agent_name, user_id=user_id)
        legacy_path = self._legacy_agent_memory_path(path, agent_name) if agent_name is not None else None
        previous_default_dir = path.parent / "agents" / "lead-agent"
        needs_migration = (
            (path.parent / ".memory.journal.json").exists()
            or (legacy_path is not None and legacy_path.exists())
            or self._global_json_needs_migration(path)
            or (agent_name == DEFAULT_AGENT_BUCKET and previous_default_dir.exists() and not (previous_default_dir / "config.yaml").is_file())
        )
        migration_notifications: list[ScopedRetrievalNotifications] = []
        if needs_migration:
            with self._scope_lock(key), _process_file_lock(path.parent / ".memory.lock", float(getattr(self._config, "file_lock_timeout_seconds", 10))):
                migration_notifications = self._run_read_migrations_locked(path, agent_name, user_id=user_id)
        for notification_agent, notifications in migration_notifications:
            self._dispatch_retrieval_notifications(notifications, user_id=user_id, agent_name=notification_agent)
        document = self._read_document(path, agent_name, user_id=user_id)
        signature = self._scope_signature(path, agent_name)
        with self._cache_lock:
            self._memory_cache[key] = (copy.deepcopy(document), signature)
        return copy.deepcopy(document)

    def migrate(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Run the idempotent version-driven migration for one exact scope."""
        if agent_name is None:
            raise ValueError("agent_name is required to migrate legacy facts")
        path = self._get_memory_file_path(agent_name, user_id=user_id)
        key = self._cache_key(agent_name, user_id=user_id)
        with self._scope_lock(key), _process_file_lock(path.parent / ".memory.lock", float(getattr(self._config, "file_lock_timeout_seconds", 10))):
            self._recover_if_needed(path)
            migrated, from_version, notifications = self._migrate_locked(path, agent_name, user_id=user_id, include_global=True)
        self._dispatch_retrieval_notifications(notifications, user_id=user_id, agent_name=agent_name)
        document = self.reload(agent_name, user_id=user_id)
        return {
            "migrated": migrated,
            "fromVersion": from_version,
            "toVersion": document.get("version"),
            "revision": document.get("revision", 0),
        }

    def save(
        self,
        memory_data: dict[str, Any],
        agent_name: str | None = None,
        *,
        user_id: str | None = None,
        expected_revision: int | None = None,
    ) -> bool:
        """Compatibility full replacement, diffed into per-fact operations.

        This API must scan the selected agent to determine which omitted facts
        are deletions, but the commit writes only new/changed/deleted facts.
        Repository callers should prefer ``apply_changes`` to avoid even that
        full comparison scan.
        """
        path = self._get_memory_file_path(agent_name, user_id=user_id)
        key = self._cache_key(agent_name, user_id=user_id)
        lock_path = path.parent / ".memory.lock"
        notifications: list[RetrievalNotification] = []
        try:
            if not isinstance(memory_data, dict):
                raise ValueError("memory_data must be an object")
            if agent_name is not None and "facts" not in memory_data:
                raise ValueError("memory_data.facts is required for an agent full save")
            facts_raw = memory_data.get("facts", [])
            if not isinstance(facts_raw, list):
                raise ValueError("memory_data.facts must be a list")
            if any(not isinstance(fact, dict) for fact in facts_raw):
                raise ValueError("memory_data.facts must contain only fact objects")
            if agent_name is None and facts_raw:
                raise ValueError("agent_name is required to persist facts")
            with self._scope_lock(key), _process_file_lock(lock_path, float(getattr(self._config, "file_lock_timeout_seconds", 10))):
                self._recover_if_needed(path)
                ids = [str(fact.get("id") or "") for fact in facts_raw]
                if len(ids) != len(set(ids)):
                    raise ValueError("Duplicate fact ids are not allowed")
                old_ids = set(self._agent_entries(path, agent_name, user_id=user_id)) if agent_name is not None else set()
                summaries = None
                if agent_name is None:
                    summaries = {"user": memory_data.get("user", {}), "history": memory_data.get("history", {})}
                _, notifications = self._commit_changes_locked(
                    path,
                    user_id=user_id,
                    agent_name=agent_name,
                    upserts=copy.deepcopy(facts_raw),
                    deletes=sorted(old_ids - set(ids)),
                    summaries=summaries,
                    expected_revision=expected_revision,
                )
                document = self._read_document(path, agent_name, user_id=user_id)
                signature = self._scope_signature(path, agent_name)
                with self._cache_lock:
                    self._memory_cache[key] = (copy.deepcopy(document), signature)
        except MemoryRevisionConflict:
            raise
        except (OSError, ValueError, MemoryStorageCorruption) as exc:
            logger.error("Failed to save memory scope %s: %s", key, exc)
            return False

        self._dispatch_retrieval_notifications(notifications, user_id=user_id, agent_name=agent_name)
        return True

    def clear_all(self, *, user_id: str | None = None) -> dict[str, Any]:
        """Clear one user's summaries and all agent facts, preserving agent configs."""
        path = self._get_memory_file_path(user_id=user_id)
        key = self._cache_key(user_id=user_id)
        notifications_by_agent: list[ScopedRetrievalNotifications] = []
        with (
            self._scope_lock(key),
            _process_file_lock(
                path.parent / ".memory.lock",
                float(getattr(self._config, "file_lock_timeout_seconds", 10)),
            ),
        ):
            self._recover_if_needed(path)
            agents_root = path.parent / "agents"
            if agents_root.exists():
                for agent_dir in sorted(child for child in agents_root.iterdir() if child.is_dir()):
                    agent_name = agent_dir.name
                    validate_agent_name(agent_name)
                    legacy_path = self._legacy_agent_memory_path(path, agent_name)
                    if legacy_path.exists():
                        _, _, migration_notifications = self._migrate_locked(
                            path,
                            agent_name,
                            user_id=user_id,
                            include_global=False,
                            adopt_legacy_summaries=False,
                        )
                        if migration_notifications:
                            notifications_by_agent.append((agent_name, migration_notifications))
                    facts = self._load_agent_facts(path, agent_name, user_id=user_id)
                    if not facts:
                        continue
                    current_memory = self._load_memory_file(path)
                    _, notifications = self._commit_changes_locked(
                        path,
                        user_id=user_id,
                        agent_name=agent_name,
                        upserts=[],
                        deletes=[str(fact["id"]) for fact in facts],
                        summaries=None,
                        expected_revision=int((current_memory or {}).get("revision") or 0),
                        delete_revisions={str(fact["id"]): int(fact.get("revision") or 1) for fact in facts},
                    )
                    notifications_by_agent.append((agent_name, notifications))

            empty = create_empty_memory()
            current_memory = self._load_memory_file(path)
            self._commit_changes_locked(
                path,
                user_id=user_id,
                agent_name=None,
                upserts=[],
                deletes=[],
                summaries={"user": empty["user"], "history": empty["history"]},
                expected_revision=int((current_memory or {}).get("revision") or 0),
            )

        for agent_name, notifications in notifications_by_agent:
            self._dispatch_retrieval_notifications(notifications, user_id=user_id, agent_name=agent_name)
        return self.reload(DEFAULT_AGENT_BUCKET, user_id=user_id)

    @staticmethod
    def _scope_kwargs(scope: dict[str, str | None]) -> dict[str, str]:
        kwargs: dict[str, str] = {}
        if scope.get("userId") is not None:
            kwargs["user_id"] = str(scope["userId"])
        if scope.get("agentName") is not None:
            kwargs["agent_name"] = str(scope["agentName"])
        return kwargs

    def get_fact(
        self,
        fact_id: str,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any] | None:
        if agent_name is None:
            raise ValueError("agent_name is required to get a fact")
        path = self._get_memory_file_path(agent_name, user_id=user_id)
        key = self._cache_key(agent_name, user_id=user_id)
        legacy_path = self._legacy_agent_memory_path(path, agent_name)
        notifications: list[RetrievalNotification] = []
        with self._scope_lock(key), _process_file_lock(path.parent / ".memory.lock", float(getattr(self._config, "file_lock_timeout_seconds", 10))):
            self._recover_if_needed(path)
            if legacy_path.exists():
                _, _, notifications = self._migrate_locked(path, agent_name, user_id=user_id, include_global=False)
            fact, _ = self._read_fact(path, fact_id, user_id=user_id, agent_name=agent_name)
        self._dispatch_retrieval_notifications(notifications, user_id=user_id, agent_name=agent_name)
        return copy.deepcopy(fact)

    def list_facts(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        filters: dict[str, Any] | None = None,
        cursor: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if cursor < 0 or limit < 1:
            raise ValueError("cursor must be >= 0 and limit must be >= 1")
        facts = self.load(agent_name, user_id=user_id).get("facts", [])
        filters = filters or {}
        matched = [fact for fact in facts if all(key in fact and fact.get(key) == value for key, value in filters.items())]
        return copy.deepcopy(matched[cursor : cursor + limit])

    def apply_changes(
        self,
        change_set: dict[str, Any],
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        expected_manifest_revision: int | None = None,
        allow_manifest_rebase: bool = False,
    ) -> dict[str, Any]:
        """Commit an incremental change set and return only the applied delta.

        ``complete`` is deliberately false: callers that require the historical
        full document must explicitly call ``load``.  This prevents a fresh
        process from presenting a one-fact cache snapshot as the whole agent
        memory while keeping the mutation path free of full fact scans.
        """
        has_fact_changes = bool(change_set.get("upserts") or change_set.get("deletes"))
        if has_fact_changes and agent_name is None:
            raise ValueError("agent_name is required for fact repository changes")
        summaries = change_set.get("summaries")
        upserts = copy.deepcopy(change_set.get("upserts", []))
        deletes = change_set.get("deletes", [])
        delete_revisions = change_set.get("deleteRevisions")
        upsert_revisions = change_set.get("upsertRevisions")
        if not isinstance(upserts, list) or not isinstance(deletes, list):
            raise ValueError("change_set.upserts and change_set.deletes must be lists")
        if delete_revisions is not None and not isinstance(delete_revisions, dict):
            raise ValueError("change_set.deleteRevisions must be an object")
        if upsert_revisions is not None and not isinstance(upsert_revisions, dict):
            raise ValueError("change_set.upsertRevisions must be an object")

        normalized_upsert_revisions: dict[str, int | None] = {}
        for incoming in upserts:
            if not isinstance(incoming, dict):
                raise ValueError("change_set.upserts must contain fact objects")
            incoming["id"] = str(incoming.get("id") or f"fact_{uuid.uuid4().hex}")
            fact_id = incoming["id"]
            if isinstance(upsert_revisions, dict) and fact_id in upsert_revisions:
                expected_fact_revision = upsert_revisions[fact_id]
            else:
                expected_fact_revision = incoming.get("revision") if "revision" in incoming else None
            if expected_fact_revision is not None and (isinstance(expected_fact_revision, bool) or not isinstance(expected_fact_revision, int) or expected_fact_revision < 1):
                raise ValueError("change_set.upsertRevisions values must be null or integers >= 1")
            normalized_upsert_revisions[fact_id] = expected_fact_revision

        path = self._get_memory_file_path(agent_name, user_id=user_id)
        key = self._cache_key(agent_name, user_id=user_id)
        expected = expected_manifest_revision
        notifications: list[RetrievalNotification] = []
        memory_file: dict[str, Any] | None = None
        safe_delete_rebase = not deletes or (isinstance(delete_revisions, dict) and all(str(fact_id) in delete_revisions for fact_id in deletes))
        safe_upsert_rebase = all(str(incoming["id"]) in normalized_upsert_revisions for incoming in upserts)
        for attempt in range(3):
            try:
                with self._scope_lock(key), _process_file_lock(path.parent / ".memory.lock", float(getattr(self._config, "file_lock_timeout_seconds", 10))):
                    self._recover_if_needed(path)
                    memory_file, notifications = self._commit_changes_locked(
                        path,
                        user_id=user_id,
                        agent_name=agent_name,
                        upserts=upserts,
                        deletes=[str(fact_id) for fact_id in deletes],
                        summaries=copy.deepcopy(summaries),
                        expected_revision=expected,
                        delete_revisions=copy.deepcopy(delete_revisions),
                        upsert_revisions=normalized_upsert_revisions,
                    )
                break
            except MemoryManifestRevisionConflict as exc:
                can_rebase = allow_manifest_rebase and has_fact_changes and summaries is None and safe_delete_rebase and safe_upsert_rebase and attempt < 2
                if not can_rebase:
                    raise
                current = self._load_memory_file(path)
                expected = int((current or {}).get("revision") or 0)
                logger.info("Rebasing disjoint memory fact change after revision conflict: %s", exc)
        self._dispatch_retrieval_notifications(notifications, user_id=user_id, agent_name=agent_name)
        if memory_file is None:  # defensive: the bounded loop either commits or raises
            raise MemoryStorageError("Memory repository change did not produce a result")
        return {
            "complete": False,
            "version": memory_file.get("version", DOCUMENT_VERSION),
            "revision": memory_file.get("revision", 0),
            "lastUpdated": memory_file.get("lastUpdated", ""),
            "upsertedFacts": [copy.deepcopy(value) for action, value, _ in notifications if action == "upsert" and isinstance(value, dict)],
            "deletedFactIds": [str(value) for action, value, _ in notifications if action == "remove"],
        }

    def upsert_fact(
        self,
        fact: dict[str, Any],
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        expected_manifest_revision: int | None = None,
        expected_fact_revision: int | None = None,
    ) -> dict[str, Any]:
        if agent_name is None:
            raise ValueError("agent_name is required to upsert a fact")
        incoming = copy.deepcopy(fact)
        incoming["id"] = str(incoming.get("id") or f"fact_{uuid.uuid4().hex}")
        fact_id = incoming["id"]
        return self.apply_changes(
            {"upserts": [incoming], "upsertRevisions": {fact_id: expected_fact_revision}},
            user_id=user_id,
            agent_name=agent_name,
            expected_manifest_revision=expected_manifest_revision,
            allow_manifest_rebase=True,
        )

    def delete_fact(
        self,
        fact_id: str,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        expected_manifest_revision: int | None = None,
        expected_fact_revision: int | None = None,
    ) -> dict[str, Any]:
        if agent_name is None:
            raise ValueError("agent_name is required to delete a fact")
        return self.apply_changes(
            {
                "deletes": [fact_id],
                "deleteRevisions": ({fact_id: expected_fact_revision} if expected_fact_revision is not None else None),
            },
            user_id=user_id,
            agent_name=agent_name,
            expected_manifest_revision=expected_manifest_revision,
            allow_manifest_rebase=True,
        )

    def get_summaries(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        document = self.load(agent_name, user_id=user_id)
        return {"user": copy.deepcopy(document.get("user", {})), "history": copy.deepcopy(document.get("history", {})), "revision": document.get("revision", 0)}

    def update_summaries(
        self,
        summaries: dict[str, Any],
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        # Summaries are always user-global, never agent-specific.
        document = self.load(user_id=user_id)
        document.update({key: copy.deepcopy(value) for key, value in summaries.items() if key in {"user", "history"}})
        expected = int(document.get("revision") or 0) if expected_revision is None else expected_revision
        if not self.save(document, user_id=user_id, expected_revision=expected):
            raise MemoryStorageError("Failed to update global memory summaries")
        return self.reload(user_id=user_id)

    def notify_fact_upsert(self, fact: dict[str, Any], *, path: str = "") -> bool:
        if self._retrieval is None:
            return False
        scope = fact.get("scope") if isinstance(fact.get("scope"), dict) else {}
        self._retrieval.upsert(copy.deepcopy(fact), scope=copy.deepcopy(scope), path=path)
        return True

    def notify_fact_remove(self, fact_id: str, *, scope: dict[str, str | None]) -> bool:
        if self._retrieval is None:
            return False
        self._retrieval.remove(fact_id, scope=copy.deepcopy(scope))
        return True

    def search_facts(
        self,
        query: str,
        *,
        scopes: list[dict[str, str | None]],
        top_k: int = 10,
        mode: str = "hybrid",
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if self._retrieval is not None:
            return self._retrieval.search(query, scopes=scopes, top_k=top_k, mode=mode, filters=filters)
        query_lower = query.strip().lower()
        if not query_lower or top_k <= 0:
            return []
        results: list[dict[str, Any]] = []
        for scope in scopes:
            facts = self.list_facts(filters=filters, **self._scope_kwargs(scope))
            for fact in facts:
                content = fact.get("content")
                if isinstance(content, str) and query_lower in content.lower():
                    results.append({"fact": fact, "score": float(fact.get("confidence") or 0.5), "matchType": "substring"})
        results.sort(key=lambda result: result["score"], reverse=True)
        return results[:top_k]

    def rebuild_index(self, scopes: list[dict[str, str | None]] | None = None) -> dict[str, Any]:
        if self._retrieval is None:
            return {"supported": False, "indexed": 0, "failed": 0, "reason": "retrieval_not_configured"}
        indexed = 0
        failed = 0
        if scopes is None:
            root = Path(self._config.storage_path) if self._config.storage_path else memory_file_path(self._config).parent
            candidates = root.glob("**/facts/**/*.md")
            for path in candidates:
                try:
                    fact = _parse_fact_markdown(path)
                    relative_parts = path.relative_to(root).parts
                    agents_index = relative_parts.index("agents")
                    expected_agent = relative_parts[agents_index + 1]
                    expected_user_bucket = relative_parts[1] if len(relative_parts) > 1 and relative_parts[0] == "users" else None
                    fact_scope = fact.get("scope") if isinstance(fact.get("scope"), dict) else {}
                    original_user = fact_scope.get("userId")
                    if original_user is not None and not isinstance(original_user, str):
                        raise MemoryStorageCorruption(f"Fact scope userId is invalid for {path}")
                    if expected_user_bucket is not None and (original_user is None or safe_user_id(original_user) != expected_user_bucket):
                        raise MemoryStorageCorruption(f"Fact user scope does not match directory for {path}")
                    validate_agent_name(expected_agent)
                    self._validate_loaded_fact(fact, path, user_id=original_user, agent_name=expected_agent)
                    self.notify_fact_upsert(fact, path=str(path))
                    indexed += 1
                except Exception:
                    logger.exception("Failed to rebuild retrieval index for %s", path)
                    failed += 1
        else:
            for scope in scopes:
                kwargs = self._scope_kwargs(scope)
                memory_path = self._get_memory_file_path(**kwargs)
                agent_name = kwargs.get("agent_name")
                if agent_name is None:
                    continue
                for fact in self.list_facts(**kwargs):
                    try:
                        self.notify_fact_upsert(fact, path=str(fact_file_path(memory_path, fact["id"], agent_name=agent_name)))
                        indexed += 1
                    except Exception:
                        logger.exception("Failed to rebuild retrieval index for fact %s", fact.get("id"))
                        failed += 1
        return {"supported": True, "indexed": indexed, "failed": failed}

    def retrieval_status(self) -> dict[str, Any]:
        return {
            "configured": self._retrieval is not None,
            "mode": "external" if self._retrieval is not None else "substring_fallback",
        }

    def capabilities(self) -> set[str]:
        capabilities = {"file", "markdown-facts", "global-summary-json", "revision", "journal", "fact-repository", "substring-fallback"}
        if self._retrieval is not None:
            capabilities.add("retrieval")
        return capabilities


def create_storage(config: DeerMemConfig, retrieval: RetrievalPort | None = None) -> MemoryStorage:
    if retrieval is None and config.retrieval_adapter:
        try:
            module_path, factory_name = config.retrieval_adapter.rsplit(".", 1)
            factory = getattr(importlib.import_module(module_path), factory_name)
            retrieval = factory(config)
        except Exception as exc:
            raise ValueError(f"backend_config.retrieval_adapter={config.retrieval_adapter!r} failed to load: {exc}") from exc
    storage_class_path = config.storage_class
    if not storage_class_path or storage_class_path == "file":
        return FileMemoryStorage(config, retrieval=retrieval)
    try:
        module_path, class_name = storage_class_path.rsplit(".", 1)
        storage_class = getattr(importlib.import_module(module_path), class_name)
        if not isinstance(storage_class, type) or not issubclass(storage_class, MemoryStorage):
            raise TypeError(f"Configured memory storage '{storage_class_path}' is not a MemoryStorage class")
        return storage_class(config)
    except Exception as exc:
        raise ValueError(f"backend_config.storage_class={storage_class_path!r} failed to load: {exc}. Refusing to silently fall back because memory is persistent state.") from exc
