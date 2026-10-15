"""Tests for MCP routing hint configuration."""

from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig, resolve_effective_mcp_routing


def test_server_default_routing_applies_to_every_tool():
    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "postgres": {
                    "routing": {
                        "mode": "prefer",
                        "priority": 50,
                        "keywords": ["订单", "SQL"],
                    }
                }
            }
        }
    )

    routing = resolve_effective_mcp_routing(config.mcp_servers["postgres"], "query")

    assert routing["mode"] == "prefer"
    assert routing["priority"] == 50
    assert routing["keywords"] == ["订单", "SQL"]


def test_tool_routing_override_only_replaces_explicit_fields():
    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "postgres": {
                    "routing": {
                        "mode": "prefer",
                        "priority": 20,
                        "keywords": ["database", "table"],
                    },
                    "tools": {
                        "query": {
                            "routing": {
                                "priority": 100,
                            }
                        }
                    },
                }
            }
        }
    )

    routing = resolve_effective_mcp_routing(config.mcp_servers["postgres"], "query")

    assert routing == {
        "mode": "prefer",
        "priority": 100,
        "keywords": ["database", "table"],
    }


def test_invalid_routing_mode_fails_validation():
    with pytest.raises(ValidationError):
        ExtensionsConfig.model_validate(
            {
                "mcpServers": {
                    "postgres": {
                        "routing": {
                            "mode": "require",
                        }
                    }
                }
            }
        )


@pytest.mark.parametrize(
    ("raw_priority", "expected"),
    [
        (-1, 0),
        (101, 100),
    ],
)
def test_out_of_range_priority_is_clamped_with_warning(caplog, raw_priority: int, expected: int):
    caplog.set_level(logging.WARNING)

    server = McpServerConfig(routing={"mode": "prefer", "priority": raw_priority})

    assert server.routing.priority == expected
    assert "MCP routing priority" in caplog.text


def test_unknown_routing_fields_are_rejected():
    with pytest.raises(ValidationError):
        ExtensionsConfig.model_validate(
            {
                "mcpServers": {
                    "postgres": {
                        "routing": {
                            "mode": "prefer",
                            "unknown": True,
                        }
                    }
                }
            }
        )
