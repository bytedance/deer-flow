import pytest
import yaml
from pydantic import ValidationError

from deerflow.config.model_config import ModelConfig


def _make_model(**overrides) -> ModelConfig:
    return ModelConfig(
        name="openai-responses",
        display_name="OpenAI Responses",
        description=None,
        use="langchain_openai:ChatOpenAI",
        model="gpt-5",
        **overrides,
    )


def test_responses_api_fields_are_declared_in_model_schema():
    assert "use_responses_api" in ModelConfig.model_fields
    assert "output_version" in ModelConfig.model_fields


def test_responses_api_fields_round_trip_in_model_dump():
    config = _make_model(
        api_key="$OPENAI_API_KEY",
        use_responses_api=True,
        output_version="responses/v1",
    )

    dumped = config.model_dump(exclude_none=True)

    assert dumped["use_responses_api"] is True
    assert dumped["output_version"] == "responses/v1"


def test_context_window_round_trips_when_positive():
    assert _make_model(context_window=128_000).context_window == 128_000


@pytest.mark.parametrize("context_window", [0, -1])
def test_context_window_rejects_non_positive_capacity(context_window):
    with pytest.raises(ValidationError, match="context_window"):
        _make_model(context_window=context_window)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        (0, 0.0),
        (240, 240.0),
        (1.5, 1.5),
        ("240", 240.0),
    ],
)
def test_stream_chunk_timeout_accepts_finite_non_negative_seconds(raw, expected):
    """Null keeps the 240s factory default, 0 still disables, and a ``$VAR`` string still parses."""
    assert _make_model(stream_chunk_timeout=raw).stream_chunk_timeout == expected


@pytest.mark.parametrize(
    "raw",
    [
        True,
        False,
        yaml.safe_load("on"),
        yaml.safe_load("off"),
        yaml.safe_load("yes"),
        yaml.safe_load("no"),
        -1,
        -0.1,
        float("inf"),
        float("-inf"),
        float("nan"),
        yaml.safe_load(".inf"),
        yaml.safe_load(".nan"),
        "1e999",
        yaml.safe_load("1e999"),
        "inf",
        "nan",
    ],
)
def test_stream_chunk_timeout_rejects_values_that_disable_or_collapse_the_watchdog(raw):
    """These spellings used to load and then break streaming.

    YAML ``on``/``yes`` became 1.0, so every async stream died after one second.
    ``off``/``no`` became 0 and disabled the watchdog. ``inf`` (including the
    string ``1e999``, which is how PyYAML loads that token) never fires
    ``asyncio.wait_for``. A negative is rewritten by langchain-openai to its
    own 120s default instead of DeerFlow's 240s.
    """
    with pytest.raises(ValidationError, match="stream_chunk_timeout"):
        _make_model(stream_chunk_timeout=raw)
