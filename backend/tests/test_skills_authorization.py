"""Phase 3 skill-level authorization tests.

Covers Layer 1 enforcement:
- ``filter_available_skills_by_authorization`` — the lead-agent / subagent
  entry point that filters the skill-name allowlist by the provider's
  ``"skill"`` policy.
- ``filter_resources_by_authorization`` — the generic batch filter.
- Subagent executor integration: ``_load_skills`` respects authorization.
"""

from __future__ import annotations

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
        lambda skills, *, enabled, container_base_path: SimpleNamespace(describe_skill_tool=None, skill_names=frozenset()),
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
        lambda skills, *, enabled, container_base_path: SimpleNamespace(describe_skill_tool=None, skill_names=frozenset()),
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

    def filter_resources(self, principal, resource, candidates):
        return list(candidates)

    def authorize(self, request):
        from deerflow.authz.provider import AuthzDecision

        if request.resource == "skill" and request.action == "activate" and request.target in self.denied_activate:
            return AuthzDecision(allow=False)
        return AuthzDecision(allow=True)


class _RaisingAuthorizeProvider(_ActionAwareProvider):
    def authorize(self, request):
        raise RuntimeError("provider blew up")


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
        lambda skills, *, enabled, container_base_path: SimpleNamespace(describe_skill_tool=None, skill_names=frozenset()),
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
        lambda skills, *, enabled, container_base_path: SimpleNamespace(describe_skill_tool=None, skill_names=frozenset()),
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
        lambda skills, *, enabled, container_base_path: SimpleNamespace(describe_skill_tool=None, skill_names=frozenset()),
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
