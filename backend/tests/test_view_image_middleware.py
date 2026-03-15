"""Regression tests for ViewImageMiddleware image injection behavior."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, ToolMessage

from src.agents.middlewares.view_image_middleware import ViewImageMiddleware


def test_before_model_injects_image_message_from_view_image_tool_payload() -> None:
    middleware = ViewImageMiddleware()

    assistant_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "view_image",
                "args": {"image_path": "/mnt/user-data/uploads/miku.png"},
                "id": "tool-call-1",
                "type": "tool_call",
            }
        ],
    )
    tool_payload = json.dumps(
        {
            "__view_image__": True,
            "image_path": "/mnt/user-data/uploads/miku.png",
            "base64": "ZmFrZS1pbWFnZS1ieXRlcw==",
            "mime_type": "image/png",
        }
    )
    tool_msg = ToolMessage(content=tool_payload, tool_call_id="tool-call-1")

    state = {"messages": [assistant_msg, tool_msg]}

    update = middleware.before_model(state, runtime=None)  # type: ignore[arg-type]

    assert update is not None
    assert "messages" in update
    injected_human_msg = update["messages"][0]
    assert isinstance(injected_human_msg.content, list)
    assert any(
        isinstance(block, dict)
        and block.get("type") == "image_url"
        and "data:image/png;base64,ZmFrZS1pbWFnZS1ieXRlcw==" in block.get("image_url", {}).get("url", "")
        for block in injected_human_msg.content
    )
