"""Tests for UsageStorage — JSON-file persistence for token usage records."""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from deerflow.config.tenant import set_current_tenant_id
from deerflow.cost.storage import UsageRecord, UsageStorage


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def storage(temp_dir):
    set_current_tenant_id("test-tenant")
    return UsageStorage(base_dir=temp_dir)


class TestUsageRecord:
    def test_to_dict(self):
        record = UsageRecord(
            timestamp="2025-01-15T10:30:00",
            tenant_id="t1",
            thread_id="th1",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            cost_usd=0.0045,
        )
        d = record.to_dict()
        assert d["timestamp"] == "2025-01-15T10:30:00"
        assert d["tenant_id"] == "t1"
        assert d["thread_id"] == "th1"
        assert d["model_name"] == "gpt-4"
        assert d["input_tokens"] == 100
        assert d["output_tokens"] == 50
        assert d["total_tokens"] == 150
        assert d["cost_usd"] == 0.0045

    def test_from_dict(self):
        d = {
            "timestamp": "2025-01-15T10:30:00",
            "tenant_id": "t1",
            "thread_id": "th1",
            "model_name": "gpt-4",
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "cost_usd": 0.0045,
        }
        record = UsageRecord.from_dict(d)
        assert record.timestamp == "2025-01-15T10:30:00"
        assert record.tenant_id == "t1"
        assert record.thread_id == "th1"
        assert record.model_name == "gpt-4"
        assert record.input_tokens == 100
        assert record.output_tokens == 50
        assert record.total_tokens == 150
        assert record.cost_usd == 0.0045

    def test_from_dict_missing_thread_id(self):
        d = {
            "timestamp": "2025-01-15T10:30:00",
            "tenant_id": "t1",
            "model_name": "gpt-4",
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "cost_usd": 0.0045,
        }
        record = UsageRecord.from_dict(d)
        assert record.thread_id is None


class TestUsageStorage:
    def test_add_and_query(self, storage):
        record = UsageRecord(
            timestamp="2025-01-15T10:30:00",
            tenant_id="test-tenant",
            thread_id="th1",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            cost_usd=0.0045,
        )
        storage.add_record(record)
        results = storage.query()
        assert len(results) == 1
        assert results[0].model_name == "gpt-4"

    def test_query_by_date_range(self, storage):
        storage.add_record(UsageRecord(
            timestamp="2025-01-15T10:30:00", tenant_id="t1", thread_id=None,
            model_name="gpt-4", input_tokens=100, output_tokens=50, total_tokens=150, cost_usd=0.01,
        ))
        storage.add_record(UsageRecord(
            timestamp="2025-02-20T14:00:00", tenant_id="t1", thread_id=None,
            model_name="gpt-4", input_tokens=200, output_tokens=100, total_tokens=300, cost_usd=0.02,
        ))
        results = storage.query(start_date="2025-02-01")
        assert len(results) == 1
        assert results[0].cost_usd == 0.02

    def test_query_by_model(self, storage):
        storage.add_record(UsageRecord(
            timestamp="2025-01-15T10:30:00", tenant_id="t1", thread_id=None,
            model_name="gpt-4", input_tokens=100, output_tokens=50, total_tokens=150, cost_usd=0.01,
        ))
        storage.add_record(UsageRecord(
            timestamp="2025-01-16T10:30:00", tenant_id="t1", thread_id=None,
            model_name="gpt-3.5", input_tokens=200, output_tokens=100, total_tokens=300, cost_usd=0.02,
        ))
        results = storage.query(model_name="gpt-3.5")
        assert len(results) == 1
        assert results[0].model_name == "gpt-3.5"

    def test_empty_storage_returns_empty(self, storage):
        assert storage.query() == []

    def test_get_daily_total(self, storage):
        storage.add_record(UsageRecord(
            timestamp="2025-01-15T10:30:00", tenant_id="t1", thread_id=None,
            model_name="gpt-4", input_tokens=100, output_tokens=50, total_tokens=150, cost_usd=0.01,
        ))
        storage.add_record(UsageRecord(
            timestamp="2025-01-15T14:00:00", tenant_id="t1", thread_id=None,
            model_name="gpt-4", input_tokens=200, output_tokens=100, total_tokens=300, cost_usd=0.02,
        ))
        total = storage.get_daily_total("2025-01-15")
        assert total == 0.03

    def test_get_monthly_total(self, storage):
        storage.add_record(UsageRecord(
            timestamp="2025-01-15T10:30:00", tenant_id="t1", thread_id=None,
            model_name="gpt-4", input_tokens=100, output_tokens=50, total_tokens=150, cost_usd=0.01,
        ))
        storage.add_record(UsageRecord(
            timestamp="2025-02-01T10:30:00", tenant_id="t1", thread_id=None,
            model_name="gpt-4", input_tokens=200, output_tokens=100, total_tokens=300, cost_usd=0.02,
        ))
        total = storage.get_monthly_total("2025-01")
        assert total == 0.01

    def test_get_total_tokens_today(self, storage):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        storage.add_record(UsageRecord(
            timestamp=f"{today}T10:30:00", tenant_id="t1", thread_id=None,
            model_name="gpt-4", input_tokens=100, output_tokens=50, total_tokens=150, cost_usd=0.01,
        ))
        tokens = storage.get_total_tokens_today()
        assert tokens == 150

    def test_get_total_tokens_month(self, storage):
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        storage.add_record(UsageRecord(
            timestamp=f"{month}-15T10:30:00", tenant_id="t1", thread_id=None,
            model_name="gpt-4", input_tokens=100, output_tokens=50, total_tokens=150, cost_usd=0.01,
        ))
        tokens = storage.get_total_tokens_month()
        assert tokens == 150

    def test_atomic_write_persists(self, storage, temp_dir):
        record = UsageRecord(
            timestamp="2025-01-15T10:30:00", tenant_id="test-tenant", thread_id=None,
            model_name="gpt-4", input_tokens=100, output_tokens=50, total_tokens=150, cost_usd=0.01,
        )
        storage.add_record(record)
        usage_file = temp_dir / "tenants" / "test-tenant" / "token_usage.json"
        assert usage_file.exists()
        with open(usage_file, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 1

    def test_corrupted_file_handled(self, storage, temp_dir):
        usage_file = temp_dir / "tenants" / "test-tenant" / "token_usage.json"
        usage_file.parent.mkdir(parents=True, exist_ok=True)
        usage_file.write_text("not valid json", encoding="utf-8")
        results = storage.query()
        assert results == []
