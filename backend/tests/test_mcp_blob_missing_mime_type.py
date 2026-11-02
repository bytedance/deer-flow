"""An MCP blob without a mimeType must degrade, not fail the whole tool call."""

import base64

from mcp.types import BlobResourceContents, CallToolResult, EmbeddedResource, TextContent

from deerflow.mcp.tools import _convert_call_tool_result

BLOB = base64.b64encode(b"binary payload").decode("ascii")


def _result(mime_type: str | None, *, with_text: bool = True) -> CallToolResult:
    content = [TextContent(type="text", text="here is your report")] if with_text else []
    content.append(
        EmbeddedResource(
            type="resource",
            resource=BlobResourceContents(uri="file:///tmp/report.bin", blob=BLOB, mimeType=mime_type),
        )
    )
    return CallToolResult(content=content, isError=False)


def test_blob_without_mime_type_degrades_to_octet_stream():
    lc_content, _artifact = _convert_call_tool_result(_result(None))

    assert [block["type"] for block in lc_content] == ["text", "file"]
    assert lc_content[0]["text"] == "here is your report"
    assert lc_content[1]["mime_type"] == "application/octet-stream"
    assert lc_content[1]["base64"] == BLOB


def test_text_blocks_survive_the_fallback():
    lc_content, _artifact = _convert_call_tool_result(_result(None, with_text=False))

    assert [block["type"] for block in lc_content] == ["file"]
    assert lc_content[0]["mime_type"] == "application/octet-stream"


def test_declared_non_image_mime_type_is_preserved():
    lc_content, _artifact = _convert_call_tool_result(_result("application/pdf"))

    assert lc_content[1]["type"] == "file"
    assert lc_content[1]["mime_type"] == "application/pdf"


def test_declared_image_mime_type_still_becomes_an_image_block():
    lc_content, _artifact = _convert_call_tool_result(_result("image/png"))

    assert [block["type"] for block in lc_content] == ["text", "image"]
    assert lc_content[1]["mime_type"] == "image/png"
