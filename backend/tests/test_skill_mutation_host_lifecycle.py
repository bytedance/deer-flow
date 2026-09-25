"""The host owns recovery even when every extension is disabled."""

import asyncio
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from deerflow.config.database_config import DatabaseConfig
from deerflow.config.run_events_config import RunEventsConfig
from deerflow.extensions.host_access import HostAccess
from deerflow.extensions.loader import ExtensionSpec
from deerflow.persistence.base import Base
from deerflow.persistence.run import RunRepository
from deerflow.persistence.skill_mutations.model import SkillOwnerRow, SkillProposalRow
from deerflow.persistence.user.model import UserRow
from deerflow.runtime.events.store.db import DbRunEventStore


@pytest_asyncio.fixture
async def durable(tmp_path):
    database = DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path))
    sync = create_engine(database.app_sync_sqlalchemy_url)
    Base.metadata.create_all(sync)
    with Session(sync) as session, session.begin():
        session.add(UserRow(id="owner", email="owner@example.test"))
    sync.dispose()
    engine = create_async_engine(database.app_sqlalchemy_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    yield database, sf
    await engine.dispose()


def config(database, plugins=()):
    return SimpleNamespace(database=database, run_events=RunEventsConfig(backend="db"), plugins=plugins)


def granted():
    return ExtensionSpec(
        use="example:install",
        name="evolution",
        host_access=HostAccess.model_validate(
            {
                "evidence": {"owners": ["owner"]},
                "skill_mutations": {"owners": ["owner"], "operations": ["stage", "check", "commit", "revert"], "trigger_agents": ["lead_agent"], "target_skills": ["example"], "topology": "single_host_local"},
            }
        ),
    )


@pytest.mark.asyncio
async def test_default_has_no_mutation_runtime_or_worker_pool(durable, tmp_path):
    from deerflow.extensions.host_capabilities import HostCapabilities

    database, sf = durable
    host = HostCapabilities(config(database), RunRepository(sf), DbRunEventStore(sf), root=tmp_path)
    await host.start()
    try:
        assert host.bindings == {}
        assert host.runtime is None
        assert host.recovery is None
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_disabled_plugin_still_recovers_enrolled_owners(durable, tmp_path):
    from deerflow.extensions.host_capabilities import HostCapabilities

    database, sf = durable
    async with sf.begin() as session:
        session.add(SkillOwnerRow(owner_id="owner", generation=4, deleting=False))
    events = []

    class Recovery:
        def __init__(self, runtime, storage_factory):
            assert runtime.owners == frozenset({"owner"})
            events.append("constructed")

        def recover_all(self):
            events.append("recovered")

        def collect_garbage(self):
            events.append("collected")

    host = HostCapabilities(config(database), RunRepository(sf), DbRunEventStore(sf), root=tmp_path, recovery_factory=Recovery)
    await host.start()
    try:
        assert host.bindings == {}
        assert events == ["constructed", "recovered", "collected"]
        assert host.runtime.owners == frozenset({"owner"})
    finally:
        await host.close()
    assert host.workers._closed


@pytest.mark.asyncio
async def test_source_binding_and_independent_evidence_scope(durable, tmp_path):
    from deerflow.extensions.host_capabilities import HostCapabilities

    database, sf = durable
    seen = []

    class Recovery:
        def __init__(self, *args):
            pass

        def recover_all(self):
            pass

        def collect_garbage(self):
            pass

    def service(binding, **kwargs):
        seen.append((binding, kwargs))
        return object()

    host = HostCapabilities(config(database, [granted()]), RunRepository(sf), DbRunEventStore(sf), root=tmp_path, recovery_factory=Recovery, service_factory=service)
    await host.start()
    try:
        reader, mutations = host.bindings["example:install"]
        assert reader is seen[0][1]["evidence"]
        assert reader._owners == frozenset({"owner"})
        assert mutations is not None
        assert seen[0][0].plugin_id != "evolution"
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_missing_topology_refuses_mutation_startup(durable, tmp_path):
    from deerflow_extension_api import HostCapabilityError

    from deerflow.extensions.host_capabilities import HostCapabilities

    database, sf = durable
    spec = granted()
    spec = spec.model_copy(update={"host_access": spec.host_access.model_copy(update={"skill_mutations": spec.host_access.skill_mutations.model_copy(update={"topology": None})})})
    host = HostCapabilities(config(database, [spec]), RunRepository(sf), DbRunEventStore(sf), root=tmp_path)
    try:
        with pytest.raises(HostCapabilityError, match="UNSUPPORTED_TOPOLOGY"):
            await host.start()
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_cancelled_startup_drains_worker_before_releasing_topology(durable, tmp_path):
    from deerflow.extensions.host_capabilities import HostCapabilities
    from deerflow.skills.mutations.topology import PublicationTopology

    database, sf = durable
    entered, release = threading.Event(), threading.Event()

    class Recovery:
        def __init__(self, *args):
            pass

        def recover_all(self):
            entered.set()
            assert release.wait(5)

        def collect_garbage(self):
            pass

    host = HostCapabilities(config(database, [granted()]), RunRepository(sf), DbRunEventStore(sf), root=tmp_path, recovery_factory=Recovery)
    task = asyncio.create_task(host.start())
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    closing = asyncio.create_task(host.close())
    await asyncio.sleep(0)
    assert not closing.done()
    assert host._topology._fd is not None
    release.set()
    await closing
    next_host = PublicationTopology("sqlite", tmp_path)
    next_host.acquire()
    next_host.close()


@pytest.mark.asyncio
async def test_read_only_evidence_reports_unsupported_without_mutation_pool(tmp_path):
    from deerflow_extension_api import HostCapabilityError

    from deerflow.extensions.host_capabilities import HostCapabilities
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    spec = ExtensionSpec(use="example:install", name="reader", host_access=HostAccess.model_validate({"evidence": {"owners": ["owner"]}}))
    host = HostCapabilities(config(DatabaseConfig(), [spec]), MemoryRunStore(), MemoryRunEventStore(), root=tmp_path)
    await host.start()
    try:
        reader, mutations = host.bindings["example:install"]
        assert mutations is None
        assert host.workers is None
        with pytest.raises(HostCapabilityError, match="UNSUPPORTED"):
            await reader.list_changed_runs()
    finally:
        await host.close()


@pytest.mark.asyncio
async def test_mutation_owner_without_evidence_grant_is_rejected(durable, tmp_path):
    from deerflow_extension_api import HostCapabilityError

    from deerflow.extensions.host_capabilities import HostCapabilities

    database, sf = durable
    spec = granted()
    spec.host_access = spec.host_access.model_copy(update={"evidence": HostAccess().evidence})
    host = HostCapabilities(config(database, [spec]), RunRepository(sf), DbRunEventStore(sf), root=tmp_path)
    try:
        with pytest.raises(HostCapabilityError, match="INVALID_GRANT"):
            await host.start()
        assert host.workers is None
    finally:
        await host.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["startup", "maintenance"])
@pytest.mark.parametrize("failure", ["lock-directory", "lock-timeout"])
async def test_owner_gc_failure_does_not_block_host_or_healthy_owner(durable, tmp_path, monkeypatch, phase, failure):
    from deerflow.config.paths import Paths
    from deerflow.extensions.host_capabilities import HostCapabilities
    from deerflow.skills.mutations import recovery as recovery_module
    from deerflow.skills.projection import get_skill_projection_paths
    from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage

    database, sf = durable
    monkeypatch.setattr("deerflow.config.paths._paths", Paths(base_dir=tmp_path / "home"))
    owners = ("a-broken", "z-healthy")
    async with sf.begin() as session:
        for owner_id in owners:
            session.add(UserRow(id=owner_id, email=f"{owner_id}@example.test"))
            session.add(SkillOwnerRow(owner_id=owner_id, generation=0, deleting=False))

    def storage_factory(owner_id):
        return UserScopedSkillStorage(owner_id, host_path=str(tmp_path / "skills"))

    async def expire_proposals():
        async with sf.begin() as session:
            for owner_id in owners:
                session.add(
                    SkillProposalRow(
                        proposal_id=owner_id,
                        plugin_id="removed-plugin",
                        owner_id=owner_id,
                        target_ref=owner_id,
                        name="example",
                        base_revision={},
                        sources=[],
                        candidate_hash="unused",
                        package_blob=b"baseline",
                        candidate_blob=b"candidate",
                        state="PENDING",
                        expires_at=0,
                        idempotency_key=owner_id,
                        request_hash="unused",
                    )
                )

    def break_owner_lock():
        if failure == "lock-directory":
            root = get_skill_projection_paths(storage_factory(owners[0])).custom.parent
            lock_path = root.parent / f".{root.name}.projection.lock"
            # During maintenance an earlier successful acquire made a file.
            if lock_path.is_file():
                lock_path.unlink()
            lock_path.mkdir(parents=True)
        else:
            original_lock = recovery_module.skill_projection_read_lock

            @contextmanager
            def blocked_lock(storage, **kwargs):
                if storage.user_id == owners[0]:
                    raise TimeoutError("owner lock unavailable")
                with original_lock(storage, **kwargs):
                    yield

            monkeypatch.setattr(recovery_module, "skill_projection_read_lock", blocked_lock)

    # No enabled plugin: persisted host state alone must remain recoverable.
    host = HostCapabilities(config(database), RunRepository(sf), DbRunEventStore(sf), root=tmp_path, storage_factory=storage_factory)
    try:
        if phase == "startup":
            await expire_proposals()
            break_owner_lock()
        await host.start()
        if phase == "maintenance":
            await expire_proposals()
            break_owner_lock()
            await host.workers.run(lambda _: (host.recovery.recover_all(), host.recovery.collect_garbage()))
        assert host.bindings == {}
        assert host.recovery is not None
        assert not host._maintenance.done()
        with host.runtime.repository.sessions() as session:
            broken = session.get(SkillProposalRow, owners[0])
            healthy = session.get(SkillProposalRow, owners[1])
            assert broken.state == "PENDING"
            assert broken.package_blob == b"baseline" and broken.candidate_blob == b"candidate"
            assert healthy.state == "EXPIRED"
            assert healthy.package_blob is None and healthy.candidate_blob is None
    finally:
        await host.close()
