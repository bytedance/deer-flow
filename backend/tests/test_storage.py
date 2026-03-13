"""Tests for the file storage abstraction layer."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# boto3 and botocore are real dependencies (installed), no need to mock them

from src.storage.storage import FileInfo, FileStorage
from src.storage.local_storage import LocalStorage
from src.storage.r2_storage import R2Storage


class TestFileStorageKeyHelpers:
    """Test the static key-building helpers."""

    def test_upload_key(self):
        assert FileStorage.upload_key("thread-1", "doc.pdf") == "threads/thread-1/uploads/doc.pdf"

    def test_output_key(self):
        assert FileStorage.output_key("thread-1", "report.html") == "threads/thread-1/outputs/report.html"

    def test_workspace_key(self):
        assert FileStorage.workspace_key("thread-1", "main.py") == "threads/thread-1/workspace/main.py"

    def test_uploads_prefix(self):
        assert FileStorage.uploads_prefix("thread-1") == "threads/thread-1/uploads/"

    def test_outputs_prefix(self):
        assert FileStorage.outputs_prefix("thread-1") == "threads/thread-1/outputs/"

    def test_thread_prefix(self):
        assert FileStorage.thread_prefix("thread-1") == "threads/thread-1/"


class TestLocalStorage:
    """Tests for LocalStorage implementation."""

    @pytest.fixture
    def storage(self, tmp_path):
        """Create a LocalStorage with a temp base directory."""
        with patch("src.storage.local_storage.get_paths") as mock_paths:
            mock_paths.return_value.base_dir = tmp_path
            s = LocalStorage()
        return s

    def test_write_and_read(self, storage, tmp_path):
        key = "threads/t1/uploads/test.txt"
        data = b"hello world"

        storage.write(key, data)
        result = storage.read(key)

        assert result == data
        # Verify actual file path includes user-data
        actual = tmp_path / "threads" / "t1" / "user-data" / "uploads" / "test.txt"
        assert actual.exists()

    def test_read_not_found(self, storage):
        with pytest.raises(FileNotFoundError):
            storage.read("threads/t1/uploads/nonexistent.txt")

    def test_exists(self, storage):
        key = "threads/t1/uploads/test.txt"
        assert not storage.exists(key)

        storage.write(key, b"data")
        assert storage.exists(key)

    def test_delete(self, storage):
        key = "threads/t1/uploads/test.txt"
        storage.write(key, b"data")
        assert storage.exists(key)

        storage.delete(key)
        assert not storage.exists(key)

    def test_delete_not_found(self, storage):
        with pytest.raises(FileNotFoundError):
            storage.delete("threads/t1/uploads/nonexistent.txt")

    def test_list_files(self, storage):
        storage.write("threads/t1/uploads/a.txt", b"aaa")
        storage.write("threads/t1/uploads/b.pdf", b"bbb")

        files = storage.list_files("threads/t1/uploads/")
        assert len(files) == 2

        filenames = [f.filename for f in files]
        assert "a.txt" in filenames
        assert "b.pdf" in filenames

        a_file = next(f for f in files if f.filename == "a.txt")
        assert a_file.size == 3
        assert a_file.extension == ".txt"

    def test_list_files_empty(self, storage):
        files = storage.list_files("threads/t1/uploads/")
        assert files == []

    def test_write_creates_directories(self, storage):
        key = "threads/t1/outputs/subdir/deep/file.txt"
        storage.write(key, b"nested")
        assert storage.read(key) == b"nested"


class TestR2Storage:
    """Tests for R2Storage implementation."""

    @pytest.fixture
    def r2(self):
        """Create an R2Storage with mocked boto3 client."""
        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_session.client.return_value = mock_client
        with patch("src.storage.r2_storage.boto3") as mock_b3:
            mock_b3.Session.return_value = mock_session
            storage = R2Storage(
                endpoint_url="https://test.r2.cloudflarestorage.com",
                access_key_id="test-key",
                secret_access_key="test-secret",
                bucket_name="test-bucket",
            )
            # Pre-populate the thread-local client so the property doesn't create a real one
            storage._local.client = mock_client
            storage._mock_client = mock_client
            return storage

    def test_write(self, r2):
        r2.write("threads/t1/uploads/doc.pdf", b"pdf-content")

        r2._mock_client.put_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="threads/t1/uploads/doc.pdf",
            Body=b"pdf-content",
        )

    def test_read(self, r2):
        mock_body = MagicMock()
        mock_body.read.return_value = b"file-data"
        r2._mock_client.get_object.return_value = {"Body": mock_body}

        result = r2.read("threads/t1/uploads/doc.pdf")

        assert result == b"file-data"
        r2._mock_client.get_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="threads/t1/uploads/doc.pdf",
        )

    def test_read_not_found(self, r2):
        from botocore.exceptions import ClientError

        # Since botocore is mocked, create a proper-looking error
        error = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        r2._mock_client.get_object.side_effect = error

        with pytest.raises(FileNotFoundError, match="File not found in R2"):
            r2.read("threads/t1/uploads/nope.txt")

    def test_exists_true(self, r2):
        r2._mock_client.head_object.return_value = {}
        assert r2.exists("threads/t1/uploads/doc.pdf") is True

    def test_exists_false(self, r2):
        from botocore.exceptions import ClientError

        error = ClientError({"Error": {"Code": "404"}}, "HeadObject")
        r2._mock_client.head_object.side_effect = error
        assert r2.exists("threads/t1/uploads/nope.txt") is False

    def test_delete(self, r2):
        # exists returns True
        r2._mock_client.head_object.return_value = {}

        r2.delete("threads/t1/uploads/doc.pdf")

        r2._mock_client.delete_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="threads/t1/uploads/doc.pdf",
        )

    def test_delete_not_found(self, r2):
        from botocore.exceptions import ClientError

        error = ClientError({"Error": {"Code": "404"}}, "HeadObject")
        r2._mock_client.head_object.side_effect = error

        with pytest.raises(FileNotFoundError):
            r2.delete("threads/t1/uploads/nope.txt")

    def test_list_files(self, r2):
        from datetime import datetime

        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {
                        "Key": "threads/t1/uploads/a.txt",
                        "Size": 100,
                        "LastModified": datetime(2025, 1, 1),
                    },
                    {
                        "Key": "threads/t1/uploads/b.pdf",
                        "Size": 2000,
                        "LastModified": datetime(2025, 1, 2),
                    },
                ]
            }
        ]
        r2._mock_client.get_paginator.return_value = mock_paginator

        files = r2.list_files("threads/t1/uploads/")

        assert len(files) == 2
        assert files[0].filename == "a.txt"
        assert files[0].size == 100
        assert files[1].filename == "b.pdf"
        assert files[1].size == 2000

    def test_list_files_empty(self, r2):
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"Contents": []}]
        r2._mock_client.get_paginator.return_value = mock_paginator

        files = r2.list_files("threads/t1/uploads/")
        assert files == []


class TestStorageFactory:
    """Tests for the get_storage() factory function."""

    def test_local_storage_when_no_r2_config(self):
        """Should return LocalStorage when R2 env vars are not set."""
        from src.storage import reset_storage, _create_storage

        reset_storage()

        # Clear any R2 env vars
        env_vars = ["R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME", "S3_ENDPOINT_URL", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "S3_BUCKET_NAME"]
        old_values = {}
        for var in env_vars:
            old_values[var] = os.environ.pop(var, None)

        try:
            storage = _create_storage()
            assert isinstance(storage, LocalStorage)
        finally:
            for var, val in old_values.items():
                if val is not None:
                    os.environ[var] = val
            reset_storage()

    def test_r2_storage_when_configured(self):
        """Should return R2Storage when R2 env vars are set."""
        from src.storage import reset_storage, _create_storage

        reset_storage()

        with patch.dict(os.environ, {
            "R2_ENDPOINT_URL": "https://test.r2.cloudflarestorage.com",
            "R2_ACCESS_KEY_ID": "key",
            "R2_SECRET_ACCESS_KEY": "secret",
            "R2_BUCKET_NAME": "bucket",
        }):
            with patch("src.storage.r2_storage.boto3"):
                storage = _create_storage()
                assert isinstance(storage, R2Storage)

        reset_storage()
