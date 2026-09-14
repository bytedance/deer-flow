"""Phase 3 skill-level authorization tests.

Covers Layer 1 enforcement:
- ``filter_available_skills_by_authorization`` — the lead-agent / subagent
  entry point that filters the skill-name allowlist by the provider's
  ``"skill"`` policy.
- ``filter_resources_by_authorization`` — the generic batch filter.
- Subagent executor integration: ``_load_skills`` respects authorization.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from deerflow.authz.enforcement import filter_resources_by_authorization
from deerflow.authz.principal import build_principal_from_context
from deerflow.authz.rbac import RbacAuthorizationProvider
from deerflow.authz.skill_filter import filter_available_skills_by_authorization
from deerflow.config.app_config import AppConfig
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig

# ── Helpers ────────────────────────────────────────────────────────────


def _make_app_config() -> AppConfig:
    """Build a minimal AppConfig for authorization tests."""
    return AppConfig(
        models=[ModelConfig(name="gpt-4", model="gpt-4", use="langchain_openai:ChatOpenAI")],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        authorization=AuthorizationConfig(),
    )


def _context(**overrides):
    values = {
        "user_id": "user-123",
        "user_role": "user",
        "oauth_provider": "github",
        "oauth_id": "oauth-456",
        "is_internal": False,
    }
    values.update(overrides)
    return values


def _rbac_provider(roles: dict) -> RbacAuthorizationProvider:
    return RbacAuthorizationProvider(roles=roles)


def _enable_authz(app_config: AppConfig, *, fail_closed: bool = True, default_role: str = "user") -> None:
    app_config.authorization = AuthorizationConfig(
        enabled=True,
        fail_closed=fail_closed,
        default_role=default_role,
    )


# ── filter_available_skills_by_authorization ───────────────────────────


def test_filter_available_skills_disabled_is_noop():
    """When authorization is disabled, the allowlist is returned unchanged."""
    app_config = _make_app_config()
    assert filter_available_skills_by_authorization({"a", "b"}, context=_context(), app_config=app_config) == {"a", "b"}
    assert filter_available_skills_by_authorization(None, context=_context(), app_config=app_config) is None
    assert filter_available_skills_by_authorization(set(), context=_context(), app_config=app_config) == set()


def test_filter_available_skills_rbac_allow_subset(monkeypatch):
    """Role allowlist intersects with the agent allowlist."""
    provider = _rbac_provider({"user": {"skills": {"allow": ["skill-a", "skill-c"]}}})
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.skill_filter.resolve_authorization_provider",
        lambda config: provider,
    )

    result = filter_available_skills_by_authorization(
        {"skill-a", "skill-b", "skill-c"},
        context=_context(),
        app_config=app_config,
    )
    assert result == {"skill-a", "skill-c"}


def test_filter_available_skills_provider_injected_names_excluded(monkeypatch):
    """A buggy provider that returns names outside candidates can't expand the allowlist.

    Regression for zhfeng's P2 finding: filter_resources contract says results
    must be a subset of candidates, but only list[str] is validated. The filter
    must intersect the provider result with candidates so injected names are dropped.
    """

    class _InjectingProvider:
        name = "injecting"

        def filter_resources(self, principal, resource_type, candidates):
            # Returns a name not in the candidate set (simulating a buggy provider).
            return ["allowed-skill", "injected-skill"]

        def authorize(self, request):
            return None

        async def aauthorize(self, request):
            return None

    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.skill_filter.resolve_authorization_provider",
        lambda config: _InjectingProvider(),
    )

    result = filter_available_skills_by_authorization(
        {"allowed-skill"},
        context=_context(),
        app_config=app_config,
    )
    # injected-skill was never a candidate, so it must not appear.
    assert result == {"allowed-skill"}
    assert "injected-skill" not in result


def test_filter_available_skills_rbac_deny(monkeypatch):
    """Deny removes a skill even when allow is wildcard."""
    provider = _rbac_provider({"user": {"skills": {"allow": "*", "deny": ["skill-b"]}}})
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.skill_filter.resolve_authorization_provider",
        lambda config: provider,
    )

    result = filter_available_skills_by_authorization(
        {"skill-a", "skill-b", "skill-c"},
        context=_context(),
        app_config=app_config,
    )
    assert result == {"skill-a", "skill-c"}


def test_filter_available_skills_wildcard_returns_all(monkeypatch):
    """Allow: '*' preserves the full allowlist."""
    provider = _rbac_provider({"user": {"skills": {"allow": "*"}}})
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.skill_filter.resolve_authorization_provider",
        lambda config: provider,
    )

    result = filter_available_skills_by_authorization(
        {"skill-a", "skill-b"},
        context=_context(),
        app_config=app_config,
    )
    assert result == {"skill-a", "skill-b"}


def test_filter_available_skills_empty_allowlist_preserved(monkeypatch):
    """Empty set (no skills for this agent) is preserved as-is."""
    provider = _rbac_provider({"user": {"skills": {"allow": "*"}}})
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.skill_filter.resolve_authorization_provider",
        lambda config: provider,
    )

    result = filter_available_skills_by_authorization(
        set(),
        context=_context(),
        app_config=app_config,
    )
    assert result == set()


def test_filter_available_skills_provider_error_fail_closed(monkeypatch):
    """Provider error + fail_closed → empty set (deny all skills)."""

    class _ErrorProvider:
        name = "error"

        def authorize(self, request):
            raise RuntimeError("boom")

        async def aauthorize(self, request):
            raise RuntimeError("boom")

        def filter_resources(self, principal, resource_type, candidates):
            raise RuntimeError("boom")

    app_config = _make_app_config()
    _enable_authz(app_config, fail_closed=True)
    monkeypatch.setattr(
        "deerflow.authz.skill_filter.resolve_authorization_provider",
        lambda config: _ErrorProvider(),
    )

    result = filter_available_skills_by_authorization(
        {"skill-a", "skill-b"},
        context=_context(),
        app_config=app_config,
    )
    assert result == set()


def test_filter_available_skills_provider_error_fail_open(monkeypatch):
    """Provider error + fail_open → original allowlist preserved."""

    class _ErrorProvider:
        name = "error"

        def authorize(self, request):
            raise RuntimeError("boom")

        async def aauthorize(self, request):
            raise RuntimeError("boom")

        def filter_resources(self, principal, resource_type, candidates):
            raise RuntimeError("boom")

    app_config = _make_app_config()
    _enable_authz(app_config, fail_closed=False)
    monkeypatch.setattr(
        "deerflow.authz.skill_filter.resolve_authorization_provider",
        lambda config: _ErrorProvider(),
    )

    result = filter_available_skills_by_authorization(
        {"skill-a", "skill-b"},
        context=_context(),
        app_config=app_config,
    )
    assert result == {"skill-a", "skill-b"}


def test_filter_available_skills_internal_caller_uses_default_role(monkeypatch):
    """Internal callers (system_role=internal) fall under default_role."""
    provider = _rbac_provider(
        {
            "user": {"skills": {"allow": ["skill-a"]}},
            "admin": {"skills": {"allow": "*"}},
        }
    )
    app_config = _make_app_config()
    _enable_authz(app_config, default_role="user")
    monkeypatch.setattr(
        "deerflow.authz.skill_filter.resolve_authorization_provider",
        lambda config: provider,
    )

    # Internal caller with system_role=None → default_role="user"
    result = filter_available_skills_by_authorization(
        {"skill-a", "skill-b"},
        context=_context(user_role=None, is_internal=True),
        app_config=app_config,
    )
    assert result == {"skill-a"}


def test_filter_available_skills_candidate_resolution_error_fail_closed(monkeypatch):
    """available_skills=None + candidate-set resolution error + fail_closed → empty set.

    Regression for willem-bd's fail-open bypass finding: when there is no
    agent-level allowlist (``available_skills=None``) and
    ``_all_configured_skill_names`` raises (storage I/O error), the result must
    NOT be ``None`` (which would bypass authorization — every skill becomes
    activatable/loadable via SkillActivationMiddleware and subagent _load_skills).
    With ``fail_closed=true`` it must return an empty set (deny all).
    """
    provider = _rbac_provider({"user": {"skills": {"allow": "*"}}})
    app_config = _make_app_config()
    _enable_authz(app_config, fail_closed=True)
    monkeypatch.setattr(
        "deerflow.authz.skill_filter.resolve_authorization_provider",
        lambda config: provider,
    )
    monkeypatch.setattr(
        "deerflow.authz.skill_filter._all_configured_skill_names",
        lambda app_config, **kw: (_ for _ in ()).throw(RuntimeError("storage I/O failed")),
    )

    result = filter_available_skills_by_authorization(
        None,
        context=_context(),
        app_config=app_config,
    )
    # fail-closed → deny all skills, NOT None (which would bypass authorization).
    assert result == set()


def test_filter_available_skills_candidate_resolution_error_fail_open(monkeypatch):
    """available_skills=None + candidate-set resolution error + fail_open → None.

    Fail-open preserves the legacy "no constraint" behavior (None = unrestricted),
    matching how provider errors are handled in the fail-open branch above.
    """
    provider = _rbac_provider({"user": {"skills": {"allow": "*"}}})
    app_config = _make_app_config()
    _enable_authz(app_config, fail_closed=False)
    monkeypatch.setattr(
        "deerflow.authz.skill_filter.resolve_authorization_provider",
        lambda config: provider,
    )
    monkeypatch.setattr(
        "deerflow.authz.skill_filter._all_configured_skill_names",
        lambda app_config, **kw: (_ for _ in ()).throw(RuntimeError("storage I/O failed")),
    )

    result = filter_available_skills_by_authorization(
        None,
        context=_context(),
        app_config=app_config,
    )
    # fail-open → unrestricted (None), matching provider-error fail-open behavior.
    assert result is None


def test_filter_available_skills_none_with_empty_config_no_bypass(monkeypatch):
    """available_skills=None + zero configured skills → None (no bypass, nothing to load).

    Distinct from the resolution-error case: when ``_all_configured_skill_names``
    succeeds and returns an empty list (the user genuinely configured no skills),
    returning ``None`` is safe because there is nothing for SkillActivationMiddleware
    or subagent _load_skills to activate/load.
    """
    provider = _rbac_provider({"user": {"skills": {"allow": "*"}}})
    app_config = _make_app_config()
    _enable_authz(app_config, fail_closed=True)
    monkeypatch.setattr(
        "deerflow.authz.skill_filter.resolve_authorization_provider",
        lambda config: provider,
    )
    # Resolution succeeds, but the configured-skill set is genuinely empty.
    monkeypatch.setattr(
        "deerflow.authz.skill_filter._all_configured_skill_names",
        lambda app_config, **kw: [],
    )

    result = filter_available_skills_by_authorization(
        None,
        context=_context(),
        app_config=app_config,
    )
    assert result is None


def test_filter_available_skills_user_id_threads_into_candidate_resolution(monkeypatch):
    """user_id is forwarded to _all_configured_skill_names so per-user custom skills are candidates.

    Regression for willem-bd's Round 3 finding: when available_skills=None and
    authz is enabled, the candidate universe must include per-user custom skills
    (UserScopedSkillStorage), not just the process-global public skills. Otherwise
    a skills:{allow:"*"} wildcard can never reach per-user custom skills, and
    SkillActivationMiddleware blocks them.
    """
    provider = _rbac_provider({"user": {"skills": {"allow": "*"}}})
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.skill_filter.resolve_authorization_provider",
        lambda config: provider,
    )

    captured = {}

    def _record(app_config, *, user_id=None):
        captured["user_id"] = user_id
        # Simulate a per-user custom skill that only user-scoped storage would return.
        return ["public-skill", "user-custom-skill"]

    monkeypatch.setattr(
        "deerflow.authz.skill_filter._all_configured_skill_names",
        _record,
    )

    result = filter_available_skills_by_authorization(
        None,
        context=_context(user_id="user-123"),
        app_config=app_config,
        user_id="user-123",
    )
    # The user_id was forwarded to the resolver.
    assert captured["user_id"] == "user-123"
    # The per-user custom skill is in the filtered set (wildcard allows all).
    assert result == {"public-skill", "user-custom-skill"}


def test_filter_available_skills_omits_user_id_when_not_provided(monkeypatch):
    """When user_id is not passed, candidate resolution uses global storage (user_id=None)."""
    provider = _rbac_provider({"user": {"skills": {"allow": "*"}}})
    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.skill_filter.resolve_authorization_provider",
        lambda config: provider,
    )

    captured = {}

    def _record(app_config, *, user_id=None):
        captured["user_id"] = user_id
        return ["public-skill"]

    monkeypatch.setattr(
        "deerflow.authz.skill_filter._all_configured_skill_names",
        _record,
    )

    filter_available_skills_by_authorization(
        None,
        context=_context(),
        app_config=app_config,
        # user_id deliberately omitted (e.g. caller has no user context).
    )
    assert captured["user_id"] is None


# ── filter_resources_by_authorization (generic) ────────────────────────


def _named(name: str):
    return SimpleNamespace(name=name)


def test_filter_resources_by_authorization_no_provider():
    """No provider → original list returned."""
    principal = build_principal_from_context(_context(), default_role="user")
    resources = [_named("a"), _named("b")]
    assert filter_resources_by_authorization(resources, resource_type="skill", provider=None, principal=principal, fail_closed=True) == resources


def test_filter_resources_by_authorization_rbac(monkeypatch):
    """Generic filter works with any resource type."""
    provider = _rbac_provider({"user": {"skills": {"allow": ["a"], "deny": ["c"]}}})
    principal = build_principal_from_context(_context(), default_role="user")
    resources = [_named("a"), _named("b"), _named("c")]

    result = filter_resources_by_authorization(
        resources,
        resource_type="skill",
        provider=provider,
        principal=principal,
        fail_closed=True,
    )
    assert [r.name for r in result] == ["a"]


def test_filter_resources_by_authorization_provider_error_fail_closed():
    """Provider error + fail_closed → empty list."""

    class _ErrorProvider:
        name = "error"

        def authorize(self, request):
            raise RuntimeError("boom")

        async def aauthorize(self, request):
            raise RuntimeError("boom")

        def filter_resources(self, principal, resource_type, candidates):
            raise RuntimeError("boom")

    principal = build_principal_from_context(_context(), default_role="user")
    resources = [_named("a"), _named("b")]
    result = filter_resources_by_authorization(
        resources,
        resource_type="skill",
        provider=_ErrorProvider(),
        principal=principal,
        fail_closed=True,
    )
    assert result == []


def test_filter_resources_by_authorization_preserves_order():
    """Original order is preserved in the filtered result."""
    provider = _rbac_provider({"user": {"skills": {"allow": "*"}}})
    principal = build_principal_from_context(_context(), default_role="user")
    resources = [_named("z"), _named("a"), _named("m")]
    result = filter_resources_by_authorization(
        resources,
        resource_type="skill",
        provider=provider,
        principal=principal,
        fail_closed=True,
    )
    assert [r.name for r in result] == ["z", "a", "m"]


# ── DeerFlowClient._ensure_agent path ─────────────────────────────────
# Regression for willem-bd's Round 2 coverage observation: the embedded
# lead-agent construction path (DeerFlowClient._ensure_agent) must filter
# skills through authorization too, mirroring _make_lead_agent. Otherwise a
# caller building the agent via DeerFlowClient(available_skills=...) bypasses
# the role's skills policy.


def test_client_ensure_agent_filters_skills_by_authorization(monkeypatch):
    """_ensure_agent passes an authorization-filtered skill set to build_middlewares.

    Real-path test: a genuine RbacAuthorizationProvider denies 'denied-skill'
    for the 'user' role. The embedded _ensure_agent must filter it out before
    wiring SkillActivationMiddleware, so the denied skill can't be slash-activated.
    """
    from langchain_core.runnables import RunnableConfig

    from deerflow.client import DeerFlowClient

    app_config = _make_app_config()
    _enable_authz(app_config)
    provider = _rbac_provider({"user": {"skills": {"allow": ["allowed-skill"], "deny": ["denied-skill"]}}})
    monkeypatch.setattr(
        "deerflow.authz.skill_filter.resolve_authorization_provider",
        lambda config: provider,
    )
    monkeypatch.setattr(
        "deerflow.authz.tool_filter.resolve_authorization_provider",
        lambda config: _rbac_provider({"user": {"tools": {"allow": "*"}}}),
    )
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.agent.resolve_authorization_provider",
        lambda config: _rbac_provider({"user": {"models": {"allow": "*"}}}),
    )

    captured = {}

    def _capture_build_middlewares(*args, **kwargs):
        captured["available_skills"] = kwargs.get("available_skills")
        return []

    monkeypatch.setattr("deerflow.client.create_chat_model", lambda **kw: object())
    monkeypatch.setattr("deerflow.client.create_agent", lambda **kw: object())
    monkeypatch.setattr("deerflow.client.build_middlewares", _capture_build_middlewares)
    monkeypatch.setattr("deerflow.client.DeerFlowClient._get_tools", staticmethod(lambda *, model_name, subagent_enabled: []))
    monkeypatch.setattr("deerflow.client.get_enabled_skills_for_config", lambda app_config, **kw: [])
    monkeypatch.setattr(
        "deerflow.client.build_skill_search_setup",
        lambda skills, *, enabled, container_base_path, skill_authorization=None: SimpleNamespace(describe_skill_tool=None, skill_names=frozenset()),
    )
    monkeypatch.setattr(
        "deerflow.client.assemble_deferred_tools",
        lambda tools, *, enabled: ([], SimpleNamespace(deferred_names=frozenset())),
    )
    monkeypatch.setattr("deerflow.client.build_mcp_routing_middleware", lambda *a, **kw: None)
    monkeypatch.setattr("deerflow.client.get_mcp_routing_hints_prompt_section", lambda *a, **kw: "")
    monkeypatch.setattr("deerflow.client.apply_prompt_template", lambda **kw: "")
    monkeypatch.setattr("deerflow.client.get_thread_state_schema", lambda *a, **kw: object())
    monkeypatch.setattr("deerflow.client.normalize_middleware_state_schemas", lambda schemas, mode, freq: [])
    monkeypatch.setattr("deerflow.client.get_effective_user_id", lambda: "user-123")

    client = DeerFlowClient.__new__(DeerFlowClient)
    client._app_config = app_config
    client._agent_name = "default"
    client._available_skills = {"allowed-skill", "denied-skill"}
    client._checkpoint_channel_mode = "full"
    client._checkpoint_snapshot_frequency = None
    client._middlewares = []
    client._agent = None
    client._agent_config_key = None
    client._checkpointer = object()

    config = RunnableConfig(configurable={"user_id": "user-123", "user_role": "user"})
    client._ensure_agent(config)

    # The denied skill was filtered out; only 'allowed-skill' reaches the middleware.
    assert captured["available_skills"] == {"allowed-skill"}


def test_client_ensure_agent_noop_when_authorization_disabled(monkeypatch):
    """When authorization is disabled, _ensure_agent leaves the skill set unchanged."""
    from langchain_core.runnables import RunnableConfig

    from deerflow.client import DeerFlowClient

    app_config = _make_app_config()
    # AuthorizationConfig() defaults to enabled=False.

    captured = {}

    def _capture_build_middlewares(*args, **kwargs):
        captured["available_skills"] = kwargs.get("available_skills")
        return []

    monkeypatch.setattr("deerflow.client.create_chat_model", lambda **kw: object())
    monkeypatch.setattr("deerflow.client.create_agent", lambda **kw: object())
    monkeypatch.setattr("deerflow.client.build_middlewares", _capture_build_middlewares)
    monkeypatch.setattr("deerflow.client.DeerFlowClient._get_tools", staticmethod(lambda *, model_name, subagent_enabled: []))
    monkeypatch.setattr("deerflow.client.get_enabled_skills_for_config", lambda app_config, **kw: [])
    monkeypatch.setattr(
        "deerflow.client.build_skill_search_setup",
        lambda skills, *, enabled, container_base_path, skill_authorization=None: SimpleNamespace(describe_skill_tool=None, skill_names=frozenset()),
    )
    monkeypatch.setattr(
        "deerflow.client.assemble_deferred_tools",
        lambda tools, *, enabled: ([], SimpleNamespace(deferred_names=frozenset())),
    )
    monkeypatch.setattr("deerflow.client.build_mcp_routing_middleware", lambda *a, **kw: None)
    monkeypatch.setattr("deerflow.client.get_mcp_routing_hints_prompt_section", lambda *a, **kw: "")
    monkeypatch.setattr("deerflow.client.apply_prompt_template", lambda **kw: "")
    monkeypatch.setattr("deerflow.client.get_thread_state_schema", lambda *a, **kw: object())
    monkeypatch.setattr("deerflow.client.normalize_middleware_state_schemas", lambda schemas, mode, freq: [])
    monkeypatch.setattr("deerflow.client.get_effective_user_id", lambda: "user-123")

    client = DeerFlowClient.__new__(DeerFlowClient)
    client._app_config = app_config
    client._agent_name = "default"
    client._available_skills = {"skill-a", "skill-b"}
    client._checkpoint_channel_mode = "full"
    client._checkpoint_snapshot_frequency = None
    client._middlewares = []
    client._agent = None
    client._agent_config_key = None
    client._checkpointer = object()

    config = RunnableConfig(configurable={"user_id": "user-123", "user_role": "user"})
    client._ensure_agent(config)

    # Disabled → no-op: original skill set passed through unchanged.
    assert captured["available_skills"] == {"skill-a", "skill-b"}


# ── Runtime skill:activate enforcement (Layer 2) ──────────────────────


class _ActionAwareProvider:
    """Minimal provider distinguishing visibility (filter_resources) from activation."""

    def __init__(self, *, denied_activate: set[str]):
        self.denied_activate = denied_activate
        self.sync_calls: list[str] = []
        self.async_calls: list[str] = []

    def filter_resources(self, principal, resource, candidates):
        return list(candidates)

    def authorize(self, request):
        from deerflow.authz.provider import AuthzDecision

        if request.resource == "skill" and request.action == "activate":
            self.sync_calls.append(request.target)
        if request.resource == "skill" and request.action == "activate" and request.target in self.denied_activate:
            return AuthzDecision(allow=False)
        return AuthzDecision(allow=True)

    async def aauthorize(self, request):
        from deerflow.authz.provider import AuthzDecision

        if request.resource == "skill" and request.action == "activate":
            self.async_calls.append(request.target)
        if request.resource == "skill" and request.action == "activate" and request.target in self.denied_activate:
            return AuthzDecision(allow=False)
        return AuthzDecision(allow=True)


class _RaisingAuthorizeProvider(_ActionAwareProvider):
    def authorize(self, request):
        raise RuntimeError("provider blew up")

    async def aauthorize(self, request):
        raise RuntimeError("provider blew up")


class _AsyncOnlyProvider:
    """Loop-affine provider: the sync API is the wrong one and always fails.

    Models a provider whose clients are bound to the running event loop —
    ``authorize()`` from a worker thread or the loop itself is unsupported,
    while ``aauthorize()`` works. Async paths must use the async API; if they
    fall back to the sync call, fail-closed denies (or fail-open admits) with
    the wrong semantics.
    """

    name = "async-only"

    def __init__(self, *, denied_activate: set[str] = set()):
        self.denied_activate = denied_activate
        self.async_calls: list[str] = []

    def filter_resources(self, principal, resource, candidates):
        return list(candidates)

    def authorize(self, request):
        raise RuntimeError("sync authorize() is not supported by this provider")

    async def aauthorize(self, request):
        from deerflow.authz.provider import AuthzDecision

        if request.resource == "skill" and request.action == "activate":
            self.async_calls.append(request.target)
        if request.resource == "skill" and request.action == "activate" and request.target in self.denied_activate:
            return AuthzDecision(allow=False)
        return AuthzDecision(allow=True)


def _resolved_skill_authorization(provider, *, fail_closed: bool):
    from deerflow.authz.skill_filter import resolve_skill_authorization

    app_config = _make_app_config()
    _enable_authz(app_config, fail_closed=fail_closed)
    import deerflow.authz.skill_filter as skill_filter_module

    original = skill_filter_module.resolve_authorization_provider
    skill_filter_module.resolve_authorization_provider = lambda config: provider
    try:
        resolved = resolve_skill_authorization(_context(), app_config)
    finally:
        skill_filter_module.resolve_authorization_provider = original
    assert resolved is not None
    return resolved


def _middleware_for(tmp_path, monkeypatch, skills, **kwargs):
    from pathlib import Path

    from deerflow.agents.middlewares import skill_activation_middleware as middleware_module
    from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware
    from deerflow.skills.types import Skill as SkillObject
    from deerflow.skills.types import SkillCategory

    def _make_skill(name: str) -> SkillObject:
        skill_dir = tmp_path / name
        skill_dir.mkdir(exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(f"# {name}\nskill body", encoding="utf-8")
        return SkillObject(
            name=name,
            description=f"Description for {name}",
            license="MIT",
            skill_dir=skill_dir,
            skill_file=skill_file,
            relative_path=Path(name),
            category=SkillCategory.CUSTOM,
            enabled=True,
        )

    made = [_make_skill(name) for name in skills]

    def _validate_skill_file_path(skill_file):
        resolved = skill_file.resolve()
        resolved.relative_to(tmp_path.resolve())
        return resolved

    storage = SimpleNamespace(
        load_skills=lambda *, enabled_only: made,
        get_container_root=lambda: "/mnt/skills",
        get_skills_root_path=lambda: tmp_path,
        validate_skill_file_path=_validate_skill_file_path,
    )
    monkeypatch.setattr(middleware_module, "get_or_new_skill_storage", lambda **kw: storage)
    return SkillActivationMiddleware(slash_source_owner_token="test-token", **kwargs)


def test_activation_enforces_action_scoped_activate_decision(tmp_path, monkeypatch):
    """A skill visible in the Layer 1 set but denied by authorize(activate)
    must not slash-activate, while an allowed one still does (review repro)."""
    provider = _ActionAwareProvider(denied_activate={"demo-skill"})
    resolved = _resolved_skill_authorization(provider, fail_closed=True)
    middleware = _middleware_for(
        tmp_path,
        monkeypatch,
        ["demo-skill", "other-skill"],
        available_skills={"demo-skill", "other-skill"},
        skill_authorization=resolved,
    )

    denied = middleware._resolve_activation("/demo-skill analyze this")
    assert denied is not None
    assert denied.activation is None
    assert "not available" in denied.failure_message

    allowed = middleware._resolve_activation("/other-skill analyze this")
    assert allowed is not None
    assert allowed.activation is not None
    assert allowed.activation.skill_name == "other-skill"


def test_activation_provider_error_fail_closed(tmp_path, monkeypatch):
    """authorize() raising under fail_closed=True denies activation."""
    provider = _RaisingAuthorizeProvider(denied_activate=set())
    resolved = _resolved_skill_authorization(provider, fail_closed=True)
    middleware = _middleware_for(
        tmp_path,
        monkeypatch,
        ["demo-skill"],
        available_skills={"demo-skill"},
        skill_authorization=resolved,
    )

    result = middleware._resolve_activation("/demo-skill hi")
    assert result is not None
    assert result.activation is None
    assert "not available" in result.failure_message


def test_activation_provider_error_fail_open(tmp_path, monkeypatch):
    """authorize() raising under fail_closed=False allows (fail-open policy)."""
    provider = _RaisingAuthorizeProvider(denied_activate=set())
    resolved = _resolved_skill_authorization(provider, fail_closed=False)
    middleware = _middleware_for(
        tmp_path,
        monkeypatch,
        ["demo-skill"],
        available_skills={"demo-skill"},
        skill_authorization=resolved,
    )

    result = middleware._resolve_activation("/demo-skill hi")
    assert result is not None
    assert result.activation is not None


def test_activation_rbac_provider_membership_equivalent(tmp_path, monkeypatch):
    """Built-in RBAC (action-agnostic) keeps working: allowed skill activates."""
    provider = _rbac_provider({"user": {"skills": {"allow": "*"}}})
    resolved = _resolved_skill_authorization(provider, fail_closed=True)
    middleware = _middleware_for(
        tmp_path,
        monkeypatch,
        ["demo-skill"],
        available_skills={"demo-skill"},
        skill_authorization=resolved,
    )

    result = middleware._resolve_activation("/demo-skill hi")
    assert result is not None
    assert result.activation is not None


def test_client_wires_skill_authorization_into_middleware(monkeypatch):
    """_ensure_agent resolves the skill authorization context once and passes
    it to build_middlewares so SkillActivationMiddleware enforces skill:activate."""
    from langchain_core.runnables import RunnableConfig

    from deerflow.authz.skill_filter import ResolvedSkillAuthorization
    from deerflow.client import DeerFlowClient

    app_config = _make_app_config()
    _enable_authz(app_config)
    provider = _rbac_provider({"user": {"skills": {"allow": "*"}}})
    monkeypatch.setattr(
        "deerflow.authz.skill_filter.resolve_authorization_provider",
        lambda config: provider,
    )
    monkeypatch.setattr(
        "deerflow.authz.tool_filter.resolve_authorization_provider",
        lambda config: _rbac_provider({"user": {"tools": {"allow": "*"}}}),
    )
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.agent.resolve_authorization_provider",
        lambda config: _rbac_provider({"user": {"models": {"allow": "*"}}}),
    )

    captured = {}

    def _capture_build_middlewares(*args, **kwargs):
        captured["skill_authorization"] = kwargs.get("skill_authorization")
        return []

    monkeypatch.setattr("deerflow.client.create_chat_model", lambda **kw: object())
    monkeypatch.setattr("deerflow.client.create_agent", lambda **kw: object())
    monkeypatch.setattr("deerflow.client.build_middlewares", _capture_build_middlewares)
    monkeypatch.setattr("deerflow.client.DeerFlowClient._get_tools", staticmethod(lambda *, model_name, subagent_enabled: []))
    monkeypatch.setattr("deerflow.client.get_enabled_skills_for_config", lambda app_config, **kw: [])
    monkeypatch.setattr(
        "deerflow.client.build_skill_search_setup",
        lambda skills, *, enabled, container_base_path, skill_authorization=None: SimpleNamespace(describe_skill_tool=None, skill_names=frozenset()),
    )
    monkeypatch.setattr(
        "deerflow.client.assemble_deferred_tools",
        lambda tools, *, enabled: ([], SimpleNamespace(deferred_names=frozenset())),
    )
    monkeypatch.setattr("deerflow.client.build_mcp_routing_middleware", lambda *a, **kw: None)
    monkeypatch.setattr("deerflow.client.get_mcp_routing_hints_prompt_section", lambda *a, **kw: "")
    monkeypatch.setattr("deerflow.client.apply_prompt_template", lambda **kw: "")
    monkeypatch.setattr("deerflow.client.get_thread_state_schema", lambda *a, **kw: object())
    monkeypatch.setattr("deerflow.client.normalize_middleware_state_schemas", lambda schemas, mode, freq: [])
    monkeypatch.setattr("deerflow.client.get_effective_user_id", lambda: "user-123")

    client = DeerFlowClient.__new__(DeerFlowClient)
    client._app_config = app_config
    client._agent_name = "default"
    client._available_skills = None
    client._checkpoint_channel_mode = "full"
    client._checkpoint_snapshot_frequency = None
    client._middlewares = []
    client._agent = None
    client._agent_config_key = None
    client._checkpointer = object()

    client._ensure_agent(RunnableConfig(configurable={"user_id": "user-123", "user_role": "user"}))

    wired = captured["skill_authorization"]
    assert isinstance(wired, ResolvedSkillAuthorization)
    assert wired.provider is provider
    assert wired.fail_closed is True


def test_client_filter_candidates_reuse_catalog_loader(monkeypatch):
    """With no agent-level allowlist, the filter's candidates come from the
    cached catalog loader — the filter's uncached storage scan never runs."""
    from langchain_core.runnables import RunnableConfig

    from deerflow.client import DeerFlowClient

    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.skill_filter.resolve_authorization_provider",
        lambda config: _rbac_provider({"user": {"skills": {"allow": "*"}}}),
    )
    monkeypatch.setattr(
        "deerflow.authz.tool_filter.resolve_authorization_provider",
        lambda config: _rbac_provider({"user": {"tools": {"allow": "*"}}}),
    )
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.agent.resolve_authorization_provider",
        lambda config: _rbac_provider({"user": {"models": {"allow": "*"}}}),
    )

    catalog_calls = {"count": 0}

    def _catalog_loader(app_config, **kw):
        catalog_calls["count"] += 1
        return [SimpleNamespace(name="catalog-skill")]

    def _must_not_scan(*a, **kw):
        raise AssertionError("filter must not rescan storage when candidates were provided")

    monkeypatch.setattr("deerflow.client.get_enabled_skills_for_config", _catalog_loader)
    monkeypatch.setattr("deerflow.authz.skill_filter._all_configured_skill_names", _must_not_scan)

    import deerflow.authz.skill_filter as skill_filter_module

    captured = {}
    _original_filter = skill_filter_module.filter_available_skills_by_authorization

    def _filter_spy(available_skills, **kwargs):
        captured["candidate_skill_names"] = kwargs.get("candidate_skill_names")
        return _original_filter(available_skills, **kwargs)

    # client._ensure_agent lazy-imports the filter from this module, so the
    # spy has to replace it at the source.
    monkeypatch.setattr(skill_filter_module, "filter_available_skills_by_authorization", _filter_spy)
    monkeypatch.setattr("deerflow.client.create_chat_model", lambda **kw: object())
    monkeypatch.setattr("deerflow.client.create_agent", lambda **kw: object())
    monkeypatch.setattr("deerflow.client.build_middlewares", lambda *a, **kw: [])
    monkeypatch.setattr("deerflow.client.DeerFlowClient._get_tools", staticmethod(lambda *, model_name, subagent_enabled: []))
    monkeypatch.setattr(
        "deerflow.client.build_skill_search_setup",
        lambda skills, *, enabled, container_base_path, skill_authorization=None: SimpleNamespace(describe_skill_tool=None, skill_names=frozenset()),
    )
    monkeypatch.setattr(
        "deerflow.client.assemble_deferred_tools",
        lambda tools, *, enabled: ([], SimpleNamespace(deferred_names=frozenset())),
    )
    monkeypatch.setattr("deerflow.client.build_mcp_routing_middleware", lambda *a, **kw: None)
    monkeypatch.setattr("deerflow.client.get_mcp_routing_hints_prompt_section", lambda *a, **kw: "")
    monkeypatch.setattr("deerflow.client.apply_prompt_template", lambda **kw: "")
    monkeypatch.setattr("deerflow.client.get_thread_state_schema", lambda *a, **kw: object())
    monkeypatch.setattr("deerflow.client.normalize_middleware_state_schemas", lambda schemas, mode, freq: [])
    monkeypatch.setattr("deerflow.client.get_effective_user_id", lambda: "user-123")

    client = DeerFlowClient.__new__(DeerFlowClient)
    client._app_config = app_config
    client._agent_name = "default"
    client._available_skills = None  # no agent-level allowlist → candidates matter
    client._checkpoint_channel_mode = "full"
    client._checkpoint_snapshot_frequency = None
    client._middlewares = []
    client._agent = None
    client._agent_config_key = None
    client._checkpointer = object()

    client._ensure_agent(RunnableConfig(configurable={"user_id": "user-123", "user_role": "user"}))

    assert captured["candidate_skill_names"] == ["catalog-skill"]
    assert catalog_calls["count"] >= 1


def test_subagent_chain_arms_skill_activate_check(monkeypatch):
    """build_subagent_runtime_middlewares forwards skill_authorization into the
    subagent chain's SkillActivationMiddleware (a delegated task is a plain
    HumanMessage, so /skill-name in task text reaches the activation path)."""
    import deerflow.authz.skill_filter as skill_filter_module
    from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware
    from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares
    from deerflow.authz.skill_filter import resolve_skill_authorization

    app_config = _make_app_config()
    _enable_authz(app_config)
    provider = _rbac_provider({"user": {"skills": {"allow": "*"}}})
    monkeypatch.setattr(skill_filter_module, "resolve_authorization_provider", lambda config: provider)

    resolved = resolve_skill_authorization(_context(), app_config)
    assert resolved is not None

    middlewares = build_subagent_runtime_middlewares(
        app_config=app_config,
        model_name=None,
        lazy_init=True,
        available_skills={"demo-skill"},
        user_id="user-123",
        authorization_provider=provider,
        skill_authorization=resolved,
    )

    activation = [m for m in middlewares if isinstance(m, SkillActivationMiddleware)]
    assert len(activation) == 1
    assert activation[0]._skill_authorization is resolved

    # The skill-read stamp gate on the same chain shares the resolved context
    # so an autonomously read SKILL.md cannot activate a denied skill.
    from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware

    stampers = [m for m in middlewares if isinstance(m, ToolErrorHandlingMiddleware)]
    assert len(stampers) == 1
    assert stampers[0]._skill_authorization is resolved


def test_subagent_executor_resolves_skill_authorization_for_chain(monkeypatch):
    """SubagentExecutor._create_agent passes a resolved ResolvedSkillAuthorization
    into build_subagent_runtime_middlewares, built from the executor identity."""
    import importlib
    import sys
    from types import SimpleNamespace

    import deerflow.authz.skill_filter as skill_filter_module
    from deerflow.authz.skill_filter import ResolvedSkillAuthorization

    # tests/conftest.py injects a MagicMock for deerflow.subagents.executor to
    # break a production circular import; load the real module for this test
    # (same pattern as tests/test_delegation_ledger_live.py).
    sys.modules.pop("deerflow.subagents.executor", None)
    executor_module = importlib.import_module("deerflow.subagents.executor")
    SubagentExecutor = executor_module.SubagentExecutor

    app_config = _make_app_config()
    _enable_authz(app_config)
    provider = _rbac_provider({"user": {"skills": {"allow": "*"}}})
    monkeypatch.setattr(skill_filter_module, "resolve_authorization_provider", lambda config: provider)
    monkeypatch.setattr(executor_module, "create_chat_model", lambda **kw: object())
    monkeypatch.setattr(executor_module, "resolve_subagent_model_name", lambda *a, **kw: "m")

    captured = {}

    def _capture_builder(**kwargs):
        captured["skill_authorization"] = kwargs.get("skill_authorization")
        return []

    monkeypatch.setattr(
        "deerflow.agents.middlewares.tool_error_handling_middleware.build_subagent_runtime_middlewares",
        _capture_builder,
    )

    executor = SubagentExecutor.__new__(SubagentExecutor)
    executor.config = SimpleNamespace(name="sub", skills=None)
    executor.model_name = "m"
    executor.app_config = app_config
    executor._resolved_app_config = app_config
    executor._available_skill_names = None
    executor.extensions = None
    executor.user_id = "user-123"
    executor.user_role = "user"
    executor.oauth_provider = None
    executor.oauth_id = None
    executor.channel_user_id = None
    executor.is_internal = False
    executor.authz_attributes = None
    executor.tools = []

    executor._create_agent(tools=[])

    wired = captured["skill_authorization"]
    assert isinstance(wired, ResolvedSkillAuthorization)
    assert wired.provider is provider


def test_client_skill_surface_uses_one_effective_user(monkeypatch):
    """The filter, the candidate pre-load, and the catalog all resolve the same
    effective user — a request whose configurable carries no user_id must not
    fall back to the process-global skill bucket while the middleware loads
    user-scoped storage (per-user custom skills would then be filtered out)."""
    from langchain_core.runnables import RunnableConfig

    from deerflow.client import DeerFlowClient

    app_config = _make_app_config()
    _enable_authz(app_config)
    monkeypatch.setattr(
        "deerflow.authz.skill_filter.resolve_authorization_provider",
        lambda config: _rbac_provider({"user": {"skills": {"allow": "*"}}}),
    )
    monkeypatch.setattr(
        "deerflow.authz.tool_filter.resolve_authorization_provider",
        lambda config: _rbac_provider({"user": {"tools": {"allow": "*"}}}),
    )
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.agent.resolve_authorization_provider",
        lambda config: _rbac_provider({"user": {"models": {"allow": "*"}}}),
    )

    catalog_calls = []

    def _catalog_loader(app_config, **kw):
        catalog_calls.append(kw.get("user_id"))
        return [SimpleNamespace(name="catalog-skill")]

    monkeypatch.setattr("deerflow.client.get_enabled_skills_for_config", _catalog_loader)

    import deerflow.authz.skill_filter as skill_filter_module

    captured = {}
    _original_filter = skill_filter_module.filter_available_skills_by_authorization

    def _filter_spy(available_skills, **kwargs):
        captured["user_id"] = kwargs.get("user_id")
        return _original_filter(available_skills, **kwargs)

    monkeypatch.setattr(skill_filter_module, "filter_available_skills_by_authorization", _filter_spy)
    monkeypatch.setattr("deerflow.client.create_chat_model", lambda **kw: object())
    monkeypatch.setattr("deerflow.client.create_agent", lambda **kw: object())
    monkeypatch.setattr("deerflow.client.build_middlewares", lambda *a, **kw: [])
    monkeypatch.setattr("deerflow.client.DeerFlowClient._get_tools", staticmethod(lambda *, model_name, subagent_enabled: []))
    monkeypatch.setattr(
        "deerflow.client.build_skill_search_setup",
        lambda skills, *, enabled, container_base_path, skill_authorization=None: SimpleNamespace(describe_skill_tool=None, skill_names=frozenset()),
    )
    monkeypatch.setattr(
        "deerflow.client.assemble_deferred_tools",
        lambda tools, *, enabled: ([], SimpleNamespace(deferred_names=frozenset())),
    )
    monkeypatch.setattr("deerflow.client.build_mcp_routing_middleware", lambda *a, **kw: None)
    monkeypatch.setattr("deerflow.client.get_mcp_routing_hints_prompt_section", lambda *a, **kw: "")
    monkeypatch.setattr("deerflow.client.apply_prompt_template", lambda **kw: "")
    monkeypatch.setattr("deerflow.client.get_thread_state_schema", lambda *a, **kw: object())
    monkeypatch.setattr("deerflow.client.normalize_middleware_state_schemas", lambda schemas, mode, freq: [])
    # No user_id in configurable: the effective id must come from here.
    monkeypatch.setattr("deerflow.client.get_effective_user_id", lambda: "user-123")

    client = DeerFlowClient.__new__(DeerFlowClient)
    client._app_config = app_config
    client._agent_name = "default"
    client._available_skills = None
    client._checkpoint_channel_mode = "full"
    client._checkpoint_snapshot_frequency = None
    client._middlewares = []
    client._agent = None
    client._agent_config_key = None
    client._checkpointer = object()

    client._ensure_agent(RunnableConfig(configurable={"user_role": "user"}))

    # The filter, the candidate pre-load, and the catalog all used the
    # context-scoped effective user, never the global bucket.
    assert captured["user_id"] == "user-123"
    assert catalog_calls and all(call == "user-123" for call in catalog_calls)


# ── Autonomous path: describe_skill + skill-file-load gates (Layer 2) ──


def _describe_setup_for(provider, *, fail_closed: bool = True, skills=("demo-skill", "other-skill")):
    """Build a real describe_skill tool over *skills* with the provider wired."""
    from pathlib import Path

    from deerflow.skills.catalog import SkillCatalog
    from deerflow.skills.describe import build_describe_skill_tool
    from deerflow.skills.types import Skill as SkillObject
    from deerflow.skills.types import SkillCategory

    made = []
    for name in skills:
        base = Path("/mnt/skills/public") / name
        made.append(
            SkillObject(
                name=name,
                description=f"Description for {name}",
                license=None,
                skill_dir=base,
                skill_file=base / "SKILL.md",
                relative_path=Path(name),
                category=SkillCategory.PUBLIC,
                enabled=True,
            )
        )
    resolved = _resolved_skill_authorization(provider, fail_closed=fail_closed)
    return build_describe_skill_tool(SkillCatalog(tuple(made)), skill_authorization=resolved)


def _invoke_describe(tool, query: str) -> str:
    result = tool.invoke({"args": {"name": query}, "name": "describe_skill", "type": "tool_call", "id": "describe-call"})
    return result.update["messages"][0].content


def test_describe_skill_gates_on_activate_decision():
    """describe_skill omits skills denied by authorize(skill, activate) even
    though the Layer 1 catalog lists them — the autonomous load path must not
    be able to discover and read_file a skill whose activation is denied."""
    provider = _ActionAwareProvider(denied_activate={"demo-skill"})
    tool = _describe_setup_for(provider)

    content = _invoke_describe(tool, "select:demo-skill,other-skill")

    assert "other-skill" in content
    assert "demo-skill" not in content


def test_describe_skill_denied_only_reports_no_match():
    """A describe whose every match is denied is indistinguishable from a
    non-match (the denial reason is not leaked)."""
    provider = _ActionAwareProvider(denied_activate={"demo-skill"})
    tool = _describe_setup_for(provider, skills=("demo-skill",))

    content = _invoke_describe(tool, "select:demo-skill")

    assert "No skills matched" in content


def test_describe_skill_provider_error_fail_closed():
    provider = _RaisingAuthorizeProvider(denied_activate=set())
    tool = _describe_setup_for(provider, fail_closed=True)

    content = _invoke_describe(tool, "select:demo-skill")

    assert "No skills matched" in content


def test_describe_skill_provider_error_fail_open():
    provider = _RaisingAuthorizeProvider(denied_activate=set())
    tool = _describe_setup_for(provider, fail_closed=False)

    content = _invoke_describe(tool, "select:demo-skill")

    assert "demo-skill" in content


def test_describe_skill_disabled_authorization_describes_all():
    """Without a resolved authorization context the tool describes everything
    in the catalog (pre-authorization behavior)."""
    from pathlib import Path

    from deerflow.skills.catalog import SkillCatalog
    from deerflow.skills.describe import build_describe_skill_tool
    from deerflow.skills.types import Skill as SkillObject
    from deerflow.skills.types import SkillCategory

    made = []
    for name in ("demo-skill", "other-skill"):
        base = Path("/mnt/skills/public") / name
        made.append(
            SkillObject(
                name=name,
                description=f"Description for {name}",
                license=None,
                skill_dir=base,
                skill_file=base / "SKILL.md",
                relative_path=Path(name),
                category=SkillCategory.PUBLIC,
                enabled=True,
            )
        )
    tool = build_describe_skill_tool(SkillCatalog(tuple(made)))

    content = _invoke_describe(tool, "select:demo-skill,other-skill")

    assert "demo-skill" in content
    assert "other-skill" in content


# ── Skill-file-load stamping gate ─────────────────────────────────────


def _read_call_and_message(path: str):
    from langchain_core.messages import ToolMessage

    request = SimpleNamespace(tool_call={"name": "read_file", "id": "call-1", "args": {"path": path}})
    message = ToolMessage(content="---\ndescription: Demo skill\n---\n# demo", tool_call_id="call-1", name="read_file")
    return request, message


def test_skill_read_stamp_gates_on_activate_decision():
    """A completed SKILL.md read only records a skill_context entry when the
    action-scoped skill:activate decision allows it; a denied read gets the
    denial marker instead (no durable context, tool policy, or secrets)."""
    from deerflow.agents.middlewares.skill_context import SKILL_CONTEXT_DENIED_KEY, SKILL_CONTEXT_ENTRY_KEY
    from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware

    provider = _ActionAwareProvider(denied_activate={"demo-skill"})
    resolved = _resolved_skill_authorization(provider, fail_closed=True)
    middleware = ToolErrorHandlingMiddleware(app_config=_make_app_config(), skill_authorization=resolved)

    request, message = _read_call_and_message("/mnt/skills/public/demo-skill/SKILL.md")
    stamped = middleware._stamp_skill_read_metadata(message, request, tool_name="read_file")
    assert SKILL_CONTEXT_ENTRY_KEY not in stamped.additional_kwargs
    assert stamped.additional_kwargs.get(SKILL_CONTEXT_DENIED_KEY) is True

    request_ok, message_ok = _read_call_and_message("/mnt/skills/public/other-skill/SKILL.md")
    stamped_ok = middleware._stamp_skill_read_metadata(message_ok, request_ok, tool_name="read_file")
    assert SKILL_CONTEXT_DENIED_KEY not in stamped_ok.additional_kwargs
    assert SKILL_CONTEXT_ENTRY_KEY in stamped_ok.additional_kwargs


def test_extract_skills_skips_denied_reads_without_warning(caplog):
    """extract_skills treats the denial marker as intentional — no entry and
    no misleading 'missing skill read metadata' warning."""
    from langchain_core.messages import AIMessage, ToolMessage

    from deerflow.agents.middlewares import skill_context as skill_context_module
    from deerflow.agents.middlewares.skill_context import SKILL_CONTEXT_DENIED_KEY

    messages = [
        AIMessage(content="", tool_calls=[{"name": "read_file", "id": "call-1", "args": {"path": "/mnt/skills/public/demo-skill/SKILL.md"}}]),
        ToolMessage(content="# demo", tool_call_id="call-1", name="read_file", additional_kwargs={SKILL_CONTEXT_DENIED_KEY: True}),
    ]

    with caplog.at_level("WARNING", logger="deerflow.agents.middlewares.skill_context"):
        entries = skill_context_module.extract_skills(messages, skills_root="/mnt/skills", read_tool_names={"read_file"})

    assert entries == []
    assert not caplog.records


# ── Runtime-chain wiring for the autonomous-path gates ────────────────


def test_lead_runtime_chain_forwards_skill_authorization_to_stamp_gate():
    """build_lead_runtime_middlewares hands the resolved skill authorization to
    ToolErrorHandlingMiddleware so the skill-read stamp gate runs with the same
    provider instance the activation middleware uses."""
    from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware, build_lead_runtime_middlewares

    provider = _rbac_provider({"user": {"skills": {"allow": "*"}}})
    resolved = _resolved_skill_authorization(provider, fail_closed=True)

    middlewares = build_lead_runtime_middlewares(app_config=_make_app_config(), skill_authorization=resolved)

    stampers = [m for m in middlewares if isinstance(m, ToolErrorHandlingMiddleware)]
    assert len(stampers) == 1
    assert stampers[0]._skill_authorization is resolved


def test_subagent_executor_shares_one_skill_authorization_instance(monkeypatch):
    """[P2 regression] A provider factory returning a distinct instance per
    resolve must not split the subagent's layers: the Layer 1 filter in
    ``_load_skills`` and the runtime ``skill:activate`` checks in
    ``_create_agent`` see the same ResolvedSkillAuthorization (one resolve per
    executor assembly)."""
    import asyncio
    import importlib
    import sys

    import deerflow.authz.skill_filter as skill_filter_module
    from deerflow.authz.skill_filter import ResolvedSkillAuthorization

    sys.modules.pop("deerflow.subagents.executor", None)
    executor_module = importlib.import_module("deerflow.subagents.executor")
    SubagentExecutor = executor_module.SubagentExecutor

    resolved_providers: list = []

    def _distinct_factory(config):
        provider = _rbac_provider({"user": {"skills": {"allow": "*"}}})
        resolved_providers.append(provider)
        return provider

    monkeypatch.setattr(skill_filter_module, "resolve_authorization_provider", _distinct_factory)

    filter_captured: dict = {}
    _original_filter = skill_filter_module.filter_available_skills_by_authorization

    def _filter_spy(available_skills, **kwargs):
        filter_captured["authorization"] = kwargs.get("authorization")
        return _original_filter(available_skills, **kwargs)

    monkeypatch.setattr(skill_filter_module, "filter_available_skills_by_authorization", _filter_spy)

    app_config = _make_app_config()
    _enable_authz(app_config)

    monkeypatch.setattr(
        "deerflow.skills.storage.get_or_new_user_skill_storage",
        lambda user_id, **kw: SimpleNamespace(load_skills=lambda *, enabled_only: [SimpleNamespace(name="demo-skill")]),
    )

    middleware_captured: dict = {}

    def _capture_builder(**kwargs):
        middleware_captured["skill_authorization"] = kwargs.get("skill_authorization")
        return []

    monkeypatch.setattr(
        "deerflow.agents.middlewares.tool_error_handling_middleware.build_subagent_runtime_middlewares",
        _capture_builder,
    )
    monkeypatch.setattr(executor_module, "create_chat_model", lambda **kw: object())

    executor = SubagentExecutor.__new__(SubagentExecutor)
    executor.config = SimpleNamespace(name="sub", skills=None)
    executor.model_name = "m"
    executor.app_config = app_config
    executor._resolved_app_config = app_config
    executor._available_skill_names = None
    executor._skill_authorization = None
    executor._stop_reason_middlewares = []
    executor.extensions = None
    executor.trace_id = "test-trace"
    executor.user_id = "user-123"
    executor.user_role = "user"
    executor.oauth_provider = None
    executor.oauth_id = None
    executor.channel_user_id = None
    executor.is_internal = False
    executor.authz_attributes = None
    executor.tools = []

    asyncio.run(executor._load_skills())
    executor._create_agent(tools=[])

    layer1 = filter_captured["authorization"]
    layer2 = middleware_captured["skill_authorization"]
    assert isinstance(layer1, ResolvedSkillAuthorization)
    assert layer2 is layer1
    # One resolve per assembly even though the factory returns distinct objects.
    assert len(resolved_providers) == 1


# ── Re-authorization of persisted skill_context entries (review round 5) ──


def test_in_context_secret_sources_reauthorize_persisted_entries(tmp_path, monkeypatch):
    """[P1 regression] An entry stamped while activation was allowed must stop
    binding secrets on the next run once the provider denies skill:activate —
    skill_context persists across runs; the decision does not."""
    provider = _ActionAwareProvider(denied_activate={"demo-skill"})
    resolved = _resolved_skill_authorization(provider, fail_closed=True)
    middleware = _middleware_for(
        tmp_path,
        monkeypatch,
        ["demo-skill"],
        available_skills={"demo-skill"},
        skill_authorization=resolved,
    )

    def _make_skill_with_secrets(name: str):
        made = middleware._storage().load_skills(enabled_only=True)
        skill = next(s for s in made if s.name == name)
        object.__setattr__(skill, "required_secrets", [SimpleNamespace(name="API_KEY", optional=False)])
        object.__setattr__(skill, "secrets_autonomous", True)
        return skill

    skill = _make_skill_with_secrets("demo-skill")
    container_root = middleware._storage().get_container_root()
    registry = {posixpath_normpath(skill.get_container_file_path(container_root)): skill}
    request = SimpleNamespace(state={"skill_context": [{"name": "demo-skill", "path": skill.get_container_file_path(container_root)}]})

    # Run 1: activation allowed -> the persisted entry binds its secrets.
    provider.denied_activate = set()
    sources = middleware._in_context_secret_sources(request, registry)
    assert [name for name, _ in sources] == ["demo-skill"]

    # Run 2 (deny-next-run): same persisted entry, provider now denies.
    provider.denied_activate = {"demo-skill"}
    sources = middleware._in_context_secret_sources(request, registry)
    assert sources == []


def test_tool_policy_reauthorizes_persisted_entries(monkeypatch, tmp_path):
    """[P1 regression] allow-read-then-deny-next-run for allowed-tools: the
    persisted entry no longer applies its declaration once skill:activate is
    denied; an allowed skill keeps applying (partial deny does not poison)."""
    from deerflow.agents.middlewares.skill_tool_policy_middleware import SkillToolPolicyMiddleware

    provider = _ActionAwareProvider(denied_activate=set())
    resolved = _resolved_skill_authorization(provider, fail_closed=True)

    skills = {}
    for name, allowed_tools in (("demo-skill", ("bash",)), ("ok-skill", ("web_search",))):
        skill_dir = tmp_path / name
        skill_dir.mkdir(exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("# x", encoding="utf-8")
        from deerflow.skills.types import Skill as SkillObject
        from deerflow.skills.types import SkillCategory

        skills[name] = SkillObject(
            name=name,
            description="d",
            license=None,
            skill_dir=skill_dir,
            skill_file=skill_file,
            relative_path=Path(name),
            category=SkillCategory.CUSTOM,
            enabled=True,
            allowed_tools=allowed_tools,
        )

    container_root = "/mnt/skills"
    registry_entries = list(skills.values())

    def _registry_path(skill):
        return posixpath_normpath(skill.get_container_file_path(container_root))

    paths = [_registry_path(skills["demo-skill"]), _registry_path(skills["ok-skill"])]

    monkeypatch.setattr(
        SkillToolPolicyMiddleware,
        "_storage",
        lambda self: SimpleNamespace(
            load_skills=lambda *, enabled_only: registry_entries,
            get_container_root=lambda: container_root,
        ),
    )

    middleware = SkillToolPolicyMiddleware(
        available_skills={"demo-skill", "ok-skill"},
        slash_source_owner_token="test-token",
        skill_authorization=resolved,
    )
    # Both allowed: the union of both declarations applies.
    provider.denied_activate = set()
    allowed = middleware._allowed_names_for_paths(tuple(paths))
    assert "bash" in allowed and "web_search" in allowed

    # Deny-next-run for demo-skill only: its declaration stops applying, the
    # still-allowed skill's declaration keeps applying.
    provider.denied_activate = {"demo-skill"}
    allowed = middleware._allowed_names_for_paths(tuple(paths))
    assert "bash" not in allowed
    assert "web_search" in allowed

    # All denied: no active reference survives -> fail closed to builtins.
    provider.denied_activate = {"demo-skill", "ok-skill"}
    allowed = middleware._allowed_names_for_paths(tuple(paths))
    from deerflow.skills.tool_policy import ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES

    assert allowed == set(ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES)


# ── Async provider API on async execution paths (review round 5) ──────


def test_async_activation_path_uses_aauthorize(tmp_path, monkeypatch):
    """awrap_model_call resolves skill:activate with aauthorize() on the loop —
    a loop-affine provider whose sync API always fails still activates."""
    import asyncio

    from langchain_core.messages import HumanMessage

    provider = _AsyncOnlyProvider()
    resolved = _resolved_skill_authorization(provider, fail_closed=True)
    middleware = _middleware_for(
        tmp_path,
        monkeypatch,
        ["demo-skill"],
        available_skills={"demo-skill"},
        skill_authorization=resolved,
    )

    class _Request(SimpleNamespace):
        def override(self, **kwargs):
            updates = dict(self.__dict__)
            updates.update(kwargs)
            clone = _Request(**updates)
            return clone

    request = _Request(
        messages=[HumanMessage(content="/demo-skill hi")],
        state={},
        runtime=None,
    )
    captured = {}

    async def _handler(prepared):
        captured["messages"] = list(prepared.messages)
        return SimpleNamespace(ok=True)

    result = asyncio.run(middleware.awrap_model_call(request, _handler))

    assert getattr(result, "ok", False)
    # aauthorize answered; the failing sync authorize() was never consulted.
    assert provider.async_calls == ["demo-skill"]
    assert len(captured["messages"]) == 2  # activation reminder + original
    assert any(is_slash_activation_reminder(m) for m in captured["messages"])


def test_async_stamp_path_uses_aauthorize():
    """awrap_tool_call's skill-read stamp awaits aauthorize() — a loop-affine
    provider still yields an entry (not a fail-closed denial marker)."""
    import asyncio

    from deerflow.agents.middlewares.skill_context import SKILL_CONTEXT_DENIED_KEY, SKILL_CONTEXT_ENTRY_KEY
    from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware

    provider = _AsyncOnlyProvider()
    resolved = _resolved_skill_authorization(provider, fail_closed=True)
    middleware = ToolErrorHandlingMiddleware(app_config=_make_app_config(), skill_authorization=resolved)

    request, message = _read_call_and_message("/mnt/skills/public/demo-skill/SKILL.md")

    async def _run():
        return await middleware._amaybe_stamp(message, request)

    stamped = asyncio.run(_run())
    assert provider.async_calls == ["demo-skill"]
    assert SKILL_CONTEXT_ENTRY_KEY in stamped.additional_kwargs
    assert SKILL_CONTEXT_DENIED_KEY not in stamped.additional_kwargs


def test_async_stamp_path_denies_via_aauthorize():
    import asyncio

    from deerflow.agents.middlewares.skill_context import SKILL_CONTEXT_DENIED_KEY, SKILL_CONTEXT_ENTRY_KEY
    from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware

    provider = _AsyncOnlyProvider(denied_activate={"demo-skill"})
    resolved = _resolved_skill_authorization(provider, fail_closed=True)
    middleware = ToolErrorHandlingMiddleware(app_config=_make_app_config(), skill_authorization=resolved)

    request, message = _read_call_and_message("/mnt/skills/public/demo-skill/SKILL.md")

    async def _run():
        return await middleware._amaybe_stamp(message, request)

    stamped = asyncio.run(_run())
    assert provider.async_calls == ["demo-skill"]
    assert SKILL_CONTEXT_ENTRY_KEY not in stamped.additional_kwargs
    assert stamped.additional_kwargs.get(SKILL_CONTEXT_DENIED_KEY) is True


def test_describe_async_uses_aauthorize():
    """describe_skill's async invocation gates on aauthorize()."""
    import asyncio

    provider = _AsyncOnlyProvider(denied_activate={"demo-skill"})
    tool = _describe_setup_for(provider, skills=("demo-skill", "other-skill"))

    async def _run():
        return await tool.ainvoke({"args": {"name": "select:demo-skill,other-skill"}, "name": "describe_skill", "type": "tool_call", "id": "async-call"})

    result = asyncio.run(_run())
    content = result.update["messages"][0].content
    assert "other-skill" in content
    assert "demo-skill" not in content
    assert sorted(provider.async_calls) == ["demo-skill", "other-skill"]


def test_async_tool_policy_uses_aauthorize(monkeypatch, tmp_path):
    """SkillToolPolicyMiddleware's async hooks re-authorize persisted entries
    with aauthorize() — the loop-affine provider's decision is respected."""
    import asyncio

    from deerflow.agents.middlewares.skill_tool_policy_middleware import SkillToolPolicyMiddleware
    from deerflow.skills.types import Skill as SkillObject
    from deerflow.skills.types import SkillCategory

    # aauthorize ALLOWS demo-skill: with correct wiring the skill's
    # declaration applies ("bash" kept). If the async hook wrongly fell back to
    # the sync API, the provider error would fail-closed and drop "bash".
    provider = _AsyncOnlyProvider()
    resolved = _resolved_skill_authorization(provider, fail_closed=True)

    skill_dir = tmp_path / "demo-skill"
    skill_dir.mkdir(exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# x", encoding="utf-8")
    skill = SkillObject(
        name="demo-skill",
        description="d",
        license=None,
        skill_dir=skill_dir,
        skill_file=skill_dir / "SKILL.md",
        relative_path=Path("demo-skill"),
        category=SkillCategory.CUSTOM,
        enabled=True,
        allowed_tools=("bash",),
    )
    container_root = "/mnt/skills"
    skill_path = posixpath_normpath(skill.get_container_file_path(container_root))

    monkeypatch.setattr(
        SkillToolPolicyMiddleware,
        "_storage",
        lambda self: SimpleNamespace(
            load_skills=lambda *, enabled_only: [skill],
            get_container_root=lambda: container_root,
        ),
    )

    middleware = SkillToolPolicyMiddleware(
        available_skills={"demo-skill"},
        slash_source_owner_token="test-token",
        skill_authorization=resolved,
    )
    request = SimpleNamespace(state={"skill_context": [{"name": "demo-skill", "path": skill_path}]})

    async def _run():
        return await middleware._collect_activation_decisions(request)

    decisions = asyncio.run(_run())
    assert decisions == {"demo-skill": True}

    # End to end through the async hook: the aauthorize-granted entry applies.
    class _ToolsRequest(SimpleNamespace):
        def override(self, **kwargs):
            updates = dict(self.__dict__)
            updates.update(kwargs)
            return _ToolsRequest(**updates)

    async def _identity(prepared):
        return prepared

    tools_request = _ToolsRequest(state=request.state, tools=[SimpleNamespace(name="bash"), SimpleNamespace(name="read_file")], runtime=None)
    filtered = asyncio.run(middleware.awrap_model_call(tools_request, _identity))

    kept = [getattr(t, "name", None) for t in filtered.tools]
    assert kept == ["bash", "read_file"]


def posixpath_normpath(path: str) -> str:
    import posixpath

    return posixpath.normpath(path)


def is_slash_activation_reminder(message) -> bool:
    from deerflow.agents.middlewares.skill_activation_middleware import is_slash_skill_activation_reminder

    return is_slash_skill_activation_reminder(message)
