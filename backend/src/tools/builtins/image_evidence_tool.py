import base64
import json
import logging
import mimetypes
from pathlib import Path
from typing import Annotated, Any

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.config import get_config
from langgraph.types import Command
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState
from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from src.config.scientific_vision_config import get_scientific_vision_config
from src.scientific_vision.evidence_parsers import generate_image_evidence_artifacts

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


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _ensure_outputs_dir(thread_id: str) -> Path:
    outputs_dir = get_paths().sandbox_outputs_dir(thread_id)
    outputs_dir.mkdir(parents=True, exist_ok=True)
    return outputs_dir


def _normalize_virtual_path(virtual_path: str) -> str:
    if not isinstance(virtual_path, str) or not virtual_path.strip():
        raise ValueError("Path must be a non-empty string")
    stripped = virtual_path.lstrip("/")
    prefix = VIRTUAL_PATH_PREFIX.lstrip("/")
    if stripped != prefix and not stripped.startswith(prefix + "/"):
        raise ValueError(f"Path must start with {VIRTUAL_PATH_PREFIX}")
    return "/" + stripped


def _extract_one(
    *,
    thread_id: str,
    outputs_dir: Path,
    report_path: str,
) -> list[str]:
    cfg = get_scientific_vision_config()
    report_path = _normalize_virtual_path(report_path)
    report_physical = get_paths().resolve_virtual_path(thread_id, report_path)
    payload = _load_json(report_physical)
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid report JSON: {report_path}")

    image_info = payload.get("image")
    if not isinstance(image_info, dict):
        raise ValueError(f"Missing image info in report: {report_path}")

    image_path = image_info.get("image_path")
    image_sha256 = image_info.get("image_sha256")
    mime_type = image_info.get("mime_type")
    if not isinstance(image_path, str) or not isinstance(image_sha256, str):
        raise ValueError(f"Missing image_path/image_sha256 in report: {report_path}")

    report = payload.get("report")
    if not isinstance(report, dict):
        raise ValueError(f"Missing report object in report: {report_path}")

    analysis_sig = payload.get("analysis_signature") if isinstance(payload.get("analysis_signature"), str) else "unknown"
    prompt_hash = payload.get("prompt_hash") if isinstance(payload.get("prompt_hash"), str) else None
    report_model = payload.get("report_model") if isinstance(payload.get("report_model"), str) else None

    image_path = _normalize_virtual_path(image_path)
    image_physical = get_paths().resolve_virtual_path(thread_id, image_path)
    img_bytes = image_physical.read_bytes()
    image_base64 = base64.b64encode(img_bytes).decode("utf-8")

    if not isinstance(mime_type, str) or not mime_type:
        mt, _ = mimetypes.guess_type(str(image_physical))
        mime_type = mt or "application/octet-stream"

    evidence_parsers = cfg.evidence_parsers if isinstance(getattr(cfg, "evidence_parsers", None), list) else None
    result = generate_image_evidence_artifacts(
        thread_outputs_dir=outputs_dir,
        artifact_subdir=cfg.artifact_subdir,
        analysis_signature=analysis_sig,
        report_path=report_path,
        report_model=report_model,
        prompt_hash=prompt_hash,
        image_path=image_path,
        image_sha256=image_sha256,
        mime_type=mime_type,
        image_base64=image_base64,
        report=report,
        enabled_parsers=evidence_parsers,
        write_csv=bool(getattr(cfg, "evidence_write_csv", True)),
        write_overlay=bool(getattr(cfg, "evidence_write_overlay", True)),
    )
    if result is None:
        return []

    artifacts = [result.artifacts.evidence_json_virtual_path]
    if result.artifacts.evidence_csv_virtual_path:
        artifacts.append(result.artifacts.evidence_csv_virtual_path)
    if result.artifacts.overlay_png_virtual_path:
        artifacts.append(result.artifacts.overlay_png_virtual_path)
    return artifacts


@tool("extract_image_evidence", parse_docstring=True)
def image_evidence_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    report_path: str | None,
    tool_call_id: Annotated[str, InjectedToolCallId],
    index_path: str | None = None,
) -> Command:
    """Generate audit-friendly evidence tables (JSON/CSV) and ROI overlay PNGs from ImageReport artifacts.

    This tool is designed to be used *after* scientific vision pre-analysis generated ImageReport artifacts.
    It reads per-image ImageReport JSON, then runs a type-specific evidence parser to produce reproducible,
    reviewable evidence tables keyed by image SHA-256.

    Args:
        report_path: Virtual path to a per-image ImageReport artifact JSON (e.g. /mnt/user-data/outputs/.../report-xxxx.json).
        index_path: Optional virtual path to an ImageReport index artifact JSON (e.g. /mnt/user-data/outputs/.../index-xxxx.json).
                   If provided, this tool will generate evidence for all report_path entries in the index.
    """
    thread_id = _resolve_thread_id(runtime)
    if not thread_id:
        return Command(update={"messages": [ToolMessage("Error: thread_id is not available in runtime context", tool_call_id=tool_call_id)]})

    outputs_dir = _ensure_outputs_dir(thread_id)

    requested: list[str] = []
    if index_path:
        try:
            index_path = _normalize_virtual_path(index_path)
            index_physical = get_paths().resolve_virtual_path(thread_id, index_path)
            index_payload = _load_json(index_physical)
            reports = index_payload.get("reports") if isinstance(index_payload, dict) else None
            if isinstance(reports, list):
                for entry in reports:
                    if isinstance(entry, dict) and isinstance(entry.get("report_path"), str):
                        requested.append(entry["report_path"])
        except Exception as exc:
            return Command(update={"messages": [ToolMessage(f"Error: failed to read index_path: {exc}", tool_call_id=tool_call_id)]})
    if report_path:
        requested.append(report_path)

    requested = [p for p in requested if isinstance(p, str) and p.strip()]
    if not requested:
        return Command(update={"messages": [ToolMessage("Error: provide report_path or index_path", tool_call_id=tool_call_id)]})

    generated: list[str] = []
    errors: list[str] = []
    for rp in requested:
        try:
            generated.extend(_extract_one(thread_id=thread_id, outputs_dir=outputs_dir, report_path=rp))
        except Exception as exc:
            logger.warning("extract_image_evidence failed for %s (thread_id=%s): %s", rp, thread_id, exc)
            errors.append(f"{rp}: {exc}")

    if not generated and errors:
        return Command(update={"messages": [ToolMessage("Error: no evidence generated.\n" + "\n".join(errors[:10]), tool_call_id=tool_call_id)]})

    msg = f"Generated evidence artifacts: {len(generated)} file(s)."
    if errors:
        msg += f" Errors: {len(errors)} (showing up to 5)\n" + "\n".join(errors[:5])

    return Command(update={"artifacts": generated, "messages": [ToolMessage(msg, tool_call_id=tool_call_id)]})

