"""Unit tests for ViewImageMiddleware.

Tests cover the middleware's ability to inject image details (including base64
payloads) as a HumanMessage before the next LLM call, triggered only when the
previous assistant turn contained `view_image` tool calls that have all been
completed with corresponding ToolMessages.

Covered behavior:
- `_get_last_assistant_message` returns the most recent AIMessage (or None).
- `_has_view_image_tool` only matches assistant messages with `view_image` tool calls.
- `_all_tools_completed` verifies every tool call id has a matching ToolMessage.
- `_create_image_details_message` produces correctly structured content blocks.
- `_should_inject_image_message` gates injection on all preconditions, including
  deduplication when an image-details message was already added.
- `_inject_image_message` returns a state update with a HumanMessage, or None
  when injection is not warranted.
- `before_model` and `abefore_model` expose the same behavior sync/async.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware


def _view_image_call(call_id: str = "call_1", path: str = "/mnt/user-data/uploads/img.png") -> dict:
    return {"name": "view_image", "id": call_id, "args": {"image_path": path}}


def _other_tool_call(call_id: str = "call_other", name: str = "bash") -> dict:
    return {"name": name, "id": call_id, "args": {"command": "ls"}}


def _runtime() -> MagicMock:
    """Minimal Runtime stub. The middleware doesn't use it today, but the
    interface requires it."""
    return MagicMock()


class TestGetLastAssistantMessage:
    def test_returns_none_on_empty_list(self):
        mw = ViewImageMiddleware()
        assert mw._get_last_assistant_message([]) is None

    def test_returns_none_when_no_ai_message(self):
        mw = ViewImageMiddleware()
        messages = [
            SystemMessage(content="sys"),
            HumanMessage(content="hi"),
        ]
        assert mw._get_last_assistant_message(messages) is None

    def test_returns_most_recent_ai_message(self):
        mw = ViewImageMiddleware()
        older = AIMessage(content="older")
        newer = AIMessage(content="newer")
        messages = [HumanMessage(content="q"), older, HumanMessage(content="q2"), newer]
        assert mw._get_last_assistant_message(messages) is newer


class TestHasViewImageTool:
    def test_returns_false_when_tool_calls_attr_missing(self):
        """Exercise the `not hasattr(message, "tool_calls")` guard.

        AIMessage always has a `tool_calls` attribute, so we use a plain
        object that truly lacks the attribute to cover this branch.
        """
        mw = ViewImageMiddleware()
        msg = SimpleNamespace(content="just text")  # no tool_calls attribute
        assert not hasattr(msg, "tool_calls")  # precondition
        assert mw._has_view_image_tool(msg) is False

    def test_returns_false_when_ai_message_has_no_tool_calls(self):
        """AIMessage without tool_calls kwarg defaults to an empty list."""
        mw = ViewImageMiddleware()
        msg = AIMessage(content="just text")
        assert mw._has_view_image_tool(msg) is False

    def test_returns_false_when_tool_calls_empty(self):
        mw = ViewImageMiddleware()
        msg = AIMessage(content="", tool_calls=[])
        assert mw._has_view_image_tool(msg) is False

    def test_returns_true_when_view_image_present(self):
        mw = ViewImageMiddleware()
        msg = AIMessage(content="", tool_calls=[_view_image_call()])
        assert mw._has_view_image_tool(msg) is True

    def test_returns_true_when_view_image_mixed_with_others(self):
        mw = ViewImageMiddleware()
        msg = AIMessage(
            content="",
            tool_calls=[_other_tool_call(), _view_image_call(call_id="call_vi")],
        )
        assert mw._has_view_image_tool(msg) is True

    def test_returns_false_when_only_other_tools(self):
        mw = ViewImageMiddleware()
        msg = AIMessage(content="", tool_calls=[_other_tool_call()])
        assert mw._has_view_image_tool(msg) is False


class TestAllToolsCompleted:
    def test_returns_false_when_no_tool_calls(self):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[])
        assert mw._all_tools_completed([assistant], assistant) is False

    def test_returns_true_when_all_completed(self):
        mw = ViewImageMiddleware()
        assistant = AIMessage(
            content="",
            tool_calls=[_view_image_call("c1"), _view_image_call("c2", "/p2.png")],
        )
        messages = [
            assistant,
            ToolMessage(content="ok", tool_call_id="c1"),
            ToolMessage(content="ok", tool_call_id="c2"),
        ]
        assert mw._all_tools_completed(messages, assistant) is True

    def test_returns_false_when_some_tool_call_unanswered(self):
        mw = ViewImageMiddleware()
        assistant = AIMessage(
            content="",
            tool_calls=[_view_image_call("c1"), _view_image_call("c2", "/p2.png")],
        )
        messages = [assistant, ToolMessage(content="ok", tool_call_id="c1")]
        assert mw._all_tools_completed(messages, assistant) is False

    def test_returns_false_when_assistant_not_in_messages(self):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        # assistant is not part of the list, so messages.index() will raise and be caught
        messages = [HumanMessage(content="hi")]
        assert mw._all_tools_completed(messages, assistant) is False

    def test_ignores_tool_messages_before_assistant(self):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        # A stale ToolMessage with matching id appears BEFORE the assistant turn.
        # It should not count — only ToolMessages after the assistant close the call.
        messages = [
            ToolMessage(content="stale", tool_call_id="c1"),
            assistant,
        ]
        assert mw._all_tools_completed(messages, assistant) is False


class TestCreateImageDetailsMessage:
    def test_returns_placeholder_when_no_images(self):
        mw = ViewImageMiddleware()
        state = {"viewed_images": {}}
        blocks = mw._create_image_details_message(state)
        assert blocks == [{"type": "text", "text": "No images have been viewed."}]

    def test_returns_placeholder_when_state_missing_key(self):
        mw = ViewImageMiddleware()
        blocks = mw._create_image_details_message({})
        assert blocks == [{"type": "text", "text": "No images have been viewed."}]

    def test_builds_blocks_for_single_image(self):
        mw = ViewImageMiddleware()
        state = {
            "viewed_images": {
                "/path/to/cat.png": {"base64": "BASE64DATA", "mime_type": "image/png"},
            }
        }
        blocks = mw._create_image_details_message(state)

        # header text + per-image description text + per-image image_url block
        assert len(blocks) == 3
        assert blocks[0] == {"type": "text", "text": "Here are the images you've viewed:"}
        assert blocks[1]["type"] == "text"
        assert "/path/to/cat.png" in blocks[1]["text"]
        assert "image/png" in blocks[1]["text"]
        assert blocks[2] == {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,BASE64DATA"},
        }

    def test_builds_blocks_for_multiple_images(self):
        mw = ViewImageMiddleware()
        state = {
            "viewed_images": {
                "/a.png": {"base64": "AAA", "mime_type": "image/png"},
                "/b.jpg": {"base64": "BBB", "mime_type": "image/jpeg"},
            }
        }
        blocks = mw._create_image_details_message(state)

        # 1 header + (1 description + 1 image_url) per image = 5 blocks
        assert len(blocks) == 5
        image_url_blocks = [b for b in blocks if isinstance(b, dict) and b.get("type") == "image_url"]
        assert len(image_url_blocks) == 2
        urls = {b["image_url"]["url"] for b in image_url_blocks}
        assert "data:image/png;base64,AAA" in urls
        assert "data:image/jpeg;base64,BBB" in urls

    def test_omits_image_url_block_when_base64_missing(self):
        mw = ViewImageMiddleware()
        state = {
            "viewed_images": {
                "/broken.png": {"base64": "", "mime_type": "image/png"},
            }
        }
        blocks = mw._create_image_details_message(state)
        # header + description only (no image_url since base64 is empty)
        assert len(blocks) == 2
        assert all(not (isinstance(b, dict) and b.get("type") == "image_url") for b in blocks)

    def test_uses_unknown_mime_type_when_missing(self):
        mw = ViewImageMiddleware()
        state = {
            "viewed_images": {
                "/mystery.bin": {"base64": "XYZ"},  # no mime_type key
            }
        }
        blocks = mw._create_image_details_message(state)
        # The description block should mention unknown
        description_blocks = [b for b in blocks if b.get("type") == "text" and "/mystery.bin" in b.get("text", "")]
        assert len(description_blocks) == 1
        assert "unknown" in description_blocks[0]["text"]


class TestShouldInjectImageMessage:
    def test_false_when_no_messages(self):
        mw = ViewImageMiddleware()
        assert mw._should_inject_image_message({"messages": []}) is False

    def test_false_when_messages_key_missing(self):
        mw = ViewImageMiddleware()
        assert mw._should_inject_image_message({}) is False

    def test_false_when_no_assistant_message(self):
        mw = ViewImageMiddleware()
        state = {"messages": [HumanMessage(content="hello")]}
        assert mw._should_inject_image_message(state) is False

    def test_false_when_no_view_image_tool_call(self):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_other_tool_call()])
        state = {
            "messages": [assistant, ToolMessage(content="ok", tool_call_id="call_other")],
        }
        assert mw._should_inject_image_message(state) is False

    def test_false_when_tool_not_completed(self):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        state = {"messages": [assistant]}  # no ToolMessage yet
        assert mw._should_inject_image_message(state) is False

    def test_true_when_all_preconditions_met(self):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        state = {
            "messages": [assistant, ToolMessage(content="ok", tool_call_id="c1")],
            "viewed_images": {
                "/img.png": {"base64": "AAA", "mime_type": "image/png"},
            },
        }
        assert mw._should_inject_image_message(state) is True

    def test_false_when_already_injected(self):
        """If a HumanMessage with the recognized header is already present after
        the assistant turn, we must not inject a duplicate."""
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        already_injected = HumanMessage(content="Here are the images you've viewed: /img.png")
        state = {
            "messages": [
                assistant,
                ToolMessage(content="ok", tool_call_id="c1"),
                already_injected,
            ],
            "viewed_images": {
                "/img.png": {"base64": "AAA", "mime_type": "image/png"},
            },
        }
        assert mw._should_inject_image_message(state) is False

    def test_false_when_already_injected_with_list_content(self):
        """Deduplication must recognize the real injected payload shape.

        The middleware's own `_inject_image_message` creates a HumanMessage
        whose `.content` is a *list* of dicts (text + image_url blocks), not a
        plain string. This test reuses `_create_image_details_message` output
        to reproduce the realistic shape and confirms `_should_inject_image_message`
        still detects the marker via `str(msg.content)`.
        """
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        viewed_images = {"/img.png": {"base64": "AAA", "mime_type": "image/png"}}
        # Build content the same way the middleware would.
        real_injected_content = mw._create_image_details_message({"viewed_images": viewed_images})
        # Sanity: this is a list of blocks, not a plain string.
        assert isinstance(real_injected_content, list)
        already_injected = HumanMessage(content=real_injected_content)

        state = {
            "messages": [
                assistant,
                ToolMessage(content="ok", tool_call_id="c1"),
                already_injected,
            ],
            "viewed_images": viewed_images,
        }
        assert mw._should_inject_image_message(state) is False

    def test_false_when_legacy_details_marker_present(self):
        """The middleware also recognizes the legacy 'Here are the details of the
        images you've viewed' marker as an already-injected signal."""
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        legacy = HumanMessage(content="Here are the details of the images you've viewed: ...")
        state = {
            "messages": [
                assistant,
                ToolMessage(content="ok", tool_call_id="c1"),
                legacy,
            ],
            "viewed_images": {
                "/img.png": {"base64": "AAA", "mime_type": "image/png"},
            },
        }
        assert mw._should_inject_image_message(state) is False


class TestInjectImageMessage:
    def test_returns_none_when_should_not_inject(self):
        mw = ViewImageMiddleware()
        state = {"messages": []}
        assert mw._inject_image_message(state) is None

    def test_returns_state_update_with_human_message(self):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        state = {
            "messages": [assistant, ToolMessage(content="ok", tool_call_id="c1")],
            "viewed_images": {
                "/img.png": {"base64": "AAA", "mime_type": "image/png"},
            },
        }

        result = mw._inject_image_message(state)

        assert isinstance(result, dict)
        assert "messages" in result
        assert len(result["messages"]) == 1
        injected = result["messages"][0]
        assert isinstance(injected, HumanMessage)
        # Mixed-content payload: list of text + image_url blocks
        assert isinstance(injected.content, list)
        assert any(isinstance(b, dict) and b.get("type") == "image_url" for b in injected.content)


class TestBeforeModel:
    def test_before_model_returns_none_when_preconditions_not_met(self):
        mw = ViewImageMiddleware()
        state = {"messages": [HumanMessage(content="hi")]}
        assert mw.before_model(state, _runtime()) is None

    def test_before_model_returns_injection_when_ready(self):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        state = {
            "messages": [assistant, ToolMessage(content="ok", tool_call_id="c1")],
            "viewed_images": {
                "/img.png": {"base64": "AAA", "mime_type": "image/png"},
            },
        }
        result = mw.before_model(state, _runtime())
        assert result is not None
        assert isinstance(result["messages"][0], HumanMessage)

    @pytest.mark.anyio
    async def test_abefore_model_matches_sync_behavior(self):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        state = {
            "messages": [assistant, ToolMessage(content="ok", tool_call_id="c1")],
            "viewed_images": {
                "/img.png": {"base64": "AAA", "mime_type": "image/png"},
            },
        }
        result = await mw.abefore_model(state, _runtime())
        assert result is not None
        assert isinstance(result["messages"][0], HumanMessage)

    @pytest.mark.anyio
    async def test_abefore_model_returns_none_when_no_injection(self):
        mw = ViewImageMiddleware()
        state = {"messages": []}
        assert await mw.abefore_model(state, _runtime()) is None
