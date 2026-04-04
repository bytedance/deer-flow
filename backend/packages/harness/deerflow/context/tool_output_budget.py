"""Shared tool-output budgeting helpers for high-noise tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from deerflow.agents.thread_state import ThreadDataState
from deerflow.config.context_management_config import get_context_management_config
from deerflow.config.paths import VIRTUAL_PATH_PREFIX, get_paths

_MAX_TOOL_OUTPUT_CHARS = 30000
_TOOL_OUTPUT_HEAD_CHARS = 8000
_TOOL_OUTPUT_TAIL_CHARS = 3000


def truncate_tool_output(content: str, *, tool_name: str) -> str:
    """Trim oversized tool output before it is written back into thread state."""
    if len(content) <= _MAX_TOOL_OUTPUT_CHARS:
        return content

    head = content[:_TOOL_OUTPUT_HEAD_CHARS].rstrip()
    tail = content[-_TOOL_OUTPUT_TAIL_CHARS:].lstrip()
    omitted = len(content) - len(head) - len(tail)

    guidance = "Rerun with a narrower command or line range if you need more detail."
    if tool_name == "read_file":
        guidance = "Use start_line/end_line or read a narrower section if you need more detail."

    return (
        f"{head}\n\n"
        f"[... {omitted} characters omitted from {tool_name} output ...]\n"
        f"{guidance}\n\n"
        f"{tail}"
    )


def _externalize_tool_output(content: str, *, tool_name: str, thread_data: ThreadDataState | None) -> str | None:
    outputs_path = (thread_data or {}).get("outputs_path")
    if not outputs_path:
        return None

    config = get_context_management_config().tool_result_budget
    storage_dir = Path(outputs_path) / config.storage_subdir
    storage_dir.mkdir(parents=True, exist_ok=True)

    ext = "log" if tool_name in {"bash", "web_fetch"} else "txt"
    filename = f"{tool_name}-{uuid4().hex[:12]}.{ext}"
    host_path = storage_dir / filename
    host_path.write_text(content, encoding="utf-8")
    return f"{VIRTUAL_PATH_PREFIX}/outputs/{config.storage_subdir}/{filename}"


def prepare_tool_output_for_context(
    content: str,
    *,
    tool_name: str,
    thread_data: ThreadDataState | None = None,
) -> str:
    """Apply tool-result budgeting before falling back to plain truncation."""
    config = get_context_management_config().tool_result_budget
    if not config.enabled or len(content) < config.externalize_min_chars:
        return truncate_tool_output(content=content, tool_name=tool_name)

    try:
        virtual_path = _externalize_tool_output(content, tool_name=tool_name, thread_data=thread_data)
    except OSError:
        virtual_path = None

    if not virtual_path:
        return truncate_tool_output(content=content, tool_name=tool_name)

    head = content[: config.preview_head_chars].rstrip()
    tail = content[-config.preview_tail_chars :].lstrip() if config.preview_tail_chars else ""
    omitted = max(len(content) - len(head) - len(tail), 0)

    guidance = f"Read {virtual_path} with `read_file` if you need the full output."
    if tool_name == "read_file":
        guidance = f"Read {virtual_path} with `read_file`, or re-run `read_file` on a narrower line range if you need nearby context."
    elif tool_name == "web_search":
        guidance = f"Read {virtual_path} with `read_file` if you need the full search result payload, or re-run `web_search` with a narrower query."
    elif tool_name == "web_fetch":
        guidance = f"Read {virtual_path} with `read_file` if you need the full fetched page content, or re-run `web_fetch` on a more specific URL."

    parts = [head] if head else []
    parts.extend(
        [
            "",
            f"[Full {tool_name} output saved to {virtual_path}. Preview omitted {omitted} characters from the middle.]",
            guidance,
        ]
    )
    if tail:
        parts.extend(["", tail])
    return "\n".join(parts)


def prepare_tool_result_value_for_context(
    result: Any,
    *,
    tool_name: str,
    thread_data: ThreadDataState | None = None,
) -> Any:
    """Budget oversized tool results while keeping small structured payloads intact."""
    if isinstance(result, str):
        return prepare_tool_output_for_context(result, tool_name=tool_name, thread_data=thread_data)

    try:
        serialized = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        serialized = str(result)

    if len(serialized) < get_context_management_config().tool_result_budget.externalize_min_chars:
        return result

    return prepare_tool_output_for_context(serialized, tool_name=tool_name, thread_data=thread_data)


def resolve_thread_data_from_config() -> ThreadDataState | None:
    """Best-effort thread-data resolution when a tool doesn't receive runtime."""
    try:
        from langgraph.config import get_config

        config = get_config()
        thread_id = (config or {}).get("configurable", {}).get("thread_id")
        if not thread_id:
            return None
        paths = get_paths()
        return {
            "workspace_path": str(paths.sandbox_workspace_dir(thread_id)),
            "uploads_path": str(paths.sandbox_uploads_dir(thread_id)),
            "outputs_path": str(paths.sandbox_outputs_dir(thread_id)),
        }
    except Exception:
        return None
