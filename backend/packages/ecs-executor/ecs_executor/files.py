"""Bounded declared input snapshots and safe persistent output collection."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import stat
from pathlib import Path, PurePosixPath


def relative_file(name: str) -> str:
    if not isinstance(name, str) or len(name) > 255 or re.fullmatch(r"[a-zA-Z0-9_./-]+", name) is None or any(part in {"", ".", ".."} for part in name.split("/")) or PurePosixPath(name).is_absolute():
        raise ValueError("Invalid declared relative file")
    return name


def decode_inputs(files: dict[str, str], *, limit: int = 131072) -> dict[str, bytes]:
    if len(files) > 64:
        raise ValueError("Too many declared input files")
    result = {}
    for name, encoded in files.items():
        relative_file(name)
        try:
            result[name] = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise ValueError("Invalid input snapshot") from None
    if sum(map(len, result.values())) > limit:
        raise ValueError("Input snapshots exceed size limit")
    return result


def prepare(root: Path, job):
    directory = root / job["id"]
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    inputs, outputs = directory / "inputs", directory / "outputs"
    inputs.mkdir(mode=0o755, exist_ok=True)
    outputs.mkdir(mode=0o777, exist_ok=True)
    outputs.chmod(0o777)
    for name, payload in decode_inputs(job["spec"]["input_files"], limit=job.get("max_input_bytes", 131072)).items():
        path = inputs / name
        path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        path.write_bytes(payload)
        path.chmod(0o444)
    return inputs.resolve(), outputs.resolve()


def collect(directory: Path, *, limit: int) -> dict[str, bytes]:
    """Never follow symlinks, devices or multiply-linked container outputs."""
    result, total = {}, 0
    for parent, dirs, names in os.walk(directory, followlinks=False):
        for name in dirs:
            if not stat.S_ISDIR((Path(parent) / name).lstat().st_mode):
                raise ValueError("Unsafe output directory")
        for name in names:
            path = Path(parent) / name
            relative = relative_file(path.relative_to(directory).as_posix())
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Unsafe output file")
            total += info.st_size
            if total > limit or len(result) >= 256:
                raise ValueError("Output files exceed profile limit")
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                with os.fdopen(fd, "rb") as stream:
                    actual = os.fstat(stream.fileno())
                    if (actual.st_dev, actual.st_ino) != (info.st_dev, info.st_ino):
                        raise ValueError("Output changed during collection")
                    payload = stream.read(limit + 1)
                if len(payload) != info.st_size:
                    raise ValueError("Output changed during collection")
                result[relative] = payload
            except BaseException:
                raise
    return result


def manifest(files):
    return [{"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()} for name, payload in sorted(files.items())]
