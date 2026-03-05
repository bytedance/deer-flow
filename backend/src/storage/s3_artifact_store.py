"""S3-backed artifact storage with local disk as hot cache.

S3 is optional — if S3_ARTIFACTS_BUCKET is unset, all functions gracefully
return None / False so callers can fall back to local-only behaviour.

S3 key layout: {prefix}users/{user_id}/threads/{thread_id}/{relative_path}
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class S3ArtifactStore:
    """Synchronous S3 operations for thread artifact files."""

    def __init__(self, bucket: str, prefix: str = "", region: str | None = None) -> None:
        import boto3

        self.bucket = bucket
        self.prefix = prefix.rstrip("/") + "/" if prefix else ""
        self._client = boto3.client("s3", region_name=region)

    def _s3_key(self, user_id: str, thread_id: str, relative_path: str) -> str:
        return f"{self.prefix}users/{user_id}/threads/{thread_id}/{relative_path}"

    # ── Upload / Download ──────────────────────────────────────────────

    def upload_file(self, user_id: str, thread_id: str, relative_path: str, local_path: Path) -> None:
        key = self._s3_key(user_id, thread_id, relative_path)
        self._client.upload_file(str(local_path), self.bucket, key)
        logger.debug(f"Uploaded s3://{self.bucket}/{key}")

    def download_file(self, user_id: str, thread_id: str, relative_path: str, local_path: Path) -> bool:
        """Download a single file from S3. Returns True on success."""
        key = self._s3_key(user_id, thread_id, relative_path)
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            self._client.download_file(self.bucket, key, str(local_path))
            logger.debug(f"Downloaded s3://{self.bucket}/{key} -> {local_path}")
            return True
        except self._client.exceptions.NoSuchKey:
            return False
        except Exception as e:
            # ClientError with 404 status
            if hasattr(e, "response") and e.response.get("Error", {}).get("Code") == "404":
                return False
            logger.error(f"S3 download error for {key}: {e}")
            return False

    # ── Sync ───────────────────────────────────────────────────────────

    def sync_thread(self, user_id: str, thread_id: str, local_user_data_dir: Path) -> int:
        """Upload all local files for a thread to S3. Returns count uploaded."""
        if not local_user_data_dir.is_dir():
            return 0
        count = 0
        for file_path in local_user_data_dir.rglob("*"):
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(local_user_data_dir)
            self.upload_file(user_id, thread_id, str(relative), file_path)
            count += 1
        return count

    def is_synced(self, user_id: str, thread_id: str, local_user_data_dir: Path) -> bool:
        """Check every local file has a matching S3 object (by key existence)."""
        if not local_user_data_dir.is_dir():
            return True
        for file_path in local_user_data_dir.rglob("*"):
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(local_user_data_dir)
            if not self.file_exists(user_id, thread_id, str(relative)):
                return False
        return True

    # ── Delete ─────────────────────────────────────────────────────────

    def delete_thread(self, user_id: str, thread_id: str) -> int:
        """Delete all S3 objects for a thread. Returns count deleted."""
        prefix = self._s3_key(user_id, thread_id, "")
        return self._delete_prefix(prefix)

    def delete_user(self, user_id: str) -> int:
        """Delete all S3 objects for a user. Returns count deleted."""
        prefix = f"{self.prefix}users/{user_id}/"
        return self._delete_prefix(prefix)

    def _delete_prefix(self, prefix: str) -> int:
        """Delete all objects under a given S3 prefix."""
        deleted = 0
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            objects = page.get("Contents", [])
            if not objects:
                continue
            keys = [{"Key": obj["Key"]} for obj in objects]
            self._client.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})
            deleted += len(keys)
        return deleted

    # ── Query ──────────────────────────────────────────────────────────

    def file_exists(self, user_id: str, thread_id: str, relative_path: str) -> bool:
        key = self._s3_key(user_id, thread_id, relative_path)
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False


# ── Singleton ──────────────────────────────────────────────────────────

_store: S3ArtifactStore | None = None
_checked = False


def is_s3_enabled() -> bool:
    """Return True if S3_ARTIFACTS_BUCKET is configured."""
    return bool(os.environ.get("S3_ARTIFACTS_BUCKET"))


def get_s3_artifact_store() -> S3ArtifactStore | None:
    """Return the singleton S3ArtifactStore, or None if S3 is not configured."""
    global _store, _checked
    if _checked:
        return _store
    _checked = True

    bucket = os.environ.get("S3_ARTIFACTS_BUCKET")
    if not bucket:
        return None

    prefix = os.environ.get("S3_ARTIFACTS_PREFIX", "")
    region = os.environ.get("S3_ARTIFACTS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    _store = S3ArtifactStore(bucket=bucket, prefix=prefix, region=region)
    logger.info(f"S3 artifact store initialised: bucket={bucket}, prefix={prefix!r}, region={region}")
    return _store
