from __future__ import annotations

import hashlib
import json
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

OUTPUTS_VIRTUAL_PREFIX = "/mnt/user-data/outputs"

SPECTRUM_ANALYSIS_SCHEMA_VERSION = "deerflow.raw_data.spectrum_analysis.v1"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _virtual_outputs_path(relative: str) -> str:
    rel = Path(relative).as_posix().lstrip("/")
    return f"{OUTPUTS_VIRTUAL_PREFIX}/{rel}"


def _first_present(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols_lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in cols_lower:
            return cols_lower[cand.lower()]
    return None


def _safe_float_series(s: pd.Series) -> np.ndarray | None:
    try:
        v = pd.to_numeric(s, errors="coerce").to_numpy(dtype=float)
    except Exception:
        return None
    v = v[np.isfinite(v)]
    if v.size < 3:
        return None
    return v


def _peak_summary(x: np.ndarray, y: np.ndarray, *, max_peaks: int = 12) -> dict[str, Any]:
    if x.size < 5 or y.size < 5:
        return {"peaks_found": 0, "top_peaks": []}

    order = np.argsort(x)
    x2 = x[order]
    y2 = y[order]

    baseline = float(np.quantile(y2, 0.2))
    y_bc = y2 - baseline

    try:
        from scipy.signal import find_peaks, peak_prominences
    except Exception:
        idxs = np.argsort(-y_bc)[: max(0, min(max_peaks, y_bc.size))]
        idxs = np.sort(idxs)
        peaks = idxs
        prominences = np.asarray([0.0] * int(peaks.size), dtype=float)
    else:
        thr = float(np.quantile(y_bc, 0.85)) if y_bc.size >= 10 else float(np.max(y_bc)) * 0.5
        thr = max(1e-12, thr)
        peaks, _ = find_peaks(y_bc, prominence=thr * 0.25)
        prominences = peak_prominences(y_bc, peaks)[0] if peaks.size > 0 else np.asarray([], dtype=float)

    noise = float(np.std(y_bc[y_bc <= np.quantile(y_bc, 0.6)])) if y_bc.size >= 10 else float(np.std(y_bc))
    noise = max(1e-12, noise)

    rows: list[dict[str, Any]] = []
    for i, p in enumerate(peaks[:max_peaks], start=1):
        px = float(x2[int(p)])
        py = float(y2[int(p)])
        prom = float(prominences[i - 1]) if i - 1 < int(prominences.size) else 0.0
        snr = float(max(0.0, (py - baseline)) / noise)
        rows.append(
            {
                "rank": i,
                "x": px,
                "y": py,
                "baseline": baseline,
                "y_minus_baseline": float(py - baseline),
                "prominence_y_minus_baseline": prom,
                "snr_estimate": snr,
            }
        )

    top = sorted(rows, key=lambda r: float(r.get("snr_estimate") or 0.0), reverse=True)[: min(6, len(rows))]
    return {
        "baseline_estimate": baseline,
        "noise_estimate_std": noise,
        "peaks_found": len(rows),
        "top_peaks": top,
        "note": "Peaks derived from numeric CSV; choose x/y columns carefully for audit.",
    }


def analyze_spectrum_csv_files(
    *,
    csv_paths: list[Path],
    outputs_dir: Path,
    x_col: str | None = None,
    y_col: str | None = None,
    artifact_subdir: str = "scientific-vision/raw-data/spectrum",
) -> tuple[dict[str, Any], list[str]]:
    """Analyze spectrum CSV(s) and generate audit artifacts + reproduction script.

    Expected CSV shape: at least two numeric columns: x (wavelength/frequency/mz) and y (intensity/absorbance).
    """
    if not csv_paths:
        raise ValueError("csv_paths must be non-empty")

    inputs: list[dict[str, Any]] = []
    for p in csv_paths:
        b = p.read_bytes()
        inputs.append({"path": str(p), "sha256": _sha256_bytes(b), "bytes": len(b)})

    config_blob = json.dumps(
        {
            "schema": SPECTRUM_ANALYSIS_SCHEMA_VERSION,
            "inputs": [{"sha256": i["sha256"], "bytes": i["bytes"]} for i in inputs],
            "x_col": x_col,
            "y_col": y_col,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    analysis_sig = _sha256_text(config_blob)

    base = Path(artifact_subdir.strip("/")) / f"batch-{analysis_sig[:12]}"
    analysis_rel = base / "analysis.json"
    table_rel = base / "summary.csv"
    reproduce_rel = base / "reproduce.py"

    analysis_physical = outputs_dir / analysis_rel
    analysis_physical.parent.mkdir(parents=True, exist_ok=True)

    runs: list[dict[str, Any]] = []
    table_rows: list[dict[str, Any]] = []

    for entry in inputs:
        p = Path(entry["path"])
        df = pd.read_csv(p)
        if df.empty:
            runs.append({"input": entry, "error": "empty_csv"})
            continue

        x_name = x_col if isinstance(x_col, str) and x_col in df.columns else None
        y_name = y_col if isinstance(y_col, str) and y_col in df.columns else None
        if x_name is None:
            x_name = _first_present(df, ["wavelength", "wave_length", "wn", "wavenumber", "frequency", "mz", "m_z", "x"])
        if y_name is None:
            y_name = _first_present(df, ["intensity", "absorbance", "signal", "counts", "y"])

        if x_name is None or y_name is None:
            runs.append({"input": entry, "error": "missing_xy_columns", "columns": list(df.columns)[:80]})
            continue

        x = _safe_float_series(df[x_name])
        y = _safe_float_series(df[y_name])
        if x is None or y is None:
            runs.append({"input": entry, "error": "non_numeric_xy"})
            continue
        n = int(min(x.size, y.size))
        x = x[:n]
        y = y[:n]

        order = np.argsort(x)
        xs = x[order]
        ys = y[order]
        auc = float(np.trapz(ys, xs)) if xs.size >= 2 else None
        peak_info = _peak_summary(xs, ys)

        out: dict[str, Any] = {
            "input": entry,
            "n": n,
            "x_col": x_name,
            "y_col": y_name,
            "x_min": float(np.min(xs)) if xs.size else None,
            "x_max": float(np.max(xs)) if xs.size else None,
            "y_min": float(np.min(ys)) if ys.size else None,
            "y_max": float(np.max(ys)) if ys.size else None,
            "y_mean": float(np.mean(ys)) if ys.size else None,
            "y_std": float(np.std(ys)) if ys.size else None,
            "auc_trapezoid": auc,
            "peaks": peak_info,
        }
        runs.append(out)

        top_peaks = (peak_info or {}).get("top_peaks") if isinstance(peak_info, dict) else None
        top0 = top_peaks[0] if isinstance(top_peaks, list) and top_peaks else {}
        table_rows.append(
            {
                "csv_sha256": entry["sha256"],
                "n": n,
                "x_col": x_name,
                "y_col": y_name,
                "x_min": out.get("x_min"),
                "x_max": out.get("x_max"),
                "y_mean": out.get("y_mean"),
                "y_std": out.get("y_std"),
                "auc_trapezoid": auc,
                "peaks_found": (peak_info or {}).get("peaks_found") if isinstance(peak_info, dict) else "",
                "top_peak_x": top0.get("x") if isinstance(top0, dict) else "",
                "top_peak_snr": top0.get("snr_estimate") if isinstance(top0, dict) else "",
            }
        )

    payload: dict[str, Any] = {
        "schema_version": SPECTRUM_ANALYSIS_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "analysis_signature": analysis_sig,
        "inputs": inputs,
        "runs": runs,
        "notes": [
            "This tool computes auditable numeric metrics from CSV spectra; it does not infer axis calibration beyond the provided x column.",
            "If your spectrum is baseline-corrected / normalized upstream, include that provenance alongside the CSV.",
        ],
    }

    analysis_physical.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    table_physical = outputs_dir / table_rel
    pd.DataFrame(table_rows).to_csv(table_physical, index=False)

    reproduce_physical = outputs_dir / reproduce_rel
    repro = f"""\
#!/usr/bin/env python
# Auto-generated by DeerFlow ({SPECTRUM_ANALYSIS_SCHEMA_VERSION})
#
# Usage:
#   python reproduce.py <csv1> [<csv2> ...]
#

import json
import sys

import numpy as np
import pandas as pd


def first_present(df, candidates):
    cols = {{c.lower(): c for c in df.columns}}
    for cand in candidates:
        if cand.lower() in cols:
            return cols[cand.lower()]
    return None


def peak_summary(x, y, max_peaks=12):
    order = np.argsort(x)
    x2 = x[order]
    y2 = y[order]
    baseline = float(np.quantile(y2, 0.2))
    y_bc = y2 - baseline
    try:
        from scipy.signal import find_peaks, peak_prominences
    except Exception:
        idxs = np.argsort(-y_bc)[: max(0, min(max_peaks, y_bc.size))]
        peaks = np.sort(idxs)
        prominences = np.asarray([0.0] * int(peaks.size), dtype=float)
    else:
        thr = float(np.quantile(y_bc, 0.85)) if y_bc.size >= 10 else float(np.max(y_bc)) * 0.5
        thr = max(1e-12, thr)
        peaks, _ = find_peaks(y_bc, prominence=thr * 0.25)
        prominences = peak_prominences(y_bc, peaks)[0] if peaks.size > 0 else np.asarray([], dtype=float)
    noise = float(np.std(y_bc[y_bc <= np.quantile(y_bc, 0.6)])) if y_bc.size >= 10 else float(np.std(y_bc))
    noise = max(1e-12, noise)
    rows = []
    for i, p in enumerate(peaks[:max_peaks], start=1):
        px = float(x2[int(p)])
        py = float(y2[int(p)])
        prom = float(prominences[i - 1]) if i - 1 < int(prominences.size) else 0.0
        snr = float(max(0.0, (py - baseline)) / noise)
        rows.append({{"rank": i, "x": px, "y": py, "baseline": baseline, "y_minus_baseline": float(py - baseline), "prominence_y_minus_baseline": prom, "snr_estimate": snr}})
    top = sorted(rows, key=lambda r: float(r.get("snr_estimate") or 0.0), reverse=True)[: min(6, len(rows))]
    return {{"baseline_estimate": baseline, "noise_estimate_std": noise, "peaks_found": len(rows), "top_peaks": top}}


def analyze_one(path: str):
    df = pd.read_csv(path)
    x = {json.dumps(x_col) if x_col else "None"}
    y = {json.dumps(y_col) if y_col else "None"}
    if x is None:
        x = first_present(df, ["wavelength","wave_length","wn","wavenumber","frequency","mz","m_z","x"])
    if y is None:
        y = first_present(df, ["intensity","absorbance","signal","counts","y"])
    if x is None or y is None:
        return {{"path": path, "error": "missing_xy_columns", "columns": list(df.columns)}}
    xv = pd.to_numeric(df[x], errors="coerce").to_numpy(dtype=float)
    yv = pd.to_numeric(df[y], errors="coerce").to_numpy(dtype=float)
    mask = np.isfinite(xv) & np.isfinite(yv)
    xv = xv[mask]
    yv = yv[mask]
    if xv.size < 3:
        return {{"path": path, "error": "non_numeric_xy"}}
    auc = float(np.trapz(yv[np.argsort(xv)], np.sort(xv))) if xv.size >= 2 else None
    return {{
        "path": path,
        "n": int(xv.size),
        "x_col": x,
        "y_col": y,
        "x_min": float(np.min(xv)),
        "x_max": float(np.max(xv)),
        "y_mean": float(np.mean(yv)),
        "y_std": float(np.std(yv)),
        "auc_trapezoid": auc,
        "peaks": peak_summary(xv, yv),
    }}


def main(argv):
    payload = {{
        "schema_version": "{SPECTRUM_ANALYSIS_SCHEMA_VERSION}",
        "generated_at": "{_now_iso()}",
        "analysis_signature": "{analysis_sig}",
        "runs": [analyze_one(a) for a in argv],
    }}
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: reproduce.py <csv1> [<csv2> ...]", file=sys.stderr)
        raise SystemExit(2)
    main(sys.argv[1:])
"""
    reproduce_physical.write_text(textwrap.dedent(repro), encoding="utf-8")

    artifacts = [
        _virtual_outputs_path(analysis_rel.as_posix()),
        _virtual_outputs_path(table_rel.as_posix()),
        _virtual_outputs_path(reproduce_rel.as_posix()),
    ]
    return payload, artifacts

