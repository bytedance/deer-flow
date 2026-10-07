"""Loopback-only real plugin/SQL/action preview, with explicitly synthetic auth."""

import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import uvicorn
from deerflow_extension_api.auth import EXTENSION_PRINCIPAL_RESOLVER_KEY
from deerflow_extension_api.batch_results import BATCH_RESULTS_RESOLVER_KEY
from fastapi import FastAPI

from app.gateway.app import create_app as create_host_app
from app.gateway.routers.plugins import router
from deerflow.community.ragflow.formatting import format_retrieval_sources
from deerflow.community.ragflow.sources import durable_source_artifact
from deerflow.config.database_config import DatabaseConfig
from deerflow.extensions.loader import ExtensionSpec, load_extensions
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.subagent_batches import SubagentBatchRepository
from deerflow.persistence.thread_meta import make_thread_store

THREAD = "550e8400-e29b-41d4-a716-446655440000"


async def create_app(directory):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-batch-review"))
    extensions, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_batch_review:install", config={"enabled": True}, required=True)])
    assert not diagnostics
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(Path(directory))))
    repository = SubagentBatchRepository(get_session_factory())
    await repository.create_batch(
        batch_id="research-batch",
        user_id="alice",
        thread_id=THREAD,
        run_id="run",
        tool_call_id="call",
        submission_key="preview",
        title="Historical research",
        subagent_type="general-purpose",
        items=[{"key": f"topic-{i}", "prompt": "Research"} for i in range(51)],
        max_live_items=1,
        max_running_items=1,
        max_attempts=2,
        execution_spec={"private": "DO NOT EXPOSE"},
    )
    claimed = await repository.claim_items(now=datetime.now(UTC), lease_owner="preview", lease_seconds=60, limit=1)
    report, artifact = format_retrieval_sources(
        {"chunks": [{"id": "chunk", "dataset_id": "dataset", "document_id": "doc", "document_keyword": "Captured.pdf", "content": "Original source <script>window.PWNED = true</script>"}]},
        dataset_names_by_id={"dataset": "Original dataset"},
        max_chars_per_chunk=2000,
        max_total_chars=3000,
    )
    report = "Full saved report\n" + report + "\n<script>window.PWNED = true</script>"
    snapshot = durable_source_artifact([{"type": "tool", "name": "knowledge_search", "artifact": artifact}], report, max_chars=100_000)
    await repository.finalize_item(
        claimed[0]["id"],
        lease_owner="preview",
        succeeded=True,
        result=report,
        result_preview="Full saved…",
        result_truncated=False,
        error=None,
        stop_reason=None,
        token_usage=None,
        model_name="offline",
        completed_at=datetime.now(UTC),
        result_artifact=snapshot,
    )
    host = create_host_app()
    host.state.subagent_batch_repo = repository
    host.state.thread_store = make_thread_store(get_session_factory(), None)
    host.state.subagent_batches_available = False

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            await close_engine()

    app = FastAPI(lifespan=lifespan)
    app.state.extensions = extensions
    for key in (EXTENSION_PRINCIPAL_RESOLVER_KEY, BATCH_RESULTS_RESOLVER_KEY):
        setattr(app.state, key, getattr(host.state, key))

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.user = SimpleNamespace(id=request.headers.get("x-test-user", "alice"), system_role="user")
        request.state.auth_source = "session"
        request.state.auth = SimpleNamespace(has_permission=lambda resource, action: request.headers.get("x-test-denied") != "1")
        return await call_next(request)

    app.include_router(router)

    @app.get("/health")
    async def health():
        return {"fixture": "synthetic auth; worker stopped"}

    return app


if __name__ == "__main__":
    with TemporaryDirectory(prefix="deerflow-batch-review-preview-") as directory:
        uvicorn.run(asyncio.run(create_app(directory)), host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
