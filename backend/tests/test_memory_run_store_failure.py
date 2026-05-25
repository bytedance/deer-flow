"""ISSUE-02 regression: MemoryRunStore handles failure_category and failed_layer."""

import pytest

from deerflow.runtime.runs.store.memory import MemoryRunStore


@pytest.mark.asyncio
class TestMemoryRunStoreFailureFields:
    async def test_put_stores_failure_fields(self):
        store = MemoryRunStore()
        await store.put(
            "run-1",
            thread_id="thread-1",
            status="failed",
            failure_category="execution_failed",
            failed_layer="runtime",
        )
        record = await store.get("run-1")
        assert record is not None
        assert record["status"] == "failed"
        assert record["failure_category"] == "execution_failed"
        assert record["failed_layer"] == "runtime"

    async def test_put_without_failure_fields(self):
        store = MemoryRunStore()
        await store.put("run-2", thread_id="thread-2", status="running")
        record = await store.get("run-2")
        assert record is not None
        assert record["failure_category"] is None
        assert record["failed_layer"] is None

    async def test_update_status_stores_failure_fields(self):
        store = MemoryRunStore()
        await store.put("run-3", thread_id="thread-3")
        await store.update_status(
            "run-3", "failed",
            error="Something broke",
            failure_category="external_dependency_unavailable",
            failed_layer="external",
        )
        record = await store.get("run-3")
        assert record["status"] == "failed"
        assert record["error"] == "Something broke"
        assert record["failure_category"] == "external_dependency_unavailable"
        assert record["failed_layer"] == "external"

    async def test_update_status_partial_failure_fields(self):
        store = MemoryRunStore()
        await store.put("run-4", thread_id="thread-4")
        await store.update_status(
            "run-4", "failed",
            failure_category="upload_failed",
        )
        record = await store.get("run-4")
        assert record["failure_category"] == "upload_failed"
        assert record["failed_layer"] is None

    async def test_aggregate_tokens_uses_canonical_statuses(self):
        store = MemoryRunStore()
        await store.put("r1", thread_id="t1", status="success")
        await store.put("r2", thread_id="t1", status="failed")
        await store.put("r3", thread_id="t1", status="cancelled")
        await store.update_run_completion("r1", status="success", total_tokens=100)
        await store.update_run_completion("r2", status="failed", total_tokens=50)
        await store.update_run_completion("r3", status="cancelled", total_tokens=200)
        result = await store.aggregate_tokens_by_thread("t1")
        # cancelled should not be included; only success + failed
        assert result["total_tokens"] == 150
        assert result["total_runs"] == 2
