"""Inspection summary — factual report.

Sprint S5 enhancement — consumes ``inspection_data.json`` and produces a
fact-only summary: severity distribution with percentages, anomaly list
(warning + critical, sorted by severity desc), corrective recommendations.

No §13.2 evidence/confidence/human_review_required (factual report).
"""

from __future__ import annotations

import sys
from pathlib import Path

from _stub_helpers import (
    base_parser,
    emit_error,
    iso_now,
    read_json,
    write_json,
)


SCHEMA_VERSION = "1"

SEVERITY_ORDER = ["low", "medium", "high", "critical"]
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITY_ORDER)}


def _severity_distribution(records: list[dict]) -> list[dict]:
    counts = {s: 0 for s in SEVERITY_ORDER}
    for r in records:
        sev = r.get("severity", "low")
        counts[sev] = counts.get(sev, 0) + 1
    total = len(records) or 1
    return [
        {"severity": s, "count": counts[s], "percentage": round(counts[s] / total, 4)}
        for s in SEVERITY_ORDER
    ]


def _anomaly_list(records: list[dict]) -> list[dict]:
    """Records with severity >= medium, sorted by severity desc then time desc."""
    anomalies = [r for r in records if SEVERITY_RANK.get(r.get("severity", "low"), 0) >= 1]
    anomalies.sort(
        key=lambda r: (-SEVERITY_RANK.get(r.get("severity", "low"), 0), -ord((r.get("time") or " ")[-1] if r.get("time") else " ")),
    )
    return [
        {
            "id": r["id"],
            "time": r.get("time"),
            "equipment": r.get("equipment"),
            "inspector": r.get("inspector"),
            "severity": r.get("severity"),
            "status": r.get("status"),
            "description": r.get("description"),
        }
        for r in anomalies
    ]


def _recommendations(severity_dist: list[dict]) -> list[str]:
    by_sev = {row["severity"]: row["count"] for row in severity_dist}
    recs: list[str] = []
    if by_sev.get("critical", 0) > 0:
        recs.append(f"立即处置 {by_sev['critical']} 项 critical 巡检项，并启动应急复盘")
    if by_sev.get("high", 0) > 0:
        recs.append(f"24 小时内安排 {by_sev['high']} 项 high 风险项专项检查")
    if by_sev.get("medium", 0) > 0:
        recs.append(f"在下个巡检周期内复检 {by_sev['medium']} 项 medium 风险项")
    if not recs:
        recs.append("未发现 medium/high/critical 风险项，按周期巡检即可")
    return recs


def main() -> int:
    parser = base_parser("Inspection summary (factual report)")
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    try:
        raw = read_json(Path(args.input))
    except (FileNotFoundError, ValueError) as exc:
        return emit_error("INPUT_UNREADABLE", str(exc))

    records = raw.get("records") or []
    total = len(records)
    severity_dist = _severity_distribution(records)
    anomalies = _anomaly_list(records)
    recommendations = _recommendations(severity_dist)

    critical_count = next((row["count"] for row in severity_dist if row["severity"] == "critical"), 0)
    high_count = next((row["count"] for row in severity_dist if row["severity"] == "high"), 0)

    if critical_count > 0:
        level = "critical"
    elif high_count > 0:
        level = "warning"
    elif total > 0:
        level = "good"
    else:
        level = "warning"  # no records is suspicious

    overall_status = {
        "level": level,
        "summary": (
            f"共 {total} 条巡检记录，critical {critical_count}、high {high_count}、"
            f"异常合计 {len(anomalies)} 项。"
        )[:80],
        "total_records": total,
        "anomaly_count": len(anomalies),
    }

    output = {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "inspection_date": raw.get("inspection_date"),
            "route": raw.get("route"),
            "area": raw.get("area"),
            "severity_min": raw.get("severity_min"),
            "data_source": raw.get("data_source"),
        },
        "overall_status": overall_status,
        "severity_distribution": severity_dist,
        "anomaly_list": anomalies,
        "corrective_recommendations": recommendations,
        "_meta": {"stub": True, "generated_at": iso_now()},
    }
    write_json(Path(args.output_dir), "inspection_summary", output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
