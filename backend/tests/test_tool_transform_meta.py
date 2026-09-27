"""Declared transform trail for tool results.

Middlewares between the raw callable and the model-visible result append an
entry, so a consumer classifies raw -> visible transforms from facts instead of
sniffing output wording.
"""

from langchain_core.messages import ToolMessage

from deerflow.agents.middlewares.tool_transform_meta import (
    TOOL_TRANSFORMS_KEY,
    append_tool_transform,
    read_tool_transforms,
)


def test_entries_are_ordered_by_application():
    kwargs: dict = {}
    append_tool_transform(kwargs, "sanitized", by="ToolResultSanitizationMiddleware")
    append_tool_transform(kwargs, "truncated", by="ToolOutputBudgetMiddleware")
    assert [entry["kind"] for entry in kwargs[TOOL_TRANSFORMS_KEY]] == ["sanitized", "truncated"]


def test_read_returns_empty_for_an_untagged_message():
    assert read_tool_transforms(ToolMessage(content="x", tool_call_id="1")) == ()


def test_read_ignores_a_malformed_trail_rather_than_raising():
    message = ToolMessage(content="x", tool_call_id="1", additional_kwargs={TOOL_TRANSFORMS_KEY: "not-a-list"})
    assert read_tool_transforms(message) == ()


def test_read_drops_entries_without_a_string_kind():
    message = ToolMessage(
        content="x",
        tool_call_id="1",
        additional_kwargs={TOOL_TRANSFORMS_KEY: [{"kind": "ok", "by": "m"}, {"by": "m"}, "junk"]},
    )
    assert read_tool_transforms(message) == ({"kind": "ok", "by": "m"},)


def test_mcp_source_projection_is_credential_free_and_defaults_transport():
    from langchain_core.tools import tool as make_tool

    from deerflow.tools.mcp_metadata import get_mcp_source, tag_mcp_tool

    @make_tool
    def probe(x: str) -> str:
        """probe"""
        return x

    tag_mcp_tool(probe, server_name="files", transport=None)
    assert get_mcp_source(probe) == {"server_name": "files", "transport": "unknown"}


def test_gateway_treats_the_transform_trail_as_server_owned():
    """A caller must not be able to forge a transform trail on an inbound message."""
    from app.gateway.services import _SERVER_OWNED_MESSAGE_METADATA_KEYS

    assert TOOL_TRANSFORMS_KEY in _SERVER_OWNED_MESSAGE_METADATA_KEYS


def test_mcp_source_is_absent_when_no_server_name_is_supplied():
    from langchain_core.tools import tool as make_tool

    from deerflow.tools.mcp_metadata import get_mcp_source, tag_mcp_tool

    @make_tool
    def probe(x: str) -> str:
        """probe"""
        return x

    tag_mcp_tool(probe)
    assert get_mcp_source(probe) is None
