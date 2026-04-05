"""Tooling for managing custom skills under skills/custom/."""

import asyncio
import json
import logging
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from langchain.tools import ToolRuntime, tool
from langgraph.typing import ContextT

from deerflow.agents.thread_state import ThreadState
from deerflow.skills.loader import get_skills_root_path
from deerflow.skills.parser import parse_skill_file
from deerflow.skills.security_scanner import ScanDecision, scan_content
from deerflow.skills.validation import validate_skill_frontmatter_content

logger = logging.getLogger(__name__)

ALLOWED_SUBDIRS = frozenset({"references", "templates", "scripts"})
MAX_TEXT_FILE_BYTES = 32 * 1024
MAX_HISTORY_SNIPPET_BYTES = 5_000

_skill_locks: dict[tuple[int, str], asyncio.Lock] = {}


def _get_lock(name: str) -> asyncio.Lock:
    """Get a per-skill lock scoped to the current event loop."""
    loop = asyncio.get_running_loop()
    key = (id(loop), name)
    lock = _skill_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _skill_locks[key] = lock
    return lock


def _clear_locks(name: str) -> None:
    """Drop cached locks for a skill after deletion."""
    for key in [key for key in _skill_locks if key[1] == name]:
        _skill_locks.pop(key, None)


def _get_skills_root_dir() -> Path:
    """Resolve the configured skills root directory."""
    try:
        from deerflow.config import get_app_config

        return get_app_config().skills.get_skills_path()
    except Exception:
        return get_skills_root_path()


def _get_custom_skills_dir() -> Path:
    return _get_skills_root_dir() / "custom"


def _validate_skill_name(name: str) -> str | None:
    """Return an error message if the skill name is invalid."""
    if not name:
        return "Skill name cannot be empty"
    if not re.match(r"^[a-z0-9-]+$", name):
        return f"Name '{name}' must be hyphen-case (lowercase letters, digits, hyphens only)"
    if name.startswith("-") or name.endswith("-") or "--" in name:
        return f"Name '{name}' cannot start/end with hyphen or contain consecutive hyphens"
    if len(name) > 64:
        return f"Name too long ({len(name)} chars, max 64)"
    return None


def _validate_text_size(content: str, *, label: str) -> str | None:
    """Validate text content size against the scanner-compatible upper bound."""
    size = len(content.encode("utf-8"))
    if size > MAX_TEXT_FILE_BYTES:
        return f"{label} is too large ({size} bytes, max {MAX_TEXT_FILE_BYTES} bytes for full security scanning)"
    return None


def _validate_skill_content(content: str, *, expected_name: str) -> str | None:
    """Validate SKILL.md content and ensure it matches the requested skill name."""
    valid, message, parsed_name = validate_skill_frontmatter_content(content)
    if not valid:
        return message
    if parsed_name != expected_name:
        return f"Frontmatter name '{parsed_name}' must match tool name '{expected_name}'"
    return None


def _validate_file_path(file_path: str | None) -> str | None:
    """Validate a relative path for a supporting text file."""
    if not file_path:
        return "file_path is required"
    if "\\" in file_path:
        return "file_path must use forward slashes"

    path = PurePosixPath(file_path)
    if path.is_absolute():
        return "Absolute paths are not allowed"
    if ".." in path.parts:
        return "Directory traversal is not allowed"
    if len(path.parts) < 2:
        allowed = ", ".join(sorted(ALLOWED_SUBDIRS))
        return f"file_path must be under one of: {allowed}/"
    if path.parts[0] not in ALLOWED_SUBDIRS:
        allowed = ", ".join(sorted(ALLOWED_SUBDIRS))
        return f"Files must be under one of: {allowed}/. Got: {path.parts[0]}/"
    return None


def _find_public_skill_by_name(name: str) -> Path | None:
    """Return the public skill directory for a given skill name, if present."""
    public_dir = _get_skills_root_dir() / "public"
    if not public_dir.exists():
        return None

    for current_root, dir_names, file_names in os.walk(public_dir, followlinks=True):
        dir_names[:] = sorted(entry for entry in dir_names if not entry.startswith("."))
        if "SKILL.md" not in file_names:
            continue

        skill_file = Path(current_root) / "SKILL.md"
        relative_path = skill_file.parent.relative_to(public_dir)
        skill = parse_skill_file(skill_file, category="public", relative_path=relative_path)
        if skill and skill.name == name:
            return skill.skill_dir
    return None


def _resolve_target_path(skill_dir: Path, file_path: str) -> Path:
    """Resolve a managed file path under a custom skill directory."""
    target = skill_dir / PurePosixPath(file_path)
    resolved_target = target.resolve()
    resolved_skill_dir = skill_dir.resolve()
    if not resolved_target.is_relative_to(resolved_skill_dir):
        raise ValueError("Path escapes skill directory")
    return resolved_target


def _truncate_for_history(content: str) -> str:
    raw = content.encode("utf-8")
    if len(raw) <= MAX_HISTORY_SNIPPET_BYTES:
        return content
    return raw[:MAX_HISTORY_SNIPPET_BYTES].decode("utf-8", errors="ignore")


def _append_history(
    skill_dir: Path,
    *,
    action: str,
    thread_id: str | None,
    prev_content: str | None,
    new_content: str | None,
    file_path: str | None = None,
) -> None:
    """Append an audit record to the skill's history file."""
    history_file = skill_dir / "HISTORY.jsonl"
    record: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "action": action,
        "author": "agent",
        "thread_id": thread_id or "unknown",
    }
    if file_path:
        record["file_path"] = file_path
    if prev_content is not None:
        record["prev_content"] = _truncate_for_history(prev_content)
    if new_content is not None:
        record["new_content"] = _truncate_for_history(new_content)

    history_file.parent.mkdir(parents=True, exist_ok=True)
    with history_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _extract_thread_id(runtime: ToolRuntime[ContextT, ThreadState] | None) -> str | None:
    """Extract thread_id from tool runtime, if present."""
    if runtime is None:
        return None
    if runtime.context:
        thread_id = runtime.context.get("thread_id")
        if thread_id is not None:
            return thread_id
    if runtime.config:
        return runtime.config.get("configurable", {}).get("thread_id")
    return None


def _format_scan_result(prefix: str, verdict_reason: str) -> str:
    return f"{prefix}: {verdict_reason}" if verdict_reason else prefix


@tool("skill_manage", parse_docstring=True)
async def skill_manage_tool(
    runtime: ToolRuntime[ContextT, ThreadState] | None,
    action: Literal["create", "patch", "edit", "delete", "write_file", "remove_file"],
    name: str,
    content: str | None = None,
    old_str: str | None = None,
    new_str: str | None = None,
    file_path: str | None = None,
    file_content: str | None = None,
) -> str:
    """Manage custom skills inside skills/custom/.

    This tool only edits custom skills. Built-in skills are read-only; to customize one,
    create a custom skill with the same frontmatter name and DeerFlow will prefer it over
    the built-in version. Supporting files are text-only in Phase 1 and must live under
    `references/`, `templates/`, or `scripts/`.

    Args:
        action: The action to perform: create, patch, edit, delete, write_file, or remove_file.
        name: Skill name in hyphen-case. The SKILL.md frontmatter name must match this value exactly.
        content: Full SKILL.md content for create or edit.
        old_str: Exact string to replace for patch.
        new_str: Replacement text for patch.
        file_path: Relative supporting-file path such as `references/guide.md`.
        file_content: Text content for write_file.
    """
    name_error = _validate_skill_name(name)
    if name_error:
        return f"Error: {name_error}"

    thread_id = _extract_thread_id(runtime)
    custom_root = _get_custom_skills_dir()
    skill_dir = custom_root / name

    if action != "create" and not (skill_dir / "SKILL.md").exists():
        if _find_public_skill_by_name(name) is not None:
            return (
                f"Error: '{name}' is a built-in skill. Use action='create' with the same name "
                "to create a custom override under skills/custom/."
            )
        return f"Error: Skill '{name}' not found in skills/custom/"

    lock = _get_lock(name)
    async with lock:
        if action == "create":
            if not content:
                return "Error: 'content' is required for create action"
            size_error = _validate_text_size(content, label="SKILL.md content")
            if size_error:
                return f"Error: {size_error}"
            content_error = _validate_skill_content(content, expected_name=name)
            if content_error:
                return f"Error: {content_error}"
            if (skill_dir / "SKILL.md").exists():
                return f"Error: Skill '{name}' already exists. Use 'patch' or 'edit' to modify it."

            verdict = await scan_content(content, content_type="skill")
            if verdict.decision == ScanDecision.BLOCK:
                return f"Error: Content blocked by security scanner: {verdict.reason}"

            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
            _append_history(skill_dir, action="create", thread_id=thread_id, prev_content=None, new_content=content)

            message = f"Skill '{name}' created at skills/custom/{name}/SKILL.md."
            if _find_public_skill_by_name(name) is not None:
                message += " This custom skill now overrides the built-in version."
            if verdict.decision == ScanDecision.WARN:
                message += f" Warning: {verdict.reason}"
            return message

        if action == "patch":
            if not old_str or new_str is None:
                return "Error: 'old_str' and 'new_str' are required for patch action"

            skill_file = skill_dir / "SKILL.md"
            current = skill_file.read_text(encoding="utf-8")
            if old_str not in current:
                return "Error: old_str not found in SKILL.md. Use 'edit' for a full rewrite."

            updated = current.replace(old_str, new_str, 1)
            size_error = _validate_text_size(updated, label="Patched SKILL.md content")
            if size_error:
                return f"Error: {size_error}"
            content_error = _validate_skill_content(updated, expected_name=name)
            if content_error:
                return f"Error: Patch would produce invalid SKILL.md: {content_error}"

            verdict = await scan_content(updated, content_type="skill")
            if verdict.decision == ScanDecision.BLOCK:
                return f"Error: Patched content blocked by security scanner: {verdict.reason}"

            skill_file.write_text(updated, encoding="utf-8")
            _append_history(skill_dir, action="patch", thread_id=thread_id, prev_content=current, new_content=updated)

            message = "Skill patched."
            if verdict.decision == ScanDecision.WARN:
                message += f" Warning: {verdict.reason}"
            return message

        if action == "edit":
            if not content:
                return "Error: 'content' is required for edit action"

            size_error = _validate_text_size(content, label="SKILL.md content")
            if size_error:
                return f"Error: {size_error}"
            content_error = _validate_skill_content(content, expected_name=name)
            if content_error:
                return f"Error: {content_error}"

            verdict = await scan_content(content, content_type="skill")
            if verdict.decision == ScanDecision.BLOCK:
                return f"Error: Content blocked by security scanner: {verdict.reason}"

            skill_file = skill_dir / "SKILL.md"
            previous = skill_file.read_text(encoding="utf-8")
            skill_file.write_text(content, encoding="utf-8")
            _append_history(skill_dir, action="edit", thread_id=thread_id, prev_content=previous, new_content=content)

            message = f"Skill '{name}' updated."
            if verdict.decision == ScanDecision.WARN:
                message += f" Warning: {verdict.reason}"
            return message

        if action == "delete":
            shutil.rmtree(skill_dir)
            _clear_locks(name)
            return f"Skill '{name}' deleted."

        if action == "write_file":
            if file_content is None:
                return "Error: 'file_content' is required for write_file action"

            path_error = _validate_file_path(file_path)
            if path_error:
                return f"Error: {path_error}"
            size_error = _validate_text_size(file_content, label="Supporting file content")
            if size_error:
                return f"Error: {size_error}"

            assert file_path is not None
            try:
                target = _resolve_target_path(skill_dir, file_path)
            except ValueError as e:
                return f"Error: {e}"

            if target.exists() and target.is_dir():
                return f"Error: '{file_path}' is a directory"

            content_type = "script" if PurePosixPath(file_path).parts[0] == "scripts" else "skill"
            verdict = await scan_content(file_content, content_type=content_type)
            if verdict.decision != ScanDecision.ALLOW and content_type == "script":
                return f"Error: Script blocked by security scanner: {verdict.reason}"
            if verdict.decision == ScanDecision.BLOCK:
                return f"Error: Content blocked by security scanner: {verdict.reason}"

            previous = target.read_text(encoding="utf-8") if target.exists() else None
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(file_content, encoding="utf-8")
            _append_history(skill_dir, action="write_file", thread_id=thread_id, prev_content=previous, new_content=file_content, file_path=file_path)

            message = f"File '{file_path}' written to skill '{name}'."
            if verdict.decision == ScanDecision.WARN:
                message += f" Warning: {verdict.reason}"
            return message

        path_error = _validate_file_path(file_path)
        if path_error:
            return f"Error: {path_error}"

        assert file_path is not None
        try:
            target = _resolve_target_path(skill_dir, file_path)
        except ValueError as e:
            return f"Error: {e}"

        if not target.exists():
            return f"Error: File '{file_path}' not found"
        if not target.is_file():
            return f"Error: '{file_path}' is not a file"

        previous = target.read_text(encoding="utf-8")
        target.unlink()
        _append_history(skill_dir, action="remove_file", thread_id=thread_id, prev_content=previous, new_content=None, file_path=file_path)
        return f"File '{file_path}' removed from skill '{name}'."
