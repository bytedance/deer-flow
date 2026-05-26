#!/usr/bin/env python
"""Pro-tier spectrum analysis: Hilbert envelope, cepstrum, bearing fault frequency matching, sideband detection.

Consumes ``waveform_data.json`` and ``spectrum_features.json``, produces ``pro_spectrum_result.json``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from _stub_helpers import base_parser, emit_error, read_json, write_json

SCHEMA_VERSION = "2"

# Bearing fault characteristic frequencies (orders of rotation speed)
# BPFO: outer race, BPFI: inner race, BSF: ball spin, FTF: cage
BEARING_FAULT_ORDERS = {
    "BPFO": {"label": "外圈故障 (BPFO)", "order_factor": 3.1},   # Typical ~3.1x for common bearings
    "BPFI": {"label": "内圈故障 (BPFI)", "order_factor": 4.9},
    "BSF": {"label": "滚动体故障 (BSF)", "order_factor": 2.0},
    "FTF": {"label": "保持架故障 (FTF)", "order_factor": 0.4},
}


def _hilbert_envelope(signal: list[float]) -> dict | None:
    """Compute Hilbert envelope spectrum."""
    try:
        import numpy as np
        from scipy import signal as sp_signal
    except ImportError:
        return None

    clean = np.array([v for v in signal if v is not None], dtype=float)
    if len(clean) < 16:
        return None

    analytic = sp_signal.hilbert(clean)
    envelope = np.abs(analytic)

    # FFT of envelope
    n = len(envelope)
    fft = np.fft.rfft(envelope)
    freqs = np.fft.rfftfreq(n, d=1.0)  # normalized frequency
    mag = np.abs(fft)

    # Only keep low-frequency range (envelope spectrum is low-freq)
    cutoff = min(len(mag), 200)
    return {
        "frequencies": freqs[:cutoff].tolist(),
        "magnitudes": mag[:cutoff].tolist(),
    }


def _cepstrum(signal: list[float]) -> dict | None:
    """Compute real cepstrum (inverse FFT of log magnitude spectrum)."""
    try:
        import numpy as np
    except ImportError:
        return None

    clean = np.array([v for v in signal if v is not None], dtype=float)
    if len(clean) < 16:
        return None

    n = len(clean)
    fft = np.fft.rfft(clean)
    log_mag = np.log(np.abs(fft) + 1e-8)
    cep = np.fft.irfft(log_mag, n=n)

    # Quefrency axis (first half)
    half = n // 2
    return {
        "quefrencies": list(range(half)),
        "amplitudes": cep[:half].tolist(),
    }


def _bearing_fault_match(
    speed_hz: float | None,
    spec_freqs: list[float],
    spec_mags: list[float],
) -> list[dict]:
    """Match spectral peaks against bearing fault frequency orders."""
    if speed_hz is None or speed_hz <= 0:
        return []

    matches = []
    for fault_key, fault_info in BEARING_FAULT_ORDERS.items():
        target_freq = speed_hz * fault_info["order_factor"]
        # Find nearest peak
        best_idx = None
        best_dist = float("inf")
        for i, f in enumerate(spec_freqs):
            if f <= 0:
                continue
            dist = abs(f - target_freq) / target_freq
            if dist < 0.05 and dist < best_dist:  # within 5%
                best_dist = dist
                best_idx = i

        if best_idx is not None:
            matches.append({
                "fault_type": fault_key,
                "fault_label": fault_info["label"],
                "target_freq_hz": round(target_freq, 2),
                "measured_freq_hz": round(spec_freqs[best_idx], 2),
                "deviation_pct": round(best_dist * 100, 1),
                "amplitude": round(spec_mags[best_idx], 4),
            })

    # Sort by smallest deviation
    matches.sort(key=lambda m: m["deviation_pct"])
    return matches


def _sideband_detection(
    spec_freqs: list[float],
    spec_mags: list[float],
    carrier_freq: float | None = None,
    modulation_freq: float | None = None,
) -> list[dict]:
    """Detect sidebands around a carrier frequency."""
    if carrier_freq is None or carrier_freq <= 0:
        return []

    sidebands = []
    for harmonic in range(1, 4):  # 1X, 2X, 3X
        cf = carrier_freq * harmonic
        for sb_offset in [1, 2]:  # ±1, ±2 sidebands
            if modulation_freq is None:
                continue
            for sign in [-1, 1]:
                sb_freq = cf + sign * modulation_freq * sb_offset
                if sb_freq <= 0:
                    continue
                # Find nearest spectral peak
                for i, f in enumerate(spec_freqs):
                    if abs(f - sb_freq) / max(sb_freq, 1) < 0.03:
                        sidebands.append({
                            "carrier_harmonic": harmonic,
                            "sideband_order": sb_offset,
                            "side": "upper" if sign > 0 else "lower",
                            "frequency_hz": round(f, 2),
                            "amplitude": round(spec_mags[i], 4),
                        })

    return sidebands


def analyze_spectrum_pro(
    waveform_data: dict,
    spectrum_features: dict,
    equipment_type: str = "",
) -> dict:
    """Pro-tier spectrum analysis."""
    speed_hz = spectrum_features.get("speed_hz") or waveform_data.get("speed_hz")
    points = waveform_data.get("points", [])

    hilbert_results: list[dict] = []
    cepstrum_results: list[dict] = []
    bearing_matches: list[dict] = []
    sidebands: list[dict] = []

    for point in points:
        point_id = point.get("point_id", "")
        wave_y = point.get("wave_y") or point.get("data", {}).get("wave_y", [])

        if len(wave_y) < 16:
            continue

        # Hilbert envelope
        env = _hilbert_envelope(wave_y)
        if env:
            hilbert_results.append({
                "point_id": point_id,
                "envelope": env,
            })

        # Cepstrum
        cep = _cepstrum(wave_y)
        if cep:
            cepstrum_results.append({
                "point_id": point_id,
                "cepstrum": cep,
            })

        # Bearing fault matching from spectrum features
        spec_x = point.get("spec_x") or point.get("data", {}).get("spec_x", [])
        spec_y = point.get("spec_y") or point.get("data", {}).get("spec_y", [])
        matches = _bearing_fault_match(speed_hz, spec_x, spec_y)
        if matches:
            bearing_matches.extend([{**m, "point_id": point_id} for m in matches])

        # Sideband detection (1X as carrier)
        if speed_hz and spec_x:
            sbs = _sideband_detection(spec_x, spec_y, carrier_freq=speed_hz, modulation_freq=speed_hz * 0.5)
            if sbs:
                sidebands.extend([{**s, "point_id": point_id} for s in sbs])

    return {
        "schema_version": SCHEMA_VERSION,
        "speed_hz": speed_hz,
        "hilbert_envelope": hilbert_results,
        "cepstrum": cepstrum_results,
        "bearing_fault_match": bearing_matches,
        "sideband_detection": sidebands,
        "equipment_type": equipment_type,
    }


def main() -> int:
    parser = base_parser(description="Pro-tier spectrum analysis")
    parser.add_argument("--input", required=True, help="Path to waveform_data.json")
    parser.add_argument("--features", required=True, help="Path to spectrum_features.json")
    parser.add_argument("--equipment-type", default="", help="Equipment type for domain context")
    args = parser.parse_args()

    # Check optional dependencies
    try:
        import scipy  # noqa: F401
    except ImportError:
        emit_error(
            "DEPENDENCY_MISSING",
            "scipy not installed. Install with: pip install scipy",
        )
        return 0

    wf = read_json(Path(args.input))
    if wf is None:
        emit_error("BAD_INPUT", f"Failed to read {args.input}")
        return 0

    sf = read_json(Path(args.features))
    if sf is None:
        emit_error("BAD_INPUT", f"Failed to read {args.features}")
        return 0

    result = analyze_spectrum_pro(wf, sf, equipment_type=args.equipment_type)

    out_path = write_json(Path(args.output_dir), "pro_spectrum_result", result)

    print(json.dumps({
        "ok": True,
        "hilbert_points": len(result["hilbert_envelope"]),
        "cepstrum_points": len(result["cepstrum"]),
        "bearing_matches": len(result["bearing_fault_match"]),
        "sidebands": len(result["sideband_detection"]),
        "output": str(out_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
