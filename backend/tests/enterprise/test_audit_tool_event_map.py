"""Tests for ``tool_event_map`` routing (plan M2-5b)."""

from __future__ import annotations

import pytest

from deerflow.enterprise.audit.events import AuditEventType
from deerflow.enterprise.audit.tool_event_map import (
    RECORDED_TOOLS,
    extract_mcp_server,
    map_tool_to_event_type,
)


@pytest.mark.parametrize("tool", ["bash", "write_file", "str_replace"])
def test_sandbox_writes_map_to_sandbox_command(tool: str):
    assert map_tool_to_event_type(tool) == AuditEventType.SANDBOX_COMMAND_EXECUTED


@pytest.mark.parametrize("tool", ["ls", "read_file", "view_image", "present_files", "write_todos"])
def test_read_only_whitelist_is_skipped(tool: str):
    assert map_tool_to_event_type(tool) is None


@pytest.mark.parametrize("tool", ["mcp:figma:get_file", "mcp:slack:post_message"])
def test_mcp_tools_map_to_tool_invoked(tool: str):
    assert map_tool_to_event_type(tool) == AuditEventType.TOOL_INVOKED


@pytest.mark.parametrize("tool", ["tavily_search", "jina_fetch", "firecrawl_crawl"])
def test_community_data_tools_map_to_data_exported(tool: str):
    assert map_tool_to_event_type(tool) == AuditEventType.DATA_EXPORTED


def test_unknown_tool_falls_through_to_default():
    """Future tools we don't know about still get recorded so we don't drop them silently."""
    assert map_tool_to_event_type("brand_new_tool") == AuditEventType.AGENT_TASK_COMPLETED


def test_extract_mcp_server_parses_three_segment_names():
    assert extract_mcp_server("mcp:figma:get_file") == "figma"


def test_extract_mcp_server_returns_none_for_non_mcp():
    assert extract_mcp_server("bash") is None


def test_recorded_tools_inverse_of_whitelist():
    """``RECORDED_TOOLS`` should never overlap with read-only whitelist."""
    overlap = RECORDED_TOOLS & {"ls", "read_file", "view_image", "present_files", "write_todos"}
    assert overlap == frozenset()
