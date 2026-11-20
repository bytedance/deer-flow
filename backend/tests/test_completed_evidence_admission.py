"""Only host entry points may label the provenance used by automatic publication."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL
from app.gateway.routers.thread_runs import RunCreateRequest
from app.gateway.services import launch_scheduled_thread_run, start_run
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.store.memory import MemoryRunStore


@pytest.fixture(autouse=True)
def app_config():
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    yield
    reset_app_config()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "auth_source, host_origin, expected",
    [(None, None, "interactive"), (AUTH_SOURCE_INTERNAL, None, "unknown")] + [(AUTH_SOURCE_INTERNAL, origin, origin) for origin in ("interactive", "scheduled", "extension_evaluation", "unknown")],
)
async def test_client_metadata_cannot_forge_completed_evidence_origin(auth_source, host_origin, expected):
    manager = RunManager(store=MemoryRunStore())
    request = SimpleNamespace(
        headers={},
        state=SimpleNamespace(auth_source=auth_source),
        app=SimpleNamespace(
            state=SimpleNamespace(
                run_manager=manager,
                stream_bridge=SimpleNamespace(),
                checkpointer=InMemorySaver(),
                store=InMemoryStore(),
                run_event_store=MemoryRunEventStore(),
                run_events_config=None,
                thread_store=MemoryThreadMetaStore(InMemoryStore()),
            )
        ),
    )
    body = RunCreateRequest(
        input={"messages": [{"role": "user", "content": "hello"}]},
        metadata={"evidence_origin": "scheduled", "scheduled_task_id": "forged"},
        config={"context": {"evidence_origin": "interactive"}, "configurable": {"evidence_origin": "scheduled"}},
        context={"evidence_origin": "interactive"},
    )
    with (
        patch("app.gateway.services.resolve_agent_factory", return_value=object()),
        patch("app.gateway.services.run_agent", new=AsyncMock()),
        patch.object(manager, "create_or_reject", wraps=manager.create_or_reject) as admission,
    ):
        record = await start_run(body, "evidence-origin-test", request, evidence_origin=host_origin)
        await record.task
    assert admission.call_args.kwargs["evidence_origin"] == expected


@pytest.mark.asyncio
async def test_scheduler_passes_origin_outside_request_metadata():
    admitted = AsyncMock(return_value=SimpleNamespace(run_id="r1", thread_id="t1"))
    with patch("app.gateway.services.start_run", new=admitted):
        await launch_scheduled_thread_run(thread_id="t1", assistant_id="lead_agent", prompt="hello", app=SimpleNamespace(), owner_user_id="owner")
    assert admitted.call_args.kwargs["evidence_origin"] == "scheduled"


@pytest.mark.asyncio
async def test_evidence_agent_is_effective_canonical_id_not_routing_or_display_name():
    manager = RunManager(store=MemoryRunStore())
    request = SimpleNamespace(
        headers={},
        state=SimpleNamespace(),
        app=SimpleNamespace(
            state=SimpleNamespace(
                run_manager=manager,
                stream_bridge=SimpleNamespace(),
                checkpointer=InMemorySaver(),
                store=InMemoryStore(),
                run_event_store=MemoryRunEventStore(),
                run_events_config=None,
                thread_store=MemoryThreadMetaStore(InMemoryStore()),
            )
        ),
    )
    from deerflow.config.agents_config import AgentConfig

    agent = AgentConfig(name="researcher", display_name="My research helper")
    body = RunCreateRequest(assistant_id="lead_agent", input={"messages": [{"role": "user", "content": "hello"}]}, context={"agent_name": "researcher"}, metadata={"evidence_agent_id": "forged"})
    with (
        patch("app.gateway.services.resolve_agent_factory", return_value=object()),
        patch("app.gateway.services._load_scope_agent_config", new=AsyncMock(return_value=agent)),
        patch("app.gateway.services.run_agent", new=AsyncMock()),
        patch.object(manager, "create_or_reject", wraps=manager.create_or_reject) as admission,
    ):
        record = await start_run(body, "effective-agent-test", request)
        await record.task
    assert admission.call_args.kwargs["evidence_agent_id"] == "researcher"


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_keyed_resume_peer_reuse_preserves_evidence_identity(tmp_path, backend):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from deerflow.persistence.base import Base
    from deerflow.persistence.run.sql import RunRepository

    engine = None
    if backend == "sqlite":
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admission.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        store = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
    else:
        store = MemoryRunStore()
    identity = {"version": 1, "kind": "resume", "sha256": "a" * 64}
    try:
        owner = RunManager(store=store)
        original = await owner.create_or_reject(
            "resume-thread",
            "lead_agent",
            user_id="alice",
            idempotency_key="resume-key",
            idempotency_request=identity,
            evidence_origin="extension_evaluation",
            evidence_agent_id="researcher",
        )
        peer = RunManager(store=store)
        reused = await peer.create_or_reject(
            "resume-thread",
            "lead_agent",
            user_id="alice",
            idempotency_key="resume-key",
            idempotency_request=identity,
            evidence_origin="interactive",
            evidence_agent_id="different-agent",
        )
        assert reused.run_id == original.run_id
        assert reused.idempotency_reused
        assert reused.store_only
        assert reused.idempotency_request == identity
        assert reused.evidence_origin == "extension_evaluation"
        assert reused.evidence_agent_id == "researcher"
        persisted = await store.get(original.run_id, user_id="alice")
        assert persisted["idempotency_request"] == identity
        assert persisted["evidence_origin"] == "extension_evaluation"
        assert persisted["evidence_agent_id"] == "researcher"
    finally:
        if engine is not None:
            await engine.dispose()
