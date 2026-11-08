"""Evidence-gated skill self-evolution example.

Demonstrates the roadmap deliverable: a proposed change, the regression case it
fixes, the old and new results, and a rollback to a known-good version — all
through the host ``SkillMutationService`` contract merged in #5645.

Install via ``config.yaml -> plugins:`` with a ``host_access.skill_mutations``
grant (see README.md). Without the grant the service fails to start and the
Gateway reports a diagnostic; nothing else changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from deerflow_extension_api import ExtensionInstall, ExtensionRegistry, extension

from deerflow_extension_skill_evolution.service import EvolutionService, build_router

__all__ = ["install"]

_DEFAULT_CASES_DIR = Path(__file__).resolve().parent / "cases"


@extension(api="0.2.11", name="skill-evolution")
def install(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    """Register the evolution service and its HTTP walkthrough surface."""
    # ``is False`` alone would silently keep the plugin on for ``enabled: 0`` or
    # ``enabled: "false"``; a mistyped off switch must fail the deployment.
    enabled = config.get("enabled", True)
    if type(enabled) is not bool:
        raise ValueError(f"skill-evolution: config.enabled must be a boolean, got {enabled!r}")
    if not enabled:
        return

    cases_dir = config.get("cases_dir")
    service = EvolutionService(cases_dir=Path(cases_dir) if cases_dir else _DEFAULT_CASES_DIR)
    registry.service(service)
    registry.routers((build_router(service),))


_entry_point: ExtensionInstall = install
