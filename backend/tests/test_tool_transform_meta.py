"""Declared transform trail for tool results.

Middlewares between the raw callable and the model-visible result append an
entry, so a consumer classifies raw -> visible transforms from facts instead of
sniffing output wording.
"""

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.messages.content import create_text_block

from deerflow.agents.middlewares.tool_transform_meta import (
    TOOL_TRANSFORMS_KEY,
    append_tool_transform,
    read_tool_transforms,
    tool_content_fingerprint,
    tool_result_source_digest,
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


def test_source_digest_comes_from_the_first_replacement():
    kwargs: dict = {}
    append_tool_transform(kwargs, "sanitized", by="ToolResultSanitizationMiddleware")
    append_tool_transform(kwargs, "externalized", by="ToolOutputBudgetMiddleware", source_sha256="a" * 64)
    append_tool_transform(kwargs, "truncated", by="ToolOutputBudgetMiddleware", source_sha256="b" * 64)
    assert "source_sha256" not in kwargs[TOOL_TRANSFORMS_KEY][0]
    assert tool_result_source_digest(ToolMessage(content="preview", tool_call_id="1", additional_kwargs=kwargs)) == "a" * 64


@pytest.mark.parametrize("digest", [None, "", "a" * 63, "g" * 64, 123, ["a" * 64]])
def test_source_digest_ignores_malformed_persisted_values(digest):
    trail = [{"kind": "externalized", "by": "ToolOutputBudgetMiddleware", "source_sha256": digest}]
    message = ToolMessage(content="preview", tool_call_id="1", additional_kwargs={TOOL_TRANSFORMS_KEY: trail})
    assert tool_result_source_digest(message) is None


def test_content_fingerprint_ignores_block_ids_but_not_data():
    first, second = ([create_text_block("page")] for _ in range(2))
    assert first[0]["id"] != second[0]["id"]
    assert tool_content_fingerprint(first) == tool_content_fingerprint(second)
    assert tool_content_fingerprint([create_text_block("other page")]) != tool_content_fingerprint(first)
    assert tool_content_fingerprint("page") != tool_content_fingerprint("other page")
    # Outside a standard content block an id can be the data that changed.
    assert tool_content_fingerprint([{"id": "row-1", "status": "pending"}]) != tool_content_fingerprint([{"id": "row-2", "status": "pending"}])
    assert tool_content_fingerprint([{"type": ["text"], "id": "a"}]) != tool_content_fingerprint([{"type": ["text"], "id": "b"}])


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
