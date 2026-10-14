"""Local persistence for runtime IM channel configuration."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RUNTIME_CHANNEL_DISABLED_FLAG = "_runtime_disabled"


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
    config.yaml edit.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            from deerflow.config.paths import get_paths

            path = Path(get_paths().base_dir) / "channels" / "runtime-config.json"
        self._path = Path(path)
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


def _provider_enabled(channel_connections_config: Any, provider: str) -> bool:
    provider_config = getattr(channel_connections_config, provider, None)
    return bool(getattr(provider_config, "enabled", False))


def _runtime_channel_disconnected(runtime_config: dict[str, Any]) -> bool:
    return runtime_config.get(RUNTIME_CHANNEL_DISABLED_FLAG) is True and runtime_config.get("enabled") is False


def merge_runtime_channel_configs(
    channels_config: dict[str, Any],
    channel_connections_config: Any,
    *,
    store: ChannelRuntimeConfigStore | None = None,
) -> None:
    """Merge persisted runtime provider config into ``channels_config`` in-place."""
    if channel_connections_config is None or not getattr(channel_connections_config, "enabled", False):
        return

    runtime_store = store or ChannelRuntimeConfigStore()
    for provider, runtime_config in runtime_store.load_all().items():
        if not _provider_enabled(channel_connections_config, provider):
            continue
        if _runtime_channel_disconnected(runtime_config):
            channels_config.pop(provider, None)
            continue
        existing = channels_config.get(provider)
        merged = dict(existing) if isinstance(existing, dict) else {}
        merged.update(runtime_config)
        channels_config[provider] = merged


def apply_runtime_connection_config(
    channel_connections_config: Any,
    *,
    store: ChannelRuntimeConfigStore | None = None,
) -> Any:
    """Apply persisted connection metadata that lives outside ``channels``.

    Telegram uses a bot username for deep links; UI-entered values are stored
    with the runtime channel config so local restarts keep the provider
    configured.
    """
    if channel_connections_config is None or not getattr(channel_connections_config, "enabled", False):
        return channel_connections_config

    runtime_store = store or ChannelRuntimeConfigStore()
    telegram_runtime_config = runtime_store.get_provider_config("telegram")
    bot_username = ""
    if isinstance(telegram_runtime_config, dict):
        bot_username = str(telegram_runtime_config.get("bot_username") or "").strip()
    if not bot_username or not _provider_enabled(channel_connections_config, "telegram"):
        return channel_connections_config

    config = channel_connections_config.model_copy(deep=True)
    config.telegram.bot_username = bot_username
    return config
