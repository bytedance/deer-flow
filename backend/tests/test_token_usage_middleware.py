from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from deerflow.agents.middlewares.token_usage_middleware import TokenUsageMiddleware


def test_after_model_logs_usage_metadata_counts():
    middleware = TokenUsageMiddleware()
    state = {
        "messages": [
            AIMessage(
                content="done",
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
            )
        ]
    }

    with patch("deerflow.agents.middlewares.token_usage_middleware.logger.info") as info_mock:
        result = middleware.after_model(state=state, runtime=MagicMock())

    assert result is None
    info_mock.assert_called_once_with(
        "LLM token usage: input=%s output=%s total=%s",
        10,
        5,
        15,
    )
