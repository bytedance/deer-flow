"""Tests for ModelContentCompatibilityMiddleware (read-time sanitizer).

The MCP conversion layer used to persist URL-sourced ``file`` content blocks
(e.g. a ResourceLink with a ``ui://`` URI) into checkpointed ToolMessages. Under
the Chat Completions API every subsequent model call in such a thread fails at
client-side serialization — langchain-core's OpenAI translator raises
``ValueError: OpenAI Chat Completions does not support file URLs.`` for ANY
``file`` block carrying a ``url`` — and the error-handling middleware answers
every later turn with a non-retriable fallback. The thread is bricked.

This middleware heals those threads at read time: just before a request reaches
the model adapter it rewrites, in the request view only (state and checkpoints
are never touched),

- any ``{"type": "file", "url": ...}`` block in list-form message content into
  a plain text placeholder
  ``[Resource ({mime or "unknown type"}) available at {url}]``;
- any ``{"type": "image", "url": ...}`` block whose URL scheme is not
  fetchable by the provider (not ``http``/``https``/``data``) into the same
  placeholder.

The rules apply to every message role: imported or cross-client history can
carry URL file blocks on HumanMessage/AIMessage too, and such a block is
unserializable regardless of the role carrying it. Everything else — fetchable
image URLs, embedded base64 payloads, text blocks, and string content — passes
through untouched, in order, and a second application is a no-op.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from deerflow.agents.middlewares.model_content_compatibility_middleware import (
    ModelContentCompatibilityMiddleware,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _model_request(messages: list[AnyMessage]) -> ModelRequest:
    """Build a real ModelRequest so `.override()` behaves as it does in the graph."""
    return ModelRequest(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="ok")]),
        messages=list(messages),
        system_message=None,
        tool_choice=None,
        tools=[],
        response_format=None,
        state={"messages": list(messages)},
        runtime=MagicMock(),
        model_settings={},
    )


def _tool_message(content, tool_call_id: str = "call_1") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=tool_call_id, name="some_tool")


def _run_sync(middleware: ModelContentCompatibilityMiddleware, request: ModelRequest) -> ModelRequest:
    """Run wrap_model_call with a capturing handler; return the request the model would see."""
    seen: list[ModelRequest] = []
    middleware.wrap_model_call(request, lambda prepared: seen.append(prepared) or AIMessage(content="ok"))
    assert len(seen) == 1
    return seen[0]


async def _run_async(middleware: ModelContentCompatibilityMiddleware, request: ModelRequest) -> ModelRequest:
    """Run awrap_model_call with a capturing handler; return the request the model would see."""
    seen: list[ModelRequest] = []

    async def handler(prepared: ModelRequest) -> AIMessage:
        seen.append(prepared)
        return AIMessage(content="ok")

    await middleware.awrap_model_call(request, handler)
    assert len(seen) == 1
    return seen[0]


def _url_file_block(url: str, mime_type: str | None = None) -> dict:
    """The legacy persisted shape: create_file_block(url=..., mime_type=...)."""
    block = {"type": "file", "id": "lc_legacy", "url": url}
    if mime_type is not None:
        block["mime_type"] = mime_type
    return block


class TestUrlFileBlocksBecomeTextPlaceholders:
    def test_ui_scheme_file_block_becomes_text_placeholder(self):
        """The incident regression: an MCP App ``ui://`` card must not reach the model as a file block."""
        message = _tool_message([_url_file_block("ui://weather-app/card", "text/html;profile=mcp-app")])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == [{"type": "text", "text": "[Resource (text/html;profile=mcp-app) available at ui://weather-app/card]"}]

    def test_remote_https_file_block_becomes_text_placeholder(self):
        message = _tool_message([_url_file_block("https://example.com/report.pdf", "application/pdf")])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == [{"type": "text", "text": "[Resource (application/pdf) available at https://example.com/report.pdf]"}]

    def test_local_virtual_path_file_block_becomes_text_placeholder(self):
        message = _tool_message([_url_file_block("/mnt/user-data/outputs/notes.txt", "text/plain")])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == [{"type": "text", "text": "[Resource (text/plain) available at /mnt/user-data/outputs/notes.txt]"}]

    def test_file_block_without_mime_type_uses_unknown_type(self):
        message = _tool_message([_url_file_block("https://example.com/mystery.bin")])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == [{"type": "text", "text": "[Resource (unknown type) available at https://example.com/mystery.bin]"}]

    def test_no_chat_completions_rejected_block_remains(self):
        """Pin the exact incident condition: no ``file`` block carrying a ``url`` survives."""
        message = _tool_message(
            [
                _url_file_block("ui://weather-app/card", "text/html;profile=mcp-app"),
                _url_file_block("https://example.com/report.pdf", "application/pdf"),
                {"type": "text", "text": "done"},
            ]
        )
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        content = prepared.messages[0].content
        assert isinstance(content, list)
        assert not any(isinstance(block, dict) and block.get("type") == "file" and "url" in block for block in content)

    def test_file_block_with_empty_string_url_is_rewritten(self):
        """langchain-core raises on ANY ``file`` block carrying a ``url`` key — an
        empty string included — so key presence, not truthiness, must drive the
        rewrite. With no usable location the placeholder drops the suffix."""
        message = _tool_message([{"type": "file", "url": "", "mime_type": "application/pdf"}])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == [{"type": "text", "text": "[Resource (application/pdf)]"}]

    def test_file_block_with_none_url_is_rewritten(self):
        message = _tool_message([{"type": "file", "url": None, "mime_type": "image/png"}])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == [{"type": "text", "text": "[Resource (image/png)]"}]


class TestImageBlockSchemeGating:
    def test_image_block_with_non_fetchable_scheme_is_downgraded(self):
        message = _tool_message([{"type": "image", "url": "ui://weather-app/chart", "mime_type": "image/png"}])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == [{"type": "text", "text": "[Resource (image/png) available at ui://weather-app/chart]"}]

    def test_local_virtual_path_image_block_is_downgraded(self):
        """Local images have no scheme; the model must use the view_image tool instead."""
        message = _tool_message([{"type": "image", "url": "/mnt/user-data/outputs/chart.png", "mime_type": "image/png"}])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == [{"type": "text", "text": "[Resource (image/png) available at /mnt/user-data/outputs/chart.png]"}]

    def test_http_and_https_image_blocks_pass_through(self):
        blocks = [
            {"type": "image", "url": "http://example.com/a.png", "mime_type": "image/png"},
            {"type": "image", "url": "https://example.com/b.png", "mime_type": "image/png"},
        ]
        message = _tool_message(blocks)
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == blocks

    def test_data_scheme_image_block_passes_through(self):
        blocks = [{"type": "image", "url": "data:image/png;base64,iVBORw0KGgo=", "mime_type": "image/png"}]
        message = _tool_message(blocks)
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == blocks

    def test_file_scheme_image_block_omits_host_path(self):
        """A ``file://`` image URL is downgraded like any other non-fetchable
        scheme, but the host path is withheld from model-visible text (US-16)."""
        message = _tool_message([{"type": "image", "url": "file:///Users/ops/deploy-internal/chart.png", "mime_type": "image/png"}])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == [{"type": "text", "text": "[Resource (image/png)]"}]
        assert "file://" not in prepared.messages[0].content[0]["text"]

    def test_malformed_image_url_is_downgraded_without_raising(self):
        """urlparse raises ValueError on structurally invalid URLs (a bad IPv6
        literal here); the sanitizer must downgrade the block instead of
        raising on every model call for the thread it is meant to heal."""
        message = _tool_message([{"type": "image", "url": "http://[::1", "mime_type": "image/png"}])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == [{"type": "text", "text": "[Resource (image/png)]"}]


class TestLocationSuppression:
    """The placeholder's location segment goes through the shared
    ``model_visible_location`` gate, matching the conversion layer: host paths
    and inline ``data:`` payloads that pre-fix blocks carried must never reach
    model-visible text — the healing path serves exactly those checkpoints."""

    def test_data_uri_file_block_payload_never_enters_placeholder(self):
        """A pre-fix block could carry a whole inline base64 payload as the
        ``data:`` file URL. The rewrite must heal the block without inlining
        kilobytes (or megabytes) of base64 into the prompt."""
        payload = "QUFB" + "A" * 5000
        message = _tool_message([_url_file_block(f"data:application/pdf;base64,{payload}", "application/pdf")])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == [{"type": "text", "text": "[Resource (application/pdf)]"}]
        assert all(payload not in str(block) for block in prepared.messages[0].content)

    def test_blob_uri_file_block_omits_location(self):
        message = _tool_message([_url_file_block("blob:https://example.com/550e8400-e29b-41d4-a716-446655440000", "application/pdf")])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == [{"type": "text", "text": "[Resource (application/pdf)]"}]

    def test_file_scheme_url_is_withheld_from_placeholder(self):
        """Pre-fix checkpoints hold unresolved ``file://`` links (resources
        outside the user-data tree); the host path must not reach the prompt."""
        message = _tool_message([_url_file_block("file:///Users/ops/deploy-internal/secret.pdf", "application/pdf")])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == [{"type": "text", "text": "[Resource (application/pdf)]"}]
        assert all("file://" not in block.get("text", "") for block in prepared.messages[0].content)

    def test_bare_host_path_url_is_withheld_from_placeholder(self):
        message = _tool_message([_url_file_block("/srv/deploy-internal/secret.pdf", "application/pdf")])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == [{"type": "text", "text": "[Resource (application/pdf)]"}]

    def test_windows_drive_path_url_is_withheld_from_placeholder(self):
        # urlparse reads the drive prefix as a single-letter scheme; the host
        # path must be suppressed all the same.
        message = _tool_message([_url_file_block("C:\\Users\\ops\\creds.txt", "text/plain")])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == [{"type": "text", "text": "[Resource (text/plain)]"}]
        assert all(":\\" not in block.get("text", "") for block in prepared.messages[0].content)

    def test_virtual_and_remote_locations_stay_visible(self):
        message = _tool_message(
            [
                _url_file_block("/mnt/user-data/outputs/notes.txt", "text/plain"),
                _url_file_block("https://example.com/report.pdf", "application/pdf"),
                _url_file_block("ui://weather-app/card", "text/html;profile=mcp-app"),
            ]
        )
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == [
            {"type": "text", "text": "[Resource (text/plain) available at /mnt/user-data/outputs/notes.txt]"},
            {"type": "text", "text": "[Resource (application/pdf) available at https://example.com/report.pdf]"},
            {"type": "text", "text": "[Resource (text/html;profile=mcp-app) available at ui://weather-app/card]"},
        ]


class TestPassthrough:
    def test_base64_blocks_pass_through(self):
        blocks = [
            {"type": "file", "base64": "aGVsbG8=", "mime_type": "text/plain"},
            {"type": "image", "base64": "aGVsbG8=", "mime_type": "image/png"},
        ]
        message = _tool_message(blocks)
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == blocks

    def test_text_blocks_and_bare_strings_pass_through(self):
        blocks = ["plain string", {"type": "text", "text": "hello"}]
        message = _tool_message(blocks)
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == blocks

    def test_string_tool_message_content_is_untouched(self):
        message = _tool_message("plain string result")
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == "plain string result"

    def test_human_message_base64_file_block_passes_through(self):
        """Uploads produce base64 blocks; a base64 file block on any role is valid and stays."""
        blocks = [{"type": "file", "base64": "aGVsbG8=", "mime_type": "application/pdf"}]
        human = HumanMessage(content=blocks)
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([human]))

        assert prepared.messages[0] is human

    def test_human_message_string_content_is_untouched(self):
        human = HumanMessage(content="plain user turn")
        request = _model_request([human])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), request)

        assert prepared is request


class TestRoleAgnosticRewriting:
    """Imported or cross-client history can carry URL file blocks on any role.

    The block is unserializable under Chat Completions regardless of who
    carries it, so the sanitizer rewrites every message with list-form
    content — not just checkpointed ToolMessages.
    """

    def test_human_message_url_file_block_is_rewritten(self):
        human = HumanMessage(content=[_url_file_block("https://example.com/upload.pdf", "application/pdf")])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([human]))

        assert prepared.messages[0].content == [{"type": "text", "text": "[Resource (application/pdf) available at https://example.com/upload.pdf]"}]
        # The rewrite is request-view-only: the input message keeps its block.
        assert human.content[0]["type"] == "file"

    def test_ai_message_url_file_block_is_rewritten(self):
        ai = AIMessage(content=[_url_file_block("ui://app/card", "text/html")])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([ai]))

        assert prepared.messages[0].content == [{"type": "text", "text": "[Resource (text/html) available at ui://app/card]"}]

    def test_nothing_to_rewrite_hands_the_same_request_through(self):
        message = _tool_message("plain string result")
        request = _model_request([message])
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), request)

        assert prepared is request


class TestOrderingIdempotenceAndState:
    def test_mixed_content_order_is_preserved(self):
        blocks = [
            {"type": "text", "text": "before"},
            _url_file_block("https://example.com/report.pdf", "application/pdf"),
            {"type": "image", "url": "https://example.com/keep.png", "mime_type": "image/png"},
            _url_file_block("ui://app/card", "text/html"),
            {"type": "text", "text": "after"},
        ]
        message = _tool_message(blocks)
        prepared = _run_sync(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == [
            {"type": "text", "text": "before"},
            {"type": "text", "text": "[Resource (application/pdf) available at https://example.com/report.pdf]"},
            {"type": "image", "url": "https://example.com/keep.png", "mime_type": "image/png"},
            {"type": "text", "text": "[Resource (text/html) available at ui://app/card]"},
            {"type": "text", "text": "after"},
        ]

    def test_repeated_application_is_a_noop(self):
        message = _tool_message([_url_file_block("ui://weather-app/card", "text/html;profile=mcp-app")])
        middleware = ModelContentCompatibilityMiddleware()

        once = _run_sync(middleware, _model_request([message]))
        twice = _run_sync(middleware, once)

        assert twice is once

    def test_input_messages_are_never_mutated(self):
        """The rewrite lives in the request view; the checkpointed message keeps its blocks."""
        original_block = _url_file_block("ui://weather-app/card", "text/html;profile=mcp-app")
        message = _tool_message([original_block])
        request = _model_request([message])

        prepared = _run_sync(ModelContentCompatibilityMiddleware(), request)

        # The prepared message is a copy; the original objects are untouched.
        assert prepared.messages[0] is not message
        assert message.content == [original_block]
        assert request.state["messages"][0].content == [original_block]


class TestChainWiring:
    """The sanitizer must be registered on every chain that replays checkpointed
    ToolMessages — a subagent thread holds MCP tool results too."""

    def test_registered_on_the_lead_agent_chain(self):
        from deerflow.agents.lead_agent.agent import build_middlewares
        from deerflow.config.app_config import AppConfig
        from deerflow.config.sandbox_config import SandboxConfig

        middlewares = build_middlewares(
            config={"configurable": {}},
            model_name=None,
            app_config=AppConfig(sandbox=SandboxConfig(use="test")),
        )
        assert ModelContentCompatibilityMiddleware in [type(m) for m in middlewares]

    def test_registered_on_the_subagent_runtime_chain(self):
        from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares
        from deerflow.config.app_config import AppConfig
        from deerflow.config.sandbox_config import SandboxConfig

        middlewares = build_subagent_runtime_middlewares(
            app_config=AppConfig(sandbox=SandboxConfig(use="test")),
        )
        assert ModelContentCompatibilityMiddleware in [type(m) for m in middlewares]

    def test_registered_on_the_sdk_factory_chain(self):
        from deerflow.agents.factory import _assemble_from_features
        from deerflow.agents.features import RuntimeFeatures

        middlewares, _ = _assemble_from_features(RuntimeFeatures())
        assert ModelContentCompatibilityMiddleware in [type(m) for m in middlewares]


class TestAsyncParity:
    async def test_awrap_model_call_rewrites_like_sync(self):
        message = _tool_message([_url_file_block("ui://weather-app/card", "text/html;profile=mcp-app")])
        prepared = await _run_async(ModelContentCompatibilityMiddleware(), _model_request([message]))

        assert prepared.messages[0].content == [{"type": "text", "text": "[Resource (text/html;profile=mcp-app) available at ui://weather-app/card]"}]

    async def test_awrap_model_call_without_rewrites_hands_the_same_request_through(self):
        message = _tool_message("plain string result")
        request = _model_request([message])
        prepared = await _run_async(ModelContentCompatibilityMiddleware(), request)

        assert prepared is request
