"""MinIOWorkspaceBackend — stores agent workspace in MinIO object storage.

Path convention: {bucket}/{prefix}/{dept_id}/{user_id}/{agent_name}/
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from deerflow.sandbox.workspace import WorkspaceBackend

if TYPE_CHECKING:
    from deerflow.identity.agent_identity import AgentIdentity

logger = logging.getLogger(__name__)


class MinIOWorkspaceBackend(WorkspaceBackend):
    """MinIO-backed persistent workspace.

    Requires the ``minio`` package (``uv add minio``).

    Args:
        endpoint: MinIO server endpoint (e.g. "localhost:9000").
        bucket: Bucket name (e.g. "deer-flow").
        access_key: MinIO access key.
        secret_key: MinIO secret key.
        secure: Use HTTPS when True.
        prefix: Object prefix inside the bucket (e.g. "workspaces").
    """

    def __init__(
        self,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        secure: bool = False,
        prefix: str = "workspaces",
    ) -> None:
        try:
            from minio import Minio  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "MinIOWorkspaceBackend requires the 'minio' package. "
                "Install it with: uv add minio"
            ) from exc

        self._client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self._bucket = bucket
        self._prefix = prefix.rstrip("/")

        # Ensure bucket exists (blocking — called at construction time only)
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)

    # ── WorkspaceBackend interface ────────────────────────────────────────

    async def sync_down(self, identity: "AgentIdentity", local_dir: Path) -> None:
        """Download workspace objects from MinIO → *local_dir*."""
        remote_prefix = self._object_prefix(identity)
        local_dir.mkdir(parents=True, exist_ok=True)

        await asyncio.get_event_loop().run_in_executor(
            None, self._sync_down_sync, remote_prefix, local_dir
        )

    async def sync_up(self, identity: "AgentIdentity", local_dir: Path) -> None:
        """Upload *local_dir* files → MinIO."""
        remote_prefix = self._object_prefix(identity)

        await asyncio.get_event_loop().run_in_executor(
            None, self._sync_up_sync, remote_prefix, local_dir
        )

    # ── Sync helpers (run in executor thread pool) ────────────────────────

    def _object_prefix(self, identity: "AgentIdentity") -> str:
        """Build the MinIO object prefix for the given identity."""
        return f"{self._prefix}/{identity.ov_account}/{identity.ov_user}/{identity.ov_agent}"

    def _sync_down_sync(self, remote_prefix: str, local_dir: Path) -> None:
        objects = self._client.list_objects(self._bucket, prefix=remote_prefix + "/", recursive=True)
        count = 0
        for obj in objects:
            if obj.object_name is None:
                continue
            # Strip remote prefix to get relative path
            relative = obj.object_name[len(remote_prefix) :].lstrip("/")
            if not relative:
                continue
            dest = local_dir / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            self._client.fget_object(self._bucket, obj.object_name, str(dest))
            count += 1
        logger.debug("sync_down: %d objects from %s/%s", count, self._bucket, remote_prefix)

    def _sync_up_sync(self, remote_prefix: str, local_dir: Path) -> None:
        if not local_dir.exists():
            return
        count = 0
        for local_file in local_dir.rglob("*"):
            if not local_file.is_file():
                continue
            relative = local_file.relative_to(local_dir)
            object_name = f"{remote_prefix}/{relative.as_posix()}"
            self._client.fput_object(self._bucket, object_name, str(local_file))
            count += 1
        logger.debug("sync_up: %d objects to %s/%s", count, self._bucket, remote_prefix)
