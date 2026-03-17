from __future__ import annotations

import hashlib
import json
import re
import textwrap
from pathlib import Path
from typing import Any

from PIL import Image

from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths

OUTPUTS_VIRTUAL_PREFIX = f"{VIRTUAL_PATH_PREFIX}/outputs"


def _sha256_json(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _safe_filename(name: str) -> str:
    # Keep it conservative: ASCII-ish filenames avoid cross-platform issues.
    base = name.strip().replace("\\", "/").split("/")[-1]
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    if not base:
        return "report.pdf"
    if not base.lower().endswith(".pdf"):
        base = base + ".pdf"
    return base


def _virtual_outputs_path(relative: str) -> str:
    rel = Path(relative).as_posix().lstrip("/")
    return f"{OUTPUTS_VIRTUAL_PREFIX}/{rel}"


def _resolve_virtual_path(thread_id: str, virtual_path: str) -> Path:
    return get_paths().resolve_virtual_path(thread_id, virtual_path)


def generate_image_report_pdf(
    *,
    thread_id: str,
    index_payload: dict[str, Any],
    artifact_subdir: str,
    output_filename: str | None = None,
    index_virtual_path: str | None = None,
) -> str:
    """Generate an audit-friendly PDF report from ImageReport artifacts.

    Args:
        thread_id: Thread ID.
        index_payload: The injected ImageReport index payload (schema: deerflow.image_report.index.v1).
        artifact_subdir: Subdir under `/mnt/user-data/outputs/` to store PDFs.
        output_filename: Optional output filename (stored under `{artifact_subdir}/pdfs/`).
        index_virtual_path: Optional virtual path to the index artifact for provenance display.

    Returns:
        The virtual path of the generated PDF under `/mnt/user-data/outputs/`.
    """
    outputs_dir = get_paths().sandbox_outputs_dir(thread_id)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    index_id = _sha256_json(index_payload)
    filename = _safe_filename(output_filename or f"scientific-image-report-{index_id[:12]}.pdf")
    pdf_rel = Path(artifact_subdir.strip("/")) / "pdfs" / filename
    pdf_physical = outputs_dir / pdf_rel
    pdf_virtual = _virtual_outputs_path(pdf_rel.as_posix())
    pdf_physical.parent.mkdir(parents=True, exist_ok=True)

    reports = index_payload.get("reports")
    if not isinstance(reports, list):
        raise ValueError("index_payload.reports must be a list")

    # Lazy imports (matplotlib is heavy).
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.patches import Rectangle

    def _wrap(lines: list[str], width: int = 110) -> str:
        return "\n".join(textwrap.fill(line, width=width, subsequent_indent="  ") for line in lines if line)

    with PdfPages(str(pdf_physical)) as pdf:
        # Cover page
        fig = plt.figure(figsize=(8.27, 11.69))  # A4 portrait in inches
        fig.patch.set_facecolor("white")
        ax = fig.add_axes([0, 0, 1, 1])
        ax.axis("off")

        title = "实验数据智能分析报告"
        meta_lines = [
            f"Thread: {thread_id}",
            f"Index schema: {index_payload.get('schema_version', 'unknown')}",
            f"Report model: {index_payload.get('report_model', 'unknown')}",
            f"Generated at: {index_payload.get('generated_at', '')}",
            f"Analysis signature: {index_payload.get('analysis_signature', '')}",
            f"Prompt hash: {index_payload.get('prompt_hash', '')}",
            f"Images: {len(reports)}",
        ]
        if index_virtual_path:
            meta_lines.append(f"Index artifact: {index_virtual_path}")

        ax.text(0.08, 0.92, title, fontsize=22, fontweight="bold", va="top")
        ax.text(0.08, 0.86, _wrap(meta_lines, width=120), fontsize=10, va="top")
        ax.text(
            0.08,
            0.12,
            "说明：本 PDF 由 DeerFlow 基于 ImageReport 审计 artifacts 自动生成。每条结论应以 evidence/ROI 为依据；如无证据或置信度较低，请回到原图进一步核验。",
            fontsize=9,
            va="top",
            wrap=True,
        )
        pdf.savefig(fig)
        plt.close(fig)

        # Per-image pages
        for idx, entry in enumerate(reports, start=1):
            if not isinstance(entry, dict):
                continue
            report_path = entry.get("report_path")
            if not isinstance(report_path, str) or not report_path:
                continue

            # Load per-image artifact JSON
            report_physical = _resolve_virtual_path(thread_id, report_path)
            try:
                per_image = json.loads(report_physical.read_text(encoding="utf-8"))
            except Exception:
                per_image = {}

            image_info = per_image.get("image") if isinstance(per_image, dict) else {}
            if not isinstance(image_info, dict):
                image_info = {}

            image_virtual = image_info.get("image_path") or entry.get("image_path")
            if not isinstance(image_virtual, str) or not image_virtual:
                continue

            # Load image bytes
            try:
                image_physical = _resolve_virtual_path(thread_id, image_virtual)
                img = Image.open(image_physical).convert("RGB")
            except Exception:
                continue

            w, h = img.size

            report_obj = per_image.get("report") if isinstance(per_image, dict) else {}
            if not isinstance(report_obj, dict):
                report_obj = {}

            evidence = report_obj.get("evidence")
            evidence_list = evidence if isinstance(evidence, list) else []

            findings = report_obj.get("findings")
            findings_list = findings if isinstance(findings, list) else []

            limitations = report_obj.get("limitations")
            limitations_list = limitations if isinstance(limitations, list) else []

            evidence_payload: dict[str, Any] | None = None
            evidence_json_path: str | None = None
            evidence_artifacts = entry.get("evidence_artifacts")
            if isinstance(evidence_artifacts, dict):
                candidate = evidence_artifacts.get("json")
                if isinstance(candidate, str) and candidate:
                    evidence_json_path = candidate
                    try:
                        ev_physical = _resolve_virtual_path(thread_id, candidate)
                        evidence_payload = json.loads(ev_physical.read_text(encoding="utf-8"))
                        if not isinstance(evidence_payload, dict):
                            evidence_payload = None
                    except Exception:
                        evidence_payload = None

            # Layout page
            fig = plt.figure(figsize=(8.27, 11.69))
            fig.patch.set_facecolor("white")
            gs = fig.add_gridspec(2, 1, height_ratios=[3.1, 2.2], hspace=0.12)
            ax_img = fig.add_subplot(gs[0])
            ax_txt = fig.add_subplot(gs[1])

            ax_img.imshow(img)
            ax_img.set_title(f"Figure {idx}: {image_virtual}", fontsize=11, loc="left")
            ax_img.axis("off")

            # Draw ROIs
            palette = [
                "#d946ef",
                "#22c55e",
                "#3b82f6",
                "#f97316",
                "#ef4444",
                "#14b8a6",
                "#eab308",
                "#8b5cf6",
            ]
            color_i = 0
            for ev in evidence_list:
                if not isinstance(ev, dict):
                    continue
                ev_id = ev.get("id")
                bbox = ev.get("bbox_norm")
                if not isinstance(ev_id, str):
                    continue
                if not (isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(x, (int, float)) for x in bbox)):
                    continue
                x1, y1, x2, y2 = [max(0.0, min(1.0, float(x))) for x in bbox]
                x = min(x1, x2) * w
                y = min(y1, y2) * h
                rw = abs(x2 - x1) * w
                rh = abs(y2 - y1) * h
                color = palette[color_i % len(palette)]
                color_i += 1
                rect = Rectangle((x, y), rw, rh, fill=False, linewidth=2, edgecolor=color)
                ax_img.add_patch(rect)
                ax_img.text(
                    x,
                    y,
                    ev_id,
                    fontsize=8,
                    color="white",
                    bbox=dict(facecolor="black", alpha=0.55, pad=1, linewidth=0),
                )

            ax_txt.axis("off")

            # Text blocks
            image_type = report_obj.get("image_type")
            image_conf = report_obj.get("image_confidence")
            overall = per_image.get("overall") if isinstance(per_image, dict) else {}
            if not isinstance(overall, dict):
                overall = {}

            lines: list[str] = []
            lines.append(f"Image type: {image_type or 'unknown'}; image_confidence={image_conf!r}")
            lines.append(f"Report artifact: {report_path}")
            lines.append("")

            # Findings
            lines.append("Findings:")
            for f in findings_list[:12]:
                if not isinstance(f, dict):
                    continue
                claim = f.get("claim")
                conf = f.get("confidence")
                evid_ids = f.get("evidence_ids")
                evid_txt = ""
                if isinstance(evid_ids, list):
                    evid_txt = ", ".join([str(x) for x in evid_ids[:8]])
                    if len(evid_ids) > 8:
                        evid_txt += ", …"
                if isinstance(claim, str) and claim:
                    lines.append(f"- {claim} (conf={conf!r})" + (f" [evidence: {evid_txt}]" if evid_txt else ""))
            if len(findings_list) == 0:
                lines.append("- (none)")
            lines.append("")

            # Evidence summary
            lines.append("Evidence:")
            for ev in evidence_list[:18]:
                if not isinstance(ev, dict):
                    continue
                ev_id = ev.get("id")
                kind = ev.get("kind")
                conf = ev.get("confidence")
                desc = ev.get("description")
                if isinstance(ev_id, str) and ev_id:
                    parts = [ev_id]
                    if isinstance(kind, str) and kind:
                        parts.append(f"kind={kind}")
                    parts.append(f"conf={conf!r}")
                    if isinstance(desc, str) and desc:
                        parts.append(desc)
                    lines.append("- " + " | ".join(parts))
            if len(evidence_list) == 0:
                lines.append("- (none)")
            lines.append("")

            if isinstance(evidence_payload, dict) and evidence_json_path:
                lines.append("Derived evidence table (parser):")
                lines.append(f"- artifact: {evidence_json_path}")
                summary = evidence_payload.get("summary")
                if isinstance(summary, dict):
                    for key in ("lanes_detected", "bands_detected", "gates", "peaks_found", "separation_index", "min_center_distance_norm"):
                        if key in summary:
                            lines.append(f"- summary.{key}: {summary.get(key)!r}")
                    top_peaks = summary.get("top_peaks")
                    if isinstance(top_peaks, list) and top_peaks:
                        lines.append("- summary.top_peaks:")
                        for tp in top_peaks[:6]:
                            if isinstance(tp, dict):
                                lines.append(f"  - {tp.get('id')} | x_norm={tp.get('peak_x_norm')!r} | snr={tp.get('snr_estimate')!r}")
                rows = evidence_payload.get("rows")
                if isinstance(rows, list) and rows:
                    lines.append("- rows (first 12):")
                    for r in rows[:12]:
                        if not isinstance(r, dict):
                            continue
                        rid = r.get("id")
                        kind = r.get("kind")
                        metrics = r.get("metrics") if isinstance(r.get("metrics"), dict) else {}
                        parts = []
                        if rid is not None:
                            parts.append(str(rid))
                        if isinstance(kind, str) and kind:
                            parts.append(f"kind={kind}")
                        for mk in ("lane_index", "ratio_to_loading_control", "sum_signal_bg_corrected", "relative_ink_fraction", "snr_estimate", "peak_x_norm"):
                            if mk in metrics:
                                parts.append(f"{mk}={metrics.get(mk)!r}")
                        if parts:
                            lines.append("- " + " | ".join(parts))
                lines.append("")

            # Limitations
            if limitations_list:
                lines.append("Limitations:")
                for lim in limitations_list[:8]:
                    if isinstance(lim, str) and lim:
                        lines.append(f"- {lim}")
                lines.append("")

            # Overall
            if overall:
                lines.append("Overall:")
                oc = overall.get("overall_conclusion")
                of = overall.get("overall_confidence")
                if oc is not None:
                    lines.append(f"- overall_conclusion: {oc}")
                if of is not None:
                    lines.append(f"- overall_confidence: {of!r}")

            ax_txt.text(0.02, 0.98, _wrap(lines, width=120), fontsize=9, va="top", family="monospace")

            pdf.savefig(fig)
            plt.close(fig)

    return pdf_virtual

