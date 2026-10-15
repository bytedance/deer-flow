"""Integration tests for deployment-wide E2B admission."""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from deerflow.community.e2b_sandbox.capacity import (
    CapacityBackendError,
    RedisE2BCapacityStore,
    ReserveStatus,
    make_e2b_capacity_store,
)
from deerflow.config.sandbox_config import SandboxOwnershipConfig

REDIS_URL = os.environ.get("DEER_FLOW_TEST_REDIS_URL", "redis://localhost:6379/15")
pytestmark = pytest.mark.integration


@pytest.fixture
def make_store():
    redis = pytest.importorskip("redis")
    probe = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=0.5)
    try:
        probe.ping()
    except Exception:
        probe.close()
        pytest.skip(f"Redis not reachable at {REDIS_URL}")

    prefix = f"deerflow:test:{uuid.uuid4().hex}"
    stores = []

    def make(hard_limit: int = 1):
        store = RedisE2BCapacityStore(
            redis_url=REDIS_URL,
            hard_limit=hard_limit,
            key_prefix=prefix,
        )
        stores.append(store)
        return store

    try:
        yield make
    finally:
        probe.delete(f"{prefix}:e2b-capacity")
        probe.close()
        for store in stores:
            store.close()


def _initialize(store) -> None:
    assert store.reconcile(
        expected_revision=store.revision(),
        remote_sandboxes={},
        complete=True,
        reservation_max_age_ms=0,
    )


def _counts(store) -> tuple[int, int]:
    fields = store._redis.hkeys(store.key)
    return (
        sum(field.startswith("s:") for field in fields),
        sum(field.startswith("r:") for field in fields),
    )


def test_factory_is_lazy_and_backend_errors_fail_closed() -> None:
    assert make_e2b_capacity_store(SandboxOwnershipConfig(type="memory"), hard_limit=3) is None
    store = make_e2b_capacity_store(
        SandboxOwnershipConfig(type="redis", redis_url="redis://127.0.0.1:1/0", key_prefix="test"),
        hard_limit=3,
    )
    assert store is not None and store.key == "test:e2b-capacity"
    try:
        with pytest.raises(CapacityBackendError):
            store.reserve("reservation")
    finally:
        store.close()


def test_two_gateways_atomically_share_one_hash(make_store) -> None:
    gateway_a, gateway_b = make_store(), make_store()
    assert gateway_a.reserve("not-ready") is ReserveStatus.NOT_READY
    _initialize(gateway_a)
    barrier = threading.Barrier(2)

    def reserve(args):
        store, token = args
        barrier.wait()
        return store.reserve(token)

    tokens = ["reservation-a", "reservation-b"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, zip((gateway_a, gateway_b), tokens)))

    assert results.count(ReserveStatus.GRANTED) == 1
    assert results.count(ReserveStatus.FULL) == 1
    assert list(gateway_a._redis.scan_iter(f"{gateway_a.key}")) == [gateway_a.key]
    winner = tokens[results.index(ReserveStatus.GRANTED)]
    gateway_a.track("sandbox-a", reservation_token=winner)
    gateway_a.track("sandbox-a", reservation_token=winner)
    assert _counts(gateway_a) == (1, 0)
    # A successful but stale list must not release a just-tracked slot.
    assert gateway_b.reconcile(
        expected_revision=gateway_b.revision(),
        remote_sandboxes={},
        complete=True,
        reservation_max_age_ms=120_000,
    )
    assert gateway_b.reserve("stale-inventory") is ReserveStatus.FULL
    gateway_b.release("sandbox-a")
    gateway_b.release("sandbox-a")
    assert _counts(gateway_a) == (0, 0)


def test_reconcile_repairs_crashes_without_erasing_concurrent_changes(make_store) -> None:
    gateway_a, gateway_b = make_store(2), make_store(2)
    _initialize(gateway_a)
    assert gateway_a.reserve("crashed-create") is ReserveStatus.GRANTED
    assert gateway_b.reconcile(
        expected_revision=gateway_b.revision(),
        remote_sandboxes={"sandbox-a": "crashed-create"},
        complete=True,
        reservation_max_age_ms=0,
    )
    stale_revision = gateway_a.revision()
    assert gateway_b.reserve("concurrent") is ReserveStatus.GRANTED
    assert not gateway_a.reconcile(
        expected_revision=stale_revision,
        remote_sandboxes={},
        complete=True,
        reservation_max_age_ms=0,
    )
    assert _counts(gateway_a) == (1, 1)


def test_reconcile_keeps_incomplete_inventory_and_fresh_reservations(make_store) -> None:
    store = make_store(2)
    _initialize(store)
    store.track("sandbox-a")
    assert store.reserve("creating") is ReserveStatus.GRANTED

    assert store.reconcile(
        expected_revision=store.revision(),
        remote_sandboxes={},
        complete=False,
        reservation_max_age_ms=0,
    )
    assert _counts(store) == (1, 1)
    assert store.reconcile(
        expected_revision=store.revision(),
        remote_sandboxes={"sandbox-a": None},
        complete=True,
        reservation_max_age_ms=120_000,
    )
    assert _counts(store) == (1, 1)
    store._redis.hset(store.key, "s:sandbox-a", "m:0")
    assert store.reconcile(
        expected_revision=store.revision(),
        remote_sandboxes={},
        complete=True,
        reservation_max_age_ms=0,
    )
    assert _counts(store) == (0, 0)


def test_mismatched_hard_limits_fail_closed(make_store) -> None:
    gateway_a, gateway_b = make_store(), make_store(2)
    _initialize(gateway_a)
    with pytest.raises(CapacityBackendError, match="configuration mismatch"):
        gateway_b.revision()
    with pytest.raises(CapacityBackendError, match="configuration mismatch"):
        gateway_b.reserve("reservation")


def test_ledger_meta_field_count_matches_constant(make_store) -> None:
    # Admission derives the live-entry count as HLEN - META_FIELD_COUNT, so the
    # Lua constant must equal the number of 'meta:*' fields initialize() writes.
    # Adding a meta field without updating the constant also trips the existing
    # concurrency tests, but those report an unexpected reservation outcome; this
    # one names the cause.
    store = make_store(3)
    _initialize(store)
    fields = store._redis.hkeys(store.key)

    assert _counts(store) == (0, 0)
    assert sorted(fields) == ["meta:hard_limit", "meta:revision", "meta:state"]
    assert len(fields) == 3


def test_reserve_admits_exactly_hard_limit_entries(make_store) -> None:
    # Locks the invariant the constant exists to protect: an off-by-one in the
    # HLEN offset shifts the ceiling, which this catches regardless of how the
    # offset happens to be spelled.
    store = make_store(3)
    _initialize(store)

    granted = [store.reserve(f"reservation-{index}") for index in range(3)]

    assert granted == [ReserveStatus.GRANTED] * 3
    assert _counts(store) == (0, 3)
    assert store.reserve("reservation-overflow") is ReserveStatus.FULL
    assert store.reserve("reservation-0") is ReserveStatus.GRANTED
