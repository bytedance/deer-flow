"""Import a share into a fresh owner-scoped default-agent conversation."""

import os
import uuid
from contextlib import asynccontextmanager

from fastapi import HTTPException, Request
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Overwrite

from app.gateway.deps import get_checkpointer, get_run_event_store, get_run_manager, get_thread_store
from app.gateway.extension_artifacts import snapshot_sandbox
from app.gateway.history_seed import reserve_history_seed, write_history_seed
from app.gateway.persistent_writes import run_drained_write
from app.gateway.services import build_checkpoint_state_mutation_accessor
from app.gateway.share_snapshot import MAX_SHARE_FILE_BYTES, OUTPUT_PREFIX, artifact_path
from deerflow.config.paths import get_paths
from deerflow.persistence.thread_shares.sql import ThreadShareRepository
from deerflow.runtime import ThreadOperationKind
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.goal import goal_thread_lock
from deerflow.runtime.journal import build_branch_history_seed_events
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.artifact_snapshot import publish_snapshot
from deerflow.utils.file_io import run_file_io


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
    owner = get_effective_user_id()
    thread_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"deerflow-share:{owner}:{share['share_id']}:{request_id}"))
    threads = get_thread_store(request)
    async with goal_thread_lock(thread_id):
        existing = await threads.get(thread_id, user_id=owner)
        if existing is not None:
            if existing.get("metadata", {}).get("share_import_complete") is True:
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
        messages = []
        for item in share["snapshot"]["messages"]:
            content = item["content"]
            if item["type"] == "tool":
                content = f"{item['name']}:\n{content}"
            cls = HumanMessage if item["type"] == "human" else AIMessage
            messages.append(cls(content=content, id=str(uuid.uuid4())))
        title = str(share["snapshot"]["title"])[:256]
        # Recheck after loading all bytes, before creating any new workspace state.
        if await repo.get_public(token) is None:
            raise HTTPException(404, "Share unavailable")
        async with _reserve_import(request, thread_id, owner) as reservation:
            existing = await threads.get(thread_id, user_id=owner)
            if existing is not None:
                if existing.get("metadata", {}).get("share_import_complete") is True:
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
                await threads.update_metadata(thread_id, {"share_import_complete": True}, user_id=owner)
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
