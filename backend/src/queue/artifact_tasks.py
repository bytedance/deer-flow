"""RQ job functions for S3 artifact synchronisation.

These run in background worker processes. Follows the same pattern as memory_tasks.py.
"""

import logging
import shutil

logger = logging.getLogger(__name__)


def sync_thread_to_s3(user_id: str, thread_id: str) -> bool:
    """Upload all local artifacts for a thread to S3 and mark as synced."""
    from src.config.paths import get_paths
    from src.db.engine import get_db_session
    from src.db.models import ThreadModel
    from src.storage.s3_artifact_store import get_s3_artifact_store

    store = get_s3_artifact_store()
    if store is None:
        return False

    local_dir = get_paths().sandbox_user_data_dir(thread_id)
    logger.info(f"Syncing thread {thread_id} (user {user_id}) to S3")

    try:
        count = store.sync_thread(user_id, thread_id, local_dir)
        logger.info(f"Uploaded {count} files for thread {thread_id}")
    except Exception:
        logger.exception(f"Failed to sync thread {thread_id} to S3")
        return False

    try:
        with get_db_session() as session:
            thread = session.get(ThreadModel, thread_id)
            if thread:
                thread.s3_sync_status = "synced"
    except Exception:
        logger.exception(f"Failed to update sync status for thread {thread_id}")

    return True


def delete_thread_from_s3(user_id: str, thread_id: str) -> bool:
    """Delete all S3 objects for a thread."""
    from src.storage.s3_artifact_store import get_s3_artifact_store

    store = get_s3_artifact_store()
    if store is None:
        return False

    logger.info(f"Deleting S3 artifacts for thread {thread_id} (user {user_id})")
    try:
        deleted = store.delete_thread(user_id, thread_id)
        logger.info(f"Deleted {deleted} S3 objects for thread {thread_id}")
        return True
    except Exception:
        logger.exception(f"Failed to delete S3 artifacts for thread {thread_id}")
        return False


def delete_user_from_s3(user_id: str) -> bool:
    """Delete all S3 objects for a user."""
    from src.storage.s3_artifact_store import get_s3_artifact_store

    store = get_s3_artifact_store()
    if store is None:
        return False

    logger.info(f"Deleting all S3 artifacts for user {user_id}")
    try:
        deleted = store.delete_user(user_id)
        logger.info(f"Deleted {deleted} S3 objects for user {user_id}")
        return True
    except Exception:
        logger.exception(f"Failed to delete S3 artifacts for user {user_id}")
        return False


def evict_stale_threads(retention_days: int = 7) -> dict:
    """Evict locally cached thread data that has been synced to S3.

    Finds threads where last_accessed_at < now - retention_days AND
    s3_sync_status = 'synced', verifies sync, then deletes local directory.

    Returns:
        Dict with counts: {"evicted": N, "skipped": N, "errors": N}
    """
    from datetime import UTC, datetime, timedelta

    from src.config.paths import get_paths
    from src.db.engine import get_db_session
    from src.db.models import ThreadModel
    from src.storage.s3_artifact_store import get_s3_artifact_store

    store = get_s3_artifact_store()
    if store is None:
        logger.info("S3 not configured, skipping eviction")
        return {"evicted": 0, "skipped": 0, "errors": 0}

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    paths = get_paths()
    result = {"evicted": 0, "skipped": 0, "errors": 0}

    with get_db_session() as session:
        stale_threads = (
            session.query(ThreadModel)
            .filter(
                ThreadModel.s3_sync_status == "synced",
                ThreadModel.local_evicted == False,  # noqa: E712
                ThreadModel.last_accessed_at != None,  # noqa: E711
                ThreadModel.last_accessed_at < cutoff,
            )
            .all()
        )

        logger.info(f"Found {len(stale_threads)} stale threads for eviction (cutoff={cutoff.isoformat()})")

        for thread in stale_threads:
            thread_dir = paths.thread_dir(thread.thread_id)
            local_user_data = paths.sandbox_user_data_dir(thread.thread_id)

            if not thread_dir.exists():
                thread.local_evicted = True
                result["skipped"] += 1
                continue

            try:
                if not store.is_synced(thread.user_id, thread.thread_id, local_user_data):
                    logger.warning(f"Thread {thread.thread_id} not fully synced, skipping eviction")
                    result["skipped"] += 1
                    continue

                shutil.rmtree(thread_dir)
                thread.local_evicted = True
                result["evicted"] += 1
                logger.info(f"Evicted local data for thread {thread.thread_id}")
            except Exception:
                logger.exception(f"Error evicting thread {thread.thread_id}")
                result["errors"] += 1

    logger.info(f"Eviction complete: {result}")
    return result
