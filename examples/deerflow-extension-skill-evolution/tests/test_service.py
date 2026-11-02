import asyncio
from types import SimpleNamespace

from deerflow_extension_skill_evolution.service import CapabilityHandle, SkillEvolutionBridgeService


def _deps(**overrides):
    """Minimal stand-in for ExtensionRuntimeDeps."""
    return SimpleNamespace(**overrides)


def _bridge():
    mutations, evidence = CapabilityHandle(), CapabilityHandle()
    return mutations, evidence, SkillEvolutionBridgeService(mutations=mutations, evidence=evidence)


def test_handles_start_empty() -> None:
    assert CapabilityHandle().get() is None


def test_bridge_captures_delivered_handles() -> None:
    mutations, evidence, service = _bridge()
    bound_service, bound_reader = object(), object()
    asyncio.run(service.start(_deps(skill_mutations=bound_service, completed_run_evidence=bound_reader)))
    assert mutations.get() is bound_service
    assert evidence.get() is bound_reader


def test_bridge_tolerates_deps_without_the_fields() -> None:
    # Hosts older than API 0.2.7 have neither attribute at all.
    mutations, evidence, service = _bridge()
    asyncio.run(service.start(_deps(app_store=None)))
    assert mutations.get() is None
    assert evidence.get() is None


def test_bridge_binds_none_when_ungranted() -> None:
    mutations, evidence, service = _bridge()
    asyncio.run(service.start(_deps(skill_mutations=None, completed_run_evidence=None)))
    assert mutations.get() is None
    assert evidence.get() is None


def test_stop_releases_the_handles() -> None:
    mutations, evidence, service = _bridge()
    asyncio.run(service.start(_deps(skill_mutations=object(), completed_run_evidence=object())))
    asyncio.run(service.stop())
    assert mutations.get() is None
    assert evidence.get() is None


def test_rebind_replaces_the_handles() -> None:
    mutations, evidence, service = _bridge()
    first, second = object(), object()
    asyncio.run(service.start(_deps(skill_mutations=first, completed_run_evidence=object())))
    asyncio.run(service.start(_deps(skill_mutations=second, completed_run_evidence=object())))
    assert mutations.get() is second
