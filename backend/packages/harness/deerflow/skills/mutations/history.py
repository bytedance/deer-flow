"""Bounded best-effort metadata mirror; the operation database is authoritative."""

import json
import os
import stat
from collections import defaultdict
from dataclasses import asdict

from deerflow.skills.mutations.assets import open_directory_chain

MAX_HISTORY_BYTES = 8 * 1024 * 1024
MAX_HISTORY_LINE_BYTES = 64 * 1024


def mirror_operations(storage, operations):
    """Caller owns the owner guard. Never copy retained Skill body blobs here.

    Replay at most the latest 100 operations per owner. An oversized/malformed
    history is left untouched, since bounded work cannot prove deduplication.
    """
    grouped = defaultdict(list)
    for operation in operations:
        grouped[operation.name].append(operation)
    if not grouped:
        return
    custom = open_directory_chain(storage.get_custom_skill_dir(next(iter(grouped))).parent)
    try:
        try:
            os.mkdir(".history", 0o700, dir_fd=custom)
        except FileExistsError:
            pass
        directory = os.open(".history", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=custom)
    finally:
        os.close(custom)
    try:
        for name, items in grouped.items():
            storage.validate_skill_name(name)
            fd = os.open(name + ".jsonl", os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_HISTORY_BYTES:
                    continue
                seen, pending, total = set(), b"", 0
                valid = True
                while chunk := os.read(fd, min(65536, MAX_HISTORY_BYTES + 1 - total)):
                    total += len(chunk)
                    if total > MAX_HISTORY_BYTES:
                        valid = False
                        break
                    lines = (pending + chunk).split(b"\n")
                    pending = lines.pop()
                    for line in lines:
                        if len(line) > MAX_HISTORY_LINE_BYTES:
                            valid = False
                            break
                        if not line.strip():
                            continue
                        try:
                            record = json.loads(line)
                            if not isinstance(record, dict):
                                raise ValueError
                            identifier = record.get("operation_id")
                            if isinstance(identifier, str):
                                seen.add(identifier)
                        except (ValueError, UnicodeError):
                            valid = False
                            break
                    if not valid or len(pending) > MAX_HISTORY_LINE_BYTES:
                        valid = False
                        break
                if not valid or pending.strip() or os.fstat(fd).st_size != before.st_size:
                    continue
                records = []
                for operation in reversed(items):
                    if operation.operation_id in seen:
                        continue
                    records.append(
                        json.dumps(
                            {
                                "operation_id": operation.operation_id,
                                "action": "host_revert" if operation.reverts_operation_id else "host_commit",
                                "publication": operation.publication,
                                "prev_revision": asdict(operation.before_revision),
                                "new_revision": asdict(operation.after_revision),
                                "scope": "main-file-only",
                                "file_path": "SKILL.md",
                            },
                            separators=(",", ":"),
                        ).encode()
                        + b"\n"
                    )
                if total + sum(map(len, records)) > MAX_HISTORY_BYTES:
                    continue
                for record in records:
                    if os.write(fd, record) != len(record):
                        raise OSError("incomplete history mirror")
                if records:
                    os.fsync(fd)
                    os.fsync(directory)
            finally:
                os.close(fd)
    finally:
        os.close(directory)
