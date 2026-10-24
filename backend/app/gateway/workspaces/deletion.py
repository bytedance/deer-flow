"""Native local-thread deletion through a captured private lifecycle receipt."""

import logging

from fastapi import HTTPException, Request

from app.gateway import deps
from deerflow.authz.workspace import get_current_workspace
from deerflow.config.paths import get_paths
from deerflow.persistence.run.sql import RunRepository
from deerflow.persistence.thread_meta import ThreadMetaRepository
from deerflow.persistence.thread_meta.deletion import ThreadDeletionBusy, ThreadDeletionRepository
from deerflow.runtime import ThreadOperationKind
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.goal import goal_thread_lock
from deerflow.utils.file_io import await_drained, run_file_io
from deerflow.utils.thread_id import validate_thread_id

logger = logging.getLogger(__name__)


async def delete_private_thread(request: Request, thread_id: str):
    context = get_current_workspace()
    threads = deps.get_thread_store(request)
    runs = deps.get_run_store(request)
    events = deps.get_run_event_store(request)
    if context is None or not isinstance(threads, ThreadMetaRepository) or not isinstance(runs, RunRepository) or threads._sf is not runs._sf:
        raise HTTPException(status_code=503, detail="Thread cleanup is not available")
    if not isinstance(events, (MemoryRunEventStore, DbRunEventStore)) or (isinstance(events, DbRunEventStore) and events._sf is not threads._sf):
        raise HTTPException(status_code=503, detail="Thread cleanup is not available for this history storage")
    if deps.get_app_config().sandbox.use != "deerflow.sandbox.local:LocalSandboxProvider" or getattr(request.app.state, "native_run_admission_host", None) is not None:
        raise HTTPException(status_code=503, detail="Thread cleanup is not available for this execution environment")
    try:
        validate_thread_id(thread_id)
    except ValueError:
        raise HTTPException(status_code=409, detail="This conversation requires migration before cleanup") from None
    lifecycle = ThreadDeletionRepository(threads)
    source = await lifecycle.get(thread_id)
    manager = deps.get_run_manager(request)
    try:
        async with goal_thread_lock(thread_id):
            async with manager.reserve_thread_operation(thread_id, kind=ThreadOperationKind.delete, user_id=context.actor_user_id):
                # Drain mark+cleanup as one owned operation. No writer lock is
                # held across session/FS/checkpoint cleanup. Unknown outcomes
                # leave the metadata tombstone and never auto-replay.
                await await_drained(_clean(lifecycle, source["incarnation"], events, request, thread_id, context.actor_user_id))
    except ThreadDeletionBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"success": True, "message": "Conversation data deleted"}


async def _clean(lifecycle, incarnation, events, request, thread_id, user_id):
    receipt = await lifecycle.begin(thread_id, incarnation)
    try:
        try:
            from deerflow.community.browser_automation import get_browser_session_manager
            from deerflow.community.browser_automation.session import BrowserSessionScope
        except ImportError:
            pass  # An unavailable optional provider has no local manager here.
        else:
            browser = get_browser_session_manager()
            scope = BrowserSessionScope(user_id, thread_id, incarnation)
            await browser.close_scoped_session(scope)
            if scope.key in browser.retained_session_keys():
                raise RuntimeError("Browser physical closure is unconfirmed")
        from deerflow.mcp.session_pool import get_session_pool

        await get_session_pool().close_thread_scope(user_id=user_id, thread_id=thread_id)
        await deps.get_checkpointer(request).adelete_thread(thread_id)
        await run_file_io(get_paths().delete_thread_dir, thread_id, user_id=user_id)
        await events.delete_by_thread(thread_id, user_id=user_id)
        await lifecycle.finish(receipt)
    except Exception:
        logger.exception("Private conversation cleanup did not finish; lifecycle fence retained")
        raise HTTPException(status_code=503, detail="Deletion paused for safe recovery") from None
