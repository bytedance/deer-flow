"""Unit tests for SafetyTerminationDetector built-ins."""

from langchain_core.messages import AIMessage

from deerflow.agents.middlewares.safety_termination_detectors import (
    AnthropicRefusalDetector,
    GeminiSafetyDetector,
    OpenAICompatibleContentFilterDetector,
    SafetyTermination,
    SafetyTerminationDetector,
    default_detectors,
)


def _ai(*, content="", tool_calls=None, response_metadata=None, additional_kwargs=None) -> AIMessage:
    return AIMessage(
        content=content,
        tool_calls=tool_calls or [],
        response_metadata=response_metadata or {},
        additional_kwargs=additional_kwargs or {},
    )


class TestOpenAICompatibleContentFilterDetector:
    def test_default_matches_content_filter(self):
        d = OpenAICompatibleContentFilterDetector()
        hit = d.detect(_ai(response_metadata={"finish_reason": "content_filter"}))
        assert hit is not None
        assert hit.detector == "openai_compatible_content_filter"
        assert hit.reason_field == "finish_reason"
        assert hit.reason_value == "content_filter"

    def test_case_insensitive_match(self):
        d = OpenAICompatibleContentFilterDetector()
        assert d.detect(_ai(response_metadata={"finish_reason": "CONTENT_FILTER"})) is not None

    def test_other_finish_reasons_pass_through(self):
        d = OpenAICompatibleContentFilterDetector()
        assert d.detect(_ai(response_metadata={"finish_reason": "stop"})) is None
        assert d.detect(_ai(response_metadata={"finish_reason": "tool_calls"})) is None
        assert d.detect(_ai(response_metadata={"finish_reason": "length"})) is None

    def test_missing_metadata_passes_through(self):
        d = OpenAICompatibleContentFilterDetector()
        assert d.detect(_ai()) is None

    def test_non_string_finish_reason_passes_through(self):
        # Some adapters may stash an enum or dict — must not raise.
        d = OpenAICompatibleContentFilterDetector()
        assert d.detect(_ai(response_metadata={"finish_reason": 42})) is None
        assert d.detect(_ai(response_metadata={"finish_reason": {"value": "content_filter"}})) is None

    def test_falls_back_to_additional_kwargs(self):
        # Legacy adapters surface finish_reason via additional_kwargs.
        d = OpenAICompatibleContentFilterDetector()
        hit = d.detect(_ai(additional_kwargs={"finish_reason": "content_filter"}))
        assert hit is not None

    def test_configurable_extra_values(self):
        # Chinese providers sometimes use bespoke tokens.
        d = OpenAICompatibleContentFilterDetector(finish_reasons=["content_filter", "sensitive", "violation"])
        assert d.detect(_ai(response_metadata={"finish_reason": "sensitive"})) is not None
        assert d.detect(_ai(response_metadata={"finish_reason": "violation"})) is not None
        # Original token still matches.
        assert d.detect(_ai(response_metadata={"finish_reason": "content_filter"})) is not None

    def test_carries_azure_content_filter_results(self):
        d = OpenAICompatibleContentFilterDetector()
        filter_results = {"hate": {"filtered": True, "severity": "high"}}
        hit = d.detect(
            _ai(
                response_metadata={
                    "finish_reason": "content_filter",
                    "content_filter_results": filter_results,
                },
            )
        )
        assert hit is not None
        assert hit.extras["content_filter_results"] == filter_results


class TestAnthropicRefusalDetector:
    def test_default_matches_refusal(self):
        hit = AnthropicRefusalDetector().detect(_ai(response_metadata={"stop_reason": "refusal"}))
        assert hit is not None
        assert hit.reason_field == "stop_reason"
        assert hit.reason_value == "refusal"

    def test_other_stop_reasons_pass_through(self):
        d = AnthropicRefusalDetector()
        assert d.detect(_ai(response_metadata={"stop_reason": "end_turn"})) is None
        assert d.detect(_ai(response_metadata={"stop_reason": "tool_use"})) is None
        assert d.detect(_ai(response_metadata={"stop_reason": "max_tokens"})) is None

    def test_anthropic_does_not_steal_finish_reason(self):
        # An OpenAI message must not accidentally trip the Anthropic detector.
        assert AnthropicRefusalDetector().detect(_ai(response_metadata={"finish_reason": "content_filter"})) is None


class TestGeminiSafetyDetector:
    def test_default_set_covers_documented_reasons(self):
        d = GeminiSafetyDetector()
        for reason in (
            # text safety
            "SAFETY",
            "BLOCKLIST",
            "PROHIBITED_CONTENT",
            "SPII",
            "RECITATION",
            # image safety
            "IMAGE_SAFETY",
            "IMAGE_PROHIBITED_CONTENT",
            "IMAGE_RECITATION",
        ):
            assert d.detect(_ai(response_metadata={"finish_reason": reason})) is not None, reason

    def test_normal_termination_passes_through(self):
        d = GeminiSafetyDetector()
        assert d.detect(_ai(response_metadata={"finish_reason": "STOP"})) is None
        # MAX_TOKENS / LANGUAGE / NO_IMAGE / OTHER / IMAGE_OTHER /
        # MALFORMED_FUNCTION_CALL / UNEXPECTED_TOOL_CALL are intentionally
        # excluded from the default set — they are either normal termination,
        # capability mismatches, too broad (OTHER), or tool-call protocol
        # errors. See GeminiSafetyDetector docstring.
        for reason in (
            "MAX_TOKENS",
            "LANGUAGE",
            "NO_IMAGE",
            "OTHER",
            "IMAGE_OTHER",
            "MALFORMED_FUNCTION_CALL",
            "UNEXPECTED_TOOL_CALL",
            "FINISH_REASON_UNSPECIFIED",
        ):
            assert d.detect(_ai(response_metadata={"finish_reason": reason})) is None, reason

    def test_carries_safety_ratings(self):
        ratings = [{"category": "HARM_CATEGORY_HARASSMENT", "probability": "HIGH"}]
        hit = GeminiSafetyDetector().detect(
            _ai(
                response_metadata={
                    "finish_reason": "SAFETY",
                    "safety_ratings": ratings,
                },
            )
        )
        assert hit is not None
        assert hit.extras["safety_ratings"] == ratings


class TestDefaultDetectorSet:
    def test_default_set_returns_three_detectors(self):
        dets = default_detectors()
        names = {d.name for d in dets}
        assert names == {"openai_compatible_content_filter", "anthropic_refusal", "gemini_safety"}

    def test_default_set_returns_fresh_list(self):
        # Caller mutation must not affect later calls.
        first = default_detectors()
        first.clear()
        second = default_detectors()
        assert len(second) == 3


class TestProtocolConformance:
    def test_builtins_satisfy_protocol(self):
        for d in default_detectors():
            assert isinstance(d, SafetyTerminationDetector)

    def test_safety_termination_is_frozen(self):
        t = SafetyTermination(detector="x", reason_field="finish_reason", reason_value="content_filter")
        try:
            t.detector = "y"  # type: ignore[misc]
        except Exception:
            return
        raise AssertionError("SafetyTermination should be frozen")
