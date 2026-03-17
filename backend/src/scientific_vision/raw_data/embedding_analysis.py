from __future__ import annotations

import hashlib
import json
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import silhouette_score
from sklearn.neighbors import NearestNeighbors

OUTPUTS_VIRTUAL_PREFIX = "/mnt/user-data/outputs"

EMBEDDING_ANALYSIS_SCHEMA_VERSION = "deerflow.raw_data.embedding_analysis.v1"


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


def _knn_batch_mixing_score(xy: np.ndarray, batch: np.ndarray, k: int = 30) -> dict[str, Any] | None:
    n = int(xy.shape[0])
    if n < 5:
        return None
    unique = np.unique(batch)
    if unique.size < 2:
        return None
    k_eff = int(min(max(3, k), n - 1))
    nn = NearestNeighbors(n_neighbors=k_eff + 1, algorithm="auto")
    nn.fit(xy)
    _dist, idxs = nn.kneighbors(xy, return_distance=True)
    # drop self (first neighbor)
    idxs = idxs[:, 1:]
    neighbor_batch = batch[idxs]
    same = neighbor_batch == batch[:, None]
    same_frac = np.mean(same, axis=1)
    mixing = float(1.0 - np.mean(same_frac))
    return {
        "k": k_eff,
        "mixing_score": mixing,
        "same_batch_fraction_mean": float(np.mean(same_frac)),
        "note": "mixing_score = 1 - mean(fraction of same-batch neighbors); higher means better mixing",
    }


def analyze_embedding_csv_files(
    *,
    csv_paths: list[Path],
    outputs_dir: Path,
    x_col: str | None = None,
    y_col: str | None = None,
    cluster_col: str | None = None,
    batch_col: str | None = None,
    knn_k: int = 30,
    artifact_subdir: str = "scientific-vision/raw-data/embedding",
) -> tuple[dict[str, Any], list[str]]:
    """Analyze embedding CSV(s) for cluster separation and batch effects.

    Returns:
        (payload_dict, artifact_virtual_paths)
    """
    if not csv_paths:
        raise ValueError("csv_paths must be non-empty")

    inputs: list[dict[str, Any]] = []
    for p in csv_paths:
        b = p.read_bytes()
        inputs.append({"path": str(p), "sha256": _sha256_bytes(b), "bytes": len(b)})

    config_blob = json.dumps(
        {
            "schema": EMBEDDING_ANALYSIS_SCHEMA_VERSION,
            "inputs": [{"sha256": i["sha256"], "bytes": i["bytes"]} for i in inputs],
            "x_col": x_col,
            "y_col": y_col,
            "cluster_col": cluster_col,
            "batch_col": batch_col,
            "knn_k": int(knn_k),
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
            x_name = _first_present(df, ["tsne_1", "tsne1", "tSNE1", "umap_1", "umap1", "x"])
        if y_name is None:
            y_name = _first_present(df, ["tsne_2", "tsne2", "tSNE2", "umap_2", "umap2", "y"])
        if x_name is None or y_name is None:
            runs.append({"input": entry, "error": "missing_embedding_columns", "columns": list(df.columns)[:50]})
            continue

        xy = df[[x_name, y_name]].to_numpy(dtype=float)
        n = int(xy.shape[0])

        cluster_name = cluster_col if isinstance(cluster_col, str) and cluster_col in df.columns else None
        if cluster_name is None:
            cluster_name = _first_present(df, ["cluster", "clusters", "label", "cell_type", "celltype", "group"])

        batch_name = batch_col if isinstance(batch_col, str) and batch_col in df.columns else None
        if batch_name is None:
            batch_name = _first_present(df, ["batch", "sample", "donor", "condition"])

        out: dict[str, Any] = {"input": entry, "n": n, "x_col": x_name, "y_col": y_name, "cluster_col": cluster_name, "batch_col": batch_name}

        # Cluster separation
        if cluster_name and cluster_name in df.columns:
            labels = df[cluster_name].astype(str).to_numpy()
            uniq = np.unique(labels)
            if uniq.size >= 2 and uniq.size < n:
                try:
                    out["silhouette_cluster"] = float(silhouette_score(xy, labels))
                except Exception:
                    out["silhouette_cluster"] = None
            out["cluster_count"] = int(uniq.size)
        else:
            out["silhouette_cluster"] = None
            out["cluster_count"] = None

        # Batch effect
        if batch_name and batch_name in df.columns:
            batches = df[batch_name].astype(str).to_numpy()
            uniq_b = np.unique(batches)
            out["batch_count"] = int(uniq_b.size)
            if uniq_b.size >= 2 and uniq_b.size < n:
                try:
                    out["silhouette_batch"] = float(silhouette_score(xy, batches))
                except Exception:
                    out["silhouette_batch"] = None
            out["knn_batch_mixing"] = _knn_batch_mixing_score(xy, batches, k=int(knn_k))
        else:
            out["silhouette_batch"] = None
            out["batch_count"] = None
            out["knn_batch_mixing"] = None

        runs.append(out)

        table_rows.append(
            {
                "csv_sha256": entry["sha256"],
                "n": n,
                "x_col": x_name,
                "y_col": y_name,
                "cluster_col": cluster_name or "",
                "batch_col": batch_name or "",
                "silhouette_cluster": out.get("silhouette_cluster"),
                "silhouette_batch": out.get("silhouette_batch"),
                "knn_k": (out.get("knn_batch_mixing") or {}).get("k") if isinstance(out.get("knn_batch_mixing"), dict) else "",
                "knn_mixing_score": (out.get("knn_batch_mixing") or {}).get("mixing_score") if isinstance(out.get("knn_batch_mixing"), dict) else "",
            }
        )

    payload: dict[str, Any] = {
        "schema_version": EMBEDDING_ANALYSIS_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "analysis_signature": analysis_sig,
        "inputs": inputs,
        "runs": runs,
        "notes": [
            "Silhouette scores are computed in 2D embedding space (x_col, y_col).",
            "Batch mixing uses kNN in embedding space; prefer raw high-dimensional data for definitive batch effect diagnostics.",
        ],
    }

    analysis_physical.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # CSV summary
    table_physical = outputs_dir / table_rel
    pd.DataFrame(table_rows).to_csv(table_physical, index=False)

    # Reproduce script (lightweight; relies on pandas/numpy/sklearn)
    reproduce_physical = outputs_dir / reproduce_rel
    repro = f"""\
#!/usr/bin/env python
# Auto-generated by DeerFlow ({EMBEDDING_ANALYSIS_SCHEMA_VERSION})
#
# Usage:
#   python reproduce.py <csv1> [<csv2> ...]
#

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import silhouette_score
from sklearn.neighbors import NearestNeighbors


def first_present(df, candidates):
    cols = {{c.lower(): c for c in df.columns}}
    for cand in candidates:
        if cand.lower() in cols:
            return cols[cand.lower()]
    return None


def knn_mixing(xy, batch, k=30):
    n = xy.shape[0]
    if n < 5:
        return None
    uniq = np.unique(batch)
    if uniq.size < 2:
        return None
    k_eff = int(min(max(3, k), n - 1))
    nn = NearestNeighbors(n_neighbors=k_eff + 1)
    nn.fit(xy)
    _d, idxs = nn.kneighbors(xy)
    idxs = idxs[:, 1:]
    nb = batch[idxs]
    same = nb == batch[:, None]
    same_frac = np.mean(same, axis=1)
    return {{
        "k": k_eff,
        "mixing_score": float(1.0 - np.mean(same_frac)),
        "same_batch_fraction_mean": float(np.mean(same_frac)),
    }}


def analyze_one(path: str):
    df = pd.read_csv(path)
    x = {json.dumps(x_col) if x_col else "None"}
    y = {json.dumps(y_col) if y_col else "None"}
    if x is None:
        x = first_present(df, ["tsne_1","tsne1","tSNE1","umap_1","umap1","x"])
    if y is None:
        y = first_present(df, ["tsne_2","tsne2","tSNE2","umap_2","umap2","y"])
    if x is None or y is None:
        return {{"path": path, "error": "missing_embedding_columns", "columns": list(df.columns)}}
    xy = df[[x,y]].to_numpy(dtype=float)
    out = {{"path": path, "n": int(xy.shape[0]), "x_col": x, "y_col": y}}
    cluster_col = {json.dumps(cluster_col) if cluster_col else "None"}
    batch_col = {json.dumps(batch_col) if batch_col else "None"}
    if cluster_col is None:
        cluster_col = first_present(df, ["cluster","clusters","label","cell_type","celltype","group"])
    if batch_col is None:
        batch_col = first_present(df, ["batch","sample","donor","condition"])
    if cluster_col and cluster_col in df.columns:
        labels = df[cluster_col].astype(str).to_numpy()
        if np.unique(labels).size >= 2 and np.unique(labels).size < xy.shape[0]:
            out["silhouette_cluster"] = float(silhouette_score(xy, labels))
        out["cluster_col"] = cluster_col
    if batch_col and batch_col in df.columns:
        batches = df[batch_col].astype(str).to_numpy()
        if np.unique(batches).size >= 2 and np.unique(batches).size < xy.shape[0]:
            out["silhouette_batch"] = float(silhouette_score(xy, batches))
        out["batch_col"] = batch_col
        out["knn_batch_mixing"] = knn_mixing(xy, batches, k={int(knn_k)})
    return out


def main(argv):
    payload = {{
        "schema_version": "{EMBEDDING_ANALYSIS_SCHEMA_VERSION}",
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

