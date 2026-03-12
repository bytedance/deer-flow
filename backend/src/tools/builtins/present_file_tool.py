from typing import Annotated

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState

# Common mis-path prefixes that agents use instead of /mnt/user-data/
_TMP_PATH_MAPPINGS = {
    "/tmp/outputs/": "/mnt/user-data/outputs/",
    "/tmp/workspace/": "/mnt/user-data/workspace/",
    "/tmp/uploads/": "/mnt/user-data/uploads/",
    "/tmp/outputs": "/mnt/user-data/outputs",
    "/tmp/workspace": "/mnt/user-data/workspace",
    "/tmp/uploads": "/mnt/user-data/uploads",
}


def _normalize_artifact_path(filepath: str) -> str:
    """Normalize common mis-paths (e.g. /tmp/outputs/) to /mnt/user-data/ paths."""
    for wrong, correct in _TMP_PATH_MAPPINGS.items():
        if filepath.startswith(wrong):
            return correct + filepath[len(wrong):]
    return filepath


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

    Examples:
        present_files(filepaths=["/mnt/user-data/outputs/report.pdf"])
        present_files(filepaths=["/mnt/user-data/outputs/chart.png", "/mnt/user-data/outputs/data.csv", "/mnt/user-data/outputs/analysis.md"])

    Args:
        filepaths: List of absolute file paths to present to the user. **Only** files in `/mnt/user-data/outputs` can be presented.
    """
    # Normalize common mis-paths (e.g. /tmp/outputs/) to /mnt/user-data/outputs/
    normalized = [_normalize_artifact_path(fp) for fp in filepaths]

    # The merge_artifacts reducer will handle merging and deduplication
    return Command(
        update={"artifacts": normalized, "messages": [ToolMessage("Successfully presented files", tool_call_id=tool_call_id)]},
    )
