"""Regression test for the writability of the mounted extensions config.

``AGENTS.md`` states that ``config.yaml`` / ``extensions_config.json`` "may be
edited at runtime via the Gateway API", and the Gateway implements exactly that
for the latter: ``PUT``/``PATCH /api/mcp/config``, the MCP enable/disable switch
in the settings UI, and the skill update route all funnel into
``atomic_write_extensions_config``.

The production compose file mounted that path read-only, so every one of those
writes failed against the shipped artifact. Two independent kernel behaviours
were involved and both are covered here plus in
``test_extensions_config_atomic_write.py``:

1. A read-only bind mount rejects the write outright.
2. Even read-write, the destination is its own mount point, and Linux refuses
   ``rename()`` over a mount point with ``EBUSY``. That half is handled by the
   in-place fallback in ``atomic_write_extensions_config``.

``config.yaml`` deliberately stays read-only: no API writes it, and the
top-level ``plugins:`` list it carries causes code to be imported, so it is
kept out of the API-writable surface on purpose.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PROD_COMPOSE = REPO_ROOT / "docker" / "docker-compose.yaml"

EXTENSIONS_CONFIG_TARGET = "/app/backend/extensions_config.json"
APP_CONFIG_TARGET = "/app/backend/config.yaml"


def _gateway_volume_for(target: str) -> str:
    compose = yaml.safe_load(PROD_COMPOSE.read_text(encoding="utf-8"))
    volumes = compose["services"]["gateway"]["volumes"]
    matches = [str(entry) for entry in volumes if str(entry).split(":")[1:2] == [target]]
    assert len(matches) == 1, f"expected exactly one gateway mount for {target}, got {matches}"
    return matches[0]


def _mount_options(volume: str) -> set[str]:
    """Return the option flags of a short-syntax ``source:target[:options]`` mount.

    Options are comma-separated, so ``ro`` can legally appear as ``ro,z`` or
    ``z,ro``. Testing the raw string for a ``:ro`` suffix would read those as
    writable and let a read-only regression through.
    """
    parts = volume.split(":")
    if len(parts) < 3:
        return set()
    return {option.strip() for option in parts[2].split(",") if option.strip()}


@pytest.mark.parametrize(
    ("volume", "expected"),
    [
        ("./src:/dst", set()),
        ("./src:/dst:ro", {"ro"}),
        ("./src:/dst:ro,z", {"ro", "z"}),
        ("./src:/dst:z,ro", {"z", "ro"}),
        ("./src:/dst:rw", {"rw"}),
    ],
)
def test_mount_options_parses_comma_separated_flags(volume: str, expected: set[str]) -> None:
    assert _mount_options(volume) == expected


def test_extensions_config_is_mounted_writable() -> None:
    mount = _gateway_volume_for(EXTENSIONS_CONFIG_TARGET)
    assert "ro" not in _mount_options(mount), f"the Gateway writes {EXTENSIONS_CONFIG_TARGET} at runtime, so it must not be mounted read-only: {mount}"


def test_app_config_stays_read_only() -> None:
    mount = _gateway_volume_for(APP_CONFIG_TARGET)
    assert "ro" in _mount_options(mount), f"no API writes {APP_CONFIG_TARGET}; it must stay read-only: {mount}"
