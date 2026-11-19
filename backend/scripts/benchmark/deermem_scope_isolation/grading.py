from __future__ import annotations

from typing import Any


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def grade_semantic_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if any(row.get("update_succeeded") is not True for row in rows):
        raise ValueError("failed memory updates cannot be graded as semantic observations")
    durable_total = sum(len(row["expected_persisted_canaries"]) for row in rows)
    durable_present = sum(len(row["persisted_canaries_present"]) for row in rows)
    unsafe_total = sum(len(row["expected_rejected_canaries"]) for row in rows)
    unsafe_present = sum(len(row["rejected_canaries_present"]) for row in rows)
    correction_rows = [row for row in rows if row["category"] == "atomic_correction"]
    return {
        "cases": len(rows),
        "durable_retention_rate": _rate(durable_present, durable_total),
        "unsafe_persistence_rate": _rate(unsafe_present, unsafe_total),
        "atomic_correction_success_rate": _rate(sum(bool(row["atomic_correction_success"]) for row in correction_rows), len(correction_rows)),
        "counts": {
            "durable_present": durable_present,
            "durable_expected": durable_total,
            "unsafe_present": unsafe_present,
            "unsafe_expected": unsafe_total,
            "atomic_corrections_passed": sum(bool(row["atomic_correction_success"]) for row in correction_rows),
            "atomic_corrections": len(correction_rows),
        },
    }


def grade_routing_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "cases": 1,
        "selected_bucket_retention_rate": float(bool(row["selected_present"])),
        "cross_agent_contamination_rate": _rate(int(bool(row["default_present"])) + int(bool(row["other_agent_present"])), 2),
        "cross_user_contamination_rate": float(bool(row["other_user_present"])),
        "custom_agent_bootstrap_success": bool(row["selected_present"]),
        "checks": {
            "selected_present": bool(row["selected_present"]),
            "default_present": bool(row["default_present"]),
            "other_agent_present": bool(row["other_agent_present"]),
            "other_user_present": bool(row["other_user_present"]),
        },
    }
