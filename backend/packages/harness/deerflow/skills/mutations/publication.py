"""One-file durable publication. The PREPARED journal precedes every replace."""

from __future__ import annotations

import os
import stat

from deerflow_extension_api.host_capabilities import HostCapabilityError

from deerflow.persistence.skill_mutations.model import SkillAssetRow, SkillOperationRow, SkillOwnerRow
from deerflow.skills.mutations.assets import capture_package, open_directory_chain
from deerflow.skills.mutations.codec import operation_packages
from deerflow.skills.mutations.repository import supersede_views


def replace_main(root, content: bytes, *, operation_id: str) -> None:
    """Use the validated directory descriptor throughout; preserve mode bits."""
    directory = open_directory_chain(root)
    parent = None
    created = False
    temporary = ".host-mutation-" + operation_id
    try:
        parent = open_directory_chain(root.parent)
        original = os.stat("SKILL.md", dir_fd=directory, follow_symlinks=False)
        if not stat.S_ISREG(original.st_mode):
            raise HostCapabilityError("UNSUPPORTED_ASSET")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        created = True
        try:
            offset = 0
            while offset < len(content):
                written = os.write(fd, content[offset:])
                if written <= 0:
                    raise OSError("short publication write")
                offset += written
            # Preserve regular permissions, never propagate setuid/setgid/sticky.
            os.fchmod(fd, stat.S_IMODE(original.st_mode) & 0o777)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, "SKILL.md", src_dir_fd=parent, dst_dir_fd=directory)
        os.fsync(directory)
        os.fsync(parent)
    finally:
        try:
            if created:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
        finally:
            os.close(directory)
            if parent is not None:
                os.close(parent)


def assert_temporary_absent(root, operation_id):
    parent = open_directory_chain(root.parent)
    try:
        try:
            os.stat(".host-mutation-" + operation_id, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise HostCapabilityError("UNSUPPORTED_ASSET")
    finally:
        os.close(parent)


def durable_current(root):
    """Recovery also needs successful barriers before claiming a disk outcome."""
    directory = open_directory_chain(root)
    try:
        fd = os.open("SKILL.md", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("unsupported main file")
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(directory)
    finally:
        os.close(directory)
    parent = open_directory_chain(root.parent)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def cleanup_temporary(root, operation_id):
    parent = open_directory_chain(root.parent)
    try:
        try:
            os.unlink(".host-mutation-" + operation_id, dir_fd=parent)
            os.fsync(parent)
        except FileNotFoundError:
            pass
    finally:
        os.close(parent)


def finalize(session, operation, publication: str) -> None:
    """Apply reserved counters exactly once, while holding the owner guard."""
    asset = session.get(SkillAssetRow, operation.target_ref)
    owner = session.get(SkillOwnerRow, operation.owner_id)
    if asset is None or owner is None or asset.operation_id != operation.operation_id:
        operation.publication = "NEEDS_REPAIR"
        operation.error_code = "ASSET_IDENTITY_CHANGED"
        return
    operation.publication = publication
    if publication == "APPLIED":
        after = operation.after_revision
        asset.incarnation_id, asset.mutation_seq, asset.content_digest = after["incarnation_id"], after["mutation_seq"], after["content_digest"]
        asset.mutating = False
        owner.generation = operation.generation
        supersede_views(session, operation.owner_id, owner.generation)
        operation.error_code = None
    elif publication == "ABORTED":
        asset.mutating = False
        asset.operation_id = operation.before_operation_id
        operation.views = "SUPERSEDED"
        operation.superseded_by_generation = owner.generation
        operation.error_code = "PUBLICATION_ABORTED"
    else:
        operation.error_code = "DISK_STATE_UNKNOWN"


def resolve_prepared(repository, storage, operation_id: str) -> None:
    """Classify disk only. Recovery never replays a write."""
    with repository.sessions.begin() as session:
        operation = session.get(SkillOperationRow, operation_id)
        if operation is None or operation.publication not in {"PREPARED", "NEEDS_REPAIR"}:
            return
        try:
            operation_packages(operation)
        except ValueError:
            operation.publication = "NEEDS_REPAIR"
            operation.error_code = "BLOB_INTEGRITY_ERROR"
            return
        try:
            disk = capture_package(storage.get_custom_skill_dir(operation.name)).digest
        except (OSError, ValueError):
            disk = None
        before, after = operation.before_revision["content_digest"], operation.after_revision["content_digest"]
        publication = "ABORTED" if disk == before else "APPLIED" if disk == after else "NEEDS_REPAIR"
        if publication != "NEEDS_REPAIR":
            try:
                durable_current(storage.get_custom_skill_dir(operation.name))
            except (OSError, ValueError):
                operation.error_code = "DURABILITY_UNCONFIRMED"
                return
        finalize(session, operation, publication)
        if publication != "NEEDS_REPAIR":
            cleanup_temporary(storage.get_custom_skill_dir(operation.name), operation_id)


def publish_prepared(repository, storage, operation_id: str) -> None:
    with repository.sessions() as session:
        operation = session.get(SkillOperationRow, operation_id)
        try:
            _, package = operation_packages(operation)
        except ValueError:
            resolve_prepared(repository, storage, operation_id)
            return
        name = operation.name
    try:
        replace_main(storage.get_custom_skill_dir(name), package.main_content.encode("utf-8"), operation_id=operation_id)
    except Exception:
        # A response failure after replace must never look like ordinary refusal.
        # Journal classification distinguishes not-written, written and uncertain.
        resolve_prepared(repository, storage, operation_id)
        return
    with repository.sessions.begin() as session:
        finalize(session, session.get(SkillOperationRow, operation_id), "APPLIED")
