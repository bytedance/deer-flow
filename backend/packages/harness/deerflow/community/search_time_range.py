"""Shared relative time-range contract for supported bundled web-search providers."""

from typing import Literal

type SearchTimeRange = Literal["day", "week", "month", "year"]

DDGS_TIMELIMIT_BY_TIME_RANGE: dict[SearchTimeRange, str] = {
    "day": "d",
    "week": "w",
    "month": "m",
    "year": "y",
}

BRAVE_FRESHNESS_BY_TIME_RANGE: dict[SearchTimeRange, str] = {
    "day": "pd",
    "week": "pw",
    "month": "pm",
    "year": "py",
}
