"""Tests for view image middleware context injection behavior."""

import asyncio
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.middlewares.view_image_middleware import (
    VIEW_IMAGE_INJECTION_MARKER,
    ViewImageMiddleware,
)


def _make_runtime():
    runtime = MagicMock()
    runtime.context = {"thread_id": "test-thread"}
    return runtime


def _view_image_ai_message():
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "view_image",
                "id": "tool-1",
                "args": {"image_path": "/mnt/user-data/outputs/chart.png"},
            }
        ],
    )


def _view_image_tool_result():
    return ToolMessage(content="Successfully read image", tool_call_id="tool-1")


def _viewed_images_state():
    return {
        "/mnt/user-data/outputs/chart.png": {
            "base64": "ZmFrZS1pbWFnZS1ieXRlcw==",
            "mime_type": "image/png",
        }
    }


class TestViewImageMiddleware:
    def test_injects_hidden_human_message_after_completed_view_image(self):
        middleware = ViewImageMiddleware()
        state = {
            "messages": [HumanMessage(content="Please inspect this chart"), _view_image_ai_message(), _view_image_tool_result()],
            "viewed_images": _viewed_images_state(),
        }

        result = middleware.before_model(state, _make_runtime())

        assert result is not None
        messages = result["messages"]
        assert len(messages) == 1
        injected = messages[0]
        assert isinstance(injected, HumanMessage)
        assert injected.additional_kwargs["hide_from_ui"] is True
        assert injected.additional_kwargs[VIEW_IMAGE_INJECTION_MARKER] is True
        assert injected.content[0]["text"] == "Here are the images you've viewed:"
        assert injected.content[2]["image_url"]["url"].startswith("data:image/png;base64,")

    def test_does_not_inject_twice_when_hidden_message_already_exists(self):
        middleware = ViewImageMiddleware()
        injected_message = HumanMessage(
            content="internal context",
            additional_kwargs={
                "hide_from_ui": True,
                VIEW_IMAGE_INJECTION_MARKER: True,
            },
        )
        state = {
            "messages": [
                HumanMessage(content="Please inspect this chart"),
                _view_image_ai_message(),
                _view_image_tool_result(),
                injected_message,
            ],
            "viewed_images": _viewed_images_state(),
        }

        assert middleware.before_model(state, _make_runtime()) is None

    def test_abefore_model_matches_sync_behavior(self):
        middleware = ViewImageMiddleware()
        state = {
            "messages": [HumanMessage(content="Inspect"), _view_image_ai_message(), _view_image_tool_result()],
            "viewed_images": _viewed_images_state(),
        }

        result = asyncio.run(middleware.abefore_model(state, _make_runtime()))

        assert result is not None
        assert result["messages"][0].additional_kwargs["hide_from_ui"] is True
