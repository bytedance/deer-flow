from unittest.mock import Mock, patch

from deerflow.agents.lead_agent.agent import _create_summarization_middleware


class _Keep:
    def to_tuple(self):
        return ("messages", 20)


class _Config:
    enabled = True
    model_name = "model-masswork"
    trigger = None
    keep = _Keep()
    trim_tokens_to_summarize = None
    summary_prompt = None


def test_create_summarization_middleware_uses_model_alias_via_factory():
    fake_model = Mock(name="summary-model")

    with patch("deerflow.agents.lead_agent.agent.get_summarization_config", return_value=_Config()), \
        patch("deerflow.agents.lead_agent.agent.create_chat_model", return_value=fake_model) as create_model:
        middleware = _create_summarization_middleware()

    create_model.assert_called_once_with(name="model-masswork", thinking_enabled=False)
    assert middleware.model is fake_model
