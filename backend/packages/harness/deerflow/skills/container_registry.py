"""Map container SKILL.md paths to the live registry's canonical skills.

The directory a skill lives in (``relative_path``, e.g.
``vercel-deploy-claimable``) and the name its SKILL.md declares
(``Skill.name``, e.g. ``vercel-deploy``) are deliberately independent: the
authorization layers (Layer 1 filtering, slash activation, ``describe_skill``)
all speak the declared ``Skill.name``, so any path-derived lookup must be
resolved through this registry before it is compared against — or sent to — an
authorization decision.
"""

from __future__ import annotations

import posixpath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deerflow.skills.types import Skill


def build_container_path_registry(storage) -> dict[str, Skill]:
    """Build the live registry keyed by normalized container SKILL.md path.

    Blocking (full skill-tree read): call from sync handlers or a worker
    thread, never the event loop. ``enabled_only=False`` on purpose — the
    activation decision is authorization's to make, not the enabled flag's.
    """
    container_root = storage.get_container_root()
    return {posixpath.normpath(skill.get_container_file_path(container_root)): skill for skill in storage.load_skills(enabled_only=False)}


def canonical_skill_name(registry: dict[str, Skill], skill_md_path: str) -> str | None:
    """Resolve a container SKILL.md path to the registry skill's declared name.

    ``None`` for a path the registry does not know (uninstalled, forged, or
    failed to parse) — callers decide their own fallback, typically the
    path-derived directory name for display or a skip for policy.
    """
    skill = registry.get(posixpath.normpath(skill_md_path))
    return skill.name if skill is not None else None
