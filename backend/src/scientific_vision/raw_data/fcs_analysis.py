from __future__ import annotations

import hashlib
import json
import math
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from flowio import FlowData

OUTPUTS_VIRTUAL_PREFIX = "/mnt/user-data/outputs"

FCS_ANALYSIS_SCHEMA_VERSION = "deerflow.raw_data.fcs_analysis.v1"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _virtual_outputs_path(relative: str) -> str:
    rel = Path(relative).as_posix().lstrip("/")
    return f"{OUTPUTS_VIRTUAL_PREFIX}/{rel}"


def _safe_float(x: Any) -> float | None:
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except Exception:
        return None


def _split_spillover_tokens(value: str) -> list[str]:
    # Typical format: "n,Ch1,Ch2,...,v11,v12,..."
    # Some files use commas; keep it conservative and strip whitespace.
    tokens = [t.strip() for t in value.replace(";", ",").split(",")]
    return [t for t in tokens if t]


def _parse_spillover(text: dict[str, Any]) -> dict[str, Any] | None:
    raw = None
    for key in ("$SPILLOVER", "$SPILL", "$COMP", "SPILLOVER", "SPILL"):
        v = text.get(key)
        if isinstance(v, str) and v.strip():
            raw = v.strip()
            break
    if raw is None:
        return None
    tokens = _split_spillover_tokens(raw)
    if not tokens:
        return None
    try:
        n = int(tokens[0])
    except Exception:
        return None
    if n <= 0:
        return None
    names = tokens[1 : 1 + n]
    vals = tokens[1 + n :]
    if len(names) != n or len(vals) < n * n:
        return None
    try:
        mat_vals = [float(x) for x in vals[: n * n]]
    except Exception:
        return None
    matrix = np.asarray(mat_vals, dtype=np.float64).reshape((n, n))
    return {
        "source_key": key,
        "channels": names,
        "matrix": matrix.tolist(),
        "raw": raw[:2000],
    }


def _match_channel_index(
    *,
    pnn_labels: list[str],
    pns_labels: list[str],
    channel: str,
) -> int | None:
    if not channel:
        return None
    target = channel.strip().lower()
    pnn_lower = [c.lower() for c in pnn_labels]
    pns_lower = [c.lower() for c in pns_labels]
    if target in pnn_lower:
        return pnn_lower.index(target)
    if target in pns_lower:
        return pns_lower.index(target)
    # Fuzzy: contains
    for i, c in enumerate(pnn_lower):
        if target in c:
            return i
    for i, c in enumerate(pns_lower):
        if target in c:
            return i
    return None


def _channel_stats(vec: np.ndarray) -> dict[str, Any]:
    if vec.size == 0:
        return {"count": 0}
    v = vec.astype(np.float64)
    # Robust to NaN
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {"count": 0}
    return {
        "count": int(v.size),
        "min": float(np.min(v)),
        "max": float(np.max(v)),
        "mean": float(np.mean(v)),
        "median": float(np.median(v)),
        "std": float(np.std(v)),
        "p01": float(np.percentile(v, 1)),
        "p05": float(np.percentile(v, 5)),
        "p95": float(np.percentile(v, 95)),
        "p99": float(np.percentile(v, 99)),
    }


def _apply_compensation_if_possible(
    *,
    data: np.ndarray,
    spill: dict[str, Any] | None,
    pnn_labels: list[str],
    pns_labels: list[str],
) -> tuple[np.ndarray, dict[str, Any] | None]:
    if spill is None:
        return data, None
    channels = spill.get("channels")
    matrix = spill.get("matrix")
    if not (isinstance(channels, list) and isinstance(matrix, list)):
        return data, None
    try:
        mat = np.asarray(matrix, dtype=np.float64)
    except Exception:
        return data, None
    if mat.ndim != 2 or mat.shape[0] != mat.shape[1] or mat.shape[0] != len(channels):
        return data, None

    idxs: list[int] = []
    for ch in channels:
        if not isinstance(ch, str):
            return data, None
        i = _match_channel_index(pnn_labels=pnn_labels, pns_labels=pns_labels, channel=ch)
        if i is None:
            return data, None
        idxs.append(i)

    try:
        inv = np.linalg.inv(mat)
    except Exception:
        return data, {"warning": "spillover_matrix_not_invertible", "channels": channels}

    corrected = data.astype(np.float64, copy=True)
    sub = corrected[:, idxs]
    sub_corr = sub @ inv
    corrected[:, idxs] = sub_corr
    return corrected, {"channels": channels, "matrix": matrix, "method": "data @ inv(spillover)"}


def _gate_mask_threshold(data: np.ndarray, idx: int, op: str, thr: float) -> np.ndarray:
    col = data[:, idx]
    if op == ">":
        return col > thr
    if op == ">=":
        return col >= thr
    if op == "<":
        return col < thr
    if op == "<=":
        return col <= thr
    return col > thr


def _gate_mask_rect2d(data: np.ndarray, x_idx: int, y_idx: int, x_min: float, x_max: float, y_min: float, y_max: float) -> np.ndarray:
    x = data[:, x_idx]
    y = data[:, y_idx]
    return (x >= x_min) & (x <= x_max) & (y >= y_min) & (y <= y_max)


def _normalize_gate_spec(g: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(g, dict):
        return None
    gid = g.get("id")
    gtype = g.get("type")
    if not isinstance(gid, str) or not gid.strip():
        return None
    if not isinstance(gtype, str) or not gtype.strip():
        return None
    out = dict(g)
    out["id"] = gid.strip()
    out["type"] = gtype.strip()
    parent = g.get("parent")
    out["parent"] = parent.strip() if isinstance(parent, str) and parent.strip() else None
    return out


def analyze_fcs_file(
    *,
    fcs_path: Path,
    outputs_dir: Path,
    gates: list[dict[str, Any]] | None = None,
    preprocess: bool = False,
    apply_compensation: bool = False,
    max_events: int | None = 200_000,
    artifact_subdir: str = "scientific-vision/raw-data/fcs",
) -> tuple[dict[str, Any], list[str]]:
    """Analyze an FCS file and persist audit artifacts under outputs_dir.

    Returns:
        (payload_dict, artifact_virtual_paths)
    """
    raw_bytes = fcs_path.read_bytes()
    fcs_sha256 = _sha256_bytes(raw_bytes)

    # Normalize analysis config for hashing
    gates_norm = []
    if isinstance(gates, list):
        for g in gates:
            ng = _normalize_gate_spec(g) if isinstance(g, dict) else None
            if ng is not None:
                gates_norm.append(ng)
    config_blob = json.dumps(
        {
            "schema": FCS_ANALYSIS_SCHEMA_VERSION,
            "preprocess": bool(preprocess),
            "apply_compensation": bool(apply_compensation),
            "max_events": int(max_events) if isinstance(max_events, int) else None,
            "gates": gates_norm,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    analysis_sig = _sha256_text(config_blob)

    base = Path(artifact_subdir.strip("/")) / f"sha256-{fcs_sha256}"
    analysis_rel = base / f"analysis-{analysis_sig[:12]}.json"
    gates_rel = base / f"gates-{analysis_sig[:12]}.csv"
    channels_rel = base / f"channels-{analysis_sig[:12]}.csv"
    reproduce_rel = base / f"reproduce-{analysis_sig[:12]}.py"

    analysis_physical = outputs_dir / analysis_rel
    analysis_physical.parent.mkdir(parents=True, exist_ok=True)

    fd = FlowData(str(fcs_path))
    text = getattr(fd, "text", {}) or {}
    pnn_labels = list(getattr(fd, "pnn_labels", []) or [])
    pns_labels = list(getattr(fd, "pns_labels", []) or [])
    pnr_values = list(getattr(fd, "pnr_values", []) or [])
    channel_count = int(getattr(fd, "channel_count", len(pnn_labels) or 0) or 0)
    event_count = int(getattr(fd, "event_count", 0) or 0)

    data = fd.as_array(preprocess=bool(preprocess))
    if not isinstance(data, np.ndarray) or data.ndim != 2:
        raise ValueError("FlowIO returned invalid data array")
    if channel_count and data.shape[1] != channel_count:
        channel_count = int(data.shape[1])

    analyzed_count = int(data.shape[0])
    if isinstance(max_events, int) and max_events > 0 and analyzed_count > max_events:
        data = data[:max_events, :]
        analyzed_count = int(data.shape[0])

    spill = _parse_spillover(text if isinstance(text, dict) else {})
    comp_info: dict[str, Any] | None = None
    if apply_compensation:
        data, comp_info = _apply_compensation_if_possible(data=data, spill=spill, pnn_labels=pnn_labels, pns_labels=pns_labels)

    channels: list[dict[str, Any]] = []
    for i in range(channel_count):
        pnn = pnn_labels[i] if i < len(pnn_labels) else f"P{i+1}N"
        pns = pns_labels[i] if i < len(pns_labels) else ""
        pnr = pnr_values[i] if i < len(pnr_values) else None
        channels.append(
            {
                "index": i,
                "pnn": pnn,
                "pns": pns,
                "pnr": pnr,
                "stats": _channel_stats(data[:, i]),
            }
        )

    # Gates
    gate_results: list[dict[str, Any]] = []
    masks: dict[str, np.ndarray] = {}
    total_mask = np.ones((analyzed_count,), dtype=bool)

    for g in gates_norm:
        gid = g["id"]
        parent = g.get("parent")
        parent_mask = masks.get(parent) if isinstance(parent, str) else total_mask
        if parent_mask is None:
            parent_mask = total_mask

        gtype = g["type"]
        mask = None
        if gtype in ("threshold", "1d", "gate1d"):
            ch = g.get("channel")
            op = g.get("op") if isinstance(g.get("op"), str) else ">"
            thr = _safe_float(g.get("threshold"))
            idx = _match_channel_index(pnn_labels=pnn_labels, pns_labels=pns_labels, channel=ch) if isinstance(ch, str) else None
            if idx is not None and thr is not None:
                mask = _gate_mask_threshold(data, idx, op, thr)
        elif gtype in ("rect", "rect2d", "gate2d"):
            xch = g.get("x_channel")
            ych = g.get("y_channel")
            x_min = _safe_float(g.get("x_min"))
            x_max = _safe_float(g.get("x_max"))
            y_min = _safe_float(g.get("y_min"))
            y_max = _safe_float(g.get("y_max"))
            x_idx = _match_channel_index(pnn_labels=pnn_labels, pns_labels=pns_labels, channel=xch) if isinstance(xch, str) else None
            y_idx = _match_channel_index(pnn_labels=pnn_labels, pns_labels=pns_labels, channel=ych) if isinstance(ych, str) else None
            if None not in (x_idx, y_idx, x_min, x_max, y_min, y_max):
                mask = _gate_mask_rect2d(data, int(x_idx), int(y_idx), float(x_min), float(x_max), float(y_min), float(y_max))

        if mask is None:
            gate_results.append({"id": gid, "type": gtype, "parent": parent, "error": "invalid_gate_spec"})
            continue

        mask = mask & parent_mask
        masks[gid] = mask

        in_gate = int(np.sum(mask))
        parent_count = int(np.sum(parent_mask))
        total_count = int(np.sum(total_mask))
        frac_parent = float(in_gate / parent_count) if parent_count > 0 else None
        frac_total = float(in_gate / total_count) if total_count > 0 else None

        # Simple sensitivity: +/-2% thresholds for numeric parameters
        sens: dict[str, Any] = {}
        delta = 0.02
        if gtype in ("threshold", "1d", "gate1d") and isinstance(g.get("threshold"), (int, float)) and isinstance(g.get("channel"), str):
            thr0 = float(g["threshold"])
            thr_lo = thr0 * (1.0 - delta)
            thr_hi = thr0 * (1.0 + delta)
            idx = _match_channel_index(pnn_labels=pnn_labels, pns_labels=pns_labels, channel=g["channel"])
            if idx is not None:
                m_lo = _gate_mask_threshold(data, idx, g.get("op") if isinstance(g.get("op"), str) else ">", thr_lo) & parent_mask
                m_hi = _gate_mask_threshold(data, idx, g.get("op") if isinstance(g.get("op"), str) else ">", thr_hi) & parent_mask
                sens = {
                    "delta_fraction": delta,
                    "threshold_lo": thr_lo,
                    "threshold_hi": thr_hi,
                    "frac_parent_lo": float(np.sum(m_lo) / parent_count) if parent_count > 0 else None,
                    "frac_parent_hi": float(np.sum(m_hi) / parent_count) if parent_count > 0 else None,
                }
        if gtype in ("rect", "rect2d", "gate2d") and isinstance(g.get("x_min"), (int, float)) and isinstance(g.get("x_max"), (int, float)) and isinstance(g.get("y_min"), (int, float)) and isinstance(g.get("y_max"), (int, float)):
            x_min0 = float(g["x_min"])
            x_max0 = float(g["x_max"])
            y_min0 = float(g["y_min"])
            y_max0 = float(g["y_max"])
            x_min_lo, x_min_hi = x_min0 * (1.0 - delta), x_min0 * (1.0 + delta)
            x_max_lo, x_max_hi = x_max0 * (1.0 - delta), x_max0 * (1.0 + delta)
            y_min_lo, y_min_hi = y_min0 * (1.0 - delta), y_min0 * (1.0 + delta)
            y_max_lo, y_max_hi = y_max0 * (1.0 - delta), y_max0 * (1.0 + delta)
            x_idx = _match_channel_index(pnn_labels=pnn_labels, pns_labels=pns_labels, channel=g.get("x_channel") or "")
            y_idx = _match_channel_index(pnn_labels=pnn_labels, pns_labels=pns_labels, channel=g.get("y_channel") or "")
            if x_idx is not None and y_idx is not None:
                m_lo = _gate_mask_rect2d(data, x_idx, y_idx, x_min_lo, x_max_lo, y_min_lo, y_max_lo) & parent_mask
                m_hi = _gate_mask_rect2d(data, x_idx, y_idx, x_min_hi, x_max_hi, y_min_hi, y_max_hi) & parent_mask
                sens = {
                    "delta_fraction": delta,
                    "frac_parent_lo": float(np.sum(m_lo) / parent_count) if parent_count > 0 else None,
                    "frac_parent_hi": float(np.sum(m_hi) / parent_count) if parent_count > 0 else None,
                }

        gate_results.append(
            {
                "id": gid,
                "type": gtype,
                "parent": parent,
                "count_in_gate": in_gate,
                "count_parent": parent_count,
                "fraction_of_parent": frac_parent,
                "fraction_of_total": frac_total,
                "sensitivity": sens or None,
            }
        )

    payload: dict[str, Any] = {
        "schema_version": FCS_ANALYSIS_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "input": {
            "fcs_path": str(fcs_path),
            "fcs_sha256": fcs_sha256,
            "event_count_reported": event_count,
            "event_count_analyzed": analyzed_count,
            "preprocess": bool(preprocess),
            "apply_compensation": bool(apply_compensation),
        },
        "analysis_signature": analysis_sig,
        "channels": channels,
        "compensation": comp_info,
        "gates": gate_results,
        "notes": [
            "This analysis is audit-oriented. If you need FlowJo-equivalent results, provide the exact gating strategy and compensation settings.",
            "If apply_compensation=true, we apply compensated_data = data @ inv(spillover) when a spillover matrix is found and invertible.",
        ],
    }

    analysis_physical.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write CSV artifacts (gates + channels)
    gates_csv_physical = outputs_dir / gates_rel
    gates_csv_physical.parent.mkdir(parents=True, exist_ok=True)
    gates_header = [
        "id",
        "type",
        "parent",
        "count_in_gate",
        "count_parent",
        "fraction_of_parent",
        "fraction_of_total",
        "sens_delta_fraction",
        "sens_frac_parent_lo",
        "sens_frac_parent_hi",
        "error",
    ]
    rows = [",".join(gates_header)]
    for g in gate_results:
        sens = g.get("sensitivity") if isinstance(g.get("sensitivity"), dict) else {}
        row = [
            str(g.get("id", "")),
            str(g.get("type", "")),
            str(g.get("parent", "") or ""),
            str(g.get("count_in_gate", "")),
            str(g.get("count_parent", "")),
            str(g.get("fraction_of_parent", "")),
            str(g.get("fraction_of_total", "")),
            str(sens.get("delta_fraction", "")),
            str(sens.get("frac_parent_lo", "")),
            str(sens.get("frac_parent_hi", "")),
            str(g.get("error", "") or ""),
        ]
        rows.append(",".join(row))
    gates_csv_physical.write_text("\n".join(rows) + "\n", encoding="utf-8")

    chan_csv_physical = outputs_dir / channels_rel
    chan_header = [
        "index",
        "pnn",
        "pns",
        "pnr",
        "count",
        "min",
        "max",
        "mean",
        "median",
        "std",
        "p01",
        "p05",
        "p95",
        "p99",
    ]
    chan_rows = [",".join(chan_header)]
    for ch in channels:
        stats = ch.get("stats") if isinstance(ch.get("stats"), dict) else {}
        row = [
            str(ch.get("index", "")),
            str(ch.get("pnn", "")),
            str(ch.get("pns", "")),
            str(ch.get("pnr", "")),
            str(stats.get("count", "")),
            str(stats.get("min", "")),
            str(stats.get("max", "")),
            str(stats.get("mean", "")),
            str(stats.get("median", "")),
            str(stats.get("std", "")),
            str(stats.get("p01", "")),
            str(stats.get("p05", "")),
            str(stats.get("p95", "")),
            str(stats.get("p99", "")),
        ]
        chan_rows.append(",".join(row))
    chan_csv_physical.parent.mkdir(parents=True, exist_ok=True)
    chan_csv_physical.write_text("\n".join(chan_rows) + "\n", encoding="utf-8")

    # Reproduce script
    reproduce_physical = outputs_dir / reproduce_rel
    reproduce_physical.parent.mkdir(parents=True, exist_ok=True)
    max_events_val = int(max_events) if isinstance(max_events, int) else None
    repro = f"""\
#!/usr/bin/env python
# Auto-generated by DeerFlow ({FCS_ANALYSIS_SCHEMA_VERSION})
#
# Usage:
#   python {reproduce_physical.name} <path-to-fcs>
#
# Dependencies: flowio, numpy

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from flowio import FlowData


PREPROCESS = {bool(preprocess)}
APPLY_COMPENSATION = {bool(apply_compensation)}
MAX_EVENTS = {max_events_val if max_events_val is not None else "None"}
ANALYSIS_SIGNATURE = "{analysis_sig}"
GATES = {repr(gates_norm)}
SENSITIVITY_DELTA = 0.02


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def channel_stats(vec: np.ndarray) -> dict:
    v = np.asarray(vec, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {{"count": 0}}
    return {{
        "count": int(v.size),
        "min": float(np.min(v)),
        "max": float(np.max(v)),
        "mean": float(np.mean(v)),
        "median": float(np.median(v)),
        "std": float(np.std(v)),
        "p01": float(np.percentile(v, 1)),
        "p05": float(np.percentile(v, 5)),
        "p95": float(np.percentile(v, 95)),
        "p99": float(np.percentile(v, 99)),
    }}


def split_spillover_tokens(value: str) -> list[str]:
    tokens = [t.strip() for t in value.replace(";", ",").split(",")]
    return [t for t in tokens if t]


def parse_spillover(text: dict) -> dict | None:
    raw = None
    key_used = None
    for key in ("$SPILLOVER", "$SPILL", "$COMP", "SPILLOVER", "SPILL"):
        v = text.get(key)
        if isinstance(v, str) and v.strip():
            raw = v.strip()
            key_used = key
            break
    if raw is None:
        return None
    tokens = split_spillover_tokens(raw)
    if not tokens:
        return None
    try:
        n = int(tokens[0])
    except Exception:
        return None
    if n <= 0:
        return None
    names = tokens[1 : 1 + n]
    vals = tokens[1 + n :]
    if len(names) != n or len(vals) < n * n:
        return None
    try:
        mat_vals = [float(x) for x in vals[: n * n]]
    except Exception:
        return None
    matrix = np.asarray(mat_vals, dtype=float).reshape((n, n))
    return {{"source_key": key_used, "channels": names, "matrix": matrix}}


def match_channel_index(pnn_labels: list[str], pns_labels: list[str], channel: str) -> int | None:
    if not channel:
        return None
    target = channel.strip().lower()
    pnn_lower = [c.lower() for c in pnn_labels]
    pns_lower = [c.lower() for c in pns_labels]
    if target in pnn_lower:
        return pnn_lower.index(target)
    if target in pns_lower:
        return pns_lower.index(target)
    for i, c in enumerate(pnn_lower):
        if target in c:
            return i
    for i, c in enumerate(pns_lower):
        if target in c:
            return i
    return None


def apply_compensation_if_possible(data: np.ndarray, spill: dict | None, pnn_labels: list[str], pns_labels: list[str]) -> tuple[np.ndarray, dict | None]:
    if spill is None:
        return data, None
    channels = spill.get("channels")
    matrix = spill.get("matrix")
    if not (isinstance(channels, list) and isinstance(matrix, np.ndarray)):
        return data, None
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or matrix.shape[0] != len(channels):
        return data, None

    idxs: list[int] = []
    for ch in channels:
        if not isinstance(ch, str):
            return data, None
        i = match_channel_index(pnn_labels, pns_labels, ch)
        if i is None:
            return data, None
        idxs.append(int(i))

    try:
        inv = np.linalg.inv(matrix.astype(float))
    except Exception:
        return data, {{"warning": "spillover_matrix_not_invertible", "channels": channels}}

    corrected = data.astype(float, copy=True)
    sub = corrected[:, idxs]
    corrected[:, idxs] = sub @ inv
    return corrected, {{"channels": channels, "method": "data @ inv(spillover)"}}


def gate_mask_threshold(data: np.ndarray, idx: int, op: str, thr: float) -> np.ndarray:
    col = data[:, idx]
    if op == ">":
        return col > thr
    if op == ">=":
        return col >= thr
    if op == "<":
        return col < thr
    if op == "<=":
        return col <= thr
    return col > thr


def gate_mask_rect2d(data: np.ndarray, x_idx: int, y_idx: int, x_min: float, x_max: float, y_min: float, y_max: float) -> np.ndarray:
    x = data[:, x_idx]
    y = data[:, y_idx]
    return (x >= x_min) & (x <= x_max) & (y >= y_min) & (y <= y_max)


def analyze(fcs_path: Path) -> dict:
    raw_bytes = fcs_path.read_bytes()
    fcs_sha256 = sha256_bytes(raw_bytes)

    fd = FlowData(str(fcs_path))
    text = getattr(fd, "text", {{}}) or {{}}
    pnn = list(getattr(fd, "pnn_labels", []) or [])
    pns = list(getattr(fd, "pns_labels", []) or [])
    pnr = list(getattr(fd, "pnr_values", []) or [])
    event_count_reported = int(getattr(fd, "event_count", 0) or 0)

    data = fd.as_array(preprocess=bool(PREPROCESS))
    if MAX_EVENTS is not None and data.shape[0] > int(MAX_EVENTS):
        data = data[: int(MAX_EVENTS), :]

    spill = parse_spillover(text if isinstance(text, dict) else {{}})
    comp_info = None
    if APPLY_COMPENSATION:
        data, comp_info = apply_compensation_if_possible(data, spill, pnn, pns)

    channels = []
    for i in range(int(data.shape[1])):
        channels.append(
            {{
                "index": int(i),
                "pnn": pnn[i] if i < len(pnn) else f"P{{i+1}}N",
                "pns": pns[i] if i < len(pns) else "",
                "pnr": pnr[i] if i < len(pnr) else None,
                "stats": channel_stats(data[:, i]),
            }}
        )

    total_mask = np.ones((data.shape[0],), dtype=bool)
    masks: dict[str, np.ndarray] = {{}}
    gate_results = []
    for g in GATES:
        if not isinstance(g, dict):
            continue
        gid = g.get("id")
        gtype = g.get("type")
        parent = g.get("parent")
        if not isinstance(gid, str) or not isinstance(gtype, str):
            continue

        parent_mask = masks.get(parent) if isinstance(parent, str) else total_mask
        if parent_mask is None:
            parent_mask = total_mask

        mask = None
        if gtype in ("threshold", "1d", "gate1d"):
            ch = g.get("channel")
            op = g.get("op") if isinstance(g.get("op"), str) else ">"
            try:
                thr = float(g.get("threshold"))
            except Exception:
                thr = None
            idx = match_channel_index(pnn, pns, ch) if isinstance(ch, str) else None
            if idx is not None and thr is not None:
                mask = gate_mask_threshold(data, int(idx), op, float(thr))
        elif gtype in ("rect", "rect2d", "gate2d"):
            xch = g.get("x_channel")
            ych = g.get("y_channel")
            try:
                x_min = float(g.get("x_min"))
                x_max = float(g.get("x_max"))
                y_min = float(g.get("y_min"))
                y_max = float(g.get("y_max"))
            except Exception:
                x_min = x_max = y_min = y_max = None
            x_idx = match_channel_index(pnn, pns, xch) if isinstance(xch, str) else None
            y_idx = match_channel_index(pnn, pns, ych) if isinstance(ych, str) else None
            if None not in (x_idx, y_idx, x_min, x_max, y_min, y_max):
                mask = gate_mask_rect2d(data, int(x_idx), int(y_idx), float(x_min), float(x_max), float(y_min), float(y_max))

        if mask is None:
            gate_results.append({{"id": gid, "type": gtype, "parent": parent, "error": "invalid_gate_spec"}})
            continue

        mask = mask & parent_mask
        masks[gid] = mask

        in_gate = int(np.sum(mask))
        parent_count = int(np.sum(parent_mask))
        total_count = int(np.sum(total_mask))
        frac_parent = float(in_gate / parent_count) if parent_count > 0 else None
        frac_total = float(in_gate / total_count) if total_count > 0 else None

        sens = None
        if gtype in ("threshold", "1d", "gate1d") and isinstance(g.get("threshold"), (int, float)) and isinstance(g.get("channel"), str):
            thr0 = float(g["threshold"])
            thr_lo = thr0 * (1.0 - SENSITIVITY_DELTA)
            thr_hi = thr0 * (1.0 + SENSITIVITY_DELTA)
            idx = match_channel_index(pnn, pns, g["channel"])
            if idx is not None:
                m_lo = gate_mask_threshold(data, int(idx), g.get("op") if isinstance(g.get("op"), str) else ">", thr_lo) & parent_mask
                m_hi = gate_mask_threshold(data, int(idx), g.get("op") if isinstance(g.get("op"), str) else ">", thr_hi) & parent_mask
                sens = {{
                    "delta_fraction": SENSITIVITY_DELTA,
                    "threshold_lo": thr_lo,
                    "threshold_hi": thr_hi,
                    "frac_parent_lo": float(np.sum(m_lo) / parent_count) if parent_count > 0 else None,
                    "frac_parent_hi": float(np.sum(m_hi) / parent_count) if parent_count > 0 else None,
                }}

        gate_results.append(
            {{
                "id": gid,
                "type": gtype,
                "parent": parent,
                "count_in_gate": in_gate,
                "count_parent": parent_count,
                "fraction_of_parent": frac_parent,
                "fraction_of_total": frac_total,
                "sensitivity": sens,
            }}
        )

    return {{
        "schema_version": "{FCS_ANALYSIS_SCHEMA_VERSION}",
        "generated_at": now_iso(),
        "analysis_signature": ANALYSIS_SIGNATURE,
        "input": {{
            "fcs_path": str(fcs_path),
            "fcs_sha256": fcs_sha256,
            "event_count_reported": event_count_reported,
            "event_count_analyzed": int(data.shape[0]),
            "preprocess": bool(PREPROCESS),
            "apply_compensation": bool(APPLY_COMPENSATION),
            "max_events": MAX_EVENTS,
        }},
        "channels": channels,
        "compensation": comp_info,
        "gates": gate_results,
    }}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: reproduce.py <path-to-fcs>", file=sys.stderr)
        raise SystemExit(2)
    payload = analyze(Path(sys.argv[1]))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
"""
    reproduce_physical.write_text(textwrap.dedent(repro), encoding="utf-8")

    artifacts = [
        _virtual_outputs_path(analysis_rel.as_posix()),
        _virtual_outputs_path(gates_rel.as_posix()),
        _virtual_outputs_path(channels_rel.as_posix()),
        _virtual_outputs_path(reproduce_rel.as_posix()),
    ]
    return payload, artifacts

