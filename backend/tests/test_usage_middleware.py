from types import SimpleNamespace

from src.agents.middlewares.usage_middleware import extract_usage_delta


def test_extract_usage_delta_from_usage_metadata() -> None:
    message = SimpleNamespace(
        type="ai",
        response_metadata={"model_name": "gpt-5"},
        tool_calls=[{"name": "web_search"}, {"name": "web_search"}],
        usage_metadata={
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
        },
    )

    assert extract_usage_delta(message) == {
        "models": [
            {
                "model": "gpt-5",
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "total_tokens": 18,
            }
        ],
        "tool_calls": {"web_search": 2},
    }


def test_extract_usage_delta_from_response_metadata_token_usage() -> None:
    message = SimpleNamespace(
        type="ai",
        usage_metadata=None,
        response_metadata={
            "model": "gpt-4o-mini",
            "token_usage": {
                "prompt_tokens": 20,
                "completion_tokens": 5,
            }
        },
    )

    assert extract_usage_delta(message) == {
        "models": [
            {
                "model": "gpt-4o-mini",
                "prompt_tokens": 20,
                "completion_tokens": 5,
                "total_tokens": 25,
            }
        ],
        "tool_calls": {},
    }


def test_extract_usage_delta_with_tool_calls_only() -> None:
    message = SimpleNamespace(
        type="ai",
        usage_metadata=None,
        response_metadata={"model_name": "gpt-5"},
        tool_calls=[{"name": "web_search"}, {"name": "read_file"}, {"name": "web_search"}],
    )

    assert extract_usage_delta(message) == {
        "models": [],
        "tool_calls": {
            "web_search": 2,
            "read_file": 1,
        },
    }


def test_extract_usage_delta_returns_none_for_non_ai() -> None:
    message = SimpleNamespace(type="human", usage_metadata={"input_tokens": 1})
    assert extract_usage_delta(message) is None
