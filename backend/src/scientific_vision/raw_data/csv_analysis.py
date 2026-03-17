from __future__ import annotations

import hashlib
import json
import math
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

CSV_ANALYSIS_SCHEMA_VERSION = "deerflow.raw_data.csv_analysis.v1"
OUTPUTS_VIRTUAL_PREFIX = "/mnt/user-data/outputs"


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


def _pick_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols = {c.lower(): c for c in df.columns if isinstance(c, str)}
    for cand in candidates:
        if cand.lower() in cols:
            return cols[cand.lower()]
    return None


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _knn_batch_mixing_score(xy: np.ndarray, batch: np.ndarray, k: int = 30, max_points: int = 50_000) -> dict[str, Any]:
    """Compute a simple batch-mixing index in embedding space.

    mixing_index = mean fraction of kNN that share the same batch label.
    Higher => stronger batch clustering (worse mixing).
    """
    n = int(xy.shape[0])
    if n == 0:
        return {"n": 0}
    if n > max_points:
        idx = np.random.default_rng(0).choice(n, size=max_points, replace=False)
        xy = xy[idx]
        batch = batch[idx]
        n = int(xy.shape[0])

    # Pairwise distances via chunked dot products would be heavy; use sklearn if available.
    try:
        from sklearn.neighbors import NearestNeighbors
    except Exception:
        return {"n": n, "warning": "sklearn_missing"}

    k_eff = int(min(max(2, k), max(2, n - 1)))
    nn = NearestNeighbors(n_neighbors=k_eff + 1, algorithm="auto")
    nn.fit(xy)
    _d, idxs = nn.kneighbors(xy, n_neighbors=k_eff + 1, return_distance=True)
    idxs = idxs[:, 1:]  # drop self
    same = (batch[idxs] == batch[:, None]).astype(np.float64)
    frac_same = np.mean(same, axis=1)
    return {
        "n": n,
        "k": k_eff,
        "mixing_index_mean_same_batch_frac": float(np.mean(frac_same)),
        "mixing_index_median_same_batch_frac": float(np.median(frac_same)),
        "mixing_index_p05_same_batch_frac": float(np.percentile(frac_same, 5)),
        "mixing_index_p95_same_batch_frac": float(np.percentile(frac_same, 95)),
        "interpretation": "Higher means stronger batch clustering (worse mixing).",
    }


def analyze_embedding_csv(
    *,
    csv_path: Path,
    outputs_dir: Path,
    artifact_subdir: str = "scientific-vision/raw-data/embedding",
    x_col: str | None = None,
    y_col: str | None = None,
    batch_col: str | None = None,
    cluster_col: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    raw_bytes = csv_path.read_bytes()
    csv_sha256 = _sha256_bytes(raw_bytes)

    df = pd.read_csv(csv_path)
    if df.empty:
        raise ValueError("CSV is empty")

    x = x_col or _pick_column(df, ["x", "tsne_1", "tsne1", "umap_1", "umap1", "dim1", "pc1"])
    y = y_col or _pick_column(df, ["y", "tsne_2", "tsne2", "umap_2", "umap2", "dim2", "pc2"])
    if not x or not y:
        raise ValueError("Cannot infer embedding columns (x/y). Provide x_col/y_col.")

    batch = batch_col or _pick_column(df, ["batch", "donor", "sample", "run", "plate"])
    cluster = cluster_col or _pick_column(df, ["cluster", "label", "cell_type", "group"])

    xy = df[[x, y]].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    mask = np.isfinite(xy).all(axis=1)
    df2 = df.loc[mask].copy()
    xy = xy[mask]

    n = int(xy.shape[0])
    if n < 5:
        raise ValueError("Too few valid points after numeric coercion")

    # Basic stats
    centroid = xy.mean(axis=0)
    spread = xy.std(axis=0)

    batch_summary: dict[str, Any] | None = None
    mixing: dict[str, Any] | None = None
    if batch and batch in df2.columns:
        b = df2[batch].astype(str).to_numpy()
        counts = {str(k): int(v) for k, v in pd.Series(b).value_counts().head(50).to_dict().items()}
        # per-batch centroid distances
        centroids = []
        for name, g in df2.groupby(batch):
            pts = g[[x, y]].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
            pts = pts[np.isfinite(pts).all(axis=1)]
            if pts.shape[0] < 5:
                continue
            c = pts.mean(axis=0)
            centroids.append({"batch": str(name), "n": int(pts.shape[0]), "cx": float(c[0]), "cy": float(c[1])})
        batch_summary = {"batch_col": batch, "counts_top50": counts, "centroids": centroids[:200]}
        mixing = _knn_batch_mixing_score(xy, b, k=30)

    cluster_summary: dict[str, Any] | None = None
    silhouette: float | None = None
    if cluster and cluster in df2.columns:
        labels = df2[cluster].astype(str).to_numpy()
        counts = {str(k): int(v) for k, v in pd.Series(labels).value_counts().head(50).to_dict().items()}
        cluster_summary = {"cluster_col": cluster, "counts_top50": counts}
        try:
            from sklearn.metrics import silhouette_score

            # Only compute when >1 cluster and not too many unique labels
            if len(set(labels.tolist())) >= 2 and len(set(labels.tolist())) <= 200:
                silhouette = float(silhouette_score(xy, labels))
        except Exception:
            silhouette = None

    config_blob = json.dumps(
        {
            "schema": CSV_ANALYSIS_SCHEMA_VERSION,
            "kind": "embedding",
            "x_col": x,
            "y_col": y,
            "batch_col": batch,
            "cluster_col": cluster,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    analysis_sig = _sha256_text(config_blob)

    base = Path(artifact_subdir.strip("/")) / f"sha256-{csv_sha256}"
    analysis_rel = base / f"analysis-{analysis_sig[:12]}.json"
    reproduce_rel = base / f"reproduce-{analysis_sig[:12]}.py"

    payload: dict[str, Any] = {
        "schema_version": CSV_ANALYSIS_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "kind": "embedding",
        "input": {"csv_path": str(csv_path), "csv_sha256": csv_sha256, "n_total": int(df.shape[0]), "n_used": n},
        "columns": {"x": x, "y": y, "batch": batch, "cluster": cluster},
        "summary": {
            "centroid": {"x": float(centroid[0]), "y": float(centroid[1])},
            "spread_std": {"x": float(spread[0]), "y": float(spread[1])},
            "silhouette_score": silhouette,
        },
        "batch": batch_summary,
        "mixing": mixing,
        "cluster": cluster_summary,
        "analysis_signature": analysis_sig,
        "notes": [
            "This analysis is computed from raw embedding CSV. If the embedding parameters (perplexity/min_dist) vary across runs, provide them to interpret parameter dependence.",
        ],
    }

    _write_json(outputs_dir / analysis_rel, payload)

    repro = f"""\
#!/usr/bin/env python
# Auto-generated by DeerFlow ({CSV_ANALYSIS_SCHEMA_VERSION}) - embedding
import pandas as pd
import numpy as np

CSV_PATH = r\"\"\"{str(csv_path)}\"\"\"
X_COL = {x!r}
Y_COL = {y!r}
BATCH_COL = {batch!r}
CLUSTER_COL = {cluster!r}

df = pd.read_csv(CSV_PATH)
xy = df[[X_COL, Y_COL]].apply(pd.to_numeric, errors='coerce').to_numpy(dtype=float)
mask = np.isfinite(xy).all(axis=1)
df = df.loc[mask].copy()
xy = xy[mask]
print('n_used', xy.shape[0])
print('centroid', xy.mean(axis=0))
if BATCH_COL and BATCH_COL in df.columns:
    print('batch_counts', df[BATCH_COL].astype(str).value_counts().head(20).to_dict())
if CLUSTER_COL and CLUSTER_COL in df.columns:
    print('cluster_counts', df[CLUSTER_COL].astype(str).value_counts().head(20).to_dict())
"""
    _write_text(outputs_dir / reproduce_rel, textwrap.dedent(repro))

    return payload, [_virtual_outputs_path(analysis_rel.as_posix()), _virtual_outputs_path(reproduce_rel.as_posix())]


def analyze_spectrum_csv(
    *,
    csv_path: Path,
    outputs_dir: Path,
    artifact_subdir: str = "scientific-vision/raw-data/spectrum",
    x_col: str | None = None,
    y_col: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    raw_bytes = csv_path.read_bytes()
    csv_sha256 = _sha256_bytes(raw_bytes)
    df = pd.read_csv(csv_path)
    if df.empty:
        raise ValueError("CSV is empty")

    x = x_col or _pick_column(df, ["wavelength", "lambda", "x", "nm", "freq", "frequency"])
    y = y_col or _pick_column(df, ["intensity", "flux", "y", "signal", "counts"])
    if not x or not y:
        raise ValueError("Cannot infer spectrum columns. Provide x_col/y_col.")

    xs = pd.to_numeric(df[x], errors="coerce").to_numpy(dtype=np.float64)
    ys = pd.to_numeric(df[y], errors="coerce").to_numpy(dtype=np.float64)
    mask = np.isfinite(xs) & np.isfinite(ys)
    xs = xs[mask]
    ys = ys[mask]
    if xs.size < 10:
        raise ValueError("Too few valid points after numeric coercion")

    # sort by x
    order = np.argsort(xs)
    xs = xs[order]
    ys = ys[order]

    # smooth
    try:
        from scipy.signal import find_peaks, peak_prominences, savgol_filter
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("scipy is required for spectrum analysis") from exc

    win = int(min(51, max(7, (xs.size // 20) | 1)))  # odd window
    smooth = savgol_filter(ys, window_length=win, polyorder=3, mode="interp")

    # baseline noise
    resid = ys - smooth
    noise = float(np.std(resid)) if resid.size > 0 else 1.0
    noise = max(1e-12, noise)

    peaks, props = find_peaks(smooth, prominence=max(noise * 3.0, float(np.percentile(np.abs(smooth), 80)) * 0.05))
    prominences = peak_prominences(smooth, peaks)[0] if peaks.size > 0 else np.asarray([], dtype=np.float64)

    peak_rows: list[dict[str, Any]] = []
    for i, p in enumerate(peaks[:20], start=1):
        x0 = float(xs[int(p)])
        y0 = float(smooth[int(p)])
        prom = float(prominences[i - 1]) if i - 1 < prominences.size else 0.0
        snr = float((y0) / noise)
        peak_rows.append({"id": f"P{i}", "x": x0, "y_smooth": y0, "prominence": prom, "snr_estimate": snr})

    config_blob = json.dumps(
        {"schema": CSV_ANALYSIS_SCHEMA_VERSION, "kind": "spectrum", "x_col": x, "y_col": y},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    analysis_sig = _sha256_text(config_blob)
    base = Path(artifact_subdir.strip("/")) / f"sha256-{csv_sha256}"
    analysis_rel = base / f"analysis-{analysis_sig[:12]}.json"
    reproduce_rel = base / f"reproduce-{analysis_sig[:12]}.py"

    payload: dict[str, Any] = {
        "schema_version": CSV_ANALYSIS_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "kind": "spectrum",
        "input": {"csv_path": str(csv_path), "csv_sha256": csv_sha256, "n_used": int(xs.size)},
        "columns": {"x": x, "y": y},
        "summary": {
            "x_min": float(xs.min()),
            "x_max": float(xs.max()),
            "y_min": float(ys.min()),
            "y_max": float(ys.max()),
            "noise_std_estimate": noise,
            "peaks_found": len(peak_rows),
            "top_peaks": sorted(peak_rows, key=lambda r: float(r.get("snr_estimate") or 0.0), reverse=True)[:8],
        },
        "peaks": peak_rows,
        "analysis_signature": analysis_sig,
    }
    _write_json(outputs_dir / analysis_rel, payload)

    repro = f"""\
#!/usr/bin/env python
# Auto-generated by DeerFlow ({CSV_ANALYSIS_SCHEMA_VERSION}) - spectrum
import pandas as pd
import numpy as np
from scipy.signal import savgol_filter, find_peaks, peak_prominences

CSV_PATH = r\"\"\"{str(csv_path)}\"\"\"
X_COL = {x!r}
Y_COL = {y!r}

df = pd.read_csv(CSV_PATH)
xs = pd.to_numeric(df[X_COL], errors='coerce').to_numpy(dtype=float)
ys = pd.to_numeric(df[Y_COL], errors='coerce').to_numpy(dtype=float)
mask = np.isfinite(xs) & np.isfinite(ys)
xs, ys = xs[mask], ys[mask]
order = np.argsort(xs)
xs, ys = xs[order], ys[order]
win = int(min(51, max(7, (xs.size // 20) | 1)))
smooth = savgol_filter(ys, window_length=win, polyorder=3, mode='interp')
noise = float(np.std(ys - smooth))
peaks, _ = find_peaks(smooth, prominence=max(noise*3.0, float(np.percentile(np.abs(smooth),80))*0.05))
prom = peak_prominences(smooth, peaks)[0] if peaks.size else np.array([])
for i, p in enumerate(peaks[:20], start=1):
    x0 = float(xs[int(p)])
    y0 = float(smooth[int(p)])
    pr = float(prom[i-1]) if i-1 < prom.size else 0.0
    print(i, x0, y0, pr, y0/max(1e-12, noise))
"""
    _write_text(outputs_dir / reproduce_rel, textwrap.dedent(repro))

    return payload, [_virtual_outputs_path(analysis_rel.as_posix()), _virtual_outputs_path(reproduce_rel.as_posix())]


def analyze_densitometry_csv(
    *,
    csv_path: Path,
    outputs_dir: Path,
    artifact_subdir: str = "scientific-vision/raw-data/densitometry",
    lane_col: str | None = None,
    target_col: str | None = None,
    control_col: str | None = None,
    group_col: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    raw_bytes = csv_path.read_bytes()
    csv_sha256 = _sha256_bytes(raw_bytes)
    df = pd.read_csv(csv_path)
    if df.empty:
        raise ValueError("CSV is empty")

    lane = lane_col or _pick_column(df, ["lane", "sample", "condition", "id"])
    target = target_col or _pick_column(df, ["target", "band", "intensity", "signal", "target_intensity"])
    control = control_col or _pick_column(df, ["control", "loading", "actin", "gapdh", "tubulin", "control_intensity"])
    group = group_col or _pick_column(df, ["group", "condition", "treatment", "genotype"])
    if not target or not control:
        raise ValueError("Cannot infer target/control columns. Provide target_col/control_col.")

    df2 = df.copy()
    df2[target] = pd.to_numeric(df2[target], errors="coerce")
    df2[control] = pd.to_numeric(df2[control], errors="coerce")
    df2 = df2[np.isfinite(df2[target]) & np.isfinite(df2[control])].copy()
    if df2.empty:
        raise ValueError("No valid numeric rows after coercion")

    df2["normalized"] = df2[target] / df2[control].replace(0, np.nan)
    df2 = df2[np.isfinite(df2["normalized"])].copy()
    if df2.empty:
        raise ValueError("Normalization produced no valid rows (control may be zero)")

    # Fold change vs first group or global median
    baseline = float(np.median(df2["normalized"].to_numpy(dtype=np.float64)))
    df2["fold_vs_median"] = df2["normalized"] / baseline if baseline != 0 else np.nan

    group_summary: list[dict[str, Any]] = []
    if group and group in df2.columns:
        for name, g in df2.groupby(group):
            v = g["normalized"].to_numpy(dtype=np.float64)
            group_summary.append(
                {
                    "group": str(name),
                    "n": int(v.size),
                    "mean": float(np.mean(v)),
                    "median": float(np.median(v)),
                    "std": float(np.std(v)),
                }
            )

    config_blob = json.dumps(
        {"schema": CSV_ANALYSIS_SCHEMA_VERSION, "kind": "densitometry", "lane_col": lane, "target_col": target, "control_col": control, "group_col": group},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    analysis_sig = _sha256_text(config_blob)
    base = Path(artifact_subdir.strip("/")) / f"sha256-{csv_sha256}"
    analysis_rel = base / f"analysis-{analysis_sig[:12]}.json"
    normalized_rel = base / f"normalized-{analysis_sig[:12]}.csv"
    reproduce_rel = base / f"reproduce-{analysis_sig[:12]}.py"

    payload: dict[str, Any] = {
        "schema_version": CSV_ANALYSIS_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "kind": "densitometry",
        "input": {"csv_path": str(csv_path), "csv_sha256": csv_sha256, "n_used": int(df2.shape[0])},
        "columns": {"lane": lane, "target": target, "control": control, "group": group},
        "summary": {"baseline_median_normalized": baseline},
        "group_summary": group_summary or None,
        "analysis_signature": analysis_sig,
    }
    _write_json(outputs_dir / analysis_rel, payload)

    # normalized CSV
    norm_physical = outputs_dir / normalized_rel
    norm_physical.parent.mkdir(parents=True, exist_ok=True)
    cols = [c for c in [lane, group, target, control] if c and c in df2.columns]
    cols += ["normalized", "fold_vs_median"]
    df2[cols].to_csv(norm_physical, index=False)

    repro = f"""\
#!/usr/bin/env python
# Auto-generated by DeerFlow ({CSV_ANALYSIS_SCHEMA_VERSION}) - densitometry
import pandas as pd
import numpy as np

CSV_PATH = r\"\"\"{str(csv_path)}\"\"\"
LANE_COL = {lane!r}
TARGET_COL = {target!r}
CONTROL_COL = {control!r}
GROUP_COL = {group!r}

df = pd.read_csv(CSV_PATH)
df[TARGET_COL] = pd.to_numeric(df[TARGET_COL], errors='coerce')
df[CONTROL_COL] = pd.to_numeric(df[CONTROL_COL], errors='coerce')
df = df[np.isfinite(df[TARGET_COL]) & np.isfinite(df[CONTROL_COL])].copy()
df['normalized'] = df[TARGET_COL] / df[CONTROL_COL].replace(0, np.nan)
df = df[np.isfinite(df['normalized'])].copy()
baseline = float(np.median(df['normalized'].to_numpy(dtype=float)))
df['fold_vs_median'] = df['normalized'] / baseline if baseline else np.nan
print('baseline_median_normalized', baseline)
print(df[[c for c in [LANE_COL, GROUP_COL] if c and c in df.columns] + ['normalized','fold_vs_median']].head(20))
"""
    _write_text(outputs_dir / reproduce_rel, textwrap.dedent(repro))

    return payload, [
        _virtual_outputs_path(analysis_rel.as_posix()),
        _virtual_outputs_path(normalized_rel.as_posix()),
        _virtual_outputs_path(reproduce_rel.as_posix()),
    ]

