"""Gateway-lifetime extension service: schema chain, stores, and the indexing worker.

The host starts it once persistence is ready (``ExtensionService.start(deps)``) and stops
it on shutdown. Both contributed routers read the app-layer ``KnowledgeService`` through
this object, so they answer 503 while it is not running.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

from deerflow_knowledge.services.knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)


class KnowledgeExtensionService:
    """Owns the store / vector-store / worker trio for the extension's lifetime."""

    def __init__(self) -> None:
        self.knowledge: KnowledgeService | None = None
        self._worker = None

    def require_knowledge_service(self) -> KnowledgeService:
        """The app-layer service, or 503 while the extension is not running."""
        if self.knowledge is None:
            raise HTTPException(status_code=503, detail="Knowledge service not available")
        return self.knowledge

    async def start(self, deps) -> None:
        """Bring the extension's schema to head, then build and start the pipeline."""
        from deerflow.config.app_config import get_app_config
        from deerflow.config.paths import get_paths
        from deerflow_knowledge.migrations.runner import run_knowledge_migrations
        from deerflow_knowledge.services.rag_migration import migration_running
        from deerflow_knowledge.store import KnowledgeStore
        from deerflow_knowledge.vector_store import get_vector_store
        from deerflow_knowledge.worker import KnowledgeIndexWorker

        session_factory = deps.session_factory
        if session_factory is None:
            raise RuntimeError("the knowledge extension needs a durable database session factory")

        # The extension owns its schema end to end: its private chain runs before anything
        # reads a table, versioned under kb_alembic_version and advisory-locked on Postgres
        # so concurrent Gateway instances serialise (mirrors bootstrap_schema).
        await run_knowledge_migrations(session_factory)

        config = get_app_config()
        rag = config.rag
        data_dir = get_paths().base_dir / "data"
        store = KnowledgeStore(session_factory)
        vector_store = get_vector_store()
        worker = KnowledgeIndexWorker(
            store=store,
            vector_store=vector_store,
            concurrency=rag.worker_concurrency,
            sweep_enabled=rag.sweep_enabled,
            sweep_interval_hours=rag.sweep_interval_hours,
            data_dir=data_dir,
            migration_running_fn=migration_running,
        )
        await worker.start()
        self._worker = worker
        self.knowledge = KnowledgeService(
            store=store,
            vector_store=vector_store,
            worker=worker,
            data_dir=data_dir,
        )
        logger.info("Knowledge extension started (concurrency=%d)", rag.worker_concurrency)

    async def stop(self) -> None:
        worker, self._worker = self._worker, None
        self.knowledge = None
        if worker is not None:
            await worker.stop()
