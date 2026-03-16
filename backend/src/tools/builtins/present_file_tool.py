import logging
from pathlib import Path
from typing import Annotated

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState
from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from src.sandbox.sandbox_provider import get_sandbox_provider
from src.utils.runtime import get_thread_id

logger = logging.getLogger(__name__)

OUTPUTS_VIRTUAL_PREFIX = f"{VIRTUAL_PATH_PREFIX}/outputs"


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

    thread_id = get_thread_id(runtime)
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


def _sync_artifact_to_storage(thread_id: str, virtual_path: str) -> None:
    """Sync an artifact file from the sandbox to persistent storage (R2/local).

    For non-local sandboxes (E2B, Docker), this reads the file from the sandbox
    and writes it to persistent storage so the artifacts router can serve it.
    """
    try:
        sandbox_state = None
        provider = get_sandbox_provider()

        # Get sandbox for this thread
        # We need to find the sandbox_id — check common patterns
        sandbox = None
        # Try to get sandbox from the provider's thread mapping
        if hasattr(provider, "_thread_sandboxes"):
            sandbox_id = provider._thread_sandboxes.get(thread_id)
            if sandbox_id:
                sandbox = provider.get(sandbox_id)

        if sandbox is None:
            return

        # Only sync for non-local sandboxes
        if sandbox.id == "local":
            return

        # Read file from sandbox
        data = sandbox.read_file(virtual_path)
        if not data or data.startswith("Error:"):
            logger.warning(f"Could not read artifact from sandbox: {virtual_path}")
            return

        # Write to configured durable outputs backend
        from src.storage import get_thread_file_backend

        outputs_backend = get_thread_file_backend("outputs")
        outputs_backend.put_virtual_file(thread_id, virtual_path, data.encode("utf-8") if isinstance(data, str) else data)
        logger.info("Synced artifact to outputs backend: %s", virtual_path)

    except Exception as e:
        logger.warning(f"Failed to sync artifact to storage: {e}")


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

    # Sync artifacts from sandbox to persistent storage
    thread_id = get_thread_id(runtime) if runtime else None
    if thread_id:
        for vpath in normalized_paths:
            _sync_artifact_to_storage(thread_id, vpath)

    # The merge_artifacts reducer will handle merging and deduplication
    return Command(
        update={
            "artifacts": normalized_paths,
            "messages": [ToolMessage("Successfully presented files", tool_call_id=tool_call_id)],
        },
    )
