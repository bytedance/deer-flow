"""``ChannelService`` under ``channels.leader_lease``: one transport per provider across instances.

Two services share one SQLite ``channel_leases`` table, as two Gateway
instances share the application database. Transports are fakes; supervision
rounds are driven by hand (``_supervise_once`` + the scheduled per-provider
actions) except for the end-to-end failover case, which runs the real loop
with a 3-second lease.

On ``main`` before the lease existed both services started every enabled
provider: that duplicate Telegram poller / Discord session is what
``test_only_the_lease_holder_starts_an_arbitrated_transport`` pins.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.channels.base import ChannelStopTimeout
from app.channels.leadership import ChannelLeadership
from app.channels.service import ChannelService
from app.channels.store import JsonChannelStore
from deerflow import reflection
from deerflow.persistence.base import Base
from deerflow.persistence.channel_leases import ChannelLeaseRow, SqlChannelLeaseRepository, db_now

pytestmark = pytest.mark.asyncio


class FakeTransport:
    """A platform connection: ``started`` counts real starts across the test."""

    started: list[FakeTransport] = []
    start_gate: asyncio.Event | None = None
    fail_start = False
    stop_error: Exception | None = None

    def __init__(self, *, bus: object, config: dict) -> None:
        self.config = config
        self.is_running = False

    async def start(self) -> None:
        if FakeTransport.start_gate is not None:
            await FakeTransport.start_gate.wait()
        if FakeTransport.fail_start:
            return
        self.is_running = True
        FakeTransport.started.append(self)

    async def stop(self) -> None:
        if FakeTransport.stop_error is not None:
            raise FakeTransport.stop_error
        self.is_running = False


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def fake_transports(monkeypatch):
    FakeTransport.started = []
    FakeTransport.start_gate = None
    FakeTransport.fail_start = False
    FakeTransport.stop_error = None
    monkeypatch.setattr(reflection, "resolve_class", lambda *_args, **_kwargs: FakeTransport)
    yield


@pytest_asyncio.fixture
async def engine(tmp_path) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'leases.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[ChannelLeaseRow.__table__])
    try:
        yield engine
    finally:
        await engine.dispose()


def _repo(engine: AsyncEngine) -> SqlChannelLeaseRepository:
    return SqlChannelLeaseRepository(async_sessionmaker(engine, expire_on_commit=False))


CHANNELS = {"telegram": {"enabled": True, "bot_token": "t-1"}, "discord": {"enabled": True, "bot_token": "d-1"}, "github": {"enabled": True}}


def _service(engine, owner: str, tmp_path: Path, *, clock=None, channels=None, repo=None, lease_seconds: int = 30, grace_seconds: int = 10, supervise: bool = False) -> ChannelService:
    leadership = ChannelLeadership(repo or _repo(engine), owner_id=owner, lease_seconds=lease_seconds, grace_seconds=grace_seconds, clock=clock or time.monotonic)
    service = ChannelService(channels_config={name: dict(block) for name, block in (channels or CHANNELS).items()}, store=JsonChannelStore(tmp_path / owner / "store.json"), leadership=leadership)

    async def noop() -> None:
        return None

    service.manager.start = noop
    service.manager.stop = noop
    if not supervise:
        service._start_supervisor = lambda: None
    # A takeover reloads the provider's config from disk; keep the cached one.
    service._load_channel_config = lambda name: None
    return service


async def _round(service: ChannelService) -> None:
    """One supervision round, then wait for the transport actions it scheduled."""
    await service._supervise_once()
    if service._lease_actions:
        await asyncio.gather(*list(service._lease_actions.values()))


def _running(service: ChannelService) -> set[str]:
    return {name for name, channel in service._channels.items() if channel.is_running}


async def _lease(engine, provider: str) -> ChannelLeaseRow | None:
    async with async_sessionmaker(engine)() as session:
        return await session.get(ChannelLeaseRow, provider)


async def test_only_the_lease_holder_starts_an_arbitrated_transport(engine, tmp_path):
    a, b = _service(engine, "A", tmp_path), _service(engine, "B", tmp_path)
    await a.start()
    await b.start()
    try:
        assert _running(a) == {"telegram", "discord", "github"}
        # GitHub is webhook-driven and stays on every instance; the rest have one transport.
        assert _running(b) == {"github"}
        assert len([t for t in FakeTransport.started if "bot_token" in t.config]) == 2

        await _round(a)  # A's renewal reports its transports running
        await _round(b)  # B's refused acquisitions observe A
        for service in (a, b):
            status = service.get_status()["channels"]
            assert status["telegram"]["running"] is True
            assert status["telegram"]["leader"] == "A"
            assert status["github"]["running"] is True and "leader" not in status["github"]
        assert a.get_status()["channels"]["telegram"]["leader_here"] is True
        assert b.get_status()["channels"]["telegram"]["leader_here"] is False
        assert b.leader_of("telegram") == "A" and b.leader_of("github") is None
    finally:
        await a.stop()
        await b.stop()


async def test_a_stopping_holder_releases_and_the_peer_takes_over_on_its_next_round(engine, tmp_path):
    a, b = _service(engine, "A", tmp_path), _service(engine, "B", tmp_path)
    await a.start()
    await b.start()
    try:
        await a.stop()
        row = await _lease(engine, "telegram")
        assert (row.owner_id, row.lease_expires_at) == ("A", 0.0)  # released, not left to expire

        # The new holder starts from its freshly loaded config (credentials saved since it started).
        b._load_channel_config = lambda name: {"enabled": True, "bot_token": f"{name}-rotated"}
        await _round(b)
        assert _running(b) == {"telegram", "discord", "github"}
        assert b._channels["telegram"].config["bot_token"] == "telegram-rotated"
        assert (await _lease(engine, "telegram")).owner_id == "B"
    finally:
        await b.stop()


async def test_a_lost_lease_stops_the_transport(engine, tmp_path):
    a = _service(engine, "A", tmp_path)
    await a.start()
    try:
        async with engine.begin() as conn:  # a peer took the row over (newer epoch)
            await conn.execute(sa.update(ChannelLeaseRow).where(ChannelLeaseRow.provider == "telegram").values(owner_id="B", epoch=ChannelLeaseRow.epoch + 1))
        await _round(a)
        assert "telegram" not in a._channels
        assert _running(a) == {"discord", "github"}
        # The next round only observes the peer; it does not reconnect.
        await _round(a)
        assert "telegram" not in a._channels
        assert a.get_status()["channels"]["telegram"]["leader"] == "B"
    finally:
        await a.stop()
    assert (await _lease(engine, "telegram")).owner_id == "B"  # shutdown never releases someone else's lease


async def test_unconfirmed_renewals_stop_the_transport_before_a_peer_may_connect(engine, tmp_path):
    clock = Clock()
    repo = _repo(engine)
    a = _service(engine, "A", tmp_path, clock=clock, repo=repo)
    await a.start()
    try:

        async def unreachable(*args, **kwargs):
            raise ConnectionError("database unreachable")

        repo.renew = unreachable
        clock.now += 10
        await _round(a)
        assert _running(a) == {"telegram", "discord", "github"}  # one missed renewal is tolerated

        clock.now += 10  # the next tick would be at the local deadline (1000 + 30)
        await _round(a)
        assert _running(a) == {"github"}
        # A peer may connect only lease + grace after the last confirmed renewal was sent:
        # stopping at 1020 leaves grace_seconds + one interval of margin.
        assert clock.now + a._leadership.renew_interval + a._leadership.grace_seconds <= 1000 + 30 + 10
        # The row is not released: the database may be the one that is unreachable.
        assert (await _lease(engine, "telegram")).owner_id == "A"
    finally:
        await a.stop()


async def test_paths_on_a_non_holder_never_start_the_transport(engine, tmp_path):
    a, b = _service(engine, "A", tmp_path), _service(engine, "B", tmp_path)
    await a.start()
    await b.start()
    try:
        assert await b.ensure_channel_ready("telegram") is False
        assert await b.restart_channel("telegram", reload_config=False) is False
        assert b.leader_of("telegram") == "A"
        # Runtime config is accepted (the holder's transport serves the provider) but starts nothing here.
        assert await b.configure_channel("telegram", {"enabled": True, "bot_token": "t-2"}) is True
        assert b._config["telegram"]["bot_token"] == "t-2"
        assert await b._start_channel("telegram", {"enabled": True}) is False  # the fence itself
        assert "telegram" not in b._channels
        assert len([t for t in FakeTransport.started if t.config.get("bot_token", "").startswith("t-")]) == 1
    finally:
        await a.stop()
        await b.stop()


async def test_a_transport_that_fails_to_stop_keeps_its_lease_on_shutdown(engine, tmp_path):
    a, b = _service(engine, "A", tmp_path, channels={"telegram": {"enabled": True}}), _service(engine, "B", tmp_path, channels={"telegram": {"enabled": True}})
    await a.start()
    FakeTransport.stop_error = ChannelStopTimeout("telegram polling thread still alive")
    with pytest.raises(ExceptionGroup):
        await a.stop()
    FakeTransport.stop_error = None
    row = await _lease(engine, "telegram")
    assert row.owner_id == "A" and row.lease_expires_at > 0  # left to expire: the old socket may still be open
    await b.start()
    try:
        assert "telegram" not in b._channels
    finally:
        await b.stop()


async def test_removing_a_provider_releases_its_lease_for_a_peer(engine, tmp_path):
    a, b = _service(engine, "A", tmp_path), _service(engine, "B", tmp_path)
    await a.start()
    await b.start()
    try:
        assert await a.remove_channel("telegram") is True
        assert (await _lease(engine, "telegram")).lease_expires_at == 0.0
        await _round(b)
        assert "telegram" in _running(b)
    finally:
        await a.stop()
        await b.stop()


async def test_a_provider_disabled_on_the_holder_is_stopped_and_released_by_supervision(engine, tmp_path):
    a = _service(engine, "A", tmp_path)
    await a.start()
    try:
        a._config["discord"] = {"enabled": False}
        await _round(a)
        assert "discord" not in a._channels
        assert (await _lease(engine, "discord")).lease_expires_at == 0.0
    finally:
        await a.stop()


async def test_notification_claims_are_left_to_the_holder(engine, tmp_path):
    a, b = _service(engine, "A", tmp_path), _service(engine, "B", tmp_path)
    await a.start()
    await b.start()
    try:
        assert a.notification_excluded_providers() == frozenset()
        assert b.notification_excluded_providers() == frozenset({"telegram", "discord"})
    finally:
        await a.stop()
        await b.stop()


async def test_a_provider_connected_on_a_peer_is_left_to_it_although_absent_from_local_config(engine, tmp_path):
    """Review on #6843: a provider set up from the web UI on A never enters B's config.

    B must still leave its notification rows to A (instead of claiming and
    parking them) and report A as its leader, which it learns from the lease
    table rather than from its own config.
    """
    a = _service(engine, "A", tmp_path, channels={"github": {"enabled": True}})
    b = _service(engine, "B", tmp_path, channels={"github": {"enabled": True}})
    await a.start()
    await b.start()
    try:
        assert await a.configure_channel("telegram", {"enabled": True, "bot_token": "ui-token"}) is True
        assert "telegram" in _running(a) and "telegram" not in b._config
        await _round(a)  # A's renewal reports its transport running
        assert "telegram" not in b.notification_excluded_providers()  # before B has seen the lease table

        await _round(b)
        assert b.notification_excluded_providers() == frozenset({"telegram"})
        status = b.get_status()["channels"]["telegram"]
        assert (status["leader"], status["leader_here"], status["running"]) == ("A", False, True)
        assert "telegram" not in b._channels  # observing never starts anything

        assert await a.remove_channel("telegram") is True  # released: no instance runs it now
        await _round(b)
        assert b.notification_excluded_providers() == frozenset()  # rows settle again (park / fail)
        assert b.get_status()["channels"]["telegram"]["leader"] is None
    finally:
        await a.stop()
        await b.stop()


async def test_a_slow_start_never_delays_another_providers_renewal(engine, tmp_path):
    a = _service(engine, "A", tmp_path, channels={"telegram": {"enabled": True}, "discord": {"enabled": True}})
    await a.start()
    try:
        a._channels.pop("discord")  # the transport died; the next round restarts it
        gate = asyncio.Event()
        FakeTransport.start_gate = gate
        await a._supervise_once()  # schedules the (blocked) discord start and returns
        assert "discord" in a._lease_actions
        before = (await _lease(engine, "telegram")).updated_at
        await asyncio.sleep(0.01)
        await a._supervise_once()  # telegram renews while discord's start is still pending
        assert (await _lease(engine, "telegram")).updated_at > before
        gate.set()
        await asyncio.gather(*list(a._lease_actions.values()))
        assert "discord" in _running(a)
    finally:
        FakeTransport.start_gate = None
        await a.stop()


async def test_a_holder_that_cannot_start_backs_off(engine, tmp_path):
    clock = Clock()
    a = _service(engine, "A", tmp_path, clock=clock, channels={"telegram": {"enabled": True}})
    FakeTransport.fail_start = True
    await a.start()
    try:
        assert "telegram" not in _running(a)
        attempts = []
        original = a.ensure_channel_ready

        async def counting(name, *args, **kwargs):
            attempts.append(name)
            return await original(name, *args, **kwargs)

        a.ensure_channel_ready = counting
        await _round(a)
        await _round(a)  # inside the backoff window: no new attempt
        assert attempts == ["telegram"]
        clock.now += a._leadership.renew_interval * 2
        await _round(a)
        assert attempts == ["telegram", "telegram"]
        FakeTransport.fail_start = False
        clock.now += a._leadership.renew_interval * 4
        await _round(a)
        assert "telegram" in _running(a)
        assert "telegram" not in a._lease_start_backoff
    finally:
        await a.stop()


async def test_without_the_lease_every_instance_behaves_as_before(tmp_path):
    service = ChannelService(channels_config={name: dict(block) for name, block in CHANNELS.items()}, store=JsonChannelStore(tmp_path / "store.json"))

    async def noop() -> None:
        return None

    service.manager.start = noop
    service.manager.stop = noop
    await service.start()
    try:
        assert _running(service) == {"telegram", "discord", "github"}
        assert service.get_status()["channels"]["telegram"] == {"enabled": True, "running": True}
        assert service.notification_excluded_providers() is None
        assert service.lease_owner_id is None and service.leader_of("telegram") is None
        assert service._supervisor_task is None
    finally:
        await service.stop()


async def test_from_app_config_turns_the_lease_on_from_the_multi_process_signal(monkeypatch, tmp_path):
    """``auto`` follows the Gateway's multi-process signal; ``false`` never builds the lease."""
    from types import SimpleNamespace

    import app.channels.service as service_module

    built = []
    monkeypatch.setattr(service_module, "_make_leadership", lambda config, *, owner_id: built.append((config.lease_seconds, owner_id)) or None)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    config = SimpleNamespace(model_extra={"channels": {"leader_lease": {"enabled": "auto", "lease_seconds": 12}}})

    ChannelService.from_app_config(config, multi_process=False)
    assert built == []
    ChannelService.from_app_config(config, multi_process=True, lease_owner_id="host:worker")
    assert built == [(12, "host:worker")]
    config.model_extra["channels"]["leader_lease"]["enabled"] = False
    ChannelService.from_app_config(config, multi_process=True)
    assert built == [(12, "host:worker")]


async def test_an_active_lease_without_a_database_refuses_to_build(monkeypatch):
    import deerflow.persistence.engine as engine_module
    from app.channels.service import _make_leadership
    from deerflow.config.channel_leader_lease_config import ChannelLeaderLeaseConfig

    monkeypatch.setattr(engine_module, "get_session_factory", lambda: None)
    with pytest.raises(RuntimeError, match="channels.leader_lease is active"):
        _make_leadership(ChannelLeaderLeaseConfig(enabled=True), owner_id=None)


async def test_a_crashed_holder_is_replaced_within_one_lease_period(engine, tmp_path):
    """End to end with the real supervision loop: the holder dies without releasing (kill -9)."""
    a = _service(engine, "A", tmp_path, channels={"telegram": {"enabled": True}}, lease_seconds=3, grace_seconds=1, supervise=True)
    b = _service(engine, "B", tmp_path, channels={"telegram": {"enabled": True}}, lease_seconds=3, grace_seconds=1, supervise=True)
    await a.start()
    await b.start()
    try:
        assert "telegram" in _running(a) and "telegram" not in b._channels
        await asyncio.sleep(1.5)  # several renewals: B must not take a live lease
        assert "telegram" not in b._channels

        # Crash A: its loop stops renewing and nothing is released.
        await a._stop_supervisor()
        crashed_at = time.monotonic()
        deadline = crashed_at + 3 + 1 + 3  # lease + grace + slack for B's tick and the SQLite round trips
        while "telegram" not in _running(b) and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        assert "telegram" in _running(b)
        async with engine.connect() as conn:
            # The takeover respected the grace period on the database clock.
            row = (await conn.execute(sa.select(ChannelLeaseRow.owner_id, ChannelLeaseRow.epoch, db_now("sqlite")).where(ChannelLeaseRow.provider == "telegram"))).one()
        assert (row.owner_id, row.epoch) == ("B", 2)
        assert time.monotonic() - crashed_at >= 1.0
    finally:
        a._running = False
        a._channels.clear()
        await b.stop()


async def test_start_channel_service_threads_the_lease_settings(monkeypatch):
    import app.channels.service as service_module

    captured = {}

    class _Started:
        async def start(self):
            return None

    def fake_from_app_config(app_config=None, **kwargs):
        captured.update(kwargs)
        return _Started()

    monkeypatch.setattr(service_module.ChannelService, "from_app_config", staticmethod(fake_from_app_config))
    monkeypatch.setattr(service_module, "_channel_service", None)
    await service_module.start_channel_service(multi_process=True, lease_owner_id="host:worker-1")
    assert (captured["multi_process"], captured["lease_owner_id"]) == (True, "host:worker-1")


async def test_gateway_lifespan_passes_the_gate_signal_and_the_run_worker_id():
    """``auto`` follows the gate's multi-process signal; the lease owner is the run worker id."""
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi import FastAPI

    from app.gateway.app import lifespan

    @asynccontextmanager
    async def runtime(app, _startup_config):
        app.state.run_manager = SimpleNamespace(worker_id="host:worker-1")
        yield

    startup_config = MagicMock()
    startup_config.log_level = "INFO"
    startup_config.memory.enabled = False
    startup_config.memory.shutdown_flush_timeout_seconds = 5.0
    captured = {}

    async def fake_start(_startup_config, **kwargs):
        captured.update(kwargs)
        service = MagicMock()
        service.get_status.return_value = {}
        return service

    with (
        patch("app.gateway.app.get_app_config", return_value=startup_config),
        patch("app.gateway.app.get_gateway_config", return_value=MagicMock(host="x", port=0)),
        patch("app.gateway.app.langgraph_runtime", runtime),
        patch("app.gateway.app.multi_process_deployment", return_value=True) as signal,
        # The real configure_logging would raise the root logger to INFO for every later test.
        patch("app.gateway.app.configure_logging"),
        patch("deerflow.skills.projection.ensure_public_skill_projection"),
        patch("app.gateway.app.auth.close_oidc_service", AsyncMock()),
        patch("app.channels.service.start_channel_service", side_effect=fake_start),
        patch("app.channels.service.stop_channel_service", AsyncMock()),
        patch("deerflow.agents.memory.get_memory_manager", return_value=MagicMock()),
    ):
        async with lifespan(FastAPI()):
            pass

    signal.assert_called_once_with(startup_config)
    assert (captured["multi_process"], captured["lease_owner_id"]) == (True, "host:worker-1")


def test_multi_process_deployment_is_the_gate_signal(monkeypatch):
    from types import SimpleNamespace

    from app.gateway.deps import multi_process_deployment

    monkeypatch.delenv("DEER_FLOW_MULTI_INSTANCE", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    single = SimpleNamespace(deployment=SimpleNamespace(multi_instance=False))
    assert multi_process_deployment(single) is False
    assert multi_process_deployment(SimpleNamespace(deployment=SimpleNamespace(multi_instance=True))) is True
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    assert multi_process_deployment(single) is True
