"""Thread message persistence for saving and loading conversation history."""

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage, BaseMessage

from src.config.paths import get_paths

logger = logging.getLogger(__name__)


def _serialize_message(msg: Any) -> dict[str, Any]:
    """Serialize a LangChain message to a JSON-serializable dict.

    Args:
        msg: A LangChain message object.

    Returns:
        A dict representation of the message.
    """
    msg_type = getattr(msg, "type", "unknown")
    content = getattr(msg, "content", "")
    msg_id = getattr(msg, "id", None)

    result: dict[str, Any] = {
        "type": msg_type,
        "content": content,
    }

    if msg_id:
        result["id"] = msg_id

    # Handle additional fields for AI messages
    if msg_type == "ai":
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            # Serialize tool calls
            serialized_calls = []
            for tc in tool_calls:
                call_dict = {
                    "name": tc.get("name"),
                    "args": tc.get("args", {}),
                    "id": tc.get("id"),
                }
                serialized_calls.append(call_dict)
            result["tool_calls"] = serialized_calls

    # Handle tool messages
    if msg_type == "tool":
        tool_call_id = getattr(msg, "tool_call_id", None)
        if tool_call_id:
            result["tool_call_id"] = tool_call_id
        name = getattr(msg, "name", None)
        if name:
            result["name"] = name

    return result


def _deserialize_message(data: dict[str, Any]) -> BaseMessage:
    """Deserialize a dict back to a LangChain message.

    Args:
        data: A dict representation of a message.

    Returns:
        A LangChain message object.
    """
    msg_type = data.get("type", "unknown")
    content = data.get("content", "")
    msg_id = data.get("id")

    if msg_type == "human":
        msg = HumanMessage(content=content, id=msg_id)
    elif msg_type == "ai":
        tool_calls = data.get("tool_calls")
        msg = AIMessage(content=content, id=msg_id, tool_calls=tool_calls or [])
    elif msg_type == "system":
        msg = SystemMessage(content=content, id=msg_id)
    elif msg_type == "tool":
        msg = ToolMessage(
            content=content,
            tool_call_id=data.get("tool_call_id", ""),
            name=data.get("name"),
            id=msg_id,
        )
    else:
        # Fallback to a simple dict-like object
        msg = {"type": msg_type, "content": content, "id": msg_id}

    return msg


def save_messages(thread_id: str, messages: list[Any]) -> bool:
    """Save thread messages to disk atomically.

    Args:
        thread_id: The thread ID.
        messages: List of LangChain message objects.

    Returns:
        True if successful, False otherwise.
    """
    if not thread_id:
        logger.warning("Cannot save messages: thread_id is empty")
        return False

    paths = get_paths()
    file_path = paths.messages_file(thread_id)

    try:
        # Ensure thread directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Serialize messages
        serialized = [_serialize_message(msg) for msg in messages]
        data = {"messages": serialized}

        # Write atomically using temp file
        temp_path = file_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Rename temp file to actual file (atomic on most systems)
        temp_path.replace(file_path)

        logger.debug(f"Saved {len(messages)} messages to {file_path}")
        return True

    except OSError as e:
        logger.error(f"Failed to save messages for thread {thread_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error saving messages for thread {thread_id}: {e}")
        return False


def load_messages(thread_id: str) -> list[BaseMessage]:
    """Load thread messages from disk.

    Args:
        thread_id: The thread ID.

    Returns:
        List of LangChain message objects, or empty list if file doesn't exist.
    """
    if not thread_id:
        logger.warning("Cannot load messages: thread_id is empty")
        return []

    paths = get_paths()
    file_path = paths.messages_file(thread_id)

    if not file_path.exists():
        logger.debug(f"No messages file found for thread {thread_id}")
        return []

    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)

        serialized = data.get("messages", [])
        messages = [_deserialize_message(msg_data) for msg_data in serialized]

        logger.debug(f"Loaded {len(messages)} messages from {file_path}")
        return messages

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse messages file for thread {thread_id}: {e}")
        return []
    except OSError as e:
        logger.error(f"Failed to load messages for thread {thread_id}: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error loading messages for thread {thread_id}: {e}")
        return []


def delete_messages(thread_id: str) -> bool:
    """Delete the messages file for a thread.

    Args:
        thread_id: The thread ID.

    Returns:
        True if file was deleted or didn't exist, False on error.
    """
    if not thread_id:
        return False

    paths = get_paths()
    file_path = paths.messages_file(thread_id)

    if not file_path.exists():
        return True

    try:
        file_path.unlink()
        logger.debug(f"Deleted messages file for thread {thread_id}")
        return True
    except OSError as e:
        logger.error(f"Failed to delete messages for thread {thread_id}: {e}")
        return False


def get_messages_export(thread_id: str) -> dict[str, Any] | None:
    """Export thread messages for API responses.

    Args:
        thread_id: The thread ID.

    Returns:
        Dict with messages list, or None if no messages exist.
    """
    if not thread_id:
        return None

    paths = get_paths()
    file_path = paths.messages_file(thread_id)

    if not file_path.exists():
        return None

    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to export messages for thread {thread_id}: {e}")
        return None
