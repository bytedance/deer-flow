import logging
from pathlib import Path
from typing import Annotated

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.config import get_config
from langgraph.types import Command
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState
from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from src.scientific_vision.raw_data.spectrum_analysis import analyze_spectrum_csv_files

logger = logging.getLogger(__name__)


def _resolve_thread_id(runtime: ToolRuntime[ContextT, ThreadState]) -> str | None:
    ctx = runtime.context
    thread_id = ctx.get("thread_id") if (ctx is not None and hasattr(ctx, "get")) else None
    if thread_id:
        return thread_id
    try:
        return get_config().get("configurable", {}).get("thread_id")
    except RuntimeError:
        return None


def _normalize_virtual_path(virtual_path: str) -> str:
    if not isinstance(virtual_path, str) or not virtual_path.strip():
        raise ValueError("Path must be a non-empty string")
    stripped = virtual_path.lstrip("/")
    prefix = VIRTUAL_PATH_PREFIX.lstrip("/")
    if stripped != prefix and not stripped.startswith(prefix + "/"):
        raise ValueError(f"Path must start with {VIRTUAL_PATH_PREFIX}")
    return "/" + stripped


def _get_outputs_dir(runtime: ToolRuntime[ContextT, ThreadState], thread_id: str) -> Path:
    thread_data = runtime.state.get("thread_data") if runtime.state else None
    if isinstance(thread_data, dict):
        outputs_path = thread_data.get("outputs_path")
        if isinstance(outputs_path, str) and outputs_path:
            p = Path(outputs_path)
            p.mkdir(parents=True, exist_ok=True)
            return p
    p = get_paths().sandbox_outputs_dir(thread_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


@tool("analyze_spectrum_csv", parse_docstring=True)
def analyze_spectrum_csv_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    csv_paths: list[str],
    tool_call_id: Annotated[str, InjectedToolCallId],
    x_col: str | None = None,
    y_col: str | None = None,
) -> Command:
    """Analyze numeric spectrum CSV(s) and generate auditable peak/AUC metrics + reproduction script.

    Outputs are written under `/mnt/user-data/outputs/scientific-vision/raw-data/spectrum/` and added to `artifacts`.

    Args:
        csv_paths: List of virtual paths to CSV files under `/mnt/user-data/...` (typically `/mnt/user-data/uploads/*.csv`).
        x_col: Optional x axis column (auto-detected if not provided).
        y_col: Optional y axis column (auto-detected if not provided).
    """
    thread_id = _resolve_thread_id(runtime)
    if not thread_id:
        return Command(update={"messages": [ToolMessage("Error: thread_id is not available in runtime context", tool_call_id=tool_call_id)]})
    if not isinstance(csv_paths, list) or not csv_paths:
        return Command(update={"messages": [ToolMessage("Error: csv_paths must be a non-empty list", tool_call_id=tool_call_id)]})

    physical_paths: list[Path] = []
    for p in csv_paths:
        try:
            vp = _normalize_virtual_path(p)
            physical = get_paths().resolve_virtual_path(thread_id, vp)
        except Exception as exc:
            return Command(update={"messages": [ToolMessage(f"Error: cannot resolve path '{p}': {exc}", tool_call_id=tool_call_id)]})
        if not physical.exists() or not physical.is_file():
            return Command(update={"messages": [ToolMessage(f"Error: file not found: {p}", tool_call_id=tool_call_id)]})
        physical_paths.append(physical)

    outputs_dir = _get_outputs_dir(runtime, thread_id)
    try:
        payload, artifacts = analyze_spectrum_csv_files(
            csv_paths=physical_paths,
            outputs_dir=outputs_dir,
            x_col=x_col,
            y_col=y_col,
        )
    except Exception as exc:
        logger.exception("analyze_spectrum_csv failed (thread_id=%s): %s", thread_id, exc)
        return Command(update={"messages": [ToolMessage(f"Error: analyze_spectrum_csv failed: {exc}", tool_call_id=tool_call_id)]})

    msg = f"analyze_spectrum_csv completed: inputs={len(payload.get('inputs') or [])}, artifacts={len(artifacts)}. signature={payload.get('analysis_signature')}"
    return Command(update={"artifacts": artifacts, "messages": [ToolMessage(msg, tool_call_id=tool_call_id)]})
