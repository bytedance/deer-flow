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

DENSITOMETRY_ANALYSIS_SCHEMA_VERSION = "deerflow.raw_data.densitometry_analysis.v1"


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


def _as_str(s: pd.Series) -> pd.Series:
    return s.astype(str).fillna("")


def _as_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def analyze_densitometry_csv_files(
    *,
    csv_paths: list[Path],
    outputs_dir: Path,
    sample_col: str | None = None,
    target_col: str | None = None,
    value_col: str | None = None,
    control_target: str | None = None,
    artifact_subdir: str = "scientific-vision/raw-data/densitometry",
) -> tuple[dict[str, Any], list[str]]:
    """Analyze densitometry CSV(s) and generate auditable metrics + reproduction script.

    Typical upstream sources:
    - ImageJ/Fiji "Analyze Gels" exports
    - Western blot quant tables from figure software

    Minimal required columns:
    - sample/lane identifier
    - target/protein identifier
    - numeric intensity/density value
    """
    if not csv_paths:
        raise ValueError("csv_paths must be non-empty")

    inputs: list[dict[str, Any]] = []
    for p in csv_paths:
        b = p.read_bytes()
        inputs.append({"path": str(p), "sha256": _sha256_bytes(b), "bytes": len(b)})

    config_blob = json.dumps(
        {
            "schema": DENSITOMETRY_ANALYSIS_SCHEMA_VERSION,
            "inputs": [{"sha256": i["sha256"], "bytes": i["bytes"]} for i in inputs],
            "sample_col": sample_col,
            "target_col": target_col,
            "value_col": value_col,
            "control_target": control_target,
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

        s_name = sample_col if isinstance(sample_col, str) and sample_col in df.columns else None
        t_name = target_col if isinstance(target_col, str) and target_col in df.columns else None
        v_name = value_col if isinstance(value_col, str) and value_col in df.columns else None

        if s_name is None:
            s_name = _first_present(df, ["sample", "lane", "lanes", "condition", "group", "replicate", "rep", "well"])
        if t_name is None:
            t_name = _first_present(df, ["target", "protein", "gene", "band", "marker", "antibody"])
        if v_name is None:
            v_name = _first_present(df, ["intensity", "density", "integrated_density", "integrated density", "area", "volume", "mean", "value", "signal"])

        if s_name is None or t_name is None or v_name is None:
            runs.append({"input": entry, "error": "missing_required_columns", "columns": list(df.columns)[:80]})
            continue

        sample = _as_str(df[s_name]).rename("sample")
        target = _as_str(df[t_name]).rename("target")
        value = _as_num(df[v_name]).rename("value")

        tidy = pd.concat([sample, target, value], axis=1)
        tidy = tidy[np.isfinite(tidy["value"].to_numpy(dtype=float))]
        if tidy.empty:
            runs.append({"input": entry, "error": "no_numeric_values"})
            continue

        # Per (sample,target) replicate summary
        g = tidy.groupby(["sample", "target"], dropna=False)["value"]
        agg = g.agg(["count", "mean", "std", "median"]).reset_index()
        agg["cv"] = agg["std"] / agg["mean"].replace({0.0: np.nan})

        # Optional within-sample normalization by control_target
        norm_note = None
        if isinstance(control_target, str) and control_target.strip():
            ct = control_target.strip()
            control = agg[agg["target"].astype(str) == ct][["sample", "mean"]].rename(columns={"mean": "control_mean"})
            merged = agg.merge(control, on="sample", how="left")
            merged["ratio_to_control"] = merged["mean"] / merged["control_mean"].replace({0.0: np.nan})
            merged["log2_ratio_to_control"] = np.log2(merged["ratio_to_control"])
            agg2 = merged
            norm_note = f"ratio_to_control uses per-sample mean(target)/mean(control_target='{ct}')"
        else:
            agg2 = agg

        # Basic outlier flags per target on raw tidy values (IQR)
        outlier_counts: dict[str, int] = {}
        for t in sorted(tidy["target"].unique().tolist()):
            sub = tidy[tidy["target"] == t]["value"].to_numpy(dtype=float)
            if sub.size < 6:
                continue
            q1 = float(np.quantile(sub, 0.25))
            q3 = float(np.quantile(sub, 0.75))
            iqr = q3 - q1
            lo = q1 - 1.5 * iqr
            hi = q3 + 1.5 * iqr
            outlier_counts[str(t)] = int(np.sum((sub < lo) | (sub > hi)))

        # Table row highlights
        n_samples = int(agg2["sample"].nunique())
        n_targets = int(agg2["target"].nunique())
        overall_cv_median = float(np.nanmedian(agg2["cv"].to_numpy(dtype=float))) if "cv" in agg2.columns else None

        out: dict[str, Any] = {
            "input": entry,
            "n_rows_numeric": int(tidy.shape[0]),
            "sample_col": s_name,
            "target_col": t_name,
            "value_col": v_name,
            "samples": n_samples,
            "targets": n_targets,
            "replicate_summary": {
                "columns": list(agg2.columns),
                "rows": agg2.sort_values(["sample", "target"]).head(200).to_dict(orient="records"),
                "note": "replicate_summary.rows is truncated (first 200) for audit convenience; full CSV summary is written separately",
            },
            "outlier_counts_iqr": outlier_counts,
            "normalization": {"control_target": control_target, "note": norm_note} if norm_note else None,
        }
        runs.append(out)

        table_rows.append(
            {
                "csv_sha256": entry["sha256"],
                "n_rows_numeric": int(tidy.shape[0]),
                "samples": n_samples,
                "targets": n_targets,
                "cv_median": overall_cv_median,
                "control_target": control_target or "",
            }
        )

        # Write per-input expanded summary CSV
        per_rel = base / f"summary-{entry['sha256'][:12]}.csv"
        (outputs_dir / per_rel).parent.mkdir(parents=True, exist_ok=True)
        agg2.to_csv(outputs_dir / per_rel, index=False)

    payload: dict[str, Any] = {
        "schema_version": DENSITOMETRY_ANALYSIS_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "analysis_signature": analysis_sig,
        "inputs": inputs,
        "runs": runs,
        "notes": [
            "This tool focuses on auditable aggregation/normalization; it does NOT attempt to re-quantify bands from pixels (use ImageReport evidence parsers for ROI-based pixel metrics).",
            "If you require exact methodology matching a paper/figure, provide the upstream quant software + settings.",
        ],
    }

    analysis_physical.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    table_physical = outputs_dir / table_rel
    pd.DataFrame(table_rows).to_csv(table_physical, index=False)

    reproduce_physical = outputs_dir / reproduce_rel
    repro = f"""\
#!/usr/bin/env python
# Auto-generated by DeerFlow ({DENSITOMETRY_ANALYSIS_SCHEMA_VERSION})
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


def analyze_one(path: str):
    df = pd.read_csv(path)
    sample_col = {json.dumps(sample_col) if sample_col else "None"}
    target_col = {json.dumps(target_col) if target_col else "None"}
    value_col = {json.dumps(value_col) if value_col else "None"}
    control_target = {json.dumps(control_target) if control_target else "None"}
    if sample_col is None:
        sample_col = first_present(df, ["sample","lane","lanes","condition","group","replicate","rep","well"])
    if target_col is None:
        target_col = first_present(df, ["target","protein","gene","band","marker","antibody"])
    if value_col is None:
        value_col = first_present(df, ["intensity","density","integrated_density","integrated density","area","volume","mean","value","signal"])
    if sample_col is None or target_col is None or value_col is None:
        return {{"path": path, "error": "missing_required_columns", "columns": list(df.columns)}}

    tidy = pd.DataFrame(
        {{
            "sample": df[sample_col].astype(str).fillna(""),
            "target": df[target_col].astype(str).fillna(""),
            "value": pd.to_numeric(df[value_col], errors="coerce"),
        }}
    )
    tidy = tidy[np.isfinite(tidy["value"].to_numpy(dtype=float))]
    if tidy.empty:
        return {{"path": path, "error": "no_numeric_values"}}

    agg = tidy.groupby(["sample", "target"])["value"].agg(["count", "mean", "std", "median"]).reset_index()
    agg["cv"] = agg["std"] / agg["mean"].replace({{0.0: np.nan}})
    if control_target is not None and str(control_target).strip():
        ct = str(control_target).strip()
        control = agg[agg["target"].astype(str) == ct][["sample", "mean"]].rename(columns={{"mean": "control_mean"}})
        merged = agg.merge(control, on="sample", how="left")
        merged["ratio_to_control"] = merged["mean"] / merged["control_mean"].replace({{0.0: np.nan}})
        merged["log2_ratio_to_control"] = np.log2(merged["ratio_to_control"])
        agg = merged

    return {{
        "path": path,
        "n_rows_numeric": int(tidy.shape[0]),
        "samples": int(agg["sample"].nunique()),
        "targets": int(agg["target"].nunique()),
        "control_target": control_target,
        "replicate_summary_head": agg.sort_values(["sample","target"]).head(50).to_dict(orient="records"),
    }}


def main(argv):
    payload = {{
        "schema_version": "{DENSITOMETRY_ANALYSIS_SCHEMA_VERSION}",
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

