"""One host-owned coordination point for managed storage readers and writers."""

from __future__ import annotations

import hashlib
from contextlib import ExitStack, contextmanager, nullcontext

from deerflow_extension_api.host_capabilities import HostCapabilityError

from deerflow.skills.mutations.assets import capture_package
from deerflow.skills.mutations.repository import revision

_runtime: SkillMutationRuntime | None = None


def configure_mutation_runtime(runtime: SkillMutationRuntime | None) -> None:
    """Gateway startup/shutdown only. Recovery remains independent of plugins."""
    global _runtime
    _runtime = runtime


def runtime_for(storage) -> SkillMutationRuntime | None:
    runtime = _runtime
    return runtime if runtime is not None and getattr(storage, "user_id", None) in runtime.owners else None


def owner_is_managed(owner_id: str | None) -> bool:
    return _runtime is not None and owner_id in _runtime.owners


@contextmanager
def managed_read(storage):
    runtime = runtime_for(storage)
    if runtime is None:
        yield
        return
    from deerflow.skills.projection import skill_projection_read_lock

    with skill_projection_read_lock(storage):
        runtime.ensure_readable(storage)
        yield


def managed_global_read(storage):
    """Only enrolled owners need global -> owner ordering around view rebuilds."""
    if runtime_for(storage) is None:
        return nullcontext()
    from deerflow.skills.projection import _projection_lock, get_skill_projection_paths

    return _projection_lock(get_skill_projection_paths(storage).public.parent, timeout=5.0)


def read_optional_text(storage, path):
    """Canonical reads for existing edit/rollback audit paths, inside readiness."""
    with managed_read(storage):
        return path.read_text(encoding="utf-8") if path.exists() else None


@contextmanager
def managed_name_writes(storage, names, *, global_scope=False, timeout=None):
    """Serialize one Skill name across public state and enrolled owner writes."""
    runtime = _runtime
    owner_id = getattr(storage, "user_id", None)
    if runtime is None or not names or (not global_scope and owner_id not in runtime.owners):
        yield
        return
    from deerflow.skills.projection import _projection_lock, get_skill_projection_paths

    lock_root = get_skill_projection_paths(storage).public.parent / ".skill-mutation-names"
    with ExitStack() as stack:
        for name in sorted(set(names)):
            token = hashlib.sha256(name.encode("utf-8")).hexdigest()
            stack.enter_context(_projection_lock(lock_root / token, timeout=timeout))
        yield


@contextmanager
def managed_global_state_write(storage, name):
    """A global same-name enable toggle also changes each user's custom asset.

    Acquire before config locks: name fence -> global projection -> sorted owner guards -> DB.
    A name fence prevents concurrent same-name creation. Only owners that have
    the affected custom asset are then reserved before changing the shared flag.
    """
    runtime = _runtime
    if runtime is None:
        yield
        return
    from deerflow.skills.projection import _projection_lock, get_skill_projection_paths, skill_projection_read_lock
    from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage

    with managed_name_writes(storage, (name,), global_scope=True, timeout=5.0), _projection_lock(get_skill_projection_paths(storage).public.parent, timeout=5.0), ExitStack() as stack:
        storages = []
        for owner in sorted(runtime.owners):
            scoped = UserScopedSkillStorage(owner, host_path=str(storage.get_skills_root_path()))
            if not scoped.get_custom_skill_file(name).exists():
                continue
            stack.enter_context(skill_projection_read_lock(scoped))
            runtime.ensure_readable(scoped)
            if scoped.get_custom_skill_file(name).exists():
                storages.append(scoped)
        for scoped in storages:
            stack.enter_context(runtime.writer(scoped, (name,)))
        yield


class SkillMutationRuntime:
    def __init__(self, repository, *, owners: frozenset[str]):
        self.repository = repository
        self.owners = owners
        self.recover_locked = None

    def ensure_readable(self, storage):
        """Caller owns the owner guard; lazy recovery never rebuilds views."""
        try:
            self.repository.check_readable(storage.user_id)
        except HostCapabilityError as exc:
            if exc.code != "NEEDS_REPAIR" or self.recover_locked is None:
                raise
            self.recover_locked(storage)
            self.repository.check_readable(storage.user_id)

    @staticmethod
    def state(storage, name):
        root = storage.get_custom_skill_dir(name)
        exists = root.exists()
        if not exists:
            return "", False, False
        try:
            digest = capture_package(root).digest
        except ValueError:
            # Old APIs retain their broader asset support. Such assets cannot
            # enter the new automatic API; each legacy write invalidates CAS.
            import uuid

            digest = "unsupported-" + uuid.uuid4().hex
        from deerflow.config.extensions_config import ExtensionsConfig

        enabled = storage.get_skill_enabled_state(name) and ExtensionsConfig.from_file().is_skill_enabled(name, "custom")
        return digest, enabled, True

    def read_revision(self, storage, name):
        from deerflow.skills.projection import skill_projection_read_lock

        with skill_projection_read_lock(storage):
            digest, enabled, exists = self.state(storage, name)
            row = self.repository.observe(storage.user_id, name, digest, enabled, exists=exists)
            if not exists:
                raise HostCapabilityError("NOT_FOUND_OR_FORBIDDEN")
            return revision(row)

    @contextmanager
    def writer(self, storage, names):
        # The caller already owns the projection/user guard, on one worker.
        self.ensure_readable(storage)
        for name in names:
            digest, enabled, exists = self.state(storage, name)
            self.repository.observe(storage.user_id, name, digest, enabled, exists=exists, mark_mutating=True)
        try:
            yield
        except BaseException:
            # Keep the marker: the next guarded access must conservatively
            # advance the version even if a failed writer restored old bytes.
            raise
        else:
            for name in names:
                digest, enabled, exists = self.state(storage, name)
                self.repository.finish_writer(storage.user_id, name, digest, enabled, exists=exists)


@contextmanager
def managed_writer(storage, names):
    runtime = runtime_for(storage)
    if runtime is None:
        yield
    else:
        with runtime.writer(storage, names):
            yield
