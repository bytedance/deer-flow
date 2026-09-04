"""Authorization decorators and context for DeerFlow.

Inspired by LangGraph Auth system: https://github.com/langchain-ai/langgraph/blob/main/libs/sdk-py/langgraph_sdk/auth/__init__.py

**Usage:**

1. Use ``@require_auth`` on routes that need authentication
2. Use ``@require_permission("resource", "action", filter_key=...)`` for permission checks
3. The decorator chain processes from bottom to top

**Example:**

    @router.get("/{thread_id}")
    @require_auth
    @require_permission("threads", "read", owner_check=True)
    async def get_thread(thread_id: str, request: Request):
        # User is authenticated and has threads:read permission
        ...

**Permission Model:**

- threads:read   - View thread
- threads:write  - Create/update thread
- threads:delete - Delete thread
- runs:create   - Run agent
- runs:read     - View run
- runs:cancel   - Cancel run
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

from fastapi import HTTPException, Request

from deerflow.authz.principal import build_principal_from_context
from deerflow.authz.provider import AuthorizationProvider, AuthzDecision, AuthzRequest, Principal
from deerflow.authz.runtime import resolve_authorization_provider
from deerflow.config.authorization_config import AuthorizationConfig

if TYPE_CHECKING:
    from app.gateway.auth.models import User
    from deerflow.config.app_config import AppConfig

P = ParamSpec("P")
T = TypeVar("T")
logger = logging.getLogger(__name__)


# Permission constants
class Permissions:
    """Permission constants for resource:action format."""

    # Threads
    THREADS_READ = "threads:read"
    THREADS_WRITE = "threads:write"
    THREADS_DELETE = "threads:delete"

    # Runs
    RUNS_CREATE = "runs:create"
    RUNS_READ = "runs:read"
    RUNS_CANCEL = "runs:cancel"


class AuthContext:
    """Authentication context for the current request.

    Stored in request.state.auth after require_auth decoration.

    Attributes:
        user: The authenticated user, or None if anonymous
        permissions: List of permission strings (e.g., "threads:read")
    """

    __slots__ = ("user", "permissions")

    def __init__(self, user: User | None = None, permissions: list[str] | None = None):
        self.user = user
        self.permissions = permissions or []

    @property
    def is_authenticated(self) -> bool:
        """Check if user is authenticated."""
        return self.user is not None

    def has_permission(self, resource: str, action: str) -> bool:
        """Check if context has permission for resource:action.

        Args:
            resource: Resource name (e.g., "threads")
            action: Action name (e.g., "read")

        Returns:
            True if user has permission
        """
        permission = f"{resource}:{action}"
        return permission in self.permissions

    def require_user(self) -> User:
        """Get user or raise 401.

        Raises:
            HTTPException 401 if not authenticated
        """
        if not self.user:
            raise HTTPException(status_code=401, detail="Authentication required")
        return self.user


def get_auth_context(request: Request) -> AuthContext | None:
    """Get AuthContext from request state."""
    return getattr(request.state, "auth", None)


def require_cancel_permission_if(request: Request, can_cancel: bool) -> None:
    """Require ``runs:cancel`` when a request carries cancel capability.

    Cancel capability reaches the run lifecycle through more than the dedicated
    cancel route: ``?action=interrupt|rollback`` on the join-stream entry and
    ``multitask_strategy=interrupt|rollback`` on run creation both terminate an
    already-active run. A credential whose scopes omit ``runs:cancel`` (e.g. a
    create- or read-only PAT) must not reach any of those paths, and
    decorators cannot express query- or body-parameter-conditional
    permissions, so callers apply this check where the capability is known.

    ``request.state.auth`` may be absent in middleware-less compositions
    (unit-test stubs, auth-disabled startup); the shipped Gateway always
    stamps it via ``AuthMiddleware`` before handlers run.
    """
    if not can_cancel:
        return
    auth = getattr(request.state, "auth", None)
    if auth is not None and not auth.has_permission("runs", "cancel"):
        raise HTTPException(status_code=403, detail="Permission denied: runs:cancel")


_ALL_PERMISSIONS: list[str] = [
    Permissions.THREADS_READ,
    Permissions.THREADS_WRITE,
    Permissions.THREADS_DELETE,
    Permissions.RUNS_CREATE,
    Permissions.RUNS_READ,
    Permissions.RUNS_CANCEL,
]


def _make_test_request_stub() -> Any:
    """Create a minimal request-like object for direct unit calls.

    Used when decorated route handlers are invoked without FastAPI's
    request injection. Includes fields accessed by auth helpers.
    """
    return SimpleNamespace(state=SimpleNamespace(), cookies={}, _deerflow_test_bypass_auth=True)


def _get_route_authorization_config() -> AuthorizationConfig:
    """Return the hot-reloaded authorization config for this request.

    Falls back to a disabled config when AppConfig is not available (e.g. test
    environments without a config.yaml), preserving legacy all-permissions behavior.
    """
    from deerflow.config.app_config import get_app_config

    try:
        return get_app_config().authorization
    except (FileNotFoundError, RuntimeError):
        return AuthorizationConfig()


# --- Provider cache (W1/F1) ---
# Keyed by config object identity (id) so the expensive model_dump() signature
# is only recomputed when get_app_config() returns a new object (hot-reload).
_route_provider_cache: dict[str, AuthorizationProvider] = {}
_route_provider_config_id: int | None = None
_route_provider_config_sig: str | None = None


def _get_cached_route_provider(config: AuthorizationConfig) -> AuthorizationProvider | None:
    """Resolve (or reuse) the authorization provider for route permissions.

    The provider is cached per config object identity. When ``get_app_config()``
    returns a new object (hot-reload), the signature is recomputed and compared;
    only an actual content change triggers re-resolution. This avoids calling
    ``model_dump()`` on every request — the fast path is a single ``id()`` check.
    """
    global _route_provider_config_id, _route_provider_config_sig, _route_provider_cache

    config_id = id(config)

    # Fast path: same config object as last time → return cached provider.
    if config_id == _route_provider_config_id and _route_provider_cache:
        return _route_provider_cache.get("provider")

    # Config object changed (hot-reload): compute signature to check if
    # content actually changed or just the wrapper object identity.
    sig = repr(sorted(config.model_dump().items()))
    if sig == _route_provider_config_sig and _route_provider_cache:
        # Same content, different object — update id, reuse provider.
        _route_provider_config_id = config_id
        return _route_provider_cache.get("provider")

    # Content changed (or first call): re-resolve into a local first,
    # then publish id + sig + provider together to avoid a race window.
    _route_provider_cache.clear()

    provider = resolve_authorization_provider(config)
    if provider is not None:
        _route_provider_cache["provider"] = provider
    _route_provider_config_id = config_id
    _route_provider_config_sig = sig
    return provider


async def resolve_route_permissions(user: User, *, is_internal: bool) -> list[str]:
    """Return the route permissions granted to an authenticated user.

    Disabled authorization preserves the legacy all-permissions behavior.
    When enabled, every registered ``resource:action`` permission is evaluated
    independently so a provider failure affects only the route being checked.
    Provider instances are cached per config signature (hot-reload safe).
    """
    config = _get_route_authorization_config()
    if config.enabled is not True:
        return list(_ALL_PERMISSIONS)

    try:
        provider = _get_cached_route_provider(config)
        if provider is None:
            raise ValueError("authorization is enabled but provider resolution returned None")
    except Exception:
        logger.warning("Failed to resolve authorization provider for Gateway routes", exc_info=True)
        return [] if config.fail_closed else list(_ALL_PERMISSIONS)

    # Align with Phase 1B's tool path: internal callers (IM channel workers,
    # scheduler) have system_role="internal", which is not a real RBAC role.
    # Omit it so default_role applies, mirroring inject_authenticated_user_context
    # which pops user_role for internal callers without a resolved owner.
    from app.gateway.internal_auth import INTERNAL_SYSTEM_ROLE

    user_role = getattr(user, "system_role", None)
    if user_role == INTERNAL_SYSTEM_ROLE:
        user_role = None

    principal = build_principal_from_context(
        {
            "user_id": str(user.id),
            "user_role": user_role,
            "oauth_provider": getattr(user, "oauth_provider", None),
            "oauth_id": getattr(user, "oauth_id", None),
            "is_internal": is_internal,
        },
        default_role=config.default_role,
    )

    # Evaluate all permissions in parallel (W2).
    async def _evaluate(permission: str) -> str | None:
        _, action = permission.split(":", maxsplit=1)
        request = AuthzRequest(
            principal=principal,
            resource="route",
            action=action,
            target=permission,
        )
        try:
            decision = await provider.aauthorize(request)
            if not isinstance(decision, AuthzDecision):
                raise TypeError("AuthorizationProvider.aauthorize must return AuthzDecision")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Authorization provider failed while evaluating route permission %s",
                permission,
                exc_info=True,
            )
            return permission if not config.fail_closed else None
        return permission if decision.allow else None

    results = await asyncio.gather(*[_evaluate(p) for p in _ALL_PERMISSIONS])
    return [p for p in results if p is not None]


class _AuthorizationUnavailable(Exception):
    """Raised internally when the provider cannot be resolved for a route check.

    Carries the ``fail_closed`` flag so the caller can decide between deny-all
    and legacy allow-all without re-reading config.
    """

    def __init__(self, *, fail_closed: bool) -> None:
        self.fail_closed = fail_closed


def resolve_model_authorization(user: User, *, is_internal: bool) -> tuple[AuthorizationProvider | None, Principal | None]:
    """Return ``(provider, principal)`` for model-route authorization.

    When authorization is disabled, returns ``(None, None)`` so callers can
    short-circuit to legacy behavior (all models visible). When enabled,
    resolves the cached provider and builds a Principal identical to
    ``resolve_route_permissions`` (including the ``INTERNAL_SYSTEM_ROLE``
    → ``None`` pop so internal callers fall under ``default_role``).

    Raises ``_AuthorizationUnavailable`` (carrying the ``fail_closed`` flag)
    when the provider cannot be resolved; callers translate that into the
    appropriate deny response (empty list / 403).
    """
    config = _get_route_authorization_config()
    if config.enabled is not True:
        return None, None

    try:
        provider = _get_cached_route_provider(config)
        if provider is None:
            raise ValueError("authorization is enabled but provider resolution returned None")
    except Exception:
        logger.warning("Failed to resolve authorization provider for model routes", exc_info=True)
        raise _AuthorizationUnavailable(fail_closed=config.fail_closed)

    principal = build_principal_from_context(
        _route_authz_context(user, is_internal=is_internal),
        default_role=config.default_role,
    )
    return provider, principal


def _route_authz_context(user: User, *, is_internal: bool) -> dict:
    """Build the shared Principal context dict for a request-scoped user.

    Applies the ``INTERNAL_SYSTEM_ROLE → None`` pop so internal callers fall
    under ``default_role`` (mirrors ``inject_authenticated_user_context``).
    Used by ``resolve_model_authorization`` and ``authorize_sandbox_for_request``
    so every route-level authorization path builds the identity the same way.
    """
    from app.gateway.internal_auth import INTERNAL_SYSTEM_ROLE

    user_role = getattr(user, "system_role", None)
    if user_role == INTERNAL_SYSTEM_ROLE:
        user_role = None
    return {
        "user_id": str(user.id),
        "user_role": user_role,
        "oauth_provider": getattr(user, "oauth_provider", None),
        "oauth_id": getattr(user, "oauth_id", None),
        "is_internal": is_internal,
    }


def authorize_sandbox_for_request(
    user: User,
    *,
    is_internal: bool,
    app_config: AppConfig | None,
) -> None:
    """Check ``sandbox:execute`` for a Gateway request before sandbox acquisition.

    Thin wrapper over the harness-level ``authorize_sandbox_execution`` that
    builds the Principal from the request-scoped ``user`` — the same identity
    construction as ``resolve_model_authorization`` (including the
    ``INTERNAL_SYSTEM_ROLE → None`` pop). Raises
    :class:`~deerflow.sandbox.exceptions.SandboxAuthorizationError` on deny or
    on provider-resolution failure under ``fail_closed``; callers translate
    that into skipping the sandbox sync (not an HTTP error, since the primary
    operation — e.g. file upload — can proceed without it).

    No-op when ``authorization.enabled`` is false.
    """
    from deerflow.authz.sandbox_authz import authorize_sandbox_execution
    from deerflow.sandbox.exceptions import SandboxAuthorizationError

    config = _get_route_authorization_config()
    if config.enabled is not True:
        return

    context = _route_authz_context(user, is_internal=is_internal)

    try:
        authorize_sandbox_execution(
            context=context,
            app_config=app_config,
        )
    except SandboxAuthorizationError:
        raise
    except Exception:
        # Defense-in-depth: provider resolution and authorize() errors are
        # already converted to SandboxAuthorizationError (or allowed under
        # fail-open) one layer down inside authorize_sandbox_execution, so this
        # normally only catches config-read failures here (e.g. get_config()
        # raising in a config-less environment). Those must not 500 the
        # upload/artifact route — degrade per fail_closed instead.
        logger.warning("Failed to resolve authorization provider for sandbox:execute", exc_info=True)
        if config.fail_closed:
            raise SandboxAuthorizationError(role=context.get("user_role")) from None


@dataclass(slots=True)
class SandboxRequestLease:
    """One Gateway request's process-local use of a sandbox client."""

    sandbox: object | None
    sandbox_id: str | None
    denied: bool
    owner_id: str | None
    provider: object | None

    async def release(self) -> None:
        """Drop the request holder without bypassing concurrent executions."""
        if self.owner_id is None or self.provider is None:
            return
        from deerflow.sandbox.lease import get_sandbox_lease_manager

        owner_id = self.owner_id
        self.owner_id = None
        await get_sandbox_lease_manager(self.provider).release_async(owner_id)


async def try_acquire_sandbox_for_request(
    request: Request,
    sandbox_provider,
    thread_id: str,
    *,
    user_id: str,
    app_config: AppConfig | None,
    owner_prefix: str = "gateway",
    release_on_last: bool = True,
) -> SandboxRequestLease:
    """Gate + acquire the thread sandbox for a Gateway sync path.

    Single entry point for the uploads/artifacts sandbox-sync paths so the
    deny/skip semantics live in one place: runs the ``sandbox:execute`` gate
    for the request's user, then acquires the sandbox under a unique request
    holder. Callers must await :meth:`SandboxRequestLease.release` after their
    last client operation.

    - denied role → no sandbox/owner and ``denied=True``: acquisition was skipped by policy;
      the primary operation (upload / artifact edit) proceeds without the
      sandbox copy.
    - allowed → ``sandbox`` is the acquired instance, or ``sandbox is None`` when
      the provider lost it right after acquiring (infrastructure error —
      callers surface it as 500 / RuntimeError respectively, since that is
      not a policy decision).
    - ``request is None`` (direct-call tests) and unresolvable users skip the
      gate — same fail-open semantics as the models routes' anonymous bypass.
    """
    from deerflow.sandbox.exceptions import SandboxAuthorizationError

    try:
        from app.gateway.deps import get_optional_user_from_request

        user = await get_optional_user_from_request(request) if request is not None else None
        if user is not None:
            authorize_sandbox_for_request(user, is_internal=_is_internal_caller(request, user), app_config=app_config)
    except SandboxAuthorizationError:
        logger.info("Sandbox sync skipped: sandbox execution not permitted for this caller (thread_id=%s)", thread_id)
        return SandboxRequestLease(
            sandbox=None,
            sandbox_id=None,
            denied=True,
            owner_id=None,
            provider=None,
        )

    from deerflow.sandbox.lease import get_sandbox_lease_manager

    owner_id = f"{owner_prefix}:{uuid.uuid4()}"
    sandbox_id = await get_sandbox_lease_manager(sandbox_provider).acquire_async(
        owner_id,
        thread_id,
        user_id=user_id,
        release_on_last=release_on_last,
    )
    return SandboxRequestLease(
        sandbox=sandbox_provider.get(sandbox_id),
        sandbox_id=sandbox_id,
        denied=False,
        owner_id=owner_id,
        provider=sandbox_provider,
    )


async def _authenticate(request: Request) -> AuthContext:
    """Authenticate request and return AuthContext.

    Delegates to deps.get_optional_user_from_request() for the JWT→User pipeline.
    Returns AuthContext with user=None for anonymous requests.
    """
    from app.gateway.deps import get_optional_user_from_request

    user = await get_optional_user_from_request(request)
    if user is None:
        return AuthContext(user=None, permissions=[])

    is_internal = _is_internal_caller(request, user)
    permissions = await resolve_route_permissions(user, is_internal=is_internal)
    return AuthContext(user=user, permissions=permissions)


def _is_internal_caller(request: Request, user: Any) -> bool:
    """Determine if the request originates from a trusted internal caller.

    Checks three signals (any one suffices):
    1. ``request.state.auth_source == AUTH_SOURCE_INTERNAL`` (set by AuthMiddleware).
    2. ``user.system_role == INTERNAL_SYSTEM_ROLE`` (synthetic internal user).
    3. The request carries a valid internal auth token header (decorator-only path
       where AuthMiddleware may not have stamped ``auth_source`` yet).
    """
    from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL
    from app.gateway.internal_auth import INTERNAL_AUTH_HEADER_NAME, INTERNAL_SYSTEM_ROLE, is_valid_internal_auth_token

    if getattr(getattr(request, "state", None), "auth_source", None) == AUTH_SOURCE_INTERNAL:
        return True
    if getattr(user, "system_role", None) == INTERNAL_SYSTEM_ROLE:
        return True
    # Decorator-only path: check the internal token header directly.
    internal_token = request.headers.get(INTERNAL_AUTH_HEADER_NAME) if hasattr(request, "headers") else None
    if internal_token and is_valid_internal_auth_token(internal_token):
        return True
    return False


def require_auth[**P, T](func: Callable[P, T]) -> Callable[P, T]:
    """Decorator that authenticates the request and enforces authentication.

    Independently raises HTTP 401 for unauthenticated requests, regardless of
    whether ``AuthMiddleware`` is present in the ASGI stack. Sets the resolved
    ``AuthContext`` on ``request.state.auth`` for downstream handlers.

    Must be placed ABOVE other decorators (executes after them).

    Usage:
        @router.get("/{thread_id}")
        @require_auth  # Bottom decorator (executes first after permission check)
        @require_permission("threads", "read")
        async def get_thread(thread_id: str, request: Request):
            auth: AuthContext = request.state.auth
            ...

    Raises:
        HTTPException: 401 if the request is unauthenticated.
        ValueError: If 'request' parameter is missing.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        request = kwargs.get("request")
        if request is None:
            # Unit tests may call decorated handlers directly without a
            # FastAPI Request object. Inject a minimal request stub when
            # the wrapped function declares `request`.
            if "request" in inspect.signature(func).parameters:
                kwargs["request"] = _make_test_request_stub()
            else:
                raise ValueError("require_auth decorator requires 'request' parameter")
            request = kwargs["request"]

        if getattr(request, "_deerflow_test_bypass_auth", False):
            return await func(*args, **kwargs)

        # Authenticate and set context
        auth_context = await _authenticate(request)
        request.state.auth = auth_context

        if not auth_context.is_authenticated:
            raise HTTPException(status_code=401, detail="Authentication required")

        return await func(*args, **kwargs)

    return wrapper


def require_permission(
    resource: str,
    action: str,
    owner_check: bool = False,
    require_existing: bool = False,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator that checks permission for resource:action.

    Must be used AFTER @require_auth.

    Args:
        resource: Resource name (e.g., "threads", "runs")
        action: Action name (e.g., "read", "write", "delete")
        owner_check: If True, validates that the current user owns the resource.
                     Requires 'thread_id' path parameter and performs ownership check.
        require_existing: Only meaningful with ``owner_check=True``. If True, a
                          missing ``threads_meta`` row counts as a denial (404)
                          instead of "untracked legacy thread, allow". Use on
                          **destructive / mutating** routes (DELETE, PATCH,
                          state-update) so a deleted thread can't be re-targeted
                          by another user via the missing-row code path.

    Usage:
        # Read-style: legacy untracked threads are allowed
        @require_permission("threads", "read", owner_check=True)
        async def get_thread(thread_id: str, request: Request):
            ...

        # Destructive: thread row MUST exist and be owned by caller
        @require_permission("threads", "delete", owner_check=True, require_existing=True)
        async def delete_thread(thread_id: str, request: Request):
            ...

    Raises:
        HTTPException 401: If authentication required but user is anonymous
        HTTPException 403: If user lacks permission
        HTTPException 404: If owner_check=True but user doesn't own the thread
        ValueError: If owner_check=True but 'thread_id' parameter is missing
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = kwargs.get("request")
            if request is None:
                # Unit tests may call decorated route handlers directly — with
                # or without constructing a FastAPI Request object — and may
                # pass ``request`` positionally. Bind to the real signature
                # first so a positional request is found rather than
                # duplicated by the stub injection below.
                try:
                    bound = inspect.signature(func).bind_partial(*args, **kwargs)
                except TypeError:
                    bound = None
                if bound is not None and "request" in bound.arguments:
                    request = bound.arguments["request"]
                elif "request" in inspect.signature(func).parameters:
                    kwargs["request"] = _make_test_request_stub()
                    request = kwargs["request"]
                else:
                    return await func(*args, **kwargs)

            if getattr(request, "_deerflow_test_bypass_auth", False):
                return await func(*args, **kwargs)

            auth: AuthContext = getattr(request.state, "auth", None)
            if auth is None:
                auth = await _authenticate(request)
                request.state.auth = auth

            if not auth.is_authenticated:
                raise HTTPException(status_code=401, detail="Authentication required")

            # Check permission
            if not auth.has_permission(resource, action):
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission denied: {resource}:{action}",
                )

            # Owner check for thread-specific resources.
            #
            # 2.0-rc moved thread metadata into the SQL persistence layer
            # (``threads_meta`` table). We verify ownership via
            # ``ThreadMetaStore.check_access``: it returns True for
            # missing rows (untracked legacy thread) and for rows whose
            # ``user_id`` is NULL (shared / pre-auth data), so this is
            # strict-deny rather than strict-allow — only an *existing*
            # row with a *different* user_id triggers 404.
            if owner_check:
                from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, INTERNAL_SYSTEM_ROLE

                thread_id = kwargs.get("thread_id")
                if thread_id is None:
                    raise ValueError("require_permission with owner_check=True requires 'thread_id' parameter")

                from app.gateway.deps import get_thread_store

                thread_store = get_thread_store(request)
                allowed = await thread_store.check_access(
                    thread_id,
                    str(auth.user.id),
                    require_existing=require_existing,
                )
                if not allowed and getattr(auth.user, "system_role", None) == INTERNAL_SYSTEM_ROLE:
                    # Trusted internal callers (channel workers) also act for
                    # the connection owner carried in X-DeerFlow-Owner-User-Id.
                    # Scope the check to that owner instead of bypassing it; a
                    # leaked internal token must not grant cross-user thread
                    # access. The header is honored only after ``auth`` proved
                    # the caller holds the internal token (mirrors
                    # get_trusted_internal_owner_user_id, which keys off the
                    # middleware-stamped ``request.state.user``).
                    header_owner = (request.headers.get(INTERNAL_OWNER_USER_ID_HEADER_NAME) or "").strip()
                    if header_owner:
                        allowed = await thread_store.check_access(
                            thread_id,
                            header_owner,
                            require_existing=require_existing,
                        )
                if not allowed:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Thread {thread_id} not found",
                    )

            return await func(*args, **kwargs)

        return wrapper

    return decorator
