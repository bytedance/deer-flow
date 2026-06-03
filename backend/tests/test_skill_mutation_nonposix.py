"""Non-POSIX hosts are refused before publication touches the filesystem.

These checks monkeypatch ``os.name`` so CI, which runs on POSIX, still
exercises the same branch Windows hits. The suites that need a real POSIX
host skip there instead of failing.
"""

import os
from types import SimpleNamespace

import pytest
from deerflow_extension_api.host_capabilities import HostCapabilityError

from deerflow.extensions.host_access import BoundHostAccess, HostAccess
from deerflow.skills.mutations.assets import capture_package
from deerflow.skills.mutations.service import HostSkillMutationService
from deerflow.skills.mutations.topology import PublicationTopology

_SKILL = "---\nname: example\ndescription: Example\n---\nBody\n"


def _service() -> HostSkillMutationService:
    """Build only the fields ``_authorize`` reads, without starting workers."""
    binding = BoundHostAccess(
        "plugin",
        HostAccess.model_validate(
            {
                "evidence": {"owners": ["owner"]},
                "skill_mutations": {
                    "owners": ["owner"],
                    "operations": ["stage"],
                    "trigger_agents": ["trainer"],
                    "target_skills": ["example"],
                    "topology": "single_host_local",
                },
            }
        ),
    )
    service = HostSkillMutationService.__new__(HostSkillMutationService)
    service.binding = binding
    service.runtime = SimpleNamespace(owners=frozenset({"owner"}))
    return service


def test_capture_package_refuses_non_posix_before_reading(tmp_path, monkeypatch):
    (tmp_path / "SKILL.md").write_text(_SKILL, encoding="utf-8")
    monkeypatch.setattr(os, "name", "nt")

    with pytest.raises(ValueError, match="^UNSUPPORTED_ASSET$"):
        capture_package(tmp_path)


def test_topology_acquire_refuses_non_posix_without_a_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    topology = PublicationTopology("sqlite", tmp_path)

    with pytest.raises(HostCapabilityError, match="^UNSUPPORTED_TOPOLOGY$"):
        topology.acquire()

    assert topology._fd is None


def test_authorize_refuses_non_posix_even_with_a_local_grant(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")

    with pytest.raises(HostCapabilityError, match="^UNSUPPORTED_TOPOLOGY$"):
        _service()._authorize("owner", "example")


def test_authorize_accepts_a_posix_local_grant(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")

    assert _service()._authorize("owner", "example") is None
