"""Redis integration tests for deployment-wide E2B admission."""

from __future__ import annotations

import os
import threading
import uuid

import pytest

from deerflow.community.e2b_sandbox.capacity import (
    CapacityBackendError,
    ReserveStatus,
    make_e2b_capacity_store,
)
from deerflow.config.sandbox_config import SandboxOwnershipConfig

REDIS_TEST_URL = os.environ.get(
    "DEER_FLOW_TEST_REDIS_URL",
    "redis://localhost:6379/15",
)


def _redis_available() -> bool:
    try:
        import redis
    except ImportError:
        return False
    try:
        client = redis.Redis.from_url(
            REDIS_TEST_URL,
            socket_connect_timeout=0.5,
        )
        try:
            client.ping()
        finally:
            client.close()
        return True
    except Exception:
        return False


requires_redis = pytest.mark.skipif(
    not _redis_available(),
    reason=f"Redis not reachable at {REDIS_TEST_URL}",
)


class _RedisStores:
    def __init__(self, *, hard_limit: int = 1) -> None:
        self.hard_limit = hard_limit
        self.key_prefix = f"deerflow:test:{uuid.uuid4().hex}"
        self.made = []

    def make(self, *, hard_limit: int | None = None):
        from deerflow.community.e2b_sandbox.capacity.redis import (
            RedisE2BCapacityStore,
        )

        store = RedisE2BCapacityStore(
            redis_url=REDIS_TEST_URL,
            hard_limit=hard_limit or self.hard_limit,
            key_prefix=self.key_prefix,
        )
        self.made.append(store)
        return store

    def cleanup(self) -> None:
        if self.made:
            self.made[0]._redis.delete(self.made[0].key)
        for store in self.made:
            store.close()


@pytest.fixture
def redis_stores():
    stores = _RedisStores()
    try:
        yield stores
    finally:
        stores.cleanup()


def _initialize(store) -> None:
    assert store.reconcile(
        expected_revision=store.revision(),
        remote_sandboxes={},
        complete=True,
        stale_reservation_before_ms=0,
    )


def _ledger_counts(store) -> tuple[int, int]:
    fields = store._redis.hkeys(store.key)
    return (
        sum(field.startswith("s:") for field in fields),
        sum(field.startswith("r:") for field in fields),
    )


def test_factory_keeps_memory_mode_local_and_builds_one_redis_scope() -> None:
    assert (
        make_e2b_capacity_store(
            SandboxOwnershipConfig(type="memory"),
            hard_limit=3,
        )
        is None
    )

    store = make_e2b_capacity_store(
        SandboxOwnershipConfig(
            type="redis",
            redis_url="redis://127.0.0.1:1/0",
            key_prefix="deerflow:test",
        ),
        hard_limit=3,
    )
    assert store is not None
    try:
        assert store.key == "deerflow:test:e2b-capacity"
    finally:
        store.close()


def test_redis_backend_error_is_wrapped_and_admission_fails_closed() -> None:
    from deerflow.community.e2b_sandbox.capacity.redis import (
        RedisE2BCapacityStore,
    )

    store = RedisE2BCapacityStore(
        redis_url="redis://127.0.0.1:1/0",
        hard_limit=1,
        key_prefix=f"deerflow:test:{uuid.uuid4().hex}",
    )
    try:
        with pytest.raises(CapacityBackendError):
            store.reserve("reservation-1")
    finally:
        store.close()


@pytest.mark.integration
@requires_redis
def test_scope_is_initialized_in_one_redis_hash(redis_stores) -> None:
    store = redis_stores.make()
    _initialize(store)

    assert store._redis.type(store.key) in {"hash", b"hash"}
    assert list(store._redis.scan_iter(f"{redis_stores.key_prefix}:*")) == [store.key]


@pytest.mark.integration
@requires_redis
def test_two_gateways_atomically_share_the_hard_limit(redis_stores) -> None:
    gateway_a = redis_stores.make()
    gateway_b = redis_stores.make()
    _initialize(gateway_a)
    barrier = threading.Barrier(3, timeout=5)
    results: list[ReserveStatus | Exception] = []
    lock = threading.Lock()

    def reserve(store, token: str) -> None:
        barrier.wait()
        try:
            result = store.reserve(token)
        except Exception as error:
            result = error
        with lock:
            results.append(result)

    threads = [
        threading.Thread(target=reserve, args=(gateway_a, "reservation-a")),
        threading.Thread(target=reserve, args=(gateway_b, "reservation-b")),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert results.count(ReserveStatus.GRANTED) == 1
    assert results.count(ReserveStatus.FULL) == 1
    assert sum(_ledger_counts(gateway_a)) == 1


@pytest.mark.integration
@requires_redis
def test_inventory_cannot_erase_a_concurrent_reservation(redis_stores) -> None:
    gateway_a = redis_stores.make()
    gateway_b = redis_stores.make()
    _initialize(gateway_a)
    inventory_revision = gateway_a.revision()

    assert gateway_b.reserve("reservation-b") is ReserveStatus.GRANTED
    status = gateway_a.reconcile(
        expected_revision=inventory_revision,
        remote_sandboxes={},
        complete=True,
        stale_reservation_before_ms=10**15,
    )

    assert status is False
    assert _ledger_counts(gateway_a) == (0, 1)


@pytest.mark.integration
@requires_redis
def test_inventory_repairs_a_crash_between_create_and_commit(
    redis_stores,
) -> None:
    gateway_a = redis_stores.make()
    gateway_b = redis_stores.make()
    _initialize(gateway_a)
    assert gateway_a.reserve("reservation-a") is ReserveStatus.GRANTED
    inventory_revision = gateway_b.revision()

    assert gateway_b.reconcile(
        expected_revision=inventory_revision,
        remote_sandboxes={"sandbox-a": "reservation-a"},
        complete=True,
        stale_reservation_before_ms=0,
    )
    assert _ledger_counts(gateway_a) == (1, 0)


@pytest.mark.integration
@requires_redis
def test_track_and_release_are_idempotent(redis_stores) -> None:
    store = redis_stores.make()
    _initialize(store)

    assert store.reserve("committed") is ReserveStatus.GRANTED
    store.track("sandbox-a", reservation_token="committed")
    store.track("sandbox-a", reservation_token="committed")
    assert _ledger_counts(store) == (1, 0)

    store.release("sandbox-a")
    store.release("sandbox-a")
    assert _ledger_counts(store) == (0, 0)


@pytest.mark.integration
@requires_redis
def test_incomplete_inventory_never_removes_capacity(redis_stores) -> None:
    store = redis_stores.make()
    _initialize(store)
    store.track("sandbox-a")
    inventory_revision = store.revision()

    store.reconcile(
        expected_revision=inventory_revision,
        remote_sandboxes={},
        complete=False,
        stale_reservation_before_ms=10**15,
    )

    assert _ledger_counts(store) == (1, 0)


@pytest.mark.integration
@requires_redis
def test_workers_with_different_limits_fail_closed(redis_stores) -> None:
    gateway_a = redis_stores.make()
    _initialize(gateway_a)
    gateway_b = redis_stores.make(hard_limit=2)

    with pytest.raises(CapacityBackendError, match="configuration mismatch"):
        gateway_b.revision()
    with pytest.raises(CapacityBackendError, match="configuration mismatch"):
        gateway_b.reserve("reservation-b")
