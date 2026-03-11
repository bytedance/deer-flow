"""Memory updater for reading, writing, and updating memory data."""

import json
import re
import uuid
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from src.agents.memory.constants import is_postgres_backend
from src.agents.memory.prompt import MEMORY_UPDATE_PROMPT, format_conversation_for_update
from src.config.memory_config import get_memory_config
from src.config.paths import get_paths
from src.models import create_chat_model


def _scope_values(workspace_type: str | None = None, workspace_id: str | None = None) -> tuple[str, str]:
    """Resolve effective memory scope values.

    When strict_scope is disabled, missing scope falls back to global/global.
    """
    config = get_memory_config()
    wt = workspace_type or ""
    wid = workspace_id or ""

    if config.strict_scope and (not wt or not wid):
        raise ValueError("workspace_type and workspace_id are required when memory.strict_scope=true")

    return (wt or "global", wid or "global")


def _create_empty_memory() -> dict[str, Any]:
    return {
        "version": "1.0",
        "lastUpdated": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
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


# File-backend cache key: (scope_type, scope_id, agent_name) -> (memory_data, file_mtime)
_memory_cache: dict[tuple[str, str, str | None], tuple[dict[str, Any], float | None]] = {}


def _get_memory_file_path(agent_name: str | None = None, workspace_type: str | None = None, workspace_id: str | None = None) -> Path:
    scope_type, scope_id = _scope_values(workspace_type, workspace_id)

    # For explicit non-global scope, use scoped path tree.
    if scope_type != "global" or scope_id != "global":
        scope_dir = get_paths().base_dir / "memory" / scope_type / scope_id
        if agent_name is None:
            return scope_dir / "memory.json"
        return scope_dir / "agents" / f"{agent_name.lower()}.json"

    # Global scope behavior remains compatible with original file backend.
    if agent_name is not None:
        return get_paths().agent_memory_file(agent_name)

    config = get_memory_config()
    if config.storage_path:
        p = Path(config.storage_path)
        return p if p.is_absolute() else get_paths().base_dir / p

    return get_paths().memory_file


def _load_memory_from_file(agent_name: str | None = None, workspace_type: str | None = None, workspace_id: str | None = None) -> dict[str, Any]:
    file_path = _get_memory_file_path(agent_name, workspace_type, workspace_id)
    if not file_path.exists():
        return _create_empty_memory()

    try:
        with open(file_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Failed to load memory file: {e}")
        return _create_empty_memory()


def _save_memory_to_file(memory_data: dict[str, Any], agent_name: str | None = None, workspace_type: str | None = None, workspace_id: str | None = None) -> bool:
    file_path = _get_memory_file_path(agent_name, workspace_type, workspace_id)
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        memory_data["lastUpdated"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        temp_path = file_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(memory_data, f, indent=2, ensure_ascii=False)

        temp_path.replace(file_path)

        try:
            mtime = file_path.stat().st_mtime
        except OSError:
            mtime = None

        scope_type, scope_id = _scope_values(workspace_type, workspace_id)
        _memory_cache[(scope_type, scope_id, agent_name)] = (memory_data, mtime)
        return True
    except OSError as e:
        print(f"Failed to save memory file: {e}")
        return False


def _pg_connect(database_url: str):
    try:
        psycopg = import_module("psycopg")
    except ImportError as e:
        raise RuntimeError("psycopg is required for memory.backend=postgres") from e
    return psycopg.connect(database_url)


def _load_memory_from_postgres(workspace_type: str, workspace_id: str) -> dict[str, Any]:
    config = get_memory_config()
    if not config.database_url:
        raise ValueError("memory.database_url is required when memory.backend=postgres")

    try:
        with _pg_connect(config.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT profile_json
                FROM memory_profiles
                WHERE workspace_type = %s AND workspace_id = %s
                """,
                (workspace_type, workspace_id),
            )
            row = cur.fetchone()
            return dict(row[0]) if row else _create_empty_memory()
    except Exception as e:
        print(f"Failed to load memory from postgres: {e}")
        return _create_empty_memory()


def _save_memory_to_postgres(memory_data: dict[str, Any], workspace_type: str, workspace_id: str) -> bool:
    config = get_memory_config()
    if not config.database_url:
        raise ValueError("memory.database_url is required when memory.backend=postgres")

    try:
        profile_json = dict(memory_data)
        profile_json["lastUpdated"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        with _pg_connect(config.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memory_profiles (workspace_type, workspace_id, version, profile_json, last_updated, updated_at)
                VALUES (%s, %s, %s, %s::jsonb, NOW(), NOW())
                ON CONFLICT (workspace_type, workspace_id)
                DO UPDATE SET
                  version = EXCLUDED.version,
                  profile_json = EXCLUDED.profile_json,
                  last_updated = NOW(),
                  updated_at = NOW()
                """,
                (workspace_type, workspace_id, profile_json.get("version", "1.0"), json.dumps(profile_json)),
            )
            conn.commit()
        return True
    except Exception as e:
        print(f"Failed to save memory to postgres: {e}")
        return False


def get_memory_data(agent_name: str | None = None, workspace_type: str | None = None, workspace_id: str | None = None) -> dict[str, Any]:
    config = get_memory_config()
    scope_type, scope_id = _scope_values(workspace_type, workspace_id)

    if is_postgres_backend(config.backend):
        # Keep reads fresh for DB backend; avoid stale in-process cache.
        return _load_memory_from_postgres(scope_type, scope_id)

    file_path = _get_memory_file_path(agent_name, scope_type, scope_id)
    try:
        current_mtime = file_path.stat().st_mtime if file_path.exists() else None
    except OSError:
        current_mtime = None

    cache_key = (scope_type, scope_id, agent_name)
    cached = _memory_cache.get(cache_key)
    if cached is None or cached[1] != current_mtime:
        memory_data = _load_memory_from_file(agent_name, scope_type, scope_id)
        _memory_cache[cache_key] = (memory_data, current_mtime)
        return memory_data

    return cached[0]


def reload_memory_data(agent_name: str | None = None, workspace_type: str | None = None, workspace_id: str | None = None) -> dict[str, Any]:
    config = get_memory_config()
    scope_type, scope_id = _scope_values(workspace_type, workspace_id)

    if is_postgres_backend(config.backend):
        return _load_memory_from_postgres(scope_type, scope_id)

    file_path = _get_memory_file_path(agent_name, scope_type, scope_id)
    memory_data = _load_memory_from_file(agent_name, scope_type, scope_id)

    try:
        mtime = file_path.stat().st_mtime if file_path.exists() else None
    except OSError:
        mtime = None

    _memory_cache[(scope_type, scope_id, agent_name)] = (memory_data, mtime)
    return memory_data


def save_memory_data(memory_data: dict[str, Any], agent_name: str | None = None, workspace_type: str | None = None, workspace_id: str | None = None) -> bool:
    """Persist memory data to the configured backend for the given scope."""
    config = get_memory_config()
    scope_type, scope_id = _scope_values(workspace_type, workspace_id)

    if is_postgres_backend(config.backend):
        return _save_memory_to_postgres(memory_data, scope_type, scope_id)

    return _save_memory_to_file(memory_data, agent_name, scope_type, scope_id)


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
    for section in ("user", "history"):
        section_data = memory_data.get(section, {})
        for _key, val in section_data.items():
            if isinstance(val, dict) and "summary" in val:
                cleaned = _UPLOAD_SENTENCE_RE.sub("", val["summary"]).strip()
                cleaned = re.sub(r"  +", " ", cleaned)
                val["summary"] = cleaned

    facts = memory_data.get("facts", [])
    if facts:
        memory_data["facts"] = [f for f in facts if not _UPLOAD_SENTENCE_RE.search(f.get("content", ""))]

    return memory_data


class MemoryUpdater:
    """Updates memory using LLM based on conversation context."""

    def __init__(self, model_name: str | None = None):
        self._model_name = model_name

    def _get_model(self):
        config = get_memory_config()
        model_name = self._model_name or config.model_name
        return create_chat_model(name=model_name, thinking_enabled=False)

    def update_memory(
        self,
        messages: list[Any],
        thread_id: str | None = None,
        agent_name: str | None = None,
        workspace_type: str | None = None,
        workspace_id: str | None = None,
    ) -> bool:
        config = get_memory_config()
        if not config.enabled or not messages:
            return False

        try:
            scope_type, scope_id = _scope_values(workspace_type, workspace_id)
            current_memory = get_memory_data(agent_name, scope_type, scope_id)

            conversation_text = format_conversation_for_update(messages)
            if not conversation_text.strip():
                return False

            prompt = MEMORY_UPDATE_PROMPT.format(
                current_memory=json.dumps(current_memory, indent=2),
                conversation=conversation_text,
            )

            model = self._get_model()
            response = model.invoke(prompt)
            response_text = str(response.content).strip()

            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

            update_data = json.loads(response_text)
            updated_memory = self._apply_updates(current_memory, update_data, thread_id)
            updated_memory = _strip_upload_mentions_from_memory(updated_memory)

            if is_postgres_backend(config.backend):
                return _save_memory_to_postgres(updated_memory, scope_type, scope_id)

            return _save_memory_to_file(updated_memory, agent_name, scope_type, scope_id)

        except json.JSONDecodeError as e:
            print(f"Failed to parse LLM response for memory update: {e}")
            return False
        except Exception as e:
            print(f"Memory update failed: {e}")
            return False

    def _apply_updates(self, current_memory: dict[str, Any], update_data: dict[str, Any], thread_id: str | None = None) -> dict[str, Any]:
        config = get_memory_config()
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        user_updates = update_data.get("user", {})
        for section in ["workContext", "personalContext", "topOfMind"]:
            section_data = user_updates.get(section, {})
            if section_data.get("shouldUpdate") and section_data.get("summary"):
                current_memory["user"][section] = {
                    "summary": section_data["summary"],
                    "updatedAt": now,
                }

        history_updates = update_data.get("history", {})
        for section in ["recentMonths", "earlierContext", "longTermBackground"]:
            section_data = history_updates.get(section, {})
            if section_data.get("shouldUpdate") and section_data.get("summary"):
                current_memory["history"][section] = {
                    "summary": section_data["summary"],
                    "updatedAt": now,
                }

        facts_to_remove = set(update_data.get("factsToRemove", []))
        if facts_to_remove:
            current_memory["facts"] = [f for f in current_memory.get("facts", []) if f.get("id") not in facts_to_remove]

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

        if len(current_memory["facts"]) > config.max_facts:
            current_memory["facts"] = sorted(current_memory["facts"], key=lambda f: f.get("confidence", 0), reverse=True)[: config.max_facts]

        return current_memory


def update_memory_from_conversation(
    messages: list[Any],
    thread_id: str | None = None,
    agent_name: str | None = None,
    workspace_type: str | None = None,
    workspace_id: str | None = None,
) -> bool:
    updater = MemoryUpdater()
    return updater.update_memory(messages, thread_id, agent_name, workspace_type, workspace_id)
