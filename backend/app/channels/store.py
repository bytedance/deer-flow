"""ChannelStore — persists IM chat-to-DeerFlow thread bindings.

``ChannelManager`` maps every unbound IM conversation
(``channel_name:chat_id[:topic_id]``) to the DeerFlow thread it runs on. Two
implementations share the :class:`ChannelStore` protocol:

- :class:`SqlChannelStore` keeps the bindings in the ``channel_thread_bindings``
  table of the application database (SQLite or PostgreSQL). Every Gateway
  replica sharing that database sees the same bindings, so a conversation
  created on one replica continues on the same thread when the next message
  lands on another. This is the store for every non-``memory`` database.
- :class:`JsonChannelStore` is the historical single file at
  ``{base_dir}/channels/store.json``, loaded once per process and rewritten
  atomically on every change. It stays for ``database.backend: memory`` (no
  database to share) and as the source of the one-time import below. With
  several Gateway processes each loads its own copy: a binding created on one
  is invisible to the others and concurrent writers clobber each other's file.

The protocol is async because the SQL store runs on the async engine and must
never block the Gateway event loop; the JSON store offloads its file I/O through
``asyncio.to_thread`` for the same reason (anchored by
``tests/blocking_io/test_channel_thread_binding_store.py``). Callers in a
synchronous SDK callback (Feishu's lark thread) bridge to the loop through
``Channel._submit_threadsafe_coroutine_future``.

Selection (:func:`resolve_channel_store`) follows ``database.backend``:
``memory`` -> JSON; ``sqlite`` / ``postgres`` -> SQL whenever the persistence
engine is initialised, else JSON with a warning (a bare ``ChannelService``
without the Gateway lifespan). ``ChannelService.start()`` then runs
:meth:`SqlChannelStore.import_legacy_json` once: if ``store.json`` exists and the
table is empty every entry is inserted with ``ON CONFLICT DO NOTHING`` (two
replicas importing concurrently cannot duplicate or clobber a binding) and the
file is renamed to ``store.json.migrated``; a populated table leaves the file
alone, and a missing file is a no-op.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.channel_thread_bindings import ChannelThreadBinding, SqlChannelThreadBindingRepository, binding_key, split_binding_key
from deerflow.persistence.channel_thread_bindings.model import BINDING_KEY_LENGTH, CHANNEL_NAME_LENGTH, CHAT_ID_LENGTH, THREAD_ID_LENGTH, TOPIC_ID_LENGTH, USER_ID_LENGTH

logger = logging.getLogger(__name__)

#: Suffix appended to ``store.json`` once its entries live in the database.
MIGRATED_SUFFIX = ".migrated"


class ChannelStore(Protocol):
    """Async mapping from an IM conversation/topic to its DeerFlow ``thread_id``."""

    async def get_thread_id(self, channel_name: str, chat_id: str, topic_id: str | None = None) -> str | None:
        """Look up the DeerFlow thread_id for a given IM conversation/topic."""
        ...

    async def set_thread_id(self, channel_name: str, chat_id: str, thread_id: str, *, topic_id: str | None = None, user_id: str = "") -> None:
        """Create or update the mapping for an IM conversation/topic (an update keeps ``created_at``)."""
        ...

    async def remove(self, channel_name: str, chat_id: str, topic_id: str | None = None) -> bool:
        """Remove one topic mapping, or — without ``topic_id`` — the base mapping and every topic of that chat."""
        ...

    async def list_entries(self, channel_name: str | None = None) -> list[dict[str, Any]]:
        """List all stored mappings, optionally filtered by channel."""
        ...


def default_store_path() -> Path:
    """``{base_dir}/channels/store.json`` (resolves ``base_dir`` through realpath: call off the loop)."""
    from deerflow.config.paths import get_paths

    return Path(get_paths().base_dir) / "channels" / "store.json"


class JsonChannelStore:
    """JSON-file-backed store that maps IM conversations to DeerFlow threads.

    Data layout (on disk)::

        {
            "<channel_name>:<chat_id>[:<topic_id>]": {
                "thread_id": "<uuid>",
                "user_id": "<platform_user>",
                "created_at": 1700000000.0,
                "updated_at": 1700000000.0
            },
            ...
        }

    The file is read once (lazily, on the first access) and atomically
    rewritten on every mutation, with the lock held across the mutation and the
    write so concurrent writers in this process serialize. Nothing re-reads the
    file afterwards, so processes sharing one file do not see each other's
    bindings — use :class:`SqlChannelStore` whenever an application database
    exists. Construction is I/O-free; every operation runs its file work in a
    worker thread.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else default_store_path()
        self._data: dict[str, dict[str, Any]] | None = None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def channels_dir(self) -> Path:
        """The directory sibling channel state files (Discord thread map, Buzz seen events) live in."""
        return self._path.parent

    # -- persistence (worker thread, lock held by the caller) ---------------

    def _ensure_loaded(self) -> dict[str, dict[str, Any]]:
        if self._data is None:
            self._data = _read_legacy_file(self._path, log_missing=False, on_corrupt="Corrupt channel store at %s, starting fresh") or {}
        return self._data

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = tempfile.NamedTemporaryFile(mode="w", dir=self._path.parent, suffix=".tmp", delete=False)
        try:
            json.dump(self._data, fd, indent=2)
            fd.close()
            Path(fd.name).replace(self._path)
        except BaseException:
            fd.close()
            Path(fd.name).unlink(missing_ok=True)
            raise

    # -- sync bodies -------------------------------------------------------

    def _get_sync(self, key: str) -> str | None:
        with self._lock:
            entry = self._ensure_loaded().get(key)
            return entry["thread_id"] if entry else None

    def _set_sync(self, key: str, thread_id: str, user_id: str) -> None:
        with self._lock:
            data = self._ensure_loaded()
            now = time.time()
            existing = data.get(key)
            data[key] = {
                "thread_id": thread_id,
                "user_id": user_id,
                "created_at": existing["created_at"] if existing else now,
                "updated_at": now,
            }
            self._save()

    def _remove_sync(self, channel_name: str, chat_id: str, topic_id: str | None) -> bool:
        with self._lock:
            data = self._ensure_loaded()
            if topic_id is not None:
                key = binding_key(channel_name, chat_id, topic_id)
                if key not in data:
                    return False
                del data[key]
                self._save()
                return True
            prefix = binding_key(channel_name, chat_id)
            keys_to_delete = [k for k in data if k == prefix or k.startswith(prefix + ":")]
            if not keys_to_delete:
                return False
            for k in keys_to_delete:
                del data[k]
            self._save()
            return True

    def _list_sync(self, channel_name: str | None) -> list[dict[str, Any]]:
        # Snapshot under the lock, format after release: a concurrent writer
        # cannot resize the dict while this iterates.
        with self._lock:
            entries = [(key, entry.copy()) for key, entry in self._ensure_loaded().items()]
        results = []
        for key, entry in entries:
            ch, chat, topic = split_binding_key(key)
            if channel_name and ch != channel_name:
                continue
            item: dict[str, Any] = {"channel_name": ch, "chat_id": chat, **entry}
            if topic is not None:
                item["topic_id"] = topic
            results.append(item)
        return results

    # -- public API --------------------------------------------------------

    async def get_thread_id(self, channel_name: str, chat_id: str, topic_id: str | None = None) -> str | None:
        return await asyncio.to_thread(self._get_sync, binding_key(channel_name, chat_id, topic_id))

    async def set_thread_id(self, channel_name: str, chat_id: str, thread_id: str, *, topic_id: str | None = None, user_id: str = "") -> None:
        await asyncio.to_thread(self._set_sync, binding_key(channel_name, chat_id, topic_id), thread_id, user_id)

    async def remove(self, channel_name: str, chat_id: str, topic_id: str | None = None) -> bool:
        return await asyncio.to_thread(self._remove_sync, channel_name, chat_id, topic_id)

    async def list_entries(self, channel_name: str | None = None) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_sync, channel_name)


class SqlChannelStore:
    """Database-backed store over ``channel_thread_bindings``, shared by every replica using the database."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], *, legacy_path: str | Path | None = None) -> None:
        self._repo = SqlChannelThreadBindingRepository(session_factory)
        self._legacy_path = Path(legacy_path) if legacy_path is not None else None

    @property
    def legacy_path(self) -> Path | None:
        """The ``store.json`` this store imports from (and whose directory sibling state files use)."""
        return self._legacy_path

    @property
    def channels_dir(self) -> Path | None:
        return self._legacy_path.parent if self._legacy_path is not None else None

    async def get_thread_id(self, channel_name: str, chat_id: str, topic_id: str | None = None) -> str | None:
        return await self._repo.get_thread_id(binding_key(channel_name, chat_id, topic_id))

    async def set_thread_id(self, channel_name: str, chat_id: str, thread_id: str, *, topic_id: str | None = None, user_id: str = "") -> None:
        await self._repo.upsert(ChannelThreadBinding.build(channel_name, chat_id, thread_id, topic_id=topic_id, user_id=user_id, now=time.time()))

    async def remove(self, channel_name: str, chat_id: str, topic_id: str | None = None) -> bool:
        if topic_id is not None:
            return await self._repo.delete(binding_key(channel_name, chat_id, topic_id))
        return await self._repo.delete_prefix(binding_key(channel_name, chat_id)) > 0

    async def list_entries(self, channel_name: str | None = None) -> list[dict[str, Any]]:
        return [binding.to_entry() for binding in await self._repo.list(channel_name)]

    async def import_legacy_json(self) -> int:
        """Move the entries of ``legacy_path`` into the table once; returns how many rows this call inserted.

        No file, no legacy path or a populated table is a no-op (the file is
        left where it is in the last case: a populated table is the source of
        truth and the operator may still want the JSON). A corrupt file is
        kept and reported. Otherwise every well-formed entry is inserted with
        ``ON CONFLICT DO NOTHING`` — so two replicas starting together both
        import without duplicating or clobbering anything — and the file is
        renamed to ``store.json.migrated``; a rename that fails because a peer
        already renamed it is tolerated.
        """
        path = self._legacy_path
        if path is None:
            return 0
        entries = await asyncio.to_thread(lambda: _read_legacy_file(path, log_missing=True, on_corrupt="Corrupt legacy channel store at %s; skipping the import (file kept)"))
        if entries is None:
            return 0
        if await self._repo.count() > 0:
            logger.info("Channel thread bindings are already in the database; leaving legacy %s in place without importing it", path)
            return 0
        now = time.time()
        bindings: list[ChannelThreadBinding] = []
        skipped = 0
        for key, entry in entries.items():
            binding = _legacy_binding(key, entry, now)
            if binding is None:
                skipped += 1
                continue
            bindings.append(binding)
        if skipped:
            logger.warning(
                "Skipping %d malformed or oversized entries in legacy channel store %s (not an object, no thread_id, empty channel/chat, or a component longer than its column)",
                skipped,
                path,
            )
        inserted = await self._repo.insert_missing(bindings)
        renamed = await asyncio.to_thread(_rename_migrated, path)
        logger.info(
            "Imported %d of %d chat-to-thread bindings from %s into channel_thread_bindings%s",
            inserted,
            len(bindings),
            path,
            f"; renamed to {path.name}{MIGRATED_SUFFIX}" if renamed else " (file already moved by a peer)",
        )
        return inserted


def _read_legacy_file(path: Path, *, log_missing: bool, on_corrupt: str) -> dict[str, Any] | None:
    """Parse ``store.json``; ``None`` when missing or corrupt.

    ``on_corrupt`` is the caller's warning (``%s`` = path): the JSON store starts
    fresh, the import skips and keeps the file — the two outcomes differ, so the
    wording is the caller's.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if log_missing:
            logger.debug("No legacy channel store at %s", path)
        return None
    except OSError:
        logger.warning(on_corrupt, path, exc_info=True)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(on_corrupt, path)
        return None
    if not isinstance(data, dict):
        logger.warning(on_corrupt, path)
        return None
    return data


def _legacy_binding(key: str, entry: Any, now: float) -> ChannelThreadBinding | None:
    """One legacy entry as a binding, or ``None`` when it is malformed or would not fit the table.

    The column bounds are checked here because only PostgreSQL enforces
    ``String(n)``: an oversized component would fail the whole import batch there
    (``value too long for type character varying``) and take every IM channel down
    with ``ChannelService.start()``, while SQLite silently accepts the same row.
    """
    if not isinstance(entry, dict) or not isinstance(entry.get("thread_id"), str) or not entry["thread_id"]:
        return None
    channel_name, chat_id, topic_id = split_binding_key(key)
    if not channel_name or not chat_id:
        return None
    thread_id = entry["thread_id"]
    user_id = entry.get("user_id")
    user_id = user_id if isinstance(user_id, str) else ""
    if (
        len(key) > BINDING_KEY_LENGTH
        or len(channel_name) > CHANNEL_NAME_LENGTH
        or len(chat_id) > CHAT_ID_LENGTH
        or (topic_id is not None and len(topic_id) > TOPIC_ID_LENGTH)
        or len(thread_id) > THREAD_ID_LENGTH
        or len(user_id) > USER_ID_LENGTH
    ):
        return None
    created_at = _stamp(entry.get("created_at"), now)
    updated_at = _stamp(entry.get("updated_at"), created_at)
    return ChannelThreadBinding(key, channel_name, chat_id, topic_id, thread_id, user_id, created_at, updated_at)


def _stamp(value: Any, fallback: float) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else fallback


def _rename_migrated(path: Path) -> bool:
    """Rename ``store.json`` to ``store.json.migrated``; ``False`` when a peer already did."""
    try:
        path.replace(path.with_name(path.name + MIGRATED_SUFFIX))
    except FileNotFoundError:
        return False
    except OSError:
        logger.warning("Imported legacy channel store %s but could not rename it; the next start finds a populated table and leaves it alone", path, exc_info=True)
        return False
    return True


_UNRESOLVED = object()


def resolve_channel_store(app_config: Any | None, *, session_factory: Any = _UNRESOLVED, path: str | Path | None = None) -> ChannelStore:
    """Pick the store for ``database.backend``: JSON for ``memory`` (or no config), SQL for a database.

    ``session_factory`` defaults to the process engine's
    (``deerflow.persistence.engine.get_session_factory``); passing ``None``
    models a configured database whose engine is not initialised, which falls
    back to the JSON file with a warning so a bare ``ChannelService`` keeps
    working. ``path`` is the JSON file (default ``{base_dir}/channels/store.json``),
    also the SQL store's import source and sibling-state directory.
    """
    backend = getattr(getattr(app_config, "database", None), "backend", None)
    store_path = Path(path) if path is not None else default_store_path()
    if backend in ("sqlite", "postgres"):
        if session_factory is _UNRESOLVED:
            from deerflow.persistence.engine import get_session_factory

            session_factory = get_session_factory()
        if session_factory is not None:
            logger.info("IM chat-to-thread bindings use the shared channel_thread_bindings table (database.backend=%s)", backend)
            return SqlChannelStore(session_factory, legacy_path=store_path)
        logger.warning("database.backend=%s but no persistence engine is initialised; IM chat-to-thread bindings fall back to %s for this process", backend, store_path)
    return JsonChannelStore(store_path)


__all__ = [
    "MIGRATED_SUFFIX",
    "ChannelStore",
    "JsonChannelStore",
    "SqlChannelStore",
    "binding_key",
    "default_store_path",
    "resolve_channel_store",
    "split_binding_key",
]
