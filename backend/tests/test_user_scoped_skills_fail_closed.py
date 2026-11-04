"""A broken extensions config must not take down a user-scoped skill listing.

``UserScopedSkillStorage._load_skills_unlocked`` re-reads the extensions config to AND the per-user state
with the global default. That second read is unguarded, so a config that cannot be read raised out of
``load_skills()`` for user-scoped deployments even after the local/global path learned to degrade.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deerflow.config.extensions_config import ExtensionsConfig, reset_extensions_config
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage

_SKILL_MD = """---
name: {name}
description: {name} description
---
body
"""


def _raise_unreadable_config(*_args: object, **_kwargs: object) -> None:
    # What one schema-invalid ``mcpServers`` entry raises from
    # ``McpServerConfig._validate_header_names``; a malformed JSON file raises
    # ``ValueError`` from the same call site.
    raise ValueError("headers maps the same HTTP header under two spellings ('X-Api-Key' and 'x-api-key')")


@pytest.fixture()
def user_skills_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A skills root with one public skill and a readable extensions config."""
    root = tmp_path / "skills"
    public = root / "public" / "demo"
    public.mkdir(parents=True)
    (public / "SKILL.md").write_text(_SKILL_MD.format(name="demo"), encoding="utf-8")
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))
    reset_extensions_config()
    return root


def test_user_scoped_listing_degrades_when_the_config_cannot_be_read(user_skills_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = UserScopedSkillStorage("owner", host_path=str(user_skills_root))

    assert [(skill.name, skill.enabled) for skill in storage.load_skills()] == [("demo", True)]

    monkeypatch.setattr(ExtensionsConfig, "from_file", classmethod(_raise_unreadable_config))

    # The listing survives: no exception, every skill present and disabled.
    assert [(skill.name, skill.enabled) for skill in storage.load_skills()] == [("demo", False)]
    assert storage.load_skills(enabled_only=True) == []


def test_user_scoped_custom_skill_with_per_user_state_degrades_when_the_config_cannot_be_read(
    user_skills_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CUSTOM/LEGACY skills are the second read's own responsibility.

    Their per-user state exists only to be ANDed with the global default, so
    the degraded branch has to cover them too: with a per-user state present,
    an unreadable config still lists the custom skill — disabled — instead of
    raising out of ``load_skills()``. Dropping the guard turns this red: the
    second read raises out of the listing.
    """
    from deerflow.config.paths import Paths

    # Route the user custom root (and the per-user states file) into tmp.
    monkeypatch.setattr("deerflow.config.paths._paths", Paths(base_dir=tmp_path / "home"))
    custom_dir = tmp_path / "home" / "users" / "owner" / "skills" / "custom" / "my-tool"
    custom_dir.mkdir(parents=True)
    (custom_dir / "SKILL.md").write_text(_SKILL_MD.format(name="my-tool"), encoding="utf-8")
    states_file = tmp_path / "home" / "users" / "owner" / "skills" / "_skill_states.json"
    states_file.write_text(json.dumps({"my-tool": {"enabled": True}}), encoding="utf-8")

    storage = UserScopedSkillStorage("owner", host_path=str(user_skills_root))

    assert [(skill.name, skill.enabled) for skill in storage.load_skills()] == [("demo", True), ("my-tool", True)]

    monkeypatch.setattr(ExtensionsConfig, "from_file", classmethod(_raise_unreadable_config))

    # The listing survives: every skill present (per-user state on disk for
    # the custom one), none enabled, no exception.
    assert [(skill.name, skill.enabled) for skill in storage.load_skills()] == [("demo", False), ("my-tool", False)]
    assert storage.load_skills(enabled_only=True) == []
