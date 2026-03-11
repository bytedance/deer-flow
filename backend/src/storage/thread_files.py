import io
import os
import mimetypes
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.config import get_app_config
from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths


@dataclass
class ThreadUploadItem:
    filename: str
    size: int
    extension: str
    modified: float


OUTPUTS_VIRTUAL_PREFIX = f"{VIRTUAL_PATH_PREFIX}/outputs/"
UPLOADS_VIRTUAL_PREFIX = f"{VIRTUAL_PATH_PREFIX}/uploads/"

DEFAULT_UPLOAD_CACHE_TTL_SECONDS = 6 * 60 * 60
DEFAULT_UPLOAD_CACHE_MAX_THREAD_BYTES = 2 * 1024 * 1024 * 1024


class ThreadFileBackend:
    """Storage backend for thread-scoped uploads and artifacts."""

    def put_virtual_file(self, thread_id: str, virtual_path: str, content: bytes) -> None:
        raise NotImplementedError

    def read_virtual_file(self, thread_id: str, virtual_path: str) -> bytes:
        raise NotImplementedError

    def exists_virtual_file(self, thread_id: str, virtual_path: str) -> bool:
        raise NotImplementedError

    def delete_virtual_file(self, thread_id: str, virtual_path: str) -> bool:
        raise NotImplementedError

    def list_uploads(self, thread_id: str) -> list[ThreadUploadItem]:
        raise NotImplementedError

    def materialize_virtual_file(self, thread_id: str, virtual_path: str, destination_path: str | Path) -> Path:
        """Materialize a virtual file to a local destination path.

        Default implementation reads the object and writes bytes to disk.
        Backends should override this to support streaming downloads.
        """
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.read_virtual_file(thread_id, virtual_path))
        return destination


class LocalThreadFileBackend(ThreadFileBackend):
    def _resolve(self, thread_id: str, virtual_path: str) -> Path:
        try:
            return get_paths().resolve_virtual_path(thread_id, virtual_path)
        except ValueError as e:
            if "traversal" in str(e):
                raise PermissionError("Access denied: path traversal detected") from e
            raise

    def put_virtual_file(self, thread_id: str, virtual_path: str, content: bytes) -> None:
        path = self._resolve(thread_id, virtual_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def read_virtual_file(self, thread_id: str, virtual_path: str) -> bytes:
        path = self._resolve(thread_id, virtual_path)
        return path.read_bytes()

    def exists_virtual_file(self, thread_id: str, virtual_path: str) -> bool:
        path = self._resolve(thread_id, virtual_path)
        return path.is_file()

    def delete_virtual_file(self, thread_id: str, virtual_path: str) -> bool:
        path = self._resolve(thread_id, virtual_path)
        if not path.exists():
            return False
        if not path.is_file():
            return False
        path.unlink()
        return True

    def list_uploads(self, thread_id: str) -> list[ThreadUploadItem]:
        uploads_dir = get_paths().sandbox_uploads_dir(thread_id)
        if not uploads_dir.exists():
            return []

        items: list[ThreadUploadItem] = []
        for path in sorted(uploads_dir.iterdir()):
            if not path.is_file():
                continue
            stat = path.stat()
            items.append(
                ThreadUploadItem(
                    filename=path.name,
                    size=stat.st_size,
                    extension=path.suffix,
                    modified=stat.st_mtime,
                )
            )

        return items

    def materialize_virtual_file(self, thread_id: str, virtual_path: str, destination_path: str | Path) -> Path:
        source_path = self._resolve(thread_id, virtual_path)
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source_path.resolve() != destination.resolve():
            shutil.copy2(source_path, destination)
        destination.touch(exist_ok=True)
        return destination


class R2ThreadFileBackend(ThreadFileBackend):
    """Cloudflare R2 implementation via S3-compatible API."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint: str,
        access_key_id: str,
        secret_access_key: str,
        region: str,
        key_prefix: str,
    ) -> None:
        self._bucket = bucket
        self._key_prefix = key_prefix.strip("/")

        if not bucket or not endpoint or not access_key_id or not secret_access_key:
            raise ValueError("thread_files.r2 config is incomplete; bucket/endpoint/access_key_id/secret_access_key are required")

        try:
            from importlib import import_module

            boto3 = import_module("boto3")
        except ImportError as e:
            raise RuntimeError("boto3 is required for thread_files r2 backend") from e

        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region or "auto",
        )

    def _normalize_virtual_path(self, virtual_path: str) -> str:
        stripped = virtual_path.lstrip("/")
        prefix = VIRTUAL_PATH_PREFIX.lstrip("/")
        if stripped != prefix and not stripped.startswith(prefix + "/"):
            raise ValueError(f"Path must start with /{prefix}")
        relative = stripped[len(prefix) :].lstrip("/")
        if ".." in Path(relative).parts:
            raise PermissionError("Access denied: path traversal detected")
        return relative

    def _object_key(self, thread_id: str, virtual_path: str) -> str:
        rel = self._normalize_virtual_path(virtual_path)
        parts = [p for p in [self._key_prefix, thread_id, rel] if p]
        return "/".join(parts)

    def _uploads_prefix(self, thread_id: str) -> str:
        parts = [p for p in [self._key_prefix, thread_id, "uploads/"] if p]
        return "/".join(parts)

    def put_virtual_file(self, thread_id: str, virtual_path: str, content: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=self._object_key(thread_id, virtual_path), Body=content)

    def read_virtual_file(self, thread_id: str, virtual_path: str) -> bytes:
        obj = self._client.get_object(Bucket=self._bucket, Key=self._object_key(thread_id, virtual_path))
        return obj["Body"].read()

    def exists_virtual_file(self, thread_id: str, virtual_path: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=self._object_key(thread_id, virtual_path))
            return True
        except Exception:
            return False

    def delete_virtual_file(self, thread_id: str, virtual_path: str) -> bool:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=self._object_key(thread_id, virtual_path))
            return True
        except Exception:
            return False

    def list_uploads(self, thread_id: str) -> list[ThreadUploadItem]:
        prefix = self._uploads_prefix(thread_id)
        resp = self._client.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
        contents = resp.get("Contents", [])
        items: list[ThreadUploadItem] = []

        for obj in contents:
            key = obj.get("Key") or ""
            if key.endswith("/"):
                continue
            filename = key.rsplit("/", 1)[-1]
            if not filename:
                continue
            last_modified = obj.get("LastModified")
            modified = last_modified.timestamp() if isinstance(last_modified, datetime) else 0.0
            items.append(
                ThreadUploadItem(
                    filename=filename,
                    size=int(obj.get("Size", 0)),
                    extension=Path(filename).suffix,
                    modified=modified,
                )
            )

        items.sort(key=lambda i: i.filename)
        return items

    def materialize_virtual_file(self, thread_id: str, virtual_path: str, destination_path: str | Path) -> Path:
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as file_obj:
            self._client.download_fileobj(self._bucket, self._object_key(thread_id, virtual_path), file_obj)
        destination.touch(exist_ok=True)
        return destination


_backend_cache: dict[str, ThreadFileBackend] = {}


def get_thread_file_backend(feature: str) -> ThreadFileBackend:
    config = None
    backend_kind = "local"
    try:
        config = get_app_config().thread_files
        backend_kind = config.backend_for_feature(feature)
    except Exception:
        # Some tests and utility contexts run without a full config file.
        backend_kind = "local"
    cache_key = f"{feature}:{backend_kind}"

    cached = _backend_cache.get(cache_key)
    if cached is not None:
        return cached

    if backend_kind == "local":
        backend = LocalThreadFileBackend()
    elif backend_kind == "r2":
        if config is None:
            raise ValueError("thread_files config is unavailable for r2 backend")
        r2 = config.r2
        backend = R2ThreadFileBackend(
            bucket=r2.bucket,
            endpoint=r2.endpoint,
            access_key_id=r2.access_key_id,
            secret_access_key=r2.secret_access_key,
            region=r2.region,
            key_prefix=r2.key_prefix,
        )
    else:
        raise ValueError(f"Unsupported thread-files backend: {backend_kind}")

    _backend_cache[cache_key] = backend
    return backend


def reset_thread_file_backends() -> None:
    _backend_cache.clear()


def build_upload_metadata(thread_id: str, item: ThreadUploadItem) -> dict:
    return {
        "filename": item.filename,
        "size": item.size,
        "path": str(get_paths().sandbox_uploads_dir(thread_id) / item.filename),
        "virtual_path": f"{VIRTUAL_PATH_PREFIX}/uploads/{item.filename}",
        "artifact_url": f"/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/{item.filename}",
        "extension": item.extension,
        "modified": item.modified,
    }


def is_uploads_virtual_path(path: str) -> bool:
    """Return True when the path points to /mnt/user-data/uploads."""
    normalized = f"/{path.lstrip('/')}"
    return normalized.startswith(UPLOADS_VIRTUAL_PREFIX)


def upload_filename_from_virtual_path(path: str) -> str | None:
    """Extract upload filename from a /mnt/user-data/uploads virtual path."""
    if not is_uploads_virtual_path(path):
        return None
    normalized = f"/{path.lstrip('/')}"
    relative = normalized[len(UPLOADS_VIRTUAL_PREFIX) :]
    if not relative:
        return None
    filename = Path(relative).name
    if filename != relative or filename in {"", ".", ".."}:
        return None
    return filename


def _safe_upload_cache_config() -> tuple[int, int]:
    ttl = DEFAULT_UPLOAD_CACHE_TTL_SECONDS
    max_bytes = DEFAULT_UPLOAD_CACHE_MAX_THREAD_BYTES
    try:
        ttl = max(60, int(os.getenv("THREAD_UPLOAD_CACHE_TTL_SECONDS", str(ttl))))
    except ValueError:
        ttl = DEFAULT_UPLOAD_CACHE_TTL_SECONDS
    try:
        max_bytes = max(10 * 1024 * 1024, int(os.getenv("THREAD_UPLOAD_CACHE_MAX_THREAD_BYTES", str(max_bytes))))
    except ValueError:
        max_bytes = DEFAULT_UPLOAD_CACHE_MAX_THREAD_BYTES
    return ttl, max_bytes


def evict_local_upload_cache(thread_id: str, *, keep_filenames: set[str] | None = None) -> None:
    """Apply TTL and size-based eviction for local materialized upload cache files."""
    uploads_dir = get_paths().sandbox_uploads_dir(thread_id)
    if not uploads_dir.exists():
        return

    ttl_seconds, max_thread_bytes = _safe_upload_cache_config()
    now = datetime.now().timestamp()
    keep_filenames = keep_filenames or set()

    files: list[tuple[Path, float, int]] = []
    for file_path in uploads_dir.iterdir():
        if not file_path.is_file():
            continue
        try:
            stat = file_path.stat()
        except OSError:
            continue
        files.append((file_path, stat.st_mtime, stat.st_size))

    for file_path, mtime, _size in files:
        if file_path.name in keep_filenames:
            continue
        if now - mtime > ttl_seconds:
            try:
                file_path.unlink()
            except OSError:
                pass

    files_after_ttl: list[tuple[Path, float, int]] = []
    total_size = 0
    for file_path in uploads_dir.iterdir():
        if not file_path.is_file():
            continue
        try:
            stat = file_path.stat()
        except OSError:
            continue
        files_after_ttl.append((file_path, stat.st_mtime, stat.st_size))
        total_size += stat.st_size

    if total_size <= max_thread_bytes:
        return

    # Evict oldest files first until under budget.
    files_after_ttl.sort(key=lambda item: item[1])
    for file_path, _mtime, size in files_after_ttl:
        if total_size <= max_thread_bytes:
            break
        if file_path.name in keep_filenames:
            continue
        try:
            file_path.unlink()
            total_size -= size
        except OSError:
            continue


def materialize_upload_to_local_cache(thread_id: str, virtual_path: str) -> Path:
    """Lazy materialize an upload into the thread-local uploads cache directory."""
    filename = upload_filename_from_virtual_path(virtual_path)
    if not filename:
        raise ValueError(f"Invalid upload virtual path: {virtual_path}")

    local_path = get_paths().sandbox_uploads_dir(thread_id) / filename
    if local_path.is_file():
        local_path.touch(exist_ok=True)
        evict_local_upload_cache(thread_id, keep_filenames={filename})
        return local_path

    uploads_backend = get_thread_file_backend("uploads")
    normalized = f"/{virtual_path.lstrip('/')}"
    if not uploads_backend.exists_virtual_file(thread_id, normalized):
        raise FileNotFoundError(f"Upload not found in durable backend: {normalized}")

    uploads_backend.materialize_virtual_file(thread_id, normalized, local_path)
    local_path.touch(exist_ok=True)
    evict_local_upload_cache(thread_id, keep_filenames={filename})
    return local_path


def guess_mime_type(path: str) -> str | None:
    mime_type, _ = mimetypes.guess_type(path)
    return mime_type


def is_text_bytes(content: bytes, sample_size: int = 8192) -> bool:
    return b"\x00" not in content[:sample_size]


def extract_file_from_skill_archive_bytes(zip_bytes: bytes, internal_path: str) -> bytes | None:
    if not zip_bytes:
        return None

    try:
        with io.BytesIO(zip_bytes) as stream:
            import zipfile

            if not zipfile.is_zipfile(stream):
                return None
            stream.seek(0)
            with zipfile.ZipFile(stream, "r") as zip_ref:
                namelist = zip_ref.namelist()
                if internal_path in namelist:
                    return zip_ref.read(internal_path)

                for name in namelist:
                    if name.endswith("/" + internal_path) or name == internal_path:
                        return zip_ref.read(name)
    except Exception:
        return None

    return None


def is_outputs_virtual_path(path: str) -> bool:
    """Return True when the path points to /mnt/user-data/outputs."""
    normalized = f"/{path.lstrip('/')}"
    return normalized.startswith(OUTPUTS_VIRTUAL_PREFIX)


def publish_output_bytes(thread_id: str, virtual_path: str, content: bytes) -> None:
    """Publish a generated output file through the configured outputs backend."""
    if not is_outputs_virtual_path(virtual_path):
        return
    backend = get_thread_file_backend("outputs")
    backend.put_virtual_file(thread_id, f"/{virtual_path.lstrip('/')}", content)


def publish_output_file(thread_id: str, virtual_path: str, local_path: str | Path) -> None:
    """Publish a local output file through the configured outputs backend."""
    path = Path(local_path)
    if not path.is_file():
        return
    publish_output_bytes(thread_id, virtual_path, path.read_bytes())
