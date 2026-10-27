"""Live authorization for skill discovery and execution, separate from storage ownership."""

from collections.abc import Mapping

from deerflow.runtime.user_context import get_current_user


def _config(app_config=None):
    if app_config is not None:
        return app_config
    from deerflow.config import get_app_config

    return get_app_config()


def skill_authorization_enabled(app_config=None):
    from deerflow.authz.user_policy import PROVIDER_PATH

    authorization = getattr(_config(app_config), "authorization", None)
    provider = getattr(authorization, "provider", None)
    return getattr(authorization, "enabled", None) is True and getattr(provider, "use", None) == PROVIDER_PATH


def _identity(runtime=None):
    user = get_current_user()
    if runtime is None:
        try:
            from langgraph.runtime import get_runtime

            runtime = get_runtime()
        except RuntimeError:
            pass
    context = runtime if isinstance(runtime, Mapping) else getattr(runtime, "context", None)
    if user is not None:
        owner = str(user.id)
        role = getattr(user, "system_role", None) or getattr(user, "role", None)
        if isinstance(context, Mapping) and context.get("user_id"):
            if str(context["user_id"]) != owner:
                return None, None
            if role is None:
                role = context.get("user_role")
        return owner, role
    if isinstance(context, Mapping):
        return context.get("user_id"), context.get("user_role")
    return None, None


def skill_resource_target(skill, user_id=None):
    """Use category and package path; private custom targets include their owner."""
    if str(skill.category) == "custom":
        owner = user_id or _identity()[0]
        if not owner:
            raise ValueError("Custom skill authorization requires an owner")
        return f"custom:{owner}:{skill.skill_path or skill.name}"
    return f"{skill.category}:{skill.skill_path or skill.name}"


def filter_authorized_skills(skills, *, user_id=None, app_config=None, runtime=None):
    """Filter an already ownership-scoped catalog using fresh effective grants.

    Runtime context must come from the server-stamped run, never request input.
    No role defaults are used here, even when authorization.default_role is admin.
    """
    app_config = _config(app_config)
    if not skill_authorization_enabled(app_config):
        return list(skills)
    owner, role = _identity(runtime)
    if not owner or owner == "default" or role not in {"admin", "user"} or (user_id is not None and user_id != owner):
        return []
    if role == "admin":
        return list(skills)
    from deerflow.security.defaults import DEFAULT_SKILL_TARGETS
    from deerflow.security.store import UserSecurityStore

    grants = UserSecurityStore(app_config.authorization.provider.config.get("store_path")).grants(owner)
    return [skill for skill in skills if (target := skill_resource_target(skill, owner)) in DEFAULT_SKILL_TARGETS or ("skill", target) in grants]


def filter_authorized_skill_context(entries, *, runtime=None):
    """Do not re-inject historical captured skill bodies after permission removal."""
    if not entries or not skill_authorization_enabled():
        return entries
    from deerflow.skills.storage import get_or_new_user_skill_storage

    owner, _ = _identity(runtime)
    if not owner:
        return []
    storage = get_or_new_user_skill_storage(owner)
    skills = filter_authorized_skills(storage.load_skills(enabled_only=True), user_id=owner, runtime=runtime)
    paths = {skill.get_container_file_path(storage.get_container_root()) for skill in skills}
    return [entry for entry in entries if entry.get("path") in paths]
