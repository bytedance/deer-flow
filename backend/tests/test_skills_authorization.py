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
