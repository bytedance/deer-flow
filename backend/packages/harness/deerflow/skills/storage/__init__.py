"""SkillStorage singleton + reflection-based factory.

Mirrors the pattern used by ``deerflow/sandbox/sandbox_provider.py``.
"""

from __future__ import annotations

from deerflow.skills.storage.local_skill_storage import LocalSkillStorage
from deerflow.skills.storage.skill_storage import SkillStorage

_default_skill_storage: SkillStorage | None = None


_DEFAULT_STORAGE_CLASS = "deerflow.skills.storage.local_skill_storage:LocalSkillStorage"


def _resolve_host_path(skills_config) -> str | None:
    """Extract host_path from a skills config, supporting both real SkillsConfig and test SimpleNamespace."""
    if hasattr(skills_config, "path") and not callable(skills_config.path):
        return skills_config.path  # real SkillsConfig: str | None
    if callable(getattr(skills_config, "get_skills_path", None)):
        return str(skills_config.get_skills_path())  # test SimpleNamespace
    return None


def get_skill_storage(**kwargs) -> SkillStorage:
    """Return the cached ``SkillStorage`` singleton, creating it on first call.

    The implementation class is resolved from ``config.skills.use`` via
    ``deerflow.reflection.resolve_class``.  Additional keyword arguments are
    forwarded to the implementation constructor.

    If ``app_config`` is present in ``kwargs``, a fresh (non-cached) instance
    is constructed so that per-request config (e.g. Gateway ``Depends(get_config)``)
    is respected without polluting the process-level singleton.
    """
    global _default_skill_storage

    # Per-request path: construct a fresh instance bound to the given config.
    app_config = kwargs.pop("app_config", None)
    if app_config is not None:
        from deerflow.reflection import resolve_class

        use = getattr(app_config.skills, "use", _DEFAULT_STORAGE_CLASS)
        cls = resolve_class(use, SkillStorage)
        return cls(
            host_path=_resolve_host_path(app_config.skills),
            container_path=app_config.skills.container_path,
            **kwargs,
        )

    # Process-level singleton path.
    if _default_skill_storage is None:
        import deerflow.config as _df_config
        from deerflow.reflection import resolve_class

        config = _df_config.get_app_config()
        use = getattr(config.skills, "use", _DEFAULT_STORAGE_CLASS)
        cls = resolve_class(use, SkillStorage)
        _default_skill_storage = cls(
            host_path=_resolve_host_path(config.skills),
            container_path=config.skills.container_path,
            **kwargs,
        )
    return _default_skill_storage


def reset_skill_storage() -> None:
    """Clear the cached singleton (used in tests and hot-reload scenarios)."""
    global _default_skill_storage
    _default_skill_storage = None


def set_skill_storage(storage: SkillStorage) -> None:
    """Inject a custom ``SkillStorage`` instance (used in tests)."""
    global _default_skill_storage
    _default_skill_storage = storage


__all__ = [
    "LocalSkillStorage",
    "SkillStorage",
    "get_skill_storage",
    "reset_skill_storage",
    "set_skill_storage",
]
