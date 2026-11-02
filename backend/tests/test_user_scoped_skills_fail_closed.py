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

    def _raise(*_args: object, **_kwargs: object) -> None:
        # What one schema-invalid ``mcpServers`` entry raises; a malformed JSON file raises ``ValueError`` from the same call site.
        raise ValueError("headers maps the same HTTP header under two spellings ('X-Api-Key' and 'x-api-key')")

    monkeypatch.setattr(ExtensionsConfig, "from_file", classmethod(_raise))

    # The listing survives: no exception, every skill present and disabled.
    assert [(skill.name, skill.enabled) for skill in storage.load_skills()] == [("demo", False)]
    assert storage.load_skills(enabled_only=True) == []
