"""Native file snapshots/publication under owner row locks and no-follow dirfds."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, select

from deerflow.config.paths import Paths, make_safe_user_id
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from ecs_executor.files import relative_file


@contextmanager
def directory_at(root_fd: int, components, *, create=False):
    """Pin every ancestor; subsequent operations cannot follow replaced names."""
    fd = os.dup(root_fd)
    try:
        for component in components:
            if create:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def read_at(root_fd, name, limit):
    parts = relative_file(name).split("/")
    with directory_at(root_fd, parts[:-1]) as parent:
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
                raise ValueError("Unsafe or oversized native file")
            content = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            if len(content) > limit or len(content) != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("Native file changed during snapshot")
            return content


def write_at(root_fd, name, content):
    parts = relative_file(name).split("/")
    with directory_at(root_fd, parts[:-1], create=True) as parent:
        fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(parent)


def remove_tree_at(parent_fd, name):
    """Clean only our private staged directory, without resolving host paths."""
    with directory_at(parent_fd, [name]) as fd:
        for child in os.listdir(fd):
            if stat.S_ISDIR(os.stat(child, dir_fd=fd, follow_symlinks=False).st_mode):
                remove_tree_at(fd, child)
            else:
                os.unlink(child, dir_fd=fd)
    os.rmdir(name, dir_fd=parent_fd)


class WorkspacePublication:
    def __init__(self, *, workspace_root: Path, metadata_database_url: str):
        self.root = Path(workspace_root).resolve()
        self.paths = Paths(self.root)
        self.engine = create_engine(metadata_database_url)

    @contextmanager
    def authorized_root(self, job, path, *, create=False):
        with self.engine.connect() as connection:
            if self.engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                connection.begin()
            try:
                query = select(ThreadMetaRow.user_id, ThreadMetaRow.incarnation).where(ThreadMetaRow.thread_id == job["thread_id"])
                if self.engine.dialect.name == "postgresql":
                    query = query.with_for_update()
                owner = connection.execute(query).first()
                if owner is None or owner.user_id != job["user_id"] or owner.incarnation != job["incarnation"]:
                    raise ValueError("Native file access denied: owner/incarnation no longer matches")
                self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
                root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    with directory_at(root_fd, path.relative_to(self.root).parts, create=create) as fd:
                        yield fd
                finally:
                    os.close(root_fd)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def snapshot(self, identity, references, *, limit):
        if len(references) > 64:
            raise ValueError("Too many declared input references")
        root = self.paths.sandbox_user_data_dir(identity["thread_id"], user_id=make_safe_user_id(identity["user_id"]))
        result = {}
        with self.authorized_root(identity, root) as fd:
            for name, reference in references.items():
                relative_file(name)
                if set(reference) != {"path", "sha256"} or re.fullmatch(r"[0-9a-f]{64}", reference["sha256"]) is None:
                    raise ValueError("Native reference requires relative path and SHA256 digest")
                relative_file(reference["path"])
                if reference["path"].split("/")[0] not in {"uploads", "workspace", "outputs"}:
                    raise ValueError("Native reference must name current thread user-data")
                payload = read_at(fd, reference["path"], limit)
                if hashlib.sha256(payload).hexdigest() != reference["sha256"]:
                    raise ValueError("Native input digest mismatch")
                limit -= len(payload)
                result[name] = payload
        return result

    def publish(self, job, payload: bytes, files: dict[str, bytes]) -> str:
        outputs = self.paths.sandbox_outputs_dir(job["thread_id"], user_id=make_safe_user_id(job["user_id"]))
        for name in files:
            relative_file(name)
        with self.authorized_root(job, outputs, create=True) as outputs_fd:
            try:
                os.stat(job["id"], dir_fd=outputs_fd, follow_symlinks=False)
            except FileNotFoundError:
                temporary = ".ecs-publication-" + uuid.uuid4().hex
                os.mkdir(temporary, mode=0o700, dir_fd=outputs_fd)
                try:
                    with directory_at(outputs_fd, [temporary]) as staged_fd:
                        write_at(staged_fd, "result.json", payload)
                        if files:
                            with directory_at(staged_fd, ["files"], create=True) as files_fd:
                                for name, content in files.items():
                                    write_at(files_fd, name, content)
                                os.fsync(files_fd)
                        os.fsync(staged_fd)
                    os.rename(temporary, job["id"], src_dir_fd=outputs_fd, dst_dir_fd=outputs_fd)
                    os.fsync(outputs_fd)
                finally:
                    try:
                        remove_tree_at(outputs_fd, temporary)
                    except FileNotFoundError:
                        pass
            else:
                with directory_at(outputs_fd, [job["id"]]) as published_fd:
                    if read_at(published_fd, "result.json", len(payload)) != payload:
                        raise ValueError("Native publication identity/integrity conflict")
                    if files:
                        with directory_at(published_fd, ["files"]) as files_fd:
                            for name, content in files.items():
                                if read_at(files_fd, name, len(content)) != content:
                                    raise ValueError("Native publication identity/integrity conflict")
        return f"/api/threads/{job['thread_id']}/artifacts/mnt/user-data/outputs/{job['id']}/result.json"
