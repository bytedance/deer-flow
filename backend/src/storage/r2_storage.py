"""Cloudflare R2 / S3-compatible file storage implementation."""

import logging
import threading
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from src.storage.storage import FileInfo, FileStorage

logger = logging.getLogger(__name__)

# boto3 defaults to no timeout, which can hang in non-main threads.
_BOTO3_CONFIG = Config(
    connect_timeout=10,
    read_timeout=30,
    retries={"max_attempts": 2},
)


class R2Storage(FileStorage):
    """File storage backed by Cloudflare R2 (S3-compatible).

    Thread-safe: uses per-thread boto3 sessions to avoid concurrent client access.

    Configuration via environment variables:
        R2_ENDPOINT_URL: R2 endpoint (e.g., https://<account_id>.r2.cloudflarestorage.com)
        R2_ACCESS_KEY_ID: R2 access key
        R2_SECRET_ACCESS_KEY: R2 secret key
        R2_BUCKET_NAME: R2 bucket name
    """

    def __init__(self, endpoint_url: str, access_key_id: str, secret_access_key: str, bucket_name: str):
        self._bucket_name = bucket_name
        self._endpoint_url = endpoint_url
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._local = threading.local()
        logger.info(f"R2 storage initialized: bucket={bucket_name}, endpoint={endpoint_url}")

    @property
    def _client(self):
        """Get a thread-local boto3 S3 client."""
        client = getattr(self._local, "client", None)
        if client is None:
            session = boto3.Session()
            client = session.client(
                "s3",
                endpoint_url=self._endpoint_url,
                aws_access_key_id=self._access_key_id,
                aws_secret_access_key=self._secret_access_key,
                region_name="auto",
                config=_BOTO3_CONFIG,
            )
            self._local.client = client
        return client

    def write(self, key: str, data: bytes) -> None:
        """Write data to R2."""
        self._client.put_object(Bucket=self._bucket_name, Key=key, Body=data)
        logger.debug(f"Wrote {len(data)} bytes to R2: {key}")

    def read(self, key: str) -> bytes:
        """Read data from R2."""
        try:
            response = self._client.get_object(Bucket=self._bucket_name, Key=key)
            return response["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(f"File not found in R2: {key}") from e
            raise

    def exists(self, key: str) -> bool:
        """Check if a key exists in R2."""
        try:
            self._client.head_object(Bucket=self._bucket_name, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    def delete(self, key: str) -> None:
        """Delete a file from R2."""
        if not self.exists(key):
            raise FileNotFoundError(f"File not found in R2: {key}")
        self._client.delete_object(Bucket=self._bucket_name, Key=key)
        logger.debug(f"Deleted from R2: {key}")

    def generate_presigned_put(self, key: str, content_type: str = "application/octet-stream", expires_in: int = 3600) -> str:
        """Generate a presigned PUT URL for direct browser upload.

        Args:
            key: Storage key (e.g., 'threads/{thread_id}/uploads/file.txt').
            content_type: MIME type of the file.
            expires_in: URL expiration time in seconds (default: 1 hour).

        Returns:
            Presigned PUT URL.
        """
        return self._client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._bucket_name,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=expires_in,
        )

    def warmup(self) -> None:
        """Pre-warm the boto3 client by forcing the SSL handshake.

        Call this at startup to avoid ~10s cold start on first real operation.
        """
        try:
            self._client.list_objects_v2(Bucket=self._bucket_name, MaxKeys=0)
            logger.info("R2 client warmed up successfully")
        except Exception as e:
            logger.warning(f"R2 warmup failed (non-fatal): {e}")

    def list_files(self, prefix: str) -> list[FileInfo]:
        """List files under a prefix in R2."""
        files = []
        paginator = self._client.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=self._bucket_name, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                filename = Path(key).name
                if not filename:
                    continue
                files.append(
                    FileInfo(
                        filename=filename,
                        size=obj["Size"],
                        path=key,
                        extension=Path(filename).suffix,
                        modified=obj["LastModified"].timestamp(),
                    )
                )

        return sorted(files, key=lambda f: f.filename)
