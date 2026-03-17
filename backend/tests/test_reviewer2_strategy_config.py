"""Tests for reviewer2 strategy configuration loading and normalization."""

from __future__ import annotations

from src.config.reviewer2_strategy_config import (
    get_reviewer2_strategy_config,
    load_reviewer2_strategy_config_from_dict,
    set_reviewer2_strategy_config,
)


def test_load_reviewer2_strategy_config_normalizes_keys_and_dedupes_styles():
    previous = get_reviewer2_strategy_config().model_copy(deep=True)
    try:
        load_reviewer2_strategy_config_from_dict(
            {
                "default_styles": ["statistical_tyrant", "statistical_tyrant"],
                "venue_style_overrides": {
                    "NeurIPS": ["statistical_tyrant", "methodology_fundamentalist", "statistical_tyrant"],
                },
                "ab_variant_a_styles": ["methodology_fundamentalist", "methodology_fundamentalist"],
                "ab_variant_b_styles": ["domain_traditionalist", "domain_traditionalist"],
                "ab_default_variant": "A",
            }
        )
        cfg = get_reviewer2_strategy_config()
        assert cfg.default_styles == ["statistical_tyrant"]
        assert "neurips" in cfg.venue_style_overrides
        assert cfg.venue_style_overrides["neurips"] == ["statistical_tyrant", "methodology_fundamentalist"]
        assert cfg.ab_variant_a_styles == ["methodology_fundamentalist"]
        assert cfg.ab_variant_b_styles == ["domain_traditionalist"]
        assert cfg.ab_default_variant == "A"
    finally:
        set_reviewer2_strategy_config(previous)
