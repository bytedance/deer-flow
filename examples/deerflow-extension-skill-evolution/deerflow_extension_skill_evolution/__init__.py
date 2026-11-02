"""Agent self-evolution for DeerFlow, starting with the Skill module.

This package owns the *policy* half of skill self-evolution — when the agent
should consider distilling task experience into a skill, and the
``skill_manage`` tool entry point the policy drives. Everything that makes a
mutation safe (validation, static + LLM scanning, per-user storage, history,
sandbox projection, cache invalidation) stays with the host and is reached
through the host's own tool object; this package never reimplements it.

When the operator grants the PR #5645 host capabilities
(``host_access.skill_mutations`` + ``host_access.evidence``), the package
additionally drives the host's guarded managed-mutation backbone
(``mutations.py``: read → stage → check → commit / discard / revert over
sealed completed-run evidence) through read-only-owner plugin actions.

Design: docs/design.md in this example package, and
https://github.com/bytedance/deer-flow/discussions/6954 (RFC 6954).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from deerflow_extension_api import BackendAction, BrowserAssets, ExtensionInstall, ExtensionRegistry, PluginContribution, extension

from deerflow_extension_skill_evolution.actions import ManagedEvolutionActions
from deerflow_extension_skill_evolution.config import parse_config
from deerflow_extension_skill_evolution.configure import SkillConfigurator
from deerflow_extension_skill_evolution.drafts import AnnotationDrafts
from deerflow_extension_skill_evolution.evolve import AnnotationEvolution
from deerflow_extension_skill_evolution.evolved import EvolvedSkills, EvolvedSkillStore
from deerflow_extension_skill_evolution.feedback import build_skill_feedback_tool
from deerflow_extension_skill_evolution.middleware import SkillEvolutionContributor
from deerflow_extension_skill_evolution.modes import EvolutionModeSettings
from deerflow_extension_skill_evolution.mutations import ManagedEvolution
from deerflow_extension_skill_evolution.service import CapabilityHandle, SkillEvolutionBridgeService
from deerflow_extension_skill_evolution.status import NAMESPACE, StatusReporter
from deerflow_extension_skill_evolution.tools import resolve_skill_manage_tool
from deerflow_extension_skill_evolution.trajectories import SkillTrajectories

__all__ = ["install"]
__version__ = "0.18.0"

logger = logging.getLogger(__name__)


@extension(api="0.2.8", name="skill-evolution")
def install(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    """Register the evolution policy prompt, the ``skill_manage`` tool entry,
    and the guarded managed-mutation pipeline actions.

    Fail-closed by construction: an invalid private config raises
    ``ValueError`` and a host without the ``skill_manage`` tool raises
    ``RuntimeError`` — the loader attributes both to this extension, and a
    ``required: true`` deployment turns them into a startup abort rather than
    a half-usable capability. There is deliberately no private ``enabled``
    key: the ``plugins:`` entry's own ``enabled`` flag is the single
    deployment switch.
    """
    settings = parse_config(config)
    skill_manage = resolve_skill_manage_tool()

    # Plugin-owned record of skills saved through the managed pipeline; the
    # page's "self-evolved skills" listing stays empty (UNAVAILABLE) without
    # an operator-configured storage_path.
    store = EvolvedSkillStore(settings.storage_path) if settings.storage_path else None
    mode_settings = EvolutionModeSettings(settings.storage_path)

    # Annotation-driven evolution has two shapes behind one runtime switch,
    # ``evolution_mode`` (settings JSON beside storage_path, see modes.py):
    # "model" runs background model jobs (evolve.py), "append" synthesizes
    # the deterministic feedback section (drafts.py). Both are always wired;
    # each action checks the live mode per call. The read-only skill_feedback
    # tool records annotations in either mode — annotations feed both paths —
    # so it is declared whenever they have a store to live in. A host without
    # the tool seams degrades to page-side annotation only.
    tools: list[Any] = [skill_manage]
    if store is not None:
        try:
            tools.append(build_skill_feedback_tool(store))
        except RuntimeError:
            logger.warning("skill-evolution: the host lacks the skill_feedback tool seams; annotation capture stays page-side")
    registry.middlewares(SkillEvolutionContributor(settings=settings, tools=tools))

    # Captures deps.skill_mutations, deps.completed_run_evidence and
    # deps.model_invoker at service start when the operator granted the
    # corresponding host_access entries; the slots stay None otherwise.
    mutations_handle = CapabilityHandle()
    evidence_handle = CapabilityHandle()
    model_handle = CapabilityHandle()
    registry.service(SkillEvolutionBridgeService(mutations=mutations_handle, evidence=evidence_handle, model=model_handle))

    evolution = ManagedEvolution(mutations_handle, evidence_handle, recorder=store)
    actions = ManagedEvolutionActions(evolution)
    drafts = AnnotationDrafts(evolution, store, mode_reader=mode_settings.read)
    jobs = AnnotationEvolution(evolution, store, model_handle, mode_reader=mode_settings.read)
    trajectories = SkillTrajectories(evidence_handle, store)
    configurator = SkillConfigurator(mode_reader=mode_settings.read, mode_writer=mode_settings.write)
    reporter = StatusReporter(settings=settings, extension_version=__version__, mutations_handle=mutations_handle, evidence_handle=evidence_handle, model_handle=model_handle, mode_reader=mode_settings.read)
    accepted = registry.plugin(
        PluginContribution(
            namespace=NAMESPACE,
            title="Agent 自演进 / Agent self-evolution",
            description="Agent 自演进工作台：通过 Skill 模块从使用反馈中改进技能，预留 Memory 等演进能力。所有变更均经过宿主受控管线。",
            enabled=True,
            frontend=BrowserAssets(
                module="skill-evolution.v1",
                root=Path(__file__).resolve().parent,
                manifest="ui_manifest.json",
            ),
            backend=(
                BackendAction("status", reporter.status),
                BackendAction("skill_config", configurator.status),
                BackendAction("skill_config_write", configurator.write),
                BackendAction("evolved_skills", EvolvedSkills(store).list),
                BackendAction("evolved_version", EvolvedSkills(store).version),
                BackendAction("managed_read", actions.managed_read),
                BackendAction("managed_stage", actions.managed_stage),
                BackendAction("managed_check", actions.managed_check),
                BackendAction("managed_propose", actions.managed_propose),
                BackendAction("managed_publish", actions.managed_publish),
                BackendAction("managed_discard", actions.managed_discard),
                BackendAction("managed_rollback", actions.managed_rollback),
                BackendAction("annotation_draft", drafts.annotation_draft),
                BackendAction("annotation_evolve", jobs.launch),
                BackendAction("evolution_status", jobs.status),
                BackendAction("evolution_discard", jobs.discard),
                BackendAction("skill_trajectories", trajectories.list),
                BackendAction("trajectory_annotate", trajectories.annotate),
                BackendAction("trajectory_unannotate", trajectories.unannotate),
            ),
        )
    )
    if not accepted:
        logger.info("skill-evolution: this host does not accept full-stack plugin contributions; the status and managed-mutation surfaces are disabled")


_entry_point: ExtensionInstall = install
