"""LangGraph compatibility auth handler — shares JWT logic with Gateway.

The default DeerFlow runtime is embedded in the FastAPI Gateway; scripts and
Docker deployments do not load this module.  It is retained for LangGraph
tooling, Studio, or direct LangGraph Server compatibility through
``langgraph.json``'s ``auth.path``.

When that compatibility path is used, this module reuses the same JWT and CSRF
rules as Gateway so both modes validate sessions consistently.

Two layers:
  1. @auth.authenticate — validates JWT cookie, extracts user_id,
     and enforces CSRF on state-changing methods (POST/PUT/DELETE/PATCH)
  2. @auth.on — returns metadata filter so each user only sees own threads
"""

import secrets
from contextvars import ContextVar
from uuid import uuid4

from langgraph_sdk import Auth
from starlette.exceptions import HTTPException

from app.gateway.auth.errors import TokenError
from app.gateway.auth.jwt import decode_token
from app.gateway.auth_disabled import AUTH_DISABLED_USER_ID, is_auth_disabled
from app.gateway.deps import get_local_provider
from deerflow.mcp_scope import (
    THREAD_INCARNATION_CONTEXT_KEY,
    THREAD_INCARNATION_METADATA_GUARD_KEY,
    is_valid_thread_incarnation,
)

auth = Auth()

# StudioUser was added after DeerFlow's historical langgraph-sdk floor. Resolve
# it once so older compatible SDK installs keep ordinary owner scoping instead
# of failing every request with an AttributeError.
_STUDIO_USER_TYPE = getattr(Auth.types, "StudioUser", None)

# Methods that require CSRF validation (state-changing per RFC 7231).
_CSRF_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})
_allow_thread_incarnation_write: ContextVar[bool] = ContextVar(
    "deerflow_allow_standalone_thread_incarnation_write",
    default=False,
)
_MISSING = object()


def _metadata(value: dict) -> dict:
    metadata = value.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        value["metadata"] = metadata
    return metadata


def _scrub_run_incarnation(value: dict) -> None:
    lifecycle_keys = (
        THREAD_INCARNATION_CONTEXT_KEY,
        THREAD_INCARNATION_METADATA_GUARD_KEY,
    )
    metadata = _metadata(value)
    for key in lifecycle_keys:
        metadata.pop(key, None)
    kwargs = value.get("kwargs")
    if not isinstance(kwargs, dict):
        kwargs = {}
        value["kwargs"] = kwargs
    context = kwargs.get("context")
    if not isinstance(context, dict):
        context = {}
        kwargs["context"] = context
    runtime_keys = (*lifecycle_keys, "user_id", "thread_id", "run_id")
    for key in runtime_keys:
        context.pop(key, None)
    config = kwargs.get("config")
    if not isinstance(config, dict):
        config = {}
        kwargs["config"] = config
    for key in ("context", "metadata", "configurable"):
        section = config.get(key)
        if isinstance(section, dict):
            for protected_key in runtime_keys:
                section.pop(protected_key, None)


async def _read_standalone_thread(thread_id, ctx) -> dict | None:
    from langgraph_runtime.database import connect
    from langgraph_runtime.ops import Threads

    try:
        async with connect() as conn:
            rows = await Threads.get(conn, thread_id, ctx=ctx)
            return await anext(rows, None)
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise


async def _ensure_standalone_thread_incarnation(
    thread_id,
    assistant_id,
    ctx,
    *,
    create_if_missing: bool,
    creation_metadata: dict | None = None,
) -> str | None | object:
    thread = await _read_standalone_thread(thread_id, ctx)
    if thread is None:
        if not create_if_missing:
            return _MISSING
        incarnation = uuid4().hex
    else:
        metadata = thread.get("metadata")
        stored = metadata.get(THREAD_INCARNATION_CONTEXT_KEY, _MISSING) if isinstance(metadata, dict) else _MISSING
        if stored is _MISSING:
            # Match the rollout contract used by the Gateway and embedded
            # runtime: a persisted pre-incarnation thread remains in the
            # explicit legacy generation. A read/patch backfill cannot fence
            # deletion plus same-ID recreation through LangGraph's public API.
            return None
        if not is_valid_thread_incarnation(stored):
            raise RuntimeError("Standalone LangGraph thread has an invalid incarnation")
        return stored

    from langgraph_api.utils import AuthContext as RuntimeAuthContext
    from langgraph_runtime.database import connect
    from langgraph_runtime.ops import Assistants, Threads

    token = _allow_thread_incarnation_write.set(True)
    try:
        async with connect() as conn:
            auth_token = RuntimeAuthContext.set(None)
            try:
                assistant_rows = await Assistants.get(conn, assistant_id, ctx=None)
                assistant = await anext(assistant_rows, None)
            finally:
                RuntimeAuthContext.reset(auth_token)
            if assistant is None:
                raise HTTPException(status_code=404, detail="Assistant not found")
            if assistant.get("metadata", {}).get("created_by") != "system":
                authorized_rows = await Assistants.get(conn, assistant_id, ctx=ctx)
                if await anext(authorized_rows, None) is None:
                    raise HTTPException(status_code=404, detail="Assistant not found")

            rows = await Threads.put(
                conn,
                thread_id,
                metadata={**(creation_metadata or {}), THREAD_INCARNATION_CONTEXT_KEY: incarnation},
                if_exists="do_nothing",
                ctx=ctx,
            )
            if await anext(rows, None) is None:
                raise RuntimeError("Standalone LangGraph thread incarnation was not persisted")
    finally:
        _allow_thread_incarnation_write.reset(token)

    persisted = await _read_standalone_thread(thread_id, ctx)
    if persisted is None:
        raise RuntimeError("Standalone LangGraph thread incarnation could not be verified")
    persisted_metadata = persisted.get("metadata")
    value = persisted_metadata.get(THREAD_INCARNATION_CONTEXT_KEY, _MISSING) if isinstance(persisted_metadata, dict) else _MISSING
    if value is _MISSING:
        # A mixed-version peer may have won the do-nothing create with a
        # legacy thread. Keep that persisted lifecycle on the legacy scope.
        return None
    if not is_valid_thread_incarnation(value):
        raise RuntimeError("Standalone LangGraph thread incarnation could not be verified")
    return value


async def _bind_standalone_run_incarnation(ctx, value: dict) -> None:
    _scrub_run_incarnation(value)
    thread_id = value.get("thread_id")
    if thread_id is None:
        incarnation: str | None = None
    else:
        # Pre-creation bypasses LangGraph's implicit-create metadata merge.
        # Preserve its precedence using only the already-sanitized metadata;
        # the helper adds the server incarnation last and never updates an
        # existing thread (including a concurrent creation winner).
        config_metadata = value["kwargs"]["config"].get("metadata")
        creation_metadata = {
            **(config_metadata if isinstance(config_metadata, dict) else {}),
            **value["metadata"],
        }
        incarnation = await _ensure_standalone_thread_incarnation(
            thread_id,
            value["assistant_id"],
            ctx,
            create_if_missing=value.get("if_not_exists") == "create",
            creation_metadata=creation_metadata,
        )
        if incarnation is _MISSING:
            return
        assert is_valid_thread_incarnation(incarnation)

    context = value["kwargs"]["context"]
    context["user_id"] = ctx.user.identity
    if thread_id is not None:
        context["thread_id"] = str(thread_id)
    else:
        context.pop("thread_id", None)
    run_id = value.get("run_id")
    if run_id is not None:
        context["run_id"] = str(run_id)
    else:
        context.pop("run_id", None)
    context[THREAD_INCARNATION_CONTEXT_KEY] = incarnation
    context[THREAD_INCARNATION_METADATA_GUARD_KEY] = True


def _check_csrf(request) -> None:
    """Enforce Double Submit Cookie CSRF check for state-changing requests.

    Mirrors Gateway's CSRFMiddleware logic so that LangGraph routes
    proxied directly by nginx have the same CSRF protection.
    """
    method = getattr(request, "method", "") or ""
    if method.upper() not in _CSRF_METHODS:
        return

    if is_auth_disabled():
        return

    cookie_token = request.cookies.get("csrf_token")
    header_token = request.headers.get("x-csrf-token")

    if not cookie_token or not header_token:
        raise Auth.exceptions.HTTPException(
            status_code=403,
            detail="CSRF token missing. Include X-CSRF-Token header.",
        )

    if not secrets.compare_digest(cookie_token, header_token):
        raise Auth.exceptions.HTTPException(
            status_code=403,
            detail="CSRF token mismatch.",
        )


@auth.authenticate
async def authenticate(request):
    """Validate the session cookie, decode JWT, and check token_version.

    Same validation chain as Gateway's get_current_user_from_request:
      cookie → decode JWT → DB lookup → token_version match
    Also enforces CSRF on state-changing methods.
    """
    # CSRF check before authentication so forged cross-site requests
    # are rejected early, even if the cookie carries a valid JWT.
    _check_csrf(request)

    if is_auth_disabled():
        return AUTH_DISABLED_USER_ID

    token = request.cookies.get("access_token")
    if not token:
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="Not authenticated",
        )

    payload = decode_token(token)
    if isinstance(payload, TokenError):
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="Invalid token",
        )

    user = await get_local_provider().get_user(payload.sub)
    if user is None:
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="User not found",
        )
    if user.token_version != payload.ver:
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="Token revoked (password changed)",
        )

    return payload.sub


@auth.on
async def add_owner_filter(ctx: Auth.types.AuthContext, value: dict):
    """Inject user_id metadata on writes; filter by user_id on reads.

    Gateway stores thread ownership as ``metadata.user_id``.
    This handler ensures LangGraph Server enforces the same isolation.
    """
    # LangGraph represents its trusted local Studio principal with a dedicated
    # user type. Do not infer that privilege from its public identity string:
    # an ordinary authenticated principal may reuse the same string.
    if _STUDIO_USER_TYPE is not None and isinstance(ctx.user, _STUDIO_USER_TYPE) and ctx.resource == "assistants" and ctx.action in {"read", "search"}:
        return {
            "$or": [
                {"created_by": "system"},
                {"user_id": ctx.user.identity},
            ]
        }

    # Ownership and provenance on external assistant writes are server-owned.
    # LangGraph treats ``created_by=system`` as privileged during run creation,
    # so accepting that marker from request metadata would cross the auth
    # boundary. The standalone pre-runtime persistence repair also scrubs this
    # marker from legacy active rows and their version history before normal
    # version selection becomes available.
    metadata = _metadata(value)
    metadata["user_id"] = ctx.user.identity
    if ctx.resource == "threads" and ctx.action == "create_run":
        await _bind_standalone_run_incarnation(ctx, value)
    elif ctx.resource == "threads":
        if ctx.action == "create":
            if not _allow_thread_incarnation_write.get():
                metadata[THREAD_INCARNATION_CONTEXT_KEY] = uuid4().hex
            elif not is_valid_thread_incarnation(metadata.get(THREAD_INCARNATION_CONTEXT_KEY, _MISSING)):
                raise RuntimeError("Standalone LangGraph internal thread create has an invalid incarnation")
        elif ctx.action == "update" and not _allow_thread_incarnation_write.get():
            metadata.pop(THREAD_INCARNATION_CONTEXT_KEY, None)
    if ctx.resource == "assistants" and ctx.action in {"create", "update"}:
        metadata["created_by"] = "user"

    # Return filter dict — LangGraph applies it to search/read/delete
    return {"user_id": ctx.user.identity}
