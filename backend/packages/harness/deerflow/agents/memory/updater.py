"""内存 updater for reading, writing, and updating 内存 数据."""

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from deerflow.agents.memory.prompt import (
    MEMORY_UPDATE_PROMPT,
    format_conversation_for_update,
)
from deerflow.config.memory_config import get_memory_config
from deerflow.config.paths import get_paths
from deerflow.models import create_chat_model


def _get_memory_file_path(agent_name: str | None = None) -> Path:
    """Get the 路径 to the 内存 文件.

    Args:
        agent_name: If provided, returns the per-代理 内存 文件 路径.
                    If None, returns the global 内存 文件 路径.

    Returns:
        Path to the 内存 文件.
    """
    if agent_name is not None:
        return get_paths().agent_memory_file(agent_name)

    config = get_memory_config()
    if config.storage_path:
        p = Path(config.storage_path)
        #    Absolute 路径: use as-is; relative 路径: resolve against base_dir


        return p if p.is_absolute() else get_paths().base_dir / p
    return get_paths().memory_file


def _create_empty_memory() -> dict[str, Any]:
    """Create an empty 内存 structure."""
    return {
        "version": "1.0",
        "lastUpdated": datetime.utcnow().isoformat() + "Z",
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


#    Per-代理 内存 缓存: keyed by agent_name (None = global)


#    Value: (memory_data, file_mtime)


_memory_cache: dict[str | None, tuple[dict[str, Any], float | None]] = {}


def get_memory_data(agent_name: str | None = None) -> dict[str, Any]:
    """Get the 当前 内存 数据 (cached with 文件 modification time 检查).

    The 缓存 is automatically invalidated if the 内存 文件 has been modified
    since the 最后 load, ensuring fresh 数据 is always returned.

    Args:
        agent_name: If provided, loads per-代理 内存. If None, loads global 内存.

    Returns:
        The 内存 数据 dictionary.
    """
    file_path = _get_memory_file_path(agent_name)

    #    Get 当前 文件 modification time


    try:
        current_mtime = file_path.stat().st_mtime if file_path.exists() else None
    except OSError:
        current_mtime = None

    cached = _memory_cache.get(agent_name)

    #    Invalidate 缓存 如果 文件 has been modified or doesn't exist


    if cached is None or cached[1] != current_mtime:
        memory_data = _load_memory_from_file(agent_name)
        _memory_cache[agent_name] = (memory_data, current_mtime)
        return memory_data

    return cached[0]


def reload_memory_data(agent_name: str | None = None) -> dict[str, Any]:
    """Reload 内存 数据 from 文件, forcing 缓存 invalidation.

    Args:
        agent_name: If provided, reloads per-代理 内存. If None, reloads global 内存.

    Returns:
        The reloaded 内存 数据 dictionary.
    """
    file_path = _get_memory_file_path(agent_name)
    memory_data = _load_memory_from_file(agent_name)

    try:
        mtime = file_path.stat().st_mtime if file_path.exists() else None
    except OSError:
        mtime = None

    _memory_cache[agent_name] = (memory_data, mtime)
    return memory_data


def _load_memory_from_file(agent_name: str | None = None) -> dict[str, Any]:
    """Load 内存 数据 from 文件.

    Args:
        agent_name: If provided, loads per-代理 内存 文件. If None, loads global.

    Returns:
        The 内存 数据 dictionary.
    """
    file_path = _get_memory_file_path(agent_name)

    if not file_path.exists():
        return _create_empty_memory()

    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, OSError) as e:
        print(f"Failed to load memory file: {e}")
        return _create_empty_memory()


#    Matches sentences that describe a 文件-upload *event* rather than general


#    文件-related work.  Deliberately narrow to avoid removing legitimate facts


#    such as "用户 works with CSV files" or "prefers PDF export".


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
    """Remove sentences about 文件 uploads from all 内存 summaries and facts.

    Uploaded files are 会话-scoped; persisting upload events in long-term
    内存 causes the 代理 to search for non-existent files in future sessions.
    """
    #    Scrub summaries in 用户/history sections


    for section in ("user", "history"):
        section_data = memory_data.get(section, {})
        for _key, val in section_data.items():
            if isinstance(val, dict) and "summary" in val:
                cleaned = _UPLOAD_SENTENCE_RE.sub("", val["summary"]).strip()
                cleaned = re.sub(r"  +", " ", cleaned)
                val["summary"] = cleaned

    #    Also remove any facts that describe upload events


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


def _save_memory_to_file(memory_data: dict[str, Any], agent_name: str | None = None) -> bool:
    """Save 内存 数据 to 文件 and 更新 缓存.

    Args:
        memory_data: The 内存 数据 to save.
        agent_name: If provided, saves to per-代理 内存 文件. If None, saves to global.

    Returns:
        True if successful, False otherwise.
    """
    file_path = _get_memory_file_path(agent_name)

    try:
        #    Ensure 目录 exists


        file_path.parent.mkdir(parents=True, exist_ok=True)

        #    Update lastUpdated timestamp


        memory_data["lastUpdated"] = datetime.utcnow().isoformat() + "Z"

        #    Write atomically using temp 文件


        temp_path = file_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(memory_data, f, indent=2, ensure_ascii=False)

        #    Rename temp 文件 to actual 文件 (atomic on most systems)


        temp_path.replace(file_path)

        #    Update 缓存 and 文件 modification time


        try:
            mtime = file_path.stat().st_mtime
        except OSError:
            mtime = None

        _memory_cache[agent_name] = (memory_data, mtime)

        print(f"Memory saved to {file_path}")
        return True
    except OSError as e:
        print(f"Failed to save memory file: {e}")
        return False


class MemoryUpdater:
    """Updates 内存 using LLM based on conversation context."""

    def __init__(self, model_name: str | None = None):
        """Initialize the 内存 updater.

        Args:
            model_name: Optional 模型 名称 to use. If None, uses 配置 or 默认.
        """
        self._model_name = model_name

    def _get_model(self):
        """Get the 模型 for 内存 updates."""
        config = get_memory_config()
        model_name = self._model_name or config.model_name
        return create_chat_model(name=model_name, thinking_enabled=False)

    def update_memory(self, messages: list[Any], thread_id: str | None = None, agent_name: str | None = None) -> bool:
        """Update 内存 based on conversation messages.

        Args:
            messages: List of conversation messages.
            thread_id: Optional 线程 ID for tracking source.
            agent_name: If provided, updates per-代理 内存. If None, updates global 内存.

        Returns:
            True if 更新 was successful, False otherwise.
        """
        config = get_memory_config()
        if not config.enabled:
            return False

        if not messages:
            return False

        try:
            #    Get 当前 内存


            current_memory = get_memory_data(agent_name)

            #    Format conversation 对于 提示词


            conversation_text = format_conversation_for_update(messages)

            if not conversation_text.strip():
                return False

            #    Build 提示词


            prompt = MEMORY_UPDATE_PROMPT.format(
                current_memory=json.dumps(current_memory, indent=2),
                conversation=conversation_text,
            )

            #    Call LLM


            model = self._get_model()
            response = model.invoke(prompt)
            response_text = str(response.content).strip()

            #    Parse 响应


            #    Remove markdown code blocks 如果 present


            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

            update_data = json.loads(response_text)

            #    Apply updates


            updated_memory = self._apply_updates(current_memory, update_data, thread_id)

            #    Strip 文件-upload mentions from all summaries before saving.


            #    Uploaded files are 会话-scoped and won't exist in future sessions,


            #    so recording upload events in long-term 内存 causes the 代理 to


            #    try (and fail) to locate those files in subsequent conversations.


            updated_memory = _strip_upload_mentions_from_memory(updated_memory)

            #    Save


            return _save_memory_to_file(updated_memory, agent_name)

        except json.JSONDecodeError as e:
            print(f"Failed to parse LLM response for memory update: {e}")
            return False
        except Exception as e:
            print(f"Memory update failed: {e}")
            return False

    def _apply_updates(
        self,
        current_memory: dict[str, Any],
        update_data: dict[str, Any],
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Apply LLM-generated updates to 内存.

        Args:
            current_memory: Current 内存 数据.
            update_data: Updates from LLM.
            thread_id: Optional 线程 ID for tracking.

        Returns:
            Updated 内存 数据.
        """
        config = get_memory_config()
        now = datetime.utcnow().isoformat() + "Z"

        #    Update 用户 sections


        user_updates = update_data.get("user", {})
        for section in ["workContext", "personalContext", "topOfMind"]:
            section_data = user_updates.get(section, {})
            if section_data.get("shouldUpdate") and section_data.get("summary"):
                current_memory["user"][section] = {
                    "summary": section_data["summary"],
                    "updatedAt": now,
                }

        #    Update history sections


        history_updates = update_data.get("history", {})
        for section in ["recentMonths", "earlierContext", "longTermBackground"]:
            section_data = history_updates.get(section, {})
            if section_data.get("shouldUpdate") and section_data.get("summary"):
                current_memory["history"][section] = {
                    "summary": section_data["summary"],
                    "updatedAt": now,
                }

        #    Remove facts


        facts_to_remove = set(update_data.get("factsToRemove", []))
        if facts_to_remove:
            current_memory["facts"] = [f for f in current_memory.get("facts", []) if f.get("id") not in facts_to_remove]

        #    Add 新建 facts


        existing_fact_keys = {
            fact_key
            for fact_key in (
                _fact_content_key(fact.get("content"))
                for fact in current_memory.get("facts", [])
            )
            if fact_key is not None
        }
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

        #    Enforce max facts limit


        if len(current_memory["facts"]) > config.max_facts:
            #    Sort by confidence and keep 顶部 ones


            current_memory["facts"] = sorted(
                current_memory["facts"],
                key=lambda f: f.get("confidence", 0),
                reverse=True,
            )[: config.max_facts]

        return current_memory


def update_memory_from_conversation(messages: list[Any], thread_id: str | None = None, agent_name: str | None = None) -> bool:
    """Convenience 函数 to 更新 内存 from a conversation.

    Args:
        messages: List of conversation messages.
        thread_id: Optional 线程 ID.
        agent_name: If provided, updates per-代理 内存. If None, updates global 内存.

    Returns:
        True if successful, False otherwise.
    """
    updater = MemoryUpdater()
    return updater.update_memory(messages, thread_id, agent_name)
