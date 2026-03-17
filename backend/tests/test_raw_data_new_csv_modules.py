"""Tests for the newer raw-data CSV analysis modules (multi-file, audit artifacts)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.scientific_vision.raw_data.densitometry_analysis import analyze_densitometry_csv_files
from src.scientific_vision.raw_data.embedding_analysis import analyze_embedding_csv_files
from src.scientific_vision.raw_data.spectrum_analysis import analyze_spectrum_csv_files


def test_analyze_embedding_csv_files_writes_three_artifacts(tmp_path: Path):
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    csv_path = tmp_path / "embed.csv"
    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "tsne_1": np.r_[rng.normal(0, 1, 200), rng.normal(6, 1, 200)],
            "tsne_2": np.r_[rng.normal(0, 1, 200), rng.normal(6, 1, 200)],
            "batch": ["A"] * 200 + ["B"] * 200,
            "cluster": ["c1"] * 150 + ["c2"] * 50 + ["c3"] * 200,
        }
    )
    df.to_csv(csv_path, index=False)

    payload, artifacts = analyze_embedding_csv_files(csv_paths=[csv_path], outputs_dir=outputs_dir)
    assert payload["schema_version"] == "deerflow.raw_data.embedding_analysis.v1"
    assert isinstance(artifacts, list) and len(artifacts) == 3
    assert all(isinstance(a, str) and a.startswith("/mnt/user-data/outputs/") for a in artifacts)


def test_analyze_spectrum_csv_files_writes_three_artifacts_and_peaks(tmp_path: Path):
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    csv_path = tmp_path / "spec.csv"
    xs = np.linspace(400, 800, 900)
    ys = (
        0.03 * np.sin(xs / 35)
        + np.exp(-0.5 * ((xs - 520) / 7) ** 2)
        + 0.8 * np.exp(-0.5 * ((xs - 680) / 9) ** 2)
        + 0.01 * np.random.default_rng(1).normal(0, 1, xs.size)
    )
    pd.DataFrame({"wavelength": xs, "intensity": ys}).to_csv(csv_path, index=False)

    payload, artifacts = analyze_spectrum_csv_files(csv_paths=[csv_path], outputs_dir=outputs_dir)
    assert payload["schema_version"] == "deerflow.raw_data.spectrum_analysis.v1"
    assert isinstance(artifacts, list) and len(artifacts) == 3
    assert any("peaks" in (r or {}) for r in (payload.get("runs") or []) if isinstance(r, dict))


def test_analyze_densitometry_csv_files_writes_three_artifacts(tmp_path: Path):
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    csv_path = tmp_path / "dens.csv"
    df = pd.DataFrame(
        {
            "lane": ["L1", "L2", "L3", "L1", "L2", "L3"],
            "protein": ["Target", "Target", "Target", "GAPDH", "GAPDH", "GAPDH"],
            "intensity": [100.0, 200.0, 150.0, 50.0, 100.0, 75.0],
        }
    )
    df.to_csv(csv_path, index=False)

    payload, artifacts = analyze_densitometry_csv_files(
        csv_paths=[csv_path],
        outputs_dir=outputs_dir,
        sample_col="lane",
        target_col="protein",
        value_col="intensity",
        control_target="GAPDH",
    )
    assert payload["schema_version"] == "deerflow.raw_data.densitometry_analysis.v1"
    assert isinstance(artifacts, list) and len(artifacts) == 3
    assert all(isinstance(a, str) and a.startswith("/mnt/user-data/outputs/") for a in artifacts)

