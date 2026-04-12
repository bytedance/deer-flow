"""Tests for ThreadMetaRepository (SQLAlchemy-backed)."""

import pytest

from deerflow.persistence.thread_meta import ThreadMetaRepository


async def _make_repo(tmp_path):
    from deerflow.persistence.engine import get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return ThreadMetaRepository(get_session_factory())


async def _cleanup():
    from deerflow.persistence.engine import close_engine

    await close_engine()


class TestThreadMetaRepository:
    @pytest.mark.anyio
    async def test_create_and_get(self, tmp_path):
        repo = await _make_repo(tmp_path)
        record = await repo.create("t1")
        assert record["thread_id"] == "t1"
        assert record["status"] == "idle"
        assert "created_at" in record

        fetched = await repo.get("t1")
        assert fetched is not None
        assert fetched["thread_id"] == "t1"
        await _cleanup()

    @pytest.mark.anyio
    async def test_create_with_assistant_id(self, tmp_path):
        repo = await _make_repo(tmp_path)
        record = await repo.create("t1", assistant_id="agent1")
        assert record["assistant_id"] == "agent1"
        await _cleanup()

    @pytest.mark.anyio
    async def test_create_with_owner_and_display_name(self, tmp_path):
        repo = await _make_repo(tmp_path)
        record = await repo.create("t1", user_id="user1", display_name="My Thread")
        assert record["user_id"] == "user1"
        assert record["display_name"] == "My Thread"
        await _cleanup()

    @pytest.mark.anyio
    async def test_create_with_metadata(self, tmp_path):
        repo = await _make_repo(tmp_path)
        record = await repo.create("t1", metadata={"key": "value"})
        assert record["metadata"] == {"key": "value"}
        await _cleanup()

    @pytest.mark.anyio
    async def test_get_nonexistent(self, tmp_path):
        repo = await _make_repo(tmp_path)
        assert await repo.get("nonexistent") is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_check_access_no_record_allows(self, tmp_path):
        repo = await _make_repo(tmp_path)
        assert await repo.check_access("unknown", "user1") is True
        await _cleanup()

    @pytest.mark.anyio
    async def test_check_access_owner_matches(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1", user_id="user1")
        assert await repo.check_access("t1", "user1") is True
        await _cleanup()

    @pytest.mark.anyio
    async def test_check_access_owner_mismatch(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1", user_id="user1")
        assert await repo.check_access("t1", "user2") is False
        await _cleanup()

    @pytest.mark.anyio
    async def test_check_access_no_owner_allows_all(self, tmp_path):
        repo = await _make_repo(tmp_path)
        # Explicit user_id=None to bypass the new AUTO default that
        # would otherwise pick up the test user from the autouse fixture.
        await repo.create("t1", user_id=None)
        assert await repo.check_access("t1", "anyone") is True
        await _cleanup()

    @pytest.mark.anyio
    async def test_check_access_strict_missing_row_denied(self, tmp_path):
        """require_existing=True flips the missing-row case to *denied*.

        Closes the delete-idempotence cross-user gap: after a thread is
        deleted, the row is gone, and the permissive default would let any
        caller "claim" it as untracked. The strict mode demands a row.
        """
        repo = await _make_repo(tmp_path)
        assert await repo.check_access("never-existed", "user1", require_existing=True) is False
        await _cleanup()

    @pytest.mark.anyio
    async def test_check_access_strict_owner_match_allowed(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1", user_id="user1")
        assert await repo.check_access("t1", "user1", require_existing=True) is True
        await _cleanup()

    @pytest.mark.anyio
    async def test_check_access_strict_owner_mismatch_denied(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1", user_id="user1")
        assert await repo.check_access("t1", "user2", require_existing=True) is False
        await _cleanup()

    @pytest.mark.anyio
    async def test_check_access_strict_null_owner_still_allowed(self, tmp_path):
        """Even in strict mode, a row with NULL user_id stays shared.

        The strict flag tightens the *missing row* case, not the *shared
        row* case — legacy pre-auth rows that survived a clean migration
        without an owner are still everyone's.
        """
        repo = await _make_repo(tmp_path)
        await repo.create("t1", user_id=None)
        assert await repo.check_access("t1", "anyone", require_existing=True) is True
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_status(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1")
        await repo.update_status("t1", "busy")
        record = await repo.get("t1")
        assert record["status"] == "busy"
        await _cleanup()

    @pytest.mark.anyio
    async def test_delete(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1")
        await repo.delete("t1")
        assert await repo.get("t1") is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_delete_nonexistent_is_noop(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.delete("nonexistent")  # should not raise
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_metadata_merges(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1", metadata={"a": 1, "b": 2})
        await repo.update_metadata("t1", {"b": 99, "c": 3})
        record = await repo.get("t1")
        # Existing key preserved, overlapping key overwritten, new key added
        assert record["metadata"] == {"a": 1, "b": 99, "c": 3}
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_metadata_on_empty(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1")
        await repo.update_metadata("t1", {"k": "v"})
        record = await repo.get("t1")
        assert record["metadata"] == {"k": "v"}
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_metadata_nonexistent_is_noop(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.update_metadata("nonexistent", {"k": "v"})  # should not raise
        await _cleanup()
