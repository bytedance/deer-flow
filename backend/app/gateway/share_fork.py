"""Import a share into a fresh owner-scoped default-agent conversation."""

import asyncio
import logging
import os
import uuid
from collections.abc import Mapping
from contextlib import asynccontextmanager

from deerflow_extension_api import AgentRunError
from fastapi import HTTPException, Request
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Overwrite

from app.gateway.deps import get_checkpointer, get_run_event_store, get_run_manager, get_thread_store
from app.gateway.extension_artifacts import snapshot_sandbox
from app.gateway.history_seed import reserve_history_seed, write_history_seed
from app.gateway.internal_auth import get_trusted_internal_owner_user_id
from app.gateway.persistent_writes import run_drained_write
from app.gateway.services import build_checkpoint_state_mutation_accessor
from app.gateway.share_snapshot import MAX_SHARE_FILE_BYTES, OUTPUT_PREFIX, artifact_path
from app.gateway.utils import sanitize_log_param
from deerflow.config.paths import get_paths
from deerflow.persistence.thread_meta import ThreadMetaStore
from deerflow.persistence.thread_shares.sql import ThreadShareRepository
from deerflow.runtime import ConflictError, ThreadOperationKind
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.goal import goal_thread_lock
from deerflow.runtime.journal import build_branch_history_seed_events
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.artifact_snapshot import publish_snapshot
from deerflow.utils.file_io import run_file_io
from deerflow.utils.messages import IMPORTED_HISTORY_KEY

logger = logging.getLogger(__name__)

#: Thread metadata, written only by this module (the thread routes strip
#: client copies): the copy's history is fully imported, and its copied
#: messages carry :data:`IMPORTED_HISTORY_KEY`.
SHARE_IMPORT_COMPLETE_KEY = "share_import_complete"
SHARE_IMPORT_HISTORY_MARKED_KEY = "share_import_history_marked"

# The descriptor-confined writer below is POSIX-only. Capture already refuses
# the same artifacts off POSIX, so import answers with that contract instead of
# surfacing a 500 from a partial write.
_ARTIFACT_IMPORT_SUPPORTED = os.name == "posix"


def _write_fork_files(owner: str, thread_id: str, artifacts: list[dict]) -> None:
    """A fresh UUID directory, descriptor-confined descendants and exclusive files."""
    root = get_paths().sandbox_outputs_dir(thread_id, user_id=owner)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(root, directory_flags)
    try:
        for artifact in artifacts:
            parts = artifact_path(artifact["path"]).split("/")
            directory = os.dup(root_fd)
            try:
                for part in parts[:-1]:
                    try:
                        os.mkdir(part, 0o700, dir_fd=directory)
                    except FileExistsError:
                        pass
                    following = os.open(part, directory_flags, dir_fd=directory)
                    os.close(directory)
                    directory = following
                    os.fchmod(directory, 0o777)
                fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                with os.fdopen(fd, "wb") as target:
                    target.write(artifact["content"])
                    target.flush()
                    os.fchmod(target.fileno(), 0o666)
                    os.fsync(target.fileno())
            finally:
                os.close(directory)
        # The bind mount is writable by the sandbox UID even when Gateway runs
        # under a different UID or a restrictive umask.
        os.fchmod(root_fd, 0o777)
    finally:
        os.close(root_fd)


@asynccontextmanager
async def _reserve_import(request: Request, thread_id: str, owner: str):
    if isinstance(get_run_event_store(request), DbRunEventStore):
        async with reserve_history_seed(request, thread_id) as reservation:
            yield reservation
    else:
        async with get_run_manager(request).reserve_thread_operation(thread_id, kind=ThreadOperationKind.checkpoint_write, user_id=owner):
            yield None


async def fork_share(request: Request, repo: ThreadShareRepository, token: str, request_id: str) -> dict:
    share = await repo.get_public(token)
    if share is None:
        raise HTTPException(404, "Share unavailable")
    if share["artifacts"] and not _ARTIFACT_IMPORT_SUPPORTED:
        raise AgentRunError(422, "Importing a share with artifacts requires POSIX")
    owner = get_effective_user_id()
    thread_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"deerflow-share:{owner}:{share['share_id']}:{request_id}"))
    threads = get_thread_store(request)
    async with goal_thread_lock(thread_id):
        existing = await threads.get(thread_id, user_id=owner)
        if existing is not None:
            if existing.get("metadata", {}).get(SHARE_IMPORT_COMPLETE_KEY) is True:
                return {"thread_id": thread_id}
            raise HTTPException(409, "The previous import did not finish; create a new copy")
        artifacts = []
        for descriptor in share["artifacts"]:
            artifact = await repo.get_artifact(token, descriptor["path"])
            if artifact is None:
                raise HTTPException(404, "Share unavailable")
            artifacts.append(artifact)
        # Tool results become ordinary historical assistant text. The new thread
        # inherits no tool execution, system prompt, Agent, project or auth grants.
        # The import mark keeps the copied turns out of the visitor's memory.
        messages = []
        for item in share["snapshot"]["messages"]:
            content = item["content"]
            if item["type"] == "tool":
                content = f"{item['name']}:\n{content}"
            cls = HumanMessage if item["type"] == "human" else AIMessage
            messages.append(cls(content=content, id=str(uuid.uuid4()), additional_kwargs={IMPORTED_HISTORY_KEY: "share"}))
        title = str(share["snapshot"]["title"])[:256]
        # Recheck after loading all bytes, before creating any new workspace state.
        if await repo.get_public(token) is None:
            raise HTTPException(404, "Share unavailable")
        async with _reserve_import(request, thread_id, owner) as reservation:
            existing = await threads.get(thread_id, user_id=owner)
            if existing is not None:
                if existing.get("metadata", {}).get(SHARE_IMPORT_COMPLETE_KEY) is True:
                    return {"thread_id": thread_id}
                raise HTTPException(409, "The previous import did not finish; create a new copy")
            created = False
            try:
                record = await threads.create(thread_id, user_id=owner, display_name=title)
                created = True
                if artifacts:
                    await run_drained_write("Import shared artifacts", _write_fork_files, (), owner, thread_id, artifacts)
                    async with snapshot_sandbox(request, owner, thread_id) as sandbox:
                        if sandbox is not None:
                            for artifact in artifacts:
                                await run_file_io(publish_snapshot, sandbox, artifact["path"], artifact["content"], area="outputs", max_bytes=MAX_SHARE_FILE_BYTES)
                accessor, config = build_checkpoint_state_mutation_accessor(request, thread_id=thread_id, as_node="branch")
                await accessor.aupdate(config, {"messages": Overwrite(messages), "title": title, "artifacts": Overwrite([OUTPUT_PREFIX + a["path"] for a in artifacts])}, as_node="branch")
                events = build_branch_history_seed_events(messages, thread_id=thread_id, run_id_prefix=f"branch-seed-{thread_id}", parent_thread_id=thread_id)
                await write_history_seed(request, events, reservation=reservation, seed_kind="branch", thread=record)
                await threads.update_metadata(thread_id, {SHARE_IMPORT_COMPLETE_KEY: True, SHARE_IMPORT_HISTORY_MARKED_KEY: True}, user_id=owner)
            except Exception:
                if created:
                    # Keep admission until rollback finishes, so a failed import
                    # cannot be continued while its files/checkpoints are removed.
                    await get_checkpointer(request).adelete_thread(thread_id)
                    await get_run_event_store(request).delete_by_thread(thread_id, user_id=owner)
                    await run_drained_write("Remove failed share import", get_paths().delete_thread_dir, (), thread_id, user_id=owner)
                    await threads.delete(thread_id, user_id=owner)
                raise
        return {"thread_id": thread_id}


async def _imported_message_ids(request: Request, accessor, config: dict) -> set[str] | None:
    """IDs of the history the import wrote as the thread's root checkpoint.

    ``None`` when the root is gone or unreadable: guessing from a later
    checkpoint would mark the owner's own turns as someone else's.
    """
    tuples = [item async for item in get_checkpointer(request).alist(config)]
    if not tuples or tuples[-1].parent_config is not None:
        return None
    root_id = tuples[-1].config["configurable"]["checkpoint_id"]
    snapshot = await accessor.aget({**config, "configurable": {**config["configurable"], "checkpoint_id": root_id}})
    messages = snapshot.values.get("messages") if isinstance(snapshot.values, dict) else None
    ids = {message.id for message in messages or () if getattr(message, "id", None)}
    return ids or None


def is_share_copy_metadata(metadata: object) -> bool:
    """Return whether thread *metadata* records a completed share import."""
    return isinstance(metadata, Mapping) and metadata.get(SHARE_IMPORT_COMPLETE_KEY) is True


def resolve_share_copy(admission_result: bool | None, metadata_record: Mapping | None, thread_id: str) -> bool:
    """Decide whether memory capture treats a run's thread as a share copy.

    ``admission_result`` is what :func:`prepare_share_copy_run` returned;
    ``None`` means its read failed, and the run's later thread-metadata record
    decides. When neither is available the thread counts as a copy: on an
    ordinary thread that adds one DeerMem note for this run, while the
    opposite mistake records a sharer's details as the visitor's.
    """
    if admission_result is not None:
        return admission_result
    if metadata_record is not None:
        return is_share_copy_metadata(metadata_record.get("metadata"))
    logger.warning("Share provenance of thread %s is unknown; memory capture treats it as a share copy for this run", sanitize_log_param(thread_id))
    return True


async def is_share_copy_thread(threads: ThreadMetaStore | None, thread_id: str, *, metadata_timeout: float) -> bool:
    """Whether memory capture outside a run, such as manual compaction, treats *thread_id* as a share copy."""
    if threads is None:
        return False
    try:
        async with asyncio.timeout(metadata_timeout):
            record = await threads.get(thread_id, user_id=None)
    except Exception:
        logger.warning("Could not read metadata of thread %s", sanitize_log_param(thread_id), exc_info=True)
        return resolve_share_copy(None, None, thread_id)
    return is_share_copy_metadata(record.get("metadata") if isinstance(record, dict) else None)


async def prepare_share_copy_run(request: Request, thread_id: str, *, threads: ThreadMetaStore | None, metadata_timeout: float) -> bool | None:
    """Return whether *thread_id* is a share copy, marking legacy copies first.

    Runs before admission like ``ensure_checkpoint_history_seeded``. The
    result lets memory capture treat the thread as a copy even after
    compaction has removed the copied messages and their marks. A metadata
    read failure returns ``None``, so the caller can decide later through
    :func:`resolve_share_copy`; it never blocks the run.

    Marking is a migration shim for copies imported before marks existed:
    without it, such a copy's history reaches memory extraction on the owner's
    next run, also through the pre-compaction flush, which ignores extraction
    watermarks. Remove that part once those copies are no longer an upgrade
    source. A busy or paused thread is left for a later run, because a
    checkpoint write would race the active run or replace the pending
    interrupt. The shim is best effort: a failure is logged.
    """
    if threads is None:
        # Sharing needs a thread store, so a thread without one is no copy.
        return False
    try:
        async with asyncio.timeout(metadata_timeout):
            record = await threads.get(thread_id, user_id=None)
    except Exception:
        logger.warning("Could not read metadata of thread %s; its copied share history is checked on a later run", sanitize_log_param(thread_id), exc_info=True)
        return None
    metadata = record.get("metadata") if isinstance(record, dict) else None
    if not is_share_copy_metadata(metadata):
        return False
    if metadata.get(SHARE_IMPORT_HISTORY_MARKED_KEY) is not True:
        await _mark_legacy_share_copy(request, thread_id, threads)
    return True


async def _mark_legacy_share_copy(request: Request, thread_id: str, threads: ThreadMetaStore) -> None:
    try:
        async with get_run_manager(request).reserve_thread_operation(thread_id, kind=ThreadOperationKind.checkpoint_write, user_id=get_trusted_internal_owner_user_id(request)):
            accessor, config = build_checkpoint_state_mutation_accessor(request, thread_id=thread_id, as_node="branch")
            head = await accessor.aget(config)
            if head.next or any(task.interrupts for task in head.tasks):
                return
            imported = await _imported_message_ids(request, accessor, config)
            if imported is None:
                # Recorded as handled anyway, so later runs skip the history scan.
                logger.warning("Share copy %s has no readable import checkpoint; its copied history stays unmarked", sanitize_log_param(thread_id))
                imported = set()
            unmarked = [message for message in head.values.get("messages") or () if getattr(message, "id", None) in imported and not message.additional_kwargs.get(IMPORTED_HISTORY_KEY)]
            if unmarked:
                marked = [message.model_copy(update={"additional_kwargs": {**message.additional_kwargs, IMPORTED_HISTORY_KEY: "share"}}) for message in unmarked]
                await accessor.aupdate(config, {"messages": marked}, as_node="branch")
            await threads.update_metadata(thread_id, {SHARE_IMPORT_HISTORY_MARKED_KEY: True}, touch=False, user_id=None)
            logger.info("Marked %d copied messages in share copy %s", len(unmarked), sanitize_log_param(thread_id))
    except ConflictError:
        logger.info("Share copy %s is busy; marking its copied history on a later run", sanitize_log_param(thread_id))
    except Exception:
        logger.warning("Could not mark the copied history of share copy %s; retrying on a later run", sanitize_log_param(thread_id), exc_info=True)
