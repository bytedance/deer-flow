"""Offline, restartable migration of sandbox files into mountable per-user roots.

Run with the Gateway stopped. Conversation metadata and skill projections never
enter the writable data mount. Existing files are moved, never overwritten.
"""

from contextlib import contextmanager
from pathlib import Path

from deerflow.config.paths import Paths

LAYOUT_MARKER = ".user-sandbox-data-v1"


@contextmanager
def _migration_lock(path):
    from .aio_sandbox_provider import _lock_file_exclusive, _open_lock_file, _unlock_file

    with _open_lock_file(path) as stream:
        _lock_file_exclusive(stream)
        try:
            yield
        finally:
            _unlock_file(stream)


def migrate_user_data(base_dir: str | Path) -> int:
    base = Path(base_dir).resolve(strict=True)
    paths = Paths(base)
    moved = 0
    with _migration_lock(base / ".user-sandbox-data-migration.lock"):
        if (base / LAYOUT_MARKER).exists():
            return 0
        users = base / "users"
        operations = []
        for user in sorted(users.iterdir()) if users.is_dir() else []:
            threads = user / "threads"
            if not threads.is_dir():
                continue
            for thread in sorted(threads.iterdir()):
                if not thread.is_dir():
                    continue
                paths.thread_dir(thread.name, user_id=user.name)  # Validate names.
                for source_name, target_name in (("user-data", "sandbox-data"), ("acp-workspace", "sandbox-acp")):
                    source = thread / source_name
                    target = user / target_name / thread.name
                    # Validate resolved absolute paths before any directory move.
                    for candidate in (source, target):
                        candidate.resolve().relative_to(base)
                    if source.is_symlink() or target.is_symlink():
                        raise RuntimeError("Sandbox storage migration refuses symlink roots")
                    if source.exists():
                        if target.exists():
                            raise RuntimeError(f"Sandbox storage has both source and destination for {user.name}/{thread.name}")
                        operations.append((source, target))
        for source, target in operations:
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
            moved += 1
        # A failed migration can resume: previously moved sources are absent.
        (base / LAYOUT_MARKER).write_text("1\n", encoding="utf-8")
    return moved
