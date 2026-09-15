"""Inbound webhook dedupe store.

The manager-level inbound dedupe (``ChannelManager._inbound_dedupe_key``) guards an
agent run / final answer against provider redeliveries. The default store is an
in-process ``OrderedDict`` (backward compatible, single-pod). A shared store (e.g.
Postgres) can be injected for multi-pod deployments so a redelivery landing on a
different pod is still dropped as a duplicate. See issue #4120.
"""

from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict
from typing import Any, Protocol

from sqlalchemy import text

logger = logging.getLogger(__name__)

INBOUND_DEDUPE_TTL_SECONDS = 10 * 60
INBOUND_DEDUPE_MAX_ENTRIES = 4096

# Key tuple matches ChannelManager._inbound_dedupe_key:
# (channel_name, workspace_id, chat_id, message_id).
InboundDedupeKey = tuple[str, str, str, str]


class InboundDedupeStore(Protocol):
    """Async contract for recording / releasing inbound dedupe keys.

    ``try_record`` returns ``True`` if the key already existed (duplicate -> drop)
    and ``False`` if it was newly recorded or its prior entry had expired (proceed).
    Shared-state implementations must be atomic; the Postgres variant uses a single
    conditional upsert (``INSERT ... ON CONFLICT DO UPDATE ... WHERE first_seen < TTL``).
    """

    async def try_record(self, key: InboundDedupeKey) -> bool: ...
    async def release(self, key: InboundDedupeKey) -> None: ...


class MemoryInboundDedupeStore:
    """Process-local ``OrderedDict`` store — preserves the pre-#4120 behavior exactly."""

    def __init__(
        self,
        ttl_seconds: int = INBOUND_DEDUPE_TTL_SECONDS,
        max_entries: int = INBOUND_DEDUPE_MAX_ENTRIES,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        # Insertion order == chronological (keys are never re-inserted), so an
        # OrderedDict lets us evict expired/overflow entries from the front in
        # O(k) instead of scanning all entries on every inbound message.
        self._store: OrderedDict[InboundDedupeKey, float] = OrderedDict()

    async def try_record(self, key: InboundDedupeKey) -> bool:
        now = time.monotonic()
        # Entries are in chronological insertion order, so expired ones cluster at
        # the front: pop from the front until we hit a still-live entry.
        while self._store:
            _, oldest_at = next(iter(self._store.items()))
            if now - oldest_at > self._ttl:
                self._store.popitem(last=False)
            else:
                break
        while len(self._store) > self._max:
            self._store.popitem(last=False)

        if key in self._store:
            return True

        self._store[key] = now
        return False

    async def release(self, key: InboundDedupeKey) -> None:
        self._store.pop(key, None)


class PostgresInboundDedupeStore:
    """Shared Postgres-backed dedupe store (issue #4120).

    One row per dispatched inbound webhook (keyed by the 4-tuple). A redelivery
    routed to a different gateway pod hits the same table. The acquire is a single
    atomic conditional upsert:

        INSERT ... ON CONFLICT (4-tuple) DO UPDATE SET first_seen = now()
        WHERE first_seen < now() - TTL RETURNING channel

    - No conflict -> row inserted -> proceed.
    - Conflict + expired row -> DO UPDATE refreshes ``first_seen``, row RETURNED ->
      proceed (honors the 10-minute ceiling and re-admits a never-released/expired
      redelivery, e.g. a manual provider "Redeliver").
    - Conflict + live row -> WHERE fails, no row RETURNED -> drop as duplicate.

    Because the upsert is a single row-locked statement, two pods racing on the same
    expired key cannot both proceed (one wins the update; the other sees the fresh row
    and is dropped). Lazy cleanup (``DELETE`` of rows older than the TTL) runs in the
    same transaction, amortized into the proceed path with no background task.

    Fail-open: any DB error is logged and treated as "allow" so a storage
    outage never drops a webhook or returns 5xx to the provider.
    """

    def __init__(self, session_factory: Any | None = None) -> None:
        # Injected in tests; otherwise resolved lazily from the app engine.
        self._session_factory = session_factory

    def _resolve_session_factory(self) -> Any:
        if self._session_factory is not None:
            return self._session_factory
        from deerflow.persistence.engine import get_session_factory

        sf = get_session_factory()
        if sf is None:
            raise RuntimeError("PostgresInboundDedupeStore requires a Postgres session factory")
        return sf

    async def try_record(self, key: InboundDedupeKey) -> bool:
        channel, workspace_id, chat_id, message_id = key
        try:
            sf = self._resolve_session_factory()
            async with sf() as session:
                async with session.begin():
                    # Atomic acquire + TTL reclamation in ONE row-locked statement.
                    #
                    # - No conflict  -> new row inserted, RETURNING a row -> proceed.
                    # - Conflict + the existing row is EXPIRED (first_seen older than
                    #   the TTL) -> DO UPDATE refreshes first_seen to now() and the row
                    #   is RETURNED, so the redelivery is re-admitted (proceed). This is
                    #   the cross-pod-safe equivalent of the memory store's "evict
                    #   expired entries before the membership check", and it honors the
                    #   10-minute ceiling of issue #4120 even for a row that was never
                    #   released (e.g. a crashed run): a manual provider "Redeliver" of
                    #   an old message is re-admitted instead of being dropped forever
                    #   in a quiet deployment.
                    # - Conflict + the existing row is still LIVE -> the WHERE fails, no
                    #   UPDATE, no row RETURNED -> duplicate -> drop.
                    #
                    # A single conditional upsert has no TOCTOU window (unlike a separate
                    # DELETE-then-INSERT), so two pods racing on the same expired key
                    # cannot both proceed: one wins the update and proceeds, the other
                    # sees the now-fresh row and is dropped.
                    result = await session.execute(
                        text(
                            "INSERT INTO webhook_deliveries "
                            "(channel, workspace_id, chat_id, message_id, first_seen) "
                            "VALUES (:c, :w, :ch, :m, now()) "
                            "ON CONFLICT (channel, workspace_id, chat_id, message_id) "
                            "DO UPDATE SET first_seen = now() "
                            "WHERE webhook_deliveries.first_seen < now() - make_interval(secs => :ttl) "
                            "RETURNING channel"
                        ),
                        {
                            "c": channel,
                            "w": workspace_id,
                            "ch": chat_id,
                            "m": message_id,
                            "ttl": INBOUND_DEDUPE_TTL_SECONDS,
                        },
                    )
                    # A returned row means the key was admitted (new delivery, or an
                    # expired row that was re-admitted). No row means a live duplicate
                    # that must be dropped. RETURNING (not rowcount) is used because
                    # rowcount reliability for ON CONFLICT DO NOTHING/DO UPDATE varies
                    # across DB drivers.
                    inserted = result.fetchone() is not None
                    # Lazy cleanup in the same transaction: drop rows older than the
                    # TTL. Only when a row was admitted (proceed path) so the periodic
                    # sweep is amortized into normal inbound traffic and keys never
                    # re-accessed still get reclaimed.
                    if inserted:
                        await session.execute(
                            text("DELETE FROM webhook_deliveries WHERE first_seen < now() - make_interval(secs => :ttl)"),
                            {"ttl": INBOUND_DEDUPE_TTL_SECONDS},
                        )
            # inserted=True -> admitted (proceed, not a duplicate).
            return not inserted
        except Exception:
            # Fail-open: if the store is unavailable we must NOT drop the
            # message. Return False so the caller treats it as a new delivery
            # and proceeds (at worst a possible duplicate, never silent loss).
            logger.exception("PostgresInboundDedupeStore.try_record failed; proceeding without dedupe (fail-open)")
            return False

    async def release(self, key: InboundDedupeKey) -> None:
        channel, workspace_id, chat_id, message_id = key
        try:
            sf = self._resolve_session_factory()
            async with sf() as session:
                async with session.begin():
                    await session.execute(
                        text("DELETE FROM webhook_deliveries WHERE channel = :c AND workspace_id = :w AND chat_id = :ch AND message_id = :m"),
                        {"c": channel, "w": workspace_id, "ch": chat_id, "m": message_id},
                    )
        except Exception:
            logger.exception("PostgresInboundDedupeStore.release failed; key left for TTL expiry (fail-open)")


def _gateway_workers() -> int:
    """Mirror deps._enforce_postgres_for_multi_worker's worker detection."""
    try:
        return int(os.environ.get("GATEWAY_WORKERS", "1") or 1)
    except (TypeError, ValueError):
        return 1


def _build_postgres_store() -> InboundDedupeStore:
    """Build the shared Postgres dedupe store."""
    return PostgresInboundDedupeStore()


def make_inbound_dedupe_store(app_config: Any | None = None) -> InboundDedupeStore:
    """Resolve the inbound dedupe store from app config.

    - ``memory`` -> in-process store (per-pod; a redelivery routed to a different
      replica is NOT deduped).
    - ``postgres`` -> shared Postgres store. Requires ``database.backend='postgres'``;
      if the application DB is not Postgres the store falls back to the in-process
      memory store and logs a WARNING (otherwise cross-pod dedupe would be silently
      disabled).
    - ``auto`` (default) -> shared Postgres store whenever the application DB is
      Postgres. This is the recommended setting for any deployment that may run more
      than one replica, including Kubernetes with ``GATEWAY_WORKERS=1`` per pod where
      multiple pods still share the single Postgres DB. For non-Postgres DBs ``auto``
      falls back to the cheaper in-process memory store (correct for a single-DB,
      single-pod deployment).

    Emits a WARNING when a multi-worker/multi-replica deployment cannot use the shared
    Postgres store (the cross-pod dedupe gap becomes an explicit misconfiguration
    rather than silent default behavior).
    """
    backend = "auto"
    db_is_postgres = False
    db_backend = None
    if app_config is not None:
        dedupe_cfg = getattr(app_config, "dedupe_storage", None)
        if dedupe_cfg is not None:
            backend = str(dedupe_cfg.backend.value if hasattr(dedupe_cfg.backend, "value") else dedupe_cfg.backend)
        db = getattr(app_config, "database", None)
        db_backend = getattr(db, "backend", None)
        db_is_postgres = db_backend == "postgres"

    multi_worker = _gateway_workers() > 1

    if backend == "postgres":
        if not db_is_postgres:
            logger.warning(
                "dedupe_storage=postgres requires database.backend='postgres' (got '%s'). Falling back to the in-process memory store; inbound webhook dedupe is per-pod and cross-pod redeliveries will NOT be deduped. See issue #4120.",
                db_backend,
            )
            return MemoryInboundDedupeStore()
        return _build_postgres_store()
    if backend == "memory":
        if multi_worker:
            logger.warning(
                "dedupe_storage=memory with GATEWAY_WORKERS>1: inbound webhook dedupe "
                "is per-pod and will NOT drop redeliveries routed to a different replica. "
                "Use dedupe_storage=postgres (or remove the setting to let 'auto' pick it) "
                "for multi-worker deployments. See issue #4120."
            )
        return MemoryInboundDedupeStore()
    # auto
    if db_is_postgres:
        logger.info("dedupe_storage=auto resolved to the shared Postgres store (database.backend=postgres); inbound webhook dedupe is shared across pods.")
        return _build_postgres_store()
    if multi_worker:
        logger.warning(
            "Multi-worker deployment detected but dedupe_storage=auto resolved to the "
            "in-process memory store (application database is not Postgres). Inbound "
            "webhook dedupe is per-pod and will NOT drop redeliveries routed to a different "
            "replica. Set database.backend=postgres (required for multi-worker) so dedupe "
            "shares state across pods. See issue #4120."
        )
    return MemoryInboundDedupeStore()
