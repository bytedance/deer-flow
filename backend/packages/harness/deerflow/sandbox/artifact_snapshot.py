"""Bounded, descriptor-confined snapshots over a sandbox's command transport."""

import base64
import hashlib
import json
import logging
import shlex
import uuid
from pathlib import PurePosixPath
from typing import Any

from deerflow_extension_api import AgentRunError

from deerflow.sandbox.sandbox import Sandbox

MAX_BYTES = 2 * 1024 * 1024
CHUNK_BYTES = 49152
logger = logging.getLogger(__name__)

# The same POSIX protocol runs in every supported remote provider. Each command
# is below Linux's per-argument limit, including JSON/base64 and shell quoting.
_SCRIPT = r"""
import base64, hashlib, json, os, stat, sys
p = json.loads(sys.argv[1])
limit = p.get('max_bytes', 2097152)
directory = None
def stamp(s):
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]
def opened(name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    s = os.fstat(fd)
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_size > limit:
        os.close(fd)
        raise ValueError('Unsafe or oversized file')
    return os.fdopen(fd, 'rb'), s
def digest(name):
    source, before = opened(name)
    with source:
        data = source.read(limit + 1)
        if len(data) > limit or stamp(before) != stamp(os.fstat(source.fileno())):
            raise ValueError('File changed during snapshot')
        return hashlib.sha256(data).hexdigest(), len(data)
try:
    if os.name != 'posix':
        raise ValueError('POSIX required')
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    parts = [v for v in p['root'].split('/') if v]
    if p.get('area'):
        parts += [p['area']] + p.get('name', '').split('/')[:-1]
    for part in parts:
        if p['op'] in ('append', 'publish'):
            try:
                os.mkdir(part, 0o755, dir_fd=directory)
            except FileExistsError:
                pass
        nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
        os.close(directory)
        directory = nxt
    op = p['op']
    name = p.get('name', '').rsplit('/', 1)[-1]
    result = {'ok': True}
    if op == 'append':
        data = base64.b64decode(p['data'], validate=True)
        flags = os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        flags |= (os.O_CREAT | os.O_EXCL) if p['offset'] == 0 else os.O_APPEND
        fd = os.open(p['temporary'], flags, 0o600, dir_fd=directory)
        with os.fdopen(fd, 'ab') as target:
            s = os.fstat(target.fileno())
            if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_size != p['offset'] or s.st_size + len(data) > limit:
                raise ValueError('Staging file changed')
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
    elif op == 'publish':
        if digest(p['temporary']) != (p['sha256'], p['size']):
            raise ValueError('Staging bytes changed')
        try:
            os.link(p['temporary'], name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        except FileExistsError:
            pass
        os.unlink(p['temporary'], dir_fd=directory)
        if digest(name) != (p['sha256'], p['size']):
            raise ValueError('Imported artifact was changed; existing file retained')
    elif op == 'verify':
        if digest(name) != (p['sha256'], p['size']):
            raise ValueError('Imported artifact was changed; existing file retained')
    elif op == 'read':
        source, before = opened(name)
        with source:
            if p.get('stamp') is not None and p['stamp'] != stamp(before):
                raise ValueError('Output changed during capture')
            source.seek(p['offset'])
            data = source.read(49152)
            if stamp(before) != stamp(os.fstat(source.fileno())):
                raise ValueError('Output changed during capture')
        result.update(data=base64.b64encode(data).decode('ascii'), stamp=stamp(before), size=before.st_size)
    elif op == 'cleanup':
        try:
            os.unlink(p['temporary'], dir_fd=directory)
        except FileNotFoundError:
            pass
    elif op != 'probe':
        raise ValueError('Unknown snapshot operation')
except (OSError, ValueError) as exc:
    result = {'error': str(exc)}
finally:
    if directory is not None:
        os.close(directory)
print(json.dumps(result))
"""


def _call(sandbox: Sandbox, op: str, *, area: str | None = None, name: str = "", **values: Any) -> dict[str, Any]:
    root = getattr(sandbox, "artifact_root", None)
    if not isinstance(root, str) or not root.startswith("/") or ".." in PurePosixPath(root).parts:
        raise AgentRunError(422, "Sandbox does not support safe artifact snapshots")
    if name and (str(PurePosixPath(name)) != name or name.startswith("/") or ".." in PurePosixPath(name).parts or "\\" in name or any(ord(c) < 32 for c in name)):
        raise AgentRunError(422, "Invalid artifact snapshot path")
    payload = json.dumps({"root": root, "op": op, "area": area, "name": name, **values})
    output = sandbox.execute_command("python3 -I -c " + shlex.quote(_SCRIPT) + " " + shlex.quote(payload), timeout=30)
    try:
        result = json.loads(output)
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise ValueError("Snapshot rejected")
    except (ValueError, TypeError) as exc:
        # Never echo remote output, paths or shell diagnostics into task errors.
        raise AgentRunError(422, "Remote artifact unavailable, changed or unsafe") from exc
    return result


def validate_snapshot_support(sandbox: Sandbox) -> None:
    """Probe the declared POSIX/Python 3 root; reject unsafe support with 422."""
    _call(sandbox, "probe")


def publish_snapshot(sandbox: Sandbox, filename: str, content: bytes, *, area: str = "uploads", max_bytes: int = MAX_BYTES) -> None:
    """Publish bounded bytes, reusing only identical regular files.

    Unsafe paths, changed existing files or rejected remote operations raise
    AgentRunError(422). Existing edits are retained; staging cleanup is attempted
    even on failure. Run this synchronous command sequence off the event loop.
    """
    if area not in {"uploads", "outputs"} or not isinstance(content, bytes) or len(content) > max_bytes:
        raise AgentRunError(422, "Artifact exceeds the snapshot size limit")
    temporary = ".artifact-" + uuid.uuid4().hex + ".part"
    try:
        for offset in range(0, max(1, len(content)), CHUNK_BYTES):
            _call(sandbox, "append", area=area, max_bytes=max_bytes, name=filename, temporary=temporary, offset=offset, data=base64.b64encode(content[offset : offset + CHUNK_BYTES]).decode("ascii"))
        _call(sandbox, "publish", area=area, max_bytes=max_bytes, name=filename, temporary=temporary, sha256=hashlib.sha256(content).hexdigest(), size=len(content))
    finally:
        try:
            _call(sandbox, "cleanup", area=area, name=filename, temporary=temporary)
        except Exception:
            logger.warning("Failed to clean remote artifact staging file", exc_info=True)


def verify_snapshot(sandbox: Sandbox, filename: str, sha256: str, size: int) -> None:
    """Check an uploads file's hash/size, raising 422 for unsafe or changed bytes."""
    _call(sandbox, "verify", area="uploads", name=filename, sha256=sha256, size=size)


def read_snapshot(sandbox: Sandbox, relative_path: str, *, max_bytes: int = MAX_BYTES) -> bytes:
    """Read bounded output bytes with file identity checked across chunks.

    Raise AgentRunError(422) for unsafe paths, changed files or invalid remote
    replies. Run this synchronous command sequence off the event loop.
    """
    content, stamp = bytearray(), None
    while True:
        result = _call(sandbox, "read", area="outputs", name=relative_path, offset=len(content), stamp=stamp, max_bytes=max_bytes)
        try:
            data = base64.b64decode(result["data"], validate=True)
            size = result["size"]
            current_stamp = result["stamp"]
            valid = type(size) is int and 0 <= size <= max_bytes and len(data) <= CHUNK_BYTES and len(content) + len(data) <= size
            if not valid or (stamp is not None and stamp != current_stamp) or (not data and len(content) != size):
                raise ValueError("Invalid remote snapshot")
        except (ValueError, KeyError, TypeError) as exc:
            raise AgentRunError(422, "Invalid remote artifact snapshot") from exc
        stamp = current_stamp
        content.extend(data)
        if len(content) == size:
            return bytes(content)
