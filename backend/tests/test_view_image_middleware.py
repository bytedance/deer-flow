"""Unit tests for ViewImageMiddleware.

Tests cover the middleware's ability to inject image details (including base64
payloads) as a HumanMessage before the next LLM call, triggered only when the
previous assistant turn contained `view_image` tool calls that have all been
completed with corresponding ToolMessages.

Covered behavior:
- `_get_last_assistant_message` returns the most recent AIMessage (or None).
- `_has_view_image_tool` only matches assistant messages with `view_image` tool calls.
- `_all_tools_completed` verifies every tool call id has a matching ToolMessage.
- `_create_image_details_message` produces correctly structured content blocks,
  reading image files on-demand from disk (no base64 stored in state).
- `_should_inject_image_message` gates injection on all preconditions, including
  deduplication when an image-details message was already added.
- `_inject_image_message` returns a state update with a HumanMessage, or None
  when injection is not warranted.
- `before_model` and `abefore_model` expose the same behavior sync/async.
- `after_model` and `aafter_model` remove only the transient image message so
  later checkpoints do not retain its base64 payload.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain.agents import create_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langgraph.graph.message import add_messages

from deerflow.agents.middlewares.view_image_middleware import (
    _IMAGE_CONTEXT_MESSAGE_MARKER_KEY,
    ViewImageMiddleware,
)


def _view_image_call(call_id: str = "call_1", path: str = "/mnt/user-data/uploads/img.png") -> dict:
    return {"name": "view_image", "id": call_id, "args": {"image_path": path}}


def _other_tool_call(call_id: str = "call_other", name: str = "bash") -> dict:
    return {"name": name, "id": call_id, "args": {"command": "ls"}}


def _runtime() -> MagicMock:
    """Minimal Runtime stub. The middleware doesn't use it today, but the
    interface requires it."""
    return MagicMock()


class _CaptureChatMessages(BaseCallbackHandler):
    def __init__(self):
        self.messages = []

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self.messages = messages[0]


def _make_viewed_image(tmp_path, filename="img.png", mime_type="image/png", data=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"):
    """Create a real image file and return viewed_images metadata dict."""
    img_path = tmp_path / filename
    img_path.write_bytes(data)
    return {
        "mime_type": mime_type,
        "size": len(data),
        "actual_path": str(img_path),
    }


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

    def test_builds_blocks_for_single_image(self, tmp_path):
        mw = ViewImageMiddleware()
        img_meta = _make_viewed_image(tmp_path, "cat.png")
        state = {
            "viewed_images": {
                "/path/to/cat.png": img_meta,
            }
        }
        blocks = mw._create_image_details_message(state)

        # header text + per-image description text + per-image image_url block
        assert len(blocks) == 3
        assert blocks[0] == {"type": "text", "text": "Here are the images you've viewed:"}
        assert blocks[1]["type"] == "text"
        assert "/path/to/cat.png" in blocks[1]["text"]
        assert "image/png" in blocks[1]["text"]
        assert blocks[2]["type"] == "image_url"
        assert blocks[2]["image_url"]["url"].startswith("data:image/png;base64,")

    def test_builds_blocks_for_multiple_images(self, tmp_path):
        mw = ViewImageMiddleware()
        img1 = _make_viewed_image(tmp_path, "a.png", data=b"\x89PNG\r\n\x1a\nfake-png")
        img2 = _make_viewed_image(tmp_path, "b.jpg", mime_type="image/jpeg", data=b"\xff\xd8\xff\xe0fake-jpeg")
        state = {
            "viewed_images": {
                "/a.png": img1,
                "/b.jpg": img2,
            }
        }
        blocks = mw._create_image_details_message(state)

        # 1 header + (1 description + 1 image_url) per image = 5 blocks
        assert len(blocks) == 5
        image_url_blocks = [b for b in blocks if isinstance(b, dict) and b.get("type") == "image_url"]
        assert len(image_url_blocks) == 2
        urls = {b["image_url"]["url"] for b in image_url_blocks}
        assert any(u.startswith("data:image/png;base64,") for u in urls)
        assert any(u.startswith("data:image/jpeg;base64,") for u in urls)

    def test_omits_image_url_block_when_file_missing(self, tmp_path):
        mw = ViewImageMiddleware()
        state = {
            "viewed_images": {
                "/broken.png": {
                    "mime_type": "image/png",
                    "size": 0,
                    "actual_path": str(tmp_path / "nonexistent.png"),
                },
            }
        }
        blocks = mw._create_image_details_message(state)
        # header + description + error text (file no longer available)
        assert len(blocks) == 3
        assert all(not (isinstance(b, dict) and b.get("type") == "image_url") for b in blocks)

    def test_uses_unknown_mime_type_when_missing(self, tmp_path):
        mw = ViewImageMiddleware()
        img_meta = _make_viewed_image(tmp_path, "mystery.bin", mime_type="unknown")
        state = {
            "viewed_images": {
                "/mystery.bin": img_meta,
            }
        }
        blocks = mw._create_image_details_message(state)
        # The description block should mention unknown
        description_blocks = [b for b in blocks if b.get("type") == "text" and "/mystery.bin" in b.get("text", "")]
        assert len(description_blocks) == 1
        assert "unknown" in description_blocks[0]["text"]

    def test_omits_image_url_when_read_raises_oserror(self, tmp_path, monkeypatch):
        """A failure during on-demand read must not crash the middleware."""
        img_meta = _make_viewed_image(tmp_path, "ok.png")
        state = {
            "viewed_images": {
                "/ok.png": img_meta,
            }
        }

        def _raise(*args, **kwargs):
            raise OSError("disk error")

        monkeypatch.setattr("builtins.open", _raise)

        mw = ViewImageMiddleware()
        blocks = mw._create_image_details_message(state)
        # header + description + 'unavailable' text, no image_url block
        assert all(not (isinstance(b, dict) and b.get("type") == "image_url") for b in blocks)
        unavailable = [b for b in blocks if isinstance(b, dict) and b.get("type") == "text" and "unavailable" in b.get("text", "")]
        assert len(unavailable) == 1

    def test_omits_image_url_when_size_changes_between_view_and_inject(self, tmp_path):
        """Defense against TOCTOU growth: skip if current size differs from recorded size."""
        img_meta = _make_viewed_image(tmp_path, "shrinking.png", data=b"original-larger-content")
        # Grow the file after the metadata was written
        img_meta_path = Path(img_meta["actual_path"])
        img_meta_path.write_bytes(b"much-much-much-larger-content-bytes")

        state = {"viewed_images": {"/shrinking.png": img_meta}}
        mw = ViewImageMiddleware()
        blocks = mw._create_image_details_message(state)
        assert all(not (isinstance(b, dict) and b.get("type") == "image_url") for b in blocks)

    def test_omits_image_url_when_size_exceeds_cap(self, tmp_path):
        """Records a small size but the actual file is large - the cap kicks in regardless."""
        img_meta = _make_viewed_image(tmp_path, "huge.png", data=b"x" * 100)
        img_meta_path = Path(img_meta["actual_path"])
        # Grow past the cap (20 MB)
        img_meta_path.write_bytes(b"y" * (21 * 1024 * 1024))

        state = {"viewed_images": {"/huge.png": img_meta}}
        mw = ViewImageMiddleware()
        blocks = mw._create_image_details_message(state)
        assert all(not (isinstance(b, dict) and b.get("type") == "image_url") for b in blocks)


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

    def test_true_when_all_preconditions_met(self, tmp_path):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        img_meta = _make_viewed_image(tmp_path)
        state = {
            "messages": [assistant, ToolMessage(content="ok", tool_call_id="c1")],
            "viewed_images": {"/img.png": img_meta},
        }
        assert mw._should_inject_image_message(state) is True

    def test_false_when_already_injected(self, tmp_path):
        """If a HumanMessage with the recognized header is already present after
        the assistant turn, we must not inject a duplicate."""
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        already_injected = HumanMessage(content="Here are the images you've viewed: /img.png")
        img_meta = _make_viewed_image(tmp_path)
        state = {
            "messages": [
                assistant,
                ToolMessage(content="ok", tool_call_id="c1"),
                already_injected,
            ],
            "viewed_images": {"/img.png": img_meta},
        }
        assert mw._should_inject_image_message(state) is False

    def test_false_when_already_injected_with_list_content(self, tmp_path):
        """Deduplication must recognize the real injected payload shape.

        The middleware's own `_inject_image_message` creates a HumanMessage
        whose `.content` is a *list* of dicts (text + image_url blocks), not a
        plain string. This test reuses `_create_image_details_message` output
        to reproduce the realistic shape and confirms `_should_inject_image_message`
        still detects the marker via `str(msg.content)`.
        """
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        img_meta = _make_viewed_image(tmp_path)
        viewed_images = {"/img.png": img_meta}
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

    def test_false_when_legacy_details_marker_present(self, tmp_path):
        """The middleware also recognizes the legacy 'Here are the details of the
        images you've viewed' marker as an already-injected signal."""
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        legacy = HumanMessage(content="Here are the details of the images you've viewed: ...")
        img_meta = _make_viewed_image(tmp_path)
        state = {
            "messages": [
                assistant,
                ToolMessage(content="ok", tool_call_id="c1"),
                legacy,
            ],
            "viewed_images": {"/img.png": img_meta},
        }
        assert mw._should_inject_image_message(state) is False


class TestInjectImageMessage:
    def test_returns_none_when_should_not_inject(self):
        mw = ViewImageMiddleware()
        state = {"messages": []}
        assert mw._inject_image_message(state) is None

    def test_returns_state_update_with_human_message(self, tmp_path):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        img_meta = _make_viewed_image(tmp_path)
        state = {
            "messages": [assistant, ToolMessage(content="ok", tool_call_id="c1")],
            "viewed_images": {"/img.png": img_meta},
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
        # Internal injection: must be hidden from the chat UI (and IM channels),
        # like the other middleware-injected context messages.
        assert injected.additional_kwargs.get("hide_from_ui") is True
        assert injected.additional_kwargs.get(_IMAGE_CONTEXT_MESSAGE_MARKER_KEY) is True
        assert injected.id is not None
        assert injected.id.startswith("view-image-context:")


class TestBeforeModel:
    def test_before_model_returns_none_when_preconditions_not_met(self):
        mw = ViewImageMiddleware()
        state = {"messages": [HumanMessage(content="hi")]}
        assert mw.before_model(state, _runtime()) is None

    def test_before_model_returns_injection_when_ready(self, tmp_path):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        img_meta = _make_viewed_image(tmp_path)
        state = {
            "messages": [assistant, ToolMessage(content="ok", tool_call_id="c1")],
            "viewed_images": {"/img.png": img_meta},
        }
        result = mw.before_model(state, _runtime())
        assert result is not None
        assert isinstance(result["messages"][0], HumanMessage)

    @pytest.mark.anyio
    async def test_abefore_model_matches_sync_behavior(self, tmp_path):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        img_meta = _make_viewed_image(tmp_path)
        state = {
            "messages": [assistant, ToolMessage(content="ok", tool_call_id="c1")],
            "viewed_images": {"/img.png": img_meta},
        }
        result = await mw.abefore_model(state, _runtime())
        assert result is not None
        assert isinstance(result["messages"][0], HumanMessage)

    @pytest.mark.anyio
    async def test_abefore_model_returns_none_when_no_injection(self):
        mw = ViewImageMiddleware()
        state = {"messages": []}
        assert await mw.abefore_model(state, _runtime()) is None


class TestAfterModel:
    def test_graph_exposes_image_context_only_during_model_call(self, tmp_path):
        capture = _CaptureChatMessages()
        model = FakeMessagesListChatModel(
            responses=[AIMessage(content="I can see the image.")],
            callbacks=[capture],
        )
        graph = create_agent(model=model, tools=[], middleware=[ViewImageMiddleware()])
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        img_meta = _make_viewed_image(tmp_path)

        result = graph.invoke(
            {
                "messages": [assistant, ToolMessage(content="ok", tool_call_id="c1")],
                "viewed_images": {"/img.png": img_meta},
            }
        )

        model_image_messages = [message for message in capture.messages if isinstance(message, HumanMessage) and message.id and message.id.startswith("view-image-context:")]
        assert len(model_image_messages) == 1
        assert any(block.get("type") == "image_url" for block in model_image_messages[0].content)
        assert all(not (isinstance(message, HumanMessage) and message.id and message.id.startswith("view-image-context:")) for message in result["messages"])

    def test_removes_transient_image_message_from_later_state(self, tmp_path):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        tool_result = ToolMessage(content="ok", tool_call_id="c1")
        img_meta = _make_viewed_image(tmp_path)
        before_state = {
            "messages": [assistant, tool_result],
            "viewed_images": {"/img.png": img_meta},
        }
        injected = mw.before_model(before_state, _runtime())["messages"][0]
        model_response = AIMessage(content="I can see the image.")
        model_state = {
            **before_state,
            "messages": [assistant, tool_result, injected, model_response],
        }

        result = mw.after_model(model_state, _runtime())

        assert result is not None
        assert len(result["messages"]) == 1
        removal = result["messages"][0]
        assert isinstance(removal, RemoveMessage)
        assert removal.id == injected.id

        checkpoint_messages = add_messages(model_state["messages"], result["messages"])
        assert injected.id not in {message.id for message in checkpoint_messages}
        assert model_response in checkpoint_messages

    def test_does_not_remove_unmarked_human_messages(self):
        mw = ViewImageMiddleware()
        state = {
            "messages": [
                HumanMessage(
                    id="view-image-context:client-supplied",
                    content="Here are the images you've viewed: user-authored text",
                    additional_kwargs={"hide_from_ui": True},
                ),
                AIMessage(content="response"),
            ]
        }

        assert mw.after_model(state, _runtime()) is None

    def test_graph_preserves_normalized_client_message_with_reserved_prefix(self, tmp_path):
        from app.gateway.services import normalize_input

        client_id = "view-image-context:client-supplied"
        normalized = normalize_input(
            {
                "messages": [
                    {
                        "role": "user",
                        "id": client_id,
                        "content": "client-authored message",
                        "additional_kwargs": {
                            _IMAGE_CONTEXT_MESSAGE_MARKER_KEY: True,
                            "custom": "keep-me",
                        },
                    }
                ]
            }
        )
        client_message = normalized["messages"][0]
        assert _IMAGE_CONTEXT_MESSAGE_MARKER_KEY not in client_message.additional_kwargs

        capture = _CaptureChatMessages()
        model = FakeMessagesListChatModel(
            responses=[AIMessage(content="I can see the image.")],
            callbacks=[capture],
        )
        graph = create_agent(model=model, tools=[], middleware=[ViewImageMiddleware()])
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])

        result = graph.invoke(
            {
                "messages": [
                    client_message,
                    assistant,
                    ToolMessage(content="ok", tool_call_id="c1"),
                ],
                "viewed_images": {"/img.png": _make_viewed_image(tmp_path)},
            }
        )

        assert any(message.id == client_id for message in capture.messages)
        assert any(isinstance(message, HumanMessage) and message.id != client_id and message.additional_kwargs.get(_IMAGE_CONTEXT_MESSAGE_MARKER_KEY) is True for message in capture.messages)
        persisted_client = next(message for message in result["messages"] if message.id == client_id)
        assert persisted_client.content == "client-authored message"
        assert persisted_client.additional_kwargs == {"custom": "keep-me"}
        assert all(message.additional_kwargs.get(_IMAGE_CONTEXT_MESSAGE_MARKER_KEY) is not True for message in result["messages"] if isinstance(message, HumanMessage))

    @pytest.mark.anyio
    async def test_aafter_model_matches_sync_cleanup(self, tmp_path):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        tool_result = ToolMessage(content="ok", tool_call_id="c1")
        img_meta = _make_viewed_image(tmp_path)
        before_state = {
            "messages": [assistant, tool_result],
            "viewed_images": {"/img.png": img_meta},
        }
        injected = (await mw.abefore_model(before_state, _runtime()))["messages"][0]
        model_state = {
            **before_state,
            "messages": [assistant, tool_result, injected, AIMessage(content="response")],
        }

        result = await mw.aafter_model(model_state, _runtime())

        assert result is not None
        assert isinstance(result["messages"][0], RemoveMessage)
        assert result["messages"][0].id == injected.id
