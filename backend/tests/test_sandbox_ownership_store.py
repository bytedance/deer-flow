"""Contract tests for the sandbox ownership store (#4206).

Every behavioural test here is **backend-agnostic**: it runs against each store
implementation through the same fixture, so the memory and redis backends cannot
drift apart on the semantics the provider depends on.

Redis coverage is opt-in and self-skipping, mirroring the stream-bridge
integration tier: point at a server with ``DEER_FLOW_TEST_REDIS_URL`` (defaults
to redis://localhost:6379/15 — DB 15 to avoid clobbering real data). There is no
fake-redis tier on purpose — the redis backend's exclusion lives in Lua scripts
that a hand-rolled fake would not execute, so a fake would pin the mock rather
than the script. When no server is reachable these skip and the memory backend
still covers the contract.
"""

from __future__ import annotations

import os
import threading
import time
import uuid

import pytest

from deerflow.community.aio_sandbox.ownership import (
    MemoryOwnershipStore,
    OwnershipBackendError,
    RenewOutcome,
    compute_lease_ttl,
    generate_owner_id,
    make_sandbox_ownership_store,
    resolve_ownership_config,
)
from deerflow.config.sandbox_config import SandboxOwnershipConfig
from deerflow.config.stream_bridge_config import StreamBridgeConfig

REDIS_TEST_URL = os.environ.get("DEER_FLOW_TEST_REDIS_URL", "redis://localhost:6379/15")


def _redis_available() -> bool:
    try:
        import redis
    except ImportError:
        return False
    try:
        client = redis.Redis.from_url(REDIS_TEST_URL, socket_connect_timeout=0.5)
        try:
            client.ping()
        finally:
            client.close()
        return True
    except Exception:
        return False


requires_redis = pytest.mark.skipif(not _redis_available(), reason=f"Redis not reachable at {REDIS_TEST_URL}")


class _StoreFactory:
    """Builds stores for one backend that all share the same keyspace."""

    def __init__(self, kind: str, ttl_seconds: float = 60.0):
        self.kind = kind
        self.ttl = ttl_seconds
        self._shared_leases: dict = {}
        self._key_prefix = f"deerflow:test:{uuid.uuid4().hex}"
        self._made: list = []

    def make(self, owner_id: str, *, ttl_seconds: float | None = None):
        ttl = self.ttl if ttl_seconds is None else ttl_seconds
        if self.kind == "memory":
            store = MemoryOwnershipStore(owner_id=owner_id, ttl_seconds=ttl)
            # Share one dict so separate store objects model separate instances
            # talking to one backend, as redis clients naturally do.
            store._leases = self._shared_leases
        else:
            from deerflow.community.aio_sandbox.ownership.redis import RedisOwnershipStore

            store = RedisOwnershipStore(
                owner_id=owner_id,
                redis_url=REDIS_TEST_URL,
                ttl_seconds=ttl,
                key_prefix=self._key_prefix,
            )
        self._made.append(store)
        return store

    def cleanup(self):
        if self.kind == "redis" and self._made:
            client = self._made[0]._redis
            for key in client.scan_iter(f"{self._key_prefix}:*"):
                client.delete(key)
        for store in self._made:
            store.close()


@pytest.fixture(params=["memory", pytest.param("redis", marks=[requires_redis, pytest.mark.integration])])
def stores(request):
    factory = _StoreFactory(request.param)
    try:
        yield factory
    finally:
        factory.cleanup()


# ── The #4206 invariant: a peer cannot claim a live owner's container ─────────


def test_claim_is_exclusive_across_instances(stores):
    a = stores.make("A")
    b = stores.make("B")

    assert a.claim("s1") is True
    assert b.claim("s1") is False, "a peer claimed a container A already owns — #4206"
    assert a.owner("s1") == "A"


def test_failed_claim_does_not_steal_the_lease(stores):
    a = stores.make("A")
    b = stores.make("B")
    a.claim("s1")

    b.claim("s1")

    assert a.owner("s1") == "A"


def test_claim_refreshes_our_own_lease(stores):
    a = stores.make("A")
    assert a.claim("s1") is True
    assert a.claim("s1") is True


def test_claim_succeeds_once_a_lease_expires(stores):
    """The crash path: a dead owner's container must become adoptable."""
    a = stores.make("A", ttl_seconds=0.2)
    b = stores.make("B")
    assert a.claim("s1") is True
    assert b.claim("s1") is False

    time.sleep(0.35)

    assert a.owner("s1") is None
    assert b.claim("s1") is True


# ── take(): ownership transfers when a thread moves instance ─────────────────


def test_take_transfers_ownership_from_a_live_peer(stores):
    a = stores.make("A")
    b = stores.make("B")
    a.claim("s1")

    assert b.take("s1") is True

    assert b.owner("s1") == "B"


def test_take_makes_the_previous_owners_renew_report_lost(stores):
    """How the previous owner learns to stop tracking the container."""
    a = stores.make("A")
    b = stores.make("B")
    a.claim("s1")
    b.take("s1")

    assert a.renew("s1") is RenewOutcome.LOST
    assert b.renew("s1") is RenewOutcome.RENEWED


# ── The destroy window: take() must not overrun a teardown ──────────────────


def test_take_is_refused_while_a_peer_is_destroying(stores):
    """#4206's remaining window: an unconditional take would overwrite a
    destroyer's claim, and the peer's container stop would then land on a
    container this instance had already handed to an agent."""
    a = stores.make("A")
    b = stores.make("B")
    assert a.claim("s1", for_destroy=True) is True

    assert b.take("s1") is False, "took over a container that is being destroyed"


def test_take_is_allowed_once_the_teardown_marker_is_released(stores):
    a = stores.make("A")
    b = stores.make("B")
    a.claim("s1", for_destroy=True)
    a.release("s1")

    assert b.take("s1") is True


def test_a_destroyers_own_claim_is_idempotent(stores):
    a = stores.make("A")
    assert a.claim("s1", for_destroy=True) is True
    assert a.claim("s1", for_destroy=True) is True


def test_claim_for_destroy_is_still_refused_against_a_peer(stores):
    a = stores.make("A")
    b = stores.make("B")
    a.claim("s1")

    assert b.claim("s1", for_destroy=True) is False


def test_a_stale_teardown_marker_expires(stores):
    """A destroyer that dies mid-stop must not block the container forever."""
    a = stores.make("A", ttl_seconds=0.2)
    b = stores.make("B")
    a.claim("s1", for_destroy=True)
    assert b.take("s1") is False

    time.sleep(0.35)

    assert b.take("s1") is True


def test_renew_does_not_keep_a_teardown_alive(stores):
    """A teardown marker is not a normal lease; renewal must not extend it."""
    a = stores.make("A")
    a.claim("s1", for_destroy=True)

    assert a.renew("s1") is RenewOutcome.LOST


# ── renew(): distinguishes lapsed from stolen ───────────────────────────────


def test_renew_reports_lapsed_not_lost_for_an_expired_lease(stores):
    """Collapsing these is what dropped every live sandbox on a Redis restart.

    Nobody took the lease — it is simply gone — so the caller is free to
    re-establish it. Reporting LOST would make the provider evict a container it
    is actively using.
    """
    a = stores.make("A", ttl_seconds=0.2)
    a.claim("s1")

    time.sleep(0.35)

    assert a.renew("s1") is RenewOutcome.LAPSED
    assert a.owner("s1") is None


def test_renew_does_not_reacquire_on_its_own(stores):
    """The caller decides; renew() never silently re-takes."""
    a = stores.make("A", ttl_seconds=0.2)
    a.claim("s1")
    time.sleep(0.35)

    a.renew("s1")

    assert a.owner("s1") is None, "renew() re-acquired a lapsed lease by itself"


def test_renew_extends_the_lease(stores):
    a = stores.make("A", ttl_seconds=0.4)
    b = stores.make("B")
    a.claim("s1")

    for _ in range(3):
        time.sleep(0.15)
        assert a.renew("s1") is RenewOutcome.RENEWED

    assert b.claim("s1") is False, "a renewed lease must keep peers out"


def test_renew_of_unknown_sandbox_is_lapsed(stores):
    a = stores.make("A")
    assert a.renew("never-claimed") is RenewOutcome.LAPSED


# ── release(): only ever drops our own ──────────────────────────────────────


def test_release_frees_the_container_for_a_peer(stores):
    a = stores.make("A")
    b = stores.make("B")
    a.claim("s1")

    a.release("s1")

    assert a.owner("s1") is None
    assert b.claim("s1") is True


def test_release_does_not_clear_a_peers_lease(stores):
    a = stores.make("A")
    b = stores.make("B")
    a.claim("s1")

    b.release("s1")

    assert a.owner("s1") == "A", "B released a lease it does not hold"


def test_release_of_unowned_sandbox_is_a_noop(stores):
    a = stores.make("A")
    a.release("never-claimed")


# ── owner(): read-only ──────────────────────────────────────────────────────


def test_owner_returns_none_when_unowned(stores):
    a = stores.make("A")
    assert a.owner("nobody") is None


def test_owner_does_not_take_ownership(stores):
    """Unlike claim(), a read must leave ownership untouched."""
    a = stores.make("A")
    b = stores.make("B")

    assert b.owner("s1") is None

    assert a.claim("s1") is True, "owner() took the lease as a side effect"


# ── Factory / config ────────────────────────────────────────────────────────


def test_memory_store_declares_it_cannot_see_peers():
    store = make_sandbox_ownership_store(SandboxOwnershipConfig(type="memory"), owner_id="A")
    assert store.supports_cross_process is False


def test_default_config_is_memory():
    store = make_sandbox_ownership_store(None, owner_id="A")
    assert isinstance(store, MemoryOwnershipStore)


def test_unknown_type_raises():
    config = SandboxOwnershipConfig()
    object.__setattr__(config, "type", "bogus")
    with pytest.raises(ValueError, match="Unknown sandbox ownership type"):
        make_sandbox_ownership_store(config, owner_id="A")


def test_ttl_derives_from_renewal_interval_not_idle_timeout():
    """The coupling that let leases lapse under idle_timeout: 0 must stay broken."""
    config = SandboxOwnershipConfig(renewal_interval_seconds=30, ttl_multiplier=4)
    assert compute_lease_ttl(config) == 120


def test_ttl_tolerates_missed_renewals():
    """A single slow renewal cycle must not expire a live owner's lease."""
    config = SandboxOwnershipConfig()
    assert compute_lease_ttl(config) > config.renewal_interval_seconds * 2


def test_ttl_multiplier_below_two_is_rejected():
    with pytest.raises(ValueError):
        SandboxOwnershipConfig(ttl_multiplier=1.0)


def test_owner_ids_are_unique_per_instance():
    """Two workers on one host must not share an owner id."""
    assert generate_owner_id() != generate_owner_id()


def test_stream_bridge_redis_env_implies_redis_ownership(monkeypatch):
    """A deployment already using redis for the stream bridge is multi-instance.

    Defaulting it to memory ownership would leave #4206 open on exactly the
    deployments that hit it.
    """
    monkeypatch.setenv("DEER_FLOW_STREAM_BRIDGE_REDIS_URL", "redis://somewhere:6379/0")
    resolved = resolve_ownership_config(None)
    assert resolved.type == "redis"
    assert resolved.redis_url == "redis://somewhere:6379/0"


def test_stream_bridge_redis_in_config_yaml_implies_redis_ownership(monkeypatch):
    """The config.yaml-native way of using redis must trigger the inference too.

    The stream bridge's own resolver reads `app_config.stream_bridge` *before*
    the env var, so inferring only from the env var missed every deployment that
    configures the bridge in config.yaml — i.e. exactly the multi-instance
    deployments this inference exists for.
    """
    monkeypatch.delenv("DEER_FLOW_STREAM_BRIDGE_REDIS_URL", raising=False)
    monkeypatch.delenv("DEER_FLOW_SANDBOX_OWNERSHIP_REDIS_URL", raising=False)

    resolved = resolve_ownership_config(None, stream_bridge=StreamBridgeConfig(type="redis", redis_url="redis://in-yaml:6379/0"))

    assert resolved.type == "redis"
    assert resolved.redis_url == "redis://in-yaml:6379/0"


def test_memory_stream_bridge_does_not_imply_redis_ownership(monkeypatch):
    """The other direction: a single-process bridge must not force redis."""
    monkeypatch.delenv("DEER_FLOW_STREAM_BRIDGE_REDIS_URL", raising=False)
    monkeypatch.delenv("DEER_FLOW_SANDBOX_OWNERSHIP_REDIS_URL", raising=False)

    resolved = resolve_ownership_config(None, stream_bridge=StreamBridgeConfig(type="memory"))

    assert resolved.type == "memory"


def test_explicit_config_wins_over_env(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_STREAM_BRIDGE_REDIS_URL", "redis://somewhere:6379/0")
    resolved = resolve_ownership_config(SandboxOwnershipConfig(type="memory"))
    assert resolved.type == "memory"


def test_no_env_defaults_to_memory(monkeypatch):
    monkeypatch.delenv("DEER_FLOW_STREAM_BRIDGE_REDIS_URL", raising=False)
    monkeypatch.delenv("DEER_FLOW_SANDBOX_OWNERSHIP_REDIS_URL", raising=False)
    assert resolve_ownership_config(None).type == "memory"


# ── Redis-specific: failure surfaces as OwnershipBackendError ───────────────


def test_redis_backend_error_is_wrapped_not_leaked():
    """Callers fail closed on OwnershipBackendError; a raw RedisError would escape that.

    Deliberately **not** marked `integration`/`requires_redis`: it points at a
    dead port, so it needs no server — only the `redis` package, which is pinned
    in the dev group. Gating it on a live Redis would mean the fail-closed
    contract was never exercised in CI, which is the one place it matters.
    """
    from deerflow.community.aio_sandbox.ownership.redis import RedisOwnershipStore

    store = RedisOwnershipStore(
        owner_id="A",
        redis_url="redis://127.0.0.1:1/0",  # nothing listening
        ttl_seconds=60,
        key_prefix=f"deerflow:test:{uuid.uuid4().hex}",
    )
    with pytest.raises(OwnershipBackendError):
        store.claim("s1")
    with pytest.raises(OwnershipBackendError):
        store.claim("s1", for_destroy=True)
    with pytest.raises(OwnershipBackendError):
        store.take("s1")
    with pytest.raises(OwnershipBackendError):
        store.renew("s1")
    with pytest.raises(OwnershipBackendError):
        store.release("s1")
    with pytest.raises(OwnershipBackendError):
        store.owner("s1")


def test_non_destroy_claim_does_not_unwind_our_own_teardown(stores):
    """A `for_destroy=False` claim must not downgrade our own `del:` marker.

    The stop it marks is already in flight and cannot be recalled, so turning the
    lease back into `own:` would let a `take()` hand out a container that is
    about to die — the #4206 failure, self-inflicted. No caller does this today
    (the non-destroy callers run against an absent or unowned key), but the
    contract has to forbid it rather than rely on that staying true.

    Runs against both backends on purpose: the redis rule lives in Lua and the
    memory rule in Python, so a fix applied to one only would drift silently.
    """
    a = stores.make("A")

    assert a.claim("s1", for_destroy=True) is True
    assert a.claim("s1") is False, "a non-destroy claim unwound our own in-flight teardown"
    # Still a teardown: the marker survived the refused claim intact.
    assert a.renew("s1") is RenewOutcome.LOST
    b = stores.make("B")
    assert b.take("s1") is False, "the teardown marker stopped refusing takes"

    # Refreshing the teardown itself is still allowed — that is the heartbeat.
    assert a.claim("s1", for_destroy=True) is True


def test_concurrent_claims_serialize_to_one_winner(stores):
    """The exclusion must hold under contention, not just in sequence.

    The rest of this suite drives sequential calls, so it pins the predicate and
    not the atomicity the predicate depends on — redis carries it in Lua, the
    memory store in a process lock. Eight instances race for one container; the
    read-modify-write is only atomic if exactly one wins.
    """
    barrier = threading.Barrier(8)
    results = {}
    lock = threading.Lock()

    def contend(name):
        store = stores.make(name)
        barrier.wait(timeout=5)
        won = store.claim("s1")
        with lock:
            results[name] = won

    threads = [threading.Thread(target=contend, args=(f"W{i}",), daemon=True) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
        assert not t.is_alive(), "a contending claim never finished"

    winners = [name for name, won in results.items() if won]
    assert len(winners) == 1, f"claim is not atomic under contention: {len(winners)} winners ({winners})"


@pytest.mark.integration
@requires_redis
def test_redis_store_declares_cross_process_support():
    from deerflow.community.aio_sandbox.ownership.redis import RedisOwnershipStore

    store = RedisOwnershipStore(owner_id="A", redis_url=REDIS_TEST_URL, ttl_seconds=60, key_prefix=f"deerflow:test:{uuid.uuid4().hex}")
    try:
        assert store.supports_cross_process is True
    finally:
        store.close()
