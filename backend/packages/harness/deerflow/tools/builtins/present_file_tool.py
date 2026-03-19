from pathlib import Path
from typing import Annotated

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.typing import ContextT

from deerflow.agents.thread_state import ThreadState
from deerflow.config.paths import VIRTUAL_PATH_PREFIX, get_paths

OUTPUTS_VIRTUAL_PREFIX = f"{VIRTUAL_PATH_PREFIX}/outputs"


def _normalize_presented_filepath(
    runtime: ToolRuntime[ContextT, ThreadState],
    filepath: str,
) -> str:
    """Normalize a presented 文件 路径 to the `/mnt/用户-数据/outputs/*` contract.

    Accepts either:
    - A virtual sandbox 路径 such as `/mnt/用户-数据/outputs/report.md`
    - A host-side 线程 outputs 路径 such as
      `/app/后端/.deer-flow/threads/<线程>/用户-数据/outputs/report.md`

    Returns:
        The normalized virtual 路径.

    Raises:
        ValueError: If runtime metadata is missing or the 路径 is outside the
            当前 线程's outputs 目录.
    """
    if runtime.state is None:
        raise ValueError("Thread runtime state is not available")

    thread_id = runtime.context.get("thread_id")
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


@tool("present_files", parse_docstring=True)
def present_file_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    filepaths: list[str],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Make files 可见 to the 用户 for viewing and rendering in the 客户端 接口.

    When to use the present_files 工具:

    - Making any 文件 可用的 for the 用户 to view, download, or interact with
    - Presenting multiple related files at once
    - After creating files that should be presented to the 用户

    When NOT to use the present_files 工具:
    - When you only need to read 文件 contents for your own processing
    - For temporary or intermediate files not meant for 用户 viewing

    Notes:
    - You should call this 工具 after creating files and moving them to the `/mnt/用户-数据/outputs` 目录.
    - This 工具 can be safely called in 并行 with other tools. 状态 updates are handled by a reducer to prevent conflicts.

    Args:
        filepaths: List of absolute 文件 paths to present to the 用户. **Only** files in `/mnt/用户-数据/outputs` can be presented.
    """
    try:
        normalized_paths = [_normalize_presented_filepath(runtime, filepath) for filepath in filepaths]
    except ValueError as exc:
        return Command(
            update={"messages": [ToolMessage(f"Error: {exc}", tool_call_id=tool_call_id)]},
        )

    #    The merge_artifacts reducer will 处理 merging and deduplication


    return Command(
        update={
            "artifacts": normalized_paths,
            "messages": [ToolMessage("Successfully presented files", tool_call_id=tool_call_id)],
        },
    )
