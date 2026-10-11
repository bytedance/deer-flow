"""New consumer through actual formatter/worker/reopened SQLite and PostgreSQL."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from test_batch_rag_evidence import env as env
from test_batch_rag_evidence import execute, retrieval

from app.gateway.routers.subagent_batches import get_batch_item_result
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.subagent_batches import SubagentBatchRepository


@pytest.mark.asyncio
async def test_saved_result_reader_survives_worker_shutdown_provider_loss_and_database_reopen(env, monkeypatch):
    env.result.result, env.result.ai_messages = retrieval(text="Historical excerpt; provider now unavailable")
    batch = await execute(env)
    await env.service.stop()
    await close_engine()
    await init_engine_from_config(env.db)
    repository = SubagentBatchRepository(get_session_factory())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(subagent_batch_repo=repository)))

    async def current_user(request):
        return "user-1"

    monkeypatch.setattr("app.gateway.routers.subagent_batches.get_current_user", current_user)
    saved = await get_batch_item_result.__wrapped__(request=request, thread_id="thread-1", batch_id=batch["id"], position=0)
    assert saved["result"] == env.result.result
    assert saved["evidence"]["sources"][0]["text"] == "Historical excerpt; provider now unavailable"
    assert saved["evidence"]["sources"][0]["document_name"] == "Manual.pdf"
    assert saved["status"] == "succeeded"
    assert "execution_spec" not in saved and "prompt" not in saved
    env.result.ai_messages.clear()
    assert await get_batch_item_result.__wrapped__(request=request, thread_id="thread-1", batch_id=batch["id"], position=0) == saved
    for thread_id, position in (("other-thread", 0), ("thread-1", 1)):
        with pytest.raises(HTTPException) as denied:
            await get_batch_item_result.__wrapped__(request=request, thread_id=thread_id, batch_id=batch["id"], position=position)
        assert denied.value.status_code == 404
