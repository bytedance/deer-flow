"""Thread router for thread-level operations.

Provides user-scoped thread CRUD: list, delete, rename, claim,
and message truncation. All endpoints require JWT authentication
and enforce per-user ownership via the thread store.
"""

import logging
import os
import shutil
import stat
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import RemoveMessage
from langgraph_sdk import get_client
from pydantic import BaseModel

from src.config.paths import get_paths
from src.gateway.auth.middleware import get_current_user
from src.gateway.auth.ownership import verify_thread_ownership
from src.gateway.auth.thread_store import (
    claim_thread,
    get_user_threads,
)
from src.gateway.auth.thread_store import (
    delete_thread as delete_thread_ownership,
)
from src.gateway.config import get_gateway_config
from src.gateway.rate_limiter import check_user_api_rate

logger = logging.getLogger(__name__)

# Router for /api/threads (collection-level, no thread_id in path)
router_list = APIRouter(prefix="/api/threads", tags=["threads"])

# Router for /api/threads/{thread_id} (item-level operations)
router = APIRouter(prefix="/api/threads/{thread_id}", tags=["threads"])


def _langgraph_url() -> str:
    """Get the LangGraph server URL from configuration."""
    return get_gateway_config().langgraph_url


# ── Pydantic Models ──────────────────────────────────────────────────────────


class TruncateMessagesRequest(BaseModel):
    """Request model for truncating messages."""

    message_index: int


class TruncateMessagesResponse(BaseModel):
    """Response model for message truncation."""

    success: bool
    messages_kept: int
    messages_removed: int
    checkpoint_id: str | None = None
    checkpoint_ns: str | None = None


class ThreadRenameRequest(BaseModel):
    """Request model for renaming a thread."""

    title: str


class ThreadClaimResponse(BaseModel):
    """Response model for claiming thread ownership."""

    success: bool
    thread_id: str


# ── Collection Endpoints (/api/threads) ──────────────────────────────────────


@router_list.get("")
async def list_threads(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> list[dict[str, Any]]:
    """List all threads owned by the authenticated user.

    Returns thread objects with metadata (title, timestamps, etc.)
    fetched from LangGraph, filtered to only those owned by the user.
    Falls back to ownership store data if LangGraph is unavailable.

    Args:
        current_user: The authenticated user (injected by dependency).

    Returns:
        List of thread objects belonging to the user, sorted by updated_at desc.
    """
    user_id = current_user["id"]
    check_user_api_rate(user_id)

    try:
        # Get thread IDs owned by this user from the ownership store
        owned_thread_ids = get_user_threads(user_id)

        if not owned_thread_ids:
            return []

        owned_set = set(owned_thread_ids)

        # Fetch thread details from LangGraph
        langgraph_threads: dict[str, dict[str, Any]] = {}
        try:
            client = get_client(url=_langgraph_url())
            all_threads = await client.threads.search(
                limit=100,
                sort_by="updated_at",
                sort_order="desc",
            )
            langgraph_threads = {
                t["thread_id"]: t for t in all_threads if t["thread_id"] in owned_set
            }
        except Exception as e:
            logger.warning(f"Failed to fetch threads from LangGraph for user {user_id}: {e}")

        # Build result: use LangGraph data where available, fall back to stubs
        user_threads: list[dict[str, Any]] = []
        for tid in owned_thread_ids:
            if tid in langgraph_threads:
                user_threads.append(langgraph_threads[tid])
            else:
                # Thread exists in ownership store but not in LangGraph.
                # Return a stub so the UI can still display it.
                user_threads.append({
                    "thread_id": tid,
                    "values": {},
                    "metadata": {},
                    "status": "idle",
                    "created_at": "",
                    "updated_at": "",
                })

        # Sort by updated_at desc (LangGraph threads have timestamps, stubs sort last)
        user_threads.sort(key=lambda t: t.get("updated_at", ""), reverse=True)

        return user_threads

    except Exception as e:
        logger.error(f"Error listing threads for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list threads: {str(e)}")


# ── Item Endpoints (/api/threads/{thread_id}) ────────────────────────────────


@router.delete("")
async def delete_thread(
    thread_id: str,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, bool]:
    """Delete a thread.

    Verifies ownership, deletes the thread from LangGraph, and removes
    the ownership record.

    Args:
        thread_id: The thread ID.
        current_user: The authenticated user (injected by dependency).

    Returns:
        Success status.

    Raises:
        HTTPException: If the user doesn't own the thread or deletion fails.
    """
    verify_thread_ownership(thread_id, current_user["id"])

    try:
        client = get_client(url=_langgraph_url())
        await client.threads.delete(thread_id)
    except Exception as e:
        logger.error(f"Error deleting thread {thread_id} from LangGraph: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete thread: {str(e)}")

    # Remove ownership record (best-effort; thread is already deleted)
    try:
        delete_thread_ownership(thread_id)
    except Exception as e:
        logger.warning(f"Failed to remove ownership record for {thread_id}: {e}")

    # Delete local thread directory (best-effort)
    # Files may be owned by root (created inside Docker containers), so fix
    # permissions on the fly before retrying the removal.
    def _rmtree_onerror(_func, path, _exc_info):
        try:
            os.chmod(path, stat.S_IRWXU)
            parent = os.path.dirname(path)
            os.chmod(parent, stat.S_IRWXU)
            _func(path)
        except Exception:
            pass

    try:
        thread_dir = get_paths().thread_dir(thread_id)
        if thread_dir.exists():
            shutil.rmtree(thread_dir, onerror=_rmtree_onerror)
    except Exception as e:
        logger.warning(f"Failed to delete local thread directory for {thread_id}: {e}")

    # Enqueue S3 deletion if S3 is configured (best-effort)
    try:
        from src.storage.s3_artifact_store import is_s3_enabled

        if is_s3_enabled():
            from src.queue.redis_connection import get_redis_client, is_redis_available

            if is_redis_available():
                from rq import Queue as RQQueue

                redis = get_redis_client()
                queue = RQQueue("artifact_sync", connection=redis)
                queue.enqueue(
                    "src.queue.artifact_tasks.delete_thread_from_s3",
                    user_id=current_user["id"],
                    thread_id=thread_id,
                    job_timeout=120,
                )
    except Exception as e:
        logger.warning(f"Failed to enqueue S3 deletion for {thread_id}: {e}")

    logger.info(f"Deleted thread {thread_id} for user {current_user['id']}")
    return {"success": True}


@router.patch("")
async def rename_thread(
    thread_id: str,
    request: ThreadRenameRequest,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, bool]:
    """Rename a thread by updating its title in LangGraph state.

    Args:
        thread_id: The thread ID.
        request: Request containing the new title.
        current_user: The authenticated user (injected by dependency).

    Returns:
        Success status.

    Raises:
        HTTPException: If the user doesn't own the thread or rename fails.
    """
    verify_thread_ownership(thread_id, current_user["id"])

    try:
        client = get_client(url=_langgraph_url())
        await client.threads.update_state(
            thread_id,
            {"values": {"title": request.title}},
        )
    except Exception as e:
        logger.error(f"Error renaming thread {thread_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to rename thread: {str(e)}")

    logger.info(f"Renamed thread {thread_id} to '{request.title}'")
    return {"success": True}


@router.post("/claim", response_model=ThreadClaimResponse)
async def claim_thread_ownership(
    thread_id: str,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> ThreadClaimResponse:
    """Claim ownership of a thread.

    If the thread is unclaimed, assigns it to the authenticated user.
    If already owned by this user, returns success.
    If owned by a different user, returns failure.

    Args:
        thread_id: The thread ID to claim.
        current_user: The authenticated user (injected by dependency).

    Returns:
        Claim result with success status.
    """
    user_id = current_user["id"]
    success = claim_thread(thread_id, user_id)

    if not success:
        raise HTTPException(
            status_code=403,
            detail="Thread is owned by another user",
        )

    logger.info(f"Thread {thread_id} claimed by user {user_id}")
    return ThreadClaimResponse(success=True, thread_id=thread_id)


@router.post("/truncate-messages", response_model=TruncateMessagesResponse)
async def truncate_messages(
    thread_id: str,
    request: TruncateMessagesRequest,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> TruncateMessagesResponse:
    """Truncate thread messages up to a specific index.

    This endpoint removes all messages after the specified index and prepares
    the thread for regenerating responses from that point.

    Args:
        thread_id: The thread ID
        request: Request containing the message_index to truncate from
        current_user: The authenticated user (injected by dependency).

    Returns:
        Response with truncation results

    Raises:
        HTTPException: If truncation fails
    """
    verify_thread_ownership(thread_id, current_user["id"])

    try:
        # Get LangGraph client
        client = get_client(url=_langgraph_url())

        # Get current thread state
        state = await client.threads.get_state(thread_id)

        # state is a dict with keys like 'values', 'next', 'checkpoint', etc.
        # The actual thread data is in state['values']
        if not state or "values" not in state or "messages" not in state["values"]:
            raise HTTPException(status_code=404, detail="Thread or messages not found")

        raw_messages = state["values"]["messages"]
        message_index = request.message_index

        # Validate index
        if message_index < 0 or message_index >= len(raw_messages):
            raise HTTPException(status_code=400, detail=f"Invalid message index: {message_index}. Valid range: 0-{len(raw_messages) - 1}")

        # Remove the selected message and everything after it.
        messages_to_remove = raw_messages[message_index:]
        messages_kept = message_index
        messages_removed = len(messages_to_remove)

        remove_message_updates: list[RemoveMessage] = []
        for msg in messages_to_remove:
            msg_id = msg.get("id") if isinstance(msg, dict) else getattr(msg, "id", None)
            if msg_id:
                remove_message_updates.append(RemoveMessage(id=msg_id))
            else:
                logger.warning(f"Skipping message without id during truncation for thread {thread_id}: {msg}")

        if not remove_message_updates:
            raise HTTPException(status_code=400, detail="No valid messages found to remove")

        # Pin the update to the exact checkpoint we read so we don't try to
        # remove IDs that don't exist at a different checkpoint.
        fetched_checkpoint = state.get("checkpoint", {}) if isinstance(state, dict) else {}
        checkpoint_id = fetched_checkpoint.get("checkpoint_id") if isinstance(fetched_checkpoint, dict) else None

        # Use RemoveMessage updates so LangGraph's add_messages reducer actually
        # deletes messages instead of merging/appending.
        update_result = await client.threads.update_state(
            thread_id,
            {"messages": remove_message_updates},
            checkpoint_id=checkpoint_id,
        )

        checkpoint = update_result.get("checkpoint", {}) if isinstance(update_result, dict) else {}
        checkpoint_id = checkpoint.get("checkpoint_id") if isinstance(checkpoint, dict) else None
        checkpoint_ns = checkpoint.get("checkpoint_ns") if isinstance(checkpoint, dict) else None

        logger.info(f"Truncated thread {thread_id}: kept {messages_kept} messages, removed {messages_removed}")

        return TruncateMessagesResponse(
            success=True,
            messages_kept=messages_kept,
            messages_removed=messages_removed,
            checkpoint_id=checkpoint_id,
            checkpoint_ns=checkpoint_ns,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error truncating messages for thread {thread_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to truncate messages: {str(e)}")
