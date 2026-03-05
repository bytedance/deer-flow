"""Tests for S3 artifact storage: S3ArtifactStore, artifact tasks, middleware,
router fallback, thread deletion, eviction, and debounce logic."""

import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_s3_store(mock_s3_client, bucket="test-bucket", prefix="prod/", region="us-west-2"):
    """Create an S3ArtifactStore with a mocked boto3 client."""
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_s3_client
    with patch.dict(sys.modules, {"boto3": mock_boto3}):
        from src.storage.s3_artifact_store import S3ArtifactStore

        store = S3ArtifactStore(bucket=bucket, prefix=prefix, region=region)
    store._client = mock_s3_client
    return store


def _make_mock_s3_client():
    """Create a mock S3 client with NoSuchKey exception."""
    client = MagicMock()
    client.exceptions.NoSuchKey = type("NoSuchKey", (Exception,), {})
    return client


# ══════════════════════════════════════════════════════════════════════════
# S3ArtifactStore unit tests
# ══════════════════════════════════════════════════════════════════════════


class TestS3ArtifactStore:
    """Core S3ArtifactStore methods with a mocked boto3 client."""

    @pytest.fixture()
    def mock_s3_client(self):
        return _make_mock_s3_client()

    @pytest.fixture()
    def store(self, mock_s3_client):
        return _make_s3_store(mock_s3_client)

    # ── Key format ─────────────────────────────────────────────────────

    def test_s3_key_format(self, store):
        key = store._s3_key("user1", "thread1", "outputs/report.pdf")
        assert key == "prod/users/user1/threads/thread1/outputs/report.pdf"

    def test_s3_key_no_prefix(self, mock_s3_client):
        store = _make_s3_store(mock_s3_client, prefix="")
        key = store._s3_key("u", "t", "file.txt")
        assert key == "users/u/threads/t/file.txt"

    def test_s3_key_prefix_trailing_slash_normalized(self, mock_s3_client):
        store = _make_s3_store(mock_s3_client, prefix="staging/")
        key = store._s3_key("u", "t", "f.txt")
        assert key == "staging/users/u/threads/t/f.txt"
        # No double slash
        assert "//" not in key

    # ── Upload ─────────────────────────────────────────────────────────

    def test_upload_file(self, store, mock_s3_client, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        store.upload_file("u1", "t1", "outputs/test.txt", f)
        mock_s3_client.upload_file.assert_called_once_with(
            str(f), "test-bucket", "prod/users/u1/threads/t1/outputs/test.txt"
        )

    # ── Download ───────────────────────────────────────────────────────

    def test_download_file_success(self, store, mock_s3_client, tmp_path):
        dest = tmp_path / "sub" / "file.txt"
        result = store.download_file("u1", "t1", "outputs/file.txt", dest)
        assert result is True
        assert dest.parent.exists()
        mock_s3_client.download_file.assert_called_once()

    def test_download_file_creates_parent_dirs(self, store, mock_s3_client, tmp_path):
        dest = tmp_path / "a" / "b" / "c" / "file.txt"
        store.download_file("u1", "t1", "deep/file.txt", dest)
        assert dest.parent.exists()

    def test_download_file_not_found_no_such_key(self, store, mock_s3_client, tmp_path):
        mock_s3_client.download_file.side_effect = mock_s3_client.exceptions.NoSuchKey()
        result = store.download_file("u1", "t1", "missing.txt", tmp_path / "m.txt")
        assert result is False

    def test_download_file_not_found_404_error(self, store, mock_s3_client, tmp_path):
        error = Exception("not found")
        error.response = {"Error": {"Code": "404"}}
        mock_s3_client.download_file.side_effect = error
        result = store.download_file("u1", "t1", "missing.txt", tmp_path / "x.txt")
        assert result is False

    def test_download_file_unexpected_error(self, store, mock_s3_client, tmp_path):
        error = Exception("network error")
        error.response = {"Error": {"Code": "500"}}
        mock_s3_client.download_file.side_effect = error
        result = store.download_file("u1", "t1", "err.txt", tmp_path / "e.txt")
        assert result is False

    # ── Sync ───────────────────────────────────────────────────────────

    def test_sync_thread(self, store, mock_s3_client, tmp_path):
        user_data = tmp_path / "user-data"
        (user_data / "outputs").mkdir(parents=True)
        (user_data / "outputs" / "a.txt").write_text("a")
        (user_data / "outputs" / "b.txt").write_text("b")
        (user_data / "workspace").mkdir()
        (user_data / "workspace" / "c.txt").write_text("c")
        count = store.sync_thread("u1", "t1", user_data)
        assert count == 3
        assert mock_s3_client.upload_file.call_count == 3

    def test_sync_thread_missing_dir(self, store):
        count = store.sync_thread("u1", "t1", Path("/nonexistent"))
        assert count == 0

    def test_sync_thread_empty_dir(self, store, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        count = store.sync_thread("u1", "t1", empty)
        assert count == 0

    def test_sync_thread_skips_subdirs(self, store, mock_s3_client, tmp_path):
        """Only files are uploaded, not directory entries."""
        d = tmp_path / "data"
        d.mkdir()
        (d / "subdir").mkdir()
        (d / "file.txt").write_text("x")
        count = store.sync_thread("u1", "t1", d)
        assert count == 1

    # ── file_exists ────────────────────────────────────────────────────

    def test_file_exists_true(self, store, mock_s3_client):
        assert store.file_exists("u1", "t1", "file.txt") is True
        mock_s3_client.head_object.assert_called_once()

    def test_file_exists_false(self, store, mock_s3_client):
        mock_s3_client.head_object.side_effect = Exception("not found")
        assert store.file_exists("u1", "t1", "file.txt") is False

    # ── is_synced ──────────────────────────────────────────────────────

    def test_is_synced_true(self, store, mock_s3_client, tmp_path):
        d = tmp_path / "data"
        (d / "outputs").mkdir(parents=True)
        (d / "outputs" / "a.txt").write_text("a")
        assert store.is_synced("u1", "t1", d) is True

    def test_is_synced_false(self, store, mock_s3_client, tmp_path):
        mock_s3_client.head_object.side_effect = Exception("missing")
        d = tmp_path / "data"
        (d / "outputs").mkdir(parents=True)
        (d / "outputs" / "a.txt").write_text("a")
        assert store.is_synced("u1", "t1", d) is False

    def test_is_synced_empty_dir(self, store, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        assert store.is_synced("u1", "t1", d) is True

    def test_is_synced_nonexistent_dir(self, store):
        assert store.is_synced("u1", "t1", Path("/gone")) is True

    # ── Delete ─────────────────────────────────────────────────────────

    def test_delete_thread(self, store, mock_s3_client):
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"Contents": [{"Key": "k1"}, {"Key": "k2"}]},
            {"Contents": [{"Key": "k3"}]},
        ]
        mock_s3_client.get_paginator.return_value = paginator
        deleted = store.delete_thread("u1", "t1")
        assert deleted == 3
        assert mock_s3_client.delete_objects.call_count == 2

    def test_delete_thread_empty(self, store, mock_s3_client):
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Contents": []}]
        mock_s3_client.get_paginator.return_value = paginator
        deleted = store.delete_thread("u1", "t1")
        assert deleted == 0

    def test_delete_user(self, store, mock_s3_client):
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"Contents": [{"Key": "k1"}, {"Key": "k2"}, {"Key": "k3"}]},
        ]
        mock_s3_client.get_paginator.return_value = paginator
        deleted = store.delete_user("u1")
        assert deleted == 3
        # Verify the prefix used for user-level deletion
        paginator.paginate.assert_called_once_with(
            Bucket="test-bucket", Prefix="prod/users/u1/"
        )


# ══════════════════════════════════════════════════════════════════════════
# Singleton tests
# ══════════════════════════════════════════════════════════════════════════


class TestSingleton:
    def setup_method(self):
        """Reset singleton state before each test."""
        import src.storage.s3_artifact_store as mod

        mod._checked = False
        mod._store = None

    def test_is_s3_enabled_false_when_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("S3_ARTIFACTS_BUCKET", None)
            import src.storage.s3_artifact_store as mod

            assert mod.is_s3_enabled() is False
            assert mod.get_s3_artifact_store() is None

    def test_is_s3_enabled_true_when_set(self):
        import src.storage.s3_artifact_store as mod

        with patch.dict(os.environ, {"S3_ARTIFACTS_BUCKET": "my-bucket"}):
            assert mod.is_s3_enabled() is True
            with patch.dict(sys.modules, {"boto3": MagicMock()}):
                store = mod.get_s3_artifact_store()
                assert store is not None
                assert store.bucket == "my-bucket"

    def test_singleton_returns_same_instance(self):
        import src.storage.s3_artifact_store as mod

        with patch.dict(os.environ, {"S3_ARTIFACTS_BUCKET": "b"}):
            with patch.dict(sys.modules, {"boto3": MagicMock()}):
                s1 = mod.get_s3_artifact_store()
                s2 = mod.get_s3_artifact_store()
                assert s1 is s2

    def test_region_falls_back_to_aws_default(self):
        import src.storage.s3_artifact_store as mod

        with patch.dict(os.environ, {
            "S3_ARTIFACTS_BUCKET": "b",
            "AWS_DEFAULT_REGION": "ap-southeast-1",
        }):
            os.environ.pop("S3_ARTIFACTS_REGION", None)
            mock_boto3 = MagicMock()
            with patch.dict(sys.modules, {"boto3": mock_boto3}):
                mod.get_s3_artifact_store()
                mock_boto3.client.assert_called_once_with("s3", region_name="ap-southeast-1")


# ══════════════════════════════════════════════════════════════════════════
# Artifact tasks tests
# ══════════════════════════════════════════════════════════════════════════


class TestArtifactTasks:
    def test_sync_thread_to_s3_disabled(self):
        with patch("src.storage.s3_artifact_store.get_s3_artifact_store", return_value=None):
            from src.queue.artifact_tasks import sync_thread_to_s3

            assert sync_thread_to_s3("u1", "t1") is False

    def test_sync_thread_to_s3_success(self, tmp_path):
        mock_store = MagicMock()
        mock_store.sync_thread.return_value = 5

        mock_session = MagicMock()
        mock_thread = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = mock_thread

        with (
            patch("src.storage.s3_artifact_store.get_s3_artifact_store", return_value=mock_store),
            patch("src.config.paths.get_paths") as mock_paths,
            patch("src.db.engine.get_db_session", return_value=mock_session),
        ):
            mock_paths.return_value.sandbox_user_data_dir.return_value = tmp_path
            from src.queue.artifact_tasks import sync_thread_to_s3

            result = sync_thread_to_s3("u1", "t1")
            assert result is True
            mock_store.sync_thread.assert_called_once_with("u1", "t1", tmp_path)
            assert mock_thread.s3_sync_status == "synced"

    def test_sync_thread_to_s3_upload_failure(self, tmp_path):
        mock_store = MagicMock()
        mock_store.sync_thread.side_effect = Exception("S3 error")

        with (
            patch("src.storage.s3_artifact_store.get_s3_artifact_store", return_value=mock_store),
            patch("src.config.paths.get_paths") as mock_paths,
        ):
            mock_paths.return_value.sandbox_user_data_dir.return_value = tmp_path
            from src.queue.artifact_tasks import sync_thread_to_s3

            result = sync_thread_to_s3("u1", "t1")
            assert result is False

    def test_sync_thread_to_s3_db_failure_still_returns_true(self, tmp_path):
        """If upload succeeds but DB update fails, sync still returns True."""
        mock_store = MagicMock()
        mock_store.sync_thread.return_value = 2

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(side_effect=Exception("DB error"))
        mock_session.__exit__ = MagicMock(return_value=False)

        with (
            patch("src.storage.s3_artifact_store.get_s3_artifact_store", return_value=mock_store),
            patch("src.config.paths.get_paths") as mock_paths,
            patch("src.db.engine.get_db_session", return_value=mock_session),
        ):
            mock_paths.return_value.sandbox_user_data_dir.return_value = tmp_path
            from src.queue.artifact_tasks import sync_thread_to_s3

            result = sync_thread_to_s3("u1", "t1")
            assert result is True

    def test_delete_thread_from_s3_success(self):
        mock_store = MagicMock()
        mock_store.delete_thread.return_value = 3
        with patch("src.storage.s3_artifact_store.get_s3_artifact_store", return_value=mock_store):
            from src.queue.artifact_tasks import delete_thread_from_s3

            assert delete_thread_from_s3("u1", "t1") is True
            mock_store.delete_thread.assert_called_once_with("u1", "t1")

    def test_delete_thread_from_s3_disabled(self):
        with patch("src.storage.s3_artifact_store.get_s3_artifact_store", return_value=None):
            from src.queue.artifact_tasks import delete_thread_from_s3

            assert delete_thread_from_s3("u1", "t1") is False

    def test_delete_thread_from_s3_error(self):
        mock_store = MagicMock()
        mock_store.delete_thread.side_effect = Exception("boom")
        with patch("src.storage.s3_artifact_store.get_s3_artifact_store", return_value=mock_store):
            from src.queue.artifact_tasks import delete_thread_from_s3

            assert delete_thread_from_s3("u1", "t1") is False

    def test_delete_user_from_s3_success(self):
        mock_store = MagicMock()
        mock_store.delete_user.return_value = 10
        with patch("src.storage.s3_artifact_store.get_s3_artifact_store", return_value=mock_store):
            from src.queue.artifact_tasks import delete_user_from_s3

            assert delete_user_from_s3("u1") is True

    def test_delete_user_from_s3_error(self):
        mock_store = MagicMock()
        mock_store.delete_user.side_effect = Exception("boom")
        with patch("src.storage.s3_artifact_store.get_s3_artifact_store", return_value=mock_store):
            from src.queue.artifact_tasks import delete_user_from_s3

            assert delete_user_from_s3("u1") is False


# ══════════════════════════════════════════════════════════════════════════
# Eviction tests
# ══════════════════════════════════════════════════════════════════════════


class TestEviction:
    def test_eviction_disabled_when_s3_unconfigured(self):
        with patch("src.storage.s3_artifact_store.get_s3_artifact_store", return_value=None):
            from src.queue.artifact_tasks import evict_stale_threads

            result = evict_stale_threads(7)
            assert result == {"evicted": 0, "skipped": 0, "errors": 0}

    def test_eviction_evicts_synced_stale_thread(self, tmp_path, db_session):
        """A thread that is synced + stale + has local data should be evicted."""
        from src.db.models import ThreadModel

        stale_time = datetime.now(UTC) - timedelta(days=10)
        thread = ThreadModel(
            thread_id="stale-1",
            user_id="user-1",
            s3_sync_status="synced",
            last_accessed_at=stale_time,
            local_evicted=False,
        )
        db_session.add(thread)
        db_session.flush()

        # Create fake local thread directory
        thread_dir = tmp_path / "threads" / "stale-1"
        user_data = thread_dir / "user-data" / "outputs"
        user_data.mkdir(parents=True)
        (user_data / "file.txt").write_text("data")

        mock_store = MagicMock()
        mock_store.is_synced.return_value = True

        mock_paths = MagicMock()
        mock_paths.thread_dir.return_value = thread_dir
        mock_paths.sandbox_user_data_dir.return_value = thread_dir / "user-data"

        with (
            patch("src.storage.s3_artifact_store.get_s3_artifact_store", return_value=mock_store),
            patch("src.config.paths.get_paths", return_value=mock_paths),
            patch("src.db.engine.get_db_session") as mock_get_session,
        ):
            mock_get_session.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

            from src.queue.artifact_tasks import evict_stale_threads

            result = evict_stale_threads(7)

        assert result["evicted"] == 1
        assert result["skipped"] == 0
        assert result["errors"] == 0
        assert not thread_dir.exists()  # directory removed
        assert thread.local_evicted is True

    def test_eviction_skips_not_synced_thread(self, tmp_path, db_session):
        """A thread that isn't verified as synced should be skipped."""
        from src.db.models import ThreadModel

        stale_time = datetime.now(UTC) - timedelta(days=10)
        thread = ThreadModel(
            thread_id="not-synced-1",
            user_id="user-1",
            s3_sync_status="synced",
            last_accessed_at=stale_time,
            local_evicted=False,
        )
        db_session.add(thread)
        db_session.flush()

        thread_dir = tmp_path / "threads" / "not-synced-1"
        user_data = thread_dir / "user-data" / "outputs"
        user_data.mkdir(parents=True)
        (user_data / "file.txt").write_text("data")

        mock_store = MagicMock()
        mock_store.is_synced.return_value = False  # NOT synced

        mock_paths = MagicMock()
        mock_paths.thread_dir.return_value = thread_dir
        mock_paths.sandbox_user_data_dir.return_value = thread_dir / "user-data"

        with (
            patch("src.storage.s3_artifact_store.get_s3_artifact_store", return_value=mock_store),
            patch("src.config.paths.get_paths", return_value=mock_paths),
            patch("src.db.engine.get_db_session") as mock_get_session,
        ):
            mock_get_session.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

            from src.queue.artifact_tasks import evict_stale_threads

            result = evict_stale_threads(7)

        assert result["skipped"] == 1
        assert result["evicted"] == 0
        assert thread_dir.exists()  # NOT removed

    def test_eviction_skips_already_evicted(self, db_session):
        """Already-evicted threads should not be queried."""
        from src.db.models import ThreadModel

        thread = ThreadModel(
            thread_id="already-evicted",
            user_id="user-1",
            s3_sync_status="synced",
            last_accessed_at=datetime.now(UTC) - timedelta(days=30),
            local_evicted=True,
        )
        db_session.add(thread)
        db_session.flush()

        mock_store = MagicMock()
        mock_paths = MagicMock()

        with (
            patch("src.storage.s3_artifact_store.get_s3_artifact_store", return_value=mock_store),
            patch("src.config.paths.get_paths", return_value=mock_paths),
            patch("src.db.engine.get_db_session") as mock_get_session,
        ):
            mock_get_session.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

            from src.queue.artifact_tasks import evict_stale_threads

            result = evict_stale_threads(7)

        assert result == {"evicted": 0, "skipped": 0, "errors": 0}
        mock_store.is_synced.assert_not_called()

    def test_eviction_skips_missing_local_dir(self, db_session):
        """Thread whose local dir is already gone is marked evicted, counted as skipped."""
        from src.db.models import ThreadModel

        thread = ThreadModel(
            thread_id="gone-locally",
            user_id="user-1",
            s3_sync_status="synced",
            last_accessed_at=datetime.now(UTC) - timedelta(days=10),
            local_evicted=False,
        )
        db_session.add(thread)
        db_session.flush()

        mock_store = MagicMock()
        mock_paths = MagicMock()
        mock_paths.thread_dir.return_value = Path("/nonexistent/thread-dir")
        mock_paths.sandbox_user_data_dir.return_value = Path("/nonexistent/user-data")

        with (
            patch("src.storage.s3_artifact_store.get_s3_artifact_store", return_value=mock_store),
            patch("src.config.paths.get_paths", return_value=mock_paths),
            patch("src.db.engine.get_db_session") as mock_get_session,
        ):
            mock_get_session.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

            from src.queue.artifact_tasks import evict_stale_threads

            result = evict_stale_threads(7)

        assert result["skipped"] == 1
        assert thread.local_evicted is True


# ══════════════════════════════════════════════════════════════════════════
# Middleware tests
# ══════════════════════════════════════════════════════════════════════════


class TestArtifactSyncMiddleware:
    def test_skips_when_s3_disabled(self):
        from src.agents.middlewares.artifact_sync_middleware import ArtifactSyncMiddleware

        mw = ArtifactSyncMiddleware()
        runtime = MagicMock()
        state = {}

        with patch("src.agents.middlewares.artifact_sync_middleware.is_s3_enabled", return_value=False):
            result = mw.after_agent(state, runtime)
        assert result is None

    def test_skips_when_no_thread_id(self):
        from src.agents.middlewares.artifact_sync_middleware import ArtifactSyncMiddleware

        mw = ArtifactSyncMiddleware()
        runtime = MagicMock()
        runtime.context.get.return_value = None
        state = {}

        with patch("src.agents.middlewares.artifact_sync_middleware.is_s3_enabled", return_value=True):
            result = mw.after_agent(state, runtime)
        assert result is None

    def test_enqueues_when_enabled(self):
        from src.agents.middlewares.artifact_sync_middleware import ArtifactSyncMiddleware

        mw = ArtifactSyncMiddleware()
        runtime = MagicMock()
        runtime.context.get.side_effect = lambda k, *d: {"thread_id": "t1", "user_id": "u1"}.get(k, d[0] if d else None)
        state = {}

        mock_queue = MagicMock()
        with (
            patch("src.agents.middlewares.artifact_sync_middleware.is_s3_enabled", return_value=True),
            patch("src.queue.redis_connection.is_redis_available", return_value=True),
            patch("src.queue.redis_connection.get_redis_client", return_value=MagicMock()),
            patch("rq.Queue", return_value=mock_queue),
        ):
            result = mw.after_agent(state, runtime)
        assert result is None
        mock_queue.enqueue.assert_called_once()
        # Verify correct task function and args
        call_args = mock_queue.enqueue.call_args
        assert call_args[0][0] == "src.queue.artifact_tasks.sync_thread_to_s3"
        assert call_args[1]["user_id"] == "u1"
        assert call_args[1]["thread_id"] == "t1"

    def test_uses_default_user_id_when_missing(self):
        from src.agents.middlewares.artifact_sync_middleware import ArtifactSyncMiddleware

        mw = ArtifactSyncMiddleware()
        runtime = MagicMock()
        runtime.context.get.side_effect = lambda k, *d: {"thread_id": "t1"}.get(k, d[0] if d else None)
        state = {}

        mock_queue = MagicMock()
        with (
            patch("src.agents.middlewares.artifact_sync_middleware.is_s3_enabled", return_value=True),
            patch("src.queue.redis_connection.is_redis_available", return_value=True),
            patch("src.queue.redis_connection.get_redis_client", return_value=MagicMock()),
            patch("rq.Queue", return_value=mock_queue),
        ):
            mw.after_agent(state, runtime)
        assert mock_queue.enqueue.call_args[1]["user_id"] == "local"

    def test_graceful_when_redis_unavailable(self):
        from src.agents.middlewares.artifact_sync_middleware import ArtifactSyncMiddleware

        mw = ArtifactSyncMiddleware()
        runtime = MagicMock()
        runtime.context.get.side_effect = lambda k, *d: {"thread_id": "t1", "user_id": "u1"}.get(k, d[0] if d else None)
        state = {}

        with (
            patch("src.agents.middlewares.artifact_sync_middleware.is_s3_enabled", return_value=True),
            patch("src.queue.redis_connection.is_redis_available", return_value=False),
        ):
            # Should not raise
            result = mw.after_agent(state, runtime)
        assert result is None


# ══════════════════════════════════════════════════════════════════════════
# Artifact router helpers tests
# ══════════════════════════════════════════════════════════════════════════


class TestArtifactRouterHelpers:
    """Test _try_s3_download path stripping and _update_last_accessed debounce."""

    @pytest.mark.asyncio
    async def test_try_s3_download_strips_virtual_prefix(self):
        from src.gateway.routers.artifacts import _try_s3_download

        mock_store = MagicMock()
        mock_store.download_file.return_value = True

        with (
            patch("src.storage.s3_artifact_store.is_s3_enabled", return_value=True),
            patch("src.storage.s3_artifact_store.get_s3_artifact_store", return_value=mock_store),
        ):
            result = await _try_s3_download("t1", "u1", "mnt/user-data/outputs/report.pdf", Path("/tmp/out.pdf"))

        assert result is True
        mock_store.download_file.assert_called_once_with("u1", "t1", "outputs/report.pdf", Path("/tmp/out.pdf"))

    @pytest.mark.asyncio
    async def test_try_s3_download_handles_leading_slash(self):
        from src.gateway.routers.artifacts import _try_s3_download

        mock_store = MagicMock()
        mock_store.download_file.return_value = True

        with (
            patch("src.storage.s3_artifact_store.is_s3_enabled", return_value=True),
            patch("src.storage.s3_artifact_store.get_s3_artifact_store", return_value=mock_store),
        ):
            await _try_s3_download("t1", "u1", "/mnt/user-data/workspace/main.py", Path("/tmp/x.py"))

        mock_store.download_file.assert_called_once_with("u1", "t1", "workspace/main.py", Path("/tmp/x.py"))

    @pytest.mark.asyncio
    async def test_try_s3_download_returns_false_when_disabled(self):
        from src.gateway.routers.artifacts import _try_s3_download

        with patch("src.storage.s3_artifact_store.is_s3_enabled", return_value=False):
            result = await _try_s3_download("t1", "u1", "mnt/user-data/file.txt", Path("/tmp/f.txt"))
        assert result is False

    @pytest.mark.asyncio
    async def test_try_s3_download_returns_false_when_store_none(self):
        from src.gateway.routers.artifacts import _try_s3_download

        with (
            patch("src.storage.s3_artifact_store.is_s3_enabled", return_value=True),
            patch("src.storage.s3_artifact_store.get_s3_artifact_store", return_value=None),
        ):
            result = await _try_s3_download("t1", "u1", "mnt/user-data/file.txt", Path("/tmp/f.txt"))
        assert result is False

    @pytest.mark.asyncio
    async def test_try_s3_download_path_without_prefix(self):
        """Paths that don't start with mnt/user-data/ are passed through as-is."""
        from src.gateway.routers.artifacts import _try_s3_download

        mock_store = MagicMock()
        mock_store.download_file.return_value = True

        with (
            patch("src.storage.s3_artifact_store.is_s3_enabled", return_value=True),
            patch("src.storage.s3_artifact_store.get_s3_artifact_store", return_value=mock_store),
        ):
            await _try_s3_download("t1", "u1", "some/other/path.txt", Path("/tmp/p.txt"))

        mock_store.download_file.assert_called_once_with("u1", "t1", "some/other/path.txt", Path("/tmp/p.txt"))

    def test_update_last_accessed_debounce(self):
        """First call updates DB, second call within debounce window is skipped."""
        import src.gateway.routers.artifacts as artifacts_mod

        # Clear cache
        artifacts_mod._access_time_cache.clear()

        mock_session = MagicMock()
        mock_thread = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = mock_thread

        with (
            patch("src.db.engine.is_db_enabled", return_value=True),
            patch("src.db.engine.get_db_session", return_value=mock_session),
        ):
            # First call: should update
            artifacts_mod._update_last_accessed("thread-debounce")
            assert mock_session.get.call_count == 1

            # Second call within window: should be skipped
            artifacts_mod._update_last_accessed("thread-debounce")
            assert mock_session.get.call_count == 1  # Still 1, not 2

        # Clean up
        artifacts_mod._access_time_cache.clear()

    def test_update_last_accessed_updates_after_expiry(self):
        """After debounce period, update should fire again."""
        import src.gateway.routers.artifacts as artifacts_mod

        artifacts_mod._access_time_cache.clear()
        # Simulate a stale cache entry
        artifacts_mod._access_time_cache["thread-expired"] = time.time() - 7200  # 2h ago

        mock_session = MagicMock()
        mock_thread = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = mock_thread

        with (
            patch("src.db.engine.is_db_enabled", return_value=True),
            patch("src.db.engine.get_db_session", return_value=mock_session),
        ):
            artifacts_mod._update_last_accessed("thread-expired")
            assert mock_session.get.call_count == 1

        artifacts_mod._access_time_cache.clear()

    def test_update_last_accessed_skips_when_db_disabled(self):
        """No DB call when database is not enabled."""
        import src.gateway.routers.artifacts as artifacts_mod

        artifacts_mod._access_time_cache.clear()

        with patch("src.db.engine.is_db_enabled", return_value=False) as mock_db:
            artifacts_mod._update_last_accessed("thread-no-db")
            # is_db_enabled called but no session created

        artifacts_mod._access_time_cache.clear()


# ══════════════════════════════════════════════════════════════════════════
# Thread deletion tests (local dir + S3 enqueue)
# ══════════════════════════════════════════════════════════════════════════


class TestThreadDeletionCleanup:
    """Test that delete_thread cleans up local files and enqueues S3 deletion."""

    @pytest.mark.asyncio
    async def test_delete_thread_removes_local_dir(self, tmp_path):
        """Deleting a thread removes its local directory."""
        from src.gateway.routers.threads import delete_thread

        thread_dir = tmp_path / "threads" / "del-thread-1"
        (thread_dir / "user-data" / "outputs").mkdir(parents=True)
        (thread_dir / "user-data" / "outputs" / "file.txt").write_text("data")

        mock_paths = MagicMock()
        mock_paths.thread_dir.return_value = thread_dir

        mock_client = MagicMock()
        mock_client.threads.delete = MagicMock(return_value=None)
        # Make it async-compatible
        from unittest.mock import AsyncMock as _AsyncMock

        mock_client.threads.delete = _AsyncMock(return_value=None)

        with (
            patch("src.gateway.routers.threads.verify_thread_ownership"),
            patch("src.gateway.routers.threads.get_client", return_value=mock_client),
            patch("src.gateway.routers.threads.delete_thread_ownership"),
            patch("src.gateway.routers.threads.get_paths", return_value=mock_paths),
            patch("src.storage.s3_artifact_store.is_s3_enabled", return_value=False),
        ):
            result = await delete_thread("del-thread-1", {"id": "user-1"})

        assert result == {"success": True}
        assert not thread_dir.exists()

    @pytest.mark.asyncio
    async def test_delete_thread_enqueues_s3_deletion(self, tmp_path):
        """When S3 is enabled, delete_thread enqueues S3 cleanup."""
        from src.gateway.routers.threads import delete_thread

        mock_paths = MagicMock()
        mock_paths.thread_dir.return_value = tmp_path / "nonexistent"

        mock_client = MagicMock()
        from unittest.mock import AsyncMock as _AsyncMock

        mock_client.threads.delete = _AsyncMock(return_value=None)

        mock_queue = MagicMock()

        with (
            patch("src.gateway.routers.threads.verify_thread_ownership"),
            patch("src.gateway.routers.threads.get_client", return_value=mock_client),
            patch("src.gateway.routers.threads.delete_thread_ownership"),
            patch("src.gateway.routers.threads.get_paths", return_value=mock_paths),
            patch("src.storage.s3_artifact_store.is_s3_enabled", return_value=True),
            patch("src.queue.redis_connection.is_redis_available", return_value=True),
            patch("src.queue.redis_connection.get_redis_client", return_value=MagicMock()),
            patch("rq.Queue", return_value=mock_queue),
        ):
            result = await delete_thread("del-thread-2", {"id": "user-1"})

        assert result == {"success": True}
        mock_queue.enqueue.assert_called_once()
        call_args = mock_queue.enqueue.call_args
        assert call_args[0][0] == "src.queue.artifact_tasks.delete_thread_from_s3"
        assert call_args[1]["thread_id"] == "del-thread-2"
        assert call_args[1]["user_id"] == "user-1"

    @pytest.mark.asyncio
    async def test_delete_thread_succeeds_even_if_local_cleanup_fails(self, tmp_path):
        """Thread deletion succeeds even if local dir cleanup fails."""
        from src.gateway.routers.threads import delete_thread

        mock_paths = MagicMock()
        mock_paths.thread_dir.side_effect = Exception("permission denied")

        mock_client = MagicMock()
        from unittest.mock import AsyncMock as _AsyncMock

        mock_client.threads.delete = _AsyncMock(return_value=None)

        with (
            patch("src.gateway.routers.threads.verify_thread_ownership"),
            patch("src.gateway.routers.threads.get_client", return_value=mock_client),
            patch("src.gateway.routers.threads.delete_thread_ownership"),
            patch("src.gateway.routers.threads.get_paths", return_value=mock_paths),
            patch("src.storage.s3_artifact_store.is_s3_enabled", return_value=False),
        ):
            result = await delete_thread("del-thread-3", {"id": "user-1"})

        assert result == {"success": True}


# ══════════════════════════════════════════════════════════════════════════
# DB model tests
# ══════════════════════════════════════════════════════════════════════════


class TestThreadModelColumns:
    def test_new_columns_defaults(self, db_session):
        from src.db.models import ThreadModel

        thread = ThreadModel(thread_id="test-thread", user_id="test-user")
        db_session.add(thread)
        db_session.flush()

        fetched = db_session.get(ThreadModel, "test-thread")
        assert fetched.s3_sync_status == "none"
        assert fetched.last_accessed_at is None
        assert fetched.local_evicted is False

    def test_columns_are_writable(self, db_session):
        from src.db.models import ThreadModel

        now = datetime.now(UTC)
        thread = ThreadModel(
            thread_id="writable-thread",
            user_id="user-1",
            s3_sync_status="synced",
            last_accessed_at=now,
            local_evicted=True,
        )
        db_session.add(thread)
        db_session.flush()

        fetched = db_session.get(ThreadModel, "writable-thread")
        assert fetched.s3_sync_status == "synced"
        assert fetched.last_accessed_at is not None
        assert fetched.local_evicted is True

    def test_s3_sync_status_values(self, db_session):
        """All three status values are accepted."""
        from src.db.models import ThreadModel

        for i, status in enumerate(["none", "pending", "synced"]):
            thread = ThreadModel(
                thread_id=f"status-{i}",
                user_id="user-1",
                s3_sync_status=status,
            )
            db_session.add(thread)

        db_session.flush()

        for i, status in enumerate(["none", "pending", "synced"]):
            fetched = db_session.get(ThreadModel, f"status-{i}")
            assert fetched.s3_sync_status == status
