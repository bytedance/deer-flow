"""A durable zero-export decision remains frozen when global tracing is enabled later."""

from contextlib import AsyncExitStack
from datetime import UTC, datetime

import pytest
import requests
from cryptography.fernet import Fernet
from langchain_core.callbacks.manager import CallbackManager
from langchain_core.runnables import RunnableLambda
from langchain_core.tracers.langchain import LangChainTracer
from langsmith import Client, tracing_context
from langsmith.utils import get_env_var, tracing_is_enabled
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


class _OfflineLangSmithSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url))
        response = requests.Response()
        response.status_code = 200
        response.url = url
        response.headers["Content-Type"] = "application/json"
        response._content = b"{}"
        response._content_consumed = True
        return response


@pytest.fixture
def durable_tracing(tmp_path, monkeypatch):
    import deerflow.persistence.models  # noqa: F401 -- register the complete application schema
    from deerflow.config.app_config import AppConfig
    from deerflow.config.credentials_key import reset_credentials_cipher
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.persistence.agents.sql import get_sync_sessionmaker
    from deerflow.persistence.base import Base

    monkeypatch.setenv("MONOCLE_TRACING", "false")
    monkeypatch.setenv("LANGFUSE_TRACING", "false")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGSMITH_API_KEY", "not-a-live-credential")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "http://127.0.0.1:9")
    monkeypatch.setenv("DEER_FLOW_CREDENTIALS_KEY", Fernet.generate_key().decode())
    get_env_var.cache_clear()
    reset_tracing_config()
    reset_credentials_cipher()
    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "database": {"backend": "sqlite", "sqlite_dir": str(tmp_path)}})
    engine = get_sync_sessionmaker(config.database.app_sync_sqlalchemy_url).kw["bind"]
    Base.metadata.create_all(engine)
    session = _OfflineLangSmithSession()
    client = Client(api_url="http://127.0.0.1:9", api_key="not-a-live-credential", workspace_id="", session=session, auto_batch_tracing=False, tracing_mode="langsmith", tracing_sampling_rate=1.0, info={"version": "0.0.0"})
    try:
        yield config, tmp_path, client, session
    finally:
        client.close(timeout=1)
        get_env_var.cache_clear()
        reset_tracing_config()
        reset_credentials_cipher()
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["inherit", "disabled"])
@pytest.mark.parametrize("recovery", ["queued", "resume"])
async def test_zero_export_snapshot_survives_sql_recovery_after_global_langsmith_enable(durable_tracing, monkeypatch, mode, recovery):
    from app.gateway import tracing_admission
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
    from deerflow.runtime.tracing_snapshot import restore_snapshot, stamp_snapshot_references
    from deerflow.tracing.factory import build_tracing_callbacks
    from deerflow.tracing.profiles import get_profile_service, resolve_run_snapshot
    from deerflow.tracing.scoped import build_scoped_callbacks, tracing_scope

    config, path, offline_client, offline_session = durable_tracing
    if mode == "disabled":
        get_profile_service(app_config=config).set_binding("lead_agent", "alice", mode="disabled", profile_id=None, expected_revision=0)
    captured = resolve_run_snapshot(None, "alice", app_config=config)
    assert captured is not None and captured.providers == () and not captured.monocle_enabled
    references = {}
    stamp_snapshot_references(references, captured)
    async with AsyncExitStack() as stack:
        if recovery == "queued":
            engine = create_async_engine(config.database.app_sqlalchemy_url)
            stack.push_async_callback(engine.dispose)
            sessions = async_sessionmaker(engine)
            await ScheduledTaskRunRepository(sessions).create(
                run_record_id="queued-untraced",
                task_id="task-untraced",
                thread_id="thread-untraced",
                scheduled_for=datetime.now(UTC),
                trigger="manual",
                status="queued",
                expected_task_user_id="alice",
                tracing_snapshot_refs=references,
            )
            stored = await ScheduledTaskRunRepository(sessions).get_active_run("task-untraced")
            recovery_kwargs = {"scheduled_references": stored["tracing_snapshot_refs"]}
            run_config = {}
        else:
            from langchain_core.messages import HumanMessage
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            from langgraph.graph import END, START, MessagesState, StateGraph

            saver = await stack.enter_async_context(AsyncSqliteSaver.from_conn_string(str(path / "checkpoints.db")))
            builder = StateGraph(MessagesState)
            builder.add_node("record", lambda state: {})
            builder.add_edge(START, "record")
            builder.add_edge("record", END)
            graph = builder.compile(checkpointer=saver)
            checkpoint_config = {"configurable": {"thread_id": "thread-untraced"}, "metadata": references}
            with tracing_scope(captured):
                await graph.ainvoke({"messages": [HumanMessage(content="Accepted before global tracing was enabled")]}, config=checkpoint_config)
            checkpoint = await saver.aget_tuple(checkpoint_config)
            run_config = {"configurable": checkpoint.config["configurable"]}
            monkeypatch.setattr(tracing_admission, "get_checkpointer", lambda request: saver)
            recovery_kwargs = {"resume": True}

        monkeypatch.setenv("LANGSMITH_TRACING", "true")
        get_env_var.cache_clear()
        reset_tracing_config()
        metadata = {}
        await tracing_admission.admit_run_tracing(None, run_config, metadata, thread_id="thread-untraced", agent_name="lead_agent", user_id="alice", app_config=config, **recovery_kwargs)
        assert metadata["deerflow_tracing_snapshot_id"] == captured.snapshot_id
        assert metadata["deerflow_tracing_managed"] is True
        restored = restore_snapshot(metadata, user_id="alice", agent_name="lead_agent", app_config=config)
        assert restored is not None and restored.mode == mode and restored.providers == ()
        with tracing_context(enabled=True, client=offline_client, parent=False, replicas=[]):
            assert tracing_is_enabled() is True
            before_requests = len(offline_session.requests)
            with tracing_scope(restored):
                assert build_tracing_callbacks() == []
                assert tracing_is_enabled() is False
                assert not any(isinstance(handler, LangChainTracer) for handler in CallbackManager.configure().handlers)
                assert await RunnableLambda(str.upper).ainvoke("restored", config={"callbacks": build_tracing_callbacks()}) == "RESTORED"
            assert len(offline_session.requests) == before_requests

            # Historical legacy runs have no managed references and preserve
            # ambient configuration rather than a frozen zero-export decision.
            legacy = restore_snapshot({}, user_id="alice", app_config=config)
            assert legacy is None
            with tracing_scope(legacy):
                assert build_scoped_callbacks() is None
                assert tracing_is_enabled() is True
                assert await RunnableLambda(str.upper).ainvoke("legacy", config={"callbacks": []}) == "LEGACY"
            assert len(offline_session.requests) > before_requests
        if mode == "inherit":
            current = resolve_run_snapshot(None, "alice", app_config=config)
            assert [provider.provider for provider in current.providers] == ["langsmith"]
