"""Tests for the EvalRunRow ORM model (spec 2026-08-24 §3.1)."""

from __future__ import annotations

from datetime import UTC, datetime

from deerflow_knowledge.models import EvalRunRow


class TestEvalRunRow:
    """Field completeness and JSON serialization for eval_runs table."""

    def test_required_fields(self) -> None:
        """All required fields are present and correctly typed."""
        now = datetime.now(UTC)
        row = EvalRunRow(
            id="test-run-001",
            kb_id="kb-001",
            status="completed",
            layer1_metrics={"hit_rate": 0.95, "recall_at_k": 0.92},
            layer2_metrics={"faithfulness": 0.93},
            created_at=now,
        )
        assert row.id == "test-run-001"
        assert row.kb_id == "kb-001"
        assert row.status == "completed"
        assert row.layer1_metrics["hit_rate"] == 0.95
        assert row.layer2_metrics["faithfulness"] == 0.93
        assert row.created_at == now
        assert row.completed_at is None
        assert row.langfuse_trace_url is None
        assert row.baseline_diff is None

    def test_optional_fields_nullable(self) -> None:
        """Optional fields can be None."""
        row = EvalRunRow(
            id="test-run-002",
            kb_id="kb-001",
            status="skipped",
            layer1_metrics={},
            layer2_metrics={},
            created_at=datetime.now(UTC),
            completed_at=None,
            langfuse_trace_url=None,
            baseline_diff=None,
        )
        assert row.completed_at is None
        assert row.langfuse_trace_url is None
        assert row.baseline_diff is None

    def test_json_fields_serialization(self) -> None:
        """JSON fields serialize and deserialize correctly."""
        layer1 = {
            "fact": {"hit_rate": 0.95, "recall_at_k": 0.92, "mrr": 0.88, "path_accuracy": 0.98},
            "relation": {"hit_rate": 0.88, "recall_at_k": 0.85, "mrr": 0.65, "path_accuracy": 0.92},
            "summary": {"hit_rate": 0.92, "recall_at_k": 0.89, "mrr": 0.81, "path_accuracy": 0.95},
        }
        layer2 = {
            "ragas": {"faithfulness": 0.93, "answer_relevancy": 0.88},
            "arch_specific": {"citation_precision": 0.94, "citation_recall": 0.59, "seed_hit_rate": None},
        }
        row = EvalRunRow(
            id="test-run-003",
            kb_id="kb-001",
            status="completed",
            layer1_metrics=layer1,
            layer2_metrics=layer2,
            created_at=datetime.now(UTC),
        )
        assert row.layer1_metrics["fact"]["hit_rate"] == 0.95
        assert row.layer1_metrics["summary"]["recall_at_k"] == 0.89
        assert row.layer2_metrics["ragas"]["faithfulness"] == 0.93
        assert row.layer2_metrics["arch_specific"]["seed_hit_rate"] is None

    def test_status_values(self) -> None:
        """Status field accepts expected values."""
        for status in ("completed", "error", "skipped"):
            row = EvalRunRow(
                id=f"test-{status}",
                kb_id="kb-001",
                status=status,
                layer1_metrics={},
                layer2_metrics={},
                created_at=datetime.now(UTC),
            )
            assert row.status == status

    def test_baseline_diff_structure(self) -> None:
        """baseline_diff JSON field stores diff data correctly."""
        baseline_diff = {
            "recall_at_k_delta": -0.025,
            "regression_detected": False,
            "threshold_percent": 3,
        }
        row = EvalRunRow(
            id="test-run-004",
            kb_id="kb-001",
            status="completed",
            layer1_metrics={},
            layer2_metrics={},
            created_at=datetime.now(UTC),
            baseline_diff=baseline_diff,
        )
        assert row.baseline_diff["recall_at_k_delta"] == -0.025
        assert row.baseline_diff["regression_detected"] is False
        assert row.baseline_diff["threshold_percent"] == 3
