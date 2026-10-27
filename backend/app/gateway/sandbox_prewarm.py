"""Bounded, authorized background warmup for the opt-in user sandbox provider."""

import asyncio
import logging
import time

from app.gateway.authz import authorize_sandbox_for_request
from deerflow.config import get_app_config
from deerflow.runtime.user_context import reset_current_user, set_current_user
from deerflow.sandbox.exceptions import SandboxAuthorizationError
from deerflow.sandbox.sandbox_provider import get_sandbox_provider

USER_POOL_PROVIDER = "deerflow.community.aio_sandbox.user_pool:UserAioSandboxProvider"
logger = logging.getLogger(__name__)
_pending: dict[str, asyncio.Task] = {}
_recent: dict[str, float] = {}


async def _prewarm(user):
    token = set_current_user(user)
    try:
        config = await asyncio.to_thread(get_app_config)
        if config.sandbox.use != USER_POOL_PROVIDER or not config.sandbox.prewarm_on_login:
            return
        await asyncio.to_thread(authorize_sandbox_for_request, user, is_internal=False, app_config=config)
        provider = await asyncio.to_thread(get_sandbox_provider)
        await provider.prewarm_async(str(user.id))
    except SandboxAuthorizationError:
        return
    except Exception:
        logger.warning("Optional user sandbox prewarm failed", exc_info=True)
    finally:
        reset_current_user(token)


def schedule_user_sandbox_prewarm(user):
    user_id = str(user.id)
    now = time.monotonic()
    if getattr(user, "needs_setup", False) or user_id in _pending or now - _recent.get(user_id, -1000) < 300 or len(_pending) >= 8:
        return
    if len(_recent) >= 256:
        _recent.pop(min(_recent, key=_recent.get))
    _recent[user_id] = now
    task = asyncio.create_task(_prewarm(user), name="user-sandbox-prewarm")
    _pending[user_id] = task
    task.add_done_callback(lambda _: _pending.pop(user_id, None))


async def close_prewarm_tasks():
    tasks = list(_pending.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
