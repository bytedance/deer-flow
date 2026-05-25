"""Tests for retrieval telemetry recording in multi_kb_retrieve and search_knowledge_base."""

from __future__ import annotations

import pytest

from deerflow.config.rag_config import RagConfig, set_rag_config
from deerflow.knowledge_base.telemetry import KbTelemetryCollector, get_kb_telemetry


class TestRetrievalTelemetryCollector:
    def test_records_retrieval_completed_event(self):
        t = KbTelemetryCollector()
        t.record_event("retrieval.completed", {
            "total_results": 5,
            "kb_count": 2,
            "per_kb_hits": {"kb-1": 3, "kb-2": 2},
        })
        assert t.get("event.retrieval.completed") == 1

    def test_records_retrieval_timeout_event(self):
        t = KbTelemetryCollector()
        t.record_event("retrieval.timeout", {
            "kb_id": "kb-1",
            "timeout_ms": 5000,
        })
        assert t.get("event.retrieval.timeout") == 1

    def test_records_retrieval_failed_event(self):
        t = KbTelemetryCollector()
        t.record_event("retrieval.failed", {
            "kb_id": "kb-2",
            "error_type": "ConnectionError",
        })
        assert t.get("event.retrieval.failed") == 1

    def test_records_retrieval_blocked_event(self):
        t = KbTelemetryCollector()
        t.record_event("retrieval.blocked", {
            "source": "tool",
            "reason": "rag.enabled=false",
        })
        assert t.get("event.retrieval.blocked") == 1

    def test_multiple_events_accumulate(self):
        t = KbTelemetryCollector()
        t.record_event("retrieval.completed", {"total_results": 3})
        t.record_event("retrieval.completed", {"total_results": 7})
        t.record_event("retrieval.failed", {"kb_id": "x"})
        assert t.get("event.retrieval.completed") == 2
        assert t.get("event.retrieval.failed") == 1

    def test_snapshot_includes_retrieval_events(self):
        t = KbTelemetryCollector()
        t.record_event("retrieval.completed", {})
        t.record_event("retrieval.timeout", {})
        snap = t.snapshot()
        assert snap.get("event.retrieval.completed") == 1
        assert snap.get("event.retrieval.timeout") == 1

    def test_record_event_increments_counter_only(self):
        """record_event without log_path increments counter but doesn't write file."""
        t = KbTelemetryCollector()
        t.record_event("retrieval.completed", {"total_results": 1})
        assert t.get("event.retrieval.completed") == 1


class TestRetrievalLatencyRecording:
    def test_record_and_retrieve_latency(self):
        t = KbTelemetryCollector()
        t.record_latency("kb-a", 100.0)
        t.record_latency("kb-a", 200.0)
        stats = t.latency_stats("kb-a")
        assert stats["total_queries"] == 2
        assert stats["avg_ms"] == 150.0

    def test_zero_latency_for_unknown_kb(self):
        t = KbTelemetryCollector()
        stats = t.latency_stats("nonexistent")
        assert stats["avg_ms"] == 0.0
        assert stats["p95_ms"] == 0.0
        assert stats["total_queries"] == 0

    def test_latency_isolated_per_kb(self):
        t = KbTelemetryCollector()
        t.record_latency("kb-a", 100.0)
        t.record_latency("kb-b", 300.0)
        assert t.latency_stats("kb-a")["avg_ms"] == 100.0
        assert t.latency_stats("kb-b")["avg_ms"] == 300.0


class TestSearchKnowledgeBaseTelemetry:
    @pytest.mark.asyncio
    async def test_disabled_rag_records_blocked_event(self):
        """When RAG is disabled, search_knowledge_base records retrieval.blocked."""
        from deerflow.rag.tools import search_knowledge_base

        t = get_kb_telemetry()
        t.clear()
        set_rag_config(RagConfig(enabled=False))
        try:
            await search_knowledge_base.ainvoke({"query": "test query"})
            assert t.get("event.retrieval.blocked") == 1
        finally:
            set_rag_config(RagConfig())
            t.clear()

    def test_clear_resets_all_counters(self):
        t = KbTelemetryCollector()
        t.record_event("retrieval.completed", {})
        t.record_latency("kb-x", 50.0)
        t.clear()
        assert t.get("event.retrieval.completed") == 0
        assert t.latency_stats("kb-x")["total_queries"] == 0


class TestMultiKbRetrieveTelemetry:
    def test_empty_kb_list_no_telemetry(self):
        """multi_kb_retrieve with empty list returns [] without recording completed."""
        from deerflow.knowledge_base.retrieval import multi_kb_retrieve

        t = get_kb_telemetry()
        t.clear()
        try:
            result = multi_kb_retrieve([], "test query")
            assert result == []
            # Empty list returns early, no retrieval.completed should be recorded
            assert t.get("event.retrieval.completed") == 0
        finally:
            t.clear()
