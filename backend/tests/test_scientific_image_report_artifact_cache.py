"""Audit-grade caching tests for ImageReport artifacts (sha256 keyed)."""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage

middleware_module = importlib.import_module("src.agents.middlewares.scientific_image_report_middleware")


def _runtime(*, model_name: str = "main-text-model") -> SimpleNamespace:
    return SimpleNamespace(context={"configurable": {"model_name": model_name}})


def _state_with_view_image(*, image_paths: list[str], viewed_images: dict[str, dict], outputs_path: str) -> dict:
    tool_calls = [{"name": "view_image", "args": {"image_path": p}, "id": f"tc-{i}"} for i, p in enumerate(image_paths, start=1)]
    ai = AIMessage(content="", id="ai-1", tool_calls=tool_calls)
    tool_messages = [ToolMessage(content="ok", id=f"tm-{i}", tool_call_id=f"tc-{i}") for i in range(1, len(image_paths) + 1)]
    return {
        "messages": [ai, *tool_messages],
        "viewed_images": viewed_images,
        "thread_data": {"outputs_path": outputs_path},
    }


class _DummyVisionModel:
    def __init__(self, response_text: str):
        self._response_text = response_text

    def invoke(self, _messages):
        return SimpleNamespace(content=self._response_text)


def test_cache_hit_skips_model_call_and_injects_index(tmp_path, monkeypatch):
    cfg = SimpleNamespace(
        inject_mode="index",
        enabled=True,
        model_name="sci-vision-model",
        artifact_subdir="scientific-vision/image-reports",
        cache_enabled=True,
        max_images=4,
        prompt_template="PROMPT",
        write_batch_artifact=True,
        include_raw_model_output_in_batch=True,
        write_index_artifact=True,
        clear_viewed_images_after_report=False,
    )
    monkeypatch.setattr(middleware_module, "get_scientific_vision_config", lambda: cfg)
    monkeypatch.setattr(
        middleware_module,
        "get_app_config",
        lambda: SimpleNamespace(get_model_config=lambda name: SimpleNamespace(supports_vision=True) if name == "sci-vision-model" else None),
    )

    # If cache works, create_chat_model must NOT be called.
    monkeypatch.setattr(middleware_module, "create_chat_model", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("vision model should not be called on cache hit")))

    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    image_path = "/mnt/user-data/uploads/fig-cache.png"
    viewed = {image_path: {"base64": "Zm9v", "mime_type": "image/png"}}
    image_sha256, byte_size = middleware_module._fingerprint_viewed_image(viewed[image_path])

    prompt_hash = middleware_module._sha256_text(cfg.prompt_template)
    analysis_sig = middleware_module._analysis_signature(report_model_name=cfg.model_name, prompt_hash=prompt_hash)

    report_physical, report_virtual, _image_index_physical = middleware_module._image_report_paths(
        outputs_dir=outputs_dir,
        artifact_subdir=cfg.artifact_subdir,
        image_sha256=image_sha256,
        analysis_sig=analysis_sig,
    )
    report_physical.parent.mkdir(parents=True, exist_ok=True)
    cached_payload = {
        "schema_version": middleware_module.IMAGE_REPORT_SCHEMA_VERSION,
        "generated_at": "2026-01-01T00:00:00Z",
        "analysis_signature": analysis_sig,
        "prompt_hash": prompt_hash,
        "report_model": cfg.model_name,
        "batch_id": "batch",
        "batch_artifact": None,
        "image": {
            "image_path": image_path,
            "image_sha256": image_sha256,
            "mime_type": "image/png",
            "byte_size": byte_size,
        },
        "report": {
            "image_path": image_path,
            "image_sha256": image_sha256,
            "image_type": "western_blot",
            "evidence": [{"id": "E1"}],
            "findings": [{"id": "F1", "claim": "cached finding", "evidence_ids": ["E1"], "confidence": 0.8}],
            "image_confidence": 0.8,
        },
        "overall": {"overall_conclusion": "ok", "overall_confidence": 0.6},
    }
    report_physical.write_text(json.dumps(cached_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    state = _state_with_view_image(image_paths=[image_path], viewed_images=viewed, outputs_path=str(outputs_dir))
    mw = middleware_module.ScientificImageReportMiddleware()

    result = mw.before_model(state, _runtime(model_name="main-text-model"))

    assert result is not None
    assert report_virtual in result.get("artifacts", [])
    injected = result["messages"][0]
    assert "<image_report" in str(injected.content)
    assert "cached finding" in str(injected.content)


def test_cache_miss_writes_report_and_batch_artifacts(tmp_path, monkeypatch):
    cfg = SimpleNamespace(
        inject_mode="index",
        enabled=True,
        model_name="sci-vision-model",
        artifact_subdir="scientific-vision/image-reports",
        cache_enabled=True,
        max_images=4,
        prompt_template="PROMPT",
        write_batch_artifact=True,
        include_raw_model_output_in_batch=True,
        write_index_artifact=True,
        clear_viewed_images_after_report=False,
    )
    monkeypatch.setattr(middleware_module, "get_scientific_vision_config", lambda: cfg)
    monkeypatch.setattr(
        middleware_module,
        "get_app_config",
        lambda: SimpleNamespace(get_model_config=lambda name: SimpleNamespace(supports_vision=True) if name == "sci-vision-model" else None),
    )

    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    image_path = "/mnt/user-data/uploads/fig-new.png"
    viewed = {image_path: {"base64": "YmFy", "mime_type": "image/png"}}
    image_sha256, _ = middleware_module._fingerprint_viewed_image(viewed[image_path])

    # Minimal batch JSON matching mapping-by-path behavior.
    response_json = (
        '{"schema_version":"deerflow.scientific_vision.batch.v1","images":[{"image_path":"'
        + image_path
        + '","image_type":"western_blot","evidence":[{"id":"E1"}],"findings":[{"id":"F1","claim":"new finding","evidence_ids":["E1"],"confidence":0.7}],"image_confidence":0.7}],"overall_conclusion":"ok","overall_confidence":0.6}'
    )
    monkeypatch.setattr(middleware_module, "create_chat_model", lambda name, thinking_enabled=False: _DummyVisionModel(response_json))

    state = _state_with_view_image(image_paths=[image_path], viewed_images=viewed, outputs_path=str(outputs_dir))
    mw = middleware_module.ScientificImageReportMiddleware()

    result = mw.before_model(state, _runtime(model_name="main-text-model"))

    assert result is not None
    # Should write per-image report file under outputs
    prompt_hash = middleware_module._sha256_text(cfg.prompt_template)
    analysis_sig = middleware_module._analysis_signature(report_model_name=cfg.model_name, prompt_hash=prompt_hash)
    report_physical, report_virtual, _ = middleware_module._image_report_paths(
        outputs_dir=outputs_dir,
        artifact_subdir=cfg.artifact_subdir,
        image_sha256=image_sha256,
        analysis_sig=analysis_sig,
    )
    assert report_physical.is_file()
    assert report_virtual in result.get("artifacts", [])
