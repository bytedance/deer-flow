"""Unit tests for ViewImageMiddleware.

Tests cover the middleware's ability to inject image details (including base64
payloads) into the model request, triggered only when the previous assistant
turn contained `view_image` tool calls that have all been completed with
corresponding ToolMessages.

Covered behavior:
- `_get_last_assistant_message` returns the most recent AIMessage (or None).
- `_has_view_image_tool` only matches assistant messages with `view_image` tool calls.
- `_all_tools_completed` verifies every tool call id has a matching ToolMessage.
- `_create_image_details_message` produces correctly structured content blocks,
  reading image files on-demand from disk (no base64 stored in state).
- `_should_inject_image_message` gates injection on all preconditions, including
  deduplication when an image-details message is already in the request.
- `_inject` rebuilds the request's image context: it sweeps out any copy left
  in the message list by an interrupted run before deciding whether to append a
  freshly built one.
- `wrap_model_call` and `awrap_model_call` expose the same behavior sync/async,
  handing the payload to the model without ever writing it to state — so no
  checkpoint retains it, even if the run is interrupted mid-call.
"""

import base64
import hashlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware.types import ModelRequest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from PIL import Image
from support.symlinks import symlink_or_skip

from deerflow.agents.middlewares.view_image_middleware import (
    _IMAGE_CONTEXT_MESSAGE_MARKER_KEY,
    ViewImageMiddleware,
)
from deerflow.agents.thread_state import merge_viewed_images
from deerflow.config.paths import Paths
from deerflow.storage import BlobRef
from deerflow.tools.builtins.view_image_tool import view_image_tool


@pytest.fixture
def budget_image_runtime(tmp_path, monkeypatch):
    paths = Paths(tmp_path)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)
    monkeypatch.setattr("deerflow.storage.get_blob_store_if_enabled", lambda: None)
    outputs = paths.sandbox_outputs_dir("thread-test", user_id="user-test")
    outputs.mkdir(parents=True)
    payloads = {}
    for index in range(5):
        buffer = BytesIO()
        Image.new("RGB", (2, 2), (index * 40, 80, 160)).save(buffer, format="PNG")
        payloads[f"/mnt/user-data/outputs/{index}.png"] = buffer.getvalue()
        (outputs / f"{index}.png").write_bytes(buffer.getvalue())
    runtime = SimpleNamespace(
        state={"thread_data": {"outputs_path": str(outputs)}},
        context={"user_id": "user-test", "thread_id": "thread-test"},
        config={},
    )
    return runtime, payloads


def _view_budget_image(runtime, image_path, call_id):
    result = view_image_tool.func(runtime=runtime, image_path=image_path, tool_call_id=call_id)
    assert result.update["messages"][0].content == "Successfully read image"
    runtime.state["viewed_images"] = merge_viewed_images(runtime.state.get("viewed_images"), result.update["viewed_images"])
    request = _model_request([AIMessage(content="", tool_calls=[_view_image_call(call_id, image_path)]), *result.update["messages"]])
    return request.override(state={**runtime.state, "messages": request.messages}, runtime=runtime)


async def _capture_budget_request(request, use_async):
    seen = []

    def handler(prepared):
        seen.append(prepared)
        return AIMessage(content="ok")

    async def async_handler(prepared):
        return handler(prepared)

    middleware = ViewImageMiddleware()
    if use_async:
        await middleware.awrap_model_call(request, async_handler)
    else:
        middleware.wrap_model_call(request, handler)
    assert len(seen) == 1
    assert _image_context_messages(request.messages) == []
    assert _image_context_messages(request.state["messages"]) == []
    return _image_urls(seen[0])


@pytest.mark.anyio
@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("budget_delta", [0, -1], ids=["exact-fit", "one-byte-short"])
async def test_cumulative_image_bytes_reach_model_within_budget(budget_image_runtime, monkeypatch, use_async, budget_delta):
    from deerflow.agents.middlewares import view_image_middleware as module

    runtime, payloads = budget_image_runtime
    selected_paths = list(payloads)[:3]
    for index, path in enumerate(selected_paths):
        request = _view_budget_image(runtime, path, f"view-{index}")
    encoded = [base64.b64encode(payloads[path]).decode("ascii") for path in selected_paths]
    budget = len(encoded[1]) + len(encoded[2]) + budget_delta
    assert all(len(data) <= budget for data in encoded)
    # Add attributes on the unfixed baseline too: RED must be behavioral,
    # not an AttributeError caused by a missing budget constant.
    monkeypatch.setattr(module, "_MAX_CONTEXT_IMAGES", 4, raising=False)
    monkeypatch.setattr(module, "_MAX_CONTEXT_BASE64_BYTES", budget, raising=False)
    reads = []
    original_open = open

    def record_open(file, *args, **kwargs):
        if isinstance(file, (str, Path)) and Path(file).suffix == ".png":
            reads.append(Path(file).name)
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", record_open)
    urls = await _capture_budget_request(request, use_async)
    expected = selected_paths[1:] if budget_delta == 0 else selected_paths[2:]
    actual = [url.split(",", 1)[1] for url in urls]
    assert sum(len(data) for data in actual) <= budget
    assert [base64.b64decode(data) for data in actual] == [payloads[path] for path in expected]
    assert reads == [Path(path).name for path in reversed(expected)]


@pytest.mark.anyio
@pytest.mark.parametrize("use_async", [False, True])
async def test_revisited_image_returns_to_model_context(budget_image_runtime, use_async):
    runtime, payloads = budget_image_runtime
    paths = list(payloads)
    for index, path in enumerate(paths):
        request = _view_budget_image(runtime, path, f"initial-{index}")
    before = await _capture_budget_request(request, use_async)
    assert [base64.b64decode(url.split(",", 1)[1]) for url in before] == [payloads[path] for path in paths[1:]]
    saved = runtime.state["viewed_images"]
    request = _view_budget_image(runtime, paths[0], "revisit-oldest")
    after = await _capture_budget_request(request, use_async)
    assert [base64.b64decode(url.split(",", 1)[1]) for url in after] == [payloads[path] for path in [*paths[2:], paths[0]]]
    assert runtime.state["viewed_images"] == saved
    assert list(saved) == paths


def _view_image_call(call_id: str = "call_1", path: str = "/mnt/user-data/uploads/img.png") -> dict:
    return {"name": "view_image", "id": call_id, "args": {"image_path": path}}


def _other_tool_call(call_id: str = "call_other", name: str = "bash") -> dict:
    return {"name": name, "id": call_id, "args": {"command": "ls"}}


def _model_request(messages: list[AnyMessage], viewed_images: dict | None = None) -> ModelRequest:
    """Build a real ModelRequest so `.override()` behaves as it does in the graph."""
    return ModelRequest(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="ok")]),
        messages=list(messages),
        system_message=None,
        tool_choice=None,
        tools=[],
        response_format=None,
        state={"messages": list(messages), "viewed_images": viewed_images or {}},
        runtime=MagicMock(),
        model_settings={},
    )


class _CaptureChatMessages(BaseCallbackHandler):
    def __init__(self):
        self.messages = []

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self.messages = messages[0]


def _image_context_messages(messages: list[AnyMessage]) -> list[HumanMessage]:
    return [message for message in messages if isinstance(message, HumanMessage) and message.id and message.id.startswith("view-image-context:")]


def _make_viewed_image(tmp_path, filename="img.png", mime_type="image/png", data=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"):
    """Create a real image file and return viewed_images metadata dict."""
    img_path = tmp_path / filename
    img_path.write_bytes(data)
    return {
        "mime_type": mime_type,
        "size": len(data),
        "actual_path": str(img_path),
    }


def _authorized_host_view(tmp_path, monkeypatch):
    paths = Paths(tmp_path)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)
    outputs = paths.sandbox_outputs_dir("thread-test", user_id="user-test")
    outputs.mkdir(parents=True)
    virtual_path = "/mnt/user-data/outputs/img.png"
    return virtual_path, _make_viewed_image(outputs)


def _blob_backed_request(monkeypatch):
    from deerflow.authz import sandbox_authz

    image_bytes = b"\x89PNG\r\n\x1a\nshared-model-image"
    ref = BlobRef(
        sha256=hashlib.sha256(image_bytes).hexdigest(),
        size=len(image_bytes),
        kind="viewed-image",
        content_type="image/png",
    )

    class SharedStore:
        def get_bytes(self, requested: BlobRef) -> bytes:
            assert requested == ref
            return image_bytes

    monkeypatch.setattr("deerflow.storage.get_blob_store_if_enabled", lambda: SharedStore())
    monkeypatch.setattr(sandbox_authz, "authorize_sandbox_execution", lambda **kwargs: None)
    virtual_path = "/mnt/user-data/outputs/shared.png"
    assistant = AIMessage(content="", tool_calls=[_view_image_call("c1", virtual_path)])
    request = _model_request(
        [assistant, ToolMessage(content="ok", tool_call_id="c1")],
        {
            virtual_path: {
                "mime_type": "image/png",
                "size": len(image_bytes),
                "actual_path": "Z:/writer-only/shared.png",
                "sha256": ref.sha256,
                "blob_ref": ref.model_dump(exclude_none=True),
            }
        },
    )
    request.runtime.context = {"user_id": "user-test", "thread_id": "thread-test"}
    return request, "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")


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
    def test_keeps_recent_images_within_count_and_byte_budget(self, tmp_path, monkeypatch):
        from deerflow.agents.middlewares import view_image_middleware as module

        monkeypatch.setattr(module, "_MAX_CONTEXT_IMAGES", 2)
        monkeypatch.setattr(module, "_MAX_CONTEXT_BASE64_BYTES", 16)
        viewed = {f"/{name}.png": _make_viewed_image(tmp_path, f"{name}.png", data=b"123456") for name in ("old", "middle", "new")}
        reads = []

        def read(_cls, _state, image_path, *_args, **_kwargs):
            reads.append(image_path)
            return "data:image/png;base64,MTIzNDU2"

        monkeypatch.setattr(ViewImageMiddleware, "_read_image_as_data_url", classmethod(read))
        blocks = ViewImageMiddleware()._create_image_details_message({"viewed_images": viewed})

        assert reads == ["/new.png", "/middle.png"]
        assert [block["type"] for block in blocks].count("image_url") == 2
        assert "Omitted viewed images: 1." in str(blocks)

    @pytest.mark.parametrize("omitted_count", [1, 2])
    def test_skips_oversized_image_without_reading_it(self, tmp_path, monkeypatch, omitted_count):
        from deerflow.agents.middlewares import view_image_middleware as module

        monkeypatch.setattr(module, "_MAX_CONTEXT_BASE64_BYTES", 8)
        viewed = {f"/large-{i}.png": _make_viewed_image(tmp_path, f"large-{i}.png", data=b"1234567") for i in range(omitted_count)}
        monkeypatch.setattr(
            ViewImageMiddleware,
            "_read_image_as_data_url",
            lambda *_args, **_kwargs: pytest.fail("oversized image was read"),
        )
        blocks = ViewImageMiddleware()._create_image_details_message({"viewed_images": viewed})
        assert all(block["type"] != "image_url" for block in blocks)
        assert f"Omitted viewed images: {omitted_count}." in str(blocks)

    def test_omission_notice_does_not_assume_omitted_image_is_older(self, tmp_path, monkeypatch):
        from deerflow.agents.middlewares import view_image_middleware as module

        monkeypatch.setattr(module, "_MAX_CONTEXT_BASE64_BYTES", 8)
        viewed = {
            "/old.png": _make_viewed_image(tmp_path, "old.png", data=b"123456"),
            "/new.png": _make_viewed_image(tmp_path, "new.png", data=b"1234567"),
        }
        blocks = ViewImageMiddleware()._create_image_details_message({"viewed_images": viewed}, host_path_allowed=lambda _, actual: Path(actual).is_relative_to(tmp_path))
        urls = [block["image_url"]["url"] for block in blocks if block["type"] == "image_url"]
        assert [base64.b64decode(url.split(",", 1)[1]) for url in urls] == [b"123456"]
        assert blocks[1] == {"type": "text", "text": "Omitted viewed images: 1. Call view_image again to inspect a specific image."}

    def test_failed_reads_consume_slots_before_readable_older_image(self, tmp_path, monkeypatch):
        viewed = {"/old.png": _make_viewed_image(tmp_path, "old.png")}
        viewed.update({f"/stale-{i}.png": {"mime_type": "image/png", "size": 1} for i in range(4)})
        middleware = ViewImageMiddleware()
        original_read = middleware._read_image_as_data_url
        reads = []

        def record_read(state, image_path, *args, **kwargs):
            reads.append(image_path)
            return original_read(state, image_path, *args, **kwargs)

        monkeypatch.setattr(middleware, "_read_image_as_data_url", record_read)
        blocks = middleware._create_image_details_message({"viewed_images": viewed}, host_path_allowed=lambda _, actual: Path(actual).is_relative_to(tmp_path))
        assert reads == [f"/stale-{i}.png" for i in reversed(range(4))]
        assert sum("file unavailable or changed" in block.get("text", "") for block in blocks) == 4
        assert all(block["type"] != "image_url" for block in blocks)
        assert "Omitted viewed images: 1." in str(blocks)

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
        blocks = mw._create_image_details_message(state, host_path_allowed=lambda _, actual: Path(actual).is_relative_to(tmp_path))

        # header text + per-image description text + per-image image_url block
        assert len(blocks) == 3
        assert blocks[0] == {"type": "text", "text": "Here are the images you've viewed:"}
        assert blocks[1]["type"] == "text"
        assert "/path/to/cat.png" in blocks[1]["text"]
        assert "image/png" in blocks[1]["text"]
        assert blocks[2]["type"] == "image_url"
        assert blocks[2]["image_url"]["url"].startswith("data:image/png;base64,")

    def test_resolves_blob_ref_when_writer_host_copy_is_absent(self, tmp_path, monkeypatch):
        image_bytes = b"\x89PNG\r\n\x1a\nshared-image"
        ref = BlobRef(
            sha256=hashlib.sha256(image_bytes).hexdigest(),
            size=len(image_bytes),
            kind="viewed-image",
            content_type="image/png",
        )
        reads: list[BlobRef] = []

        class SharedStore:
            def get_bytes(self, requested: BlobRef) -> bytes:
                reads.append(requested)
                return image_bytes

        monkeypatch.setattr("deerflow.storage.get_blob_store_if_enabled", lambda: SharedStore())
        state = {
            "viewed_images": {
                "/mnt/user-data/outputs/shared.png": {
                    "mime_type": "image/png",
                    "size": len(image_bytes),
                    "actual_path": str(tmp_path / "writer-only" / "shared.png"),
                    "sha256": ref.sha256,
                    "blob_ref": ref.model_dump(exclude_none=True),
                }
            }
        }

        blocks = ViewImageMiddleware()._create_image_details_message(state)

        image_blocks = [block for block in blocks if isinstance(block, dict) and block.get("type") == "image_url"]
        assert len(image_blocks) == 1
        assert image_blocks[0]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
        assert reads == [ref]

    def test_blob_store_factory_failure_falls_back_to_validated_host_copy(self, tmp_path, monkeypatch):
        image_bytes = b"\x89PNG\r\n\x1a\nlocal-fallback"
        img_path = tmp_path / "fallback.png"
        img_path.write_bytes(image_bytes)
        ref = BlobRef(
            sha256=hashlib.sha256(image_bytes).hexdigest(),
            size=len(image_bytes),
            kind="viewed-image",
            content_type="image/png",
        )

        def fail_to_resolve_store():
            raise ValueError("misconfigured backend")

        monkeypatch.setattr("deerflow.storage.get_blob_store_if_enabled", fail_to_resolve_store)
        state = {
            "viewed_images": {
                "/mnt/user-data/outputs/fallback.png": {
                    "mime_type": "image/png",
                    "size": len(image_bytes),
                    "actual_path": str(img_path),
                    "sha256": ref.sha256,
                    "blob_ref": ref.model_dump(exclude_none=True),
                }
            }
        }

        blocks = ViewImageMiddleware()._create_image_details_message(
            state,
            host_path_allowed=lambda _virtual, actual: actual == str(img_path),
        )

        image_blocks = [block for block in blocks if isinstance(block, dict) and block.get("type") == "image_url"]
        assert len(image_blocks) == 1
        assert image_blocks[0]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")

    def test_raw_blob_read_failure_falls_back_to_validated_host_copy(self, tmp_path, monkeypatch):
        image_bytes = b"\x89PNG\r\n\x1a\nlocal-fallback"
        img_path = tmp_path / "fallback.png"
        img_path.write_bytes(image_bytes)
        ref = BlobRef(
            sha256=hashlib.sha256(image_bytes).hexdigest(),
            size=len(image_bytes),
            kind="viewed-image",
            content_type="image/png",
        )

        class FailingStore:
            def get_bytes(self, requested: BlobRef) -> bytes:
                raise RuntimeError("raw SDK failure")

        monkeypatch.setattr("deerflow.storage.get_blob_store_if_enabled", lambda: FailingStore())
        state = {
            "viewed_images": {
                "/mnt/user-data/outputs/fallback.png": {
                    "mime_type": "image/png",
                    "size": len(image_bytes),
                    "actual_path": str(img_path),
                    "sha256": ref.sha256,
                    "blob_ref": ref.model_dump(exclude_none=True),
                }
            }
        }

        blocks = ViewImageMiddleware()._create_image_details_message(
            state,
            host_path_allowed=lambda _virtual, actual: actual == str(img_path),
        )

        image_blocks = [block for block in blocks if isinstance(block, dict) and block.get("type") == "image_url"]
        assert len(image_blocks) == 1
        assert image_blocks[0]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")

    def test_malformed_blob_ref_falls_back_to_validated_host_copy(self, tmp_path):
        image_bytes = b"\x89PNG\r\n\x1a\nlocal-fallback"
        img_path = tmp_path / "fallback.png"
        img_path.write_bytes(image_bytes)
        state = {
            "viewed_images": {
                "/mnt/user-data/outputs/fallback.png": {
                    "mime_type": "image/png",
                    "size": len(image_bytes),
                    "actual_path": str(img_path),
                    "sha256": hashlib.sha256(image_bytes).hexdigest(),
                    "blob_ref": {"sha256": "not-a-digest", "size": len(image_bytes), "kind": "viewed-image"},
                }
            }
        }

        blocks = ViewImageMiddleware()._create_image_details_message(
            state,
            host_path_allowed=lambda _virtual, actual: actual == str(img_path),
        )

        assert any(isinstance(block, dict) and block.get("type") == "image_url" for block in blocks)

    def test_blob_ref_must_match_checkpoint_metadata_before_read(self, tmp_path, monkeypatch):
        image_bytes = b"\x89PNG\r\n\x1a\nshared-image"
        ref = BlobRef(
            sha256=hashlib.sha256(image_bytes).hexdigest(),
            size=len(image_bytes),
            kind="viewed-image",
            content_type="image/png",
        )

        class StoreMustNotBeRead:
            def get_bytes(self, requested: BlobRef) -> bytes:
                raise AssertionError(f"unexpected blob read: {requested}")

        monkeypatch.setattr("deerflow.storage.get_blob_store_if_enabled", lambda: StoreMustNotBeRead())
        state = {
            "viewed_images": {
                "/mnt/user-data/outputs/shared.png": {
                    "mime_type": "image/png",
                    "size": len(image_bytes) + 1,
                    "actual_path": str(tmp_path / "missing.png"),
                    "sha256": ref.sha256,
                    "blob_ref": ref.model_dump(exclude_none=True),
                }
            }
        }

        blocks = ViewImageMiddleware()._create_image_details_message(state)

        assert all(not (isinstance(block, dict) and block.get("type") == "image_url") for block in blocks)

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
        blocks = mw._create_image_details_message(state, host_path_allowed=lambda _, actual: Path(actual).is_relative_to(tmp_path))

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
        blocks = mw._create_image_details_message(state, host_path_allowed=lambda _, actual: Path(actual).is_relative_to(tmp_path))
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
        assert mw._should_inject_image_message([]) is False

    def test_false_when_no_assistant_message(self):
        mw = ViewImageMiddleware()
        assert mw._should_inject_image_message([HumanMessage(content="hello")]) is False

    def test_false_when_no_view_image_tool_call(self):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_other_tool_call()])
        messages = [assistant, ToolMessage(content="ok", tool_call_id="call_other")]
        assert mw._should_inject_image_message(messages) is False

    def test_false_when_tool_not_completed(self):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        assert mw._should_inject_image_message([assistant]) is False  # no ToolMessage yet

    def test_true_when_all_preconditions_met(self):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        messages = [assistant, ToolMessage(content="ok", tool_call_id="c1")]
        assert mw._should_inject_image_message(messages) is True

    def test_false_when_already_injected(self):
        """A checkpoint written by an older version (or by a run that died before
        its `RemoveMessage` cleanup landed) can still carry image details. Do not
        add a duplicate on top of one."""
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        already_injected = HumanMessage(content="Here are the images you've viewed: /img.png")
        messages = [
            assistant,
            ToolMessage(content="ok", tool_call_id="c1"),
            already_injected,
        ]
        assert mw._should_inject_image_message(messages) is False

    def test_false_when_already_injected_with_list_content(self, tmp_path):
        """Deduplication must recognize the real injected payload shape.

        An unmarked leftover carries `.content` as a *list* of dicts (text +
        image_url blocks), not a plain string. This test reuses
        `_create_image_details_message` output to reproduce the realistic shape
        and confirms the marker is still detected via `str(msg.content)`.
        """
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        viewed_images = {"/img.png": _make_viewed_image(tmp_path)}
        # Build content the same way the middleware would.
        real_injected_content = mw._create_image_details_message({"viewed_images": viewed_images})
        # Sanity: this is a list of blocks, not a plain string.
        assert isinstance(real_injected_content, list)

        messages = [
            assistant,
            ToolMessage(content="ok", tool_call_id="c1"),
            HumanMessage(content=real_injected_content),
        ]
        assert mw._should_inject_image_message(messages) is False

    def test_false_when_legacy_details_marker_present(self):
        """The middleware also recognizes the legacy 'Here are the details of the
        images you've viewed' marker as an already-injected signal."""
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        legacy = HumanMessage(content="Here are the details of the images you've viewed: ...")
        messages = [
            assistant,
            ToolMessage(content="ok", tool_call_id="c1"),
            legacy,
        ]
        assert mw._should_inject_image_message(messages) is False


class TestInject:
    def test_returns_request_unchanged_when_should_not_inject(self):
        mw = ViewImageMiddleware()
        request = _model_request([HumanMessage(content="hi")])
        assert mw._inject(request) is request

    def test_appends_image_context_message_to_request(self, tmp_path, monkeypatch):
        mw = ViewImageMiddleware()
        virtual_path, image_metadata = _authorized_host_view(tmp_path, monkeypatch)
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1", virtual_path)])
        original = [assistant, ToolMessage(content="ok", tool_call_id="c1")]
        request = _model_request(original, {virtual_path: image_metadata})
        request.runtime.context = {"user_id": "user-test", "thread_id": "thread-test"}

        injected_request = mw._inject(request)

        assert injected_request is not request
        # The payload is appended last, so it directly follows the tool results.
        assert injected_request.messages[:-1] == original
        injected = injected_request.messages[-1]
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

    def test_replaces_a_stranded_payload_instead_of_stacking_a_second_one(self, tmp_path, monkeypatch):
        """A run that died during the model call can leave the old
        before_model/after_model pair's message checkpointed. Rebuild it rather
        than adding a second copy on top."""
        mw = ViewImageMiddleware()
        virtual_path, image_metadata = _authorized_host_view(tmp_path, monkeypatch)
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1", virtual_path)])
        stranded = ViewImageMiddleware._create_image_context_message([{"type": "text", "text": "stale"}])
        request = _model_request(
            [assistant, ToolMessage(content="ok", tool_call_id="c1"), stranded],
            {virtual_path: image_metadata},
        )
        request.runtime.context = {"user_id": "user-test", "thread_id": "thread-test"}

        injected = _image_context_messages(mw._inject(request).messages)

        assert len(injected) == 1
        assert injected[0].id != stranded.id
        assert any(isinstance(b, dict) and b.get("type") == "image_url" for b in injected[0].content)

    def test_drops_a_stranded_payload_even_when_no_injection_is_warranted(self):
        """Otherwise the stale base64 would ride along in every later request for
        the life of the thread -- the old `after_model` swept it, so dropping the
        hook must not lose that."""
        mw = ViewImageMiddleware()
        stranded = ViewImageMiddleware._create_image_context_message([{"type": "text", "text": "stale"}])
        request = _model_request([HumanMessage(content="hi"), stranded, AIMessage(content="done")])

        prepared = mw._inject(request)

        assert prepared is not request
        assert _image_context_messages(prepared.messages) == []
        assert [type(m) for m in prepared.messages] == [HumanMessage, AIMessage]

    def test_never_drops_a_client_message_wearing_the_reserved_prefix(self):
        """The prefix alone is not enough — Gateway strips the server-owned
        marker from client input, and both are required to match."""
        mw = ViewImageMiddleware()
        client_message = HumanMessage(id="view-image-context:client-supplied", content="client-authored", additional_kwargs={"hide_from_ui": True})
        request = _model_request([client_message, AIMessage(content="done")])

        assert mw._inject(request) is request

    def test_does_not_mutate_the_incoming_request(self, tmp_path):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        request = _model_request(
            [assistant, ToolMessage(content="ok", tool_call_id="c1")],
            {"/img.png": _make_viewed_image(tmp_path)},
        )

        mw._inject(request)

        assert _image_context_messages(request.messages) == []


class TestWrapModelCall:
    def test_blob_backed_image_reaches_sync_model_without_writer_disk(self, monkeypatch):
        request, expected = _blob_backed_request(monkeypatch)
        seen: list[ModelRequest] = []

        ViewImageMiddleware().wrap_model_call(
            request,
            lambda prepared: seen.append(prepared) or AIMessage(content="ok"),
        )

        assert _image_urls(seen[0]) == [expected]

    def test_handler_receives_the_image_context_message(self, tmp_path):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        request = _model_request(
            [assistant, ToolMessage(content="ok", tool_call_id="c1")],
            {"/img.png": _make_viewed_image(tmp_path)},
        )
        seen: list[ModelRequest] = []

        def handler(prepared: ModelRequest) -> AIMessage:
            seen.append(prepared)
            return AIMessage(content="I can see the image.")

        result = mw.wrap_model_call(request, handler)

        assert result.content == "I can see the image."
        assert len(_image_context_messages(seen[0].messages)) == 1

    def test_handler_receives_request_unchanged_when_not_warranted(self):
        mw = ViewImageMiddleware()
        request = _model_request([HumanMessage(content="hi")])
        seen: list[ModelRequest] = []

        mw.wrap_model_call(request, lambda prepared: seen.append(prepared) or AIMessage(content="ok"))

        assert seen[0] is request

    @pytest.mark.anyio
    async def test_awrap_model_call_matches_sync_behavior(self, tmp_path):
        mw = ViewImageMiddleware()
        assistant = AIMessage(content="", tool_calls=[_view_image_call("c1")])
        request = _model_request(
            [assistant, ToolMessage(content="ok", tool_call_id="c1")],
            {"/img.png": _make_viewed_image(tmp_path)},
        )
        seen: list[ModelRequest] = []

        async def handler(prepared: ModelRequest) -> AIMessage:
            seen.append(prepared)
            return AIMessage(content="I can see the image.")

        result = await mw.awrap_model_call(request, handler)

        assert result.content == "I can see the image."
        assert len(_image_context_messages(seen[0].messages)) == 1

    @pytest.mark.anyio
    async def test_blob_backed_image_reaches_async_model_without_writer_disk(self, monkeypatch):
        from deerflow.authz import sandbox_authz

        request, expected = _blob_backed_request(monkeypatch)
        seen: list[ModelRequest] = []

        async def authorize(**kwargs):
            return None

        monkeypatch.setattr(sandbox_authz, "authorize_sandbox_execution_async", authorize)

        async def handler(prepared: ModelRequest) -> AIMessage:
            seen.append(prepared)
            return AIMessage(content="ok")

        await ViewImageMiddleware().awrap_model_call(request, handler)

        assert _image_urls(seen[0]) == [expected]


class TestGraphIntegration:
    def _graph_and_capture(self):
        capture = _CaptureChatMessages()
        model = FakeMessagesListChatModel(
            responses=[AIMessage(content="I can see the image.")],
            callbacks=[capture],
        )
        return create_agent(model=model, tools=[], middleware=[ViewImageMiddleware()]), capture

    def _input(self, tmp_path, monkeypatch):
        virtual_path, image_metadata = _authorized_host_view(tmp_path, monkeypatch)
        return {
            "messages": [
                AIMessage(content="", tool_calls=[_view_image_call("c1", virtual_path)]),
                ToolMessage(content="ok", tool_call_id="c1"),
            ],
            "viewed_images": {virtual_path: image_metadata},
        }

    def test_image_context_reaches_the_model_but_never_the_state(self, tmp_path, monkeypatch):
        graph, capture = self._graph_and_capture()

        result = graph.invoke(
            self._input(tmp_path, monkeypatch),
            config={"configurable": {"thread_id": "thread-test"}},
            context={"user_id": "user-test"},
        )

        model_image_messages = _image_context_messages(capture.messages)
        assert len(model_image_messages) == 1
        assert any(block.get("type") == "image_url" for block in model_image_messages[0].content)
        # Nothing is written back, so the payload is absent from every checkpoint
        # rather than being added and then removed again.
        assert _image_context_messages(result["messages"]) == []

    @pytest.mark.anyio
    async def test_async_graph_matches_sync_behavior(self, tmp_path, monkeypatch):
        graph, capture = self._graph_and_capture()

        result = await graph.ainvoke(
            self._input(tmp_path, monkeypatch),
            config={"configurable": {"thread_id": "thread-test"}},
            context={"user_id": "user-test"},
        )

        assert len(_image_context_messages(capture.messages)) == 1
        assert any(block.get("type") == "image_url" for block in _image_context_messages(capture.messages)[0].content)
        assert _image_context_messages(result["messages"]) == []

    def test_context_thread_id_cannot_override_configured_thread(self, tmp_path, monkeypatch):
        graph, capture = self._graph_and_capture()

        graph.invoke(
            self._input(tmp_path, monkeypatch),
            config={"configurable": {"thread_id": "another-thread"}},
            context={"user_id": "user-test", "thread_id": "thread-test"},
        )

        model_image_messages = _image_context_messages(capture.messages)
        assert len(model_image_messages) == 1
        assert all(block.get("type") != "image_url" for block in model_image_messages[0].content)

    def test_graph_preserves_normalized_client_message_with_reserved_prefix(self, tmp_path, monkeypatch):
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

        graph, capture = self._graph_and_capture()
        graph_input = self._input(tmp_path, monkeypatch)

        result = graph.invoke({**graph_input, "messages": [client_message, *graph_input["messages"]]}, context={"user_id": "user-test", "thread_id": "thread-test"})

        assert any(message.id == client_id for message in capture.messages)
        assert any(message.id != client_id and message.additional_kwargs.get(_IMAGE_CONTEXT_MESSAGE_MARKER_KEY) is True for message in _image_context_messages(capture.messages))
        persisted_client = next(message for message in result["messages"] if message.id == client_id)
        assert persisted_client.content == "client-authored message"
        assert persisted_client.additional_kwargs == {"custom": "keep-me"}
        assert all(message.additional_kwargs.get(_IMAGE_CONTEXT_MESSAGE_MARKER_KEY) is not True for message in result["messages"] if isinstance(message, HumanMessage))


def test_host_image_copy_is_scoped_to_current_user_and_thread(tmp_path, monkeypatch):
    """A stale viewed_images entry must not open another user's host copy."""
    from deerflow.authz import sandbox_authz

    monkeypatch.setattr(sandbox_authz, "authorize_sandbox_execution", lambda **kwargs: None)
    paths = Paths(tmp_path)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)
    monkeypatch.setattr("deerflow.sandbox.sandbox_provider.get_sandbox_provider", lambda: SimpleNamespace(get=lambda sandbox_id: None))

    image_bytes = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
    virtual_path = "/mnt/user-data/outputs/canary.png"
    owner_path = paths.sandbox_outputs_dir("thread-b", user_id="user-b") / "canary.png"
    owner_path.parent.mkdir(parents=True)
    owner_path.write_bytes(image_bytes)
    metadata = {"mime_type": "image/png", "size": len(image_bytes), "actual_path": str(owner_path)}
    messages = [AIMessage(content="", tool_calls=[_view_image_call("call-image", virtual_path)]), ToolMessage(content="Successfully read image", tool_call_id="call-image")]

    def model_payloads(user_id: str, thread_id: str | None, actual_path: Path = owner_path) -> list[str]:
        request = _model_request(messages, {virtual_path: {**metadata, "actual_path": str(actual_path)}})
        request.runtime.context = {"user_id": user_id, "thread_id": thread_id}
        prepared = ViewImageMiddleware()._inject(request)
        return [block["image_url"]["url"] for message in _image_context_messages(prepared.messages) for block in message.content if isinstance(block, dict) and block.get("type") == "image_url"]

    expected = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    assert model_payloads("user-b", "thread-b") == [expected]
    assert model_payloads("user-a", "thread-a") == []
    assert model_payloads("user-b", "thread-a") == []
    assert model_payloads("user-b", None) == []

    alias_path = paths.sandbox_outputs_dir("thread-a", user_id="user-a") / "canary.png"
    alias_path.parent.mkdir(parents=True)
    symlink_or_skip(alias_path, owner_path)
    assert model_payloads("user-a", "thread-a", alias_path) == []


def _custom_base_view_request(tmp_path, monkeypatch):
    """Use the real tool to record a host copy under a non-global Paths base."""
    from deerflow.authz import sandbox_authz
    from deerflow.tools.builtins.view_image_tool import _view_image_authorized

    monkeypatch.setattr(sandbox_authz, "authorize_sandbox_execution", lambda **kwargs: None)
    monkeypatch.setattr("deerflow.sandbox.sandbox_provider.get_sandbox_provider", lambda: SimpleNamespace(get=lambda sandbox_id: None))

    paths = Paths(tmp_path / "custom-base")
    virtual_path = "/mnt/user-data/outputs/canary.png"
    image_bytes = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
    actual_path = paths.sandbox_outputs_dir("thread-test", user_id="user-test") / "canary.png"
    actual_path.parent.mkdir(parents=True)
    actual_path.write_bytes(image_bytes)
    thread_data = {
        "workspace_path": str(paths.sandbox_work_dir("thread-test", user_id="user-test")),
        "uploads_path": str(paths.sandbox_uploads_dir("thread-test", user_id="user-test")),
        "outputs_path": str(actual_path.parent),
    }
    tool_runtime = SimpleNamespace(
        state={"thread_data": thread_data},
        context={"user_id": "user-test", "thread_id": "thread-test"},
    )
    result = _view_image_authorized(tool_runtime, virtual_path, "call-image")
    metadata = result.update["viewed_images"][virtual_path]
    assert metadata["actual_path"] == str(actual_path)

    messages = [
        AIMessage(content="", tool_calls=[_view_image_call("call-image", virtual_path)]),
        ToolMessage(content="Successfully read image", tool_call_id="call-image"),
    ]
    request = _model_request(messages, {virtual_path: metadata})
    request.state["thread_data"] = thread_data
    request.runtime.context = tool_runtime.context
    expected = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    return request, expected


def _image_urls(request: ModelRequest) -> list[str]:
    return [block["image_url"]["url"] for message in _image_context_messages(request.messages) for block in message.content if isinstance(block, dict) and block.get("type") == "image_url"]


def test_custom_base_host_copy_reaches_sync_model(tmp_path, monkeypatch):
    request, expected = _custom_base_view_request(tmp_path, monkeypatch)
    prepared: list[ModelRequest] = []

    ViewImageMiddleware().wrap_model_call(request, lambda value: prepared.append(value) or AIMessage(content="ok"))

    assert _image_urls(prepared[0]) == [expected]


@pytest.mark.anyio
async def test_custom_base_host_copy_reaches_async_model(tmp_path, monkeypatch):
    request, expected = _custom_base_view_request(tmp_path, monkeypatch)
    prepared: list[ModelRequest] = []

    async def handler(value: ModelRequest) -> AIMessage:
        prepared.append(value)
        return AIMessage(content="ok")

    await ViewImageMiddleware().awrap_model_call(request, handler)

    assert _image_urls(prepared[0]) == [expected]


def test_custom_base_host_copy_still_requires_matching_user_and_thread(tmp_path, monkeypatch):
    request, _ = _custom_base_view_request(tmp_path, monkeypatch)
    middleware = ViewImageMiddleware()

    for user_id, thread_id in (("other-user", "thread-test"), ("user-test", "other-thread"), ("user-test", None)):
        request.runtime.context = {"user_id": user_id, "thread_id": thread_id}
        assert _image_urls(middleware._inject(request)) == []


def test_custom_base_host_copy_rejects_unscoped_thread_data_root(tmp_path, monkeypatch):
    request, _ = _custom_base_view_request(tmp_path, monkeypatch)
    virtual_path = "/mnt/user-data/outputs/canary.png"
    unscoped_path = tmp_path / "unscoped" / "canary.png"
    unscoped_path.parent.mkdir()
    unscoped_path.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="))
    request.state["thread_data"] = {**request.state["thread_data"], "outputs_path": str(unscoped_path.parent)}
    request.state["viewed_images"][virtual_path] = {
        **request.state["viewed_images"][virtual_path],
        "actual_path": str(unscoped_path),
    }

    assert _image_urls(ViewImageMiddleware()._inject(request)) == []


def _text_blocks(blocks: list) -> list[str]:
    return [block["text"] for block in blocks if isinstance(block, dict) and block.get("type") == "text"]


def test_injection_budget_keeps_newest_images_and_omits_oldest(tmp_path):
    """The image cap admits newest-first; omitted entries keep a placeholder bullet (see #6825)."""
    viewed_images = {}
    for i in range(4):
        viewed_images[f"/mnt/user-data/outputs/img_{i}.png"] = _make_viewed_image(tmp_path, f"img_{i}.png", data=bytes([i]) + b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    state = {"viewed_images": viewed_images}

    mw = ViewImageMiddleware(max_injected_images=2)
    blocks = mw._create_image_details_message(state, host_path_allowed=lambda _, actual: Path(actual).is_relative_to(tmp_path))

    image_urls = [b["image_url"]["url"] for b in blocks if isinstance(b, dict) and b.get("type") == "image_url"]
    assert len(image_urls) == 2

    # The two newest entries (img_2, img_3) are injected; the two oldest keep a placeholder.
    # Walk the raw block list so each bullet's successor block is checked in place.
    for i, block in enumerate(blocks):
        if not (isinstance(block, dict) and block.get("type") == "text"):
            continue
        text = block["text"]
        for omitted in ("img_0.png", "img_1.png"):
            if omitted in text:
                assert "omitted: image injection budget reached" in blocks[i + 1]["text"]
        for injected in ("img_2.png", "img_3.png"):
            if injected in text:
                assert blocks[i + 1].get("type") == "image_url"

    # Distinct payloads prove which entries made it.
    assert base64.b64decode(image_urls[0].split(",", 1)[1]).startswith(bytes([2]))
    assert base64.b64decode(image_urls[1].split(",", 1)[1]).startswith(bytes([3]))


def test_injection_byte_budget_drops_oldest_when_total_exceeded(tmp_path):
    """The byte cap evicts the oldest oversized entry while a newer small one still fits."""
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (900_000 - 8)
    small = b"\x89PNG\r\n\x1a\n" + b"\x00" * (100_000 - 8)
    state = {
        "viewed_images": {
            "/mnt/user-data/outputs/big_0.png": _make_viewed_image(tmp_path, "big_0.png", data=big),
            "/mnt/user-data/outputs/big_1.png": _make_viewed_image(tmp_path, "big_1.png", data=big),
            "/mnt/user-data/outputs/small_2.png": _make_viewed_image(tmp_path, "small_2.png", data=small),
        }
    }

    mw = ViewImageMiddleware(max_injected_total_chars=2_000_000)
    blocks = mw._create_image_details_message(state, host_path_allowed=lambda _, actual: Path(actual).is_relative_to(tmp_path))

    image_urls = [b["image_url"]["url"] for b in blocks if isinstance(b, dict) and b.get("type") == "image_url"]
    assert len(image_urls) == 2
    for i, block in enumerate(blocks):
        if not (isinstance(block, dict) and block.get("type") == "text"):
            continue
        if "big_0.png" in block["text"]:
            assert "omitted: image injection budget reached" in blocks[i + 1]["text"]
        if "small_2.png" in block["text"]:
            assert blocks[i + 1].get("type") == "image_url"


def test_injection_budget_defaults_keep_small_threads_unbounded(tmp_path):
    """Defaults must not change threads whose image count and sizes stay small."""
    viewed_images = {}
    for i in range(3):
        viewed_images[f"/mnt/user-data/outputs/img_{i}.png"] = _make_viewed_image(tmp_path, f"img_{i}.png")
    state = {"viewed_images": viewed_images}

    blocks = ViewImageMiddleware()._create_image_details_message(state, host_path_allowed=lambda _, actual: Path(actual).is_relative_to(tmp_path))

    assert len([b for b in blocks if isinstance(b, dict) and b.get("type") == "image_url"]) == 3
    assert not any("omitted" in t for t in _text_blocks(blocks))


def test_injection_budget_skips_reads_for_omitted_entries(tmp_path):
    """Entries over budget are never read from disk or sandbox."""
    viewed_images = {}
    for i in range(3):
        viewed_images[f"/mnt/user-data/outputs/img_{i}.png"] = _make_viewed_image(tmp_path, f"img_{i}.png", data=bytes([i]) + b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    state = {"viewed_images": viewed_images}

    mw = ViewImageMiddleware(max_injected_images=1)
    calls = []

    def _fake_read(*args, **kwargs):
        calls.append(args)
        return "data:image/png;base64,QUJD"

    mw._read_image_as_data_url = _fake_read
    blocks = mw._create_image_details_message(state)

    assert len([b for b in blocks if isinstance(b, dict) and b.get("type") == "image_url"]) == 1
    assert len(calls) == 1


def test_reviewing_omitted_image_rescues_it_from_budget(tmp_path):
    """Re-viewing an omitted image must move it to the newest slot so the
    placeholder's recovery advice actually works (see #6829 review)."""
    viewed_images = {}
    for i in range(4):
        viewed_images[f"/mnt/user-data/outputs/img_{i}.png"] = _make_viewed_image(tmp_path, f"img_{i}.png", data=bytes([i]) + b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

    mw = ViewImageMiddleware(max_injected_images=2)

    def host_ok(_, actual):
        return Path(actual).is_relative_to(tmp_path)

    blocks = mw._create_image_details_message({"viewed_images": viewed_images}, host_path_allowed=host_ok)
    injected = [b for b in blocks if isinstance(b, dict) and b.get("type") == "image_url"]
    assert len(injected) == 2  # img_2, img_3 admitted; img_0/img_1 omitted

    # The model follows the placeholder advice and re-views img_0; the reducer
    # re-inserts the updated key at the end, making it the newest entry.
    updated = merge_viewed_images(
        viewed_images,
        {"/mnt/user-data/outputs/img_0.png": _make_viewed_image(tmp_path, "img_0.png", data=bytes([0]) + b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)},
    )
    assert list(updated.keys())[-1] == "/mnt/user-data/outputs/img_0.png"

    blocks = mw._create_image_details_message({"viewed_images": updated}, host_path_allowed=host_ok)
    urls = [b["image_url"]["url"] for b in blocks if isinstance(b, dict) and b.get("type") == "image_url"]
    assert len(urls) == 2
    # Render order is oldest-first, so the admitted slots are img_3 then the
    # re-viewed img_0; img_1/img_2 stay omitted.
    payloads = [base64.b64decode(url.split(",", 1)[1]) for url in urls]
    assert payloads[0].startswith(bytes([3]))
    assert payloads[1].startswith(bytes([0]))
