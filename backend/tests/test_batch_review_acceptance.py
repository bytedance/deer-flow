"""New consumer through actual formatter/worker/reopened SQLite and PostgreSQL."""

from unittest.mock import AsyncMock

import pytest
from test_batch_rag_evidence import env as env
from test_batch_rag_evidence import execute, retrieval

from deerflow.extensions.batch_results import RepositoryBatchResultReader
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.subagent_batches import SubagentBatchRepository


@pytest.mark.asyncio
async def test_saved_result_reader_survives_worker_shutdown_provider_loss_and_database_reopen(env):
    env.result.result, env.result.ai_messages = retrieval(text="Historical excerpt; provider now unavailable")
    batch = await execute(env)
    await env.service.stop()
    await close_engine()
    await init_engine_from_config(env.db)
    repository = SubagentBatchRepository(get_session_factory())
    reader = RepositoryBatchResultReader(repository, user_id="user-1", check_thread=AsyncMock(return_value=True))
    saved = await reader.read_item(thread_id="thread-1", batch_id=batch["id"], position=0)
    assert saved["result"] == env.result.result
    assert saved["evidence"]["sources"][0]["text"] == "Historical excerpt; provider now unavailable"
    assert saved["evidence"]["sources"][0]["document_name"] == "Manual.pdf"
    assert saved["status"] == "succeeded"
    assert "execution_spec" not in saved and "prompt" not in saved
    env.result.ai_messages.clear()
    assert await reader.read_item(thread_id="thread-1", batch_id=batch["id"], position=0) == saved
    other_owner = RepositoryBatchResultReader(repository, user_id="another-user", check_thread=AsyncMock(return_value=True))
    assert await other_owner.read_item(thread_id="thread-1", batch_id=batch["id"], position=0) is None
    assert await reader.read_item(thread_id="other-thread", batch_id=batch["id"], position=0) is None
    assert await reader.read_item(thread_id="thread-1", batch_id=batch["id"], position=1) is None


@pytest.mark.asyncio
async def test_plugin_actions_use_only_public_reader_and_reject_owner_in_payload(env):
    import importlib.util
    from pathlib import Path

    from deerflow_extension_api.auth import ExtensionPrincipal
    from deerflow_extension_api.plugins import ActionContext

    path = Path(__file__).resolve().parents[2] / "examples/deerflow-extension-batch-review/deerflow_extension_batch_review/__init__.py"
    spec = importlib.util.spec_from_file_location("batch_review_test", path)
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    env.result.result, env.result.ai_messages = retrieval()
    batch = await execute(env)
    reader = RepositoryBatchResultReader(env.repo, user_id="user-1", check_thread=AsyncMock(return_value=True))
    context = ActionContext(ExtensionPrincipal("user-1"), {"enabled": True}, batch_results=lambda: reader)
    saved = await plugin.result({"thread_id": "thread-1", "batch_id": batch["id"], "position": 0}, context)
    assert saved["evidence"]["sources"][0]["text"] == "Original evidence"
    with pytest.raises(ValueError):
        await plugin.result({"thread_id": "thread-1", "batch_id": batch["id"], "position": 0, "user_id": "another-user"}, context)
