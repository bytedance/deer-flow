from __future__ import annotations

import base64
import csv
import io
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

OUTPUTS_VIRTUAL_PREFIX = "/mnt/user-data/outputs"

IMAGE_EVIDENCE_SCHEMA_VERSION = "deerflow.image_evidence.v1"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _virtual_outputs_path(relative: str) -> str:
    rel = Path(relative).as_posix().lstrip("/")
    return f"{OUTPUTS_VIRTUAL_PREFIX}/{rel}"


def _safe_b64decode(data: str) -> bytes | None:
    try:
        return base64.b64decode(data)
    except Exception:
        return None


def _clamp01(x: float) -> float:
    if math.isnan(x):
        return 0.0
    return max(0.0, min(1.0, x))


def _bbox_norm_to_pixels(bbox_norm: Any, *, width: int, height: int) -> tuple[int, int, int, int] | None:
    if not (isinstance(bbox_norm, list) and len(bbox_norm) == 4):
        return None
    try:
        x1, y1, x2, y2 = [float(x) for x in bbox_norm]
    except Exception:
        return None
    x1 = _clamp01(x1)
    y1 = _clamp01(y1)
    x2 = _clamp01(x2)
    y2 = _clamp01(y2)
    left = int(round(min(x1, x2) * (width - 1)))
    right = int(round(max(x1, x2) * (width - 1)))
    top = int(round(min(y1, y2) * (height - 1)))
    bottom = int(round(max(y1, y2) * (height - 1)))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _roi_stats_signal(gray: np.ndarray, *, bbox: tuple[int, int, int, int]) -> dict[str, Any]:
    """Compute signal stats in ROI.

    Signal is defined as `255 - gray` (dark features -> higher signal).
    """
    left, top, right, bottom = bbox
    roi = gray[top:bottom, left:right]
    if roi.size == 0:
        return {
            "roi_area_px": 0,
            "mean_gray": None,
            "sum_gray": None,
            "mean_signal": None,
            "sum_signal": None,
            "bg_median_signal": None,
            "sum_signal_bg_corrected": None,
        }
    signal = 255.0 - roi.astype(np.float32)
    area = int(roi.shape[0] * roi.shape[1])
    mean_gray = float(np.mean(roi))
    sum_gray = float(np.sum(roi))
    mean_signal = float(np.mean(signal))
    sum_signal = float(np.sum(signal))

    # Background estimation: expand ROI and use surrounding ring.
    pad = int(max(2, round(0.15 * max(roi.shape[0], roi.shape[1]))))
    h, w = gray.shape
    ex_left = max(0, left - pad)
    ex_right = min(w, right + pad)
    ex_top = max(0, top - pad)
    ex_bottom = min(h, bottom + pad)
    expanded = gray[ex_top:ex_bottom, ex_left:ex_right]
    if expanded.size == 0:
        bg_median_signal = None
        corrected = None
    else:
        expanded_signal = 255.0 - expanded.astype(np.float32)
        mask = np.ones(expanded.shape, dtype=bool)
        mask[(top - ex_top) : (bottom - ex_top), (left - ex_left) : (right - ex_left)] = False
        ring = expanded_signal[mask]
        if ring.size == 0:
            bg_median_signal = None
            corrected = None
        else:
            bg_median_signal = float(np.median(ring))
            corrected = float(max(0.0, sum_signal - bg_median_signal * area))

    return {
        "roi_area_px": area,
        "mean_gray": mean_gray,
        "sum_gray": sum_gray,
        "mean_signal": mean_signal,
        "sum_signal": sum_signal,
        "bg_median_signal": bg_median_signal,
        "sum_signal_bg_corrected": corrected,
    }


def _draw_overlay(image: Image.Image, evidence_rows: list[dict[str, Any]]) -> Image.Image:
    overlay = image.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    w, h = overlay.size

    palette = [
        (217, 70, 239),
        (34, 197, 94),
        (59, 130, 246),
        (249, 115, 22),
        (239, 68, 68),
        (20, 184, 166),
        (234, 179, 8),
        (139, 92, 246),
    ]
    i = 0
    for row in evidence_rows:
        bbox_norm = row.get("bbox_norm")
        evidence_id = row.get("id")
        bbox = _bbox_norm_to_pixels(bbox_norm, width=w, height=h)
        if bbox is None or not isinstance(evidence_id, str):
            continue
        left, top, right, bottom = bbox
        color = palette[i % len(palette)]
        i += 1
        draw.rectangle([left, top, right, bottom], outline=color, width=3)
        label = evidence_id
        # background box for text
        tx = left
        ty = max(0, top - 14)
        draw.rectangle([tx, ty, tx + 8 * len(label) + 6, ty + 14], fill=(0, 0, 0))
        draw.text((tx + 3, ty + 1), label, fill=(255, 255, 255))
    return overlay


def _flatten_metrics(rows: list[dict[str, Any]]) -> list[str]:
    keys: set[str] = set()
    for r in rows:
        metrics = r.get("metrics")
        if isinstance(metrics, dict):
            for k in metrics.keys():
                if isinstance(k, str):
                    keys.add(k)
    return sorted(keys)


def _rows_to_csv(rows: list[dict[str, Any]]) -> str:
    metric_keys = _flatten_metrics(rows)
    fieldnames = ["id", "kind", "description", "confidence", "bbox_norm"] + [f"metrics.{k}" for k in metric_keys]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        out: dict[str, Any] = {
            "id": r.get("id"),
            "kind": r.get("kind"),
            "description": r.get("description"),
            "confidence": r.get("confidence"),
            "bbox_norm": json.dumps(r.get("bbox_norm"), ensure_ascii=False),
        }
        metrics = r.get("metrics")
        if isinstance(metrics, dict):
            for k in metric_keys:
                out[f"metrics.{k}"] = metrics.get(k)
        writer.writerow(out)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Parser interface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParserArtifacts:
    evidence_json_virtual_path: str
    evidence_csv_virtual_path: str | None
    overlay_png_virtual_path: str | None


@dataclass(frozen=True)
class ParserOutput:
    evidence_payload: dict[str, Any]
    artifacts: ParserArtifacts
    derived_summary: dict[str, Any] | None


ParserFn = Callable[[Image.Image, dict[str, Any]], tuple[list[dict[str, Any]], dict[str, Any] | None]]


def _parse_western_blot(image: Image.Image, report: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    evidence = report.get("evidence")
    if not isinstance(evidence, list):
        evidence = []

    w, h = image.size
    gray = np.asarray(image.convert("L"))

    rows: list[dict[str, Any]] = []
    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        evid = ev.get("id")
        bbox_norm = ev.get("bbox_norm")
        bbox = _bbox_norm_to_pixels(bbox_norm, width=w, height=h)
        if not isinstance(evid, str) or bbox is None:
            continue
        kind = ev.get("kind") if isinstance(ev.get("kind"), str) else "unknown"
        desc = ev.get("description") if isinstance(ev.get("description"), str) else ""
        conf = ev.get("confidence") if isinstance(ev.get("confidence"), (int, float)) else None

        metrics = _roi_stats_signal(gray, bbox=bbox)
        xc = (bbox[0] + bbox[2]) / 2.0 / max(1, (w - 1))
        yc = (bbox[1] + bbox[3]) / 2.0 / max(1, (h - 1))
        metrics["roi_center_x_norm"] = float(xc)
        metrics["roi_center_y_norm"] = float(yc)

        rows.append(
            {
                "id": evid,
                "kind": kind,
                "description": desc,
                "confidence": conf,
                "bbox_norm": bbox_norm,
                "metrics": metrics,
            }
        )

    # Lane grouping by x centers
    rows_sorted = sorted(rows, key=lambda r: float(r.get("metrics", {}).get("roi_center_x_norm") or 0.0))
    xcs = [float(r.get("metrics", {}).get("roi_center_x_norm") or 0.0) for r in rows_sorted]
    lane_ids: list[int] = []
    lane = 1
    if len(xcs) >= 2:
        diffs = [abs(xcs[i + 1] - xcs[i]) for i in range(len(xcs) - 1)]
        med = float(np.median(np.asarray(diffs))) if diffs else 0.15
        threshold = max(0.04, med * 0.8)
    else:
        threshold = 0.08
    prev = None
    for xc in xcs:
        if prev is None:
            lane_ids.append(lane)
        else:
            if abs(xc - prev) > threshold:
                lane += 1
            lane_ids.append(lane)
        prev = xc

    for r, lid in zip(rows_sorted, lane_ids, strict=False):
        r.setdefault("metrics", {})["lane_index"] = lid

    # Detect loading control by keywords in description
    control_keywords = ("actin", "tubulin", "gapdh", "loading", "内参", "β-actin", "βactin")
    lanes: dict[int, dict[str, Any]] = {}
    for r in rows_sorted:
        m = r.get("metrics") if isinstance(r.get("metrics"), dict) else {}
        lid = int(m.get("lane_index") or 0)
        lanes.setdefault(lid, {"bands": [], "control_id": None})
        lanes[lid]["bands"].append(r)
        desc = (r.get("description") or "").lower()
        if any(k in desc for k in control_keywords):
            lanes[lid]["control_id"] = r.get("id")

    # Compute normalization ratios within lane (band / control)
    for lid, info in lanes.items():
        control_id = info.get("control_id")
        if not isinstance(control_id, str):
            continue
        control = next((b for b in info["bands"] if b.get("id") == control_id), None)
        if not control:
            continue
        c_metrics = control.get("metrics", {}) if isinstance(control.get("metrics"), dict) else {}
        c_val = c_metrics.get("sum_signal_bg_corrected")
        if not isinstance(c_val, (int, float)) or c_val <= 0:
            continue
        for b in info["bands"]:
            b_metrics = b.get("metrics", {}) if isinstance(b.get("metrics"), dict) else {}
            v = b_metrics.get("sum_signal_bg_corrected")
            if isinstance(v, (int, float)):
                b_metrics["ratio_to_loading_control"] = float(v) / float(c_val)
                b_metrics["loading_control_id"] = control_id

    lane_summaries: list[dict[str, Any]] = []
    for lid in sorted(lanes.keys()):
        info = lanes[lid]
        control_id = info.get("control_id") if isinstance(info.get("control_id"), str) else None
        bands = info.get("bands") if isinstance(info.get("bands"), list) else []
        lane_bands: list[dict[str, Any]] = []
        for b in sorted(
            [bb for bb in bands if isinstance(bb, dict)],
            key=lambda bb: float((bb.get("metrics") or {}).get("roi_center_y_norm") or 0.0),
        ):
            metrics = b.get("metrics") if isinstance(b.get("metrics"), dict) else {}
            lane_bands.append(
                {
                    "id": b.get("id"),
                    "description": b.get("description"),
                    "is_loading_control": bool(control_id and b.get("id") == control_id),
                    "sum_signal_bg_corrected": metrics.get("sum_signal_bg_corrected"),
                    "ratio_to_loading_control": metrics.get("ratio_to_loading_control"),
                }
            )
        lane_summaries.append(
            {
                "lane_index": lid,
                "loading_control_id": control_id,
                "bands": lane_bands,
            }
        )

    summary = {
        "lanes_detected": len(lanes),
        "bands_detected": len(rows_sorted),
        "normalization": "ratio_to_loading_control uses bg-corrected signal when a control band is detected per lane",
        "lane_summaries": lane_summaries,
    }
    return rows_sorted, summary


def _parse_spectrum(image: Image.Image, report: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    w, h = image.size
    gray = np.asarray(image.convert("L")).astype(np.float32)
    signal = 255.0 - gray

    # Focus on central area to reduce axis/label noise
    x0 = int(round(0.06 * w))
    x1 = int(round(0.94 * w))
    y0 = int(round(0.08 * h))
    y1 = int(round(0.92 * h))
    crop = signal[y0:y1, x0:x1]
    if crop.size == 0:
        return [], {"warning": "empty_crop"}

    # Trace the darkest line per x-column
    y_idx = np.argmax(crop, axis=0)
    vals = crop[y_idx, np.arange(crop.shape[1])]
    vals = vals.astype(np.float32)

    # Smooth
    if vals.size >= 9:
        kernel = np.ones(9, dtype=np.float32) / 9.0
        smooth = np.convolve(vals, kernel, mode="same")
    else:
        smooth = vals

    try:
        from scipy.signal import find_peaks, peak_prominences
    except Exception:
        # Fallback: pick top-K x positions by value
        k = int(min(8, smooth.size))
        idxs = np.argsort(-smooth)[:k]
        idxs = np.sort(idxs)
        peaks = idxs
        prominences = np.asarray([0.0] * len(peaks), dtype=np.float32)
    else:
        peaks, _props = find_peaks(smooth, prominence=max(5.0, float(np.percentile(smooth, 80)) * 0.25))
        prominences = peak_prominences(smooth, peaks)[0] if peaks.size > 0 else np.asarray([], dtype=np.float32)

    # Baseline noise estimate
    baseline = smooth[smooth <= np.percentile(smooth, 60)]
    noise = float(np.std(baseline)) if baseline.size > 10 else float(np.std(smooth)) if smooth.size > 0 else 1.0
    noise = max(1e-6, noise)

    rows: list[dict[str, Any]] = []
    for i, px in enumerate(peaks[:10], start=1):
        x_norm = float((x0 + int(px)) / max(1, (w - 1)))
        y_norm = float((y0 + int(y_idx[int(px)])) / max(1, (h - 1)))
        height = float(smooth[int(px)])
        prom = float(prominences[i - 1]) if i - 1 < len(prominences) else 0.0
        snr = float(height / noise)
        # Small bbox around the peak for audit
        half = 0.012
        bbox_norm = [
            _clamp01(x_norm - half),
            _clamp01(y_norm - half),
            _clamp01(x_norm + half),
            _clamp01(y_norm + half),
        ]
        rows.append(
            {
                "id": f"P{i}",
                "kind": "peak",
                "description": "Derived peak from spectrum trace (image-only digitization; x in normalized pixel space unless calibrated)",
                "confidence": None,
                "bbox_norm": bbox_norm,
                "metrics": {
                    "peak_x_norm": x_norm,
                    "peak_y_norm": y_norm,
                    "peak_height_signal": height,
                    "peak_prominence_signal": prom,
                    "snr_estimate": snr,
                },
            }
        )

    top_peaks = sorted(
        [
            {
                "id": r.get("id"),
                "peak_x_norm": (r.get("metrics") or {}).get("peak_x_norm"),
                "snr_estimate": (r.get("metrics") or {}).get("snr_estimate"),
                "peak_prominence_signal": (r.get("metrics") or {}).get("peak_prominence_signal"),
            }
            for r in rows
            if isinstance(r, dict)
        ],
        key=lambda x: float(x.get("snr_estimate") or 0.0),
        reverse=True,
    )[:6]
    summary = {
        "peaks_found": len(rows),
        "noise_estimate_signal_std": noise,
        "top_peaks": top_peaks,
        "note": "Peak positions are in normalized pixel space unless the vision report provides axis calibration.",
    }
    return rows, summary


def _parse_tsne(image: Image.Image, report: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    evidence = report.get("evidence")
    if not isinstance(evidence, list):
        evidence = []

    rows: list[dict[str, Any]] = []
    centers: list[tuple[float, float]] = []
    areas: list[float] = []

    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        evid = ev.get("id")
        bbox_norm = ev.get("bbox_norm")
        if not isinstance(evid, str) or not (isinstance(bbox_norm, list) and len(bbox_norm) == 4):
            continue
        try:
            x1, y1, x2, y2 = [float(x) for x in bbox_norm]
        except Exception:
            continue
        x1 = _clamp01(x1)
        y1 = _clamp01(y1)
        x2 = _clamp01(x2)
        y2 = _clamp01(y2)
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        area = abs(x2 - x1) * abs(y2 - y1)
        centers.append((cx, cy))
        areas.append(area)

        kind = ev.get("kind") if isinstance(ev.get("kind"), str) else "region"
        desc = ev.get("description") if isinstance(ev.get("description"), str) else ""
        conf = ev.get("confidence") if isinstance(ev.get("confidence"), (int, float)) else None

        rows.append(
            {
                "id": evid,
                "kind": kind,
                "description": desc,
                "confidence": conf,
                "bbox_norm": bbox_norm,
                "metrics": {
                    "center_x_norm": cx,
                    "center_y_norm": cy,
                    "area_norm": area,
                },
            }
        )

    # Separation index (from ROI centers)
    min_dist = None
    if len(centers) >= 2:
        for i in range(len(centers)):
            for j in range(i + 1, len(centers)):
                dx = centers[i][0] - centers[j][0]
                dy = centers[i][1] - centers[j][1]
                d = math.sqrt(dx * dx + dy * dy)
                min_dist = d if min_dist is None else min(min_dist, d)
    mean_area = float(np.mean(np.asarray(areas))) if areas else 0.0
    sep = float(min_dist / math.sqrt(mean_area + 1e-9)) if min_dist is not None else None

    summary = {
        "regions": len(rows),
        "min_center_distance_norm": min_dist,
        "mean_region_area_norm": mean_area,
        "separation_index": sep,
        "note": "This parser uses ROIs from ImageReport; it does not reconstruct underlying embedding coordinates.",
    }
    return rows, summary


def _parse_facs(image: Image.Image, report: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    evidence = report.get("evidence")
    if not isinstance(evidence, list):
        evidence = []

    w, h = image.size
    gray = np.asarray(image.convert("L"))

    rows: list[dict[str, Any]] = []
    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        evid = ev.get("id")
        bbox_norm = ev.get("bbox_norm")
        bbox = _bbox_norm_to_pixels(bbox_norm, width=w, height=h)
        if not isinstance(evid, str) or bbox is None:
            continue
        kind = ev.get("kind") if isinstance(ev.get("kind"), str) else "gate"
        desc = ev.get("description") if isinstance(ev.get("description"), str) else ""
        conf = ev.get("confidence") if isinstance(ev.get("confidence"), (int, float)) else None
        metrics = _roi_stats_signal(gray, bbox=bbox)

        # Sensitivity analysis: expand/shrink bbox by ~3% to estimate threshold sensitivity.
        left, top, right, bottom = bbox
        bw = max(1, right - left)
        bh = max(1, bottom - top)
        dx = max(1, int(round(0.03 * bw)))
        dy = max(1, int(round(0.03 * bh)))

        def _clamp_bbox(left_px: int, top_px: int, right_px: int, bottom_px: int) -> tuple[int, int, int, int] | None:
            l2 = max(0, min(w - 1, left_px))
            t2 = max(0, min(h - 1, top_px))
            r2 = max(0, min(w, right_px))
            b2 = max(0, min(h, bottom_px))
            if r2 <= l2 + 1 or b2 <= t2 + 1:
                return None
            return l2, t2, r2, b2

        shrink = _clamp_bbox(left + dx, top + dy, right - dx, bottom - dy)
        expand = _clamp_bbox(left - dx, top - dy, right + dx, bottom + dy)
        base_val = metrics.get("sum_signal_bg_corrected")
        sens: dict[str, Any] = {}
        if shrink is not None:
            m2 = _roi_stats_signal(gray, bbox=shrink)
            v2 = m2.get("sum_signal_bg_corrected")
            sens["shrink_3pct_sum_signal_bg_corrected"] = v2
            if isinstance(base_val, (int, float)) and isinstance(v2, (int, float)) and base_val > 0:
                sens["shrink_3pct_ratio"] = float(v2) / float(base_val)
        if expand is not None:
            m3 = _roi_stats_signal(gray, bbox=expand)
            v3 = m3.get("sum_signal_bg_corrected")
            sens["expand_3pct_sum_signal_bg_corrected"] = v3
            if isinstance(base_val, (int, float)) and isinstance(v3, (int, float)) and base_val > 0:
                sens["expand_3pct_ratio"] = float(v3) / float(base_val)
        if sens:
            metrics["threshold_sensitivity"] = sens
        rows.append(
            {
                "id": evid,
                "kind": kind,
                "description": desc,
                "confidence": conf,
                "bbox_norm": bbox_norm,
                "metrics": metrics,
            }
        )

    # Relative "ink" fraction as a rough proxy for population fraction
    totals = [r.get("metrics", {}).get("sum_signal_bg_corrected") for r in rows]
    total = float(sum([t for t in totals if isinstance(t, (int, float)) and t is not None])) if totals else 0.0
    for r in rows:
        m = r.get("metrics", {}) if isinstance(r.get("metrics"), dict) else {}
        v = m.get("sum_signal_bg_corrected")
        if isinstance(v, (int, float)) and total > 0:
            m["relative_ink_fraction"] = float(v) / total
            m["relative_ink_fraction_note"] = "Proxy from image pixel ink in gate ROI; prefer raw FCS for exact population fractions."

    summary = {
        "gates": len(rows),
        "gate_fractions": [
            {
                "id": r.get("id"),
                "relative_ink_fraction": (r.get("metrics") or {}).get("relative_ink_fraction"),
                "sum_signal_bg_corrected": (r.get("metrics") or {}).get("sum_signal_bg_corrected"),
            }
            for r in rows
            if isinstance(r, dict)
        ][:12],
        "note": "Image-only estimation is approximate. For audit-grade quantification, upload and parse raw FCS when available.",
    }
    return rows, summary


PARSERS: dict[str, ParserFn] = {
    "western_blot": _parse_western_blot,
    "spectrum": _parse_spectrum,
    "tsne": _parse_tsne,
    "facs": _parse_facs,
}


def generate_image_evidence_artifacts(
    *,
    thread_outputs_dir: Path,
    artifact_subdir: str,
    analysis_signature: str,
    report_path: str,
    report_model: str | None,
    prompt_hash: str | None,
    image_path: str,
    image_sha256: str,
    mime_type: str | None,
    image_base64: str,
    report: dict[str, Any],
    enabled_parsers: list[str] | None = None,
    write_csv: bool = True,
    write_overlay: bool = True,
) -> ParserOutput | None:
    """Generate evidence artifacts for a single image based on ImageReport ROIs.

    Returns None if:
    - image bytes cannot be decoded, or
    - no parser exists for the given `image_type`, or
    - parser is not enabled by `enabled_parsers`.
    """
    image_type = report.get("image_type") if isinstance(report.get("image_type"), str) else "unknown"
    parser = PARSERS.get(image_type)
    if parser is None:
        return None
    if enabled_parsers is not None and image_type not in enabled_parsers:
        return None

    img_bytes = _safe_b64decode(image_base64)
    if img_bytes is None:
        return None

    try:
        image = Image.open(io.BytesIO(img_bytes))
        image.load()
    except Exception:
        return None

    rows, summary = parser(image, report)

    # File paths (content-addressed by image_sha256 + analysis_signature)
    base = Path(artifact_subdir.strip("/")) / "images" / f"sha256-{image_sha256}"
    stem = f"{analysis_signature[:12]}"
    evidence_rel_json = base / f"evidence-{stem}.json"
    evidence_rel_csv = base / f"evidence-{stem}.csv"
    overlay_rel = base / f"overlay-{stem}.png"

    evidence_physical = thread_outputs_dir / evidence_rel_json
    evidence_physical.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "schema_version": IMAGE_EVIDENCE_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "analysis_signature": analysis_signature,
        "prompt_hash": prompt_hash,
        "report_model": report_model,
        "report_path": report_path,
        "image_type": image_type,
        "image": {
            "image_path": image_path,
            "image_sha256": image_sha256,
            "mime_type": mime_type,
        },
        "rows": rows,
        "summary": summary or {},
    }

    evidence_physical.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence_virtual = _virtual_outputs_path(evidence_rel_json.as_posix())

    csv_virtual: str | None = None
    if write_csv:
        csv_text = _rows_to_csv(rows)
        csv_physical = thread_outputs_dir / evidence_rel_csv
        csv_physical.write_text(csv_text, encoding="utf-8")
        csv_virtual = _virtual_outputs_path(evidence_rel_csv.as_posix())

    overlay_virtual: str | None = None
    if write_overlay and rows:
        try:
            overlay = _draw_overlay(image, rows)
            overlay_physical = thread_outputs_dir / overlay_rel
            overlay.save(overlay_physical, format="PNG")
            overlay_virtual = _virtual_outputs_path(overlay_rel.as_posix())
        except Exception:
            overlay_virtual = None

    return ParserOutput(
        evidence_payload=payload,
        artifacts=ParserArtifacts(
            evidence_json_virtual_path=evidence_virtual,
            evidence_csv_virtual_path=csv_virtual,
            overlay_png_virtual_path=overlay_virtual,
        ),
        derived_summary=(summary if isinstance(summary, dict) else None),
    )

