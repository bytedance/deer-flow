"""Tests for ViewImageMiddleware scientific-image prompt injection."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage

view_image_middleware_module = importlib.import_module("src.agents.middlewares.view_image_middleware")


def _runtime(*, model_name: str = "vision-model") -> SimpleNamespace:
    return SimpleNamespace(context={"configurable": {"model_name": model_name}})


def _make_state(*, tool_image_paths: list[str], viewed_images: dict[str, dict]) -> dict:
    tool_calls = [{"name": "view_image", "args": {"image_path": path}, "id": f"tc-{i}"} for i, path in enumerate(tool_image_paths, start=1)]
    ai = AIMessage(content="", id="ai-1", tool_calls=tool_calls)
    tool_messages = [ToolMessage(content="ok", id=f"tm-{i}", tool_call_id=f"tc-{i}") for i in range(1, len(tool_image_paths) + 1)]
    return {"messages": [ai, *tool_messages], "viewed_images": viewed_images}


def _extract_text_blocks(content: object) -> str:
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts)


def test_injects_default_scientific_prompt_when_not_configured():
    mw = view_image_middleware_module.ViewImageMiddleware(model_name=None)
    image_path = "/mnt/user-data/uploads/fig1.png"
    state = _make_state(
        tool_image_paths=[image_path],
        viewed_images={image_path: {"base64": "Zm9v", "mime_type": "image/png"}},
    )

    result = mw.before_model(state, _runtime(model_name="vision-model"))

    assert result is not None
    msg = result["messages"][0]
    assert msg.type == "human"
    assert (msg.additional_kwargs or {}).get("deerflow_injected") == "view_image"
    text = _extract_text_blocks(msg.content)
    assert "deeply analyze" in text
    assert image_path in text


def test_uses_model_vision_prompt_when_configured(monkeypatch):
    import src.config as config_module

    class _DummyModelConfig:
        def __init__(self, vision_prompt: str):
            self.vision_prompt = vision_prompt

    custom_prompt = "请用科研审稿人的标准，定量分析图像并给出结论。"
    dummy_app_config = SimpleNamespace(get_model_config=lambda name: _DummyModelConfig(custom_prompt) if name == "vision-model" else None)
    monkeypatch.setattr(config_module, "get_app_config", lambda: dummy_app_config)

    mw = view_image_middleware_module.ViewImageMiddleware(model_name="vision-model")
    image_path = "/mnt/user-data/uploads/fig2.png"
    state = _make_state(
        tool_image_paths=[image_path],
        viewed_images={image_path: {"base64": "YmFy", "mime_type": "image/png"}},
    )

    result = mw.before_model(state, _runtime(model_name="vision-model"))

    assert result is not None
    msg = result["messages"][0]
    assert isinstance(msg.content, list)
    assert msg.content[0]["type"] == "text"
    assert msg.content[0]["text"] == custom_prompt


def test_injects_only_images_from_last_view_image_tool_calls():
    mw = view_image_middleware_module.ViewImageMiddleware(model_name=None)
    img1 = "/mnt/user-data/uploads/img1.png"
    img2 = "/mnt/user-data/uploads/img2.png"
    state = _make_state(
        tool_image_paths=[img1],
        viewed_images={
            img1: {"base64": "aW1nMQ==", "mime_type": "image/png"},
            img2: {"base64": "aW1nMg==", "mime_type": "image/png"},
        },
    )

    result = mw.before_model(state, _runtime(model_name="vision-model"))

    assert result is not None
    text = _extract_text_blocks(result["messages"][0].content)
    assert img1 in text
    assert img2 not in text
