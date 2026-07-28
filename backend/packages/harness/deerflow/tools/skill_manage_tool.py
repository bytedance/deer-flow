"""Tool for creating and evolving custom skills."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, NoReturn
from weakref import WeakValueDictionary

from langchain.tools import tool

from deerflow.agents.lead_agent.prompt import refresh_user_skills_system_prompt_cache_async
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.skills.security_scanner import scan_skill_content
from deerflow.skills.security_static_scanner import (
    StaticFinding,
    StaticScanBlockedError,
    StaticScannerError,
    enforce_static_scan,
)
from deerflow.skills.storage import get_or_new_user_skill_storage
from deerflow.skills.storage.skill_storage import SkillStorage
from deerflow.skills.types import SKILL_MD_FILE
from deerflow.tools.sync import make_sync_tool_wrapper
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)

# Lock granularity: (user_id, skill_name) to avoid cross-user blocking.
_skill_locks: WeakValueDictionary[tuple[str, str], asyncio.Lock] = WeakValueDictionary()


def _get_lock(user_id: str, name: str) -> asyncio.Lock:
    key = (user_id, name)
    lock = _skill_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _skill_locks[key] = lock
    return lock


def _get_thread_id(runtime: Runtime | None) -> str | None:
    if runtime is None:
        return None
    if runtime.context and runtime.context.get("thread_id"):
        return runtime.context.get("thread_id")
    return runtime.config.get("configurable", {}).get("thread_id")


def _history_record(*, action: str, file_path: str, prev_content: str | None, new_content: str | None, thread_id: str | None, scanner: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": action,
        "author": "agent",
        "thread_id": thread_id,
        "file_path": file_path,
        "prev_content": prev_content,
        "new_content": new_content,
        "scanner": scanner,
    }


async def _scan_or_raise(content: str, *, executable: bool, location: str, static_findings: list[StaticFinding] | None = None) -> dict[str, Any]:
    # In-graph: the graph root already attached tracing (see the INVARIANT in
    # agents/lead_agent/agent.py), so the scan model must not attach it again.
    result = await scan_skill_content(content, executable=executable, location=location, static_findings=static_findings or [], attach_tracing=False)
    if result.decision == "block":
        raise ValueError(f"Security scan blocked the write: {result.reason}")
    if executable and result.decision != "allow":
        raise ValueError(f"Security scan rejected executable content: {result.reason}")
    return {"decision": result.decision, "reason": result.reason}


def _raise_static_block(error: StaticScanBlockedError) -> NoReturn:
    payload = {
        "skill_name": error.skill_name,
        "findings": error.findings,
    }
    raise ValueError(f"{error} Findings: {json.dumps(payload, ensure_ascii=False)}") from error


def _raise_static_scan_failure(name: str, error: StaticScannerError) -> NoReturn:
    raise ValueError(f"Static security scan failed for skill '{name}': {error}") from error


async def _scan_static_candidate_or_raise(name: str, updates: dict[str, str], skill_storage: SkillStorage | None = None) -> list[StaticFinding]:
    def _scan_candidate() -> list[StaticFinding]:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / name
            if skill_storage is None:
                skill_dir.mkdir(parents=True)
            else:
                shutil.copytree(skill_storage.get_custom_skill_dir(name), skill_dir)
            for relative_path, content in updates.items():
                target = skill_dir / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            return enforce_static_scan(skill_dir, skill_name=name)

    try:
        return await _to_thread(_scan_candidate)
    except StaticScanBlockedError as e:
        _raise_static_block(e)
    except StaticScannerError as e:
        _raise_static_scan_failure(name, e)


async def _to_thread(func, /, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


async def _skill_manage_impl(
    runtime: Runtime,
    action: str,
    name: str,
    content: str | None = None,
    path: str | None = None,
    find: str | None = None,
    replace: str | None = None,
    expected_count: int | None = None,
) -> str:
    """Manage custom skills under skills/custom/.

    Args:
        action: One of create, patch, edit, delete, write_file, remove_file.
        name: Skill name in hyphen-case.
        content: New file content for create, edit, or write_file.
        path: Supporting file path for write_file or remove_file.
        find: Existing text to replace for patch.
        replace: Replacement text for patch.
        expected_count: Optional expected number of replacements for patch.
    """
    name = SkillStorage.validate_skill_name(name)
    user_id = resolve_runtime_user_id(runtime)
    lock = _get_lock(user_id, name)
    thread_id = _get_thread_id(runtime)
    skill_storage = get_or_new_user_skill_storage(user_id)

    async with lock:
        if action == "create":
            if await _to_thread(skill_storage.custom_skill_exists, name):
                raise ValueError(f"Custom skill '{name}' already exists.")
            if content is None:
                raise ValueError("content is required for create.")
            await _to_thread(skill_storage.validate_skill_markdown_content, name, content)
            static_findings = await _scan_static_candidate_or_raise(name, {SKILL_MD_FILE: content})
            scan = await _scan_or_raise(content, executable=False, location=f"{name}/{SKILL_MD_FILE}", static_findings=static_findings)
            scan["static_findings"] = static_findings
            await _to_thread(skill_storage.write_custom_skill, name, SKILL_MD_FILE, content)
            await _to_thread(
                skill_storage.append_history,
                name,
                _history_record(action="create", file_path=SKILL_MD_FILE, prev_content=None, new_content=content, thread_id=thread_id, scanner=scan),
            )
            await refresh_user_skills_system_prompt_cache_async(user_id)
            return f"Created custom skill '{name}'."
        if action == "edit":
            await _to_thread(skill_storage.ensure_custom_skill_is_editable, name)
            if content is None:
                raise ValueError("content is required for edit.")
            await _to_thread(skill_storage.validate_skill_markdown_content, name, content)
            static_findings = await _scan_static_candidate_or_raise(name, {SKILL_MD_FILE: content})
            scan = await _scan_or_raise(content, executable=False, location=f"{name}/{SKILL_MD_FILE}", static_findings=static_findings)
            scan["static_findings"] = static_findings
            skill_file = skill_storage.get_custom_skill_file(name)
            prev_content = await _to_thread(skill_file.read_text, encoding="utf-8")
            await _to_thread(skill_storage.write_custom_skill, name, SKILL_MD_FILE, content)
            await _to_thread(
                skill_storage.append_history,
                name,
                _history_record(action="edit", file_path=SKILL_MD_FILE, prev_content=prev_content, new_content=content, thread_id=thread_id, scanner=scan),
            )
            await refresh_user_skills_system_prompt_cache_async(user_id)
            return f"Updated custom skill '{name}'."

        if action == "patch":
            await _to_thread(skill_storage.ensure_custom_skill_is_editable, name)
            if find is None or replace is None:
                raise ValueError("find and replace are required for patch.")
            skill_file = skill_storage.get_custom_skill_file(name)
            prev_content = await _to_thread(skill_file.read_text, encoding="utf-8")
            occurrences = prev_content.count(find)
            if occurrences == 0:
                raise ValueError("Patch target not found in SKILL.md.")
            if expected_count is not None and occurrences != expected_count:
                raise ValueError(f"Expected {expected_count} replacements but found {occurrences}.")
            replacement_count = expected_count if expected_count is not None else 1
            new_content = prev_content.replace(find, replace, replacement_count)
            await _to_thread(skill_storage.validate_skill_markdown_content, name, new_content)
            static_findings = await _scan_static_candidate_or_raise(name, {SKILL_MD_FILE: new_content})
            scan = await _scan_or_raise(new_content, executable=False, location=f"{name}/{SKILL_MD_FILE}", static_findings=static_findings)
            scan["static_findings"] = static_findings
            await _to_thread(skill_storage.write_custom_skill, name, SKILL_MD_FILE, new_content)
            await _to_thread(
                skill_storage.append_history,
                name,
                _history_record(action="patch", file_path=SKILL_MD_FILE, prev_content=prev_content, new_content=new_content, thread_id=thread_id, scanner=scan),
            )
            await refresh_user_skills_system_prompt_cache_async(user_id)
            return f"Patched custom skill '{name}' ({replacement_count} replacement(s) applied, {occurrences} match(es) found)."

        if action == "delete":
            await _to_thread(
                skill_storage.delete_custom_skill,
                name,
                history_meta=_history_record(
                    action="delete",
                    file_path=SKILL_MD_FILE,
                    prev_content=None,
                    new_content=None,
                    thread_id=thread_id,
                    scanner={"decision": "allow", "reason": "Deletion requested."},
                ),
            )
            await refresh_user_skills_system_prompt_cache_async(user_id)
            return f"Deleted custom skill '{name}'."

        if action == "write_file":
            await _to_thread(skill_storage.ensure_custom_skill_is_editable, name)
            if path is None or content is None:
                raise ValueError("path and content are required for write_file.")
            target = await _to_thread(skill_storage.ensure_safe_support_path, name, path)
            exists = await _to_thread(target.exists)
            prev_content = await _to_thread(target.read_text, encoding="utf-8") if exists else None
            executable = "scripts/" in path or path.startswith("scripts/")
            static_findings = await _scan_static_candidate_or_raise(name, {path: content}, skill_storage)
            scan = await _scan_or_raise(content, executable=executable, location=f"{name}/{path}", static_findings=static_findings)
            scan["static_findings"] = static_findings
            await _to_thread(skill_storage.write_custom_skill, name, path, content)
            await _to_thread(
                skill_storage.append_history,
                name,
                _history_record(action="write_file", file_path=path, prev_content=prev_content, new_content=content, thread_id=thread_id, scanner=scan),
            )
            await refresh_user_skills_system_prompt_cache_async(user_id)
            return f"Wrote '{path}' for custom skill '{name}'."

        if action == "remove_file":
            await _to_thread(skill_storage.ensure_custom_skill_is_editable, name)
            if path is None:
                raise ValueError("path is required for remove_file.")
            target = await _to_thread(skill_storage.ensure_safe_support_path, name, path)
            if not await _to_thread(target.exists):
                raise FileNotFoundError(f"Supporting file '{path}' not found for skill '{name}'.")
            prev_content = await _to_thread(target.read_text, encoding="utf-8")
            await _to_thread(target.unlink)
            await _to_thread(
                skill_storage.append_history,
                name,
                _history_record(action="remove_file", file_path=path, prev_content=prev_content, new_content=None, thread_id=thread_id, scanner={"decision": "allow", "reason": "Deletion requested."}),
            )
            await refresh_user_skills_system_prompt_cache_async(user_id)
            return f"Removed '{path}' from custom skill '{name}'."

        if await _to_thread(skill_storage.public_skill_exists, name):
            # public_skill_exists covers both built-in (PUBLIC) and legacy (LEGACY)
            # skills; the UserScopedSkillStorage override distinguishes them in
            # ensure_custom_skill_is_editable with category-specific messages.
            raise ValueError(f"'{name}' is a read-only skill (built-in or legacy shared). To customise it, create your own version with the same name.")
        raise ValueError(f"Unsupported action '{action}'.")


@tool("skill_manage", parse_docstring=True)
async def skill_manage_tool(
    runtime: Runtime,
    action: str,
    name: str,
    content: str | None = None,
    path: str | None = None,
    find: str | None = None,
    replace: str | None = None,
    expected_count: int | None = None,
) -> str:
    """Manage custom skills under skills/custom/.

    Args:
        action: One of create, patch, edit, delete, write_file, remove_file.
        name: Skill name in hyphen-case.
        content: New file content for create, edit, or write_file.
        path: Supporting file path for write_file or remove_file.
        find: Existing text to replace for patch.
        replace: Replacement text for patch.
        expected_count: Optional expected number of replacements for patch.
    """
    return await _skill_manage_impl(
        runtime=runtime,
        action=action,
        name=name,
        content=content,
        path=path,
        find=find,
        replace=replace,
        expected_count=expected_count,
    )


skill_manage_tool.func = make_sync_tool_wrapper(_skill_manage_impl, "skill_manage")
