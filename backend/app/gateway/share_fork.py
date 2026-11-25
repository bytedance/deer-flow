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
from deerflow.runtime.context_keys import checkpoint_agent_binding_metadata
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.goal import goal_thread_lock
from deerflow.runtime.journal import build_branch_history_seed_events
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.artifact_snapshot import publish_snapshot
from deerflow.utils.file_io import run_file_io
from deerflow.utils.messages import IMPORTED_HISTORY_CHANNEL, IMPORTED_HISTORY_KEY, IMPORTED_HISTORY_UNRESOLVED

logger = logging.getLogger(__name__)

#: Thread metadata, written only by this module (the thread routes strip
#: client copies): the copy's history is fully imported, and its copied
#: messages carry :data:`IMPORTED_HISTORY_KEY`. Memory capture reads the
#: thread state's :data:`IMPORTED_HISTORY_CHANNEL`, which branches and
#: compaction carry; this metadata only finds copies to migrate.
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
                await accessor.aupdate(config, {"messages": Overwrite(messages), "title": title, "artifacts": Overwrite([OUTPUT_PREFIX + a["path"] for a in artifacts]), IMPORTED_HISTORY_CHANNEL: "share"}, as_node="branch")
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

    ``None`` when the root is gone or unreadable, including a failed read:
    guessing from a later checkpoint would mark the owner's own turns as
    someone else's.
    """
    try:
        tuples = [item async for item in get_checkpointer(request).alist(config)]
        if not tuples or tuples[-1].parent_config is not None:
            return None
        root_id = tuples[-1].config["configurable"]["checkpoint_id"]
        snapshot = await accessor.aget({**config, "configurable": {**config["configurable"], "checkpoint_id": root_id}})
    except Exception:
        logger.warning("Could not read the import checkpoint of thread %s", sanitize_log_param(config["configurable"].get("thread_id")), exc_info=True)
        return None
    messages = snapshot.values.get("messages") if isinstance(snapshot.values, dict) else None
    ids = {message.id for message in messages or () if getattr(message, "id", None)}
    return ids or None


def is_share_copy_metadata(metadata: object) -> bool:
    """Return whether thread *metadata* records a completed share import."""
    return isinstance(metadata, Mapping) and metadata.get(SHARE_IMPORT_COMPLETE_KEY) is True


def _share_provenance(values: object) -> object:
    return values.get(IMPORTED_HISTORY_CHANNEL) if isinstance(values, Mapping) else None


def _has_share_provenance(values: object) -> bool:
    """Whether the copied turns in *values* are resolved; an unresolved copy stays eligible for migration."""
    provenance = _share_provenance(values)
    return bool(provenance) and provenance != IMPORTED_HISTORY_UNRESOLVED


def mark_imported(messages: list, imported: set[str]) -> list:
    """Return *messages* with the import mark on those whose id is in *imported*."""

    def mark(message):
        if getattr(message, "id", None) not in imported or message.additional_kwargs.get(IMPORTED_HISTORY_KEY):
            return message
        return message.model_copy(update={"additional_kwargs": {**message.additional_kwargs, IMPORTED_HISTORY_KEY: "share"}})

    return [mark(message) for message in messages]


async def _read_metadata(threads: ThreadMetaStore, thread_id: str, metadata_timeout: float) -> Mapping:
    async with asyncio.timeout(metadata_timeout):
        record = await threads.get(thread_id, user_id=None)
    metadata = record.get("metadata") if isinstance(record, dict) else None
    return metadata if isinstance(metadata, Mapping) else {}


async def _store_share_provenance(request: Request, thread_id: str, threads: ThreadMetaStore, accessor, config: dict, *, as_node: str = "branch") -> bool:
    """Mark the copied history and set the state channel at the head.

    The caller holds a checkpoint-write reservation. Returns ``True`` once the
    copied turns are marked. ``False`` means they are not: a busy or paused
    head is left for later, because a write would race the active run or
    replace the pending interrupt; a copy whose import checkpoint cannot be
    read is recorded as unresolved, so memory capture skips it, and is tried
    again on a later run.
    """
    head = await accessor.aget(config)
    if head.next or any(task.interrupts for task in head.tasks):
        return False
    # Keep the head's agent binding: without it, memory writes for the thread fail closed.
    update_config = {**config, "metadata": checkpoint_agent_binding_metadata(getattr(head, "metadata", None))}
    imported = await _imported_message_ids(request, accessor, config)
    if imported is None:
        logger.warning("Share copy %s has no readable import checkpoint; memory capture skips it until its copied history can be marked", sanitize_log_param(thread_id))
        if _share_provenance(head.values) != IMPORTED_HISTORY_UNRESOLVED:
            await accessor.aupdate(update_config, {IMPORTED_HISTORY_CHANNEL: IMPORTED_HISTORY_UNRESOLVED}, as_node=as_node)
        return False
    messages = list(head.values.get("messages") or ())
    marked = [copy for copy, original in zip(mark_imported(messages, imported), messages, strict=True) if copy is not original]
    await accessor.aupdate(update_config, {"messages": marked, IMPORTED_HISTORY_CHANNEL: "share"}, as_node=as_node)
    await threads.update_metadata(thread_id, {SHARE_IMPORT_HISTORY_MARKED_KEY: True}, touch=False, user_id=None)
    logger.info("Recorded share provenance for copy %s; marked %d copied messages", sanitize_log_param(thread_id), len(marked))
    return True


async def ensure_share_import_history_marked(request: Request, thread_id: str, *, threads: ThreadMetaStore | None, metadata_timeout: float) -> None:
    """Record share provenance in a copy imported before it was stored in state.

    Migration shim, run before admission like ``ensure_checkpoint_history_seeded``.
    Copies imported before #8422 lack the message marks, so their history
    reaches memory extraction; copies imported before the state channel
    existed lose their provenance once compaction removes the marked
    messages. Remove the shim once those copies are no longer an upgrade
    source. A busy or paused thread is left for a later run. Any other failure
    is logged and retried on a later run, but memory capture reads the
    provenance from state, so a copy whose state still has none is refused
    with ``503`` instead of being remembered as an ordinary thread.
    """
    if threads is None:
        return
    try:
        metadata = await _read_metadata(threads, thread_id, metadata_timeout)
    except Exception:
        logger.warning("Could not read metadata of thread %s; its copied share history is checked on a later run", sanitize_log_param(thread_id), exc_info=True)
        return
    if not is_share_copy_metadata(metadata):
        return
    accessor, config = build_checkpoint_state_mutation_accessor(request, thread_id=thread_id, as_node="branch")
    try:
        if _has_share_provenance((await accessor.aget(config)).values):
            return
        async with get_run_manager(request).reserve_thread_operation(thread_id, kind=ThreadOperationKind.checkpoint_write, user_id=get_trusted_internal_owner_user_id(request)):
            await _store_share_provenance(request, thread_id, threads, accessor, config)
    except ConflictError:
        logger.info("Share copy %s is busy; marking its copied history on a later run", sanitize_log_param(thread_id))
    except Exception as exc:
        logger.warning("Could not mark the copied history of share copy %s; retrying on a later run", sanitize_log_param(thread_id), exc_info=True)
        if not await _state_records_provenance(accessor, config):
            raise HTTPException(503, "The history of this copied conversation could not be checked; try again") from exc


async def _state_records_provenance(accessor, config: dict) -> bool:
    """Whether the head carries any provenance, resolved or unresolved, for memory capture to read."""
    try:
        return bool(_share_provenance((await accessor.aget(config)).values))
    except Exception:
        return False


async def prepare_share_copy_compaction(request: Request, thread_id: str, accessor, config: dict, *, as_node: str, metadata_timeout: float) -> bool:
    """Return whether a manual compaction may hand the removed messages to memory.

    Runs under the compaction's checkpoint-write reservation, so a copy that
    has not been migrated is migrated here first: its unmarked copied turns
    would otherwise be flushed as the owner's. When the thread's provenance
    cannot be established, the compaction skips the memory flush.
    """
    threads = getattr(request.app.state, "thread_store", None)
    if threads is None:
        # Sharing needs a thread store, so this thread is no copy.
        return True
    try:
        metadata = await _read_metadata(threads, thread_id, metadata_timeout)
        if not is_share_copy_metadata(metadata) or _has_share_provenance((await accessor.aget(config)).values):
            return True
        return await _store_share_provenance(request, thread_id, threads, accessor, config, as_node=as_node)
    except Exception:
        logger.warning("Could not establish the share provenance of thread %s; compacting without a memory flush", sanitize_log_param(thread_id), exc_info=True)
        return False


async def branch_share_provenance(request: Request, source_metadata: object, source_values: object, source_accessor, source_config: dict) -> tuple[str, set[str]] | None:
    """Channel value and copied-message IDs for a branch of a copy that has not been migrated.

    ``None`` means the branch inherits the source state unchanged: the source
    is no copy, or its state already carries resolved provenance, which the
    branch copies. Otherwise the branch gets the channel and these marks, so
    it does not depend on the source's next run. A branch is never migrated
    itself, so unreadable import history leaves it unresolved.
    """
    if _has_share_provenance(source_values) or not is_share_copy_metadata(source_metadata):
        return None
    imported = await _imported_message_ids(request, source_accessor, source_config)
    return (IMPORTED_HISTORY_UNRESOLVED, set()) if imported is None else ("share", imported)
