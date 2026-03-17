import base64
import csv
import json
import logging
import mimetypes
from pathlib import Path
from typing import Annotated, Any

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.config import get_config
from langgraph.types import Command
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState
from src.config import get_app_config
from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from src.config.scientific_vision_config import get_scientific_vision_config
from src.models import create_chat_model
from src.scientific_vision.cross_modal_consistency import (
    build_claim_table_rows,
    build_consistency_audit,
    consistency_signature,
    merge_vision_recheck,
)

logger = logging.getLogger(__name__)

OUTPUTS_VIRTUAL_PREFIX = "/mnt/user-data/outputs"


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


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def _extract_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        if len(lines) >= 3 and lines[-1].strip() == "```":
            raw = "\n".join(lines[1:-1]).strip()
        else:
            raw = "\n".join(lines[1:]).strip()
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {"raw": raw}
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                payload = json.loads(raw[start : end + 1])
                return payload if isinstance(payload, dict) else {"raw": raw}
            except Exception:
                pass
        return {"raw": raw}


def _collect_report_payloads(*, thread_id: str, index_path: str | None, report_paths: list[str] | None) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    requested_paths: list[str] = []
    if isinstance(index_path, str) and index_path.strip():
        normalized_index = _normalize_virtual_path(index_path)
        index_physical = get_paths().resolve_virtual_path(thread_id, normalized_index)
        index_payload = _read_json(index_physical)
        reports = index_payload.get("reports")
        if isinstance(reports, list):
            for item in reports:
                if isinstance(item, dict) and isinstance(item.get("report_path"), str):
                    requested_paths.append(item["report_path"])

    if isinstance(report_paths, list):
        for p in report_paths:
            if isinstance(p, str) and p.strip():
                requested_paths.append(p)

    dedup_requested: list[str] = []
    seen: set[str] = set()
    for p in requested_paths:
        try:
            n = _normalize_virtual_path(p)
        except Exception:
            continue
        if n in seen:
            continue
        seen.add(n)
        dedup_requested.append(n)

    payloads: list[dict[str, Any]] = []
    image_paths: list[str] = []
    for vp in dedup_requested:
        try:
            physical = get_paths().resolve_virtual_path(thread_id, vp)
            payload = _read_json(physical)
            payloads.append(payload)
            image = payload.get("image")
            if isinstance(image, dict) and isinstance(image.get("image_path"), str):
                image_paths.append(image["image_path"])
        except Exception as exc:
            logger.warning("Failed to load report artifact %s: %s", vp, exc)

    return payloads, dedup_requested, image_paths


def _collect_analysis_payloads(*, thread_id: str, analysis_paths: list[str] | None) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(analysis_paths, list):
        return [], []
    dedup_paths: list[str] = []
    seen: set[str] = set()
    for p in analysis_paths:
        if not isinstance(p, str) or not p.strip():
            continue
        try:
            n = _normalize_virtual_path(p)
        except Exception:
            continue
        if n in seen:
            continue
        seen.add(n)
        dedup_paths.append(n)

    payloads: list[dict[str, Any]] = []
    for vp in dedup_paths:
        try:
            physical = get_paths().resolve_virtual_path(thread_id, vp)
            payloads.append(_read_json(physical))
        except Exception as exc:
            logger.warning("Failed to load analysis artifact %s: %s", vp, exc)
    return payloads, dedup_paths


def _run_vision_recheck(*, thread_id: str, claim_rows: list[dict[str, Any]], image_paths: list[str]) -> dict[str, dict[str, Any]]:
    if not claim_rows or not image_paths:
        return {}

    cfg = get_scientific_vision_config()
    app_cfg = get_app_config()
    model_name = cfg.model_name or (app_cfg.models[0].name if app_cfg.models else None)
    if not model_name:
        return {}
    model_cfg = app_cfg.get_model_config(model_name)
    if model_cfg is None or not model_cfg.supports_vision:
        return {}

    max_images = int(getattr(cfg, "max_images", 4))
    blocks: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "You are a strict scientific cross-modal consistency auditor.\n"
                "Given claims from generated text and the original figures, verify each claim.\n"
                "Return JSON ONLY in this schema:\n"
                "{\n"
                '  "checks":[\n'
                '    {"claim_id":"C1","verdict":"supported|contradicted|uncertain","reason":"...","confidence":0.0,"image_path":"..."}\n'
                "  ]\n"
                "}\n"
                "Claims:\n"
                f"{json.dumps([{'claim_id': c.get('id'), 'text': c.get('text')} for c in claim_rows], ensure_ascii=False, indent=2)}"
            ),
        }
    ]

    used = 0
    for image_path in image_paths:
        if used >= max_images:
            break
        try:
            normalized = _normalize_virtual_path(image_path)
            physical = get_paths().resolve_virtual_path(thread_id, normalized)
            img_bytes = physical.read_bytes()
            mime_type, _ = mimetypes.guess_type(str(physical))
            mime_type = mime_type or "image/png"
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            blocks.append({"type": "text", "text": f"- image_path: {normalized}"})
            blocks.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}})
            used += 1
        except Exception:
            continue

    if used == 0:
        return {}

    try:
        model = create_chat_model(name=model_name, thinking_enabled=False)
        response = model.invoke([HumanMessage(content=blocks)])
        payload = _extract_json(str(response.content or ""))
    except Exception as exc:
        logger.warning("Vision recheck failed: %s", exc)
        return {}

    checks = payload.get("checks")
    if not isinstance(checks, list):
        return {}

    out: dict[str, dict[str, Any]] = {}
    for item in checks:
        if not isinstance(item, dict):
            continue
        cid = item.get("claim_id")
        verdict = item.get("verdict")
        if not isinstance(cid, str) or not cid:
            continue
        if verdict not in {"supported", "contradicted", "uncertain"}:
            verdict = "uncertain"
        out[cid] = {
            "verdict": verdict,
            "reason": item.get("reason"),
            "confidence": item.get("confidence"),
            "image_path": item.get("image_path"),
            "recheck_model": model_name,
        }
    return out


def _virtual_outputs_path(relative: str) -> str:
    rel = Path(relative).as_posix().lstrip("/")
    return f"{OUTPUTS_VIRTUAL_PREFIX}/{rel}"


@tool("audit_cross_modal_consistency", parse_docstring=True)
def cross_modal_consistency_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    narrative_text: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    index_path: str | None = None,
    report_paths: list[str] | None = None,
    analysis_paths: list[str] | None = None,
    run_vision_recheck: bool = True,
    max_claims: int = 25,
) -> Command:
    """Audit whether generated narrative claims are consistent with image/CSV evidence.

    This tool performs claim-level "text -> data" reverse verification:
    1) Extracts claim-like statements from `narrative_text`
    2) Matches each claim against ImageReport artifacts and/or raw-data analysis artifacts
    3) Optionally asks a vision model to re-check claims on original figures
    4) Writes an audit artifact (JSON + CSV) under `/mnt/user-data/outputs/`

    Args:
        narrative_text: The generated scientific narrative to be audited.
        index_path: Optional ImageReport index artifact path (`/mnt/user-data/outputs/.../index-*.json`).
        report_paths: Optional list of per-image report paths (`/mnt/user-data/outputs/.../report-*.json`).
        analysis_paths: Optional list of raw-data analysis JSON paths (e.g. analyze_fcs/analyze_embedding_csv outputs).
        run_vision_recheck: If true, run a second-pass visual re-check using a vision model.
        max_claims: Maximum claims to extract from narrative text.
    """
    thread_id = _resolve_thread_id(runtime)
    if not thread_id:
        return Command(update={"messages": [ToolMessage("Error: thread_id is not available in runtime context", tool_call_id=tool_call_id)]})
    if not isinstance(narrative_text, str) or not narrative_text.strip():
        return Command(update={"messages": [ToolMessage("Error: narrative_text must be non-empty", tool_call_id=tool_call_id)]})

    try:
        report_payloads, resolved_report_paths, image_paths = _collect_report_payloads(
            thread_id=thread_id,
            index_path=index_path,
            report_paths=report_paths,
        )
    except Exception as exc:
        return Command(update={"messages": [ToolMessage(f"Error: failed to load report artifacts: {exc}", tool_call_id=tool_call_id)]})

    analysis_payloads, resolved_analysis_paths = _collect_analysis_payloads(thread_id=thread_id, analysis_paths=analysis_paths)
    if not report_payloads and not analysis_payloads:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "Error: No usable sources. Provide `index_path` / `report_paths` and/or `analysis_paths`.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    try:
        audit_payload = build_consistency_audit(
            narrative_text=narrative_text,
            report_payloads=report_payloads,
            analysis_payloads=analysis_payloads,
            report_paths=resolved_report_paths,
            analysis_paths=resolved_analysis_paths,
            max_claims=max(1, int(max_claims)),
        )
    except Exception as exc:
        logger.exception("audit_cross_modal_consistency failed: %s", exc)
        return Command(update={"messages": [ToolMessage(f"Error: consistency audit failed: {exc}", tool_call_id=tool_call_id)]})

    if run_vision_recheck:
        try:
            vision_checks = _run_vision_recheck(
                thread_id=thread_id,
                claim_rows=[c for c in audit_payload.get("claims", []) if isinstance(c, dict)],
                image_paths=image_paths,
            )
            if vision_checks:
                audit_payload = merge_vision_recheck(audit_payload=audit_payload, vision_checks=vision_checks)
        except Exception:
            logger.exception("Vision recheck merge failed.")

    signature = consistency_signature(audit_payload)
    outputs_dir = get_paths().sandbox_outputs_dir(thread_id)
    outputs_dir.mkdir(parents=True, exist_ok=True)
    rel_base = Path("scientific-vision/cross-modal-consistency") / f"audit-{signature[:12]}"
    json_rel = rel_base / "audit.json"
    csv_rel = rel_base / "claims.csv"
    json_physical = outputs_dir / json_rel
    csv_physical = outputs_dir / csv_rel
    json_physical.parent.mkdir(parents=True, exist_ok=True)
    csv_physical.parent.mkdir(parents=True, exist_ok=True)

    json_physical.write_text(json.dumps(audit_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = build_claim_table_rows(audit_payload)
    with open(csv_physical, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                "claim_type",
                "verdict",
                "entailment",
                "confidence",
                "best_support_score",
                "numeric_matched",
                "vision_verdict",
                "uncertainty_score",
                "provenance_count",
                "text",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    artifacts = [
        _virtual_outputs_path(json_rel.as_posix()),
        _virtual_outputs_path(csv_rel.as_posix()),
    ]
    summary = audit_payload.get("summary") if isinstance(audit_payload.get("summary"), dict) else {}
    msg = (
        "audit_cross_modal_consistency completed: "
        f"claims={summary.get('claims_total', 0)}, supported={summary.get('supported', 0)}, "
        f"partial={summary.get('partially_supported', 0)}, unsupported={summary.get('unsupported', 0)}, contradicted={summary.get('contradicted', 0)}."
    )
    return Command(update={"artifacts": artifacts, "messages": [ToolMessage(msg, tool_call_id=tool_call_id)]})

