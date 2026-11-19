"""Real SQLite, host assembly, evidence, projection and public-only consumer."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from deerflow_extension_api import ExtensionData, ExtensionRuntimeDeps, HostPolicySnapshot
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.config.database_config import DatabaseConfig
from deerflow.config.paths import Paths
from deerflow.extensions.host_capabilities import HostCapabilities
from deerflow.extensions.loader import ExtensionSpec
from deerflow.persistence.base import Base
from deerflow.persistence.run import RunRepository
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.user.model import UserRow
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.skills.mutations.scanner import CandidateScanner, ScanVerdict
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage


@pytest.mark.asyncio
async def test_public_consumer_end_to_end_and_plugin_removed_restart(tmp_path, monkeypatch):
    monkeypatch.setattr("deerflow.config.paths._paths", Paths(base_dir=tmp_path / "home"))
    storage = UserScopedSkillStorage("owner", host_path=str(tmp_path / "skills"))
    root = storage.get_custom_skill_dir("example")
    root.mkdir(parents=True)
    content = "---\nname: example\ndescription: A sample skill\n---\nOriginal body.\n"
    (root / "SKILL.md").write_text(content, encoding="utf-8")
    database = DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path))
    engine = create_engine(database.app_sync_sqlalchemy_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    async_engine = create_async_engine(database.app_sqlalchemy_url)
    sf = async_sessionmaker(async_engine, expire_on_commit=False)
    async with sf.begin() as session:
        session.add(UserRow(id="owner", email="owner@example.test"))
        session.add(RunRow(run_id="run", thread_id="thread", user_id="owner", status="success", evidence_seal_state="sealed", evidence_agent_id="lead_agent", evidence_origin="interactive", evidence_upper_seq=0, evidence_event_count=0))

    async def scan(self, package, name):
        assert name == "example"
        assert package.main_content.startswith("---")
        return ScanVerdict("allow", "CHECK_PASSED", "test-policy")

    async def policy(self):
        return "test-policy"

    monkeypatch.setattr(CandidateScanner, "scan", scan)
    monkeypatch.setattr(CandidateScanner, "policy_version", policy)
    monkeypatch.setattr(CandidateScanner, "policy_version_sync", lambda _: "test-policy")
    spec = ExtensionSpec(
        use="fixture:install",
        name="fixture",
        host_access={
            "evidence": {"owners": ["owner"]},
            "skill_mutations": {"owners": ["owner"], "operations": ["stage", "check", "commit", "revert"], "trigger_agents": ["lead_agent"], "target_skills": ["example"], "topology": "single_host_local"},
        },
    )
    config = SimpleNamespace(database=database, plugins=[spec])
    host = HostCapabilities(config, RunRepository(sf), DbRunEventStore(sf), root=tmp_path, storage_factory=lambda _: storage)
    try:
        await host.start()
        evidence, mutations = host.bindings[spec.use]
        deps = ExtensionRuntimeDeps(app_store=ExtensionData("fixture"), policy=HostPolicySnapshot(), completed_run_evidence=evidence, skill_mutations=mutations)
        module_spec = importlib.util.spec_from_file_location("external_consumer", Path(__file__).parent / "fixtures" / "skill_evolution_consumer.py")
        consumer = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(consumer)
        operation, reverted = await consumer.exercise(deps, thread_id="thread", run_id="run", name="example")
        assert (operation.views, reverted.views) == ("READY", "READY")
        assert (root / "SKILL.md").read_text(encoding="utf-8") == content
        await host.close()
        config.plugins = []
        host = HostCapabilities(config, RunRepository(sf), DbRunEventStore(sf), root=tmp_path, storage_factory=lambda _: storage)
        await host.start()
        assert host.bindings == {}
        assert "owner" in host.runtime.owners
        assert host.recovery.get_operation(reverted.operation_id).publication == "APPLIED"
    finally:
        await host.close()
        await async_engine.dispose()
