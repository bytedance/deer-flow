"""Persistence for IM channel configuration entered from the web UI ("runtime config").

An admin can connect a provider from the browser instead of editing
``config.yaml``: the credentials it enters, and a later disconnect, are stored
per provider and overlaid on the ``channels.*`` blocks by
:func:`merge_runtime_channel_configs`. Two stores share the
:class:`RuntimeConfigStore` protocol:

- :class:`SqlChannelRuntimeConfigStore` keeps them in the
  ``channel_runtime_configs`` table of the application database (SQLite or
  PostgreSQL), so every Gateway instance reads the same rows. Each provider's
  config is stored as ``DEER_FLOW_CREDENTIALS_KEY`` ciphertext
  (``deerflow.config.credentials_key``); a disconnect is a plaintext tombstone
  with no secret. Every save bumps the provider's ``version``, which the leader
  lease supervisor in ``ChannelService`` polls to apply a save made on a peer.
- :class:`ChannelRuntimeConfigStore` is the historical JSON file
  ``{base_dir}/channels/runtime-config.json`` (plaintext, mode 0600). It stays
  for ``database.backend: memory`` (one process, nothing to share) and as the
  source of the SQL store's one-time import, which deletes the file afterwards.

:func:`resolve_runtime_config_store` picks one. Every store call may block (a
file or a database round trip), so async callers run it in a worker thread.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from deerflow.config.credentials_key import CredentialsCipher
    from deerflow.persistence.channel_runtime_configs import SqlChannelRuntimeConfigRepository, StoredChannelRuntimeConfig

logger = logging.getLogger(__name__)

RUNTIME_CHANNEL_DISABLED_FLAG = "_runtime_disabled"


class ChannelRuntimeConfigEncryptionUnavailable(RuntimeError):
    """The database store has no credentials key, so it refuses to persist credentials."""


class RuntimeConfigStore(Protocol):
    """Provider -> runtime config block, as entered from the web UI. Calls may block."""

    @property
    def can_store_credentials(self) -> bool:
        """False when :meth:`set_provider_config` would refuse (no encryption key for the database)."""
        ...

    def load_all(self) -> dict[str, dict[str, Any]]: ...

    def get_provider_config(self, provider: str) -> dict[str, Any] | None: ...

    def set_provider_config(self, provider: str, config: dict[str, Any]) -> None: ...

    def set_provider_disconnected(self, provider: str) -> None: ...

    def versions(self) -> dict[str, int]:
        """``provider -> version`` that changes on every save, for noticing saves made by another instance."""
        ...


@contextmanager
def _runtime_config_file_lock(path: Path) -> Iterator[None]:
    """Exclude read-modify-write cycles of this file in other Gateway processes.

    The lock is an advisory sidecar next to the store file, so it covers every
    worker and embedded client that resolves the same ``DEER_FLOW_HOME``. The
    path is normalized first, as in ``extensions_config_file_lock``, so a
    symlinked spelling of the file shares the lock of the file it points to.
    """
    target_path = path.resolve(strict=False) if path.is_symlink() else path.absolute()
    lock_path = target_path.parent / f".{target_path.name}.lock"
    with open(lock_path, "a+b") as lock_file:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

        try:
            yield
        finally:
            if os.name == "nt":
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class ChannelRuntimeConfigStore:
    """JSON-backed store for channel credentials entered from the UI.

    This intentionally mirrors ``JsonChannelStore``: local/private deployments get
    durable runtime configuration without needing a public callback URL or a
    config.yaml edit. It serves ``database.backend: memory`` (a single process);
    a sqlite/postgres database uses :class:`SqlChannelRuntimeConfigStore`.
    """

    #: The file is plaintext (mode 0600), as it always was; there is no key to miss.
    can_store_credentials = True

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else default_runtime_config_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, dict[str, Any]] = self._load()
        self._lock = threading.Lock()

    def _load(self, fallback: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                if fallback is not None:
                    logger.warning("Corrupt channel runtime config store at %s, rewriting it from this process's copy", self._path)
                    return {name: dict(config) for name, config in fallback.items()}
                logger.warning("Corrupt channel runtime config store at %s, starting fresh", self._path)
                return {}
            if isinstance(raw, dict):
                return {str(name): dict(value) for name, value in raw.items() if isinstance(value, dict)}
        return {}

    @contextmanager
    def _mutation(self) -> Iterator[dict[str, dict[str, Any]]]:
        """Yield the file's current providers for one read-modify-write cycle.

        Each Gateway worker keeps its own store, loaded when that worker first
        needed it. Saving that snapshot would overwrite providers a peer worker
        saved since, so every mutation reloads the file while holding the
        thread lock and the cross-process file lock, changes one provider, and
        saves. An unreadable file falls back to this process's copy rather
        than an empty one. The snapshot this process serves is refreshed only
        after the cycle completes; a failed save leaves the previous one in
        place.
        """
        with self._lock, _runtime_config_file_lock(self._path):
            data = self._load(fallback=self._data)
            yield data
            self._data = data

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        fd = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._path.parent,
            suffix=".tmp",
            delete=False,
        )
        try:
            try:
                Path(fd.name).chmod(0o600)
            except OSError:
                logger.debug("Unable to chmod temporary channel runtime config store at %s", fd.name, exc_info=True)
            json.dump(data, fd, indent=2, ensure_ascii=False)
            fd.close()
            Path(fd.name).replace(self._path)
            try:
                self._path.chmod(0o600)
            except OSError:
                logger.debug("Unable to chmod channel runtime config store at %s", self._path, exc_info=True)
        except BaseException:
            fd.close()
            Path(fd.name).unlink(missing_ok=True)
            raise

    def load_all(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {name: dict(config) for name, config in self._data.items()}

    def get_provider_config(self, provider: str) -> dict[str, Any] | None:
        with self._lock:
            config = self._data.get(provider)
            return dict(config) if isinstance(config, dict) else None

    def set_provider_config(self, provider: str, config: dict[str, Any]) -> None:
        with self._mutation() as data:
            data[provider] = dict(config)
            self._save(data)

    def set_provider_disconnected(self, provider: str) -> None:
        with self._mutation() as data:
            data[provider] = {
                "enabled": False,
                RUNTIME_CHANNEL_DISABLED_FLAG: True,
            }
            self._save(data)

    def remove_provider_config(self, provider: str) -> bool:
        with self._mutation() as data:
            if provider not in data:
                return False
            del data[provider]
            self._save(data)
            return True

    def versions(self) -> dict[str, int]:
        # One process owns the file (a ``memory`` database cannot be shared), so
        # every save already went through this process: there is no peer save
        # to notice.
        return {}


_TOMBSTONE: dict[str, Any] = {"enabled": False, RUNTIME_CHANNEL_DISABLED_FLAG: True}


class SqlChannelRuntimeConfigStore:
    """Database-backed store over ``channel_runtime_configs``, shared by every instance using the database.

    ``cipher`` is the deployment ``CredentialsCipher``. Without one a
    credential save raises :class:`ChannelRuntimeConfigEncryptionUnavailable`
    rather than storing plaintext, and stored credentials read as not
    configured; disconnect tombstones need no key either way. A row the key
    cannot decrypt (lost or replaced key) also reads as not configured, with
    one error per row version.
    """

    def __init__(self, repo: SqlChannelRuntimeConfigRepository, *, cipher: CredentialsCipher | None, legacy_path: str | Path | None = None) -> None:
        self._repo = repo
        self._cipher = cipher
        self._legacy_path = Path(legacy_path) if legacy_path is not None else None
        self._reported: set[tuple[str, int]] = set()

    @property
    def legacy_path(self) -> Path | None:
        """The ``runtime-config.json`` that :meth:`import_legacy_json` moves into the table."""
        return self._legacy_path

    @property
    def can_store_credentials(self) -> bool:
        return self._cipher is not None

    def load_all(self) -> dict[str, dict[str, Any]]:
        configs: dict[str, dict[str, Any]] = {}
        for row in self._repo.list_all():
            config = self._decode(row)
            if config is not None:
                configs[row.provider] = config
        return configs

    def get_provider_config(self, provider: str) -> dict[str, Any] | None:
        row = self._repo.get(provider)
        return self._decode(row) if row is not None else None

    def set_provider_config(self, provider: str, config: dict[str, Any]) -> None:
        self._repo.save(provider, config_ciphertext=self._encrypt(config), disconnected=False, now=time.time())

    def set_provider_disconnected(self, provider: str) -> None:
        self._repo.save(provider, config_ciphertext=None, disconnected=True, now=time.time())

    def versions(self) -> dict[str, int]:
        return self._repo.versions()

    def import_legacy_json(self) -> int:
        """Move ``runtime-config.json`` into the table once, then delete it; returns how many rows this call inserted.

        Every well-formed entry is inserted with ``ON CONFLICT DO NOTHING``: a
        provider already in the table keeps its row (it was saved after the
        table took over, so it is newer than the file), any other provider is
        imported, and two instances importing the same file at once neither
        duplicate nor clobber a row. The file is then deleted, not renamed: a
        plaintext copy left on disk would keep the credentials the table
        encrypts. No file is a no-op; a corrupt file is kept and reported, and
        so is a file with credentials while there is no key to encrypt them.
        """
        from deerflow.persistence.channel_runtime_configs import CHANNEL_RUNTIME_CONFIG_PROVIDER_LENGTH, StoredChannelRuntimeConfig

        path = self._legacy_path
        if path is None:
            return 0
        entries = _read_legacy_file(path)
        if entries is None:
            return 0
        rows: list[StoredChannelRuntimeConfig] = []
        skipped = 0
        for provider, config in entries.items():
            if not isinstance(config, dict) or not provider or len(provider) > CHANNEL_RUNTIME_CONFIG_PROVIDER_LENGTH:
                skipped += 1
                continue
            if runtime_channel_disconnected(config):
                rows.append(StoredChannelRuntimeConfig(provider=provider, config_ciphertext=None, disconnected=True, version=1))
                continue
            if self._cipher is None:
                logger.error("Channel runtime config %s holds credentials but no credentials key is available to encrypt them; keeping the file and not importing it", path)
                return 0
            rows.append(StoredChannelRuntimeConfig(provider=provider, config_ciphertext=self._encrypt(config), disconnected=False, version=1))
        if skipped:
            logger.warning("Skipping %d malformed entries in channel runtime config %s (not an object, or an empty or oversized provider name)", skipped, path)
        inserted = self._repo.insert_missing(rows, now=time.time())
        removed = _remove_legacy_file(path)
        logger.info(
            "Imported %d of %d channel runtime configs from %s into channel_runtime_configs%s",
            inserted,
            len(rows),
            path,
            "; deleted the plaintext file" if removed else " (file already removed by a peer)",
        )
        return inserted

    def _encrypt(self, config: dict[str, Any]) -> str:
        if self._cipher is None:
            raise ChannelRuntimeConfigEncryptionUnavailable("channel credentials cannot be stored: the DEER_FLOW_CREDENTIALS_KEY credentials key is unavailable")
        return self._cipher.encrypt_text(json.dumps(config, ensure_ascii=False))

    def _decode(self, row: StoredChannelRuntimeConfig) -> dict[str, Any] | None:
        if row.disconnected:
            return dict(_TOMBSTONE)
        if row.config_ciphertext is None:
            return None
        if self._cipher is None:
            self._report(row, "Channel runtime config for %s is stored encrypted but no DEER_FLOW_CREDENTIALS_KEY credentials key is available; treating the provider as not configured")
            return None
        from deerflow.config.credentials_key import CredentialsDecryptError

        try:
            value = json.loads(self._cipher.decrypt_text(row.config_ciphertext))
        except (CredentialsDecryptError, json.JSONDecodeError):
            self._report(
                row, "Channel runtime config for %s cannot be decrypted with the configured DEER_FLOW_CREDENTIALS_KEY; treating the provider as not configured until the key that wrote it is restored or its credentials are saved again"
            )
            return None
        return dict(value) if isinstance(value, dict) else None

    def _report(self, row: StoredChannelRuntimeConfig, message: str) -> None:
        key = (row.provider, row.version)
        if key not in self._reported:
            self._reported.add(key)
            logger.error(message, row.provider)


def _read_legacy_file(path: Path) -> dict[str, Any] | None:
    """Parse ``runtime-config.json``; ``None`` when it is missing, unreadable or not an object (kept in place)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        logger.warning("Cannot read channel runtime config %s; skipping the import (file kept)", path, exc_info=True)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        logger.warning("Corrupt channel runtime config %s; skipping the import (file kept)", path)
        return None
    return data


def _remove_legacy_file(path: Path) -> bool:
    """Delete the imported plaintext file; ``False`` when a peer already did."""
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        logger.warning("Imported channel runtime config %s but could not delete it; it still holds plaintext credentials, remove it by hand", path, exc_info=True)
        return False
    return True


def default_runtime_config_path() -> Path:
    """``{base_dir}/channels/runtime-config.json`` (resolves ``base_dir`` through realpath: call off the loop)."""
    from deerflow.config.paths import get_paths

    return Path(get_paths().base_dir) / "channels" / "runtime-config.json"


def resolve_runtime_config_store(app_config: Any, *, cipher: CredentialsCipher | None, path: str | Path | None = None) -> RuntimeConfigStore:
    """Pick the store for ``database.backend``: the JSON file for ``memory`` (or no config), the table for a database.

    The table needs the persistence engine the Gateway lifespan initialises
    (its Alembic bootstrap creates the table); without it a configured
    database falls back to the JSON file with a warning, so a bare
    ``ChannelService`` keeps working. ``path`` is the JSON file (default
    :func:`default_runtime_config_path`), also the table's import source.
    Blocks (path resolution, the JSON file's first read): call off the loop.
    """
    database = getattr(app_config, "database", None)
    backend = getattr(database, "backend", None)
    store_path = Path(path) if path is not None else default_runtime_config_path()
    if backend in ("sqlite", "postgres"):
        from deerflow.persistence.engine import get_session_factory

        if get_session_factory() is not None:
            from deerflow.persistence.agents.sql import get_sync_sessionmaker
            from deerflow.persistence.channel_runtime_configs import SqlChannelRuntimeConfigRepository

            repo = SqlChannelRuntimeConfigRepository(get_sync_sessionmaker(database.app_sync_sqlalchemy_url))
            return SqlChannelRuntimeConfigStore(repo, cipher=cipher, legacy_path=store_path)
        logger.warning("database.backend=%s but no persistence engine is initialised; IM channel runtime config falls back to %s for this process", backend, store_path)
    return ChannelRuntimeConfigStore(store_path)


def _provider_enabled(channel_connections_config: Any, provider: str) -> bool:
    provider_config = getattr(channel_connections_config, provider, None)
    return bool(getattr(provider_config, "enabled", False))


def runtime_channel_disconnected(runtime_config: dict[str, Any]) -> bool:
    return runtime_config.get(RUNTIME_CHANNEL_DISABLED_FLAG) is True and runtime_config.get("enabled") is False


def overlay_runtime_channel_configs(
    channels_config: dict[str, Any],
    channel_connections_config: Any,
    runtime_configs: dict[str, dict[str, Any]],
    *,
    keep_disconnected: bool = False,
) -> None:
    """Overlay already-loaded runtime configs onto ``channels_config`` in place.

    The runtime block wins key by key over the ``config.yaml`` block. A
    disconnect removes the provider, or with ``keep_disconnected`` leaves the
    tombstone in its place (a disabled block), so a single-provider reload can
    tell "disconnected" from "absent".
    """
    if channel_connections_config is None or not getattr(channel_connections_config, "enabled", False):
        return

    for provider, runtime_config in runtime_configs.items():
        if not _provider_enabled(channel_connections_config, provider):
            continue
        if runtime_channel_disconnected(runtime_config):
            if keep_disconnected:
                channels_config[provider] = dict(runtime_config)
            else:
                channels_config.pop(provider, None)
            continue
        existing = channels_config.get(provider)
        merged = dict(existing) if isinstance(existing, dict) else {}
        merged.update(runtime_config)
        channels_config[provider] = merged


def merge_runtime_channel_configs(
    channels_config: dict[str, Any],
    channel_connections_config: Any,
    *,
    store: RuntimeConfigStore,
) -> None:
    """Merge persisted runtime provider config into ``channels_config`` in-place (blocks: reads ``store``)."""
    if channel_connections_config is None or not getattr(channel_connections_config, "enabled", False):
        return
    overlay_runtime_channel_configs(channels_config, channel_connections_config, store.load_all())


def apply_runtime_connection_config(
    channel_connections_config: Any,
    *,
    store: RuntimeConfigStore,
) -> Any:
    """Apply persisted connection metadata that lives outside ``channels``.

    Telegram uses a bot username for deep links; UI-entered values are stored
    with the runtime channel config so local restarts keep the provider
    configured. Blocks: reads ``store``.
    """
    if channel_connections_config is None or not getattr(channel_connections_config, "enabled", False):
        return channel_connections_config

    telegram_runtime_config = store.get_provider_config("telegram")
    bot_username = ""
    if isinstance(telegram_runtime_config, dict):
        bot_username = str(telegram_runtime_config.get("bot_username") or "").strip()
    if not bot_username or not _provider_enabled(channel_connections_config, "telegram"):
        return channel_connections_config

    config = channel_connections_config.model_copy(deep=True)
    config.telegram.bot_username = bot_username
    return config
