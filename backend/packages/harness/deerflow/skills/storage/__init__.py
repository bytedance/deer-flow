"""SkillStorage singleton + reflection-based factory.

Mirrors the pattern used by ``deerflow/sandbox/sandbox_provider.py``.
"""

from __future__ import annotations

from deerflow.skills.storage.local_skill_storage import LocalSkillStorage
from deerflow.skills.storage.skill_storage import SkillStorage

_default_skill_storage: SkillStorage | None = None
_default_skill_storage_config: object | None = None  # AppConfig identity the singleton was built from


def get_or_new_skill_storage(**kwargs) -> SkillStorage:
    """Return a ``SkillStorage`` instance — either a new one or the process singleton.

    **New instance** is created (never cached) when:
    - ``user_id`` is provided — creates a per-user storage whose custom-skill paths
      are scoped to ``custom/<user_id>/``.  Never shares the process-level singleton.
    - ``skills_path`` is provided — uses it as the ``host_path`` override (class still resolved via config).
    - ``app_config`` is provided — constructs a storage from ``app_config.skills``
      so that per-request config (e.g. Gateway ``Depends(get_config)``) is respected
      without polluting the process-level singleton.

    **Singleton** is returned (created on first call, then reused) when none of the
    above kwargs are given — uses ``get_app_config()`` to resolve the active
    configuration.
    """
    global _default_skill_storage, _default_skill_storage_config

    from deerflow.config import get_app_config
    from deerflow.config.skills_config import SkillsConfig

    def _make_storage(skills_config: SkillsConfig, *, host_path: str | None = None, **kwargs) -> SkillStorage:
        from deerflow.reflection import resolve_class

        cls = resolve_class(skills_config.use, SkillStorage)
        return cls(
            host_path=host_path if host_path is not None else str(skills_config.get_skills_path()),
            container_path=skills_config.container_path,
            **kwargs,
        )

    user_id = kwargs.pop("user_id", None)
    skills_path = kwargs.pop("skills_path", None)
    app_config = kwargs.pop("app_config", None)

    # When user_id is given, always create a fresh per-user instance — never
    # the process-level singleton, because different users need different
    # _custom_base paths.
    if user_id is not None:
        if app_config is not None:
            return _make_storage(app_config.skills, user_id=user_id, **kwargs)
        app_config_now = get_app_config()
        return _make_storage(app_config_now.skills, user_id=user_id, **kwargs)

    if skills_path is not None:
        if app_config is not None:
            return _make_storage(app_config.skills, host_path=str(skills_path), **kwargs)
        # No app_config: use a default SkillsConfig so we never need to read config.yaml
        # when the caller has already supplied an explicit host path.
        from deerflow.config.skills_config import SkillsConfig

        return _make_storage(SkillsConfig(), host_path=str(skills_path), **kwargs)

    if app_config is not None:
        return _make_storage(app_config.skills, **kwargs)

    # If the singleton was manually injected (e.g. in tests) without a config
    # identity (_default_skill_storage_config is None), skip get_app_config()
    # entirely to avoid requiring a config.yaml on disk.
    if _default_skill_storage is not None and _default_skill_storage_config is None:
        return _default_skill_storage

    app_config_now = get_app_config()
    if _default_skill_storage is None or _default_skill_storage_config is not app_config_now:
        _default_skill_storage = _make_storage(app_config_now.skills, **kwargs)
        _default_skill_storage_config = app_config_now
    return _default_skill_storage


def reset_skill_storage() -> None:
    """Clear the cached singleton (used in tests and hot-reload scenarios)."""
    global _default_skill_storage, _default_skill_storage_config
    _default_skill_storage = None
    _default_skill_storage_config = None


__all__ = [
    "LocalSkillStorage",
    "SkillStorage",
    "get_or_new_skill_storage",
    "reset_skill_storage",
]
