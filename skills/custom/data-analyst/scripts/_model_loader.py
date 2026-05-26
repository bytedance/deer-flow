#!/usr/bin/env python
"""ONNX model loader with graceful fallback for Ultra-tier analysis.

All Ultra scripts import ``load_model`` from this module. If ONNX Runtime or the
model file is missing, it returns ``None`` with a reason — the caller falls back
to the Pro method and sets ``model_fallback: true`` in output.
"""

from __future__ import annotations

import json
from pathlib import Path

_MODEL_DIR = Path("/opt/features-tool/models")

_MODEL_SPECS = {
    "trend_forecaster": {
        "file": "trend_forecaster.onnx",
        "input_shape": "(batch, seq_len, n_features)",
        "output_shape": "(batch, horizon)",
        "description": "LSTM multi-step trend forecaster",
    },
    "anomaly_autoencoder": {
        "file": "anomaly_autoencoder.onnx",
        "input_shape": "(batch, n_metrics)",
        "output_shape": "(batch, n_metrics)",
        "description": "Autoencoder reconstruction error anomaly scorer",
    },
    "health_predictor": {
        "file": "health_predictor.onnx",
        "input_shape": "(batch, n_kpis)",
        "output_shape": "(batch, 1)",
        "description": "30-day health score predictor",
    },
    "spectrum_classifier": {
        "file": "spectrum_classifier.onnx",
        "input_shape": "(batch, freq_bins)",
        "output_shape": "(batch, n_classes)",
        "description": "CNN spectrum fault classifier",
    },
}


def load_model(name: str) -> dict | None:
    """Load an ONNX model and return metadata, or None if unavailable.

    Returns a dict with keys: session, spec, model_path on success.
    Returns None if onnxruntime or model file is missing.
    """
    if name not in _MODEL_SPECS:
        return None

    spec = _MODEL_SPECS[name]
    model_path = _MODEL_DIR / spec["file"]

    if not model_path.exists():
        return None

    try:
        import onnxruntime as ort

        session = ort.InferenceSession(str(model_path))
        return {"session": session, "spec": spec, "model_path": str(model_path)}
    except ImportError:
        return None
    except Exception:
        return None


def model_available(name: str) -> bool:
    """Check if an ONNX model file exists and onnxruntime is importable."""
    if name not in _MODEL_SPECS:
        return False
    if not (_MODEL_DIR / _MODEL_SPECS[name]["file"]).exists():
        return False
    try:
        import onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def model_specs() -> dict:
    """Return the full model specs dict for documentation."""
    return dict(_MODEL_SPECS)
