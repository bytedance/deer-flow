"""Tests for user feedback — storage, router endpoints."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deerflow.config.tenant import set_current_tenant_id
from deerflow.feedback.storage import FeedbackEntry, FeedbackStorage


@pytest.fixture
def tmp_storage():
    """Create a FeedbackStorage pointed at a temp directory."""
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        yield FeedbackStorage(base_dir=base)


class TestFeedbackStorage:
    def test_add_and_query(self, tmp_storage):
        entry = FeedbackEntry(
            id="abc123",
            tenant_id="default",
            thread_id="thread-1",
            message_id="msg-1",
            rating=4,
            categories=["inaccurate"],
            comment="wrong info",
            created_at="2025-01-01T00:00:00",
        )
        tmp_storage.add(entry)

        results = tmp_storage.query()
        assert len(results) == 1
        assert results[0].rating == 4
        assert results[0].categories == ["inaccurate"]

    def test_query_by_thread(self, tmp_storage):
        e1 = FeedbackEntry(id="1", tenant_id="t", thread_id="th1", message_id="m1", rating=5, created_at="2025-01-01")
        e2 = FeedbackEntry(id="2", tenant_id="t", thread_id="th2", message_id="m2", rating=3, created_at="2025-01-02")
        tmp_storage.add(e1)
        tmp_storage.add(e2)

        results = tmp_storage.query(thread_id="th1")
        assert len(results) == 1
        assert results[0].id == "1"

    def test_query_by_date_range(self, tmp_storage):
        e1 = FeedbackEntry(id="1", tenant_id="t", thread_id="th", message_id="m1", rating=5, created_at="2025-01-01")
        e2 = FeedbackEntry(id="2", tenant_id="t", thread_id="th", message_id="m2", rating=3, created_at="2025-02-01")
        tmp_storage.add(e1)
        tmp_storage.add(e2)

        results = tmp_storage.query(start_date="2025-02-01")
        assert len(results) == 1
        assert results[0].id == "2"

    def test_get_summary(self, tmp_storage):
        for i in range(3):
            tmp_storage.add(
                FeedbackEntry(
                    id=str(i), tenant_id="t", thread_id="th", message_id=f"m{i}",
                    rating=5, categories=["accurate"], created_at="2025-01-01",
                )
            )
        for i in range(3, 5):
            tmp_storage.add(
                FeedbackEntry(
                    id=str(i), tenant_id="t", thread_id="th", message_id=f"m{i}",
                    rating=1, categories=["inaccurate", "incomplete"], created_at="2025-01-01",
                )
            )

        summary = tmp_storage.get_summary()
        assert summary["total_feedback"] == 5
        assert summary["avg_rating"] == pytest.approx((15 + 2) / 5)
        assert summary["rating_distribution"]["5"] == 3
        assert summary["rating_distribution"]["1"] == 2
        assert len(summary["top_categories"]) == 3

    def test_get_summary_empty(self, tmp_storage):
        summary = tmp_storage.get_summary()
        assert summary["total_feedback"] == 0
        assert summary["avg_rating"] == 0.0

    def test_entry_to_dict(self):
        entry = FeedbackEntry(
            id="x", tenant_id="t", thread_id="th", message_id="m",
            rating=3, categories=["c1"], comment="ok", created_at="2025-01-01",
        )
        d = entry.to_dict()
        assert d["id"] == "x"
        assert d["rating"] == 3
        assert d["categories"] == ["c1"]

    def test_entry_from_dict_minimal(self):
        d = {"id": "x", "tenant_id": "t", "thread_id": "th", "message_id": "m", "rating": 3}
        entry = FeedbackEntry.from_dict(d)
        assert entry.categories == []
        assert entry.comment == ""

    def test_cross_tenant_query(self, tmp_storage):
        # query_all_tenants scans {base_dir}/feedback.json and {base_dir}/tenants/*/feedback.json
        # We need to manually create the directory layout it expects
        base = tmp_storage._paths.base_dir
        tenant_a_dir = base / "tenants" / "a"
        tenant_b_dir = base / "tenants" / "b"
        tenant_a_dir.mkdir(parents=True)
        tenant_b_dir.mkdir(parents=True)

        storage_a = FeedbackStorage(base_dir=base)
        # Write directly to the per-tenant files
        import json, os
        def _write(path, entries):
            with open(path, "w", encoding="utf-8") as f:
                json.dump([e.to_dict() for e in entries], f)

        _write(tenant_a_dir / "feedback.json", [
            FeedbackEntry(id="1", tenant_id="a", thread_id="th", message_id="m", rating=5, created_at="2025-01-01"),
        ])
        _write(tenant_b_dir / "feedback.json", [
            FeedbackEntry(id="2", tenant_id="b", thread_id="th", message_id="m", rating=3, created_at="2025-01-02"),
        ])

        all_entries = FeedbackStorage.query_all_tenants(base_dir=base)
        assert len(all_entries) == 2

        filtered = FeedbackStorage.query_all_tenants(base_dir=base, tenant_id="a")
        assert len(filtered) == 1
        assert filtered[0].tenant_id == "a"


class TestFeedbackRouter:
    @pytest.fixture
    def client(self):
        from app.gateway.routers.feedback import router

        app = FastAPI()
        app.include_router(router)

        @app.get("/api/admin/tenants")
        def _admin():
            return {"tenants": []}

        return TestClient(app)

    def test_submit_feedback(self, client):
        with patch("app.gateway.routers.feedback.FeedbackStorage.add") as mock_add:
            resp = client.post(
                "/api/feedback",
                json={
                    "thread_id": "th1",
                    "message_id": "msg1",
                    "rating": 4,
                    "categories": ["inaccurate"],
                    "comment": "test",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "id" in data
        mock_add.assert_called_once()

    def test_submit_feedback_minimal(self, client):
        with patch("app.gateway.routers.feedback.FeedbackStorage.add"):
            resp = client.post(
                "/api/feedback",
                json={"thread_id": "th1", "message_id": "msg1", "rating": 3},
            )
        assert resp.status_code == 200

    def test_submit_feedback_invalid_rating(self, client):
        resp = client.post(
            "/api/feedback",
            json={"thread_id": "th1", "message_id": "msg1", "rating": 6},
        )
        assert resp.status_code == 422

    def test_get_summary_requires_admin(self, client):
        # Enable auth so require_admin actually enforces authentication
        from deerflow.config.auth_config import load_auth_config_from_dict
        load_auth_config_from_dict({"enabled": True, "jwt_secret": "test"})
        resp = client.get("/api/feedback/summary")
        assert resp.status_code == 401

    def test_get_summary_as_admin(self, client):
        with patch("app.gateway.routers.feedback.FeedbackStorage.get_cross_tenant_summary") as mock_summary:
            mock_summary.return_value = {
                "total_feedback": 10,
                "avg_rating": 4.2,
                "rating_distribution": {"5": 6, "4": 4},
                "top_categories": [{"category": "inaccurate", "count": 3}],
            }
            with patch("app.gateway.routers.feedback.require_admin", return_value={"username": "admin", "role": "admin"}):
                resp = client.get("/api/feedback/summary")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_feedback"] == 10
            assert data["avg_rating"] == 4.2
