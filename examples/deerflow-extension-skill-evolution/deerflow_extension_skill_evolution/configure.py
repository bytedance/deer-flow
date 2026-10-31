"""Page-driven operator-config editing: target skills and evolution models.

The grants this plugin runs on — ``host_access.skill_mutations.target_skills``
and ``host_access.model_invocation.roles`` — are restart-bound operator config
in ``config.yaml``. This module lets the status page *propose* a new set:

- ``skill_config`` (read): the current target list, the granted evolution
  model roles, the caller's live skill catalog (public + their custom
  skills, the same source as ``/api/skills``), the configured model names,
  and the persisted evolution mode (``modes.py``).
- ``skill_config_write`` (write): validates the proposed skill names and
  models against those catalogs, then rewrites only this plugin's entry in
  the ``plugins:`` block using the host's own surgical editor (span-based,
  atomic, under the extension-manager lock). An optional ``evolution_mode``
  is persisted beside ``storage_path`` when configured and applies
  immediately — no restart.

The config.yaml write never takes effect in the running process; the
response tells the caller to reinstall/restart. Only callers listed in the
entry's ``skill_mutations.owners`` may write — the same users whose
mutations the grant admits. All host imports are lazy so the package still
imports and tests on hosts without the harness installed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .modes import MODES, read_evolution_mode, write_evolution_mode

logger = logging.getLogger(__name__)

_USE = "deerflow_extension_skill_evolution:install"
_SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_MAX_TARGETS = 100
_REINSTALL_COMMAND = "make extension-upgrade SOURCE=examples/deerflow-extension-skill-evolution"


def _error(code: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code}}


def _find_checkout_root() -> Path | None:
    """Locate the DeerFlow checkout the way the extension-manager CLI does."""
    candidates: list[Path] = []
    configured = os.environ.get("DEER_FLOW_PROJECT_ROOT")
    if configured:
        candidates.append(Path(configured))
    candidates.extend((Path.cwd(), *Path.cwd().parents))
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if (resolved / "backend" / "pyproject.toml").is_file():
            return resolved
    return None


def _locate_config() -> tuple[Path, Path] | None:
    """Resolve (config.yaml, project root) the way the running host did.

    ``AppConfig.resolve_config_path`` is the authoritative search the Gateway
    itself used at startup (``DEER_FLOW_CONFIG_PATH``, the project root, then
    the package-location legacy candidates), so a running Gateway always
    resolves the file it actually loaded regardless of its working directory.
    The project root mirrors the extension-manager CLI's checkout walk and
    anchors the manager lock.
    """
    config_path: Path | None = None
    try:
        from deerflow.config.app_config import AppConfig

        config_path = Path(AppConfig.resolve_config_path(None))
    except Exception:
        config_path = None
    project_root = _find_checkout_root()
    if config_path is None or not config_path.is_file():
        if project_root is not None and (project_root / "config.yaml").is_file():
            config_path = project_root / "config.yaml"
        else:
            return None
    if project_root is None:
        # Last resort for the manager lock's anchor: the config's parent, or
        # its grandparent for the legacy backend/ layout.
        project_root = config_path.parent.parent if config_path.parent.name == "backend" else config_path.parent
    return config_path, project_root


def _load_state(config_path: Path) -> tuple[str, list[Any], dict[str, Any]]:
    """Read config.yaml and locate this plugin's entry by its entry point."""
    import yaml

    with config_path.open("r", encoding="utf-8", newline="") as stream:
        original = stream.read()
    config = yaml.safe_load(original) or {}
    if not isinstance(config, dict):
        raise ValueError("config root must be a mapping")
    plugins = config.get("plugins")
    if plugins is None:
        plugins = []
    if not isinstance(plugins, list):
        raise ValueError("plugins must be a list")
    entry = next((plugin for plugin in plugins if isinstance(plugin, dict) and plugin.get("use") == _USE), None)
    if entry is None:
        raise ValueError("plugin entry not found")
    return original, plugins, entry


def _load_skill_catalog(user_id: str) -> list[str]:
    """Names of the caller's visible skills (public + their custom), blocking."""
    from deerflow.config import get_app_config
    from deerflow.skills.storage import get_or_new_user_skill_storage

    storage = get_or_new_user_skill_storage(user_id, app_config=get_app_config())
    return sorted({skill.name for skill in storage.load_skills(enabled_only=False) if isinstance(skill.name, str) and skill.name})


def _load_model_catalog() -> list[str]:
    """Names of the models configured on this host, blocking."""
    from deerflow.config import get_app_config

    return sorted({model.name for model in get_app_config().models if isinstance(model.name, str) and model.name})


def granted_model_roles() -> dict[str, str] | None:
    """The plugin's live ``model_invocation.roles`` mapping, or None if unreadable.

    Read from config.yaml — the same file the operator edit and the page write
    maintain — so evolution launches can fail fast on an ungranted model role
    instead of burning a background job on it.
    """
    located = _locate_config()
    if located is None:
        return None
    config_path = located[0]
    try:
        _, _, entry = _load_state(config_path)
        host_access = entry.get("host_access")
        if not isinstance(host_access, dict):
            return {}
        model_access = host_access.get("model_invocation")
        if not isinstance(model_access, dict):
            return {}
        roles = model_access.get("roles")
        if not isinstance(roles, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in roles.items()):
            return {}
        return dict(roles)
    except Exception:
        logger.warning("skill-evolution: could not read the model invocation roles from config.yaml", exc_info=True)
        return None


def _apply_config_write(config_path: Path, project_root: Path, *, targets: list[str]) -> None:
    """Rewrite this plugin's target skills under the host's manager lock.

    Only ``skill_mutations.target_skills`` is touched: the model invocation
    grant stays operator-owned. Evolution model choice is a per-launch
    selection (see ``evolve.py``), not persisted configuration.
    """
    from deerflow.extensions import manager as extension_manager

    with extension_manager._manager_lock(project_root):
        original, plugins, entry = _load_state(config_path)
        host_access = entry.get("host_access")
        if not isinstance(host_access, dict):
            host_access = {}
            entry["host_access"] = host_access
        mutations = host_access.get("skill_mutations")
        if not isinstance(mutations, dict):
            mutations = {}
            host_access["skill_mutations"] = mutations
        mutations["target_skills"] = list(targets)
        extension_manager._write_plugins_block(config_path, original, plugins)


def _entry_owners(entry: Mapping[str, Any]) -> tuple[str, ...]:
    host_access = entry.get("host_access")
    if not isinstance(host_access, dict):
        return ()
    mutations = host_access.get("skill_mutations")
    if not isinstance(mutations, dict):
        return ()
    owners = mutations.get("owners")
    if not isinstance(owners, list) or any(not isinstance(owner, str) for owner in owners):
        return ()
    return tuple(owners)


def _entry_targets(entry: Mapping[str, Any]) -> list[str]:
    host_access = entry.get("host_access")
    if not isinstance(host_access, dict):
        return []
    mutations = host_access.get("skill_mutations")
    if not isinstance(mutations, dict):
        return []
    targets = mutations.get("target_skills")
    if not isinstance(targets, list) or any(not isinstance(name, str) for name in targets):
        return []
    return list(targets)


def _entry_roles(entry: Mapping[str, Any]) -> dict[str, str]:
    host_access = entry.get("host_access")
    if not isinstance(host_access, dict):
        return {}
    model_access = host_access.get("model_invocation")
    if not isinstance(model_access, dict):
        return {}
    roles = model_access.get("roles")
    if not isinstance(roles, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in roles.items()):
        return {}
    return dict(roles)


class SkillConfigurator:
    """Backend actions for the page's grant-configuration card."""

    def __init__(
        self,
        *,
        config_locator: Callable[[], tuple[Path, Path] | None] = _locate_config,
        catalog_loader: Callable[[str], list[str]] = _load_skill_catalog,
        model_loader: Callable[[], list[str]] = _load_model_catalog,
        writer: Callable[..., None] = _apply_config_write,
        mode_reader: Callable[[], str] = read_evolution_mode,
        mode_writer: Callable[[str], None] = write_evolution_mode,
    ) -> None:
        self._config_locator = config_locator
        self._catalog_loader = catalog_loader
        self._model_loader = model_loader
        self._writer = writer
        self._mode_reader = mode_reader
        self._mode_writer = mode_writer

    async def status(self, payload: Any, ctx: Any) -> dict[str, Any]:
        principal = getattr(ctx, "principal", None)
        user_id = getattr(principal, "user_id", None)
        if not isinstance(user_id, str) or not user_id:
            return _error("UNAUTHENTICATED")
        if not isinstance(payload, Mapping) or set(payload):
            return _error("INVALID_REQUEST")
        try:
            catalog = await asyncio.to_thread(self._catalog_loader, user_id)
        except Exception:
            logger.warning("skill-evolution: could not load the skill catalog for the configuration page", exc_info=True)
            catalog = []
        try:
            models = await asyncio.to_thread(self._model_loader)
        except Exception:
            logger.warning("skill-evolution: could not load the model catalog for the configuration page", exc_info=True)
            models = []
        result: dict[str, Any] = {"ok": True, "skill_catalog": catalog, "models": models, "evolution_mode": self._mode_reader()}
        located = self._config_locator()
        if located is None:
            result.update({"config_available": False, "can_write": False, "targets": [], "evolution_roles": {}})
            return result
        config_path = located[0]
        try:
            _, _, entry = _load_state(config_path)
        except Exception:
            logger.warning("skill-evolution: could not read the plugin entry from config.yaml", exc_info=True)
            result.update({"config_available": False, "can_write": False, "targets": [], "evolution_roles": {}})
            return result
        result.update(
            {
                "config_available": True,
                "can_write": user_id in _entry_owners(entry),
                "targets": _entry_targets(entry),
                "evolution_roles": _entry_roles(entry),
            }
        )
        return result

    async def write(self, payload: Any, ctx: Any) -> dict[str, Any]:
        principal = getattr(ctx, "principal", None)
        user_id = getattr(principal, "user_id", None)
        if not isinstance(user_id, str) or not user_id:
            return _error("UNAUTHENTICATED")
        if not isinstance(payload, Mapping) or set(payload) - {"skill_names", "evolution_mode"}:
            return _error("INVALID_REQUEST")
        mode = payload.get("evolution_mode")
        if mode is not None and mode not in MODES:
            return _error("INVALID_REQUEST")
        skill_names = payload.get("skill_names")
        if skill_names is None and mode is None:
            return _error("INVALID_REQUEST")
        if skill_names is not None and (not isinstance(skill_names, list) or not skill_names or any(not isinstance(name, str) for name in skill_names)):
            return _error("INVALID_REQUEST")
        if skill_names is not None and (len(skill_names) > _MAX_TARGETS or any(not _SKILL_NAME.fullmatch(name) or len(name) > 64 for name in skill_names)):
            return _error("INVALID_REQUEST")
        located = self._config_locator()
        if located is None:
            return _error("CONFIG_UNAVAILABLE")
        config_path, project_root = located
        try:
            _, _, entry = _load_state(config_path)
        except Exception:
            logger.warning("skill-evolution: could not read the plugin entry from config.yaml", exc_info=True)
            return _error("CONFIG_UNAVAILABLE")
        if user_id not in _entry_owners(entry):
            return _error("FORBIDDEN")
        result: dict[str, Any] = {"ok": True}
        if skill_names is not None:
            targets = sorted(set(skill_names))
            try:
                catalog = set(await asyncio.to_thread(self._catalog_loader, user_id))
            except Exception:
                logger.warning("skill-evolution: could not load the skill catalog to validate the configuration write", exc_info=True)
                return _error("INTERNAL")
            unknown = [name for name in targets if name not in catalog]
            if unknown:
                return {"ok": False, "error": {"code": "UNKNOWN_SKILL", "skills": unknown}}
            try:
                await asyncio.to_thread(self._writer, config_path, project_root, targets=targets)
            except Exception:
                logger.warning("skill-evolution: failed to write the plugin configuration", exc_info=True)
                return _error("WRITE_FAILED")
            result.update(
                {
                    "targets": targets,
                    "restart_required": True,
                    "reinstall_command": _REINSTALL_COMMAND,
                }
            )
        if mode is not None:
            # The evolution mode is read per call, so this half of the write
            # applies immediately — no reinstall or restart.
            try:
                await asyncio.to_thread(self._mode_writer, mode)
            except Exception:
                logger.warning("skill-evolution: failed to persist the evolution mode", exc_info=True)
                return _error("WRITE_FAILED")
            result["evolution_mode"] = mode
        return result
