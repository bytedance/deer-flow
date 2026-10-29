"""A broken extensions config must not re-enable a disabled skill.

``SkillStorage.load_skills()`` merges the enabled state from
``extensions_config.json``. When that file cannot be read, the parsed default
(``enabled=True`` from ``parse_skill_file``) must not stand in for the answer:
an unrelated defect in the file — a malformed ``mcpServers`` entry, a trailing
comma — would otherwise silently re-enable every skill an operator disabled.

The sandbox projection fails closed on the same error
(``projection._rebuild_public_locked`` clears the view), so the runtime half of
the gate has to agree with it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deerflow.config.extensions_config import ExtensionsConfig, reset_extensions_config
from deerflow.skills.storage.local_skill_storage import LocalSkillStorage

_SKILL_MD = """---
name: {name}
description: {name} description
---
body
"""


def _write_public_skill(root: Path, name: str) -> None:
    skill_dir = root / "public" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(_SKILL_MD.format(name=name), encoding="utf-8")


@pytest.fixture()
def disabled_skill_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A skills root whose only skill is disabled in the extensions config."""
    root = tmp_path / "skills"
    _write_public_skill(root, "demo")
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text(
        json.dumps({"mcpServers": {}, "skills": {"demo": {"enabled": False}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))
    reset_extensions_config()
    return root


def test_disabled_skill_is_disabled_while_the_config_loads(disabled_skill_root: Path) -> None:
    storage = LocalSkillStorage(str(disabled_skill_root))

    assert [(skill.name, skill.enabled) for skill in storage.load_skills()] == [("demo", False)]
    assert storage.load_skills(enabled_only=True) == []


def test_disabled_skill_stays_disabled_when_the_config_cannot_be_read(
    disabled_skill_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalSkillStorage(str(disabled_skill_root))

    def _raise(*_args: object, **_kwargs: object) -> None:
        # What one schema-invalid ``mcpServers`` entry raises from
        # ``McpServerConfig._validate_header_names``; a malformed JSON file
        # raises ``ValueError`` from the same call site.
        raise ValueError("headers maps the same HTTP header under two spellings ('X-Api-Key' and 'x-api-key')")

    monkeypatch.setattr(ExtensionsConfig, "from_file", classmethod(_raise))

    # Still listed, so the skill does not silently disappear from the UI...
    assert [(skill.name, skill.enabled) for skill in storage.load_skills()] == [("demo", False)]
    # ...and never handed to the model as usable.
    assert storage.load_skills(enabled_only=True) == []
