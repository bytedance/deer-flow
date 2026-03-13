"""Local filesystem storage implementation (fallback when R2 is not configured)."""

import logging
from pathlib import Path

from src.config.paths import get_paths
from src.storage.storage import FileInfo, FileStorage

logger = logging.getLogger(__name__)


class LocalStorage(FileStorage):
    """File storage backed by the local filesystem.

    Files are stored under {base_dir}/threads/{thread_id}/user-data/{category}/
    to maintain backward compatibility with the existing path structure.
    """

    def __init__(self):
        self._base_dir = get_paths().base_dir
        logger.info(f"Local storage initialized: base_dir={self._base_dir}")

    def _resolve_key(self, key: str) -> Path:
        """Resolve a storage key to an absolute filesystem path.

        Storage key format: threads/{thread_id}/{category}/{filename}
        Maps to: {base_dir}/threads/{thread_id}/user-data/{category}/{filename}
        """
        parts = key.split("/", 3)  # threads / thread_id / category / rest
        if len(parts) >= 4 and parts[0] == "threads":
            thread_id = parts[1]
            category = parts[2]
            rest = parts[3]
            return self._base_dir / "threads" / thread_id / "user-data" / category / rest
        # Fallback: treat as relative path under base_dir
        return self._base_dir / key

    def write(self, key: str, data: bytes) -> None:
        """Write data to local filesystem."""
        path = self._resolve_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        logger.debug(f"Wrote {len(data)} bytes to {path}")

    def read(self, key: str) -> bytes:
        """Read data from local filesystem."""
        path = self._resolve_key(key)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        """Check if a file exists on local filesystem."""
        return self._resolve_key(key).exists()

    def delete(self, key: str) -> None:
        """Delete a file from local filesystem."""
        path = self._resolve_key(key)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        path.unlink()
        logger.debug(f"Deleted {path}")

    def list_files(self, prefix: str) -> list[FileInfo]:
        """List files under a prefix on local filesystem."""
        path = self._resolve_key(prefix)
        if not path.exists():
            return []

        files = []
        for file_path in sorted(path.iterdir()):
            if file_path.is_file():
                stat = file_path.stat()
                # Reconstruct the storage key from the file path
                relative = file_path.relative_to(self._base_dir)
                parts = list(relative.parts)
                # Convert from threads/id/user-data/category/file to threads/id/category/file
                if len(parts) >= 4 and parts[2] == "user-data":
                    key = f"{parts[0]}/{parts[1]}/{parts[3]}/{'/'.join(parts[4:])}"
                else:
                    key = str(relative)

                files.append(
                    FileInfo(
                        filename=file_path.name,
                        size=stat.st_size,
                        path=key,
                        extension=file_path.suffix,
                        modified=stat.st_mtime,
                    )
                )

        return files
