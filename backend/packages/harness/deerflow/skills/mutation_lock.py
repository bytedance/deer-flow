"""The lock every custom-skill mutation holds around read → write → history.

A mutation reads the content it replaces, writes the new content and appends a
history record that names both. Two mutations of one owner must not interleave
those steps, or one overwrites the other while recording a stale predecessor,
and the overwritten revision drops out of the history chain that rollback
walks. The Gateway skill routes and the agent's ``skill_manage`` tool both
mutate custom skills, so they hold this one lock, in-process and across
Gateway processes that share the home volume.

The lock is scoped to the owning user's storage: the critical section includes
``write_custom_skill``'s projection rebuild, which copies that user's whole
skill tree (including a large linked package) and waits on the user's
projection lock. A process-wide lock would queue every other user's mutation
behind one user's slow filesystem work, even though their skill trees,
histories and projection roots are disjoint. Keying on the resolved root, not
the user_id string and not one lock per storage instance, keeps a single lock
per user when a hot-reloaded config or a later request builds a fresh storage
object.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from deerflow.skills.storage.skill_storage import SkillStorage
from deerflow.skills.types import SkillCategory

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]
    import msvcrt

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def custom_skill_mutation_lock(storage: SkillStorage) -> threading.Lock:
    """Return the process-local part of the owning user's mutation lock."""
    scope = _mutation_scope(storage)
    with _locks_guard:
        return _locks.setdefault(scope, threading.Lock())


def _mutation_scope(storage: SkillStorage) -> str:
    """The storage scope whose custom-skill mutations must serialize together.

    User-scoped storage reports the canonical root its mutations touch, so two
    users never share a lock while two storage objects for one user always do.
    Legacy local storage uses its global custom root. Non-filesystem test
    doubles have one process-local scope.
    """
    get_user_custom_root = getattr(storage, "get_user_custom_root", None)
    if callable(get_user_custom_root):
        return str(Path(get_user_custom_root()).resolve())
    get_skills_root_path = getattr(storage, "get_skills_root_path", None)
    if callable(get_skills_root_path):
        return str((Path(get_skills_root_path()) / SkillCategory.CUSTOM.value).resolve())
    return "global"


@contextmanager
def custom_skill_mutation(storage: SkillStorage) -> Iterator[None]:
    """Hold the owner's mutation lock across threads and peer Gateway processes.

    Blocking: take it in a worker thread, and run the whole read → write →
    history sequence in that same worker. Hold it only for that sequence, not
    across a security scan: it queues every other mutation of the owner's
    skills. Whatever a scan assumed about the stored skill has to be re-read
    under the lock.

    Use a stable sidecar outside the skill tree, distinct from projection's
    lock: write/delete acquire the projection lock while this one is held.
    Acquiring that same file lock twice would deadlock on POSIX.
    """
    with custom_skill_mutation_lock(storage):
        scope = _mutation_scope(storage)
        if scope == "global":
            yield
            return
        root = Path(scope)
        lock_path = root.parent / f".{root.name}.mutation.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a", encoding="utf-8") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file, fcntl.LOCK_EX)
            else:  # pragma: no cover - Windows
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)
                else:  # pragma: no cover - Windows
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
