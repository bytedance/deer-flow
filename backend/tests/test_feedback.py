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
        from app.gateway.routers.feedback import simple_feedback_router

        app = FastAPI()
        app.include_router(simple_feedback_router)

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

"""Tests for FeedbackRepository and follow-up association.

Uses temp SQLite DB for ORM tests.
"""

import pytest

from deerflow.persistence.feedback import FeedbackRepository


async def _make_feedback_repo(tmp_path):
    from deerflow.persistence.engine import get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return FeedbackRepository(get_session_factory())


async def _cleanup():
    from deerflow.persistence.engine import close_engine

    await close_engine()


# -- FeedbackRepository --


class TestFeedbackRepository:
    @pytest.mark.anyio
    async def test_create_positive(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        record = await repo.create(run_id="r1", thread_id="t1", rating=1)
        assert record["feedback_id"]
        assert record["rating"] == 1
        assert record["run_id"] == "r1"
        assert record["thread_id"] == "t1"
        assert "created_at" in record
        await _cleanup()

    @pytest.mark.anyio
    async def test_create_negative_with_comment(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        record = await repo.create(
            run_id="r1",
            thread_id="t1",
            rating=-1,
            comment="Response was inaccurate",
        )
        assert record["rating"] == -1
        assert record["comment"] == "Response was inaccurate"
        await _cleanup()

    @pytest.mark.anyio
    async def test_create_with_message_id(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        record = await repo.create(run_id="r1", thread_id="t1", rating=1, message_id="msg-42")
        assert record["message_id"] == "msg-42"
        await _cleanup()

    @pytest.mark.anyio
    async def test_create_with_owner(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        record = await repo.create(run_id="r1", thread_id="t1", rating=1, user_id="user-1")
        assert record["user_id"] == "user-1"
        await _cleanup()

    @pytest.mark.anyio
    async def test_create_invalid_rating_zero(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        with pytest.raises(ValueError):
            await repo.create(run_id="r1", thread_id="t1", rating=0)
        await _cleanup()

    @pytest.mark.anyio
    async def test_create_invalid_rating_five(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        with pytest.raises(ValueError):
            await repo.create(run_id="r1", thread_id="t1", rating=5)
        await _cleanup()

    @pytest.mark.anyio
    async def test_get(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        created = await repo.create(run_id="r1", thread_id="t1", rating=1)
        fetched = await repo.get(created["feedback_id"])
        assert fetched is not None
        assert fetched["feedback_id"] == created["feedback_id"]
        assert fetched["rating"] == 1
        await _cleanup()

    @pytest.mark.anyio
    async def test_get_nonexistent(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        assert await repo.get("nonexistent") is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_run(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        await repo.create(run_id="r1", thread_id="t1", rating=1, user_id="user-1")
        await repo.create(run_id="r1", thread_id="t1", rating=-1, user_id="user-2")
        await repo.create(run_id="r2", thread_id="t1", rating=1, user_id="user-1")
        results = await repo.list_by_run("t1", "r1", user_id=None)
        assert len(results) == 2
        assert all(r["run_id"] == "r1" for r in results)
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_thread(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        await repo.create(run_id="r1", thread_id="t1", rating=1)
        await repo.create(run_id="r2", thread_id="t1", rating=-1)
        await repo.create(run_id="r3", thread_id="t2", rating=1)
        results = await repo.list_by_thread("t1")
        assert len(results) == 2
        assert all(r["thread_id"] == "t1" for r in results)
        await _cleanup()

    @pytest.mark.anyio
    async def test_delete(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        created = await repo.create(run_id="r1", thread_id="t1", rating=1)
        deleted = await repo.delete(created["feedback_id"])
        assert deleted is True
        assert await repo.get(created["feedback_id"]) is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_delete_nonexistent(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        deleted = await repo.delete("nonexistent")
        assert deleted is False
        await _cleanup()

    @pytest.mark.anyio
    async def test_aggregate_by_run(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        await repo.create(run_id="r1", thread_id="t1", rating=1, user_id="user-1")
        await repo.create(run_id="r1", thread_id="t1", rating=1, user_id="user-2")
        await repo.create(run_id="r1", thread_id="t1", rating=-1, user_id="user-3")
        stats = await repo.aggregate_by_run("t1", "r1")
        assert stats["total"] == 3
        assert stats["positive"] == 2
        assert stats["negative"] == 1
        assert stats["run_id"] == "r1"
        await _cleanup()

    @pytest.mark.anyio
    async def test_aggregate_empty(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        stats = await repo.aggregate_by_run("t1", "r1")
        assert stats["total"] == 0
        assert stats["positive"] == 0
        assert stats["negative"] == 0
        await _cleanup()

    @pytest.mark.anyio
    async def test_upsert_creates_new(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        record = await repo.upsert(run_id="r1", thread_id="t1", rating=1, user_id="u1")
        assert record["rating"] == 1
        assert record["feedback_id"]
        assert record["user_id"] == "u1"
        await _cleanup()

    @pytest.mark.anyio
    async def test_upsert_updates_existing(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        first = await repo.upsert(run_id="r1", thread_id="t1", rating=1, user_id="u1")
        second = await repo.upsert(run_id="r1", thread_id="t1", rating=-1, user_id="u1", comment="changed my mind")
        assert second["feedback_id"] == first["feedback_id"]
        assert second["rating"] == -1
        assert second["comment"] == "changed my mind"
        await _cleanup()

    @pytest.mark.anyio
    async def test_upsert_different_users_separate(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        r1 = await repo.upsert(run_id="r1", thread_id="t1", rating=1, user_id="u1")
        r2 = await repo.upsert(run_id="r1", thread_id="t1", rating=-1, user_id="u2")
        assert r1["feedback_id"] != r2["feedback_id"]
        assert r1["rating"] == 1
        assert r2["rating"] == -1
        await _cleanup()

    @pytest.mark.anyio
    async def test_upsert_invalid_rating(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        with pytest.raises(ValueError):
            await repo.upsert(run_id="r1", thread_id="t1", rating=0, user_id="u1")
        await _cleanup()

    @pytest.mark.anyio
    async def test_delete_by_run(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        await repo.upsert(run_id="r1", thread_id="t1", rating=1, user_id="u1")
        deleted = await repo.delete_by_run(thread_id="t1", run_id="r1", user_id="u1")
        assert deleted is True
        results = await repo.list_by_run("t1", "r1", user_id="u1")
        assert len(results) == 0
        await _cleanup()

    @pytest.mark.anyio
    async def test_delete_by_run_nonexistent(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        deleted = await repo.delete_by_run(thread_id="t1", run_id="r1", user_id="u1")
        assert deleted is False
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_thread_grouped(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        await repo.upsert(run_id="r1", thread_id="t1", rating=1, user_id="u1")
        await repo.upsert(run_id="r2", thread_id="t1", rating=-1, user_id="u1")
        await repo.upsert(run_id="r3", thread_id="t2", rating=1, user_id="u1")
        grouped = await repo.list_by_thread_grouped("t1", user_id="u1")
        assert "r1" in grouped
        assert "r2" in grouped
        assert "r3" not in grouped
        assert grouped["r1"]["rating"] == 1
        assert grouped["r2"]["rating"] == -1
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_thread_grouped_empty(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        grouped = await repo.list_by_thread_grouped("t1", user_id="u1")
        assert grouped == {}
        await _cleanup()


# -- Follow-up association --


class TestFollowUpAssociation:
    @pytest.mark.anyio
    async def test_run_records_follow_up_via_memory_store(self):
        """MemoryRunStore stores follow_up_to_run_id in kwargs."""
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        store = MemoryRunStore()
        await store.put("r1", thread_id="t1", status="success")
        # MemoryRunStore doesn't have follow_up_to_run_id as a top-level param,
        # but it can be passed via metadata
        await store.put("r2", thread_id="t1", metadata={"follow_up_to_run_id": "r1"})
        run = await store.get("r2")
        assert run["metadata"]["follow_up_to_run_id"] == "r1"

    @pytest.mark.anyio
    async def test_human_message_has_follow_up_metadata(self):
        """human_message event metadata includes follow_up_to_run_id."""
        from deerflow.runtime.events.store.memory import MemoryRunEventStore

        event_store = MemoryRunEventStore()
        await event_store.put(
            thread_id="t1",
            run_id="r2",
            event_type="human_message",
            category="message",
            content="Tell me more about that",
            metadata={"follow_up_to_run_id": "r1"},
        )
        messages = await event_store.list_messages("t1")
        assert messages[0]["metadata"]["follow_up_to_run_id"] == "r1"

    @pytest.mark.anyio
    async def test_follow_up_auto_detection_logic(self):
        """Simulate the auto-detection: latest successful run becomes follow_up_to."""
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        store = MemoryRunStore()
        await store.put("r1", thread_id="t1", status="success")
        await store.put("r2", thread_id="t1", status="error")

        # Auto-detect: list_by_thread returns newest first
        recent = await store.list_by_thread("t1", limit=1)
        follow_up = None
        if recent and recent[0].get("status") == "success":
            follow_up = recent[0]["run_id"]
        # r2 (error) is newest, so no follow_up detected
        assert follow_up is None

        # Now add a successful run
        await store.put("r3", thread_id="t1", status="success")
        recent = await store.list_by_thread("t1", limit=1)
        follow_up = None
        if recent and recent[0].get("status") == "success":
            follow_up = recent[0]["run_id"]
        assert follow_up == "r3"
