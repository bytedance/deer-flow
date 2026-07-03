"""Write `report.status.json` per spec §'lead agent 退出 status'.

状态判定逻辑：
- error_class in F1..F20            -> "error"
- error_class 为 None 且
  query_failures == 0 且
  compute_validation_failures == 0 且
  description_failures == 0 且
  chart_failures == 0               -> "success"
- 其他                              -> "partial"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _chart_metrics_from_manifest(manifest_path: str | None) -> dict[str, int]:
    """Derive chart counts from the chart_gen manifest. Returns zeros if missing."""
    zero = {"charts_declared": 0, "charts_generated": 0, "chart_failures": 0}
    if not manifest_path:
        return zero
    p = Path(manifest_path)
    if not p.exists():
        return zero
    try:
        manifest = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return zero
    summary = manifest.get("summary", {})
    ok = int(summary.get("ok", 0))
    failed = int(summary.get("failed", 0))
    return {
        "charts_declared": ok + failed,
        "charts_generated": ok,
        "chart_failures": failed,
    }


def _decide_status(error_class: str | None, metrics: dict) -> str:
    if error_class is not None:
        return "error"
    qf = int(metrics.get("query_failures", 0))
    cvf = int(metrics.get("compute_validation_failures", 0))
    df = int(metrics.get("description_failures", 0))
    cf = int(metrics.get("chart_failures", 0))
    if qf == 0 and cvf == 0 and df == 0 and cf == 0:
        return "success"
    return "partial"


def _serialize_exit_step(exit_step: str | int) -> str | int:
    text = str(exit_step)
    if text.isdigit():
        return int(text)
    return text


def write_status(
    out_path: str,
    *,
    exit_step: str | int,
    error_class: str | None,
    error_detail: str,
    outputs: dict[str, str | None],
    metrics: dict[str, Any],
    charts_manifest: str | None = None,
) -> None:
    """以规格强制的形态持久化 report.status.json。"""
    metrics = {**metrics, **_chart_metrics_from_manifest(charts_manifest)}
    if charts_manifest and "charts_manifest" not in outputs:
        outputs = {**outputs, "charts_manifest": charts_manifest}
    payload = {
        "status": _decide_status(error_class, metrics),
        "exit_step": _serialize_exit_step(exit_step),
        "error_class": error_class,
        "error_detail": error_detail,
        "outputs": dict(outputs),
        "metrics": {
            "queried_count": int(metrics.get("queried_count", 0)),
            "query_failures": int(metrics.get("query_failures", 0)),
            "computed_count": int(metrics.get("computed_count", 0)),
            "compute_validation_failures": int(metrics.get("compute_validation_failures", 0)),
            "descriptions_generated": int(metrics.get("descriptions_generated", 0)),
            "description_failures": int(metrics.get("description_failures", 0)),
            "charts_declared": int(metrics.get("charts_declared", 0)),
            "charts_generated": int(metrics.get("charts_generated", 0)),
            "chart_failures": int(metrics.get("chart_failures", 0)),
            "llm_calls": int(metrics.get("llm_calls", 0)),
            "duration_seconds": float(metrics.get("duration_seconds", 0.0)),
        },
    }
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                              encoding="utf-8")


def _json_arg(value: str) -> dict:
    path = Path(value)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="assemble_status", description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--exit-step", required=True)
    parser.add_argument("--error-class", default=None)
    parser.add_argument("--error-detail", default="")
    parser.add_argument("--outputs", required=True, help="JSON object or path")
    parser.add_argument("--metrics", required=True, help="JSON object or path")
    parser.add_argument("--charts-manifest", default=None)
    args = parser.parse_args(argv)

    try:
        write_status(
            args.out,
            exit_step=args.exit_step,
            error_class=args.error_class,
            error_detail=args.error_detail,
            outputs=_json_arg(args.outputs),
            metrics=_json_arg(args.metrics),
            charts_manifest=args.charts_manifest,
        )
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"OK: wrote status -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
