"""Tests for raw FCS analysis (flowio-based)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from flowio import create_fcs

from src.scientific_vision.raw_data.fcs_analysis import analyze_fcs_file


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("preprocess", [False, True])
def test_analyze_fcs_writes_artifacts_and_gates(tmp_path: Path, preprocess: bool):
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    fcs_path = tmp_path / "demo.fcs"
    rng = np.random.default_rng(0)
    # Columns: FSC-A, SSC-A, FITC-A
    events = np.column_stack(
        [
            rng.uniform(0, 1e5, size=200),
            rng.uniform(0, 1e5, size=200),
            rng.uniform(0, 5e3, size=200),
        ]
    ).astype(np.float32)

    with open(fcs_path, "wb") as f:
        create_fcs(
            f,
            events.ravel().tolist(),
            channel_names=["FSC-A", "SSC-A", "FITC-A"],
            opt_channel_names=["FSC-Area", "SSC-Area", "CD4 FITC"],
            metadata_dict={"$TOT": str(events.shape[0])},
        )

    payload, artifacts = analyze_fcs_file(
        fcs_path=fcs_path,
        outputs_dir=outputs_dir,
        preprocess=preprocess,
        apply_compensation=False,
        max_events=10_000,
        gates=[
            {"id": "G1", "type": "threshold", "channel": "FITC-A", "op": ">", "threshold": 2500},
            {"id": "G2", "type": "rect2d", "x_channel": "FSC-A", "y_channel": "SSC-A", "x_min": 1e4, "x_max": 9e4, "y_min": 1e4, "y_max": 9e4},
        ],
    )

    assert payload["schema_version"] == "deerflow.raw_data.fcs_analysis.v1"
    assert payload["input"]["fcs_sha256"] == _sha256(fcs_path)
    assert isinstance(artifacts, list) and len(artifacts) >= 3
    assert all(isinstance(a, str) and a.startswith("/mnt/user-data/outputs/") for a in artifacts)

    gates = payload.get("gates") or []
    assert isinstance(gates, list) and len(gates) == 2
    assert all("error" not in g for g in gates if isinstance(g, dict))

    # Ensure analysis JSON exists on disk
    fcs_sha = _sha256(fcs_path)
    analysis_sig = payload["analysis_signature"]
    analysis_physical = outputs_dir / "scientific-vision/raw-data/fcs" / f"sha256-{fcs_sha}" / f"analysis-{analysis_sig[:12]}.json"
    assert analysis_physical.is_file()
    loaded = json.loads(analysis_physical.read_text(encoding="utf-8"))
    assert loaded["analysis_signature"] == analysis_sig

