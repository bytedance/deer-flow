from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from deerflow.extensions.loader import ExtensionSpec, load_extensions


def granted(**overrides):
    return ExtensionSpec(
        use="example:install",
        name="evolution",
        host_access={
            "evidence": {"owners": ["owner"]},
            "skill_mutations": {"owners": ["owner"], "operations": ["stage", "check"], "trigger_agents": ["agent"], "target_skills": ["example"], **overrides},
        },
    )


def test_host_access_is_default_deny_and_not_private_config():
    plain = ExtensionSpec(use="example:install")
    assert plain.host_access.evidence.owners == ()
    assert plain.host_access.skill_mutations.operations == ()
    spec = granted()
    assert spec.config == {}
    assert spec.host_access.skill_mutations.operations == ("stage", "check")


@pytest.mark.parametrize("key,value", [("owners", ["*"]), ("operations", ["create"]), ("trigger_agents", [""]), ("target_skills", ["../bad"]), ("topology", "multi_node")])
def test_invalid_grants_rejected(key, value):
    with pytest.raises(ValidationError):
        granted(**{key: value})


def test_host_access_requires_stable_name():
    with pytest.raises(ValidationError):
        ExtensionSpec(use="example:install", host_access={"evidence": {"owners": ["owner"]}})


def test_granted_source_cannot_be_ambiguous_even_with_other_ungranted_entry(monkeypatch):
    calls = []
    monkeypatch.setattr("deerflow.extensions.loader.resolve_variable", lambda _: calls.append(1))
    with pytest.raises(ValueError, match="unique"):
        load_extensions([granted(), ExtensionSpec(use="example:install", name="other")])
    assert calls == []


def test_granted_name_cannot_be_ambiguous(monkeypatch):
    monkeypatch.setattr("deerflow.extensions.loader.resolve_variable", lambda _: None)
    with pytest.raises(ValueError, match="unique"):
        load_extensions([granted(), ExtensionSpec(use="other:install", name="evolution")])


def test_binding_changes_with_entry_point_and_empty_scope_means_none():
    from deerflow.extensions.host_access import bind_host_access

    first = bind_host_access([granted()])["example:install"]
    replacement = granted().model_copy(update={"use": "replacement:install"})
    second = bind_host_access([replacement])["replacement:install"]
    assert first.plugin_id != second.plugin_id
    assert not first.allows("commit", "owner", "example")
    assert first.allows("stage", "owner", "example")
    assert not first.allows("stage", "another", "example")
    empty = granted(owners=[])
    assert not bind_host_access([empty])["example:install"].allows("stage", "owner", "example")


@pytest.mark.asyncio
async def test_services_receive_independently_bound_capabilities():
    from deerflow.extensions.gateway import start_services
    from deerflow.extensions.registry import ExtensionRegistry

    received = []

    class Service:
        async def start(self, deps):
            received.append(deps)

    registry = ExtensionRegistry()
    for source in ("first", "second"):
        with registry.attributed_to(source):
            registry.service(Service())
    first, second = object(), object()
    await start_services(registry.build(), SimpleNamespace(), None, host_capabilities={"first": (first, None), "second": (None, second)})
    assert received[0].completed_run_evidence is first
    assert received[0].skill_mutations is None
    assert received[1].completed_run_evidence is None
    assert received[1].skill_mutations is second


def test_new_host_contracts_are_available_without_harness_imports():
    import deerflow_extension_api as api

    for name in (
        "HostCapabilityError",
        "CompletedRunSnapshot",
        "CompletedRunEvent",
        "CompletedRunEventPage",
        "CompletedRunEvidenceReader",
        "EvidenceLimits",
        "AssetRevision",
        "SkillRevisionView",
        "MutationCapabilities",
        "Proposal",
        "ProposalBundle",
        "BundleFile",
        "HostCheckResult",
        "AssessmentRef",
        "Operation",
        "SkillMutationService",
    ):
        assert name in api.__all__
        assert getattr(api, name).__module__.startswith("deerflow_extension_api.")


def test_mutation_bundles_and_capabilities_detach_mutable_constructor_values():
    from deerflow_extension_api import AssetRevision, BundleFile, MutationCapabilities, Proposal, ProposalBundle

    content = bytearray(b"original")
    files = [BundleFile("SKILL.md", content, "digest", False)]
    revision = AssetRevision("incarnation", 1, "digest")
    bundle = ProposalBundle("p", files, files, revision, "hash")
    ops = ["stage"]
    caps = MutationCapabilities(ops)
    sources = ["s"]
    proposal = Proposal("p", "o", "t", "skill", revision, "hash", "STAGED", "expiry", sources)
    content[:] = b"tampered"
    files.clear()
    ops.append("commit")
    sources.clear()
    assert bundle.baseline[0].content == b"original"
    assert caps.operations == ("stage",)
    assert proposal.source_refs == ("s",)
