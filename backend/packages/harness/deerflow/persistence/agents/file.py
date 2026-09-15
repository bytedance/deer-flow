"""Filesystem-backed agent store — today's per-user layout, behaviour-preserving.

The read methods are the pre-refactor bodies of ``load_agent_config`` /
``load_agent_soul`` / ``list_custom_agents`` (so the free functions in
:mod:`deerflow.config.agents_config` dispatch here without changing behaviour).
Writes use a staged temp-file + atomic ``os.replace`` commit — the crash-safety
the ``update_agent`` tool already had, applied uniformly to create/update.

Path/user resolution is done through the :mod:`deerflow.config.agents_config`
module object (``_ac.get_paths`` / ``_ac.get_effective_user_id``) rather than
direct imports, so it honours the same monkeypatch seams the existing agent
tests target.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Hashable
from pathlib import Path
from typing import Any

import yaml

from deerflow.config import agents_config as _ac
from deerflow.config.agents_config import (
    SOUL_FILENAME,
    AgentConfig,
    resolve_agent_dir,
    validate_agent_name,
)
from deerflow.persistence.agents.base import (
    AgentDeleteOutcome,
    AgentExistsError,
    AgentStore,
    parse_agent_config,
)
from deerflow.runtime.user_context import DEFAULT_USER_ID

logger = logging.getLogger(__name__)


class FileAgentStore(AgentStore):
    def get(self, name: str, *, user_id: str | None = None) -> AgentConfig:
        name = validate_agent_name(name)
        agent_dir = resolve_agent_dir(name, user_id=user_id)
        config_file = agent_dir / "config.yaml"
        if not agent_dir.exists():
            raise FileNotFoundError(f"Agent directory not found: {agent_dir}")
        if not config_file.exists():
            raise FileNotFoundError(f"Agent config not found: {config_file}")
        try:
            with open(config_file, encoding="utf-8") as f:
                data: dict[str, Any] = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse agent config {config_file}: {e}") from e
        return parse_agent_config(data, name)

    def exists(self, name: str, *, user_id: str | None = None) -> bool:
        name = validate_agent_name(name)
        paths = _ac.get_paths()
        effective_user = user_id or _ac.get_effective_user_id()
        return paths.user_agent_dir(effective_user, name).exists() or paths.agent_dir(name).exists()

    def get_soul(self, name: str, *, user_id: str | None = None) -> str | None:
        agent_dir = resolve_agent_dir(name, user_id=user_id)
        soul_path = agent_dir / SOUL_FILENAME
        # resolve_agent_dir requires config.yaml; SOUL.md loading does not, so
        # when the resolver fell back to its default path (no qualifying dir),
        # check the per-user and legacy dirs directly (#4135). The config.yaml
        # guard keeps this fallback from firing for a properly-resolved per-user
        # agent that merely lacks SOUL.md (preserves per-user-shadows-legacy).
        if not soul_path.exists() and not (agent_dir / "config.yaml").exists():
            paths = _ac.get_paths()
            effective_user = user_id or _ac.get_effective_user_id()
            for candidate in (
                paths.user_agent_dir(effective_user, name),
                paths.agent_dir(name),
            ):
                if (candidate / SOUL_FILENAME).exists():
                    soul_path = candidate / SOUL_FILENAME
                    break
        if not soul_path.exists():
            return None
        content = soul_path.read_text(encoding="utf-8").strip()
        return content or None

    def list(self, *, user_id: str | None = None) -> list[AgentConfig]:
        paths = _ac.get_paths()
        effective_user = user_id or _ac.get_effective_user_id()
        seen: set[str] = set()
        agents: list[AgentConfig] = []
        for root in (paths.user_agents_dir(effective_user), paths.agents_dir):
            if not root.exists():
                continue
            for entry in sorted(root.iterdir()):
                if not entry.is_dir() or entry.name in seen:
                    continue
                if not (entry / "config.yaml").exists():
                    logger.debug("Skipping %s: no config.yaml", entry.name)
                    continue
                try:
                    agents.append(self.get(entry.name, user_id=effective_user))
                    seen.add(entry.name)
                except Exception as e:  # noqa: BLE001 — one bad agent must not hide the rest
                    logger.warning("Skipping agent '%s': %s", entry.name, e)
        agents.sort(key=lambda a: a.name)
        return agents

    def list_all(self) -> list[tuple[str, AgentConfig]]:
        result: list[tuple[str, AgentConfig]] = []
        for user_id, name in self._discover():
            try:
                result.append((user_id, self.get(name, user_id=user_id)))
            except Exception as e:  # noqa: BLE001
                logger.warning("list_all: skipping agent %s/%s: %s", user_id, name, e)
        return result

    def create(self, name: str, config: dict, soul: str, *, user_id: str | None = None) -> None:
        name = validate_agent_name(name)
        paths = _ac.get_paths()
        effective_user = user_id or _ac.get_effective_user_id()
        agent_dir = paths.user_agent_dir(effective_user, name)
        # Refuse if a per-user directory OR a legacy shared directory already
        # owns the name — the agents router's 409 semantics (a legacy agent must
        # not be shadowed; a per-user dir may be memory-only but still blocks).
        if agent_dir.exists() or paths.agent_dir(name).exists():
            raise AgentExistsError(f"Agent '{name}' already exists for user '{effective_user}'")
        try:
            agent_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as e:
            # A concurrent create passed the existence check above and reached
            # mkdir first. Surface the router's 409 (via AgentExistsError) rather
            # than a generic 500 — mirrors SqlAgentStore's IntegrityError path.
            raise AgentExistsError(f"Agent '{name}' already exists for user '{effective_user}'") from e
        try:
            self._write(agent_dir, config, soul)
        except Exception:
            # The directory was newly created for this call; a failed write
            # must not leave an empty/partial agent dir behind.
            shutil.rmtree(agent_dir, ignore_errors=True)
            raise

    def update(self, name: str, config: dict | None, soul: str | None, *, user_id: str | None = None) -> None:
        name = validate_agent_name(name)
        effective_user = user_id or _ac.get_effective_user_id()
        agent_dir = _ac.get_paths().user_agent_dir(effective_user, name)
        pre_existing = agent_dir.exists()
        agent_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._write(agent_dir, config, soul)
        except Exception:
            # Only clean up a directory this call created — never delete a
            # pre-existing agent on a failed write.
            if not pre_existing:
                shutil.rmtree(agent_dir, ignore_errors=True)
            raise

    def delete(self, name: str, *, user_id: str | None = None) -> AgentDeleteOutcome:
        name = validate_agent_name(name)
        paths = _ac.get_paths()
        effective_user = user_id or _ac.get_effective_user_id()
        agent_dir = paths.user_agent_dir(effective_user, name)
        if not agent_dir.exists():
            # A legacy shared-layout agent is intentionally left in place (the
            # write path never targets it); report it distinctly.
            return "legacy" if paths.agent_dir(name).exists() else "missing"
        if not (agent_dir / "config.yaml").is_file():
            # The directory holds memory/facts data but is not a custom agent
            # (no config.yaml) — preserve it rather than deleting a user's memory
            # (#4279). rmtree below would otherwise take the whole tree.
            return "not-custom-agent"
        # rmtree removes config.yaml, SOUL.md and the co-located memory.json in
        # one shot — the historical behaviour.
        shutil.rmtree(agent_dir)
        return "deleted"

    def signature(self) -> Hashable:
        sig: list[tuple[str, str, float]] = []
        for user_id, name in self._discover():
            config = resolve_agent_dir(name, user_id=user_id) / "config.yaml"
            try:
                sig.append((user_id, name, config.stat().st_mtime))
            except OSError:
                continue
        return tuple(sig)

    # -- internals --

    def _discover(self) -> list[tuple[str, str]]:
        """Enumerate ``(user_id, name)`` across per-user and legacy layouts.

        A legacy shared-layout agent is attributed to ``DEFAULT_USER_ID`` and is
        shadowed only by a ``users/default/`` agent of the same name — not by an
        agent another user happens to own — matching the GitHub registry's
        historical discovery (``load_agent_config(name)`` resolves a legacy agent
        under ``DEFAULT_USER_ID``).
        """
        paths = _ac.get_paths()
        discovered: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        users_root = paths.base_dir / "users"
        if users_root.exists():
            for user_entry in sorted(users_root.iterdir()):
                if not user_entry.is_dir():
                    continue
                agents_root = paths.user_agents_dir(user_entry.name)
                if not agents_root.exists():
                    continue
                for entry in sorted(agents_root.iterdir()):
                    if entry.is_dir() and (entry / "config.yaml").exists():
                        key = (user_entry.name, entry.name)
                        discovered.append(key)
                        seen.add(key)
        legacy_root = paths.agents_dir
        if legacy_root.exists():
            for entry in sorted(legacy_root.iterdir()):
                if entry.is_dir() and (entry / "config.yaml").exists() and (DEFAULT_USER_ID, entry.name) not in seen:
                    discovered.append((DEFAULT_USER_ID, entry.name))
        return discovered

    @staticmethod
    def _write(agent_dir: Path, config: dict | None, soul: str | None) -> None:
        """Write config.yaml and/or SOUL.md, each via an atomic ``os.replace``.

        Each part is written only when supplied (``config``/``soul`` non-None),
        staged to a temp file then committed with ``os.replace``, so neither file
        is ever observed half-written. The two commits are sequential, **not** a
        single transaction: a crash between them can leave a freshly-replaced
        config.yaml beside a stale SOUL.md (single-node, sub-millisecond window).
        The ``db`` backend commits both fields in one transaction; if cross-file
        atomicity ever matters here, restore ``update_agent``'s partial-write
        reporting.
        """
        pending: list[tuple[Path, Path]] = []
        staged: list[Path] = []
        try:
            if config is not None:
                config_text = yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False)
                config_tmp = _stage_temp(agent_dir / "config.yaml", config_text)
                staged.append(config_tmp)
                pending.append((config_tmp, agent_dir / "config.yaml"))
            if soul is not None:
                soul_tmp = _stage_temp(agent_dir / SOUL_FILENAME, soul)
                staged.append(soul_tmp)
                pending.append((soul_tmp, agent_dir / SOUL_FILENAME))
            for tmp, target in pending:
                tmp.replace(target)
                staged.remove(tmp)
        finally:
            for tmp in staged:
                tmp.unlink(missing_ok=True)


def _stage_temp(target: Path, text: str) -> Path:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, suffix=".tmp", delete=False) as f:
        f.write(text)
        return Path(f.name)
