from __future__ import annotations

from langchain_core.messages import HumanMessage

from deerflow.models.rvllm_provider import RvllmChatModel


def _make_model(**kwargs) -> RvllmChatModel:
    params = {
        "model": "gemma-4-e4b-it",
        "api_key": "dummy",
        "base_url": "http://localhost:18086/v1",
    }
    params.update(kwargs)
    return RvllmChatModel(**params)


def test_rvllm_provider_llm_type():
    assert _make_model()._llm_type == "rvllm-openai-compatible"


def test_rvllm_provider_defaults_to_greedy_decoding():
    # rvllm-server's spec decode preserves greedy token identity, so the
    # provider keeps agent runs deterministic by default.
    assert _make_model().temperature == 0.0


def test_rvllm_provider_preserves_explicit_temperature():
    assert _make_model(temperature=0.7).temperature == 0.7


def test_rvllm_provider_emits_greedy_temperature_in_request_payload():
    payload = _make_model()._get_request_payload([HumanMessage(content="Hello")])
    assert payload["temperature"] == 0.0
