"""Tests for tool progress configuration."""

import pytest

from deerflow.agents.middlewares.tool_progress_middleware import is_near_duplicate, word_set
from deerflow.config.tool_progress_config import ToolProgressConfig


class TestToolProgressConfig:
    def test_defaults_match_middleware_defaults(self):
        config = ToolProgressConfig()

        assert config.enabled is False
        assert config.stagnation_threshold == 3
        assert config.warn_escalation_count == 2
        assert config.jaccard_similarity_threshold == 0.8
        assert config.min_word_count_for_similarity == 10
        assert config.max_tracked_threads == 100

    def test_accepts_custom_values(self):
        config = ToolProgressConfig(
            enabled=True,
            min_word_count_for_similarity=20,
            jaccard_similarity_threshold=0.6,
        )

        assert config.enabled is True
        assert config.min_word_count_for_similarity == 20
        assert config.jaccard_similarity_threshold == 0.6

    def test_accepts_numeric_string(self):
        config = ToolProgressConfig.model_validate({"min_word_count_for_similarity": "25"})

        assert config.min_word_count_for_similarity == 25

    def test_rejects_zero(self):
        with pytest.raises(ValueError, match="min_word_count_for_similarity"):
            ToolProgressConfig(min_word_count_for_similarity=0)

    @pytest.mark.parametrize("value", [-1, -5, -100])
    def test_rejects_negative(self, value):
        with pytest.raises(ValueError, match="min_word_count_for_similarity"):
            ToolProgressConfig(min_word_count_for_similarity=value)

    @pytest.mark.parametrize("value", [True, False])
    def test_rejects_boolean(self, value):
        with pytest.raises(ValueError, match="boolean"):
            ToolProgressConfig(min_word_count_for_similarity=value)


class TestNearDuplicateGuard:
    def test_short_content_still_skips_with_valid_min_words(self):
        # One-word result is shorter than the minimum, so it is never flagged.
        current = word_set("alpha")
        recent = [current]

        assert is_near_duplicate(current, recent, 0.8, 10) is False

    def test_matching_long_content_flagged(self):
        # A long, identical result above the minimum is correctly flagged.
        current = word_set("alpha bravo charlie delta echo")
        recent = [current]

        assert is_near_duplicate(current, recent, 0.8, 1) is True
