"""Exercise the shipped Gemini example through the model factory and OpenAI SDK."""

import json
from pathlib import Path

import httpx
import pytest
import yaml

from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.models.factory import create_chat_model


@pytest.mark.parametrize("thinking_enabled,effort", [(True, None), (True, "medium"), (True, "high"), (False, "minimal")])
def test_gemini_example_request(thinking_enabled, effort):
    example = (Path(__file__).resolve().parents[2] / "config.example.yaml").read_text(encoding="utf-8")
    block = example.split("  # Example: Gemini model via ", 1)[1].split("\n\n", 1)[0]
    lines = block[block.index("  # - name:") :].splitlines()
    settings = yaml.safe_load("\n".join(line.removeprefix("  # ") for line in lines))[0]
    settings["api_key"] = "test-key"
    config = AppConfig(models=[ModelConfig(**settings)], sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 0, "model": settings["model"], "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = create_chat_model(app_config=config, attach_tracing=False, thinking_enabled=thinking_enabled, reasoning_effort=effort, http_client=client)
        assert model.invoke("Hello").content == "OK"

    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    assert "thinking" not in payload
    assert payload.get("reasoning_effort") == effort
    if effort is None:
        assert "reasoning_effort" not in payload
    assert payload["model"] == "gemini-3.1-pro-preview"
    assert str(requests[0].url) == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
