import logging
from pathlib import Path
from typing import Annotated, Any

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.config import get_config
from langgraph.types import Command
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState
from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from src.scientific_vision.raw_data.fcs_analysis import analyze_fcs_file

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


@tool("analyze_fcs", parse_docstring=True)
def analyze_fcs_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    fcs_path: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    gates: list[dict[str, Any]] | None = None,
    preprocess: bool = False,
    apply_compensation: bool = False,
    max_events: int | None = 200_000,
) -> Command:
    """Analyze a flow cytometry FCS file (raw data) and generate audit artifacts.

    This tool upgrades “FACS plot understanding” from image-approximation to **raw, computable** analysis.
    It reads the FCS file, computes per-channel summary statistics, and (optionally) applies a simple,
    reproducible gating specification to compute population fractions and a small threshold-sensitivity scan.

    Outputs are written under `/mnt/user-data/outputs/scientific-vision/raw-data/fcs/` and added to `artifacts`.

    Args:
        fcs_path: Virtual path to an FCS file under `/mnt/user-data/...` (typically `/mnt/user-data/uploads/*.fcs`).
        gates: Optional list of gate specs (dict). Supported gate types include "threshold" and "rect2d".
        preprocess: If true, FlowIO applies gain/log/time scaling per FCS metadata before analysis.
        apply_compensation: If true, attempts to apply spillover compensation from FCS TEXT segment (when available and invertible).
        max_events: Max number of events to analyze (deterministic prefix). The reported event_count is still included.
    """
    thread_id = _resolve_thread_id(runtime)
    if not thread_id:
        return Command(update={"messages": [ToolMessage("Error: thread_id is not available in runtime context", tool_call_id=tool_call_id)]})

    try:
        fcs_path = _normalize_virtual_path(fcs_path)
    except Exception as exc:
        return Command(update={"messages": [ToolMessage(f"Error: {exc}", tool_call_id=tool_call_id)]})

    try:
        fcs_physical = get_paths().resolve_virtual_path(thread_id, fcs_path)
    except Exception as exc:
        return Command(update={"messages": [ToolMessage(f"Error: cannot resolve path: {exc}", tool_call_id=tool_call_id)]})

    if not fcs_physical.exists() or not fcs_physical.is_file():
        return Command(update={"messages": [ToolMessage(f"Error: file not found: {fcs_path}", tool_call_id=tool_call_id)]})

    outputs_dir = _get_outputs_dir(runtime, thread_id)
    try:
        payload, artifacts = analyze_fcs_file(
            fcs_path=fcs_physical,
            outputs_dir=outputs_dir,
            gates=gates,
            preprocess=preprocess,
            apply_compensation=apply_compensation,
            max_events=max_events,
        )
    except Exception as exc:
        logger.exception("analyze_fcs failed (thread_id=%s, fcs_path=%s): %s", thread_id, fcs_path, exc)
        return Command(update={"messages": [ToolMessage(f"Error: analyze_fcs failed: {exc}", tool_call_id=tool_call_id)]})

    gate_count = len(payload.get("gates") or [])
    msg = f"analyze_fcs completed: {gate_count} gate(s), artifacts={len(artifacts)}. fcs_sha256={payload.get('input', {}).get('fcs_sha256')}"
    return Command(update={"artifacts": artifacts, "messages": [ToolMessage(msg, tool_call_id=tool_call_id)]})

