"""A new Agent with the same slug cannot inherit the deleted Agent's destination."""

import stat
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_tracing_profiles import _provider
from test_tracing_profiles import control as _control_fixture

control = _control_fixture


@pytest.fixture(params=["db", "file"])
def agents(control, monkeypatch, request):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
    from deerflow.config.paths import Paths
    from deerflow.persistence.agents import make_agent_store
    from deerflow.persistence.base import Base
    from deerflow.persistence.tracing_profiles.identity import resolve_agent_incarnation
    from deerflow.persistence.tracing_profiles.sql import SqlTracingProfileRepository
    from deerflow.tracing.profiles import TracingProfileService

    _, _, cipher, path = control
    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "database": {"backend": "sqlite", "sqlite_dir": str(path)}, "agent_storage": {"backend": request.param}})
    engine = create_engine(config.database.app_sync_sqlalchemy_url)
    Base.metadata.create_all(engine)
    monkeypatch.setattr("deerflow.config.agents_config.get_paths", lambda: Paths(base_dir=path / "home"))
    set_app_config(config)
    store = make_agent_store(config)
    store.create("worker", {"name": "worker"}, "", user_id="alice")
    service = TracingProfileService(SqlTracingProfileRepository(sessionmaker(engine, expire_on_commit=False)), cipher, identity_resolver=lambda name, owner: resolve_agent_incarnation(name, owner, app_config=config))
    service.save_profile(profile_id="profile-a", name="Private", providers=(_provider(),), allowed_user_ids=["alice"], expected_revision=0)
    yield service, store, config, path
    reset_app_config()
    engine.dispose()


def test_delete_and_recreate_resets_binding_and_rejects_the_previous_execution_scope(agents):
    from deerflow.tracing.profiles import TracingControlError

    service, store, _, _ = agents
    initial = service.set_binding("worker", "alice", mode="configured", profile_id="profile-a", expected_revision=0)
    old = service.resolve_snapshot("worker", "alice")
    assert store.delete("worker", user_id="alice") == "deleted"
    store.create("worker", {"name": "worker"}, "new Agent", user_id="alice")
    fresh = service.get_binding("worker", "alice")
    assert fresh["mode"] == "inherit" and fresh["profile_id"] is None
    assert fresh["revision"] > initial["revision"]
    assert service.resolve_snapshot("worker", "alice").mode == "inherit"
    with pytest.raises(TracingControlError):
        service.resolve_snapshot("worker", "alice", snapshot_id=old.snapshot_id)


def test_prechecked_binding_write_cannot_attach_itself_to_a_recreated_agent(agents, monkeypatch):
    from deerflow.tracing.profiles import TracingConflictError

    service, store, _, _ = agents
    initial = service.set_binding("worker", "alice", mode="inherit", profile_id=None, expected_revision=0)
    entered, release = threading.Event(), threading.Event()
    original = service.repository.save_binding

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(service.repository, "save_binding", paused)
    with ThreadPoolExecutor(1) as pool:
        setter = pool.submit(service.set_binding, "worker", "alice", mode="configured", profile_id="profile-a", expected_revision=initial["revision"])
        try:
            assert entered.wait(5)
            assert store.delete("worker", user_id="alice") == "deleted"
            store.create("worker", {"name": "worker"}, "new Agent", user_id="alice")
        finally:
            release.set()
        with pytest.raises(TracingConflictError):
            setter.result(timeout=5)
    assert service.get_binding("worker", "alice")["mode"] == "inherit"


def test_custom_lead_agent_slug_is_independent_of_the_builtin_agent(agents):
    service, store, _, _ = agents
    store.create("lead-agent", {"name": "lead-agent"}, "custom", user_id="alice")
    service.set_binding("lead-agent", "alice", mode="disabled", profile_id=None, expected_revision=0)
    assert service.resolve_snapshot("lead-agent", "alice").mode == "disabled"
    assert service.resolve_snapshot(None, "alice").mode == "inherit"


def test_filesystem_incarnation_is_one_atomic_owner_only_marker(agents):
    from deerflow.config.agents_config import resolve_agent_dir
    from deerflow.persistence.tracing_profiles.identity import resolve_agent_incarnation

    _, _, config, _ = agents
    if config.agent_storage.backend != "file":
        pytest.skip("filesystem marker applies to file storage")
    with ThreadPoolExecutor(8) as pool:
        identities = list(pool.map(lambda _: resolve_agent_incarnation("worker", "alice", app_config=config), range(8)))
    assert len(set(identities)) == 1
    marker = resolve_agent_dir("worker", user_id="alice") / ".tracing-incarnation"
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_final_admission_checks_the_live_agent_even_when_a_delete_tombstone_was_lost(agents):
    import shutil

    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from deerflow.config.agents_config import resolve_agent_dir
    from deerflow.persistence.agents.model import AgentRow
    from deerflow.persistence.tracing_profiles.sql import validate_tracing_admission
    from deerflow.runtime.tracing_snapshot import snapshot_references
    from deerflow.tracing.profiles import TracingConflictError

    service, store, config, _ = agents
    snapshot = service.resolve_snapshot("worker", "alice")
    # Models the filesystem half of a deletion surviving a crashed DB worker.
    if config.agent_storage.backend == "file":
        shutil.rmtree(resolve_agent_dir("worker", user_id="alice"))
    else:
        with store._Session.begin() as session:
            session.execute(delete(AgentRow).where(AgentRow.user_id == "alice", AgentRow.name == "worker"))
    store.create("worker", {"name": "worker"}, "replacement", user_id="alice")
    engine = create_async_engine(config.database.app_sqlalchemy_url)
    try:
        async with async_sessionmaker(engine).begin() as session:
            with pytest.raises(TracingConflictError):
                await validate_tracing_admission(session, snapshot_references(snapshot), owner_user_id="alice")
    finally:
        await engine.dispose()
