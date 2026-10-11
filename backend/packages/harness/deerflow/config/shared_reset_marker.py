"""Shared cache-reset markers for Gateway processes that share one config directory.

Several process-local caches are derived from ``extensions_config.json`` and the
files beside it: the MCP tools cache (``deerflow.mcp.cache``) and the skills
prompt caches (``deerflow.agents.lead_agent.prompt``). The file itself is
revalidated by content signature on every read, but a cache can also go stale
without a byte of that file changing: a remote MCP server changes its
``tools/list`` response, or a skill is installed, edited, deleted or toggled
on a shared volume by another Gateway worker or Pod.

A **shared reset marker** carries that invalidation. The writer replaces a
hidden JSON file beside the resolved extensions config
(``.<config name>.<suffix>.json``) with a fresh random generation, using the
same atomic write and the same cross-process locks the config itself uses.
Every process mounting that directory records the marker's ``(mtime, size,
sha256)`` signature (``deerflow.config.file_signature``) when it publishes a
cache and compares it on later lookups; a different signature retires the
cache. A random generation needs no read-modify-write counter and cannot lose
two concurrent resets: the final write still differs from every previously
observed signature.

The scope is deliberately the shared config *directory*: replicas with
independent filesystems are not covered, and a deployment without a resolvable
config path has no shared directory to publish into. Callers surface that
distinction as ``scope=shared_config`` versus ``scope=process``.

Only the marker payload is JSON. The ``previous_generation`` field chains
writes so a reader can tell "exactly one publication since my last look" (and
honor that publication's optional ``user_id`` scope) from "several, of which I
only see the last" (which must widen to a full reset).
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from deerflow.config.file_signature import ConfigSignature, get_config_signature, read_config_with_signature

logger = logging.getLogger(__name__)

MARKER_VERSION = 1

#: Default minimum spacing between two marker reads by one tracker. The read is
#: one ``stat`` plus one small file read; the interval only bounds that cost on
#: hot cache lookups and is far below the cross-replica convergence budget.
DEFAULT_POLL_INTERVAL_SECONDS = 1.0

#: How many of its own recent generations a tracker remembers so it can skip the
#: redundant self-invalidation that would otherwise follow every local publish.
_OWN_GENERATIONS_LIMIT = 64


@dataclass(frozen=True)
class SharedResetMarkerPayload:
    """Parsed contents of a marker file. Every field is optional on read."""

    generation: str | None = None
    previous_generation: str | None = None
    user_id: str | None = None
    published_at: str | None = None

    @classmethod
    def from_json(cls, data: object) -> SharedResetMarkerPayload | None:
        """Return the payload a well-formed marker object carries, else ``None``."""
        if not isinstance(data, dict):
            return None
        return cls(
            generation=_optional_str(data.get("generation")),
            previous_generation=_optional_str(data.get("previous_generation")),
            user_id=_optional_str(data.get("user_id")),
            published_at=_optional_str(data.get("published_at")),
        )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


@dataclass(frozen=True)
class SharedResetChange:
    """One marker change observed by :class:`SharedResetMarkerTracker`.

    ``user_ids`` names the users whose caches the publication scoped itself to.
    ``None`` means the whole cache must be retired: a global publication, a
    deleted or unreadable marker, a config-path switch, or several publications
    between two polls of which only the last one is visible.
    """

    user_ids: frozenset[str] | None
    generation: str | None


class SharedResetMarker:
    """A named marker file colocated with the resolved extensions config."""

    def __init__(self, suffix: str) -> None:
        if not suffix or suffix in {".", ".."} or any(sep in suffix for sep in ("/", "\\")):
            raise ValueError(f"shared reset marker suffix must be a plain file-name fragment, got {suffix!r}")
        self._suffix = suffix

    @property
    def suffix(self) -> str:
        return self._suffix

    def path_for(self, config_path: Path) -> Path:
        """Return the marker path beside *config_path* (following a symlinked config)."""
        path = Path(config_path)
        target = path.resolve(strict=False) if path.is_symlink() else path
        return target.parent / f".{target.name}.{self._suffix}.json"

    def current_signature(self, config_path: Path | None) -> ConfigSignature | None:
        """Return the marker's current signature, or ``None`` without a config or marker."""
        if config_path is None:
            return None
        return get_config_signature(self.path_for(config_path))

    def read(self, config_path: Path) -> tuple[SharedResetMarkerPayload | None, ConfigSignature | None]:
        """Read the marker once, returning its payload and the signature of those bytes.

        A missing marker is ``(None, None)``: no reset has been published yet.
        A marker that exists but cannot be parsed keeps its signature so a
        reader still notices that *something* was written, and reports no
        payload so the reader widens to a full reset.
        """
        marker_path = self.path_for(config_path)
        try:
            data, signature = read_config_with_signature(marker_path)
        except OSError:
            return None, None
        try:
            payload = SharedResetMarkerPayload.from_json(json.loads(data.decode("utf-8-sig")))
        except (UnicodeDecodeError, ValueError):
            logger.debug("Shared reset marker %s is not valid JSON; treating it as an unscoped reset", marker_path)
            payload = None
        return payload, signature

    def publish(self, config_path: Path, *, user_id: str | None = None) -> str:
        """Publish a new generation under the extensions-config write locks.

        Holds the process-local ``extensions_config_write_lock`` and the
        cross-process ``extensions_config_file_lock`` for *config_path*, the
        same discipline every ``extensions_config.json`` writer follows, so the
        read of the previous generation and the replacement are one critical
        section. Returns the published generation.
        """
        from deerflow.config.extensions_config import extensions_config_file_lock, extensions_config_write_lock

        with extensions_config_write_lock, extensions_config_file_lock(config_path):
            return self.publish_locked(config_path, user_id=user_id)

    def publish_locked(self, config_path: Path, *, user_id: str | None = None) -> str:
        """Publish a new generation; the caller already holds both config locks.

        The marker is replaced atomically (temporary file + ``os.replace``,
        with the same bind-mount fallback as the config itself), so a reader
        never observes a truncated marker.
        """
        from deerflow.config.extensions_config import atomic_write_extensions_config

        previous, _signature = self.read(config_path)
        generation = uuid.uuid4().hex
        payload: dict[str, object] = {
            "version": MARKER_VERSION,
            "generation": generation,
            "previous_generation": previous.generation if previous is not None else None,
            "published_at": datetime.now(UTC).isoformat(),
        }
        if user_id:
            payload["user_id"] = user_id
        atomic_write_extensions_config(self.path_for(config_path), payload)
        return generation


def resolve_shared_config_path() -> Path | None:
    """Resolve the extensions config path for marker purposes, or ``None``.

    ``ExtensionsConfig.resolve_config_path()`` raises ``FileNotFoundError``
    when an explicit path or ``DEER_FLOW_EXTENSIONS_CONFIG_PATH`` names a file
    that does not exist; that is right for callers that need the config, but a
    marker reader runs on hot cache lookups and a marker writer only needs a
    directory to publish into. Both treat that failure as "no shared config
    directory right now", matching ``deerflow.mcp.cache._resolve_config_path``.
    """
    from deerflow.config.extensions_config import ExtensionsConfig

    try:
        return ExtensionsConfig.resolve_config_path()
    except FileNotFoundError:
        logger.debug("Extensions config path could not be resolved for a shared reset marker; treating as unconfigured", exc_info=True)
        return None


class SharedResetMarkerTracker:
    """Per-process observer of one :class:`SharedResetMarker`.

    ``poll()`` compares the marker against the last observed state at most once
    per ``poll_interval_seconds`` (monotonic clock) and reports a
    :class:`SharedResetChange` when the signature moved. The first poll adopts
    the current state silently: a process that has not cached anything yet has
    nothing to retire, and a restarted worker must not reset on the generation
    that was already current when it started.

    One instance per process is the production shape; tests build several so
    two "processes" can watch the same marker file, and ``reset()`` returns an
    instance to its never-polled state.
    """

    def __init__(
        self,
        marker: SharedResetMarker,
        *,
        resolve_config_path: Callable[[], Path | None] = resolve_shared_config_path,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds must not be negative")
        self._marker = marker
        self._resolve_config_path = resolve_config_path
        self._poll_interval = poll_interval_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self.reset()

    @property
    def marker(self) -> SharedResetMarker:
        return self._marker

    def reset(self) -> None:
        """Forget every observation; the next ``poll()`` adopts silently."""
        with self._lock:
            self._observed = False
            self._last_poll_at: float | None = None
            self._last_config_path: Path | None = None
            self._last_signature: ConfigSignature | None = None
            self._last_generation: str | None = None
            self._own_generations: list[str] = []

    def note_own_publication(self, generation: str) -> None:
        """Remember a generation this process published itself.

        The publishing process refreshes its own caches as part of the
        mutation, so observing its own marker later must not retire them
        again. An interleaved foreign publication still widens to a full reset
        because the chain of ``previous_generation`` values no longer matches.
        """
        with self._lock:
            self._own_generations.append(generation)
            del self._own_generations[:-_OWN_GENERATIONS_LIMIT]

    def poll(self) -> SharedResetChange | None:
        """Report a marker change since the previous poll, honoring the throttle.

        Never blocks on another thread's poll: a concurrent poller is already
        doing the stat, so this call returns ``None`` immediately and the
        caller serves its cache; the concurrent poller applies any change.
        """
        if not self._lock.acquire(blocking=False):
            return None
        try:
            now = self._clock()
            if self._last_poll_at is not None and now - self._last_poll_at < self._poll_interval:
                return None
            self._last_poll_at = now

            config_path = self._resolve_config_path()
            if config_path is None:
                payload, signature = None, None
            else:
                payload, signature = self._marker.read(config_path)

            if not self._observed:
                self._observed = True
                self._record(config_path, payload, signature)
                return None

            if config_path == self._last_config_path and signature == self._last_signature:
                return None

            change = self._classify(config_path, payload)
            self._record(config_path, payload, signature)
            return change
        finally:
            self._lock.release()

    def _record(self, config_path: Path | None, payload: SharedResetMarkerPayload | None, signature: ConfigSignature | None) -> None:
        self._last_config_path = config_path
        self._last_signature = signature
        self._last_generation = payload.generation if payload is not None else None

    def _classify(self, config_path: Path | None, payload: SharedResetMarkerPayload | None) -> SharedResetChange | None:
        generation = payload.generation if payload is not None else None
        # A config-path switch, a deleted marker or an unreadable one carry no
        # scope information: retire everything.
        if config_path != self._last_config_path or payload is None or generation is None:
            return SharedResetChange(user_ids=None, generation=generation)

        single_publication = payload.previous_generation == self._last_generation
        if generation in self._own_generations:
            self._own_generations.remove(generation)
            if single_publication:
                # Exactly one publication since the last poll, and it was ours.
                return None
            return SharedResetChange(user_ids=None, generation=generation)

        if single_publication and payload.user_id:
            return SharedResetChange(user_ids=frozenset({payload.user_id}), generation=generation)
        return SharedResetChange(user_ids=None, generation=generation)
