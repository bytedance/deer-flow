import os

from .local_storage import LocalStorage
from .r2_storage import R2Storage
from .thread_files import (
    OUTPUTS_VIRTUAL_PREFIX,
    ThreadUploadItem,
    build_upload_metadata,
    evict_local_upload_cache,
    extract_file_from_skill_archive_bytes,
    get_thread_file_backend,
    guess_mime_type,
    is_uploads_virtual_path,
    is_outputs_virtual_path,
    is_text_bytes,
    materialize_upload_to_local_cache,
    publish_output_bytes,
    publish_output_file,
    reset_thread_file_backends,
    upload_filename_from_virtual_path,
)

_legacy_storage = None


def _create_storage():
    """Backwards-compatible storage factory used by legacy tests/callers."""
    endpoint = os.getenv("R2_ENDPOINT_URL") or os.getenv("S3_ENDPOINT_URL")
    access_key_id = os.getenv("R2_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID")
    secret_access_key = os.getenv("R2_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY")
    bucket_name = os.getenv("R2_BUCKET_NAME") or os.getenv("S3_BUCKET_NAME")

    if endpoint and access_key_id and secret_access_key and bucket_name:
        return R2Storage(
            endpoint_url=endpoint,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            bucket_name=bucket_name,
        )

    return LocalStorage()


def get_storage():
    """Backwards-compatible singleton accessor for legacy storage API."""
    global _legacy_storage
    if _legacy_storage is None:
        _legacy_storage = _create_storage()
    return _legacy_storage


def reset_storage() -> None:
    """Reset legacy storage singleton cache."""
    global _legacy_storage
    _legacy_storage = None

__all__ = [
    "ThreadUploadItem",
    "OUTPUTS_VIRTUAL_PREFIX",
    "build_upload_metadata",
    "evict_local_upload_cache",
    "extract_file_from_skill_archive_bytes",
    "get_thread_file_backend",
    "guess_mime_type",
    "is_uploads_virtual_path",
    "is_outputs_virtual_path",
    "is_text_bytes",
    "materialize_upload_to_local_cache",
    "publish_output_bytes",
    "publish_output_file",
    "reset_thread_file_backends",
    "upload_filename_from_virtual_path",
    "get_storage",
    "reset_storage",
    "_create_storage",
]
