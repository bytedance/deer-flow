"""Tests for raw CSV analyses (embedding/spectrum/densitometry)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.scientific_vision.raw_data.csv_analysis import (
    analyze_densitometry_csv,
    analyze_embedding_csv,
    analyze_spectrum_csv,
)


def test_analyze_embedding_csv_writes_json_and_reproduce(tmp_path: Path):
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    csv_path = tmp_path / "embed.csv"
    df = pd.DataFrame(
        {
            "tsne1": np.r_[np.random.default_rng(0).normal(0, 1, 200), np.random.default_rng(1).normal(5, 1, 200)],
            "tsne2": np.r_[np.random.default_rng(2).normal(0, 1, 200), np.random.default_rng(3).normal(5, 1, 200)],
            "batch": ["A"] * 200 + ["B"] * 200,
            "cluster": ["c1"] * 150 + ["c2"] * 50 + ["c3"] * 200,
        }
    )
    df.to_csv(csv_path, index=False)

    payload, artifacts = analyze_embedding_csv(csv_path=csv_path, outputs_dir=outputs_dir)
    assert payload["kind"] == "embedding"
    assert payload["input"]["n_used"] == 400
    assert len(artifacts) == 2
    assert all(a.startswith("/mnt/user-data/outputs/") for a in artifacts)


def test_analyze_spectrum_csv_detects_peaks(tmp_path: Path):
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    csv_path = tmp_path / "spec.csv"
    xs = np.linspace(400, 800, 800)
    ys = (
        0.1 * np.sin(xs / 40)
        + np.exp(-0.5 * ((xs - 520) / 8) ** 2)
        + 0.8 * np.exp(-0.5 * ((xs - 680) / 10) ** 2)
        + 0.02 * np.random.default_rng(0).normal(0, 1, xs.size)
    )
    pd.DataFrame({"wavelength": xs, "intensity": ys}).to_csv(csv_path, index=False)

    payload, artifacts = analyze_spectrum_csv(csv_path=csv_path, outputs_dir=outputs_dir)
    assert payload["kind"] == "spectrum"
    assert payload["summary"]["peaks_found"] >= 1
    assert len(artifacts) == 2


def test_analyze_densitometry_csv_normalizes(tmp_path: Path):
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    csv_path = tmp_path / "dens.csv"
    df = pd.DataFrame(
        {
            "lane": ["L1", "L2", "L3"],
            "target_intensity": [100.0, 200.0, 150.0],
            "actin": [50.0, 100.0, 75.0],
            "group": ["ctrl", "treat", "treat"],
        }
    )
    df.to_csv(csv_path, index=False)

    payload, artifacts = analyze_densitometry_csv(csv_path=csv_path, outputs_dir=outputs_dir)
    assert payload["kind"] == "densitometry"
    assert payload["input"]["n_used"] == 3
    assert len(artifacts) == 3

