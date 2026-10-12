"""Tests for tool progress configuration bounds."""

import pytest

from deerflow.config.tool_progress_config import ToolProgressConfig


class TestToolProgressConfigBounds:
    def test_default_min_word_count_applies(self):
        config = ToolProgressConfig()

        assert config.min_word_count_for_similarity == 10

    def test_accepts_custom_min_word_count(self):
        assert ToolProgressConfig(min_word_count_for_similarity=1).min_word_count_for_similarity == 1

    def test_rejects_zero_min_word_count(self):
        # 0 disables the short-content skip, so single-word tool results start
        # counting as near-duplicate "problems" and escalate to BLOCKED.
        with pytest.raises(ValueError, match="min_word_count_for_similarity"):
            ToolProgressConfig(min_word_count_for_similarity=0)

    def test_rejects_negative_min_word_count(self):
        with pytest.raises(ValueError, match="min_word_count_for_similarity"):
            ToolProgressConfig(min_word_count_for_similarity=-1)

    def test_rejects_boolean_min_word_count(self):
        # ``true``/``false`` in YAML must not silently coerce to 1/0.
        with pytest.raises(ValueError, match="min_word_count_for_similarity"):
            ToolProgressConfig(min_word_count_for_similarity=True)

        with pytest.raises(ValueError, match="min_word_count_for_similarity"):
            ToolProgressConfig(min_word_count_for_similarity=False)

    @pytest.mark.parametrize(
        "field",
        ["stagnation_threshold", "warn_escalation_count", "max_tracked_threads"],
    )
    def test_rejects_boolean_on_the_sibling_int_fields(self, field):
        # Same coercion, same consequence: lax mode turns ``true`` into 1, which
        # each field's ``ge=1`` bound accepts, so the typo loads silently and
        # retunes the guard (e.g. warning after the very first problem call, or an
        # LRU that tracks a single thread).
        with pytest.raises(ValueError, match=field):
            ToolProgressConfig(**{field: True})

        with pytest.raises(ValueError, match=field):
            ToolProgressConfig(**{field: False})

    @pytest.mark.parametrize(
        "field",
        ["stagnation_threshold", "warn_escalation_count", "min_word_count_for_similarity", "max_tracked_threads"],
    )
    def test_guard_leaves_ordinary_integers_alone(self, field):
        assert getattr(ToolProgressConfig(**{field: 2}), field) == 2

    @pytest.mark.parametrize(
        "field",
        ["stagnation_threshold", "warn_escalation_count", "max_tracked_threads"],
    )
    def test_existing_bounds_still_apply_to_the_sibling_fields(self, field):
        with pytest.raises(ValueError, match=field):
            ToolProgressConfig(**{field: 0})
