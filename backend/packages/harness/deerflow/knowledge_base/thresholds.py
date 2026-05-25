"""Recommended observation thresholds for knowledge-link health metrics.

These thresholds drive the health status indicators in the frontend
and can be used by external alerting/monitoring systems.

Reference: docs/knowledge-link-metrics.md
"""

from __future__ import annotations

from typing import Any

# Threshold constants
# ---------
# Each threshold is a (value, description) pair.
# "critical" means immediate action is recommended.
# "warning" means attention is needed within the current sprint.

RECOMMENDED_THRESHOLDS: dict[str, dict[str, Any]] = {
    "index_success_rate": {
        "critical": 0.85,  # below 85% success needs immediate attention
        "warning": 0.95,   # below 95% success needs attention
        "unit": "ratio",
        "description": "Proportion of documents successfully indexed (ready / total)",
    },
    "retrieval_p95_latency_ms": {
        "critical": 2000.0,  # above 2s p95 is unacceptable
        "warning": 500.0,    # above 500ms p95 needs attention
        "unit": "ms",
        "description": "P95 end-to-end retrieval latency per knowledge base",
    },
    "retrieval_avg_latency_ms": {
        "warning": 300.0,  # above 300ms avg is worth investigating
        "unit": "ms",
        "description": "Average retrieval latency across all queries",
    },
    "failed_doc_count": {
        "warning": 5,   # more than 5 failed docs per tenant
        "critical": 20,  # more than 20 failed docs per tenant
        "unit": "count",
        "description": "Number of documents in failed index status",
    },
    "failure_rate_spike": {
        "warning": 0.10,  # failure rate increases by 10 percentage points in 24h
        "unit": "ratio",
        "description": "Sudden increase in index failure rate within 24 hours",
    },
}


def health_check(summary: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a health summary against recommended thresholds.

    Returns a dict with status ("healthy" | "warning" | "critical")
    and a list of triggered threshold violations.
    """
    violations: list[dict[str, Any]] = []

    # Index success rate
    index_rate = float(summary.get("index_success_rate") or 0.0)
    docs = summary.get("documents") or {}
    total_docs = int(docs.get("total") or 0)
    if total_docs > 0:
        critical = RECOMMENDED_THRESHOLDS["index_success_rate"]["critical"]
        warning = RECOMMENDED_THRESHOLDS["index_success_rate"]["warning"]
        if index_rate < critical:
            violations.append({
                "metric": "index_success_rate",
                "level": "critical",
                "value": index_rate,
                "threshold": critical,
                "message": f"Index success rate {index_rate:.1%} below critical threshold {critical:.0%}",
            })
        elif index_rate < warning:
            violations.append({
                "metric": "index_success_rate",
                "level": "warning",
                "value": index_rate,
                "threshold": warning,
                "message": f"Index success rate {index_rate:.1%} below warning threshold {warning:.0%}",
            })

    # Retrieval p95 latency
    retrieval = summary.get("retrieval") or {}
    p95 = float(retrieval.get("p95_latency_ms") or 0.0)
    total_queries = int(retrieval.get("total_queries") or 0)
    if total_queries > 0:
        critical_lat = RECOMMENDED_THRESHOLDS["retrieval_p95_latency_ms"]["critical"]
        warning_lat = RECOMMENDED_THRESHOLDS["retrieval_p95_latency_ms"]["warning"]
        if p95 > critical_lat:
            violations.append({
                "metric": "retrieval_p95_latency_ms",
                "level": "critical",
                "value": p95,
                "threshold": critical_lat,
                "message": f"P95 retrieval latency {p95:.0f}ms exceeds critical threshold {critical_lat:.0f}ms",
            })
        elif p95 > warning_lat:
            violations.append({
                "metric": "retrieval_p95_latency_ms",
                "level": "warning",
                "value": p95,
                "threshold": warning_lat,
                "message": f"P95 retrieval latency {p95:.0f}ms exceeds warning threshold {warning_lat:.0f}ms",
            })

    # Failed doc count
    failed = int(docs.get("failed") or 0)
    if failed >= RECOMMENDED_THRESHOLDS["failed_doc_count"]["critical"]:
        violations.append({
            "metric": "failed_doc_count",
            "level": "critical",
            "value": failed,
            "threshold": RECOMMENDED_THRESHOLDS["failed_doc_count"]["critical"],
            "message": f"{failed} failed documents exceeds critical threshold",
        })
    elif failed >= RECOMMENDED_THRESHOLDS["failed_doc_count"]["warning"]:
        violations.append({
            "metric": "failed_doc_count",
            "level": "warning",
            "value": failed,
            "threshold": RECOMMENDED_THRESHOLDS["failed_doc_count"]["warning"],
            "message": f"{failed} failed documents exceeds warning threshold",
        })

    # Determine overall status
    if any(v["level"] == "critical" for v in violations):
        status = "critical"
    elif violations:
        status = "warning"
    else:
        status = "healthy"

    return {
        "status": status,
        "violations": violations,
        "thresholds_ref": RECOMMENDED_THRESHOLDS,
    }
