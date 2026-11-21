"""An MCP error result without text blocks reports shapes, not base64 payloads.

The tool error a model sees is built from the result's text blocks. Before this
case was handled, an error result carrying only images or files fell back to
stringifying the LangChain content blocks, putting the whole base64 payload into
the ToolException message; the middleware's 500-character cap still left a
base64 prefix in the model-visible ToolMessage and the checkpoint. The MCP guide
forbids that.
"""

import base64

import pytest
from langchain_core.tools import ToolException
from mcp.types import BlobResourceContents, CallToolResult, EmbeddedResource, ImageContent, TextContent

from deerflow.mcp.tools import _convert_call_tool_result

PAYLOAD = base64.b64encode(b"\x89PNG\r\n\x1a\nbinary image payload").decode("ascii")


def _image() -> ImageContent:
    return ImageContent(type="image", data=PAYLOAD, mimeType="image/png")


def _file(mime_type: str | None) -> EmbeddedResource:
    return EmbeddedResource(
        type="resource",
        resource=BlobResourceContents(uri="file:///tmp/report.pdf", blob=PAYLOAD, mimeType=mime_type),
    )


def test_image_only_error_result_keeps_the_payload_out_of_the_message():
    with pytest.raises(ToolException) as excinfo:
        _convert_call_tool_result(CallToolResult(content=[_image()], isError=True))

    message = str(excinfo.value)
    assert PAYLOAD not in message
    assert "without text content" in message
    assert "image (image/png)" in message


def test_file_only_error_result_names_its_mime_type_without_the_payload():
    with pytest.raises(ToolException) as excinfo:
        _convert_call_tool_result(CallToolResult(content=[_file("application/pdf")], isError=True))

    message = str(excinfo.value)
    assert PAYLOAD not in message
    assert "file (application/pdf)" in message


def test_error_result_with_no_content_reports_that_no_text_was_sent():
    with pytest.raises(ToolException) as excinfo:
        _convert_call_tool_result(CallToolResult(content=[], isError=True))

    assert str(excinfo.value) == "MCP tool returned an error result without text content."


def test_error_result_text_blocks_are_reported_unchanged():
    with pytest.raises(ToolException) as excinfo:
        _convert_call_tool_result(
            CallToolResult(
                content=[TextContent(type="text", text="server refused: bad token"), _image()],
                isError=True,
            )
        )

    message = str(excinfo.value)
    assert message == "server refused: bad token"
    assert PAYLOAD not in message


def _empty_file(mime_type: str | None = "application/pdf") -> EmbeddedResource:
    return EmbeddedResource(
        type="resource",
        resource=BlobResourceContents(uri="file:///tmp/empty.pdf", blob="", mimeType=mime_type),
    )


def test_zero_byte_file_error_result_keeps_the_server_diagnostic():
    with pytest.raises(ToolException) as excinfo:
        _convert_call_tool_result(
            CallToolResult(
                content=[_empty_file(), TextContent(type="text", text="upload rejected: empty file")],
                isError=True,
            )
        )

    assert str(excinfo.value) == "upload rejected: empty file"


def test_zero_byte_file_only_error_result_names_its_shape():
    with pytest.raises(ToolException) as excinfo:
        _convert_call_tool_result(CallToolResult(content=[_empty_file()], isError=True))

    message = str(excinfo.value)
    assert "without text content" in message
    assert "file (application/pdf)" in message


def test_zero_byte_image_error_result_names_its_shape():
    empty_image = ImageContent(type="image", data="", mimeType="image/png")
    with pytest.raises(ToolException) as excinfo:
        _convert_call_tool_result(CallToolResult(content=[empty_image], isError=True))

    message = str(excinfo.value)
    assert "without text content" in message
    assert "image (image/png)" in message
