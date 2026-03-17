"""Tests for reproducible figure code generation from analysis artifacts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.scientific_vision.raw_data.figure_generation import generate_reproducible_figure_bundle


def test_generate_reproducible_figure_bundle_python_executes_and_exports_vectors(tmp_path: Path):
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    csv_path = tmp_path / "spectrum.csv"
    xs = np.linspace(400, 700, 200)
    ys = np.sin(xs / 40.0) + np.exp(-0.5 * ((xs - 560) / 15.0) ** 2)
    pd.DataFrame({"wavelength": xs, "intensity": ys}).to_csv(csv_path, index=False)

    analysis_payload = {
        "schema_version": "deerflow.raw_data.spectrum_analysis.v1",
        "analysis_signature": "sig-spectrum-demo",
        "runs": [
            {
                "input": {"path": str(csv_path)},
                "x_col": "wavelength",
                "y_col": "intensity",
                "peaks": {"top_peaks": [{"x": 560.0, "y": float(np.max(ys))}]},
            }
        ],
    }

    metadata, artifacts = generate_reproducible_figure_bundle(
        analysis_payload=analysis_payload,
        analysis_virtual_path="/mnt/user-data/outputs/scientific-vision/raw-data/spectrum/demo/analysis.json",
        outputs_dir=outputs_dir,
        language="python",
        style_preset="publication",
        figure_title="Demo Spectrum",
        output_stem="demo_spectrum",
        execute_code=True,
    )

    assert metadata["schema_version"] == "deerflow.raw_data.repro_figure.v1"
    assert metadata["figure_kind"] == "spectrum"
    assert metadata["language"] == "python"
    assert metadata["random_seed"] == 42
    assert isinstance(metadata["source"]["input_provenance"], list)
    assert metadata["source"]["input_provenance"]
    assert metadata["source"]["input_provenance"][0]["path"] == str(csv_path)
    assert isinstance(metadata["source"]["input_provenance"][0]["sha256"], str)
    assert len(metadata["source"]["input_provenance"][0]["sha256"]) == 64
    deps = metadata["environment"]["dependency_requirements"]
    assert "python (>=3.12)" in deps
    assert "matplotlib" in deps
    assert metadata["execution"]["status"] in {"success", "failed"}
    assert any(p.endswith(".py") for p in artifacts)
    assert any(p.endswith("metadata.json") for p in artifacts)
    # In normal environments with matplotlib installed, vector outputs should exist.
    assert any(p.endswith(".svg") for p in artifacts)
    assert any(p.endswith(".pdf") for p in artifacts)


def test_generate_reproducible_figure_bundle_r_without_execution_writes_script(tmp_path: Path):
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    csv_path = tmp_path / "embed.csv"
    df = pd.DataFrame(
        {
            "tsne_1": np.r_[np.random.default_rng(0).normal(0, 1, 50), np.random.default_rng(1).normal(4, 1, 50)],
            "tsne_2": np.r_[np.random.default_rng(2).normal(0, 1, 50), np.random.default_rng(3).normal(4, 1, 50)],
            "cluster": ["A"] * 50 + ["B"] * 50,
        }
    )
    df.to_csv(csv_path, index=False)

    analysis_payload = {
        "schema_version": "deerflow.raw_data.embedding_analysis.v1",
        "analysis_signature": "sig-embedding-demo",
        "runs": [
            {
                "input": {"path": str(csv_path)},
                "x_col": "tsne_1",
                "y_col": "tsne_2",
                "cluster_col": "cluster",
            }
        ],
    }

    metadata, artifacts = generate_reproducible_figure_bundle(
        analysis_payload=analysis_payload,
        analysis_virtual_path="/mnt/user-data/outputs/scientific-vision/raw-data/embedding/demo/analysis.json",
        outputs_dir=outputs_dir,
        language="r",
        style_preset="publication",
        figure_title="Embedding Demo",
        output_stem="embedding_demo",
        execute_code=False,
    )

    assert metadata["figure_kind"] == "embedding"
    assert metadata["language"] == "r"
    assert metadata["random_seed"] == 42
    assert metadata["source"]["input_provenance"][0]["path"] == str(csv_path)
    deps = metadata["environment"]["dependency_requirements"]
    assert "R (>=4.2)" in deps
    assert "ggplot2" in deps
    assert metadata["execution"]["status"] == "not_executed"
    assert any(p.endswith(".R") for p in artifacts)
    assert any(p.endswith("execution.log") for p in artifacts)

