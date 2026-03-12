"""Abstract file storage interface for DeerFlow thread data."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class FileInfo:
    """Metadata about a stored file."""

    filename: str
    size: int
    path: str  # Storage key / virtual path
    extension: str
    modified: float  # Unix timestamp


class FileStorage(ABC):
    """Abstract interface for persistent file storage.

    All paths use the convention: threads/{thread_id}/{category}/{filename}
    where category is 'uploads', 'outputs', or 'workspace'.
    """

    @abstractmethod
    def write(self, key: str, data: bytes) -> None:
        """Write binary data to storage.

        Args:
            key: Storage key (e.g., 'threads/{thread_id}/uploads/file.txt').
            data: Binary content to store.
        """
        pass

    @abstractmethod
    def read(self, key: str) -> bytes:
        """Read binary data from storage.

        Args:
            key: Storage key.

        Returns:
            File contents as bytes.

        Raises:
            FileNotFoundError: If the key does not exist.
        """
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if a key exists in storage.

        Args:
            key: Storage key.

        Returns:
            True if the key exists.
        """
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a file from storage.

        Args:
            key: Storage key.

        Raises:
            FileNotFoundError: If the key does not exist.
        """
        pass

    @abstractmethod
    def list_files(self, prefix: str) -> list[FileInfo]:
        """List files under a prefix.

        Args:
            prefix: Key prefix (e.g., 'threads/{thread_id}/uploads/').

        Returns:
            List of FileInfo objects for matching files.
        """
        pass

    # ── Convenience helpers ──────────────────────────────────────────────

    @staticmethod
    def upload_key(thread_id: str, filename: str) -> str:
        """Build storage key for an uploaded file."""
        return f"threads/{thread_id}/uploads/{filename}"

    @staticmethod
    def output_key(thread_id: str, filename: str) -> str:
        """Build storage key for an output/artifact file."""
        return f"threads/{thread_id}/outputs/{filename}"

    @staticmethod
    def workspace_key(thread_id: str, filename: str) -> str:
        """Build storage key for a workspace file."""
        return f"threads/{thread_id}/workspace/{filename}"

    @staticmethod
    def uploads_prefix(thread_id: str) -> str:
        """Build prefix for listing uploads."""
        return f"threads/{thread_id}/uploads/"

    @staticmethod
    def outputs_prefix(thread_id: str) -> str:
        """Build prefix for listing outputs."""
        return f"threads/{thread_id}/outputs/"

    @staticmethod
    def thread_prefix(thread_id: str) -> str:
        """Build prefix for all thread data."""
        return f"threads/{thread_id}/"
