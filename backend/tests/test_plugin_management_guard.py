"""Plugin management authority: the public guard, the host resolvers, and the provider cache.

Covers, in order:

1. the fail-closed contract of ``require_plugin_management`` / ``arequire_plugin_management``;
2. the harness decision functions those helpers call;
3. the resolvers the Gateway installs on ``app.state``;
4. the loop-keyed plugin provider cache (never a cross-loop or cross-sync reuse).
"""

from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest
from deerflow_extension_api import (
    EXTENSION_PLUGIN_AUTHZ_RESOLVER_ASYNC_KEY,
    EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY,
    EXTENSION_PRINCIPAL_RESOLVER_KEY,
    ExtensionPrincipal,
    arequire_plugin_management,
    require_plugin_management,
)
from deerflow_extension_api.plugins import BackendAction, PluginContribution

from app.gateway import authz as gateway_authz
from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from deerflow.authz.plugin_authz import (
    PluginAuthorizationError,
    aenforce_plugin_action,
    aenforce_plugin_management,
    afilter_plugin_management,
    afilter_plugin_pages,
    enforce_plugin_action,
    enforce_plugin_management,
)
from deerflow.authz.plugin_targets import (
    MANAGEMENT_READ_PART,
    MANAGEMENT_WRITE_PART,
    plugin_management_target,
)
from deerflow.authz.provider import AuthzDecision, AuthzReason, AuthzRequest, Principal
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.authorization_config import AuthorizationConfig, AuthorizationProviderConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.extensions.registry import ExtensionRegistry

RBAC = "deerflow.authz.rbac:RbacAuthorizationProvider"
NAMESPACE = "community.check"
READ_TARGET = plugin_management_target(NAMESPACE, MANAGEMENT_READ_PART)
WRITE_TARGET = plugin_management_target(NAMESPACE, MANAGEMENT_WRITE_PART)


# --- Shared helpers ------------------------------------------------------------


class _RecordingProvider:
    """Records which entry point a caller used, so placement is observable."""

    name = "recording"

    def __init__(self, *, allow: bool = True, fail: str | None = None, decision: object = None) -> None:
        self.sync_requests: list[AuthzRequest] = []
        self.async_requests: list[AuthzRequest] = []
        self.filters: list[tuple[str, list[str]]] = []
        self._allow = allow
        self._fail = fail
        self._decision = decision

    def _decide(self) -> object:
        if self._fail == "authorize":
            raise RuntimeError("provider failed")
        if self._decision is not None:
            return self._decision
        return AuthzDecision(allow=self._allow, reasons=[] if self._allow else [AuthzReason(code="authz.denied")])

    def authorize(self, request: AuthzRequest):
        self.sync_requests.append(request)
        return self._decide()

    async def aauthorize(self, request: AuthzRequest):
        self.async_requests.append(request)
        return self._decide()

    def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]):
        if self._fail == "filter":
            raise RuntimeError("provider failed")
        self.filters.append((resource_type, list(candidates)))
        return [candidate for candidate in candidates if self._allow]


class _ExplodingReasons:
    """An iterable that satisfies ``isinstance(reasons, Iterable)`` and raises while consumed.

    Two ``__iter__`` shapes: raising outright, or yielding a non-``AuthzReason``
    and then raising from ``__next__``. Both are reusable — every ``__iter__``
    call builds a fresh generator.
    """

    def __init__(self, *, raises_while_iterating: bool = False) -> None:
        self._raises_while_iterating = raises_while_iterating

    def __iter__(self):
        if not self._raises_while_iterating:
            raise RuntimeError("reasons.__iter__ failed")
        return self._explode()

    def _explode(self):
        yield "not-a-reason"
        raise RuntimeError("reasons.__next__ failed")


def _authorization_config(*, enabled: bool = True, fail_closed: bool = True, roles: dict | None = None, provider_use: str = RBAC, provider_config: dict | None = None, default_role: str = "user") -> AuthorizationConfig:
    if provider_config is None:
        provider_config = {"roles": roles or {}} if provider_use == RBAC else {}
    return AuthorizationConfig(
        enabled=enabled,
        fail_closed=fail_closed,
        default_role=default_role,
        provider=AuthorizationProviderConfig(use=provider_use, config=provider_config),
    )


def _app_config(**kwargs) -> AppConfig:
    return AppConfig(sandbox=SandboxConfig(use="test"), authorization=_authorization_config(**kwargs))


def _principal(role: str = "user") -> Principal:
    return Principal(user_id="user-1", role=role)


def _use_provider(monkeypatch: pytest.MonkeyPatch, provider: object) -> None:
    """Serve *provider* from every resolution path the decision layer can take."""
    import deerflow.authz.plugin_authz as plugin_authz

    monkeypatch.setattr(plugin_authz, "resolve_authorization_provider", lambda config: provider)
    monkeypatch.setattr(plugin_authz, "resolve_authorization_provider_spec", lambda config: object())
    monkeypatch.setattr(plugin_authz, "construct_authorization_provider", lambda spec, config: provider)


_DEFAULT_USER = object()


def _plain_request(*, user: object = _DEFAULT_USER, auth_source: str = AUTH_SOURCE_SESSION, app: object | None = None) -> SimpleNamespace:
    """A request-like object; pass ``user=None`` for an anonymous caller."""
    if user is _DEFAULT_USER:
        user = SimpleNamespace(id="user-1", system_role="user", oauth_provider=None, oauth_id=None)
    return SimpleNamespace(app=app, state=SimpleNamespace(user=user, auth_source=auth_source), headers={})


# --- 1. The public guard -------------------------------------------------------


_GUARD_PRINCIPAL = ExtensionPrincipal("u1")


def _guard_request(*, principal: ExtensionPrincipal | None = _GUARD_PRINCIPAL, **state: object) -> SimpleNamespace:
    attributes: dict[str, object] = {EXTENSION_PRINCIPAL_RESOLVER_KEY: (lambda request: principal)}
    attributes.update(state)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**attributes)))


def test_guard_returns_the_principal_when_the_host_allows():
    request = _guard_request(**{EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY: lambda request, namespace, scope: True})

    assert require_plugin_management(request, NAMESPACE, scope="write") == _GUARD_PRINCIPAL


@pytest.mark.parametrize("answer", [False, None, "yes", 1, 0])
def test_guard_rejects_every_non_true_answer(answer):
    request = _guard_request(**{EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY: lambda request, namespace, scope: answer})

    with pytest.raises(PermissionError):
        require_plugin_management(request, NAMESPACE)


def test_guard_fails_closed_without_a_resolver():
    with pytest.raises(PermissionError):
        require_plugin_management(_guard_request(), NAMESPACE)


def test_guard_fails_closed_when_the_resolver_fails():
    def boom(request, namespace, scope):
        raise RuntimeError("nope")

    request = _guard_request(**{EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY: boom})

    with pytest.raises(PermissionError):
        require_plugin_management(request, NAMESPACE)


def test_guard_fails_closed_without_an_authenticated_principal():
    """Identity is asked before authority: no identity is not an answer."""
    request = _guard_request(principal=None, **{EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY: lambda request, namespace, scope: True})

    with pytest.raises(PermissionError):
        require_plugin_management(request, NAMESPACE)


@pytest.mark.parametrize("scope", ["admin", "", "READ", None])
def test_guard_rejects_an_unknown_scope(scope):
    request = _guard_request(**{EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY: lambda request, namespace, scope: True})

    with pytest.raises(ValueError):
        require_plugin_management(request, NAMESPACE, scope=scope)


@pytest.mark.parametrize("namespace", ["", "Bad", "a/b", 1, None])
def test_guard_rejects_a_malformed_namespace(namespace):
    request = _guard_request(**{EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY: lambda request, namespace, scope: True})

    with pytest.raises(ValueError):
        require_plugin_management(request, namespace)


def test_guard_asks_the_resolver_with_the_caller_namespace_and_scope():
    seen = []

    def resolver(request, namespace, scope):
        seen.append((namespace, scope))
        return True

    require_plugin_management(_guard_request(**{EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY: resolver}), NAMESPACE, scope="write")

    assert seen == [(NAMESPACE, "write")]


@pytest.mark.asyncio
async def test_async_guard_allows_and_denies():
    async def allow(request, namespace, scope):
        return True

    async def deny(request, namespace, scope):
        return False

    allowed = _guard_request(**{EXTENSION_PLUGIN_AUTHZ_RESOLVER_ASYNC_KEY: allow})
    assert await arequire_plugin_management(allowed, NAMESPACE) == _GUARD_PRINCIPAL

    denied = _guard_request(**{EXTENSION_PLUGIN_AUTHZ_RESOLVER_ASYNC_KEY: deny})
    with pytest.raises(PermissionError):
        await arequire_plugin_management(denied, NAMESPACE)


@pytest.mark.asyncio
async def test_async_guard_never_falls_back_to_the_sync_resolver():
    """Running the sync answer here would put the host's config read on the loop."""
    sync_only = _guard_request(**{EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY: lambda request, namespace, scope: True})
    with pytest.raises(PermissionError):
        await arequire_plugin_management(sync_only, NAMESPACE)

    async_only = _guard_request(**{EXTENSION_PLUGIN_AUTHZ_RESOLVER_ASYNC_KEY: lambda request, namespace, scope: True})
    with pytest.raises(PermissionError):
        require_plugin_management(async_only, NAMESPACE)


@pytest.mark.asyncio
async def test_async_guard_fails_closed_on_a_sync_resolver_and_on_errors():
    def wrong_shape(request, namespace, scope):
        return True

    async def boom(request, namespace, scope):
        raise RuntimeError("nope")

    for resolver in (wrong_shape, boom):
        request = _guard_request(**{EXTENSION_PLUGIN_AUTHZ_RESOLVER_ASYNC_KEY: resolver})
        with pytest.raises(PermissionError):
            await arequire_plugin_management(request, NAMESPACE)


# --- 2. The decision layer -----------------------------------------------------


def test_action_decision_uses_the_composed_target(monkeypatch):
    provider = _RecordingProvider()
    _use_provider(monkeypatch, provider)

    enforce_plugin_action(principal=_principal(), app_config=_app_config(), namespace=NAMESPACE, action_name="check")

    (request,) = provider.sync_requests
    assert (request.resource, request.action, request.target) == ("plugin_action", "invoke", f"{NAMESPACE}/check")


def test_management_read_and_write_are_distinct_targets(monkeypatch):
    provider = _RecordingProvider()
    _use_provider(monkeypatch, provider)

    enforce_plugin_management(principal=_principal(), app_config=_app_config(), namespace=NAMESPACE, write=False)
    enforce_plugin_management(principal=_principal(), app_config=_app_config(), namespace=NAMESPACE, write=True)

    assert [(request.resource, request.action, request.target) for request in provider.sync_requests] == [
        ("plugin_management", "read", READ_TARGET),
        ("plugin_management", "write", WRITE_TARGET),
    ]


def test_built_in_provider_separates_read_from_write_authority():
    """One resource, two targets, two verdicts — the built-in provider ignores ``action``."""
    config = _app_config(roles={"user": {"plugin_management": {"allow": [READ_TARGET]}}})

    enforce_plugin_management(principal=_principal(), app_config=config, namespace=NAMESPACE, write=False)

    with pytest.raises(PluginAuthorizationError) as error:
        enforce_plugin_management(principal=_principal(), app_config=config, namespace=NAMESPACE, write=True)
    assert (error.value.resource, error.value.target) == ("plugin_management", WRITE_TARGET)
    assert error.value.fail_closed is True


def test_deny_reports_the_provider_reason(monkeypatch):
    provider = _RecordingProvider(allow=False)
    _use_provider(monkeypatch, provider)

    with pytest.raises(PluginAuthorizationError) as error:
        enforce_plugin_action(principal=_principal(), app_config=_app_config(), namespace=NAMESPACE, action_name="check")

    assert error.value.reason_code == "authz.denied"
    assert error.value.resource == "plugin_action"
    assert error.value.target == f"{NAMESPACE}/check"


def test_disabled_authorization_never_asks_the_provider(monkeypatch):
    provider = _RecordingProvider()
    _use_provider(monkeypatch, provider)
    config = _app_config(enabled=False)

    enforce_plugin_action(principal=_principal(), app_config=config, namespace=NAMESPACE, action_name="check")
    enforce_plugin_management(principal=_principal(), app_config=config, namespace=NAMESPACE, write=True)

    assert provider.sync_requests == []


@pytest.mark.parametrize("fail_closed", [True, False])
@pytest.mark.parametrize("provider_kwargs", [{"fail": "authorize"}, {"decision": "not-a-decision"}])
def test_unanswerable_decisions_follow_fail_closed(monkeypatch, fail_closed: bool, provider_kwargs: dict):
    provider = _RecordingProvider(**provider_kwargs)
    _use_provider(monkeypatch, provider)
    config = _app_config(fail_closed=fail_closed)

    if fail_closed:
        with pytest.raises(PluginAuthorizationError) as error:
            enforce_plugin_action(principal=_principal(), app_config=config, namespace=NAMESPACE, action_name="check")
        assert error.value.reason_code == "authz.provider_error"
    else:
        enforce_plugin_action(principal=_principal(), app_config=config, namespace=NAMESPACE, action_name="check")


@pytest.mark.parametrize("fail_closed", [True, False])
def test_a_missing_principal_follows_fail_closed(monkeypatch, fail_closed: bool):
    provider = _RecordingProvider()
    _use_provider(monkeypatch, provider)

    if fail_closed:
        with pytest.raises(PluginAuthorizationError) as error:
            enforce_plugin_management(principal=None, app_config=_app_config(), namespace=NAMESPACE, write=False)
        assert error.value.reason_code == "authz.no_principal"
    else:
        enforce_plugin_management(principal=None, app_config=_app_config(fail_closed=False), namespace=NAMESPACE, write=False)
    assert provider.sync_requests == []


@pytest.mark.asyncio
async def test_async_decisions_await_the_async_provider(monkeypatch):
    provider = _RecordingProvider()
    _use_provider(monkeypatch, provider)
    config = _app_config()

    await aenforce_plugin_action(principal=_principal(), app_config=config, namespace=NAMESPACE, action_name="check")
    await aenforce_plugin_management(principal=_principal(), app_config=config, namespace=NAMESPACE, write=True)

    assert provider.sync_requests == []
    assert [(request.resource, request.target) for request in provider.async_requests] == [
        ("plugin_action", f"{NAMESPACE}/check"),
        ("plugin_management", WRITE_TARGET),
    ]


@pytest.mark.asyncio
async def test_async_decision_honours_fail_closed(monkeypatch):
    _use_provider(monkeypatch, _RecordingProvider(fail="authorize"))

    with pytest.raises(PluginAuthorizationError):
        await aenforce_plugin_action(principal=_principal(), app_config=_app_config(), namespace=NAMESPACE, action_name="check")

    await aenforce_plugin_action(principal=_principal(), app_config=_app_config(fail_closed=False), namespace=NAMESPACE, action_name="check")


def test_an_unreadable_config_denies_instead_of_allowing(monkeypatch):
    """Review P1: config *unavailable* is not the same as a disabled policy.

    The flag that would permit an allow cannot be read, so the check fails closed
    rather than silently passing the request.
    """
    _use_provider(monkeypatch, _RecordingProvider())

    with pytest.raises(PluginAuthorizationError) as error:
        enforce_plugin_action(principal=_principal(), app_config=None, namespace=NAMESPACE, action_name="check")

    assert error.value.reason_code == "authz.config_unavailable"
    assert error.value.fail_closed is True


@pytest.mark.asyncio
async def test_an_unreadable_config_denies_the_async_paths(monkeypatch):
    _use_provider(monkeypatch, _RecordingProvider())

    with pytest.raises(PluginAuthorizationError) as error:
        await aenforce_plugin_management(principal=_principal(), app_config=None, namespace=NAMESPACE, write=True)
    assert error.value.reason_code == "authz.config_unavailable"

    with pytest.raises(PluginAuthorizationError):
        await afilter_plugin_management(principal=_principal(), app_config=None, candidates=[READ_TARGET])


@pytest.mark.parametrize("allow", ["false", "true", 1, 0, [], None])
@pytest.mark.parametrize("fail_closed", [True, False])
def test_a_non_bool_allow_is_a_malformed_decision(monkeypatch, allow, fail_closed):
    """Review P2: ``AuthzDecision(allow="false")`` is truthy and must not be an allow."""
    _use_provider(monkeypatch, _RecordingProvider(decision=AuthzDecision(allow=allow)))
    config = _app_config(fail_closed=fail_closed)

    if fail_closed:
        with pytest.raises(PluginAuthorizationError) as error:
            enforce_plugin_management(principal=_principal(), app_config=config, namespace=NAMESPACE, write=True)
        assert error.value.reason_code == "authz.provider_error"
    else:
        enforce_plugin_management(principal=_principal(), app_config=config, namespace=NAMESPACE, write=True)


@pytest.mark.parametrize("reasons", [None, 5, _ExplodingReasons(), _ExplodingReasons(raises_while_iterating=True)])
@pytest.mark.parametrize("fail_closed", [True, False])
def test_malformed_reasons_keep_the_denial(monkeypatch, reasons, fail_closed):
    """Review P2/P3: a denied verdict with unusable ``reasons`` still denies.

    ``AuthzDecision`` is a plain dataclass, so ``reasons`` can be any object —
    including one that passes the ``Iterable`` check and then raises from
    ``__iter__``/``__next__``. The verdict is a valid denial (``allow`` is a
    real ``bool``), so the denial stands and only the informative code degrades:
    extracting it must not raise, or a denial would escape as an unhandled error
    instead of ``403``.
    """
    _use_provider(monkeypatch, _RecordingProvider(decision=AuthzDecision(allow=False, reasons=reasons)))

    with pytest.raises(PluginAuthorizationError) as error:
        enforce_plugin_management(principal=_principal(), app_config=_app_config(fail_closed=fail_closed), namespace=NAMESPACE, write=True)

    assert error.value.reason_code == "authz.denied"
    assert error.value.fail_closed is fail_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("reasons", [None, 5, _ExplodingReasons(), _ExplodingReasons(raises_while_iterating=True)])
async def test_async_malformed_reasons_keep_the_denial(monkeypatch, reasons):
    _use_provider(monkeypatch, _RecordingProvider(decision=AuthzDecision(allow=False, reasons=reasons)))

    with pytest.raises(PluginAuthorizationError) as error:
        await aenforce_plugin_action(principal=_principal(), app_config=_app_config(), namespace=NAMESPACE, action_name="check")

    assert error.value.reason_code == "authz.denied"


@pytest.mark.asyncio
@pytest.mark.parametrize("allow", ["false", 1])
@pytest.mark.parametrize("fail_closed", [True, False])
async def test_async_non_bool_allow_is_a_malformed_decision(monkeypatch, allow, fail_closed):
    _use_provider(monkeypatch, _RecordingProvider(decision=AuthzDecision(allow=allow)))
    config = _app_config(fail_closed=fail_closed)

    if fail_closed:
        with pytest.raises(PluginAuthorizationError) as error:
            await aenforce_plugin_action(principal=_principal(), app_config=config, namespace=NAMESPACE, action_name="check")
        assert error.value.reason_code == "authz.provider_error"
    else:
        await aenforce_plugin_action(principal=_principal(), app_config=config, namespace=NAMESPACE, action_name="check")


@pytest.mark.asyncio
async def test_batch_filters_use_the_batch_entry_point(monkeypatch):
    provider = _RecordingProvider()
    _use_provider(monkeypatch, provider)
    config = _app_config()

    allowed = await afilter_plugin_management(principal=_principal(), app_config=config, candidates=[READ_TARGET, WRITE_TARGET])
    pages = await afilter_plugin_pages(principal=_principal(), app_config=config, candidates=[f"{NAMESPACE}/reports"])

    assert allowed == frozenset({READ_TARGET, WRITE_TARGET})
    assert pages == frozenset({f"{NAMESPACE}/reports"})
    assert provider.filters == [
        ("plugin_management", [READ_TARGET, WRITE_TARGET]),
        ("plugin_page", [f"{NAMESPACE}/reports"]),
    ]


@pytest.mark.asyncio
async def test_batch_filter_never_returns_a_target_it_was_not_asked_about(monkeypatch):
    """A provider answer can only narrow the candidates, never widen them.

    ``filter_resources`` is a plain method on a custom provider, so an answer
    naming an unrelated target (``"*"``, another namespace) must not reach the
    projection as visible authority.
    """

    class _OversharingProvider(_RecordingProvider):
        def filter_resources(self, principal, resource_type, candidates):
            return [*candidates, "*", f"{NAMESPACE}/injected"]

    _use_provider(monkeypatch, _OversharingProvider())

    pages = await afilter_plugin_pages(principal=_principal(), app_config=_app_config(), candidates=[f"{NAMESPACE}/reports"])
    management = await afilter_plugin_management(principal=_principal(), app_config=_app_config(), candidates=[READ_TARGET])

    assert pages == frozenset({f"{NAMESPACE}/reports"})
    assert management == frozenset({READ_TARGET})


@pytest.mark.asyncio
async def test_batch_filter_denies_every_candidate(monkeypatch):
    _use_provider(monkeypatch, _RecordingProvider(allow=False))

    allowed = await afilter_plugin_management(principal=_principal(), app_config=_app_config(), candidates=[READ_TARGET, WRITE_TARGET])

    assert allowed == frozenset()


@pytest.mark.asyncio
async def test_batch_filters_skip_the_provider_without_candidates(monkeypatch):
    """No candidate means no provider round trip."""
    provider = _RecordingProvider()
    _use_provider(monkeypatch, provider)

    assert await afilter_plugin_pages(principal=_principal(), app_config=_app_config(), candidates=[]) == frozenset()
    assert provider.filters == []


@pytest.mark.asyncio
async def test_batch_filters_are_unrestricted_while_authorization_is_disabled(monkeypatch):
    provider = _RecordingProvider(allow=False)
    _use_provider(monkeypatch, provider)
    config = _app_config(enabled=False)

    allowed = await afilter_plugin_management(principal=_principal(), app_config=config, candidates=[READ_TARGET])

    assert allowed == frozenset({READ_TARGET})
    assert provider.filters == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_closed", [True, False])
async def test_batch_filter_failure_follows_fail_closed(monkeypatch, fail_closed: bool):
    _use_provider(monkeypatch, _RecordingProvider(fail="filter"))
    config = _app_config(fail_closed=fail_closed)

    if fail_closed:
        with pytest.raises(PluginAuthorizationError) as error:
            await afilter_plugin_management(principal=_principal(), app_config=config, candidates=[READ_TARGET])
        assert error.value.reason_code == "authz.provider_error"
    else:
        assert await afilter_plugin_management(principal=_principal(), app_config=config, candidates=[READ_TARGET]) == frozenset({READ_TARGET})


# --- 3. The host-installed resolvers -------------------------------------------


def _plugin_extensions(*, namespace: str = NAMESPACE) -> object:
    async def check(payload, context):  # pragma: no cover - never invoked
        return {}

    plugin = PluginContribution(namespace=namespace, title="Check", enabled=True, backend=(BackendAction("check", check),))
    registry = ExtensionRegistry()
    with registry.attributed_to("test:install"):
        registry.plugin(plugin)
    return registry.build()


@pytest.fixture
def host_app(monkeypatch: pytest.MonkeyPatch):
    """A real ``create_app()`` with a stub config and our own plugin snapshot."""
    import app.gateway.app as app_module
    from deerflow.extensions import reset_loaded_extensions, reset_runtime_diagnostics

    reset_app_config()
    gateway_authz._plugin_provider_cache.clear()
    monkeypatch.setattr(app_module, "get_app_config", lambda: AppConfig(sandbox=SandboxConfig(use="test")))
    reset_loaded_extensions()
    reset_runtime_diagnostics()
    from app.gateway.app import create_app

    app = create_app()
    app.state.extensions = _plugin_extensions()
    try:
        yield app
    finally:
        gateway_authz._plugin_provider_cache.clear()
        reset_app_config()
        reset_loaded_extensions()
        reset_runtime_diagnostics()


def test_gateway_installs_both_plugin_management_resolvers(host_app):
    assert callable(getattr(host_app.state, EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY, None))
    assert callable(getattr(host_app.state, EXTENSION_PLUGIN_AUTHZ_RESOLVER_ASYNC_KEY, None))


def test_installed_resolver_is_a_noop_while_authorization_is_disabled(host_app):
    set_app_config(_app_config(enabled=False))
    resolver = getattr(host_app.state, EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY)
    request = _plain_request(app=host_app)

    assert resolver(request, NAMESPACE, "read") is True
    assert resolver(request, NAMESPACE, "write") is True
    # And the public helper therefore allows an enterprise route.
    assert require_plugin_management(request, NAMESPACE, scope="write").user_id == "user-1"


def test_installed_resolvers_decide_read_and_write_independently(host_app):
    set_app_config(_app_config(roles={"user": {"plugin_management": {"allow": [READ_TARGET]}}}))
    request = _plain_request(app=host_app)

    assert require_plugin_management(request, NAMESPACE, scope="read").user_id == "user-1"
    with pytest.raises(PermissionError):
        require_plugin_management(request, NAMESPACE, scope="write")


def test_installed_resolvers_cannot_answer_an_unknown_plugin(host_app):
    set_app_config(_app_config(roles={"user": {"plugin_management": {"allow": "*"}}}))
    request = _plain_request(app=host_app)
    resolver = getattr(host_app.state, EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY)

    assert resolver(request, "community.missing", "read") is None
    with pytest.raises(PermissionError):
        require_plugin_management(request, "community.missing")


def test_installed_resolvers_cannot_answer_an_anonymous_caller(host_app):
    set_app_config(_app_config(roles={"user": {"plugin_management": {"allow": "*"}}}))
    resolver = getattr(host_app.state, EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY)

    assert resolver(_plain_request(user=None, app=host_app), NAMESPACE, "read") is None


@pytest.mark.asyncio
async def test_installed_async_resolver_matches_the_sync_answer(host_app):
    set_app_config(_app_config(roles={"user": {"plugin_management": {"allow": [READ_TARGET]}}}))
    request = _plain_request(app=host_app)

    assert (await arequire_plugin_management(request, NAMESPACE, scope="read")).user_id == "user-1"
    with pytest.raises(PermissionError):
        await arequire_plugin_management(request, NAMESPACE, scope="write")


def test_installed_resolver_denies_when_the_config_cannot_be_read(host_app, monkeypatch):
    """Review P1: a config read failure must not resolve to 'allowed'."""
    set_app_config(_app_config(roles={"user": {"plugin_management": {"allow": "*"}}}))

    def broken_config():
        raise RuntimeError("config is being rewritten")

    monkeypatch.setattr("deerflow.config.app_config.get_app_config", broken_config)
    monkeypatch.setattr("deerflow.config.get_app_config", broken_config)

    resolver = getattr(host_app.state, EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY)

    assert resolver(_plain_request(app=host_app), NAMESPACE, "read") is False


def test_installed_resolver_allows_when_no_config_exists(host_app, monkeypatch):
    """A host that never had a config has no policy to apply: no gate.

    Same rule the route-scoped gates use (``_get_route_authorization_config``,
    ``deerflow.authz.sandbox_authz.safe_app_config``): authorization can only be
    enabled through config, so a ``config.yaml``-less host (CI runner, direct
    call, a host that mounts only the plugins router) keeps today's behavior.
    """

    def absent_config():
        raise FileNotFoundError("`config.yaml` file not found")

    monkeypatch.setattr("deerflow.config.app_config.get_app_config", absent_config)
    monkeypatch.setattr("deerflow.config.get_app_config", absent_config)

    resolver = getattr(host_app.state, EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY)

    assert resolver(_plain_request(app=host_app), NAMESPACE, "read") is True


@pytest.mark.parametrize("fail_closed,expected", [(True, False), (False, True)])
def test_installed_resolver_applies_the_running_policy_when_the_config_disappears(host_app, monkeypatch, fail_closed: bool, expected: bool):
    """Review P1: a host that lost the config it is running on must not answer 'allowed'.

    The configuration this process loaded decides the failure: an enabled policy
    follows its own ``fail_closed`` (``True`` by default) instead of the read
    failure being read as "authorization was never configured".
    """
    set_app_config(_app_config(fail_closed=fail_closed, roles={"user": {"plugin_management": {"allow": "*"}}}))

    def absent_config():
        raise FileNotFoundError("`config.yaml` file not found")

    monkeypatch.setattr("deerflow.config.app_config.get_app_config", absent_config)
    monkeypatch.setattr("deerflow.config.get_app_config", absent_config)

    resolver = getattr(host_app.state, EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY)

    assert resolver(_plain_request(app=host_app), NAMESPACE, "read") is expected


@pytest.mark.asyncio
async def test_installed_async_resolver_denies_when_the_config_disappears(host_app, monkeypatch):
    """The async resolver reaches the same answer through ``aresolve_plugin_authorization``."""
    set_app_config(_app_config(roles={"user": {"plugin_management": {"allow": "*"}}}))

    def absent_config():
        raise FileNotFoundError("`config.yaml` file not found")

    monkeypatch.setattr("deerflow.config.app_config.get_app_config", absent_config)
    monkeypatch.setattr("deerflow.config.get_app_config", absent_config)

    with pytest.raises(PermissionError):
        await arequire_plugin_management(_plain_request(app=host_app), NAMESPACE, scope="read")


def test_installed_resolver_stays_noop_when_the_lost_config_had_authorization_off(host_app, monkeypatch):
    """The running policy decides: a loaded config with authorization off has no gate to apply."""
    set_app_config(_app_config(enabled=False))

    def absent_config():
        raise FileNotFoundError("`config.yaml` file not found")

    monkeypatch.setattr("deerflow.config.app_config.get_app_config", absent_config)
    monkeypatch.setattr("deerflow.config.get_app_config", absent_config)

    resolver = getattr(host_app.state, EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY)

    assert resolver(_plain_request(app=host_app), NAMESPACE, "read") is True


@pytest.mark.parametrize("fail_closed,expected", [(True, False), (False, True)])
def test_installed_resolver_applies_the_failure_policy(host_app, fail_closed: bool, expected: bool):
    set_app_config(_app_config(fail_closed=fail_closed, provider_use="nonexistent.module:FakeProvider"))
    resolver = getattr(host_app.state, EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY)

    assert resolver(_plain_request(app=host_app), NAMESPACE, "read") is expected


# --- 4. Provider lifecycle -----------------------------------------------------


def _loop_affine_module(monkeypatch: pytest.MonkeyPatch) -> tuple[str, list]:
    """A provider whose construction is only valid on a running event loop."""
    module = ModuleType("plugin_provider_lifecycle_test_module")
    constructed: list = []

    class LoopAffineProvider:
        name = "loop-affine"

        def __init__(self, *, tolerate_no_loop: bool = False) -> None:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                if not tolerate_no_loop:
                    raise
                self.loop = None
            constructed.append(self.loop)

        def authorize(self, request):
            return AuthzDecision(allow=True)

        async def aauthorize(self, request):
            return AuthzDecision(allow=True)

        def filter_resources(self, principal, resource_type, candidates):
            return list(candidates)

    module.LoopAffineProvider = LoopAffineProvider
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return f"{module.__name__}:LoopAffineProvider", constructed


@pytest.fixture(autouse=True)
def _isolated_provider_cache():
    gateway_authz._plugin_provider_cache.clear()
    reset_app_config()
    yield
    gateway_authz._plugin_provider_cache.clear()
    reset_app_config()


@pytest.mark.asyncio
async def test_async_resolution_constructs_on_the_calling_loop(monkeypatch):
    class_path, constructed = _loop_affine_module(monkeypatch)
    set_app_config(_app_config(provider_use=class_path))

    provider, principal, app_config = await gateway_authz.aresolve_plugin_authorization(_plain_request())

    running_loop = asyncio.get_running_loop()
    assert provider is not None and provider.loop is running_loop
    assert constructed == [running_loop]
    assert principal is not None and principal.user_id == "user-1"
    assert app_config is not None and app_config.authorization.enabled is True


@pytest.mark.asyncio
async def test_a_hot_path_neither_rediscovers_nor_reconstructs(monkeypatch):
    class_path, constructed = _loop_affine_module(monkeypatch)
    set_app_config(_app_config(provider_use=class_path))
    request = _plain_request()
    first, _, _ = await gateway_authz.aresolve_plugin_authorization(request)

    discoveries: list = []
    monkeypatch.setattr(gateway_authz, "resolve_authorization_provider_spec", lambda config: discoveries.append(1))

    second, _, _ = await gateway_authz.aresolve_plugin_authorization(request)

    assert second is first
    assert constructed == [asyncio.get_running_loop()]
    assert discoveries == []


@pytest.mark.asyncio
async def test_a_configuration_change_rebuilds_the_provider(monkeypatch):
    class_path, constructed = _loop_affine_module(monkeypatch)
    set_app_config(_app_config(provider_use=class_path))
    first, _, _ = await gateway_authz.aresolve_plugin_authorization(_plain_request())

    set_app_config(_app_config(provider_use=class_path, default_role="guest"))

    second, _, _ = await gateway_authz.aresolve_plugin_authorization(_plain_request())
    assert second is not first
    assert len(constructed) == 2


def test_the_sync_slot_never_reuses_a_loop_provider(monkeypatch):
    class_path, constructed = _loop_affine_module(monkeypatch)
    config = _app_config(provider_use=class_path, provider_config={"tolerate_no_loop": True})
    set_app_config(config)

    async def _async_resolve():
        return (await gateway_authz.aresolve_plugin_authorization(_plain_request()))[0]

    loop_provider = asyncio.run(_async_resolve())
    sync_provider, principal, sync_config = gateway_authz.resolve_plugin_authorization(_plain_request())

    assert loop_provider is not None and loop_provider.loop is not None
    assert sync_provider is not None
    assert sync_provider is not loop_provider
    assert sync_provider.loop is None
    assert principal is not None

    # The sync caller keeps its own slot on the next call.
    assert gateway_authz.resolve_plugin_authorization(_plain_request())[0] is sync_provider
    assert len(constructed) == 2


def test_each_event_loop_gets_its_own_provider(monkeypatch):
    class_path, constructed = _loop_affine_module(monkeypatch)
    set_app_config(_app_config(provider_use=class_path, provider_config={"tolerate_no_loop": True}))

    async def _async_resolve():
        return (await gateway_authz.aresolve_plugin_authorization(_plain_request()))[0]

    first = asyncio.run(_async_resolve())
    second = asyncio.run(_async_resolve())

    assert first is not second
    assert first.loop is not second.loop
    assert len(constructed) == 2


@pytest.mark.asyncio
async def test_concurrent_cold_requests_still_decide_correctly(monkeypatch):
    """No single-flight lock: a duplicate construction is accepted, not a failure."""
    class_path, constructed = _loop_affine_module(monkeypatch)
    set_app_config(_app_config(provider_use=class_path))

    first, second = await asyncio.gather(
        gateway_authz.aresolve_plugin_authorization(_plain_request()),
        gateway_authz.aresolve_plugin_authorization(_plain_request()),
    )

    assert len(constructed) == 2
    for provider, principal, _snapshot in (first, second):
        assert provider is not None and principal is not None
        decision = await provider.aauthorize(AuthzRequest(principal=principal, resource="plugin_action", action="invoke", target=f"{NAMESPACE}/check"))
        assert decision.allow is True


def test_anonymous_callers_get_a_provider_without_a_principal(monkeypatch):
    class_path, _ = _loop_affine_module(monkeypatch)
    set_app_config(_app_config(provider_use=class_path, provider_config={"tolerate_no_loop": True}))

    provider, principal, app_config = gateway_authz.resolve_plugin_authorization(_plain_request(user=None))

    assert provider is not None
    assert principal is None
