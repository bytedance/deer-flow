import json
from pathlib import Path

import pytest

from deerflow.config.extensions_config import ExtensionsConfig


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_user_mcp_settings_path_resolves_under_runtime_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "state"))

    assert ExtensionsConfig.user_mcp_settings_path("user-1") == tmp_path / "state" / "users" / "user-1" / "mcp_settings.json"


@pytest.mark.parametrize("user_id", ["", "   ", ".", "..", "../other", "nested/user", "nested\\user"])
def test_user_mcp_settings_path_rejects_unsafe_user_ids(user_id: str):
    with pytest.raises(ValueError, match="Invalid user_id"):
        ExtensionsConfig.user_mcp_settings_path(user_id)


def test_from_file_keeps_existing_behavior_without_user_id(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "state"))
    global_config = tmp_path / "extensions_config.json"
    user_config = tmp_path / "state" / "users" / "user-1" / "mcp_settings.json"

    _write_json(
        global_config,
        {
            "mcpServers": {
                "global-server": {
                    "enabled": True,
                    "type": "stdio",
                    "command": "global-command",
                }
            },
            "skills": {"global-skill": {"enabled": True}},
        },
    )
    _write_json(
        user_config,
        {
            "mcpServers": {
                "user-server": {
                    "enabled": True,
                    "type": "stdio",
                    "command": "user-command",
                }
            }
        },
    )

    config = ExtensionsConfig.from_file(str(global_config))

    assert set(config.mcp_servers) == {"global-server"}
    assert set(config.skills) == {"global-skill"}


def test_from_file_merges_user_mcp_settings_from_user_id(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "state"))
    global_config = tmp_path / "extensions_config.json"
    user_config = tmp_path / "state" / "users" / "user-1" / "mcp_settings.json"

    _write_json(
        global_config,
        {
            "mcpServers": {
                "shared": {
                    "enabled": True,
                    "type": "stdio",
                    "command": "global-command",
                    "args": ["global"],
                    "description": "Global server",
                }
            },
            "skills": {"global-skill": {"enabled": True}},
        },
    )
    _write_json(
        user_config,
        {
            "mcpServers": {
                "shared": {
                    "enabled": False,
                    "args": ["user"],
                },
                "user-only": {
                    "enabled": True,
                    "type": "stdio",
                    "command": "user-command",
                },
            },
            "skills": {"ignored-user-skill": {"enabled": True}},
        },
    )

    config = ExtensionsConfig.from_file(str(global_config), user_id="user-1")

    assert set(config.mcp_servers) == {"shared", "user-only"}
    assert config.mcp_servers["shared"].enabled is False
    assert config.mcp_servers["shared"].command == "global-command"
    assert config.mcp_servers["shared"].args == ["user"]
    assert config.mcp_servers["shared"].description == "Global server"
    assert config.mcp_servers["user-only"].command == "user-command"
    assert set(config.skills) == {"global-skill"}


def test_from_file_merges_user_mcp_settings_from_explicit_path(tmp_path: Path):
    global_config = tmp_path / "extensions_config.json"
    user_config = tmp_path / "custom-user-mcp.json"

    _write_json(global_config, {"mcpServers": {}, "skills": {}})
    _write_json(
        user_config,
        {
            "mcpServers": {
                "user-only": {
                    "enabled": True,
                    "type": "stdio",
                    "command": "user-command",
                }
            }
        },
    )

    config = ExtensionsConfig.from_file(str(global_config), user_config_path=str(user_config))

    assert set(config.mcp_servers) == {"user-only"}


def test_from_file_supports_user_mcp_settings_without_global_config(tmp_path: Path):
    user_config = tmp_path / "user-mcp.json"
    _write_json(
        user_config,
        {
            "mcpServers": {
                "user-only": {
                    "enabled": True,
                    "type": "stdio",
                    "command": "user-command",
                }
            }
        },
    )

    config = ExtensionsConfig.from_file(user_config_path=str(user_config))

    assert set(config.mcp_servers) == {"user-only"}
    assert config.skills == {}


def test_from_file_rejects_invalid_user_mcp_settings_json(tmp_path: Path):
    global_config = tmp_path / "extensions_config.json"
    user_config = tmp_path / "bad-user-mcp.json"

    _write_json(global_config, {"mcpServers": {}, "skills": {}})
    user_config.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match="User MCP settings file .* is not valid JSON"):
        ExtensionsConfig.from_file(str(global_config), user_config_path=str(user_config))


def test_from_file_rejects_non_object_user_mcp_settings(tmp_path: Path):
    global_config = tmp_path / "extensions_config.json"
    user_config = tmp_path / "bad-user-mcp.json"

    _write_json(global_config, {"mcpServers": {}, "skills": {}})
    user_config.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="must contain a JSON object"):
        ExtensionsConfig.from_file(str(global_config), user_config_path=str(user_config))


def test_merge_user_mcp_settings_rejects_non_object_mcp_servers():
    with pytest.raises(ValueError, match="User MCP settings field `mcpServers` must be an object"):
        ExtensionsConfig.merge_user_mcp_settings_data({"mcpServers": {}, "skills": {}}, {"mcpServers": []})
