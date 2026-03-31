"""Memory updater for reading, writing, and updating memory data."""

import json
import logging
import math
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deerflow.agents.memory.prompt import (
    MEMORY_UPDATE_PROMPT,
    format_conversation_for_update,
)
from deerflow.agents.memory.storage import create_empty_memory, get_memory_storage
from deerflow.config.memory_config import get_memory_config
from deerflow.models import create_chat_model

if TYPE_CHECKING:
    from deerflow.identity.agent_identity import AgentIdentity

logger = logging.getLogger(__name__)


def _memory_cache_key(agent_name: str | None, identity: "AgentIdentity | None") -> tuple:
    """Build the cache key for memory data.

    When identity is present and non-global, it is the authoritative key.
    Otherwise fall back to agent_name so existing callers are unaffected.
    """
    if identity is not None and not identity.is_global:
        return ("identity", str(identity))
    return ("agent", agent_name)


def _get_memory_file_path(agent_name: str | None = None, identity: "AgentIdentity | None" = None) -> Path:
    """Get the path to the memory file.

    Priority:
      1. identity (non-global) → identity_memory_file(identity)
      2. agent_name            → agent_memory_file(agent_name)
      3. config.storage_path or global memory_file

    Args:
        agent_name: Per-agent memory path (legacy).
        identity: Full three-tier identity; when non-global takes precedence.

    Returns:
        Path to the memory file.
    """
    # Identity-scoped path takes priority
    if identity is not None and not identity.is_global:
        return get_paths().identity_memory_file(identity)

    # Original logic (unchanged)
    if agent_name is not None:
        return get_paths().agent_memory_file(agent_name)

    config = get_memory_config()
    if config.storage_path:
        p = Path(config.storage_path)
        # Absolute path: use as-is; relative path: resolve against base_dir
        return p if p.is_absolute() else get_paths().base_dir / p
    return get_paths().memory_file


def _create_empty_memory() -> dict[str, Any]:
    """Backward-compatible wrapper around the storage-layer empty-memory factory."""
    return create_empty_memory()


def _save_memory_to_file(memory_data: dict[str, Any], agent_name: str | None = None) -> bool:
    """Backward-compatible wrapper around the configured memory storage save path."""
    return get_memory_storage().save(memory_data, agent_name)


# Per-agent memory cache: keyed by (scope, key) tuple → (memory_data, file_mtime)
_memory_cache: dict[tuple, tuple[dict[str, Any], float | None]] = {}


def get_memory_data(agent_name: str | None = None, identity: "AgentIdentity | None" = None) -> dict[str, Any]:
    """Get the current memory data (cached with file modification time check).

    The cache is automatically invalidated if the memory file has been modified
    since the last load, ensuring fresh data is always returned.

    Args:
        agent_name: Per-agent memory scope (legacy).
        identity: Full three-tier identity; when non-global takes precedence over agent_name.

    Returns:
        The memory data dictionary.
    """
    file_path = _get_memory_file_path(agent_name, identity)
    cache_key = _memory_cache_key(agent_name, identity)

    # Get current file modification time
    try:
        current_mtime = file_path.stat().st_mtime if file_path.exists() else None
    except OSError:
        current_mtime = None

    cached = _memory_cache.get(cache_key)

    # Invalidate cache if file has been modified or doesn't exist
    if cached is None or cached[1] != current_mtime:
        memory_data = _load_memory_from_file(agent_name, identity)
        _memory_cache[cache_key] = (memory_data, current_mtime)
        return memory_data

    return cached[0]


def reload_memory_data(agent_name: str | None = None, identity: "AgentIdentity | None" = None) -> dict[str, Any]:
    """Reload memory data from file, forcing cache invalidation.

    Args:
        agent_name: Per-agent memory scope (legacy).
        identity: Full three-tier identity; when non-global takes precedence.

    Returns:
        The saved memory data after storage normalization.

    Raises:
        OSError: If persisting the imported memory fails.
    """
    file_path = _get_memory_file_path(agent_name, identity)
    cache_key = _memory_cache_key(agent_name, identity)
    memory_data = _load_memory_from_file(agent_name, identity)
    try:
        mtime = file_path.stat().st_mtime if file_path.exists() else None
    except OSError:
        mtime = None
    _memory_cache[cache_key] = (memory_data, mtime)
    return memory_data


def import_memory_data(memory_data: dict[str, Any], agent_name: str | None = None) -> dict[str, Any]:
    """Persist imported memory data via storage provider.

    Args:
        memory_data: Full memory payload to persist.
        agent_name: If provided, imports into per-agent memory.

    Returns:
        The saved memory data after storage normalization.

    Raises:
        OSError: If persisting the imported memory fails.
    """
    storage = get_memory_storage()
    if not storage.save(memory_data, agent_name):
        raise OSError("Failed to save imported memory data")
    return storage.load(agent_name)


def clear_memory_data(agent_name: str | None = None) -> dict[str, Any]:
    """Clear all stored memory data and persist an empty structure."""
    cleared_memory = create_empty_memory()
    if not _save_memory_to_file(cleared_memory, agent_name):
        raise OSError("Failed to save cleared memory data")
    return cleared_memory


def _validate_confidence(confidence: float) -> float:
    """Validate persisted fact confidence so stored JSON stays standards-compliant."""
    if not math.isfinite(confidence) or confidence < 0 or confidence > 1:
        raise ValueError("confidence")
    return confidence


def create_memory_fact(
    content: str,
    category: str = "context",
    confidence: float = 0.5,
    agent_name: str | None = None,
) -> dict[str, Any]:
    """Create a new fact and persist the updated memory data."""
    normalized_content = content.strip()
    if not normalized_content:
        raise ValueError("content")

    normalized_category = category.strip() or "context"
    validated_confidence = _validate_confidence(confidence)
    now = datetime.utcnow().isoformat() + "Z"
    memory_data = get_memory_data(agent_name)
    updated_memory = dict(memory_data)
    facts = list(memory_data.get("facts", []))
    facts.append(
        {
            "id": f"fact_{uuid.uuid4().hex[:8]}",
            "content": normalized_content,
            "category": normalized_category,
            "confidence": validated_confidence,
            "createdAt": now,
            "source": "manual",
        }
    )
    updated_memory["facts"] = facts

    if not _save_memory_to_file(updated_memory, agent_name):
        raise OSError("Failed to save memory data after creating fact")

    return updated_memory


def delete_memory_fact(fact_id: str, agent_name: str | None = None) -> dict[str, Any]:
    """Delete a fact by its id and persist the updated memory data."""
    memory_data = get_memory_data(agent_name)
    facts = memory_data.get("facts", [])
    updated_facts = [fact for fact in facts if fact.get("id") != fact_id]
    if len(updated_facts) == len(facts):
        raise KeyError(fact_id)

    updated_memory = dict(memory_data)
    updated_memory["facts"] = updated_facts

    if not _save_memory_to_file(updated_memory, agent_name):
        raise OSError(f"Failed to save memory data after deleting fact '{fact_id}'")

    return updated_memory


def update_memory_fact(
    fact_id: str,
    content: str | None = None,
    category: str | None = None,
    confidence: float | None = None,
    agent_name: str | None = None,
) -> dict[str, Any]:
    """Update an existing fact and persist the updated memory data."""
    memory_data = get_memory_data(agent_name)
    updated_memory = dict(memory_data)
    updated_facts: list[dict[str, Any]] = []
    found = False

    for fact in memory_data.get("facts", []):
        if fact.get("id") == fact_id:
            found = True
            updated_fact = dict(fact)
            if content is not None:
                normalized_content = content.strip()
                if not normalized_content:
                    raise ValueError("content")
                updated_fact["content"] = normalized_content
            if category is not None:
                updated_fact["category"] = category.strip() or "context"
            if confidence is not None:
                updated_fact["confidence"] = _validate_confidence(confidence)
            updated_facts.append(updated_fact)
        else:
            updated_facts.append(fact)

    if not found:
        raise KeyError(fact_id)

    updated_memory["facts"] = updated_facts

    if not _save_memory_to_file(updated_memory, agent_name):
        raise OSError(f"Failed to save memory data after updating fact '{fact_id}'")

    return updated_memory


def _extract_text(content: Any) -> str:
    """Extract plain text from LLM response content (str or list of content blocks).

    Modern LLMs may return structured content as a list of blocks instead of a
    plain string, e.g. [{"type": "text", "text": "..."}]. Using str() on such
    content produces Python repr instead of the actual text, breaking JSON
    parsing downstream.

    String chunks are concatenated without separators to avoid corrupting
    chunked JSON/text payloads. Dict-based text blocks are treated as full text
    blocks and joined with newlines for readability.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        pending_str_parts: list[str] = []

        def flush_pending_str_parts() -> None:
            if pending_str_parts:
                pieces.append("".join(pending_str_parts))
                pending_str_parts.clear()

        for block in content:
            if isinstance(block, str):
                pending_str_parts.append(block)
            elif isinstance(block, dict):
                flush_pending_str_parts()
                text_val = block.get("text")
                if isinstance(text_val, str):
                    pieces.append(text_val)

        flush_pending_str_parts()
        return "\n".join(pieces)
    return str(content)


def _load_memory_from_file(agent_name: str | None = None, identity: "AgentIdentity | None" = None) -> dict[str, Any]:
    """Load memory data from file.

    Args:
        agent_name: Per-agent memory scope (legacy).
        identity: Full three-tier identity; when non-global takes precedence.

    Returns:
        The memory data dictionary.
    """
    file_path = _get_memory_file_path(agent_name, identity)

    if not file_path.exists():
        return _create_empty_memory()

    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load memory file: %s", e)
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
        memory_data["facts"] = [f for f in facts if not _UPLOAD_SENTENCE_RE.search(f.get("content", ""))]

    return memory_data


def _fact_content_key(content: Any) -> str | None:
    if not isinstance(content, str):
        return None
    stripped = content.strip()
    if not stripped:
        return None
    return stripped


def _save_memory_to_file_identity(memory_data: dict[str, Any], agent_name: str | None = None, identity: "AgentIdentity | None" = None) -> bool:
    """Save memory data to file and update cache.

    Args:
        memory_data: The memory data to save.
        agent_name: If provided, saves to per-agent memory file. If None, saves to global.
        identity: Full three-tier identity; when non-global takes precedence over agent_name.

    Returns:
        True if successful, False otherwise.
    """
    file_path = _get_memory_file_path(agent_name, identity)
    cache_key = _memory_cache_key(agent_name, identity)

    try:
        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Update lastUpdated timestamp
        memory_data["lastUpdated"] = datetime.utcnow().isoformat() + "Z"

        # Write atomically using temp file
        temp_path = file_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(memory_data, f, indent=2, ensure_ascii=False)

        # Rename temp file to actual file (atomic on most systems)
        temp_path.replace(file_path)

        # Update cache and file modification time
        try:
            mtime = file_path.stat().st_mtime
        except OSError:
            mtime = None

        _memory_cache[cache_key] = (memory_data, mtime)

        logger.info("Memory saved to %s", file_path)
        return True
    except OSError as e:
        logger.error("Failed to save memory file: %s", e)
        return False


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

    def update_memory(self, messages: list[Any], thread_id: str | None = None, agent_name: str | None = None, user_id: str | None = None, identity: "AgentIdentity | None" = None) -> bool:
        """Update memory based on conversation messages.

        Args:
            messages: List of conversation messages.
            thread_id: Optional thread ID for tracking source.
            agent_name: If provided, updates per-agent memory. If None, updates global memory.
            user_id: Ignored (legacy parameter, superseded by identity).
            identity: Full three-tier identity; when non-global takes precedence over agent_name.

        Returns:
            True if update was successful, False otherwise.
        """
        config = get_memory_config()
        if not config.enabled:
            return False

        if not messages:
            return False

        try:
            # Get current memory (identity-scoped when available)
            current_memory = get_memory_data(agent_name, identity)

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
            response_text = _extract_text(response.content).strip()

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

            # Save (identity-scoped when available)
            return _save_memory_to_file_identity(updated_memory, agent_name, identity)

        except json.JSONDecodeError as e:
            logger.warning("Failed to parse LLM response for memory update: %s", e)
            return False
        except Exception as e:
            logger.exception("Memory update failed: %s", e)
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
        now = datetime.utcnow().isoformat() + "Z"

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
        existing_fact_keys = {fact_key for fact_key in (_fact_content_key(fact.get("content")) for fact in current_memory.get("facts", [])) if fact_key is not None}
        new_facts = update_data.get("newFacts", [])
        for fact in new_facts:
            confidence = fact.get("confidence", 0.5)
            if confidence >= config.fact_confidence_threshold:
                raw_content = fact.get("content", "")
                normalized_content = raw_content.strip()
                fact_key = _fact_content_key(normalized_content)
                if fact_key is not None and fact_key in existing_fact_keys:
                    continue

                fact_entry = {
                    "id": f"fact_{uuid.uuid4().hex[:8]}",
                    "content": normalized_content,
                    "category": fact.get("category", "context"),
                    "confidence": confidence,
                    "createdAt": now,
                    "source": thread_id or "unknown",
                }
                current_memory["facts"].append(fact_entry)
                if fact_key is not None:
                    existing_fact_keys.add(fact_key)

        # Enforce max facts limit
        if len(current_memory["facts"]) > config.max_facts:
            # Sort by confidence and keep top ones
            current_memory["facts"] = sorted(
                current_memory["facts"],
                key=lambda f: f.get("confidence", 0),
                reverse=True,
            )[: config.max_facts]

        return current_memory


def update_memory_from_conversation(messages: list[Any], thread_id: str | None = None, agent_name: str | None = None, identity: "AgentIdentity | None" = None) -> bool:
    """Convenience function to update memory from a conversation.

    Args:
        messages: List of conversation messages.
        thread_id: Optional thread ID.
        agent_name: If provided, updates per-agent memory. If None, updates global memory.
        identity: Full three-tier identity; when non-global takes precedence over agent_name.

    Returns:
        True if successful, False otherwise.
    """
    updater = MemoryUpdater()
    return updater.update_memory(messages, thread_id, agent_name, identity=identity)
