"""Convenience wrapper for Layer 1 skill authorization filtering.

Combines provider resolution, Principal construction, and skill filtering into
a single call so the assembly paths (lead agent, subagent executor) stay
one-liners. Mirrors ``apply_tool_authorization`` from ``tool_filter.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from deerflow.authz.principal import build_principal_from_context
from deerflow.authz.provider import AuthzDecision, AuthzRequest
from deerflow.authz.runtime import resolve_authorization_provider
from deerflow.config.app_config import AppConfig

if TYPE_CHECKING:
    from deerflow.authz.provider import AuthorizationProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResolvedSkillAuthorization:
    """Provider + principal resolved once per agent assembly.

    Shared by the Layer 1 visibility filter above and the runtime
    ``skill:activate`` action check in ``SkillActivationMiddleware`` so both
    layers see the same provider instance and identity without resolving
    twice. ``fail_closed`` is the provider-error policy from config.
    """

    provider: AuthorizationProvider
    principal: Any
    fail_closed: bool


def skill_activation_allowed(
    authorization: ResolvedSkillAuthorization | None,
    skill_name: str,
) -> bool:
    """Action-scoped ``skill:activate`` decision for one skill name.

    Shared by every runtime activation gate — explicit slash activation
    (``SkillActivationMiddleware``), ``describe_skill``, and the skill-file
    load that records ``skill_context`` — so all paths apply the same decision
    and the same provider-error policy. ``_available_skills``-style visibility
    sets are Layer 1 (action-agnostic ``filter_resources``); an action-aware
    custom provider may expose a skill there while denying its activation, so
    each activation path must additionally consult this check. ``None``
    (authorization disabled) allows — visibility already decided membership.
    Mirrors ``_authorize_model_name``'s second ``authorize("model", "use")``
    check. Provider errors follow the configured fail-closed / fail-open
    policy.
    """
    if authorization is None:
        return True
    try:
        decision = authorization.provider.authorize(AuthzRequest(principal=authorization.principal, resource="skill", action="activate", target=skill_name))
        if not isinstance(decision, AuthzDecision):
            raise TypeError("AuthorizationProvider.authorize must return AuthzDecision")
        return decision.allow
    except Exception:
        logger.warning("Authorization provider failed while checking skill:activate for '%s'", skill_name, exc_info=True)
        return not authorization.fail_closed


def resolve_skill_authorization(
    context: Mapping[str, Any],
    app_config: AppConfig,
) -> ResolvedSkillAuthorization | None:
    """Resolve the skill authorization context, or ``None`` when disabled.

    ``None`` means "authorization is disabled or no provider is configured" —
    callers treat that as "no extra enforcement" (the pre-authorization
    behavior). Mock-friendly in the same style as the filter below: a config
    object without a real ``AuthorizationConfig`` also yields ``None``.
    """
    authz_config = getattr(app_config, "authorization", None)
    if authz_config is None or getattr(authz_config, "enabled", None) is not True:
        return None

    provider = resolve_authorization_provider(authz_config)
    if provider is None:
        return None

    principal = build_principal_from_context(context, default_role=authz_config.default_role)
    return ResolvedSkillAuthorization(
        provider=provider,
        principal=principal,
        fail_closed=bool(getattr(authz_config, "fail_closed", False)),
    )


def filter_available_skills_by_authorization(
    available_skills: set[str] | None,
    *,
    context: Mapping[str, Any],
    app_config: AppConfig,
    user_id: str | None = None,
    candidate_skill_names: list[str] | None = None,
    authorization: ResolvedSkillAuthorization | None = None,
) -> set[str] | None:
    """Filter a skill-name allowlist by the provider's ``"skill"`` policy.

    This is the Layer 1 entry point for the lead-agent and subagent assembly
    paths. It operates on the ``available_skills`` name set (the agent-config
    allowlist) rather than on loaded ``Skill`` objects, so it runs before any
    disk I/O and constrains both the catalog (``describe_skill``) and the
    slash-activation middleware (which checks the same set).

    - ``available_skills=None`` means "no agent-level allowlist" (all enabled
      skills). When authorization is enabled, this resolves the full enabled
      skill set from config and filters it; the result is a constrained set
      (or ``None`` if authorization is disabled).
    - ``available_skills=set()`` (empty) means "no skills for this agent" and
      is preserved as-is (the agent already allows none).

    *user_id* threads the per-user identity into the candidate resolution so
    per-user custom skills (``UserScopedSkillStorage``) are included in the
    universe the provider filters — matching what the activation path loads.
    When omitted, only the process-global (public) skills are candidates.

    *candidate_skill_names* lets a caller that has already loaded skills from
    disk (e.g. the subagent executor) pass the pre-resolved name list, avoiding
    a redundant ``load_skills`` call inside ``_all_configured_skill_names``.
    Only consulted when ``available_skills is None``.

    When ``authorization.enabled`` is false, returns *available_skills*
    unchanged (no-op).
    """
    # Guard against Mock/SimpleNamespace app_config objects in tests that
    # don't carry a real AuthorizationConfig. getattr avoids AttributeError
    # and the ``is not True`` identity check avoids truthy Mock attributes.
    if authorization is None:
        authorization = resolve_skill_authorization(context, app_config)
    if authorization is None:
        return available_skills
    fail_closed = authorization.fail_closed

    principal = authorization.principal

    # If the agent already allows no skills, nothing to filter.
    if available_skills is not None and len(available_skills) == 0:
        return available_skills

    # Resolve the candidate set: the agent allowlist (if set), or all known
    # skill names from config (so authorization constrains the "no allowlist"
    # case too). When ``available_skills is None`` and the configured-skill
    # resolution fails (storage I/O error), we must NOT silently return ``None``
    # — that would bypass authorization entirely (every skill becomes
    # activatable/loadable). Instead we fall through to the same fail-closed /
    # fail-open handling as a provider error below.
    if available_skills is not None:
        candidates = sorted(available_skills)
    elif candidate_skill_names is not None:
        # Caller already loaded skills from disk (e.g. subagent executor) —
        # reuse the names instead of calling load_skills again.
        candidates = candidate_skill_names
    else:
        try:
            candidates = _all_configured_skill_names(app_config, user_id=user_id)
        except Exception:
            logger.warning("Could not resolve configured skill names for authorization filtering", exc_info=True)
            return set() if fail_closed else available_skills

    if not candidates:
        # Genuinely no skills configured (or agent allowlist is empty after
        # filtering) — ``None`` here is safe because there is nothing to authorize.
        return available_skills

    try:
        allowed = authorization.provider.filter_resources(principal, "skill", candidates)
        if not isinstance(allowed, list) or any(not isinstance(n, str) for n in allowed):
            raise TypeError("AuthorizationProvider.filter_resources must return list[str]")
    except Exception:
        logger.warning("Authorization provider failed while filtering available skills", exc_info=True)
        return set() if fail_closed else available_skills

    # Defensive intersection with the candidate set: the provider contract says
    # results must be a subset of candidates, but we only validated list[str].
    # A buggy custom provider could otherwise inject extra skill names and
    # expand an explicit agent allowlist. Mirrors filter_resources_by_authorization.
    allowed_names = set(allowed)
    return {name for name in candidates if name in allowed_names}


def _all_configured_skill_names(app_config: AppConfig, *, user_id: str | None = None) -> list[str]:
    """Return all configured skill names (public + per-user custom).

    This is only needed when ``available_skills`` is ``None`` (no agent-level
    allowlist) and authorization is enabled — we need the full candidate set
    to filter. Returns an empty list if no skills are configured. Raises on
    storage/I/O errors so the caller can apply fail-closed / fail-open semantics
    (a swallowed error here would silently bypass authorization).

    When *user_id* is provided, uses the per-user ``UserScopedSkillStorage`` so
    custom skills under ``{base}/users/{user_id}/skills/custom/`` are included —
    matching the universe the activation path loads. Without it, falls back to
    the process-global storage (public skills only).
    """
    if user_id is not None:
        from deerflow.skills.storage import get_or_new_user_skill_storage

        storage = get_or_new_user_skill_storage(user_id, app_config=app_config)
    else:
        from deerflow.skills.storage import get_or_new_skill_storage

        storage = get_or_new_skill_storage(app_config=app_config)
    skills = storage.load_skills(enabled_only=True)
    return [s.name for s in skills]
