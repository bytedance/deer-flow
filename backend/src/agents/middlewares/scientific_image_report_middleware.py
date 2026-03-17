"""Middleware for scientific image pre-analysis (ImageReport injection)."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from src.agents.thread_state import ViewedImageData
from src.config import get_app_config
from src.config.scientific_vision_config import get_scientific_vision_config
from src.models import create_chat_model
from src.scientific_vision.evidence_parsers import generate_image_evidence_artifacts

logger = logging.getLogger(__name__)

OUTPUTS_VIRTUAL_PREFIX = "/mnt/user-data/outputs"

IMAGE_REPORT_SCHEMA_VERSION = "deerflow.image_report.v1"
IMAGE_REPORT_BATCH_SCHEMA_VERSION = "deerflow.image_report.batch.v1"
IMAGE_REPORT_INDEX_SCHEMA_VERSION = "deerflow.image_report.index.v1"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_b64decode(data: str) -> bytes | None:
    try:
        return base64.b64decode(data)
    except Exception:
        return None


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _read_json_file(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _write_json_file(path: Path, payload: dict) -> None:
    _ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _virtual_outputs_path(relative: str) -> str:
    rel = Path(relative).as_posix().lstrip("/")
    return f"{OUTPUTS_VIRTUAL_PREFIX}/{rel}"


def _analysis_signature(*, report_model_name: str, prompt_hash: str) -> str:
    # Deterministic signature for audit + caching (image hash is handled separately).
    return _sha256_text(f"{IMAGE_REPORT_SCHEMA_VERSION}|{report_model_name}|{prompt_hash}")


def _image_report_paths(
    *,
    outputs_dir: Path,
    artifact_subdir: str,
    image_sha256: str,
    analysis_sig: str,
) -> tuple[Path, str, Path]:
    """Return (report_physical_path, report_virtual_path, image_index_physical_path)."""
    base = Path(artifact_subdir.strip("/"))
    rel_dir = base / "images" / f"sha256-{image_sha256}"
    report_rel = rel_dir / f"report-{analysis_sig[:12]}.json"
    index_rel = rel_dir / "index.json"
    return (
        outputs_dir / report_rel,
        _virtual_outputs_path(report_rel.as_posix()),
        outputs_dir / index_rel,
    )


def _batch_artifact_paths(*, outputs_dir: Path, artifact_subdir: str, batch_id: str) -> tuple[Path, str]:
    base = Path(artifact_subdir.strip("/"))
    rel = base / "batches" / f"batch-{batch_id[:12]}.json"
    return outputs_dir / rel, _virtual_outputs_path(rel.as_posix())


def _index_artifact_paths(*, outputs_dir: Path, artifact_subdir: str, index_id: str) -> tuple[Path, str]:
    base = Path(artifact_subdir.strip("/"))
    rel = base / "indexes" / f"index-{index_id[:12]}.json"
    return outputs_dir / rel, _virtual_outputs_path(rel.as_posix())


def _fingerprint_viewed_image(image_data: dict) -> tuple[str, int | None]:
    """Return (sha256_hex, byte_size) for a viewed image entry."""
    base64_data = image_data.get("base64", "")
    if not isinstance(base64_data, str) or not base64_data:
        return _sha256_text(str(base64_data)), None
    image_bytes = _safe_b64decode(base64_data)
    if image_bytes is None:
        return _sha256_text(base64_data), None
    return _sha256_bytes(image_bytes), len(image_bytes)


def _chunked(seq: list[Any], n: int) -> list[list[Any]]:
    if n <= 0:
        return [seq]
    return [seq[i : i + n] for i in range(0, len(seq), n)]


class ScientificImageReportMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    viewed_images: NotRequired[dict[str, ViewedImageData] | None]
    thread_data: NotRequired[dict | None]
    artifacts: NotRequired[list[str] | None]


def _strip_code_fences(text: str) -> str:
    raw = text.strip()
    if not raw.startswith("```"):
        return raw
    lines = raw.split("\n")
    # ```json\n...\n``` OR ```\n...\n```
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return "\n".join(lines[1:]).strip()


def _extract_json(text: str) -> dict:
    raw = _strip_code_fences(text)
    try:
        return json.loads(raw)
    except Exception:
        # Fallback: parse substring between first '{' and last '}'.
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = raw[start : end + 1]
            try:
                return json.loads(candidate)
            except Exception:
                pass
        return {"raw": raw, "_deerflow_warning": "invalid_json_from_scientific_vision_model"}


class ScientificImageReportMiddleware(AgentMiddleware[ScientificImageReportMiddlewareState]):
    """Generate ImageReport via a dedicated vision model and inject into main conversation.

    Trigger condition:
    - The last assistant message contains one or more `view_image` tool calls, and all tool calls are completed.

    Effect:
    - Calls the configured scientific vision model (or runtime model) with the viewed images.
    - Injects a HumanMessage containing a structured `<image_report>` JSON payload for the main model to use.
    """

    state_schema = ScientificImageReportMiddlewareState

    def __init__(self):
        super().__init__()

    def _get_last_assistant_message(self, messages: list) -> AIMessage | None:
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                return msg
        return None

    def _extract_view_image_paths(self, message: AIMessage) -> list[str]:
        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            return []

        paths: list[str] = []
        for tool_call in tool_calls:
            if tool_call.get("name") != "view_image":
                continue
            args = tool_call.get("args")
            if not isinstance(args, dict):
                continue
            image_path = args.get("image_path")
            if isinstance(image_path, str) and image_path:
                paths.append(image_path)
        return paths

    def _has_view_image_tool(self, message: AIMessage) -> bool:
        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            return False
        return any(tc.get("name") == "view_image" for tc in tool_calls)

    def _all_tools_completed(self, messages: list, assistant_msg: AIMessage) -> bool:
        tool_calls = getattr(assistant_msg, "tool_calls", None)
        if not tool_calls:
            return False

        tool_call_ids = {tc.get("id") for tc in tool_calls if tc.get("id")}
        try:
            assistant_idx = messages.index(assistant_msg)
        except ValueError:
            return False

        completed_tool_ids = set()
        for msg in messages[assistant_idx + 1 :]:
            if isinstance(msg, ToolMessage) and msg.tool_call_id:
                completed_tool_ids.add(msg.tool_call_id)
        return tool_call_ids.issubset(completed_tool_ids)

    def _already_injected_report(self, messages: list, assistant_msg: AIMessage) -> bool:
        assistant_idx = messages.index(assistant_msg)
        for msg in messages[assistant_idx + 1 :]:
            if isinstance(msg, HumanMessage):
                injected = (msg.additional_kwargs or {}).get("deerflow_injected")
                if injected == "image_report":
                    return True
                # Backward-compatible fallback
                content_str = str(msg.content)
                if "<image_report" in content_str:
                    return True
        return False

    def _resolve_runtime_model_name(self, runtime: Runtime) -> str | None:
        ctx = getattr(runtime, "context", None)
        if ctx is not None and hasattr(ctx, "get"):
            configurable = ctx.get("configurable") or {}
            if isinstance(configurable, dict):
                return configurable.get("model_name") or configurable.get("model")
        return None

    def _select_report_model_name(self, runtime: Runtime) -> str | None:
        cfg = get_scientific_vision_config()
        return cfg.model_name or self._resolve_runtime_model_name(runtime)

    def _default_prompt(self) -> str:
        return (
            "You are a scientific vision model. Given one or more scientific figures, produce a structured JSON ImageReport for audit and traceability.\n"
            "The images may include: Western Blot, t-SNE/UMAP clustering plots, FACS flow cytometry plots, astronomical spectra, microscopy, etc.\n\n"
            "Each image will be provided with BOTH:\n"
            "- image_path: a virtual path string\n"
            "- image_sha256: SHA-256 of the image bytes\n\n"
            "CRITICAL requirements:\n"
            "- Output MUST be valid JSON only (no markdown, no extra text).\n"
            "- For each image, copy back image_path and image_sha256 EXACTLY as provided.\n"
            "- Every scientific claim MUST reference evidence_ids pointing to evidence objects.\n"
            "- Evidence coordinates (if applicable) MUST be normalized to [0,1] with origin at top-left: bbox_norm=[x1,y1,x2,y2].\n"
            '- If something cannot be determined, use null or "unknown" and state why in limitations.\n'
            "- Prefer approximate quantitative descriptions (ranges/relative changes) over fabricated exact numbers.\n\n"
            "JSON schema:\n"
            "{\n"
            '  "schema_version": "deerflow.scientific_vision.batch.v1",\n'
            '  "images": [\n'
            "    {\n"
            '      "image_path": "...",\n'
            '      "image_sha256": "...",\n'
            '      "image_type": "western_blot|facs|tsne|spectrum|microscopy|other|unknown",\n'
            '      "evidence": [\n'
            '        {"id": "E1", "kind": "band|gate|peak|cluster|region|other", "description": "...", "bbox_norm": [0.0,0.0,1.0,1.0], "confidence": 0.0}\n'
            "      ],\n"
            '      "findings": [\n'
            '        {"id": "F1", "claim": "...", "evidence_ids": ["E1"], "confidence": 0.0}\n'
            "      ],\n"
            '      "quantitative_observations": [\n'
            '        {"metric": "...", "estimate": "...", "evidence_ids": ["E1"], "confidence": 0.0}\n'
            "      ],\n"
            '      "controls_and_comparisons": ["..."],\n'
            '      "anomalies_or_artifacts": ["..."],\n'
            '      "limitations": ["..."],\n'
            '      "suggested_followups": ["..."],\n'
            '      "image_confidence": 0.0\n'
            "    }\n"
            "  ],\n"
            '  "overall_conclusion": "...",\n'
            '  "overall_confidence": 0.0\n'
            "}\n"
        )

    def _build_vision_input_blocks(self, *, viewed_images: dict[str, ViewedImageData], image_paths: list[str]) -> list[dict | str]:
        cfg = get_scientific_vision_config()
        prompt = cfg.prompt_template or self._default_prompt()

        blocks: list[dict | str] = [{"type": "text", "text": prompt}]
        for p in image_paths:
            data = viewed_images.get(p)
            if not isinstance(data, dict):
                continue
            mime_type = data.get("mime_type", "unknown")
            base64_data = data.get("base64", "")
            image_bytes = _safe_b64decode(base64_data) if isinstance(base64_data, str) else None
            image_sha256 = _sha256_bytes(image_bytes) if image_bytes is not None else _sha256_text(str(base64_data))
            blocks.append(
                {
                    "type": "text",
                    "text": (f"\n- image_path: {p}\n  image_sha256: {image_sha256}\n  mime_type: {mime_type}"),
                }
            )
            if base64_data:
                blocks.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_data}"}})
        return blocks

    def _generate_report_sync(
        self,
        *,
        runtime: Runtime,
        image_paths: list[str],
        viewed_images: dict[str, ViewedImageData],
    ) -> tuple[str | None, dict | None, str | None]:
        report_model_name = self._select_report_model_name(runtime)
        if not report_model_name:
            return None, None, None

        app_config = get_app_config()
        report_model_cfg = app_config.get_model_config(report_model_name)
        if report_model_cfg is None or not report_model_cfg.supports_vision:
            logger.warning("ScientificImageReportMiddleware enabled but report model '%s' is missing or does not support vision.", report_model_name)
            return report_model_name, None, None

        model = create_chat_model(name=report_model_name, thinking_enabled=False)
        blocks = self._build_vision_input_blocks(viewed_images=viewed_images, image_paths=image_paths)
        response = model.invoke([HumanMessage(content=blocks)])
        raw = str(response.content or "")
        report = _extract_json(raw)
        return report_model_name, report, raw

    async def _generate_report_async(
        self,
        *,
        runtime: Runtime,
        image_paths: list[str],
        viewed_images: dict[str, ViewedImageData],
    ) -> tuple[str | None, dict | None, str | None]:
        report_model_name = self._select_report_model_name(runtime)
        if not report_model_name:
            return None, None, None

        app_config = get_app_config()
        report_model_cfg = app_config.get_model_config(report_model_name)
        if report_model_cfg is None or not report_model_cfg.supports_vision:
            logger.warning("ScientificImageReportMiddleware enabled but report model '%s' is missing or does not support vision.", report_model_name)
            return report_model_name, None, None

        model = create_chat_model(name=report_model_name, thinking_enabled=False)
        blocks = self._build_vision_input_blocks(viewed_images=viewed_images, image_paths=image_paths)
        response = await model.ainvoke([HumanMessage(content=blocks)])
        raw = str(response.content or "")
        report = _extract_json(raw)
        return report_model_name, report, raw

    def _inject_report_message(self, *, state: ScientificImageReportMiddlewareState, runtime: Runtime, use_async: bool = False):
        cfg = get_scientific_vision_config()
        if not cfg.enabled:
            return None

        messages = state.get("messages", [])
        if not messages:
            return None

        last_assistant = self._get_last_assistant_message(messages)
        if last_assistant is None:
            return None
        if not self._has_view_image_tool(last_assistant):
            return None
        if not self._all_tools_completed(messages, last_assistant):
            return None
        if self._already_injected_report(messages, last_assistant):
            return None

        viewed_images = state.get("viewed_images") or {}
        if not isinstance(viewed_images, dict) or not viewed_images:
            return None

        image_paths = self._extract_view_image_paths(last_assistant)
        if not image_paths:
            return None

        # Filter to those present in viewed_images and cap count
        image_paths = [p for p in image_paths if p in viewed_images]
        if not image_paths:
            return None
        image_paths = image_paths[: cfg.max_images]

        # Generate report (sync/async decided by caller)
        return (image_paths, viewed_images)

    def _get_outputs_dir(self, state: ScientificImageReportMiddlewareState) -> Path | None:
        thread_data = state.get("thread_data")
        if isinstance(thread_data, dict):
            outputs_path = thread_data.get("outputs_path")
            if isinstance(outputs_path, str) and outputs_path:
                return Path(outputs_path)
        return None

    def _format_report_message(
        self,
        *,
        report_model_name: str,
        inject_mode: str,
        index_virtual_path: str | None,
        payload: dict,
        image_paths: list[str],
        report_paths: list[str],
        analysis_signature: str,
        prompt_hash: str,
    ) -> HumanMessage:
        json_text = json.dumps(payload, ensure_ascii=False, indent=2)
        index_attr = index_virtual_path or ""
        content = (
            f'<image_report model="{report_model_name}" mode="{inject_mode}" index_path="{index_attr}">\n'
            "```json\n"
            f"{json_text}\n"
            "```\n"
            "</image_report>\n\n"
            "Use the ImageReport index above as primary visual evidence. "
            "If you need full details, use `read_file` to open the referenced report_path(s) under `/mnt/user-data/outputs`. "
            "If `evidence_artifacts` are present, prefer them for reproducible quantification (JSON/CSV) and open ROI overlay PNGs for audit."
            "\n\n"
            "Audit chains you can use (prefer raw-data when available):\n"
            "- Image-only audit: run `extract_image_evidence` using `index_path` (or a per-image report_path) to generate evidence tables (JSON/CSV) + ROI overlay PNGs.\n"
            "- Raw-data audit: upload original data and run:\n"
            "  - `analyze_fcs` for FACS (FCS raw events, compensation, gates, sensitivity)\n"
            "  - `analyze_embedding_csv` for t-SNE/UMAP (separation + batch mixing)\n"
            "  - `analyze_spectrum_csv` for spectra (peaks + AUC + SNR)\n"
            "  - `analyze_densitometry_csv` for blot quant tables (aggregation + normalization)\n"
            "- Cross-modal consistency: run `audit_cross_modal_consistency` with your drafted conclusion text + index/report/analysis paths before finalizing claims.\n"
            "- Reproducible figure generation: run `generate_reproducible_figure` from analysis JSON to export plotting code + publication-ready SVG/PDF.\n"
            "- Dedicated auditors (subagents):\n"
            '  - task(..., subagent_type="data-scientist"|"facs-auditor"|"blot-auditor"|"tsne-auditor"|"spectrum-auditor")\n'
        )
        return HumanMessage(
            content=content,
            additional_kwargs={
                "deerflow_injected": "image_report",
                "image_paths": image_paths,
                "report_paths": report_paths,
                "analysis_signature": analysis_signature,
                "prompt_hash": prompt_hash,
                "report_model": report_model_name,
            },
        )

    @override
    def before_model(self, state: ScientificImageReportMiddlewareState, runtime: Runtime) -> dict | None:
        prepared = self._inject_report_message(state=state, runtime=runtime, use_async=False)
        if prepared is None:
            return None

        cfg = get_scientific_vision_config()
        image_paths, viewed_images = prepared
        outputs_dir = self._get_outputs_dir(state)
        if outputs_dir is not None:
            _ensure_dir(outputs_dir)

        prompt_text = cfg.prompt_template or self._default_prompt()
        prompt_hash = _sha256_text(prompt_text)

        selected_model_name = self._select_report_model_name(runtime) or "unknown"
        analysis_sig = _analysis_signature(report_model_name=selected_model_name, prompt_hash=prompt_hash)

        artifacts: list[str] = []
        batch_artifacts: list[str] = []

        # Prepare per-image records and load cache
        records: list[dict[str, Any]] = []
        for p in image_paths:
            data = viewed_images.get(p)
            if not isinstance(data, dict):
                continue
            mime_type = data.get("mime_type", "unknown")
            image_sha256, byte_size = _fingerprint_viewed_image(data)

            report_physical: Path | None = None
            report_virtual: str | None = None
            image_index_physical: Path | None = None
            cached_report: dict | None = None

            if outputs_dir is not None:
                report_physical, report_virtual, image_index_physical = _image_report_paths(
                    outputs_dir=outputs_dir,
                    artifact_subdir=cfg.artifact_subdir,
                    image_sha256=image_sha256,
                    analysis_sig=analysis_sig,
                )
                if cfg.cache_enabled and report_physical.is_file():
                    cached_report = _read_json_file(report_physical)
                if report_virtual:
                    artifacts.append(report_virtual)

            records.append(
                {
                    "image_path": p,
                    "mime_type": mime_type,
                    "image_sha256": image_sha256,
                    "byte_size": byte_size,
                    "report_physical": report_physical,
                    "report_virtual": report_virtual,
                    "image_index_physical": image_index_physical,
                    "report_payload": cached_report,
                }
            )

        if not records:
            return None

        missing = [r for r in records if r.get("report_payload") is None]

        # Generate reports for missing images (in chunks)
        if missing:
            for chunk in _chunked(missing, cfg.max_images):
                chunk_paths = [r["image_path"] for r in chunk]
                chunk_hashes = [r["image_sha256"] for r in chunk]
                batch_id = _sha256_text("|".join(chunk_hashes) + "|" + analysis_sig)

                report_model_name: str | None = None
                batch_report: dict | None = None
                raw: str | None = None
                try:
                    report_model_name, batch_report, raw = self._generate_report_sync(runtime=runtime, image_paths=chunk_paths, viewed_images=viewed_images)
                except Exception as exc:
                    logger.exception("ScientificImageReportMiddleware failed to generate ImageReport batch: %s", exc)
                    report_model_name, batch_report, raw = None, None, None

                effective_model = report_model_name or selected_model_name

                # Write batch artifact for audit
                batch_virtual: str | None = None
                if outputs_dir is not None and cfg.write_batch_artifact:
                    batch_physical, batch_virtual = _batch_artifact_paths(outputs_dir=outputs_dir, artifact_subdir=cfg.artifact_subdir, batch_id=batch_id)
                    batch_payload: dict[str, Any] = {
                        "schema_version": IMAGE_REPORT_BATCH_SCHEMA_VERSION,
                        "batch_id": batch_id,
                        "created_at": _now_iso(),
                        "analysis_signature": analysis_sig,
                        "prompt_hash": prompt_hash,
                        "report_model": effective_model,
                        "image_paths": chunk_paths,
                        "image_sha256s": chunk_hashes,
                        "parsed_output": batch_report if isinstance(batch_report, dict) else {"_deerflow_warning": "no_report_generated"},
                    }
                    if cfg.include_raw_model_output_in_batch:
                        batch_payload["raw_model_output"] = raw or ""
                    _write_json_file(batch_physical, batch_payload)
                    artifacts.append(batch_virtual)
                    batch_artifacts.append(batch_virtual)

                # Map model outputs to images
                image_items: list[dict] = []
                if isinstance(batch_report, dict):
                    imgs = batch_report.get("images")
                    if isinstance(imgs, list):
                        image_items = [i for i in imgs if isinstance(i, dict)]

                by_sha = {str(i.get("image_sha256")): i for i in image_items if isinstance(i.get("image_sha256"), str) and i.get("image_sha256")}
                by_path = {str(i.get("image_path")): i for i in image_items if isinstance(i.get("image_path"), str) and i.get("image_path")}

                for r in chunk:
                    model_item = by_sha.get(r["image_sha256"]) or by_path.get(r["image_path"])
                    per_image_payload: dict[str, Any] = {
                        "schema_version": IMAGE_REPORT_SCHEMA_VERSION,
                        "generated_at": _now_iso(),
                        "analysis_signature": analysis_sig,
                        "prompt_hash": prompt_hash,
                        "report_model": effective_model,
                        "batch_id": batch_id,
                        "batch_artifact": batch_virtual,
                        "image": {
                            "image_path": r["image_path"],
                            "image_sha256": r["image_sha256"],
                            "mime_type": r["mime_type"],
                            "byte_size": r["byte_size"],
                        },
                        "report": model_item or {"_deerflow_warning": "image_item_missing_in_batch_output"},
                        "overall": {
                            "overall_conclusion": (batch_report or {}).get("overall_conclusion") if isinstance(batch_report, dict) else None,
                            "overall_confidence": (batch_report or {}).get("overall_confidence") if isinstance(batch_report, dict) else None,
                        },
                    }

                    r["report_payload"] = per_image_payload

                    # Write per-image report artifact + per-image index
                    report_physical = r.get("report_physical")
                    image_index_physical = r.get("image_index_physical")
                    if outputs_dir is not None and isinstance(report_physical, Path):
                        _write_json_file(report_physical, per_image_payload)
                    if outputs_dir is not None and isinstance(image_index_physical, Path):
                        index_payload = _read_json_file(image_index_physical) or {"image_sha256": r["image_sha256"], "reports": []}
                        if isinstance(index_payload.get("reports"), list):
                            entry = {
                                "analysis_signature": analysis_sig,
                                "report_model": effective_model,
                                "prompt_hash": prompt_hash,
                                "generated_at": per_image_payload["generated_at"],
                                "report_path": r.get("report_virtual"),
                                "batch_id": batch_id,
                                "batch_artifact": batch_virtual,
                            }
                            if entry not in index_payload["reports"]:
                                index_payload["reports"].append(entry)
                        _write_json_file(image_index_physical, index_payload)

        # Build injection index payload
        report_paths: list[str] = []
        report_summaries: list[dict[str, Any]] = []
        evidence_enabled = bool(getattr(cfg, "evidence_enabled", False))
        evidence_parsers = getattr(cfg, "evidence_parsers", None)
        enabled_parsers = evidence_parsers if isinstance(evidence_parsers, list) and evidence_parsers else None
        evidence_write_csv = bool(getattr(cfg, "evidence_write_csv", True))
        evidence_write_overlay = bool(getattr(cfg, "evidence_write_overlay", True))
        for r in records:
            report_virtual = r.get("report_virtual") or ""
            report_paths.append(report_virtual)
            payload = r.get("report_payload") if isinstance(r.get("report_payload"), dict) else {}
            model_report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
            evidence_ids: list[str] = []
            ev = model_report.get("evidence")
            if isinstance(ev, list):
                for item in ev:
                    if isinstance(item, dict) and isinstance(item.get("id"), str):
                        evidence_ids.append(item["id"])
            top_findings: list[str] = []
            findings = model_report.get("findings")
            if isinstance(findings, list):
                for f in findings:
                    if isinstance(f, dict) and isinstance(f.get("claim"), str):
                        top_findings.append(f["claim"])
            evidence_artifacts: dict[str, str] | None = None
            derived_summary: dict[str, Any] | None = None
            if evidence_enabled and outputs_dir is not None and report_virtual and isinstance(model_report, dict):
                base64_data: str | None = None
                base = Path(cfg.artifact_subdir.strip("/")) / "images" / f"sha256-{r['image_sha256']}"
                stem = f"{analysis_sig[:12]}"
                evidence_rel_json = base / f"evidence-{stem}.json"
                evidence_rel_csv = base / f"evidence-{stem}.csv"
                overlay_rel = base / f"overlay-{stem}.png"
                evidence_phys = outputs_dir / evidence_rel_json
                csv_phys = outputs_dir / evidence_rel_csv
                overlay_phys = outputs_dir / overlay_rel
                if evidence_phys.is_file():
                    evidence_artifacts = {"json": _virtual_outputs_path(evidence_rel_json.as_posix())}
                    artifacts.append(evidence_artifacts["json"])
                    if csv_phys.is_file():
                        evidence_artifacts["csv"] = _virtual_outputs_path(evidence_rel_csv.as_posix())
                        artifacts.append(evidence_artifacts["csv"])
                    if overlay_phys.is_file():
                        evidence_artifacts["overlay"] = _virtual_outputs_path(overlay_rel.as_posix())
                        artifacts.append(evidence_artifacts["overlay"])
                    loaded = _read_json_file(evidence_phys)
                    if isinstance(loaded, dict) and isinstance(loaded.get("summary"), dict):
                        derived_summary = loaded.get("summary")
                else:
                    viewed = viewed_images.get(r["image_path"])
                    base64_data = viewed.get("base64") if isinstance(viewed, dict) else None
                    if not (isinstance(base64_data, str) and base64_data):
                        base64_data = None
                if isinstance(base64_data, str) and base64_data and evidence_artifacts is None:
                    try:
                        result = generate_image_evidence_artifacts(
                            thread_outputs_dir=outputs_dir,
                            artifact_subdir=cfg.artifact_subdir,
                            analysis_signature=analysis_sig,
                            report_path=report_virtual,
                            report_model=payload.get("report_model") if isinstance(payload.get("report_model"), str) else None,
                            prompt_hash=prompt_hash,
                            image_path=r["image_path"],
                            image_sha256=r["image_sha256"],
                            mime_type=r["mime_type"],
                            image_base64=base64_data,
                            report=model_report,
                            enabled_parsers=enabled_parsers,
                            write_csv=evidence_write_csv,
                            write_overlay=evidence_write_overlay,
                        )
                        if result is not None:
                            evidence_artifacts = {
                                "json": result.artifacts.evidence_json_virtual_path,
                            }
                            artifacts.append(result.artifacts.evidence_json_virtual_path)
                            if result.artifacts.evidence_csv_virtual_path:
                                evidence_artifacts["csv"] = result.artifacts.evidence_csv_virtual_path
                                artifacts.append(result.artifacts.evidence_csv_virtual_path)
                            if result.artifacts.overlay_png_virtual_path:
                                evidence_artifacts["overlay"] = result.artifacts.overlay_png_virtual_path
                                artifacts.append(result.artifacts.overlay_png_virtual_path)
                            derived_summary = result.derived_summary
                    except Exception:
                        logger.exception("Failed to generate evidence artifacts for report_path=%s", report_virtual)
            report_summaries.append(
                {
                    "image_path": r["image_path"],
                    "image_sha256": r["image_sha256"],
                    "mime_type": r["mime_type"],
                    "report_path": report_virtual,
                    "image_type": model_report.get("image_type"),
                    "top_findings": top_findings[:3],
                    "evidence_ids": evidence_ids[:20],
                    "image_confidence": model_report.get("image_confidence"),
                    "evidence_artifacts": evidence_artifacts,
                    "derived_summary": derived_summary,
                }
            )

        index_payload: dict[str, Any] = {
            "schema_version": IMAGE_REPORT_INDEX_SCHEMA_VERSION,
            "generated_at": _now_iso(),
            "analysis_signature": analysis_sig,
            "prompt_hash": prompt_hash,
            "report_model": selected_model_name,
            "batch_artifacts": batch_artifacts,
            "reports": report_summaries,
        }

        index_virtual_path: str | None = None
        if outputs_dir is not None and cfg.write_index_artifact:
            index_id = _sha256_text("|".join([r["image_sha256"] for r in records]) + "|" + analysis_sig)
            index_physical, index_virtual_path = _index_artifact_paths(outputs_dir=outputs_dir, artifact_subdir=cfg.artifact_subdir, index_id=index_id)
            _write_json_file(index_physical, index_payload)
            artifacts.append(index_virtual_path)

        injection_payload: dict[str, Any]
        if cfg.inject_mode == "full":
            injection_payload = {
                "index": index_payload,
                "reports_full": [r.get("report_payload") for r in records if isinstance(r.get("report_payload"), dict)],
            }
        else:
            injection_payload = index_payload

        msg = self._format_report_message(
            report_model_name=selected_model_name,
            inject_mode=cfg.inject_mode,
            index_virtual_path=index_virtual_path,
            payload=injection_payload,
            image_paths=[r["image_path"] for r in records],
            report_paths=[p for p in report_paths if p],
            analysis_signature=analysis_sig,
            prompt_hash=prompt_hash,
        )

        update: dict = {"messages": [msg]}
        if artifacts:
            update["artifacts"] = [a for a in artifacts if isinstance(a, str) and a.startswith(OUTPUTS_VIRTUAL_PREFIX)]
        if cfg.clear_viewed_images_after_report:
            update["viewed_images"] = {}
        return update

    @override
    async def abefore_model(self, state: ScientificImageReportMiddlewareState, runtime: Runtime) -> dict | None:
        prepared = self._inject_report_message(state=state, runtime=runtime, use_async=True)
        if prepared is None:
            return None

        cfg = get_scientific_vision_config()
        image_paths, viewed_images = prepared
        outputs_dir = self._get_outputs_dir(state)
        if outputs_dir is not None:
            _ensure_dir(outputs_dir)

        prompt_text = cfg.prompt_template or self._default_prompt()
        prompt_hash = _sha256_text(prompt_text)

        selected_model_name = self._select_report_model_name(runtime) or "unknown"
        analysis_sig = _analysis_signature(report_model_name=selected_model_name, prompt_hash=prompt_hash)

        artifacts: list[str] = []
        batch_artifacts: list[str] = []

        records: list[dict[str, Any]] = []
        for p in image_paths:
            data = viewed_images.get(p)
            if not isinstance(data, dict):
                continue
            mime_type = data.get("mime_type", "unknown")
            image_sha256, byte_size = _fingerprint_viewed_image(data)

            report_physical: Path | None = None
            report_virtual: str | None = None
            image_index_physical: Path | None = None
            cached_report: dict | None = None

            if outputs_dir is not None:
                report_physical, report_virtual, image_index_physical = _image_report_paths(
                    outputs_dir=outputs_dir,
                    artifact_subdir=cfg.artifact_subdir,
                    image_sha256=image_sha256,
                    analysis_sig=analysis_sig,
                )
                if cfg.cache_enabled and report_physical.is_file():
                    cached_report = _read_json_file(report_physical)
                if report_virtual:
                    artifacts.append(report_virtual)

            records.append(
                {
                    "image_path": p,
                    "mime_type": mime_type,
                    "image_sha256": image_sha256,
                    "byte_size": byte_size,
                    "report_physical": report_physical,
                    "report_virtual": report_virtual,
                    "image_index_physical": image_index_physical,
                    "report_payload": cached_report,
                }
            )

        if not records:
            return None

        missing = [r for r in records if r.get("report_payload") is None]

        if missing:
            for chunk in _chunked(missing, cfg.max_images):
                chunk_paths = [r["image_path"] for r in chunk]
                chunk_hashes = [r["image_sha256"] for r in chunk]
                batch_id = _sha256_text("|".join(chunk_hashes) + "|" + analysis_sig)

                report_model_name: str | None = None
                batch_report: dict | None = None
                raw: str | None = None
                try:
                    report_model_name, batch_report, raw = await self._generate_report_async(runtime=runtime, image_paths=chunk_paths, viewed_images=viewed_images)
                except Exception as exc:
                    logger.exception("ScientificImageReportMiddleware failed to generate ImageReport batch: %s", exc)
                    report_model_name, batch_report, raw = None, None, None

                effective_model = report_model_name or selected_model_name

                batch_virtual: str | None = None
                if outputs_dir is not None and cfg.write_batch_artifact:
                    batch_physical, batch_virtual = _batch_artifact_paths(outputs_dir=outputs_dir, artifact_subdir=cfg.artifact_subdir, batch_id=batch_id)
                    batch_payload: dict[str, Any] = {
                        "schema_version": IMAGE_REPORT_BATCH_SCHEMA_VERSION,
                        "batch_id": batch_id,
                        "created_at": _now_iso(),
                        "analysis_signature": analysis_sig,
                        "prompt_hash": prompt_hash,
                        "report_model": effective_model,
                        "image_paths": chunk_paths,
                        "image_sha256s": chunk_hashes,
                        "parsed_output": batch_report if isinstance(batch_report, dict) else {"_deerflow_warning": "no_report_generated"},
                    }
                    if cfg.include_raw_model_output_in_batch:
                        batch_payload["raw_model_output"] = raw or ""
                    _write_json_file(batch_physical, batch_payload)
                    artifacts.append(batch_virtual)
                    batch_artifacts.append(batch_virtual)

                image_items: list[dict] = []
                if isinstance(batch_report, dict):
                    imgs = batch_report.get("images")
                    if isinstance(imgs, list):
                        image_items = [i for i in imgs if isinstance(i, dict)]

                by_sha = {str(i.get("image_sha256")): i for i in image_items if isinstance(i.get("image_sha256"), str) and i.get("image_sha256")}
                by_path = {str(i.get("image_path")): i for i in image_items if isinstance(i.get("image_path"), str) and i.get("image_path")}

                for r in chunk:
                    model_item = by_sha.get(r["image_sha256"]) or by_path.get(r["image_path"])
                    per_image_payload: dict[str, Any] = {
                        "schema_version": IMAGE_REPORT_SCHEMA_VERSION,
                        "generated_at": _now_iso(),
                        "analysis_signature": analysis_sig,
                        "prompt_hash": prompt_hash,
                        "report_model": effective_model,
                        "batch_id": batch_id,
                        "batch_artifact": batch_virtual,
                        "image": {
                            "image_path": r["image_path"],
                            "image_sha256": r["image_sha256"],
                            "mime_type": r["mime_type"],
                            "byte_size": r["byte_size"],
                        },
                        "report": model_item or {"_deerflow_warning": "image_item_missing_in_batch_output"},
                        "overall": {
                            "overall_conclusion": (batch_report or {}).get("overall_conclusion") if isinstance(batch_report, dict) else None,
                            "overall_confidence": (batch_report or {}).get("overall_confidence") if isinstance(batch_report, dict) else None,
                        },
                    }

                    r["report_payload"] = per_image_payload

                    report_physical = r.get("report_physical")
                    image_index_physical = r.get("image_index_physical")
                    if outputs_dir is not None and isinstance(report_physical, Path):
                        _write_json_file(report_physical, per_image_payload)
                    if outputs_dir is not None and isinstance(image_index_physical, Path):
                        index_payload = _read_json_file(image_index_physical) or {"image_sha256": r["image_sha256"], "reports": []}
                        if isinstance(index_payload.get("reports"), list):
                            entry = {
                                "analysis_signature": analysis_sig,
                                "report_model": effective_model,
                                "prompt_hash": prompt_hash,
                                "generated_at": per_image_payload["generated_at"],
                                "report_path": r.get("report_virtual"),
                                "batch_id": batch_id,
                                "batch_artifact": batch_virtual,
                            }
                            if entry not in index_payload["reports"]:
                                index_payload["reports"].append(entry)
                        _write_json_file(image_index_physical, index_payload)

        report_paths: list[str] = []
        report_summaries: list[dict[str, Any]] = []
        evidence_enabled = bool(getattr(cfg, "evidence_enabled", False))
        evidence_parsers = getattr(cfg, "evidence_parsers", None)
        enabled_parsers = evidence_parsers if isinstance(evidence_parsers, list) and evidence_parsers else None
        evidence_write_csv = bool(getattr(cfg, "evidence_write_csv", True))
        evidence_write_overlay = bool(getattr(cfg, "evidence_write_overlay", True))
        for r in records:
            report_virtual = r.get("report_virtual") or ""
            report_paths.append(report_virtual)
            payload = r.get("report_payload") if isinstance(r.get("report_payload"), dict) else {}
            model_report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
            evidence_ids: list[str] = []
            ev = model_report.get("evidence")
            if isinstance(ev, list):
                for item in ev:
                    if isinstance(item, dict) and isinstance(item.get("id"), str):
                        evidence_ids.append(item["id"])
            top_findings: list[str] = []
            findings = model_report.get("findings")
            if isinstance(findings, list):
                for f in findings:
                    if isinstance(f, dict) and isinstance(f.get("claim"), str):
                        top_findings.append(f["claim"])
            evidence_artifacts: dict[str, str] | None = None
            derived_summary: dict[str, Any] | None = None
            if evidence_enabled and outputs_dir is not None and report_virtual and isinstance(model_report, dict):
                base64_data: str | None = None
                base = Path(cfg.artifact_subdir.strip("/")) / "images" / f"sha256-{r['image_sha256']}"
                stem = f"{analysis_sig[:12]}"
                evidence_rel_json = base / f"evidence-{stem}.json"
                evidence_rel_csv = base / f"evidence-{stem}.csv"
                overlay_rel = base / f"overlay-{stem}.png"
                evidence_phys = outputs_dir / evidence_rel_json
                csv_phys = outputs_dir / evidence_rel_csv
                overlay_phys = outputs_dir / overlay_rel
                if evidence_phys.is_file():
                    evidence_artifacts = {"json": _virtual_outputs_path(evidence_rel_json.as_posix())}
                    artifacts.append(evidence_artifacts["json"])
                    if csv_phys.is_file():
                        evidence_artifacts["csv"] = _virtual_outputs_path(evidence_rel_csv.as_posix())
                        artifacts.append(evidence_artifacts["csv"])
                    if overlay_phys.is_file():
                        evidence_artifacts["overlay"] = _virtual_outputs_path(overlay_rel.as_posix())
                        artifacts.append(evidence_artifacts["overlay"])
                    loaded = _read_json_file(evidence_phys)
                    if isinstance(loaded, dict) and isinstance(loaded.get("summary"), dict):
                        derived_summary = loaded.get("summary")
                else:
                    viewed = viewed_images.get(r["image_path"])
                    base64_data = viewed.get("base64") if isinstance(viewed, dict) else None
                    if not (isinstance(base64_data, str) and base64_data):
                        base64_data = None
                if isinstance(base64_data, str) and base64_data and evidence_artifacts is None:
                    try:
                        result = generate_image_evidence_artifacts(
                            thread_outputs_dir=outputs_dir,
                            artifact_subdir=cfg.artifact_subdir,
                            analysis_signature=analysis_sig,
                            report_path=report_virtual,
                            report_model=payload.get("report_model") if isinstance(payload.get("report_model"), str) else None,
                            prompt_hash=prompt_hash,
                            image_path=r["image_path"],
                            image_sha256=r["image_sha256"],
                            mime_type=r["mime_type"],
                            image_base64=base64_data,
                            report=model_report,
                            enabled_parsers=enabled_parsers,
                            write_csv=evidence_write_csv,
                            write_overlay=evidence_write_overlay,
                        )
                        if result is not None:
                            evidence_artifacts = {
                                "json": result.artifacts.evidence_json_virtual_path,
                            }
                            artifacts.append(result.artifacts.evidence_json_virtual_path)
                            if result.artifacts.evidence_csv_virtual_path:
                                evidence_artifacts["csv"] = result.artifacts.evidence_csv_virtual_path
                                artifacts.append(result.artifacts.evidence_csv_virtual_path)
                            if result.artifacts.overlay_png_virtual_path:
                                evidence_artifacts["overlay"] = result.artifacts.overlay_png_virtual_path
                                artifacts.append(result.artifacts.overlay_png_virtual_path)
                            derived_summary = result.derived_summary
                    except Exception:
                        logger.exception("Failed to generate evidence artifacts for report_path=%s", report_virtual)
            report_summaries.append(
                {
                    "image_path": r["image_path"],
                    "image_sha256": r["image_sha256"],
                    "mime_type": r["mime_type"],
                    "report_path": report_virtual,
                    "image_type": model_report.get("image_type"),
                    "top_findings": top_findings[:3],
                    "evidence_ids": evidence_ids[:20],
                    "image_confidence": model_report.get("image_confidence"),
                    "evidence_artifacts": evidence_artifacts,
                    "derived_summary": derived_summary,
                }
            )

        index_payload: dict[str, Any] = {
            "schema_version": IMAGE_REPORT_INDEX_SCHEMA_VERSION,
            "generated_at": _now_iso(),
            "analysis_signature": analysis_sig,
            "prompt_hash": prompt_hash,
            "report_model": selected_model_name,
            "batch_artifacts": batch_artifacts,
            "reports": report_summaries,
        }

        index_virtual_path: str | None = None
        if outputs_dir is not None and cfg.write_index_artifact:
            index_id = _sha256_text("|".join([r["image_sha256"] for r in records]) + "|" + analysis_sig)
            index_physical, index_virtual_path = _index_artifact_paths(outputs_dir=outputs_dir, artifact_subdir=cfg.artifact_subdir, index_id=index_id)
            _write_json_file(index_physical, index_payload)
            artifacts.append(index_virtual_path)

        injection_payload: dict[str, Any]
        if cfg.inject_mode == "full":
            injection_payload = {
                "index": index_payload,
                "reports_full": [r.get("report_payload") for r in records if isinstance(r.get("report_payload"), dict)],
            }
        else:
            injection_payload = index_payload

        msg = self._format_report_message(
            report_model_name=selected_model_name,
            inject_mode=cfg.inject_mode,
            index_virtual_path=index_virtual_path,
            payload=injection_payload,
            image_paths=[r["image_path"] for r in records],
            report_paths=[p for p in report_paths if p],
            analysis_signature=analysis_sig,
            prompt_hash=prompt_hash,
        )

        update: dict = {"messages": [msg]}
        if artifacts:
            update["artifacts"] = [a for a in artifacts if isinstance(a, str) and a.startswith(OUTPUTS_VIRTUAL_PREFIX)]
        if cfg.clear_viewed_images_after_report:
            update["viewed_images"] = {}
        return update
