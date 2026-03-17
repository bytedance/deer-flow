"""Unit tests for scientific vision evidence parsers (audit-grade evidence tables)."""

from __future__ import annotations

import base64
import importlib
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

evidence_module = importlib.import_module("src.scientific_vision.evidence_parsers")


def _png_base64(img: Image.Image) -> str:
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def test_generates_western_blot_evidence_with_lane_normalization(tmp_path: Path):
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    # Synthetic blot: 2 lanes; each lane has target band + loading control band.
    img = Image.new("RGB", (200, 120), (255, 255, 255))
    d = ImageDraw.Draw(img)

    # Lane 1 bands (x ~ 50-80)
    d.rectangle([50, 18, 80, 30], fill=(0, 0, 0))  # target
    d.rectangle([50, 70, 80, 82], fill=(0, 0, 0))  # loading control
    # Lane 2 bands (x ~ 125-155)
    d.rectangle([125, 20, 155, 32], fill=(0, 0, 0))  # target
    d.rectangle([125, 72, 155, 84], fill=(0, 0, 0))  # loading control

    report = {
        "image_type": "western_blot",
        "evidence": [
            {"id": "E1", "kind": "band", "description": "target band", "bbox_norm": [50 / 200, 18 / 120, 80 / 200, 30 / 120], "confidence": 0.9},
            {"id": "E2", "kind": "band", "description": "β-actin loading control", "bbox_norm": [50 / 200, 70 / 120, 80 / 200, 82 / 120], "confidence": 0.9},
            {"id": "E3", "kind": "band", "description": "target band", "bbox_norm": [125 / 200, 20 / 120, 155 / 200, 32 / 120], "confidence": 0.9},
            {"id": "E4", "kind": "band", "description": "β-actin loading control", "bbox_norm": [125 / 200, 72 / 120, 155 / 200, 84 / 120], "confidence": 0.9},
        ],
        "findings": [{"id": "F1", "claim": "demo", "evidence_ids": ["E1"], "confidence": 0.6}],
        "image_confidence": 0.8,
    }

    out = evidence_module.generate_image_evidence_artifacts(
        thread_outputs_dir=outputs_dir,
        artifact_subdir="scientific-vision/image-reports",
        analysis_signature="a" * 64,
        report_path="/mnt/user-data/outputs/scientific-vision/image-reports/images/sha256-xxx/report-aaaa.json",
        report_model="sci-vision-model",
        prompt_hash="b" * 64,
        image_path="/mnt/user-data/uploads/blot.png",
        image_sha256="abc",
        mime_type="image/png",
        image_base64=_png_base64(img),
        report=report,
        enabled_parsers=None,
        write_csv=True,
        write_overlay=True,
    )

    assert out is not None
    assert out.artifacts.evidence_json_virtual_path.startswith("/mnt/user-data/outputs/")
    assert out.artifacts.evidence_csv_virtual_path is not None
    assert out.artifacts.overlay_png_virtual_path is not None

    json_physical = outputs_dir / "scientific-vision/image-reports/images/sha256-abc/evidence-aaaaaaaaaaaa.json"
    assert json_physical.is_file()
    payload = json_physical.read_text(encoding="utf-8")
    assert '"schema_version"' in payload
    assert '"western_blot"' in payload

    # At least one row should contain lane_index and ratio_to_loading_control
    data = json.loads(payload)
    rows = data.get("rows") or []
    assert isinstance(rows, list) and len(rows) >= 4
    found_ratio = False
    for r in rows:
        metrics = r.get("metrics") if isinstance(r, dict) else None
        if isinstance(metrics, dict) and "lane_index" in metrics and "ratio_to_loading_control" in metrics:
            found_ratio = True
            break
    assert found_ratio


def test_generates_spectrum_peaks_without_explicit_evidence(tmp_path: Path):
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    # Synthetic spectrum line with two peaks.
    w, h = 300, 160
    img = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    pts = []
    for x in range(10, w - 10):
        # baseline
        y = 110
        # peak1
        y -= int(45 * math.exp(-((x - 90) ** 2) / (2 * 12**2)))
        # peak2
        y -= int(55 * math.exp(-((x - 210) ** 2) / (2 * 14**2)))
        pts.append((x, y))
    d.line(pts, fill=(0, 0, 0), width=2)

    report = {"image_type": "spectrum", "evidence": []}

    out = evidence_module.generate_image_evidence_artifacts(
        thread_outputs_dir=outputs_dir,
        artifact_subdir="scientific-vision/image-reports",
        analysis_signature="c" * 64,
        report_path="/mnt/user-data/outputs/scientific-vision/image-reports/images/sha256-yyy/report-cccc.json",
        report_model="sci-vision-model",
        prompt_hash="d" * 64,
        image_path="/mnt/user-data/uploads/spec.png",
        image_sha256="spec",
        mime_type="image/png",
        image_base64=_png_base64(img),
        report=report,
        enabled_parsers=None,
        write_csv=False,
        write_overlay=False,
    )

    assert out is not None
    rows = out.evidence_payload.get("rows")
    assert isinstance(rows, list)
    assert len(rows) >= 1
    assert any(isinstance(r, dict) and str(r.get("id", "")).startswith("P") for r in rows)

