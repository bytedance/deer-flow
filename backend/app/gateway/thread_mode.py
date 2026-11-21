"""The conversation mode used by run admission and thread file operations."""

import asyncio
import logging
from collections.abc import Mapping
from typing import Annotated, Any, Literal, get_args

from fastapi import HTTPException
from pydantic import AfterValidator
from sqlalchemy.exc import DisconnectionError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from deerflow.agents.chat_mode import has_attachment_fields, has_chat_attachment
from deerflow.config.agents_config import AGENT_NAME_PATTERN
from deerflow.persistence.thread_meta import ThreadMetaStore

logger = logging.getLogger(__name__)

ThreadMode = Literal["flash", "thinking", "pro", "ultra", "chat"]
_MODES = get_args(ThreadMode)


def selected_mode(metadata: object) -> str | None:
    mode = metadata.get("mode") if isinstance(metadata, Mapping) else None
    return mode if mode in _MODES else None


def validate_mode_options(options: dict[str, Any], *, allow_null: bool = True) -> dict[str, Any]:
    if "mode" not in options or (allow_null and options["mode"] is None):
        return options
    if selected_mode(options) is None:
        raise ValueError(f"Unsupported conversation mode. Choose one of {', '.join(_MODES)}.")
    return options


RunModeOptions = Annotated[dict[str, Any], AfterValidator(validate_mode_options)]


def saved_thread_mode(metadata: object) -> str | None:
    """An old row may have no selection or contain a value this Gateway cannot run."""
    if metadata is None or (isinstance(metadata, Mapping) and metadata.get("mode") is None):
        return None
    mode = selected_mode(metadata)
    if mode is None:
        raise HTTPException(409, "Saved conversation mode is unsupported. Select a supported mode.")
    return mode


def stored_custom_agent(value: object) -> str | None:
    """Recover a custom identifier from a server-owned run or checkpoint binding."""
    return value if isinstance(value, str) and AGENT_NAME_PATTERN.fullmatch(value) else None


def state_has_attachments(values: Mapping) -> bool:
    """Accept normalized graph input or a checkpoint update at the HTTP boundary."""
    return has_attachment_fields(values) or bool(values.get("uploaded_files") or values.get("tool_artifacts")) or any(has_chat_attachment(message) for message in values.get("messages") or [])


async def thread_mode(store: ThreadMetaStore, thread_id: str, *, user_id: str | None, internal_owner_id: str | None = None, require_existing: bool = False) -> str | None:
    """Read the mode after authorization, including on shared pre-auth rows."""
    try:
        async with asyncio.timeout(5):
            # The scoped store read hides NULL-owner legacy rows even from a
            # caller with check_access. Inspect the owner before using any mode.
            try:
                row = await store.get(thread_id, user_id=None)
            except (OSError, DisconnectionError, InterfaceError, OperationalError, SQLAlchemyTimeoutError):
                # A transient read can fail after ownership was checked. Retry
                # inside the same deadline before changing the thread's file policy.
                row = await store.get(thread_id, user_id=None)
    except Exception as exc:
        logger.warning("Could not read conversation mode", exc_info=True)
        raise HTTPException(503, "Conversation mode is unavailable") from exc
    if row is None:
        if require_existing:
            raise HTTPException(404, f"Thread {thread_id} not found")
        return None
    if row.get("user_id") not in (None, user_id, internal_owner_id):
        raise HTTPException(404, "Thread not found")
    return saved_thread_mode(row.get("metadata"))


def require_file_mode(mode: str | None) -> None:
    if mode == "chat":
        raise HTTPException(422, "Chat mode accepts text only and cannot write workspace files")


async def require_thread_files(store: ThreadMetaStore, thread_id: str, *, user_id: str, internal_owner_id: str | None = None) -> None:
    mode = await thread_mode(store, thread_id, user_id=user_id, internal_owner_id=internal_owner_id)
    require_file_mode(mode)
