"""Middleware that enqueues S3 artifact sync after agent execution."""

import logging
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.storage.s3_artifact_store import is_s3_enabled

logger = logging.getLogger(__name__)


class ArtifactSyncMiddlewareState(AgentState):
    """Compatible with ThreadState schema."""

    pass


class ArtifactSyncMiddleware(AgentMiddleware[ArtifactSyncMiddlewareState]):
    """Enqueue S3 artifact sync after each agent execution."""

    state_schema = ArtifactSyncMiddlewareState

    @override
    def after_agent(self, state: ArtifactSyncMiddlewareState, runtime: Runtime) -> dict | None:
        if not is_s3_enabled():
            return None

        thread_id = runtime.context.get("thread_id")
        if not thread_id:
            return None

        user_id = runtime.context.get("user_id", "local")

        try:
            from src.queue.redis_connection import get_redis_client, is_redis_available

            if is_redis_available():
                from rq import Queue as RQQueue

                redis = get_redis_client()
                queue = RQQueue("artifact_sync", connection=redis)
                queue.enqueue(
                    "src.queue.artifact_tasks.sync_thread_to_s3",
                    user_id=user_id,
                    thread_id=thread_id,
                    job_timeout=300,
                )
                logger.info(f"Enqueued artifact sync for thread {thread_id}")
            else:
                logger.debug("Redis unavailable, skipping artifact sync enqueue")
        except Exception:
            logger.exception(f"Failed to enqueue artifact sync for thread {thread_id}")

        return None
