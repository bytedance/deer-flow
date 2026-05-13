"""In-memory TTL cache for http_connector responses."""

from __future__ import annotations

import hashlib
import json
import time
import threading
from dataclasses import dataclass, field


@dataclass
class _CacheEntry:
    value: str
    expires_at: float


class HttpConnectorCache:
    """Thread-safe in-memory cache with per-entry TTL."""

    def __init__(self, max_entries: int = 256) -> None:
        self._store: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()
        self._max_entries = max_entries

    def _make_key(self, tenant_id: str, connector_name: str, params: dict | None, body: dict | None) -> str:
        raw = json.dumps({"t": tenant_id, "c": connector_name, "p": params, "b": body}, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, tenant_id: str, connector_name: str, params: dict | None, body: dict | None) -> str | None:
        key = self._make_key(tenant_id, connector_name, params, body)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if time.monotonic() > entry.expires_at:
                del self._store[key]
                return None
            return entry.value

    def put(self, tenant_id: str, connector_name: str, params: dict | None, body: dict | None, value: str, ttl_seconds: int) -> None:
        key = self._make_key(tenant_id, connector_name, params, body)
        expires_at = time.monotonic() + ttl_seconds
        with self._lock:
            if len(self._store) >= self._max_entries:
                self._evict_expired()
            if len(self._store) >= self._max_entries:
                oldest_key = min(self._store, key=lambda k: self._store[k].expires_at)
                del self._store[oldest_key]
            self._store[key] = _CacheEntry(value=value, expires_at=expires_at)

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, v in self._store.items() if now > v.expires_at]
        for k in expired:
            del self._store[k]

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_connector_cache = HttpConnectorCache()


def get_connector_cache() -> HttpConnectorCache:
    return _connector_cache
