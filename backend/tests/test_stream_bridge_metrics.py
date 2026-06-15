"""Tests for stream bridge metrics collection."""

import pytest

from deerflow.runtime.stream_bridge.metrics import stream_bridge_metrics


@pytest.fixture(autouse=True)
def _reset_metrics():
    stream_bridge_metrics.reset()
    yield
    stream_bridge_metrics.reset()


class TestStreamBridgeMetrics:
    def test_record_publish_tracks_count_and_bytes(self):
        stream_bridge_metrics.record_publish("values", {"title": "Test"})
        stream_bridge_metrics.record_publish("values", {"title": "Another"})
        stream_bridge_metrics.record_publish("custom", {"type": "state_patch"})

        snap = stream_bridge_metrics.snapshot()
        assert snap["total_published"] == 3
        assert snap["total_payload_bytes"] > 0
        assert snap["avg_payload_bytes"] > 0
        assert snap["by_event_type"]["values"]["count"] == 2
        assert snap["by_event_type"]["custom"]["count"] == 1

    def test_record_backpressure_increments_counter(self):
        assert stream_bridge_metrics.snapshot()["backpressure_count"] == 0

        stream_bridge_metrics.record_backpressure()
        stream_bridge_metrics.record_backpressure()

        assert stream_bridge_metrics.snapshot()["backpressure_count"] == 2

    def test_queue_depth_tracking(self):
        stream_bridge_metrics.set_queue_depth("run-1", 100)
        stream_bridge_metrics.set_queue_depth("run-2", 200)

        snap = stream_bridge_metrics.snapshot()
        assert snap["active_runs"] == 2
        assert snap["total_queue_depth"] == 300

    def test_remove_run_decrements_depth(self):
        stream_bridge_metrics.set_queue_depth("run-1", 100)
        stream_bridge_metrics.set_queue_depth("run-2", 200)

        stream_bridge_metrics.remove_run("run-1")

        snap = stream_bridge_metrics.snapshot()
        assert snap["active_runs"] == 1
        assert snap["total_queue_depth"] == 200

    def test_zero_depth_removes_run(self):
        stream_bridge_metrics.set_queue_depth("run-1", 100)
        stream_bridge_metrics.set_queue_depth("run-1", 0)

        snap = stream_bridge_metrics.snapshot()
        assert snap["active_runs"] == 0
        assert snap["total_queue_depth"] == 0

    def test_avg_payload_bytes_zero_when_empty(self):
        snap = stream_bridge_metrics.snapshot()
        assert snap["avg_payload_bytes"] == 0.0

    def test_reset_clears_all(self):
        stream_bridge_metrics.record_publish("values", {"data": "test"})
        stream_bridge_metrics.record_backpressure()
        stream_bridge_metrics.set_queue_depth("run-1", 50)

        stream_bridge_metrics.reset()

        snap = stream_bridge_metrics.snapshot()
        assert snap["total_published"] == 0
        assert snap["backpressure_count"] == 0
        assert snap["active_runs"] == 0
        assert snap["total_queue_depth"] == 0

    def test_non_json_serializable_data_handled(self):
        """Non-serializable data should not crash, just record 0 bytes."""

        class Unserializable:
            pass

        stream_bridge_metrics.record_publish("custom", Unserializable())

        snap = stream_bridge_metrics.snapshot()
        assert snap["total_published"] == 1
        assert snap["by_event_type"]["custom"]["total_bytes"] == 0
