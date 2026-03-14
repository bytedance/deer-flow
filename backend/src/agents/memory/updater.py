"""Memory updater for reading, writing, and updating memory data.

Supports dual-mode storage: PostgreSQL (when DATABASE_URL is set)
or file-based (local / Electron dev).
"""

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.agents.memory.prompt import (
    MEMORY_UPDATE_PROMPT,
    format_conversation_for_update,
)
from src.config.memory_config import get_memory_config
from src.config.paths import get_paths
from src.models import create_chat_model

logger = logging.getLogger(__name__)

# Default user ID for backward compatibility (Electron single-user mode)
DEFAULT_USER_ID = "local"


# ---------------------------------------------------------------------------
# File-based memory storage
# ---------------------------------------------------------------------------
def _get_memory_file_path(user_id: str = DEFAULT_USER_ID) -> Path:
    """Get the path to the user-specific memory file.

    Args:
        user_id: The user identifier. Defaults to "local" for backward compat.

    Returns:
        Path to the user's memory JSON file.
    """
    base_dir = get_paths().base_dir / "memory"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / f"{user_id}.json"


def _create_empty_memory() -> dict[str, Any]:
    """Create an empty memory structure."""
    return {
        "version": "1.0",
        "lastUpdated": datetime.now(UTC).isoformat(),
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": [],
    }


# Per-user memory data cache: { user_id: memory_dict }
_memory_data: dict[str, dict[str, Any]] = {}
# Per-user file modification time tracking: { user_id: mtime }
_memory_file_mtime: dict[str, float | None] = {}


def _load_memory_from_file(user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
    """Load memory data from file.

    Args:
        user_id: The user identifier.

    Returns:
        The memory data dictionary.
    """
    file_path = _get_memory_file_path(user_id)

    if not file_path.exists():
        return _create_empty_memory()

    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load memory file for user {user_id}: {e}")
        return _create_empty_memory()


# Matches sentences that describe a file-upload *event* rather than general
# file-related work.  Deliberately narrow to avoid removing legitimate facts
# such as "User works with CSV files" or "prefers PDF export".
_UPLOAD_SENTENCE_RE = re.compile(
    r"[^.!?]*\b(?:"
    r"upload(?:ed|ing)?(?:\s+\w+){0,3}\s+(?:file|files?|document|documents?|attachment|attachments?)"
    r"|file\s+upload"
    r"|/mnt/user-data/uploads/"
    r"|<uploaded_files>"
    r")[^.!?]*[.!?]?\s*",
    re.IGNORECASE,
)


def _strip_upload_mentions_from_memory(memory_data: dict[str, Any]) -> dict[str, Any]:
    """Remove sentences about file uploads from all memory summaries and facts.

    Uploaded files are session-scoped; persisting upload events in long-term
    memory causes the agent to search for non-existent files in future sessions.
    """
    # Scrub summaries in user/history sections
    for section in ("user", "history"):
        section_data = memory_data.get(section, {})
        for _key, val in section_data.items():
            if isinstance(val, dict) and "summary" in val:
                cleaned = _UPLOAD_SENTENCE_RE.sub("", val["summary"]).strip()
                cleaned = re.sub(r"  +", " ", cleaned)
                val["summary"] = cleaned

    # Also remove any facts that describe upload events
    facts = memory_data.get("facts", [])
    if facts:
        memory_data["facts"] = [
            f
            for f in facts
            if not _UPLOAD_SENTENCE_RE.search(f.get("content", ""))
        ]

    return memory_data


def _save_memory_to_file(user_id: str, memory_data: dict[str, Any]) -> bool:
    """Save memory data to file and update cache.

    Args:
        user_id: The user identifier.
        memory_data: The memory data to save.

    Returns:
        True if successful, False otherwise.
    """
    file_path = _get_memory_file_path(user_id)

    try:
        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Update lastUpdated timestamp
        memory_data["lastUpdated"] = datetime.now(UTC).isoformat()

        # Write atomically using temp file
        temp_path = file_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(memory_data, f, indent=2, ensure_ascii=False)

        # Rename temp file to actual file (atomic on most systems)
        temp_path.replace(file_path)

        # Update cache and file modification time
        _memory_data[user_id] = memory_data
        try:
            _memory_file_mtime[user_id] = file_path.stat().st_mtime
        except OSError:
            _memory_file_mtime[user_id] = None

        logger.info(f"Memory saved for user {user_id} to {file_path}")
        return True
    except OSError as e:
        logger.error(f"Failed to save memory file for user {user_id}: {e}")
        return False


def _file_get_memory_data(user_id: str) -> dict[str, Any]:
    """Get memory data from file with caching."""
    file_path = _get_memory_file_path(user_id)

    # Get current file modification time
    try:
        current_mtime = file_path.stat().st_mtime if file_path.exists() else None
    except OSError:
        current_mtime = None

    # Invalidate cache if file has been modified or doesn't exist
    cached = _memory_data.get(user_id)
    cached_mtime = _memory_file_mtime.get(user_id)
    if cached is None or cached_mtime != current_mtime:
        _memory_data[user_id] = _load_memory_from_file(user_id)
        _memory_file_mtime[user_id] = current_mtime

    return _memory_data[user_id]


def _file_reload_memory_data(user_id: str) -> dict[str, Any]:
    """Reload memory data from file, forcing cache invalidation."""
    file_path = _get_memory_file_path(user_id)
    _memory_data[user_id] = _load_memory_from_file(user_id)

    try:
        _memory_file_mtime[user_id] = file_path.stat().st_mtime if file_path.exists() else None
    except OSError:
        _memory_file_mtime[user_id] = None

    return _memory_data[user_id]


# ---------------------------------------------------------------------------
# Database-backed memory storage
# ---------------------------------------------------------------------------
def _db_get_memory_data(user_id: str) -> dict[str, Any]:
    """Get memory data from database with in-memory caching."""
    # Check in-memory cache first
    cached = _memory_data.get(user_id)
    if cached is not None:
        return cached

    from src.db.engine import get_db_session
    from src.db.models import UserMemoryModel

    with get_db_session() as session:
        record = session.query(UserMemoryModel).filter(UserMemoryModel.user_id == user_id).first()
        if record and record.memory_json:
            memory = record.memory_json
        else:
            memory = _create_empty_memory()

    _memory_data[user_id] = memory
    return memory


def _db_reload_memory_data(user_id: str) -> dict[str, Any]:
    """Reload memory data from database, forcing cache invalidation."""
    # Clear cache to force re-read
    _memory_data.pop(user_id, None)
    return _db_get_memory_data(user_id)


def _db_save_memory(user_id: str, memory_data: dict[str, Any]) -> bool:
    """Save memory data to database.

    Args:
        user_id: The user identifier.
        memory_data: The memory data to save.

    Returns:
        True if successful, False otherwise.
    """
    from src.db.engine import get_db_session
    from src.db.models import UserMemoryModel

    try:
        memory_data["lastUpdated"] = datetime.now(UTC).isoformat()

        with get_db_session() as session:
            record = session.query(UserMemoryModel).filter(UserMemoryModel.user_id == user_id).first()
            if record:
                record.memory_json = memory_data
            else:
                record = UserMemoryModel(
                    user_id=user_id,
                    memory_json=memory_data,
                )
                session.add(record)

        # Update cache
        _memory_data[user_id] = memory_data
        logger.info(f"Memory saved for user {user_id} to database")
        return True
    except Exception as e:
        logger.error(f"Failed to save memory to database for user {user_id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Public API (delegates to DB or file based on configuration)
# ---------------------------------------------------------------------------
def get_memory_data(user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
    """Get the current memory data for a user (cached).

    Args:
        user_id: The user identifier.

    Returns:
        The memory data dictionary.
    """
    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_get_memory_data(user_id)
    return _file_get_memory_data(user_id)


def reload_memory_data(user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
    """Reload memory data from storage, forcing cache invalidation.

    Args:
        user_id: The user identifier.

    Returns:
        The reloaded memory data dictionary.
    """
    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_reload_memory_data(user_id)
    return _file_reload_memory_data(user_id)


def _save_memory(user_id: str, memory_data: dict[str, Any]) -> bool:
    """Save memory data to the appropriate backend.

    Args:
        user_id: The user identifier.
        memory_data: The memory data to save.

    Returns:
        True if successful, False otherwise.
    """
    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_save_memory(user_id, memory_data)
    return _save_memory_to_file(user_id, memory_data)


class MemoryUpdater:
    """Updates memory using LLM based on conversation context."""

    def __init__(self, model_name: str | None = None):
        """Initialize the memory updater.

        Args:
            model_name: Optional model name to use. If None, uses config or default.
        """
        self._model_name = model_name

    def _get_model(self):
        """Get the model for memory updates."""
        config = get_memory_config()
        model_name = self._model_name or config.model_name
        return create_chat_model(name=model_name, thinking_enabled=False)

    def update_memory(
        self,
        messages: list[Any],
        thread_id: str | None = None,
        user_id: str = DEFAULT_USER_ID,
    ) -> bool:
        """Update memory based on conversation messages.

        Args:
            messages: List of conversation messages.
            thread_id: Optional thread ID for tracking source.
            user_id: The user whose memory to update.

        Returns:
            True if update was successful, False otherwise.
        """
        config = get_memory_config()
        if not config.enabled:
            return False

        if not messages:
            return False

        try:
            # Get current memory for this user
            current_memory = get_memory_data(user_id)

            # Format conversation for prompt
            conversation_text = format_conversation_for_update(messages)

            if not conversation_text.strip():
                return False

            # Build prompt
            prompt = MEMORY_UPDATE_PROMPT.format(
                current_memory=json.dumps(current_memory, indent=2),
                conversation=conversation_text,
            )

            # Call LLM
            model = self._get_model()
            response = model.invoke(prompt)
            response_text = str(response.content).strip()

            # Parse response
            # Remove markdown code blocks if present
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

            update_data = json.loads(response_text)

            # Apply updates
            updated_memory = self._apply_updates(current_memory, update_data, thread_id)

            # Strip file-upload mentions from all summaries before saving.
            # Uploaded files are session-scoped and won't exist in future sessions,
            # so recording upload events in long-term memory causes the agent to
            # try (and fail) to locate those files in subsequent conversations.
            updated_memory = _strip_upload_mentions_from_memory(updated_memory)

            # Save for this user (uses DB or file automatically)
            success = _save_memory(user_id, updated_memory)

            try:
                from src.gateway.metrics import memory_updates_total

                memory_updates_total.labels(status="success" if success else "failure").inc()
            except Exception:
                pass

            return success

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response for memory update: {e}")
            try:
                from src.gateway.metrics import memory_updates_total

                memory_updates_total.labels(status="failure").inc()
            except Exception:
                pass
            return False
        except Exception as e:
            logger.error(f"Memory update failed for user {user_id}: {e}")
            try:
                from src.gateway.metrics import memory_updates_total

                memory_updates_total.labels(status="failure").inc()
            except Exception:
                pass
            return False

    def _apply_updates(
        self,
        current_memory: dict[str, Any],
        update_data: dict[str, Any],
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Apply LLM-generated updates to memory.

        Args:
            current_memory: Current memory data.
            update_data: Updates from LLM.
            thread_id: Optional thread ID for tracking.

        Returns:
            Updated memory data.
        """
        config = get_memory_config()
        now = datetime.now(UTC).isoformat()

        # Update user sections
        user_updates = update_data.get("user", {})
        for section in ["workContext", "personalContext", "topOfMind"]:
            section_data = user_updates.get(section, {})
            if section_data.get("shouldUpdate") and section_data.get("summary"):
                current_memory["user"][section] = {
                    "summary": section_data["summary"],
                    "updatedAt": now,
                }

        # Update history sections
        history_updates = update_data.get("history", {})
        for section in ["recentMonths", "earlierContext", "longTermBackground"]:
            section_data = history_updates.get(section, {})
            if section_data.get("shouldUpdate") and section_data.get("summary"):
                current_memory["history"][section] = {
                    "summary": section_data["summary"],
                    "updatedAt": now,
                }

        # Remove facts
        facts_to_remove = set(update_data.get("factsToRemove", []))
        if facts_to_remove:
            current_memory["facts"] = [f for f in current_memory.get("facts", []) if f.get("id") not in facts_to_remove]

        # Add new facts
        new_facts = update_data.get("newFacts", [])
        for fact in new_facts:
            confidence = fact.get("confidence", 0.5)
            if confidence >= config.fact_confidence_threshold:
                fact_entry = {
                    "id": f"fact_{uuid.uuid4().hex[:8]}",
                    "content": fact.get("content", ""),
                    "category": fact.get("category", "context"),
                    "confidence": confidence,
                    "createdAt": now,
                    "source": thread_id or "unknown",
                }
                current_memory["facts"].append(fact_entry)

        # Enforce max facts limit
        if len(current_memory["facts"]) > config.max_facts:
            # Sort by confidence and keep top ones
            current_memory["facts"] = sorted(
                current_memory["facts"],
                key=lambda f: f.get("confidence", 0),
                reverse=True,
            )[: config.max_facts]

        return current_memory


def update_memory_from_conversation(
    messages: list[Any],
    thread_id: str | None = None,
    user_id: str = DEFAULT_USER_ID,
) -> bool:
    """Convenience function to update memory from a conversation.

    Args:
        messages: List of conversation messages.
        thread_id: Optional thread ID.
        user_id: The user whose memory to update.

    Returns:
        True if successful, False otherwise.
    """
    updater = MemoryUpdater()
    return updater.update_memory(messages, thread_id, user_id)
