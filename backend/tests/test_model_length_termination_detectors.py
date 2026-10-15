"""Unit tests for provider length-termination detectors."""

from langchain_core.messages import AIMessage

from deerflow.agents.middlewares.model_length_termination_detectors import (
    AnthropicMaxTokensDetector,
    GeminiMaxTokensDetector,
    OpenAICompatibleLengthDetector,
    default_detectors,
)


def test_openai_compatible_length_detector_matches_finish_reason_length():
    hit = OpenAICompatibleLengthDetector().detect(
        AIMessage(
            content="partial",
            response_metadata={"finish_reason": "length"},
        )
    )

    assert hit is not None
    assert hit.detector == "openai_compatible_length"
    assert hit.reason_field == "finish_reason"
    assert hit.reason_value == "length"


def test_gemini_max_tokens_detector_matches_uppercase_finish_reason():
    hit = GeminiMaxTokensDetector().detect(
        AIMessage(
            content="partial",
            response_metadata={"finish_reason": "MAX_TOKENS"},
        )
    )

    assert hit is not None
    assert hit.detector == "gemini_max_tokens"
    assert hit.reason_field == "finish_reason"
    assert hit.reason_value == "MAX_TOKENS"


def test_anthropic_max_tokens_detector_matches_stop_reason():
    hit = AnthropicMaxTokensDetector().detect(
        AIMessage(
            content="partial",
            response_metadata={"stop_reason": "max_tokens"},
        )
    )

    assert hit is not None
    assert hit.detector == "anthropic_max_tokens"
    assert hit.reason_field == "stop_reason"
    assert hit.reason_value == "max_tokens"


def test_default_detectors_cover_openai_anthropic_and_gemini():
    names = [detector.name for detector in default_detectors()]

    assert names == [
        "openai_compatible_length",
        "anthropic_max_tokens",
        "gemini_max_tokens",
    ]
