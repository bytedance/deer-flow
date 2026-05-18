"""End-to-end test: middleware → SQLite storage → read API (plan M2).

This is the smoke test the plan §4.3 acceptance criteria call out:
spin up real audit storage backed by a temp SQLite file, run the
middleware against a fake tool call, then read the rows back through
the same storage to confirm the full chain landed in the table with
valid signatures.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from langchain_core.messages import ToolMessage
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.enterprise.audit.events import AuditEventType
from deerflow.enterprise.audit.middleware import AuditMiddleware
from deerflow.enterprise.audit.signer import AuditSigner
from deerflow.enterprise.audit.storage import AuditQueryFilter, SqliteAuditStorage
from deerflow.enterprise.config import AuditConfig
from deerflow.persistence.base import Base


@pytest_asyncio.fixture
async def storage_with_engine(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'e2e.db'}"
    engine = create_async_engine(url)
    from deerflow.enterprise.audit.storage import AuditEventRow  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    yield SqliteAuditStorage(sf)
    await engine.dispose()


@pytest.mark.asyncio
async def test_middleware_writes_signed_row_readable_by_storage(storage_with_engine):
    signer = AuditSigner("e2e-key")
    cfg = AuditConfig(enabled=True, sign_key="e2e-key")
    mw = AuditMiddleware(cfg, storage_with_engine, signer)

    runtime = SimpleNamespace(context={"thread_id": "t1", "user_id": "alice"}, config={})

    async def handler(_req):
        return ToolMessage(content="ok", tool_call_id="c-1", name="bash")

    request = SimpleNamespace(
        tool_call={"name": "bash", "id": "c-1", "args": {"command": "ls"}},
        runtime=runtime,
    )

    await mw.abefore_agent(state={}, runtime=runtime)
    await mw.awrap_tool_call(request, handler)
    await mw.aafter_agent(state={}, runtime=runtime)

    rows = await storage_with_engine.query(AuditQueryFilter(limit=10))
    assert {r.event_type for r in rows} == {
        AuditEventType.AGENT_TASK_STARTED,
        AuditEventType.SANDBOX_COMMAND_EXECUTED,
        AuditEventType.AGENT_TASK_COMPLETED,
    }
    # Every row carries a valid signature — tamper-evidence end-to-end.
    assert all(signer.verify(r) for r in rows)
    assert await storage_with_engine.verify_integrity(signer) is True
