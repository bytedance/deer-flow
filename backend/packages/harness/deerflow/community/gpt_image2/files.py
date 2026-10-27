"""Thread-confined image I/O; user-controlled links are never followed."""

import io
import os
import stat
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from uuid import uuid4

from langchain_core.tools import ToolException
from PIL import Image

MAX_INPUT_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_777_216


@contextmanager
def directory(root: Path, parts=(), *, create=False):
    # This deployment's Gateway runs on Linux. Refuse unsafe fallbacks on hosts
    # without descriptor-relative traversal, even if the API itself is reachable.
    if os.open not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW"):
        raise ToolException("GPT Image 2 requires a POSIX Gateway for isolated file access")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, mode=0o755, dir_fd=fd)
                except FileExistsError:
                    pass
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


def image_metadata(data: bytes, *, png_only=False):
    try:
        with Image.open(io.BytesIO(data)) as picture:
            if picture.format not in ({"PNG"} if png_only else {"PNG", "JPEG", "WEBP"}):
                raise ValueError("Unsupported image format")
            if picture.width * picture.height > MAX_IMAGE_PIXELS:
                raise ValueError("Image too large")
            result = (picture.format, picture.size, "A" in picture.getbands())
            picture.verify()
        return result
    except Exception:
        raise ToolException("Invalid or oversized image; use PNG, JPEG or WebP") from None


def read_reference(root: Path, path: str):
    prefix = "/mnt/user-data/"
    if not path.startswith(prefix) or "\\" in path:
        raise ToolException("Reference images must be files in this conversation's /mnt/user-data directory")
    parts = PurePosixPath(path[len(prefix) :]).parts
    if len(parts) < 2 or parts[0] not in {"uploads", "outputs", "workspace"} or any(p in {"..", "."} for p in parts):
        raise ToolException("Invalid reference image path")
    try:
        with directory(root, parts[:-1]) as parent:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, "rb") as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_INPUT_BYTES:
                    raise ValueError("Unsafe input")
                data = handle.read(MAX_INPUT_BYTES + 1)
                if len(data) > MAX_INPUT_BYTES:
                    raise ValueError("Oversized input")
        kind, size, alpha = image_metadata(data)
        return (parts[-1], data, {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[kind]), size, alpha
    except (OSError, ValueError):
        raise ToolException("Reference image is missing, too large, or not a safe file in this conversation") from None


def prepare_outputs(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with directory(root, ("outputs",), create=True):
        pass


def save_image(root: Path, data: bytes) -> str:
    image_metadata(data, png_only=True)
    name = f"gpt-image2-{uuid4().hex}.png"
    try:
        with directory(root, ("outputs",)) as parent:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=parent)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
            except BaseException:
                os.unlink(name, dir_fd=parent)
                raise
    except OSError:
        raise ToolException("Could not save image in this conversation's outputs") from None
    return f"/mnt/user-data/outputs/{name}"
