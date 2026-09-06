"""Tool for discovering historical uploaded files in the current thread.

Unlike ``<current_uploads>`` which lists only this run's newly uploaded files,
this tool lets the agent discover files uploaded in previous turns on demand.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from pathlib import Path
from typing import Annotated, Any

from langchain.tools import tool
from langgraph.config import get_config

from deerflow.agents.middlewares.input_sanitization_middleware import neutralize_untrusted_tags
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.tools.types import Runtime
from deerflow.uploads.manager import is_upload_staging_file
from deerflow.utils.file_outline import extract_outline_for_file

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RESULTS = 20
_MAX_MAX_RESULTS = 100


def _extension_label(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    return neutralize_untrusted_tags(suffix) or "(no extension)"


def _format_omitted_summary(omitted: list[str]) -> str:
    counts = Counter(_extension_label(Path(f)) for f in omitted)
    parts = [f"{count} {ext}" for ext, count in sorted(counts.items())]
    return neutralize_untrusted_tags(", ".join(parts))


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
        logger.warning(
            "Failed to read uploaded_files from runtime.state; current-run files may appear in list_uploaded_files results",
            exc_info=True,
        )

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
    candidates: list[tuple[float, Path, int]] = []
    try:
        # Collect file entries once to build the name set and iterate.
        entries = [e for e in os.scandir(uploads_dir) if e.is_file() and not e.is_symlink() and not is_upload_staging_file(e.name)]
        all_names: set[str] = {e.name for e in entries}

        for entry in entries:
            if entry.name in current_run_filenames:
                continue
            # Skip .md files that are conversion artifacts of another file.
            # Known limitation: if a user manually uploads both report.pdf and
            # report.md, the .md is hidden as a "conversion artifact".  This is
            # acceptable for the MVP — triggering this requires uploading files
            # whose stems collide with converted documents, which is rare.
            if entry.name.endswith(".md"):
                stem = entry.name[:-3]  # remove ".md"
                non_md_siblings = {n for n in all_names if n != entry.name and Path(n).stem == stem}
                if non_md_siblings:
                    continue
            stat = entry.stat()
            candidates.append((stat.st_mtime, Path(entry.path), stat.st_size))
    except OSError:
        return {"files": [], "message": f"Failed to read uploads directory: {uploads_dir}"}

    if not candidates:
        return {"files": [], "message": "No historical uploaded files in this thread."}

    # Sort by mtime descending (most recent first)
    candidates.sort(key=lambda item: item[0], reverse=True)

    total_count = len(candidates)
    truncated = total_count > max_results
    visible = candidates[:max_results]
    omitted_paths = [p.name for _, p, _ in candidates[max_results:]]

    files: list[dict] = []
    for _, file_path, st_size in visible:
        filename = file_path.name
        file_info: dict = {
            "filename": neutralize_untrusted_tags(filename),
            "size": st_size,
            "path": neutralize_untrusted_tags(f"/mnt/user-data/uploads/{filename}"),
            "extension": neutralize_untrusted_tags(file_path.suffix),
        }

        should_include_outline = outline_for_all or filename in outline_filenames
        if should_include_outline:
            outline, preview = extract_outline_for_file(file_path)
            if outline:
                file_info["outline"] = [{**entry, "title": neutralize_untrusted_tags(entry["title"])} if "title" in entry else entry for entry in outline]
            if preview:
                file_info["outline_preview"] = [neutralize_untrusted_tags(p) for p in preview]

        files.append(file_info)

    result: dict = {
        "files": files,
        "total_count": total_count,
    }

    if truncated:
        result["truncated"] = True
        result["omitted_summary"] = _format_omitted_summary(omitted_paths)

    if files:
        result["message"] = f"Found {total_count} historical file(s)."
    else:
        result["message"] = "No historical uploaded files in this thread."

    return result


@tool
def list_uploaded_files(
    runtime: Runtime,
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
