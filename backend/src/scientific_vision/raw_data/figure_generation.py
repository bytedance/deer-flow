from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

OUTPUTS_VIRTUAL_PREFIX = "/mnt/user-data/outputs"
REPRO_FIGURE_SCHEMA_VERSION = "deerflow.raw_data.repro_figure.v1"

_SCHEMA_TO_KIND: dict[str, str] = {
    "deerflow.raw_data.embedding_analysis.v1": "embedding",
    "deerflow.raw_data.spectrum_analysis.v1": "spectrum",
    "deerflow.raw_data.densitometry_analysis.v1": "densitometry",
    "deerflow.raw_data.fcs_analysis.v1": "fcs",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _virtual_outputs_path(relative: str) -> str:
    rel = Path(relative).as_posix().lstrip("/")
    return f"{OUTPUTS_VIRTUAL_PREFIX}/{rel}"


def _safe_stem(stem: str, default: str = "figure") -> str:
    raw = (stem or "").strip()
    if not raw:
        return default
    out = []
    for ch in raw:
        if ch.isalnum() or ch in {"-", "_", "."}:
            out.append(ch)
        else:
            out.append("_")
    cleaned = "".join(out).strip("._")
    return cleaned[:80] if cleaned else default


def _analysis_kind(analysis_payload: dict[str, Any]) -> tuple[str, str]:
    schema = analysis_payload.get("schema_version")
    if not isinstance(schema, str):
        raise ValueError("analysis payload missing schema_version")
    kind = _SCHEMA_TO_KIND.get(schema)
    if kind is None:
        raise ValueError(f"Unsupported analysis schema: {schema}")
    return schema, kind


def _first_valid_run(runs: list[Any]) -> dict[str, Any] | None:
    for run in runs:
        if isinstance(run, dict) and not run.get("error"):
            return run
    return None


def _sha256_file(path_value: str) -> str | None:
    try:
        path = Path(path_value)
    except Exception:
        return None
    if not path.exists() or not path.is_file():
        return None
    try:
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return None


def _collect_input_paths(analysis_payload: dict[str, Any], *, kind: str) -> list[str]:
    paths: list[str] = []
    if kind == "fcs":
        input_obj = analysis_payload.get("input") if isinstance(analysis_payload.get("input"), dict) else {}
        fcs_path = input_obj.get("fcs_path")
        if isinstance(fcs_path, str) and fcs_path.strip():
            paths.append(fcs_path.strip())
    runs = analysis_payload.get("runs")
    if isinstance(runs, list):
        for run in runs:
            if not isinstance(run, dict):
                continue
            input_obj = run.get("input") if isinstance(run.get("input"), dict) else {}
            csv_path = input_obj.get("path")
            if isinstance(csv_path, str) and csv_path.strip():
                paths.append(csv_path.strip())
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        if raw not in seen:
            seen.add(raw)
            deduped.append(raw)
    return deduped


def _environment_dependencies(*, language: str, kind: str) -> list[str]:
    if language == "r":
        return [
            "R (>=4.2)",
            "ggplot2",
            "svglite",
            "Cairo",
        ]
    deps = [
        "python (>=3.12)",
        "matplotlib",
        "pandas",
        "seaborn",
    ]
    if kind in {"embedding", "spectrum", "densitometry", "fcs"}:
        deps.append("numpy")
    if kind == "fcs":
        deps.append("flowio")
    return deps


def _build_python_script_embedding(*, runs: list[dict[str, Any]], figure_title: str, output_svg: Path, output_pdf: Path) -> str:
    return f"""\
#!/usr/bin/env python
from pathlib import Path
import math
import random

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

RUNS = {json.dumps(runs, ensure_ascii=False)}
FIGURE_TITLE = {json.dumps(figure_title, ensure_ascii=False)}
OUTPUT_SVG = {json.dumps(str(output_svg))}
OUTPUT_PDF = {json.dumps(str(output_pdf))}
RANDOM_SEED = 42
random.seed(RANDOM_SEED)

sns.set_theme(context="paper", style="whitegrid")
valid = []
for run in RUNS:
    if not isinstance(run, dict) or run.get("error"):
        continue
    input_obj = run.get("input") if isinstance(run.get("input"), dict) else {{}}
    csv_path = input_obj.get("path")
    x_col = run.get("x_col")
    y_col = run.get("y_col")
    if isinstance(csv_path, str) and isinstance(x_col, str) and isinstance(y_col, str):
        valid.append(run)

if not valid:
    raise SystemExit("No valid embedding runs found")

cols = 1 if len(valid) == 1 else 2
rows = int(math.ceil(len(valid) / cols))
fig, axes = plt.subplots(rows, cols, figsize=(7.0 * cols, 5.8 * rows), squeeze=False)

for idx, run in enumerate(valid):
    ax = axes.flatten()[idx]
    csv_path = run["input"]["path"]
    x_col = run["x_col"]
    y_col = run["y_col"]
    cluster_col = run.get("cluster_col")
    batch_col = run.get("batch_col")
    df = pd.read_csv(csv_path)
    if x_col not in df.columns or y_col not in df.columns:
        raise RuntimeError(f"Missing x/y columns in {{csv_path}}: {{x_col}}, {{y_col}}")
    hue_col = None
    if isinstance(cluster_col, str) and cluster_col in df.columns:
        hue_col = cluster_col
    elif isinstance(batch_col, str) and batch_col in df.columns:
        hue_col = batch_col
    cols_to_use = [x_col, y_col] + ([hue_col] if hue_col else [])
    plot_df = df[cols_to_use].dropna()
    if hue_col:
        sns.scatterplot(
            data=plot_df,
            x=x_col,
            y=y_col,
            hue=hue_col,
            s=14,
            linewidth=0,
            alpha=0.78,
            legend=False,
            ax=ax,
        )
    else:
        sns.scatterplot(
            data=plot_df,
            x=x_col,
            y=y_col,
            s=14,
            linewidth=0,
            alpha=0.78,
            color="#2563eb",
            ax=ax,
        )
    ax.set_title(Path(csv_path).name, fontsize=11)
    ax.set_xlabel(x_col)
    ax.set_ylabel(y_col)

for j in range(len(valid), rows * cols):
    axes.flatten()[j].remove()

fig.suptitle(FIGURE_TITLE, fontsize=14, fontweight="bold")
fig.tight_layout()
fig.savefig(OUTPUT_SVG, format="svg", bbox_inches="tight")
fig.savefig(OUTPUT_PDF, format="pdf", bbox_inches="tight")
print(f"Saved: {{OUTPUT_SVG}}")
print(f"Saved: {{OUTPUT_PDF}}")
"""


def _build_python_script_spectrum(*, runs: list[dict[str, Any]], figure_title: str, output_svg: Path, output_pdf: Path) -> str:
    return f"""\
#!/usr/bin/env python
from pathlib import Path
import math
import random

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

RUNS = {json.dumps(runs, ensure_ascii=False)}
FIGURE_TITLE = {json.dumps(figure_title, ensure_ascii=False)}
OUTPUT_SVG = {json.dumps(str(output_svg))}
OUTPUT_PDF = {json.dumps(str(output_pdf))}
RANDOM_SEED = 42
random.seed(RANDOM_SEED)

sns.set_theme(context="paper", style="ticks")
valid = []
for run in RUNS:
    if not isinstance(run, dict) or run.get("error"):
        continue
    input_obj = run.get("input") if isinstance(run.get("input"), dict) else {{}}
    csv_path = input_obj.get("path")
    x_col = run.get("x_col")
    y_col = run.get("y_col")
    if isinstance(csv_path, str) and isinstance(x_col, str) and isinstance(y_col, str):
        valid.append(run)

if not valid:
    raise SystemExit("No valid spectrum runs found")

cols = 1 if len(valid) == 1 else 2
rows = int(math.ceil(len(valid) / cols))
fig, axes = plt.subplots(rows, cols, figsize=(7.2 * cols, 5.0 * rows), squeeze=False)

for idx, run in enumerate(valid):
    ax = axes.flatten()[idx]
    csv_path = run["input"]["path"]
    x_col = run["x_col"]
    y_col = run["y_col"]
    df = pd.read_csv(csv_path)
    if x_col not in df.columns or y_col not in df.columns:
        raise RuntimeError(f"Missing x/y columns in {{csv_path}}: {{x_col}}, {{y_col}}")
    plot_df = df[[x_col, y_col]].dropna().copy()
    plot_df[x_col] = pd.to_numeric(plot_df[x_col], errors="coerce")
    plot_df[y_col] = pd.to_numeric(plot_df[y_col], errors="coerce")
    plot_df = plot_df.dropna().sort_values(x_col)
    ax.plot(plot_df[x_col], plot_df[y_col], color="#0f172a", linewidth=1.5)

    peaks = (run.get("peaks") or {{}}).get("top_peaks") if isinstance(run.get("peaks"), dict) else None
    if isinstance(peaks, list):
        for p in peaks[:4]:
            if not isinstance(p, dict):
                continue
            px = p.get("x")
            py = p.get("y")
            if isinstance(px, (int, float)) and isinstance(py, (int, float)):
                ax.scatter([px], [py], color="#dc2626", s=18, zorder=3)
                ax.annotate(f"{{px:.2f}}", (px, py), textcoords="offset points", xytext=(3, 4), fontsize=8, color="#dc2626")
    ax.set_title(Path(csv_path).name, fontsize=11)
    ax.set_xlabel(x_col)
    ax.set_ylabel(y_col)

for j in range(len(valid), rows * cols):
    axes.flatten()[j].remove()

fig.suptitle(FIGURE_TITLE, fontsize=14, fontweight="bold")
fig.tight_layout()
fig.savefig(OUTPUT_SVG, format="svg", bbox_inches="tight")
fig.savefig(OUTPUT_PDF, format="pdf", bbox_inches="tight")
print(f"Saved: {{OUTPUT_SVG}}")
print(f"Saved: {{OUTPUT_PDF}}")
"""


def _build_python_script_densitometry(*, runs: list[dict[str, Any]], figure_title: str, output_svg: Path, output_pdf: Path) -> str:
    return f"""\
#!/usr/bin/env python
from pathlib import Path
import math
import random

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

RUNS = {json.dumps(runs, ensure_ascii=False)}
FIGURE_TITLE = {json.dumps(figure_title, ensure_ascii=False)}
OUTPUT_SVG = {json.dumps(str(output_svg))}
OUTPUT_PDF = {json.dumps(str(output_pdf))}
RANDOM_SEED = 42
random.seed(RANDOM_SEED)

sns.set_theme(context="paper", style="whitegrid")
valid = []
for run in RUNS:
    if not isinstance(run, dict) or run.get("error"):
        continue
    input_obj = run.get("input") if isinstance(run.get("input"), dict) else {{}}
    csv_path = input_obj.get("path")
    sample_col = run.get("sample_col")
    target_col = run.get("target_col")
    value_col = run.get("value_col")
    if all(isinstance(x, str) for x in [csv_path, sample_col, target_col, value_col]):
        valid.append(run)

if not valid:
    raise SystemExit("No valid densitometry runs found")

cols = 1 if len(valid) == 1 else 2
rows = int(math.ceil(len(valid) / cols))
fig, axes = plt.subplots(rows, cols, figsize=(7.2 * cols, 5.2 * rows), squeeze=False)

for idx, run in enumerate(valid):
    ax = axes.flatten()[idx]
    csv_path = run["input"]["path"]
    sample_col = run["sample_col"]
    target_col = run["target_col"]
    value_col = run["value_col"]
    df = pd.read_csv(csv_path)
    if sample_col not in df.columns or target_col not in df.columns or value_col not in df.columns:
        raise RuntimeError(f"Missing required columns in {{csv_path}}")
    tmp = df[[sample_col, target_col, value_col]].copy()
    tmp[value_col] = pd.to_numeric(tmp[value_col], errors="coerce")
    tmp = tmp.dropna()
    agg = tmp.groupby([sample_col, target_col], dropna=False)[value_col].mean().reset_index(name="mean_value")
    sns.barplot(data=agg, x=sample_col, y="mean_value", hue=target_col, errorbar=None, ax=ax)
    ax.set_title(Path(csv_path).name, fontsize=11)
    ax.set_xlabel(sample_col)
    ax.set_ylabel(f"Mean {{value_col}}")
    ax.tick_params(axis="x", rotation=25)

for j in range(len(valid), rows * cols):
    axes.flatten()[j].remove()

fig.suptitle(FIGURE_TITLE, fontsize=14, fontweight="bold")
fig.tight_layout()
fig.savefig(OUTPUT_SVG, format="svg", bbox_inches="tight")
fig.savefig(OUTPUT_PDF, format="pdf", bbox_inches="tight")
print(f"Saved: {{OUTPUT_SVG}}")
print(f"Saved: {{OUTPUT_PDF}}")
"""


def _build_python_script_fcs(*, analysis_payload: dict[str, Any], figure_title: str, output_svg: Path, output_pdf: Path) -> str:
    input_obj = analysis_payload.get("input") if isinstance(analysis_payload.get("input"), dict) else {}
    fcs_path = input_obj.get("fcs_path")
    channels = analysis_payload.get("channels")
    gates = analysis_payload.get("gates")
    return f"""\
#!/usr/bin/env python
import random
import matplotlib.pyplot as plt

FCS_PATH = {json.dumps(fcs_path, ensure_ascii=False)}
CHANNELS = {json.dumps(channels, ensure_ascii=False)}
GATES = {json.dumps(gates, ensure_ascii=False)}
FIGURE_TITLE = {json.dumps(figure_title, ensure_ascii=False)}
OUTPUT_SVG = {json.dumps(str(output_svg))}
OUTPUT_PDF = {json.dumps(str(output_pdf))}
RANDOM_SEED = 42
random.seed(RANDOM_SEED)

fig, axes = plt.subplots(1, 2, figsize=(12, 5))
ax0, ax1 = axes

try:
    from flowio import FlowData
    import numpy as np

    fd = FlowData(str(FCS_PATH))
    data = fd.as_array(preprocess=False)
    if data.shape[1] >= 2:
        x = data[:, 0].astype(float)
        y = data[:, 1].astype(float)
        hb = ax0.hexbin(x, y, gridsize=75, cmap="viridis", mincnt=1)
        fig.colorbar(hb, ax=ax0, label="event density")
        name_x = CHANNELS[0]["pnn"] if isinstance(CHANNELS, list) and len(CHANNELS) > 0 and isinstance(CHANNELS[0], dict) else "channel_1"
        name_y = CHANNELS[1]["pnn"] if isinstance(CHANNELS, list) and len(CHANNELS) > 1 and isinstance(CHANNELS[1], dict) else "channel_2"
        ax0.set_xlabel(name_x)
        ax0.set_ylabel(name_y)
        ax0.set_title("Raw event density")
    else:
        ax0.text(0.5, 0.5, "Insufficient channels for 2D density plot", ha="center", va="center")
        ax0.set_axis_off()
except Exception as exc:
    ax0.text(0.5, 0.5, f"Failed to parse FCS\\n{{exc}}", ha="center", va="center")
    ax0.set_axis_off()

labels = []
values = []
if isinstance(GATES, list):
    for g in GATES:
        if not isinstance(g, dict):
            continue
        gid = g.get("id")
        frac = g.get("fraction_of_parent")
        if isinstance(gid, str) and isinstance(frac, (int, float)):
            labels.append(gid)
            values.append(float(frac))

if values:
    ax1.bar(labels, values, color="#2563eb")
    ax1.set_ylim(0, max(values) * 1.25 if values else 1.0)
    ax1.set_ylabel("Fraction of parent")
    ax1.set_title("Gate fractions")
else:
    ax1.text(0.5, 0.5, "No gate fractions available", ha="center", va="center")
    ax1.set_axis_off()

fig.suptitle(FIGURE_TITLE, fontsize=14, fontweight="bold")
fig.tight_layout()
fig.savefig(OUTPUT_SVG, format="svg", bbox_inches="tight")
fig.savefig(OUTPUT_PDF, format="pdf", bbox_inches="tight")
print(f"Saved: {{OUTPUT_SVG}}")
print(f"Saved: {{OUTPUT_PDF}}")
"""


def _build_python_script(*, analysis_payload: dict[str, Any], kind: str, figure_title: str, output_svg: Path, output_pdf: Path) -> str:
    runs = analysis_payload.get("runs")
    run_list = runs if isinstance(runs, list) else []
    if kind == "embedding":
        valid = [r for r in run_list if isinstance(r, dict)]
        return _build_python_script_embedding(runs=valid, figure_title=figure_title, output_svg=output_svg, output_pdf=output_pdf)
    if kind == "spectrum":
        valid = [r for r in run_list if isinstance(r, dict)]
        return _build_python_script_spectrum(runs=valid, figure_title=figure_title, output_svg=output_svg, output_pdf=output_pdf)
    if kind == "densitometry":
        valid = [r for r in run_list if isinstance(r, dict)]
        return _build_python_script_densitometry(runs=valid, figure_title=figure_title, output_svg=output_svg, output_pdf=output_pdf)
    if kind == "fcs":
        return _build_python_script_fcs(analysis_payload=analysis_payload, figure_title=figure_title, output_svg=output_svg, output_pdf=output_pdf)
    raise ValueError(f"Unsupported figure kind: {kind}")


def _build_r_script(*, analysis_payload: dict[str, Any], kind: str, figure_title: str, output_svg: Path, output_pdf: Path) -> str:
    runs = analysis_payload.get("runs")
    run_list = runs if isinstance(runs, list) else []
    first = _first_valid_run(run_list)
    if kind == "fcs":
        raise ValueError("R figure template for FCS is not supported; use language='python'")
    if first is None:
        raise ValueError("No valid run found in analysis payload")

    input_obj = first.get("input") if isinstance(first.get("input"), dict) else {}
    input_path = input_obj.get("path")
    if not isinstance(input_path, str):
        raise ValueError("analysis payload does not include input.path for R plotting")

    if kind == "embedding":
        x_col = first.get("x_col")
        y_col = first.get("y_col")
        hue_col = first.get("cluster_col") if isinstance(first.get("cluster_col"), str) else first.get("batch_col")
        if not (isinstance(x_col, str) and isinstance(y_col, str)):
            raise ValueError("embedding run missing x_col/y_col")
        hue_str = hue_col if isinstance(hue_col, str) else ""
        return f"""\
library(ggplot2)
set.seed(42)
df <- read.csv({json.dumps(input_path)})
x_col <- {json.dumps(x_col)}
y_col <- {json.dumps(y_col)}
hue_col <- {json.dumps(hue_str)}
if (hue_col != "" && hue_col %in% names(df)) {{
  p <- ggplot(df, aes_string(x = x_col, y = y_col, color = hue_col)) + geom_point(size = 0.9, alpha = 0.75)
}} else {{
  p <- ggplot(df, aes_string(x = x_col, y = y_col)) + geom_point(size = 0.9, alpha = 0.75, color = "#2563eb")
}}
p <- p + theme_bw(base_size = 13) + labs(title = {json.dumps(figure_title)})
ggsave({json.dumps(str(output_svg))}, p, width = 7, height = 5.5, device = "svg")
ggsave({json.dumps(str(output_pdf))}, p, width = 7, height = 5.5, device = cairo_pdf)
"""

    if kind == "spectrum":
        x_col = first.get("x_col")
        y_col = first.get("y_col")
        if not (isinstance(x_col, str) and isinstance(y_col, str)):
            raise ValueError("spectrum run missing x_col/y_col")
        return f"""\
library(ggplot2)
set.seed(42)
df <- read.csv({json.dumps(input_path)})
x_col <- {json.dumps(x_col)}
y_col <- {json.dumps(y_col)}
df[[x_col]] <- as.numeric(df[[x_col]])
df[[y_col]] <- as.numeric(df[[y_col]])
df <- df[complete.cases(df[, c(x_col, y_col)]), ]
p <- ggplot(df, aes_string(x = x_col, y = y_col)) +
  geom_line(color = "#0f172a", linewidth = 0.7) +
  theme_bw(base_size = 13) +
  labs(title = {json.dumps(figure_title)})
ggsave({json.dumps(str(output_svg))}, p, width = 7.2, height = 4.8, device = "svg")
ggsave({json.dumps(str(output_pdf))}, p, width = 7.2, height = 4.8, device = cairo_pdf)
"""

    if kind == "densitometry":
        sample_col = first.get("sample_col")
        target_col = first.get("target_col")
        value_col = first.get("value_col")
        if not (isinstance(sample_col, str) and isinstance(target_col, str) and isinstance(value_col, str)):
            raise ValueError("densitometry run missing sample_col/target_col/value_col")
        return f"""\
library(ggplot2)
set.seed(42)
df <- read.csv({json.dumps(input_path)})
sample_col <- {json.dumps(sample_col)}
target_col <- {json.dumps(target_col)}
value_col <- {json.dumps(value_col)}
df[[value_col]] <- as.numeric(df[[value_col]])
df <- df[complete.cases(df[, c(sample_col, target_col, value_col)]), ]
agg <- aggregate(df[[value_col]], by = list(sample = df[[sample_col]], target = df[[target_col]]), FUN = mean)
colnames(agg)[3] <- "mean_value"
p <- ggplot(agg, aes(x = sample, y = mean_value, fill = target)) +
  geom_col(position = "dodge") +
  theme_bw(base_size = 13) +
  labs(title = {json.dumps(figure_title)}, y = paste("Mean", value_col), x = sample_col)
ggsave({json.dumps(str(output_svg))}, p, width = 7.2, height = 5.2, device = "svg")
ggsave({json.dumps(str(output_pdf))}, p, width = 7.2, height = 5.2, device = cairo_pdf)
"""

    raise ValueError(f"Unsupported figure kind: {kind}")


def generate_reproducible_figure_bundle(
    *,
    analysis_payload: dict[str, Any],
    analysis_virtual_path: str,
    outputs_dir: Path,
    language: str = "python",
    style_preset: str = "publication",
    figure_title: str | None = None,
    output_stem: str | None = None,
    execute_code: bool = True,
    artifact_subdir: str = "scientific-vision/figures",
) -> tuple[dict[str, Any], list[str]]:
    """Generate (and optionally execute) publication-grade reproducible plotting code from analysis JSON."""
    schema_version, kind = _analysis_kind(analysis_payload)
    analysis_sig = analysis_payload.get("analysis_signature")
    if not isinstance(analysis_sig, str) or not analysis_sig:
        analysis_sig = _sha256_text(json.dumps(analysis_payload, ensure_ascii=False, sort_keys=True))

    language_normalized = (language or "python").strip().lower()
    if language_normalized not in {"python", "r"}:
        raise ValueError("language must be 'python' or 'r'")

    stem = _safe_stem(output_stem or f"{kind}_figure")
    title = (figure_title or f"Reproducible {kind} figure").strip()
    title = title[:200]
    random_seed = 42
    input_paths = _collect_input_paths(analysis_payload, kind=kind)
    input_provenance: list[dict[str, Any]] = []
    for path_value in input_paths:
        input_provenance.append(
            {
                "path": path_value,
                "sha256": _sha256_file(path_value),
            }
        )
    dependency_requirements = _environment_dependencies(language=language_normalized, kind=kind)

    signature_blob = json.dumps(
        {
            "schema_version": REPRO_FIGURE_SCHEMA_VERSION,
            "source_schema_version": schema_version,
            "source_analysis_signature": analysis_sig,
            "language": language_normalized,
            "style_preset": style_preset,
            "figure_title": title,
            "output_stem": stem,
            "random_seed": random_seed,
            "input_provenance": input_provenance,
            "dependency_requirements": dependency_requirements,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    figure_sig = _sha256_text(signature_blob)

    base = Path(artifact_subdir.strip("/")) / kind / f"batch-{figure_sig[:12]}"
    ext = "py" if language_normalized == "python" else "R"
    script_rel = base / f"{stem}.{ext}"
    svg_rel = base / f"{stem}.svg"
    pdf_rel = base / f"{stem}.pdf"
    metadata_rel = base / "metadata.json"
    log_rel = base / "execution.log"

    script_path = outputs_dir / script_rel
    svg_path = outputs_dir / svg_rel
    pdf_path = outputs_dir / pdf_rel
    metadata_path = outputs_dir / metadata_rel
    log_path = outputs_dir / log_rel

    script_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)

    if language_normalized == "python":
        script_text = _build_python_script(
            analysis_payload=analysis_payload,
            kind=kind,
            figure_title=title,
            output_svg=svg_path,
            output_pdf=pdf_path,
        )
    else:
        script_text = _build_r_script(
            analysis_payload=analysis_payload,
            kind=kind,
            figure_title=title,
            output_svg=svg_path,
            output_pdf=pdf_path,
        )

    script_path.write_text(script_text, encoding="utf-8")

    execution_status = "not_executed"
    return_code: int | None = None
    command: list[str] | None = None
    error_message: str | None = None
    stdout_text = ""
    stderr_text = ""

    if execute_code:
        if language_normalized == "python":
            command = [sys.executable, str(script_path)]
        else:
            rscript = shutil.which("Rscript")
            if rscript:
                command = [rscript, str(script_path)]
            else:
                execution_status = "skipped_missing_rscript"
                error_message = "Rscript not found in PATH"

        if command is not None:
            try:
                proc = subprocess.run(
                    command,
                    cwd=str(script_path.parent),
                    capture_output=True,
                    text=True,
                    timeout=240,
                    check=False,
                )
                return_code = int(proc.returncode)
                stdout_text = proc.stdout or ""
                stderr_text = proc.stderr or ""
                execution_status = "success" if proc.returncode == 0 else "failed"
                if proc.returncode != 0:
                    error_message = f"Command exited with code {proc.returncode}"
            except Exception as exc:
                execution_status = "failed"
                error_message = str(exc)

    log_content = (
        f"generated_at: {_now_iso()}\n"
        f"execution_status: {execution_status}\n"
        f"command: {command}\n"
        f"return_code: {return_code}\n"
        f"error: {error_message}\n\n"
        f"--- STDOUT ---\n{stdout_text}\n\n--- STDERR ---\n{stderr_text}\n"
    )
    log_path.write_text(log_content, encoding="utf-8")

    metadata: dict[str, Any] = {
        "schema_version": REPRO_FIGURE_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "figure_signature": figure_sig,
        "figure_kind": kind,
        "language": language_normalized,
        "style_preset": style_preset,
        "figure_title": title,
        "output_stem": stem,
        "random_seed": random_seed,
        "source": {
            "analysis_path": analysis_virtual_path,
            "analysis_schema_version": schema_version,
            "analysis_signature": analysis_sig,
            "input_provenance": input_provenance,
        },
        "environment": {
            "dependency_requirements": dependency_requirements,
        },
        "execution": {
            "status": execution_status,
            "command": command,
            "return_code": return_code,
            "error": error_message,
        },
        "artifacts": {
            "script": _virtual_outputs_path(script_rel.as_posix()),
            "svg": _virtual_outputs_path(svg_rel.as_posix()),
            "pdf": _virtual_outputs_path(pdf_rel.as_posix()),
            "log": _virtual_outputs_path(log_rel.as_posix()),
        },
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    artifacts = [
        _virtual_outputs_path(script_rel.as_posix()),
        _virtual_outputs_path(metadata_rel.as_posix()),
        _virtual_outputs_path(log_rel.as_posix()),
    ]
    if svg_path.is_file():
        artifacts.append(_virtual_outputs_path(svg_rel.as_posix()))
    if pdf_path.is_file():
        artifacts.append(_virtual_outputs_path(pdf_rel.as_posix()))
    return metadata, artifacts

