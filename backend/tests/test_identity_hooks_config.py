"""Tests for identityHooks extensions config parsing."""

import json

import pytest

from deerflow.config.extensions_config import ExtensionsConfig, IdentityHookCall, IdentityHooksConfig


def test_identity_hooks_absent_defaults_to_none():
    config = ExtensionsConfig.model_validate({"mcpServers": {}, "skills": {}})
    assert config.identity_hooks is None


def test_identity_hooks_disabled_parses():
    raw = {
        "identityHooks": {
            "enabled": False,
            "mcpServerRef": "lithtrix",
            "sessionStart": [],
        }
    }
    config = ExtensionsConfig.model_validate(raw)
    assert config.identity_hooks is not None
    assert config.identity_hooks.enabled is False
    assert config.identity_hooks.mcp_server_ref == "lithtrix"
    assert config.identity_hooks.session_start == []


def test_identity_hooks_reference_lithtrix_session_start():
    raw = {
        "mcpServers": {
            "lithtrix": {
                "enabled": True,
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "lithtrix-mcp@0.20.2"],
            }
        },
        "identityHooks": {
            "enabled": True,
            "mcpServerRef": "lithtrix",
            "sessionStart": [
                {"tool": "lithtrix_memory_context", "args": {"limit": 10}},
                {"tool": "lithtrix_commons_read", "args": {"page": 1, "per_page": 20}},
            ],
        },
    }
    config = ExtensionsConfig.model_validate(raw)
    hooks = config.identity_hooks
    assert hooks is not None
    assert hooks.enabled is True
    assert len(hooks.session_start) == 2
    assert hooks.session_start[0] == IdentityHookCall(tool="lithtrix_memory_context", args={"limit": 10})
    assert hooks.session_start[1] == IdentityHookCall(tool="lithtrix_commons_read", args={"page": 1, "per_page": 20})


def test_identity_hooks_camel_case_aliases_round_trip():
    hooks = IdentityHooksConfig(
        enabled=True,
        mcp_server_ref="lithtrix",
        session_start=[IdentityHookCall(tool="lithtrix_memory_context", args={"limit": 5})],
    )
    dumped = hooks.model_dump(by_alias=True)
    assert dumped["mcpServerRef"] == "lithtrix"
    assert dumped["sessionStart"][0]["tool"] == "lithtrix_memory_context"


def test_identity_hooks_from_json_file(tmp_path):
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text(
        json.dumps(
            {
                "identityHooks": {
                    "enabled": True,
                    "mcpServerRef": "lithtrix",
                    "sessionStart": [{"tool": "lithtrix_memory_context", "args": {"limit": 3}}],
                }
            }
        ),
        encoding="utf-8",
    )
    config = ExtensionsConfig.from_file(str(config_path))
    assert config.identity_hooks is not None
    assert config.identity_hooks.session_start[0].args == {"limit": 3}
