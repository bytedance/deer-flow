import json
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
from src.scientific_vision.raw_data.figure_generation import generate_reproducible_figure_bundle

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


@tool("generate_reproducible_figure", parse_docstring=True)
def generate_reproducible_figure_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    analysis_path: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    language: str = "python",
    style_preset: str = "publication",
    figure_title: str | None = None,
    output_stem: str | None = None,
    execute_code: bool = True,
) -> Command:
    """Generate publication-ready reproducible figure code (Python/R) from analysis JSON and export SVG/PDF.

    This tool upgrades raw-data analysis into reproducible figure production:
    - Reads one analysis artifact JSON (from analyze_fcs/analyze_embedding_csv/analyze_spectrum_csv/analyze_densitometry_csv)
    - Generates plotting code (`.py` or `.R`)
    - Optionally executes the script
    - Persists vector outputs (`.svg` + `.pdf`) and metadata

    Args:
        analysis_path: Virtual path to analysis JSON under `/mnt/user-data/outputs/.../analysis*.json`.
        language: Plotting language (`python` using Matplotlib/Seaborn, or `r` using ggplot2 templates).
        style_preset: Visual style preset tag recorded in metadata.
        figure_title: Optional figure title override.
        output_stem: Optional output file stem (default based on analysis type).
        execute_code: If true, run generated script immediately.
    """
    thread_id = _resolve_thread_id(runtime)
    if not thread_id:
        return Command(update={"messages": [ToolMessage("Error: thread_id is not available in runtime context", tool_call_id=tool_call_id)]})

    try:
        analysis_path = _normalize_virtual_path(analysis_path)
        analysis_physical = get_paths().resolve_virtual_path(thread_id, analysis_path)
    except Exception as exc:
        return Command(update={"messages": [ToolMessage(f"Error: invalid analysis_path: {exc}", tool_call_id=tool_call_id)]})

    if not analysis_physical.exists() or not analysis_physical.is_file():
        return Command(update={"messages": [ToolMessage(f"Error: file not found: {analysis_path}", tool_call_id=tool_call_id)]})

    try:
        payload = json.loads(analysis_physical.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("analysis artifact must be a JSON object")
    except Exception as exc:
        return Command(update={"messages": [ToolMessage(f"Error: failed to parse analysis JSON: {exc}", tool_call_id=tool_call_id)]})

    outputs_dir = _get_outputs_dir(runtime, thread_id)
    try:
        metadata, artifacts = generate_reproducible_figure_bundle(
            analysis_payload=payload,
            analysis_virtual_path=analysis_path,
            outputs_dir=outputs_dir,
            language=language,
            style_preset=style_preset,
            figure_title=figure_title,
            output_stem=output_stem,
            execute_code=bool(execute_code),
        )
    except Exception as exc:
        logger.exception("generate_reproducible_figure failed (thread_id=%s): %s", thread_id, exc)
        return Command(update={"messages": [ToolMessage(f"Error: generate_reproducible_figure failed: {exc}", tool_call_id=tool_call_id)]})

    execution = metadata.get("execution") if isinstance(metadata.get("execution"), dict) else {}
    status = execution.get("status")
    figure_kind = metadata.get("figure_kind")
    language_used = metadata.get("language")
    signature = metadata.get("figure_signature")
    msg = (
        "generate_reproducible_figure completed: "
        f"kind={figure_kind}, language={language_used}, execution_status={status}, "
        f"artifacts={len(artifacts)}, signature={signature}."
    )
    return Command(update={"artifacts": artifacts, "messages": [ToolMessage(msg, tool_call_id=tool_call_id)]})

