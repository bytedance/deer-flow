"""Thread API router for thread management and export."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.agents.messages import get_messages_export

router = APIRouter(prefix="/api/threads", tags=["threads"])


class ExportResponse(BaseModel):
    """Response model for thread export."""

    thread_id: str = Field(..., description="Thread ID")
    message_count: int = Field(..., description="Number of messages")
    messages: list = Field(default_factory=list, description="List of messages")


@router.get(
    "/{thread_id}/export",
    response_model=ExportResponse,
    summary="Export Thread",
    description="Export the full conversation history for a thread.",
)
async def export_thread(thread_id: str) -> ExportResponse:
    """Export thread messages.

    Args:
        thread_id: The thread ID.

    Returns:
        The exported thread messages.

    Raises:
        HTTPException: If thread not found or export fails.
    """
    data = get_messages_export(thread_id)
    
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"Thread {thread_id} not found or has no messages"
        )
    
    messages = data.get("messages", [])
    
    return ExportResponse(
        thread_id=thread_id,
        message_count=len(messages),
        messages=messages
    )
