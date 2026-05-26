"""Shared pagination helpers for gateway routers."""

from __future__ import annotations


def trim_run_message_page(rows: list[dict], *, limit: int, after_seq: int | None) -> tuple[list[dict], bool]:
    """Trim a ``limit + 1`` run message page without dropping visible rows.

    ``rows`` must be ordered oldest to newest. When an extra sentinel row is
    present, latest-page and ``before_seq`` pagination receive the sentinel on
    the older side, while ``after_seq`` pagination receives it on the newer side.
    """
    has_more = len(rows) > limit
    if not has_more:
        return rows, False

    if after_seq is not None:
        return rows[:limit], True

    return rows[-limit:], True
