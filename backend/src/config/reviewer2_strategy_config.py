"""Configuration for Reviewer2 persona strategy defaults and A/B presets."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Reviewer2Style = Literal["statistical_tyrant", "methodology_fundamentalist", "domain_traditionalist"]
PeerReviewABVariant = Literal["off", "A", "B"]


def _dedup_styles(styles: list[Reviewer2Style]) -> list[Reviewer2Style]:
    deduped: list[Reviewer2Style] = []
    seen: set[str] = set()
    for style in styles:
        if style in seen:
            continue
        seen.add(style)
        deduped.append(style)
    return deduped


class Reviewer2StrategyConfig(BaseModel):
    """Runtime strategy config for reviewer2 persona selection."""

    default_styles: list[Reviewer2Style] = Field(
        default_factory=lambda: ["statistical_tyrant", "methodology_fundamentalist"],
        description="Global fallback reviewer2 personas when venue-specific mapping misses.",
    )
    venue_style_overrides: dict[str, list[Reviewer2Style]] = Field(
        default_factory=lambda: {
            "nature": ["methodology_fundamentalist", "domain_traditionalist"],
            "cell": ["methodology_fundamentalist", "domain_traditionalist"],
            "neurips": ["statistical_tyrant", "methodology_fundamentalist"],
            "icml": ["statistical_tyrant", "methodology_fundamentalist"],
        },
        description="Venue -> reviewer2 persona defaults. Keys are matched case-insensitively.",
    )
    ab_enabled: bool = Field(
        default=True,
        description="Enable A/B preset switch for combined round-count + persona strategy experiments.",
    )
    ab_default_variant: PeerReviewABVariant = Field(
        default="off",
        description="Optional global default A/B arm (off/A/B). Applied when request does not specify variant.",
    )
    ab_variant_a_max_rounds: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Peer-review rounds for A arm.",
    )
    ab_variant_a_styles: list[Reviewer2Style] = Field(
        default_factory=lambda: ["statistical_tyrant", "methodology_fundamentalist"],
        description="Reviewer2 persona combination for A arm.",
    )
    ab_variant_b_max_rounds: int = Field(
        default=4,
        ge=1,
        le=5,
        description="Peer-review rounds for B arm.",
    )
    ab_variant_b_styles: list[Reviewer2Style] = Field(
        default_factory=lambda: ["statistical_tyrant", "methodology_fundamentalist", "domain_traditionalist"],
        description="Reviewer2 persona combination for B arm.",
    )
    ab_auto_split_enabled: bool = Field(
        default=False,
        description="Whether to auto-assign A/B arm by thread_id hash when request does not force A/B/off.",
    )
    ab_auto_split_ratio_a: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Traffic ratio assigned to arm A under hash split (remaining goes to arm B).",
    )
    ab_auto_split_salt: str = Field(
        default="reviewer2-ab-v1",
        description="Salt used for deterministic thread_id hashing when auto split is enabled.",
    )
    ab_metrics_enabled: bool = Field(
        default=True,
        description="Persist and aggregate peer-review A/B outcome metrics.",
    )
    ab_metrics_max_recent_runs: int = Field(
        default=120,
        ge=20,
        le=1000,
        description="How many recent run records are retained in aggregated A/B metrics artifact.",
    )


_reviewer2_strategy_config: Reviewer2StrategyConfig = Reviewer2StrategyConfig()


def get_reviewer2_strategy_config() -> Reviewer2StrategyConfig:
    """Get current reviewer2 strategy configuration."""
    return _reviewer2_strategy_config


def set_reviewer2_strategy_config(config: Reviewer2StrategyConfig) -> None:
    """Set reviewer2 strategy configuration."""
    global _reviewer2_strategy_config
    normalized_map: dict[str, list[Reviewer2Style]] = {}
    for venue, styles in (config.venue_style_overrides or {}).items():
        key = str(venue).strip().lower()
        if not key:
            continue
        normalized_map[key] = _dedup_styles(styles)
    _reviewer2_strategy_config = config.model_copy(
        update={
            "default_styles": _dedup_styles(config.default_styles),
            "venue_style_overrides": normalized_map,
            "ab_variant_a_styles": _dedup_styles(config.ab_variant_a_styles),
            "ab_variant_b_styles": _dedup_styles(config.ab_variant_b_styles),
        }
    )


def load_reviewer2_strategy_config_from_dict(config_dict: dict) -> None:
    """Load reviewer2 strategy configuration from a dictionary."""
    parsed = Reviewer2StrategyConfig(**(config_dict or {}))
    set_reviewer2_strategy_config(parsed)
