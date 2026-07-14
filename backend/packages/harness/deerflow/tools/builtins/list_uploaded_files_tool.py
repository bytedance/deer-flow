"""Tool for discovering historical uploaded files in the current thread.

Unlike ``<current_uploads>`` which lists only this run's newly uploaded files,
this tool lets the agent discover files uploaded in previous turns on demand.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Annotated, Any

from langchain.tools import InjectedToolArg, tool
from langgraph.config import get_config

from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.tools.types import Runtime
from deerflow.uploads.manager import is_upload_staging_file
from deerflow.utils.file_outline import extract_outline_for_file

_DEFAULT_MAX_RESULTS = 20
_MAX_MAX_RESULTS = 100


def _extension_label(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    return suffix or "(no extension)"


def _format_omitted_summary(omitted: list[str], total_omitted: int) -> str:
    counts = Counter(_extension_label(Path(f)) for f in omitted)
    parts = [f"{count} {ext}" for ext, count in sorted(counts.items())]
    if total_omitted > len(omitted):
        parts.append(f"... ({total_omitted} total)")
    return ", ".join(parts)


def _resolve_thread_id(runtime: Runtime) -> str | None:
    """Resolve the current thread id from runtime context or RunnableConfig."""
    thread_id = runtime.context.get("thread_id") if runtime.context else None
    if thread_id:
        return thread_id

    runtime_config = getattr(runtime, "config", None) or {}
    thread_id = runtime_config.get("configurable", {}).get("thread_id")
    if thread_id:
        return thread_id

    try:
        return get_config().get("configurable", {}).get("thread_id")
    except RuntimeError:
        return None


def _resolve_user_id(runtime: Runtime) -> str:
    """Resolve the current user id."""
    from deerflow.runtime.user_context import resolve_runtime_user_id

    return resolve_runtime_user_id(runtime) or get_effective_user_id()


def _list_uploaded_files_impl(
    include_outline: bool | list[str] = False,
    max_results: int = _DEFAULT_MAX_RESULTS,
    runtime: Runtime | None = None,
    *,
    _paths: Any | None = None,
) -> dict:
    """Core implementation — testable without the @tool wrapper."""
    if runtime is None:
        return {"files": [], "message": "No runtime context available."}

    thread_id = _resolve_thread_id(runtime)
    if thread_id is None:
        return {"files": [], "message": "Thread not found."}

    user_id = _resolve_user_id(runtime)
    paths = _paths or get_paths()
    uploads_dir = paths.sandbox_uploads_dir(thread_id, user_id=user_id)

    if not uploads_dir.exists():
        return {"files": [], "message": "No uploads directory for this thread."}

    # Resolve the set of filenames uploaded in the current run so we can exclude them.
    current_run_filenames: set[str] = set()
    try:
        state = runtime.state
        uploaded = state.get("uploaded_files") if isinstance(state, dict) else getattr(state, "uploaded_files", None)
        if isinstance(uploaded, list):
            for entry in uploaded:
                if isinstance(entry, dict) and entry.get("filename"):
                    current_run_filenames.add(entry["filename"])
    except Exception:
        pass  # Non-critical — worst case we list a file that is also in <current_uploads>.

    # Normalize max_results
    max_results = max(1, min(max_results, _MAX_MAX_RESULTS))

    # Normalize include_outline
    if isinstance(include_outline, bool):
        outline_for_all: bool = include_outline
        outline_filenames: set[str] = set()
    else:
        outline_for_all = False
        outline_filenames = set(include_outline)

    # Collect historical files (sorted by mtime descending).
    # Skip .md files that are conversion artifacts (have a same-stem non-.md sibling).
    candidates: list[tuple[float, Path]] = []
    try:
        # First pass: collect all non-staging filenames so we can detect conversion artifacts
        all_names: set[str] = {entry.name for entry in os.scandir(uploads_dir) if entry.is_file() and not is_upload_staging_file(entry.name)}

        for entry in os.scandir(uploads_dir):
            if not entry.is_file():
                continue
            if is_upload_staging_file(entry.name):
                continue
            if entry.name in current_run_filenames:
                continue
            # Skip .md files that are conversion artifacts of another file
            if entry.name.endswith(".md"):
                stem = entry.name[:-3]  # remove ".md"
                non_md_siblings = {n for n in all_names if n != entry.name and Path(n).stem == stem}
                if non_md_siblings:
                    continue
            stat = entry.stat()
            candidates.append((stat.st_mtime, Path(entry.path)))
    except OSError:
        return {"files": [], "message": f"Failed to read uploads directory: {uploads_dir}"}

    if not candidates:
        return {"files": [], "message": "No historical uploaded files in this thread."}

    # Sort by mtime descending (most recent first)
    candidates.sort(key=lambda item: item[0], reverse=True)

    total_count = len(candidates)
    truncated = total_count > max_results
    visible = candidates[:max_results]
    omitted_paths = [p.name for _, p in candidates[max_results:]]

    files: list[dict] = []
    for _, file_path in visible:
        filename = file_path.name
        stat = file_path.stat()
        file_info: dict = {
            "filename": filename,
            "size": stat.st_size,
            "path": f"/mnt/user-data/uploads/{filename}",
            "extension": file_path.suffix,
        }

        should_include_outline = outline_for_all or filename in outline_filenames
        if should_include_outline:
            outline, preview = extract_outline_for_file(file_path)
            if outline:
                file_info["outline"] = outline
            if preview:
                file_info["outline_preview"] = preview

        files.append(file_info)

    result: dict = {
        "files": files,
        "total_count": total_count,
    }

    if truncated:
        result["truncated"] = True
        result["omitted_summary"] = _format_omitted_summary(omitted_paths, total_count - max_results)

    if files:
        result["message"] = f"Found {total_count} historical file(s)."
    else:
        result["message"] = "No historical uploaded files in this thread."

    return result


@tool
def list_uploaded_files(
    include_outline: Annotated[
        bool | list[str],
        "Control which files get their document outline (headings/preview) returned. "
        "False (default): no outline for any file — just filename, size, and path. "
        "True: include outline/preview for every .md-convertible file. "
        'list of filenames: include outline/preview only for those specific files (e.g. ["report.md", "data.csv"]).',
    ] = False,
    max_results: Annotated[
        int,
        "Maximum number of files to return (default 20, max 100).",
    ] = _DEFAULT_MAX_RESULTS,
    runtime: Annotated[Runtime, InjectedToolArg] | None = None,
) -> dict:
    """Discover historical uploaded files available in this thread.

    Returns files that were uploaded in PREVIOUS turns — files uploaded in the
    current run are excluded (they are already listed in <current_uploads>).

    Use this tool when:
    - The user refers to previously uploaded files without naming them (e.g. "analyze those PDFs I uploaded before")
    - You need to check what files are available in this thread
    - You are starting work on a thread and want an overview of available data

    Skip this tool when:
    - The user names a specific file — use read_file or grep directly with the path
    - The file was uploaded in the current run — it's already in <current_uploads>
    """
    return _list_uploaded_files_impl(
        include_outline=include_outline,
        max_results=max_results,
        runtime=runtime,
    )
