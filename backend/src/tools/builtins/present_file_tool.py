import logging
import os
import shutil
from pathlib import Path
from typing import Annotated

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.config import get_config
from langgraph.types import Command
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState
from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths

OUTPUTS_VIRTUAL_PREFIX = f"{VIRTUAL_PATH_PREFIX}/outputs"
logger = logging.getLogger(__name__)


def _normalize_presented_filepath(
    runtime: ToolRuntime[ContextT, ThreadState],
    filepath: str,
) -> str:
    """Normalize a presented file path to the `/mnt/user-data/outputs/*` contract.

    Accepts either:
    - A virtual sandbox path such as `/mnt/user-data/outputs/report.md`
    - A host-side thread outputs path such as
      `/app/backend/.deer-flow/threads/<thread>/user-data/outputs/report.md`

    Returns:
        The normalized virtual path.

    Raises:
        ValueError: If runtime metadata is missing or the path is outside the
            current thread's outputs directory.
    """
    if runtime.state is None:
        raise ValueError("Thread runtime state is not available")

    ctx = runtime.context
    thread_id = ctx.get("thread_id") if (ctx is not None and hasattr(ctx, "get")) else None
    if not thread_id:
        try:
            thread_id = get_config().get("configurable", {}).get("thread_id")
        except RuntimeError:
            pass
    if not thread_id:
        raise ValueError("Thread ID is not available in runtime context")

    thread_data = runtime.state.get("thread_data") or {}
    outputs_path = thread_data.get("outputs_path")
    if not outputs_path:
        raise ValueError("Thread outputs path is not available in runtime state")

    outputs_dir = Path(outputs_path).resolve()
    stripped = filepath.lstrip("/")
    virtual_prefix = VIRTUAL_PATH_PREFIX.lstrip("/")

    if stripped == virtual_prefix or stripped.startswith(virtual_prefix + "/"):
        actual_path = get_paths().resolve_virtual_path(thread_id, filepath)
    else:
        actual_path = Path(filepath).expanduser().resolve()

    try:
        relative_path = actual_path.relative_to(outputs_dir)
    except ValueError as exc:
        raise ValueError(f"Only files in {OUTPUTS_VIRTUAL_PREFIX} can be presented: {filepath}") from exc

    return f"{OUTPUTS_VIRTUAL_PREFIX}/{relative_path.as_posix()}"


def _resolve_thread_id(runtime: ToolRuntime[ContextT, ThreadState]) -> str | None:
    """Best-effort thread id resolution from runtime/context."""
    ctx = runtime.context
    thread_id = ctx.get("thread_id") if (ctx is not None and hasattr(ctx, "get")) else None
    if thread_id:
        return thread_id
    try:
        return get_config().get("configurable", {}).get("thread_id")
    except RuntimeError:
        return None


def _export_presented_files_to_local(
    runtime: ToolRuntime[ContextT, ThreadState],
    normalized_paths: list[str],
) -> tuple[int, str | None]:
    """Copy presented output files to a local host directory if configured.

    Enable by setting ``DEER_FLOW_EXPORT_DIR`` to an absolute or relative path.
    Export layout:
      {DEER_FLOW_EXPORT_DIR}/{thread_id}/{relative_path_under_outputs}
    """
    export_root = os.getenv("DEER_FLOW_EXPORT_DIR")
    if not export_root:
        return 0, None

    thread_id = _resolve_thread_id(runtime)
    if not thread_id:
        logger.warning("present_files export skipped: thread_id is unavailable (DEER_FLOW_EXPORT_DIR=%s)", export_root)
        return 0, None

    exported = 0
    export_base = Path(export_root).expanduser().resolve() / thread_id
    try:
        export_base.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("present_files export failed: cannot create export directory '%s' (thread_id=%s): %s", str(export_base), thread_id, exc)
        return 0, None

    for virtual_path in normalized_paths:
        try:
            actual_path = get_paths().resolve_virtual_path(thread_id, virtual_path)
            relative_path = Path(virtual_path).as_posix().removeprefix(f"{OUTPUTS_VIRTUAL_PREFIX}/")
            if not relative_path or relative_path == Path(virtual_path).as_posix():
                continue
            target_path = export_base / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(actual_path, target_path)
            exported += 1
        except Exception as exc:
            # Best-effort export: never fail the primary presentation flow.
            logger.warning("present_files export failed for '%s' (thread_id=%s): %s", virtual_path, thread_id, exc)
            continue

    if exported == 0 and normalized_paths:
        logger.warning("present_files export completed with 0 files copied (thread_id=%s, export_dir=%s, requested=%d)", thread_id, str(export_base), len(normalized_paths))

    return exported, str(export_base)


@tool("present_files", parse_docstring=True)
def present_file_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    filepaths: list[str],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Make files visible to the user for viewing and rendering in the client interface.

    When to use the present_files tool:

    - Making any file available for the user to view, download, or interact with
    - Presenting multiple related files at once
    - After creating files that should be presented to the user

    When NOT to use the present_files tool:
    - When you only need to read file contents for your own processing
    - For temporary or intermediate files not meant for user viewing

    Notes:
    - You should call this tool after creating files and moving them to the `/mnt/user-data/outputs` directory.
    - This tool can be safely called in parallel with other tools. State updates are handled by a reducer to prevent conflicts.

    Args:
        filepaths: List of absolute file paths to present to the user. **Only** files in `/mnt/user-data/outputs` can be presented.
    """
    try:
        normalized_paths = [_normalize_presented_filepath(runtime, filepath) for filepath in filepaths]
    except ValueError as exc:
        return Command(
            update={"messages": [ToolMessage(f"Error: {exc}", tool_call_id=tool_call_id)]},
        )

    exported_count, exported_dir = _export_presented_files_to_local(runtime, normalized_paths)
    export_msg = f"; exported {exported_count} file(s) to {exported_dir}" if exported_count > 0 and exported_dir else ""

    # The merge_artifacts reducer will handle merging and deduplication.
    return Command(
        update={
            "artifacts": normalized_paths,
            "messages": [ToolMessage(f"Successfully presented files{export_msg}", tool_call_id=tool_call_id)],
        },
    )
