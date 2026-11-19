"""Strict runtime coverage of the durable host, scanner, evidence and admin API."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from app.gateway.routers.skill_mutations import router
from deerflow.config.app_config import AppConfig
from deerflow.config.paths import Paths
from deerflow.extensions.host_capabilities import HostCapabilities
from deerflow.persistence.base import Base
from deerflow.persistence.run import RunRepository
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.user.model import UserRow
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.skills.security_scanner import ScanResult
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Skill publication requires POSIX local storage")

CONTENT = "---\nname: example\ndescription: A sample skill\n---\nOriginal instructions.\n"


@pytest.fixture
def durable_host(tmp_path, monkeypatch):
    """Only seed data synchronously; all host lifetime work stays under the gate."""
    monkeypatch.setattr("deerflow.config.paths._paths", Paths(base_dir=tmp_path / "home"))
    config = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "database": {"backend": "sqlite", "sqlite_dir": str(tmp_path)},
            "skill_scan": {"enabled": True},
            "plugins": [
                {
                    "use": "fixture:install",
                    "name": "fixture",
                    "host_access": {
                        "evidence": {"owners": ["owner"]},
                        "skill_mutations": {"owners": ["owner"], "operations": ["stage", "check", "commit", "revert"], "trigger_agents": ["lead_agent"], "target_skills": ["example"], "topology": "single_host_local"},
                    },
                }
            ],
        }
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    # Replace only the remote moderation boundary, retaining the real scanner,
    # package staging/static scan, publication, projection and SQLite paths.
    model = AsyncMock(return_value=ScanResult("allow", "safe"))
    monkeypatch.setattr("deerflow.skills.mutations.scanner.scan_skill_content", model)
    storage = UserScopedSkillStorage("owner", host_path=str(tmp_path / "skills"), app_config=config)
    root = storage.get_custom_skill_dir("example")
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(CONTENT, encoding="utf-8")
    engine = create_engine(config.database.app_sync_sqlalchemy_url)
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session, session.begin():
            session.add(UserRow(id="owner", email="owner@example.test"))
            session.add(RunRow(run_id="run", thread_id="thread", user_id="owner", status="success", evidence_seal_state="sealed", evidence_agent_id="lead_agent", evidence_origin="interactive", evidence_upper_seq=2, evidence_event_count=2))
    finally:
        engine.dispose()
    return SimpleNamespace(config=config, storage=storage, model=model, root=tmp_path, database_url=config.database.app_sqlalchemy_url, skill_file=root / "SKILL.md")


@pytest.mark.asyncio
async def test_host_check_evidence_publication_revert_and_admin_are_off_loop(durable_host):
    seed = durable_host
    engine = create_async_engine(seed.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    events = DbRunEventStore(sf)
    host = HostCapabilities(seed.config, RunRepository(sf), events, root=seed.root, storage_factory=lambda _: seed.storage)
    try:
        await events.put_batch([dict(thread_id="thread", run_id="run", user_id="owner", event_type="test", category="message", content=text) for text in ("first", "second")])
        await host.start()
        evidence, mutations = host.bindings["fixture:install"]
        assert (await evidence.list_changed_runs()).items[0].run_id == "run"
        snapshot = await evidence.get_snapshot(thread_id="thread", run_id="run")
        from deerflow_extension_api import EvidenceLimits

        page = await evidence.read_events(snapshot_ref=snapshot.snapshot_ref, limits=EvidenceLimits(max_events=1))
        assert len(page.items) == 1 and page.has_more
        next_page = await evidence.read_events(snapshot_ref=snapshot.snapshot_ref, cursor=page.next_cursor, limits=EvidenceLimits(max_events=1))
        assert len(next_page.items) == 1 and not next_page.has_more
        assert next_page.items[0].seq > page.items[0].seq
        skill = await mutations.read_skill(source_ref=snapshot.snapshot_ref, name="example")
        proposal = await mutations.stage(source_refs=(snapshot.snapshot_ref,), target_ref=skill.target_ref, expected_revision=skill.revision, content=CONTENT.replace("Original", "Updated"), idempotency_key="stage")
        result = await mutations.check(proposal_id=proposal.proposal_id)
        assert result.decision == "allow"
        seed.model.assert_awaited_once()
        operation = await mutations.commit(proposal_id=proposal.proposal_id, idempotency_key="commit")
        assert operation.publication == "APPLIED" and operation.views == "READY"

        app = FastAPI()
        app.state.skill_mutation_host = host

        @app.middleware("http")
        async def identity(request: Request, call_next):
            request.state.user = SimpleNamespace(id="admin", system_role="admin")
            return await call_next(request)

        app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            url = f"/api/skill-mutations/operations/{operation.operation_id}"
            assert (await client.get("/api/skill-mutations/operations")).status_code == 200
            assert (await client.get(url)).json()["publication"] == "APPLIED"
            assert (await client.post(url + "/recover")).json()["views"] == "READY"
            assert (await client.post("/api/skill-mutations/owners/owner/recover")).status_code == 200
        reverted = await mutations.revert(operation_id=operation.operation_id, expected_current_revision=operation.after_revision, idempotency_key="revert")
        assert reverted.publication == "APPLIED" and reverted.views == "READY"
        content = await asyncio.to_thread(seed.skill_file.read_text, encoding="utf-8")
        assert content == CONTENT
    finally:
        await host.close()
        await engine.dispose()
