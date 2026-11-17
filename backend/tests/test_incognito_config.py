"""Incognito config bounds and the idle-window / absolute-lifetime relationship."""

import pytest
from pydantic import ValidationError

from deerflow.config.incognito_config import IncognitoThreadsConfig


def test_idle_window_beyond_the_absolute_lifetime_is_rejected() -> None:
    # A longer idle window would never take effect: the first activity pins
    # the deadline back to the ceiling, so the pair is a configuration error.
    with pytest.raises(ValidationError, match="must not exceed"):
        IncognitoThreadsConfig(
            idle_ttl_seconds=8 * 24 * 60 * 60,
            max_lifetime_seconds=7 * 24 * 60 * 60,
        )


def test_idle_window_equal_to_the_absolute_lifetime_is_allowed() -> None:
    config = IncognitoThreadsConfig(idle_ttl_seconds=3600, max_lifetime_seconds=3600)

    assert config.idle_ttl_seconds == 3600
    assert config.max_lifetime_seconds == 3600


def test_defaults_satisfy_the_relationship() -> None:
    config = IncognitoThreadsConfig()

    assert config.idle_ttl_seconds < config.max_lifetime_seconds


def test_idle_window_below_one_hour_is_rejected() -> None:
    # Renewal happens on runs only, so a shorter window can expire a chat
    # while the user is still writing, or right after a long run finishes.
    with pytest.raises(ValidationError, match="greater than or equal to 3600"):
        IncognitoThreadsConfig(idle_ttl_seconds=3599)


def test_lifetime_above_one_year_is_rejected() -> None:
    # Larger values overflow the datetime arithmetic that sets the deadline.
    with pytest.raises(ValidationError, match="less than or equal to 31536000"):
        IncognitoThreadsConfig(max_lifetime_seconds=365 * 24 * 60 * 60 + 1)


def test_boundary_values_are_accepted() -> None:
    shortest = IncognitoThreadsConfig(idle_ttl_seconds=3600, max_lifetime_seconds=3600)
    longest = IncognitoThreadsConfig(
        idle_ttl_seconds=365 * 24 * 60 * 60,
        max_lifetime_seconds=365 * 24 * 60 * 60,
    )

    assert shortest.idle_ttl_seconds == 3600
    assert longest.max_lifetime_seconds == 31536000
