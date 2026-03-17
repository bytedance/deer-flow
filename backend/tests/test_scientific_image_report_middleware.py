"""Tests for ScientificImageReportMiddleware (ImageReport injection)."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage

middleware_module = importlib.import_module("src.agents.middlewares.scientific_image_report_middleware")


def _runtime(*, model_name: str = "main-text-model") -> SimpleNamespace:
    return SimpleNamespace(context={"configurable": {"model_name": model_name}})


class _DummyVisionModel:
    def __init__(self, response_text: str):
        self._response_text = response_text

    def invoke(self, _messages):
        return SimpleNamespace(content=self._response_text)

    async def ainvoke(self, _messages):
        return SimpleNamespace(content=self._response_text)


def _state_with_view_image(*, image_paths: list[str], viewed_images: dict[str, dict]) -> dict:
    tool_calls = [{"name": "view_image", "args": {"image_path": p}, "id": f"tc-{i}"} for i, p in enumerate(image_paths, start=1)]
    ai = AIMessage(content="", id="ai-1", tool_calls=tool_calls)
    tool_messages = [ToolMessage(content="ok", id=f"tm-{i}", tool_call_id=f"tc-{i}") for i in range(1, len(image_paths) + 1)]
    return {"messages": [ai, *tool_messages], "viewed_images": viewed_images}


def test_injects_image_report_when_enabled(monkeypatch):
    cfg = SimpleNamespace(
        inject_mode="index",
        enabled=True,
        model_name="sci-vision-model",
        artifact_subdir="scientific-vision/image-reports",
        cache_enabled=True,
        max_images=4,
        prompt_template=None,
        write_batch_artifact=True,
        include_raw_model_output_in_batch=True,
        write_index_artifact=True,
        clear_viewed_images_after_report=False,
    )
    monkeypatch.setattr(middleware_module, "get_scientific_vision_config", lambda: cfg)

    dummy_app_cfg = SimpleNamespace(get_model_config=lambda name: SimpleNamespace(supports_vision=True) if name == "sci-vision-model" else None)
    monkeypatch.setattr(middleware_module, "get_app_config", lambda: dummy_app_cfg)

    response_json = (
        '{"images":[{"image_path":"/mnt/user-data/uploads/fig1.png","image_type":"western_blot","key_findings":[],"quantitative_observations":[],"controls_and_comparisons":[],"anomalies_or_artifacts":[],"limitations":[],"suggested_followups":[]}],'
        '"overall_conclusion":"ok","overall_confidence":0.6}'
    )
    monkeypatch.setattr(middleware_module, "create_chat_model", lambda name, thinking_enabled=False: _DummyVisionModel(response_json))

    image_path = "/mnt/user-data/uploads/fig1.png"
    state = _state_with_view_image(
        image_paths=[image_path],
        viewed_images={image_path: {"base64": "Zm9v", "mime_type": "image/png"}},
    )
    mw = middleware_module.ScientificImageReportMiddleware()

    result = mw.before_model(state, _runtime(model_name="main-text-model"))

    assert result is not None
    injected = result["messages"][0]
    assert injected.type == "human"
    assert (injected.additional_kwargs or {}).get("deerflow_injected") == "image_report"
    assert "<image_report" in str(injected.content)
    assert "sci-vision-model" in str(injected.content)


def test_clears_viewed_images_when_configured(monkeypatch):
    cfg = SimpleNamespace(
        inject_mode="index",
        enabled=True,
        model_name="sci-vision-model",
        artifact_subdir="scientific-vision/image-reports",
        cache_enabled=True,
        max_images=4,
        prompt_template=None,
        write_batch_artifact=True,
        include_raw_model_output_in_batch=True,
        write_index_artifact=True,
        clear_viewed_images_after_report=True,
    )
    monkeypatch.setattr(middleware_module, "get_scientific_vision_config", lambda: cfg)

    dummy_app_cfg = SimpleNamespace(get_model_config=lambda name: SimpleNamespace(supports_vision=True) if name == "sci-vision-model" else None)
    monkeypatch.setattr(middleware_module, "get_app_config", lambda: dummy_app_cfg)
    monkeypatch.setattr(middleware_module, "create_chat_model", lambda name, thinking_enabled=False: _DummyVisionModel('{"images":[],"overall_conclusion":"x","overall_confidence":0.1}'))

    image_path = "/mnt/user-data/uploads/fig2.png"
    state = _state_with_view_image(
        image_paths=[image_path],
        viewed_images={image_path: {"base64": "YmFy", "mime_type": "image/png"}},
    )
    mw = middleware_module.ScientificImageReportMiddleware()

    result = mw.before_model(state, _runtime(model_name="main-text-model"))

    assert result is not None
    assert result.get("viewed_images") == {}
