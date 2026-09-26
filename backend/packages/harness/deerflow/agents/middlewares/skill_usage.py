"""Bounded, display-only snapshots of skill content actually loaded by the agent.

Kept on the producing message so normal run history supplies ownership, ordering
and persistence. This metadata must never be used for tool/secret authorization.
"""

import hashlib
import logging
import posixpath

import yaml

from deerflow.agents.middlewares.skill_context import _FRONT_MATTER_RE, build_skill_entry_metadata_from_read
from deerflow.sandbox.read_file_contract import READ_FILE_NO_CONTENT_RESULTS, READ_FILE_TRUNCATION_PREFIX

SKILL_USAGE_KEY = "skill_usage"
SKILL_USAGES_KEY = "skill_usages"
MAX_SKILL_SNAPSHOT_CHARS = 100_000
logger = logging.getLogger(__name__)


def record_skill_usage(runtime: object, usage: dict | None) -> None:
    """Register evidence before the next model callback snapshots canonical history."""
    context = getattr(runtime, "context", None)
    if usage is None or not isinstance(context, dict) or context.get("is_subagent"):
        return
    journal = context.get("__run_journal")
    record = getattr(journal, "record_skill_usage", None)
    if callable(record):
        try:
            record(usage)
        except Exception:
            logger.warning("Failed to record skill usage display snapshot", exc_info=True)


def build_skill_usage(
    path: str,
    content: str,
    *,
    skills_root: str,
    activation: str = "automatic",
    name: str | None = None,
    category: str | None = None,
    partial: bool = False,
) -> dict | None:
    entry = build_skill_entry_metadata_from_read(path, content, skills_root=skills_root)
    if entry is None or not content.strip() or content.strip() in READ_FILE_NO_CONTENT_RESULTS:
        return None
    normalized_path = entry["path"]
    relative = posixpath.relpath(normalized_path, posixpath.normpath(skills_root))
    if name is None:
        match = _FRONT_MATTER_RE.match(content)
        try:
            metadata = yaml.safe_load(match.group(1)) if match else None
        except yaml.YAMLError:
            metadata = None
        value = metadata.get("name") if isinstance(metadata, dict) else None
        name = value if isinstance(value, str) and value.strip() else posixpath.basename(posixpath.dirname(normalized_path))
    return {
        "name": name[:256],
        "description": entry["description"],
        "category": category or {"public": "public", "custom": "custom", "integrations": "integrations", "legacy": "legacy"}.get(relative.split("/")[0], "legacy"),
        "path": normalized_path,
        "content": content[:MAX_SKILL_SNAPSHOT_CHARS],
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "activation": activation,
        "partial": partial or len(content) > MAX_SKILL_SNAPSHOT_CHARS or READ_FILE_TRUNCATION_PREFIX in content,
    }
