from src.storage.storage import FileStorage, FileInfo
from src.storage.r2_storage import R2Storage

__all__ = ["FileStorage", "FileInfo", "R2Storage", "get_storage"]


_storage: FileStorage | None = None


def get_storage() -> FileStorage:
    """Get the global file storage singleton.

    Returns R2Storage if R2 credentials are configured, otherwise falls back
    to LocalStorage (filesystem-based).
    """
    global _storage
    if _storage is None:
        _storage = _create_storage()
    return _storage


def reset_storage() -> None:
    """Reset the storage singleton."""
    global _storage
    _storage = None


def _create_storage() -> FileStorage:
    """Create the appropriate storage backend based on environment variables."""
    import os

    # Check for R2/S3 configuration
    endpoint = os.environ.get("R2_ENDPOINT_URL") or os.environ.get("S3_ENDPOINT_URL")
    access_key = os.environ.get("R2_ACCESS_KEY_ID") or os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY")
    bucket = os.environ.get("R2_BUCKET_NAME") or os.environ.get("S3_BUCKET_NAME")

    if endpoint and access_key and secret_key and bucket:
        from src.storage.r2_storage import R2Storage

        return R2Storage(
            endpoint_url=endpoint,
            access_key_id=access_key,
            secret_access_key=secret_key,
            bucket_name=bucket,
        )

    # Fallback to local storage
    from src.storage.local_storage import LocalStorage

    return LocalStorage()
