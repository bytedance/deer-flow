"""Write `report.status.json` per spec §'lead agent 退出 status'.

状态判定逻辑：
- error_class in F1..F20            -> "error"
- error_class 为 None 且
  query_failures == 0 且
  compute_validation_failures == 0  -> "success"
- 其他                              -> "partial"
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _decide_status(error_class: str | None, metrics: dict) -> str:
    if error_class is not None:
        return "error"
    qf = int(metrics.get("query_failures", 0))
    cvf = int(metrics.get("compute_validation_failures", 0))
    if qf == 0 and cvf == 0:
        return "success"
    return "partial"


def write_status(
    out_path: str,
    *,
    exit_step: int,
    error_class: str | None,
    error_detail: str,
    outputs: dict[str, str | None],
    metrics: dict[str, Any],
) -> None:
    """以规格强制的形态持久化 report.status.json。"""
    payload = {
        "status": _decide_status(error_class, metrics),
        "exit_step": int(exit_step),
        "error_class": error_class,
        "error_detail": error_detail,
        "outputs": dict(outputs),
        "metrics": {
            "queried_count": int(metrics.get("queried_count", 0)),
            "query_failures": int(metrics.get("query_failures", 0)),
            "computed_count": int(metrics.get("computed_count", 0)),
            "compute_validation_failures": int(metrics.get("compute_validation_failures", 0)),
            "llm_calls": int(metrics.get("llm_calls", 0)),
            "duration_seconds": float(metrics.get("duration_seconds", 0.0)),
        },
    }
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                              encoding="utf-8")
