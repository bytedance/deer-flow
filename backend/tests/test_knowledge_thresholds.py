"""Tests for knowledge observability thresholds."""

from __future__ import annotations

from deerflow.knowledge_base.thresholds import RECOMMENDED_THRESHOLDS, health_check


class TestRecommendedThresholds:
    def test_all_required_thresholds_defined(self):
        required = [
            "index_success_rate",
            "retrieval_p95_latency_ms",
            "retrieval_avg_latency_ms",
            "failed_doc_count",
            "failure_rate_spike",
        ]
        for key in required:
            assert key in RECOMMENDED_THRESHOLDS, f"Missing threshold: {key}"
            assert "unit" in RECOMMENDED_THRESHOLDS[key]
            assert "description" in RECOMMENDED_THRESHOLDS[key]

    def test_threshold_values_are_reasonable(self):
        t = RECOMMENDED_THRESHOLDS
        assert 0 < t["index_success_rate"]["critical"] < t["index_success_rate"]["warning"] <= 1.0
        assert 0 < t["retrieval_p95_latency_ms"]["warning"] < t["retrieval_p95_latency_ms"]["critical"]
        assert t["failed_doc_count"]["warning"] < t["failed_doc_count"]["critical"]


class TestHealthCheck:
    def test_healthy_when_all_metrics_good(self):
        summary = {
            "index_success_rate": 0.98,
            "documents": {"total": 100, "ready": 98, "failed": 0},
            "retrieval": {"p95_latency_ms": 200.0, "total_queries": 100},
        }
        result = health_check(summary)
        assert result["status"] == "healthy"
        assert result["violations"] == []

    def test_warning_on_low_success_rate(self):
        summary = {
            "index_success_rate": 0.90,
            "documents": {"total": 100, "ready": 90, "failed": 10},
            "retrieval": {"p95_latency_ms": 200.0, "total_queries": 100},
        }
        result = health_check(summary)
        assert result["status"] == "warning"
        assert any(v["metric"] == "index_success_rate" for v in result["violations"])

    def test_critical_on_very_low_success_rate(self):
        summary = {
            "index_success_rate": 0.80,
            "documents": {"total": 100, "ready": 80, "failed": 20},
            "retrieval": {"p95_latency_ms": 200.0, "total_queries": 100},
        }
        result = health_check(summary)
        assert result["status"] == "critical"
        assert any(
            v["level"] == "critical" and v["metric"] == "index_success_rate"
            for v in result["violations"]
        )

    def test_warning_on_high_p95_latency(self):
        summary = {
            "index_success_rate": 1.0,
            "documents": {"total": 10, "ready": 10, "failed": 0},
            "retrieval": {"p95_latency_ms": 800.0, "total_queries": 100},
        }
        result = health_check(summary)
        assert result["status"] == "warning"
        assert any(v["metric"] == "retrieval_p95_latency_ms" for v in result["violations"])

    def test_critical_on_very_high_p95_latency(self):
        summary = {
            "index_success_rate": 1.0,
            "documents": {"total": 10, "ready": 10, "failed": 0},
            "retrieval": {"p95_latency_ms": 2500.0, "total_queries": 100},
        }
        result = health_check(summary)
        assert result["status"] == "critical"

    def test_no_queries_skips_latency_check(self):
        summary = {
            "index_success_rate": 1.0,
            "documents": {"total": 10, "ready": 10, "failed": 0},
            "retrieval": {"p95_latency_ms": 9999.0, "total_queries": 0},
        }
        result = health_check(summary)
        assert result["status"] == "healthy"

    def test_warning_on_failed_docs(self):
        summary = {
            "index_success_rate": 1.0,
            "documents": {"total": 10, "ready": 5, "failed": 6},
            "retrieval": {"p95_latency_ms": 200.0, "total_queries": 0},
        }
        result = health_check(summary)
        assert result["status"] == "warning"
        assert any(v["metric"] == "failed_doc_count" for v in result["violations"])

    def test_empty_summary_is_healthy(self):
        summary = {
            "index_success_rate": 0.0,
            "documents": {"total": 0, "ready": 0, "failed": 0},
            "retrieval": {"p95_latency_ms": 0.0, "total_queries": 0},
        }
        result = health_check(summary)
        assert result["status"] == "healthy"
