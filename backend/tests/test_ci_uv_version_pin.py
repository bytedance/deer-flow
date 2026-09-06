"""Regression test pinning CI's uv binary to the version production ships.

``ExtensionManager`` is not a consumer of uv the build tool -- it is a program
whose whole job is driving ``uv`` as a subprocess, depending on its CLI
behavior (``--no-workspace``, ``--no-sync``, what ``uv add`` writes into
``[dependency-groups] extensions``) and on the ``uv.lock`` serialization
format. uv is therefore closer to a runtime dependency with a contract than to
incidental tooling.

``backend/Dockerfile`` pins that binary to an exact version, but every
``astral-sh/setup-uv`` step used to install whatever was latest at run time, so
CI exercised the manager against a uv that is not the uv production runs. The
sharpest failure that allows: a newer uv bumps ``uv.lock``'s ``revision``,
CI stays green because the same uv reads back what it wrote, and the pinned uv
in the production image then cannot read the committed lock. ``uv lock
--check`` is version-sensitive for the same reason -- it verifies the lock is
what *this* uv would produce, and two versions can emit equivalent but
non-identical output.

Pinning is only half of it; without this test the two pins drift apart again
the next time someone bumps one of them. Upgrading uv should be one explicit
change that touches the Dockerfile, the workflows, and this test together.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
COMPOSE_PATHS = (
    REPO_ROOT / "docker" / "docker-compose.yaml",
    REPO_ROOT / "docker" / "docker-compose-dev.yaml",
)

_UV_IMAGE_REFERENCE = re.compile(r"ghcr\.io/astral-sh/uv:(?P<version>\d+\.\d+\.\d+)")
_SETUP_UV_ACTION = re.compile(r"^astral-sh/setup-uv@(?P<ref>[^\s]+)$")


def _pinned_uv_version() -> str:
    """The single source of truth: the uv image the backend image builds from."""
    match = _UV_IMAGE_REFERENCE.search(BACKEND_DOCKERFILE.read_text(encoding="utf-8"))
    assert match is not None, f"{BACKEND_DOCKERFILE} no longer pins a ghcr.io/astral-sh/uv version"
    return match.group("version")


def _workflow_paths() -> list[Path]:
    return sorted(path for path in WORKFLOWS_DIR.iterdir() if path.suffix in {".yml", ".yaml"})


def _setup_uv_steps() -> list[tuple[str, str, dict]]:
    """Return (workflow name, action ref, step mapping) for each setup-uv step."""
    steps: list[tuple[str, str, dict]] = []
    for path in _workflow_paths():
        workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job in (workflow.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                uses = step.get("uses")
                if not isinstance(uses, str):
                    continue
                match = _SETUP_UV_ACTION.match(uses.strip())
                if match is not None:
                    steps.append((path.name, match.group("ref"), step))
    return steps


def test_the_repository_still_has_setup_uv_steps_to_check():
    """Guard against the other assertions silently passing on an empty list."""
    assert _setup_uv_steps(), "no astral-sh/setup-uv steps found; this test needs updating"


def test_every_setup_uv_step_pins_the_uv_version_production_ships():
    expected = _pinned_uv_version()

    unpinned: list[str] = []
    mismatched: list[str] = []
    for workflow_name, _ref, step in _setup_uv_steps():
        with_block = step.get("with")
        version = with_block.get("version") if isinstance(with_block, dict) else None
        if version is None:
            unpinned.append(f"{workflow_name}: {step.get('name', '<unnamed step>')}")
        elif str(version) != expected:
            mismatched.append(f"{workflow_name}: {version!r} != {expected!r}")

    assert not unpinned, f"setup-uv steps install whatever uv is latest, so CI would not exercise the uv production ships ({expected}): {unpinned}"
    assert not mismatched, f"setup-uv steps pin a uv other than the one backend/Dockerfile ships ({expected}): {mismatched}"


def test_every_setup_uv_step_uses_the_same_action_version():
    refs = {ref for _workflow_name, ref, _step in _setup_uv_steps()}

    assert len(refs) == 1, f"astral-sh/setup-uv is referenced at mixed action versions, so the steps do not share caching or input behavior: {sorted(refs)}"


@pytest.mark.parametrize("compose_path", COMPOSE_PATHS, ids=lambda path: path.name)
def test_compose_uv_image_default_matches_the_backend_dockerfile(compose_path: Path):
    """The compose override defaults must not drift from the image they build."""
    expected = _pinned_uv_version()
    versions = set(_UV_IMAGE_REFERENCE.findall(compose_path.read_text(encoding="utf-8")))

    assert versions, f"{compose_path.name} no longer references a pinned uv image"
    assert versions == {expected}, f"{compose_path.name} defaults to uv {sorted(versions)} while backend/Dockerfile ships {expected!r}"
