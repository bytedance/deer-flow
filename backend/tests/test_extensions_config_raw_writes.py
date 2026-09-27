"""Runtime writers must round-trip ``extensions_config.json`` without expanding ``$VAR``.

``ExtensionsConfig.from_file()`` resolves every ``$VAR`` string into the live
environment value, and an unset variable into ``""``. Serializing that model
back to disk therefore persists secrets in plaintext and permanently erases
references to variables that are not set in the writing process. Every
read-modify-write must operate on the raw on-disk JSON instead; the MCP router
already does, and these tests pin the skill-state writers to the same contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.gateway.routers import skills as skills_router
from deerflow.config.extensions_config import (
    ExtensionsConfig,
    McpServerConfig,
    SkillStateConfig,
    read_raw_extensions_config,
    set_raw_skill_enabled,
    validate_raw_extensions_config,
)

SECRET = "ghp_live_secret_value"


def _raw_config_with_placeholders() -> dict:
    return {
        "mcpServers": {
            "github": {
                "enabled": True,
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {"GITHUB_TOKEN": "$DEERFLOW_TEST_GH_TOKEN", "OPTIONAL": "$DEERFLOW_TEST_UNSET_VAR"},
            },
            "remote": {
                "type": "http",
                "url": "https://mcp.example.com/mcp",
                "headers": {"Authorization": "$DEERFLOW_TEST_GH_TOKEN"},
            },
        },
        "mcpInterceptors": {"auth": "$DEERFLOW_TEST_GH_TOKEN"},
        "skills": {"existing-skill": {"enabled": True}},
    }


@pytest.fixture
def placeholder_env(monkeypatch):
    monkeypatch.setenv("DEERFLOW_TEST_GH_TOKEN", SECRET)
    monkeypatch.delenv("DEERFLOW_TEST_UNSET_VAR", raising=False)


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Harness helpers
# ---------------------------------------------------------------------------


def test_read_raw_keeps_placeholders(tmp_path: Path, placeholder_env) -> None:
    config_path = tmp_path / "extensions_config.json"
    _write_json(config_path, _raw_config_with_placeholders())

    assert read_raw_extensions_config(config_path) == _raw_config_with_placeholders()


def test_read_raw_rejects_invalid_json(tmp_path: Path) -> None:
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid JSON"):
        read_raw_extensions_config(config_path)


def test_read_raw_rejects_non_object(tmp_path: Path) -> None:
    config_path = tmp_path / "extensions_config.json"
    _write_json(config_path, ["not", "an", "object"])

    with pytest.raises(ValueError, match="JSON object"):
        read_raw_extensions_config(config_path)


def test_validate_raw_resolves_like_runtime_without_mutating_input(placeholder_env) -> None:
    raw = _raw_config_with_placeholders()

    validated = validate_raw_extensions_config(raw)

    assert validated.mcp_servers["github"].env == {"GITHUB_TOKEN": SECRET, "OPTIONAL": ""}
    assert raw == _raw_config_with_placeholders()


def test_validate_raw_rejects_runtime_invalid_candidate() -> None:
    with pytest.raises(ValidationError):
        validate_raw_extensions_config({"mcpServers": []})


def test_set_raw_skill_enabled_creates_skills_map() -> None:
    raw: dict = {"mcpServers": {}}

    set_raw_skill_enabled(raw, "demo-skill", False)

    assert raw == {"mcpServers": {}, "skills": {"demo-skill": {"enabled": False}}}


def test_set_raw_skill_enabled_keeps_sibling_entry_keys() -> None:
    raw: dict = {"skills": {"demo-skill": {"enabled": True, "note": "operator comment"}}}

    set_raw_skill_enabled(raw, "demo-skill", False)

    assert raw["skills"]["demo-skill"] == {"enabled": False, "note": "operator comment"}


def test_set_raw_skill_enabled_rejects_non_object_skills() -> None:
    with pytest.raises(ValueError, match="skills"):
        set_raw_skill_enabled({"skills": ["demo-skill"]}, "demo-skill", False)


# ---------------------------------------------------------------------------
# Gateway skill toggle writer
# ---------------------------------------------------------------------------


def _patch_gateway_writer(monkeypatch, config_path: Path, cached: ExtensionsConfig | None = None) -> None:
    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", staticmethod(lambda _path=None: config_path))
    monkeypatch.setattr(skills_router, "reload_extensions_config", lambda: None)
    monkeypatch.setattr(skills_router, "get_extensions_config", lambda: cached or ExtensionsConfig())


def test_gateway_skill_toggle_preserves_placeholders(tmp_path: Path, monkeypatch, placeholder_env) -> None:
    config_path = tmp_path / "extensions_config.json"
    _write_json(config_path, _raw_config_with_placeholders())
    _patch_gateway_writer(monkeypatch, config_path)

    skills_router._write_extensions_skill_state(None, "demo-skill", False, rebuild_public_projection=False)

    expected = _raw_config_with_placeholders()
    expected["skills"]["demo-skill"] = {"enabled": False}
    written_text = config_path.read_text(encoding="utf-8")
    assert json.loads(written_text) == expected
    assert SECRET not in written_text


def test_gateway_skill_toggle_new_file_does_not_serialize_resolved_cache(tmp_path: Path, monkeypatch, placeholder_env) -> None:
    config_path = tmp_path / "extensions_config.json"
    cached = ExtensionsConfig(
        mcp_servers={"github": McpServerConfig(command="npx", env={"GITHUB_TOKEN": SECRET})},
        skills={"existing-skill": SkillStateConfig(enabled=False)},
    )
    _patch_gateway_writer(monkeypatch, config_path, cached)

    skills_router._write_extensions_skill_state(None, "demo-skill", True, rebuild_public_projection=False)

    written_text = config_path.read_text(encoding="utf-8")
    assert json.loads(written_text) == {"skills": {"existing-skill": {"enabled": False}, "demo-skill": {"enabled": True}}}
    assert SECRET not in written_text
    assert "demo-skill" not in cached.skills


def test_gateway_skill_toggle_leaves_invalid_config_untouched(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "extensions_config.json"
    original = json.dumps({"mcpServers": [], "skills": {}})
    config_path.write_text(original, encoding="utf-8")
    _patch_gateway_writer(monkeypatch, config_path)

    with pytest.raises(ValidationError):
        skills_router._write_extensions_skill_state(None, "demo-skill", False, rebuild_public_projection=False)

    assert config_path.read_text(encoding="utf-8") == original
