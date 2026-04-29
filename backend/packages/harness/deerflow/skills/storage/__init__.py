"""SkillStorage singleton + reflection-based factory.

Mirrors the pattern used by ``deerflow/sandbox/sandbox_provider.py``.
"""

from __future__ import annotations

from deerflow.skills.storage.local_skill_storage import LocalSkillStorage
from deerflow.skills.storage.skill_storage import SkillStorage

_default_skill_storage: SkillStorage | None = None


def get_or_new_skill_storage(**kwargs) -> SkillStorage:
    """Return a ``SkillStorage`` instance — either a new one or the process singleton.

    **New instance** is created (never cached) when:
    - ``skills_path`` is provided — uses it as the ``host_path`` override (class still resolved via config).
    - ``app_config`` is provided — constructs a storage from ``app_config.skills``
      so that per-request config (e.g. Gateway ``Depends(get_config)``) is respected
      without polluting the process-level singleton.

    **Singleton** is returned (created on first call, then reused) when neither
    ``skills_path`` nor ``app_config`` is given — uses ``get_app_config()`` to
    resolve the active configuration.
    """
    global _default_skill_storage

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

    skills_path = kwargs.pop("skills_path", None)
    app_config = kwargs.pop("app_config", None)

    if skills_path is not None:
        if app_config is not None:
            return _make_storage(app_config.skills, host_path=str(skills_path), **kwargs)

        return _make_storage(get_app_config().skills, host_path=str(skills_path), **kwargs)

    if app_config is not None:
        return _make_storage(app_config.skills, **kwargs)

    if _default_skill_storage is None:
        _default_skill_storage = _make_storage(get_app_config().skills, **kwargs)
    return _default_skill_storage


def reset_skill_storage() -> None:
    """Clear the cached singleton (used in tests and hot-reload scenarios)."""
    global _default_skill_storage
    _default_skill_storage = None

__all__ = [
    "LocalSkillStorage",
    "SkillStorage",
    "get_or_new_skill_storage",
    "reset_skill_storage",
]
