"""In-process projection cache keyed by a cheap content fingerprint (spec §6 P3).

The fingerprint is recomputed on every request — a cheap DB digest over
per-table count + max-timestamp signals — and decides everything: a matching
fingerprint serves the stored entry without recomputing; any difference (or
``refresh=True``) recomputes and replaces. Concurrent misses for the same key
collapse into a single fetch+reduce behind a per-key lock, so a KB being
viewed by many clients at once never triggers a thundering herd of SVDs.

No persistence on purpose (spec §6 权衡): a cold restart simply recomputes on
first view — seconds for a 10k-point KB — and no new migration is needed.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class CachedProjection:
    """One cached projection entry: coordinates + fitted model + metadata.

    ``fingerprint`` / ``created_at`` are filled by the cache itself, not by
    the compute callable; ``cached`` is always ``False`` on stored entries
    and only flipped on the way out for fingerprint hits.
    """

    coords: Any  # np.ndarray (n, dims)
    points: tuple  # tuple[ProjectionPoint, ...]
    model: Any | None = None  # PCAModel (None for umap — no stable transform)
    total_points: int = 0
    sampled: bool = False
    computed_ms: int = 0
    fingerprint: str = ""
    created_at: float = 0.0
    cached: bool = False


def content_fingerprint(stats: dict[str, Any]) -> str:
    """Serialize the per-table invalidation signals into a short digest.

    Signal layout (spec §6): chunks ``count + max(last_edited_at)`` (the table
    has no created_at — count alone covers insert/delete), wiki/cards
    ``count + max(updated_at)``, entities ``count`` only (count-only stale
    edge documented in the spec; ``refresh=true`` is the escape hatch).
    """

    def _ts(value: Any) -> str:
        return value.isoformat() if isinstance(value, datetime) else "-"

    chunks_count, chunks_max = stats["chunks"]
    wiki_count, wiki_max = stats["wiki"]
    cards_count, cards_max = stats["cards"]
    raw = "|".join(
        [
            f"chunks:{chunks_count}:{_ts(chunks_max)}",
            f"wiki:{wiki_count}:{_ts(wiki_max)}",
            f"cards:{cards_count}:{_ts(cards_max)}",
            f"entities:{stats['entities']}",
        ]
    )
    return f"sha1:{hashlib.sha1(raw.encode()).hexdigest()[:16]}"


class ProjectionCache:
    """Process-local cache ``{(kb_id, algo, dims, sample_size): entry}``."""

    def __init__(self) -> None:
        self._entries: dict[tuple, CachedProjection] = {}
        self._locks: dict[tuple, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    def peek(self, key: tuple) -> CachedProjection | None:
        """Read-only lookup for the query-transform endpoint — never computes."""
        return self._entries.get(key)

    async def _lock_for(self, key: tuple) -> asyncio.Lock:
        async with self._guard:
            return self._locks.setdefault(key, asyncio.Lock())

    async def get_or_compute(
        self,
        key: tuple,
        *,
        fingerprint: str,
        refresh: bool = False,
        compute: Callable[[], Awaitable[CachedProjection]],
    ) -> CachedProjection:
        """Serve the cached entry when the fingerprint matches, else compute.

        Double-checked under the per-key lock: concurrent misses see exactly
        one computation; the losers of the race return the fresh entry.
        """
        entry = self._entries.get(key)
        if not refresh and entry is not None and entry.fingerprint == fingerprint:
            return replace(entry, cached=True)
        async with await self._lock_for(key):
            entry = self._entries.get(key)
            if not refresh and entry is not None and entry.fingerprint == fingerprint:
                return replace(entry, cached=True)
            fresh = await compute()
            stored = replace(fresh, fingerprint=fingerprint, created_at=time.time(), cached=False)
            self._entries[key] = stored
            return stored
