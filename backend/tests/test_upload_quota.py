"""Tests for per-user upload quota enforcement (Phase 6.7)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from src.gateway.routers.uploads import (
    UPLOAD_QUOTA_BYTES,
    _check_upload_quota,
    _get_user_total_upload_bytes,
)


class TestUploadQuotaCheck:
    """Test quota enforcement logic."""

    def test_under_quota_passes(self):
        """Upload within quota should not raise."""
        with patch(
            "src.gateway.routers.uploads._get_user_total_upload_bytes",
            return_value=0,
        ):
            # Should not raise
            _check_upload_quota("user1", 1024)

    def test_at_quota_fails(self):
        """Upload that would exactly hit quota limit should fail."""
        with patch(
            "src.gateway.routers.uploads._get_user_total_upload_bytes",
            return_value=UPLOAD_QUOTA_BYTES,
        ):
            with pytest.raises(HTTPException) as exc_info:
                _check_upload_quota("user1", 1)
            assert exc_info.value.status_code == 413
            assert "quota exceeded" in exc_info.value.detail.lower()

    def test_over_quota_fails(self):
        """Upload exceeding quota should raise 413."""
        with patch(
            "src.gateway.routers.uploads._get_user_total_upload_bytes",
            return_value=UPLOAD_QUOTA_BYTES - 100,
        ):
            with pytest.raises(HTTPException) as exc_info:
                _check_upload_quota("user1", 200)
            assert exc_info.value.status_code == 413

    def test_zero_existing_large_upload_fails(self):
        """A single upload exceeding quota should fail."""
        with patch(
            "src.gateway.routers.uploads._get_user_total_upload_bytes",
            return_value=0,
        ):
            with pytest.raises(HTTPException) as exc_info:
                _check_upload_quota("user1", UPLOAD_QUOTA_BYTES + 1)
            assert exc_info.value.status_code == 413


class TestUserTotalUploadBytes:
    """Test upload size tracking via filesystem fallback."""

    def _mock_paths(self, tmp_path):
        """Return a Paths instance rooted at tmp_path/.think-tank."""
        from src.config.paths import Paths

        return Paths(tmp_path / ".think-tank")

    def test_empty_directory_returns_zero(self, tmp_path):
        """No uploads should return 0 bytes."""
        with (
            patch(
                "src.db.engine.is_db_enabled",
                return_value=False,
            ),
            patch(
                "src.gateway.routers.uploads.get_paths",
                return_value=self._mock_paths(tmp_path),
            ),
        ):
            total = _get_user_total_upload_bytes("user1")
            assert total == 0

    def test_counts_files_on_disk(self, tmp_path):
        """Filesystem fallback should sum file sizes across threads."""
        base = tmp_path / ".think-tank" / "threads"
        thread_uploads = base / "t1" / "user-data" / "uploads"
        thread_uploads.mkdir(parents=True)

        # Create test files
        (thread_uploads / "file1.txt").write_text("hello")
        (thread_uploads / "file2.txt").write_text("world!")

        with (
            patch(
                "src.db.engine.is_db_enabled",
                return_value=False,
            ),
            patch(
                "src.gateway.routers.uploads.get_paths",
                return_value=self._mock_paths(tmp_path),
            ),
        ):
            total = _get_user_total_upload_bytes("user1")
            assert total == 5 + 6  # "hello" + "world!"

    def test_counts_across_multiple_threads(self, tmp_path):
        """Filesystem should sum across multiple thread directories."""
        base = tmp_path / ".think-tank" / "threads"

        for tid in ["t1", "t2"]:
            uploads = base / tid / "user-data" / "uploads"
            uploads.mkdir(parents=True)
            (uploads / "data.bin").write_bytes(b"x" * 100)

        with (
            patch(
                "src.db.engine.is_db_enabled",
                return_value=False,
            ),
            patch(
                "src.gateway.routers.uploads.get_paths",
                return_value=self._mock_paths(tmp_path),
            ),
        ):
            total = _get_user_total_upload_bytes("user1")
            assert total == 200


class TestQuotaConfiguration:
    """Test quota configuration via environment variable."""

    def test_default_quota_is_500mb(self):
        """Default quota should be 500 MB."""
        assert UPLOAD_QUOTA_BYTES == 500 * 1024 * 1024

    def test_quota_env_var_override(self):
        """UPLOAD_QUOTA_MB env var should override the default."""
        with patch.dict(os.environ, {"UPLOAD_QUOTA_MB": "100"}):
            # Need to reimport to pick up env var
            import importlib

            import src.gateway.routers.uploads as uploads_mod

            importlib.reload(uploads_mod)
            assert uploads_mod.UPLOAD_QUOTA_BYTES == 100 * 1024 * 1024

            # Restore
            os.environ.pop("UPLOAD_QUOTA_MB", None)
            importlib.reload(uploads_mod)
