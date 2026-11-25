"""Database-clock expressions shared by repositories that judge expiries.

Deployments run several Gateway instances, and their host clocks can drift
independently of each other. A deadline stored by one instance must be judged
against the same clock that other instances read, so leases and grants compare
with the database statement clock instead of ``time()``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Double, cast, extract, func

#: Julian day number of the Unix epoch (1970-01-01T00:00:00Z).
_UNIX_EPOCH_JULIAN_DAY = 2440587.5
_SECONDS_PER_DAY = 86400.0


def db_now(dialect: str) -> Any:
    """The current time of the statement, in epoch seconds, from the database clock.

    SQLite evaluates ``'now'`` once per statement step, PostgreSQL's
    ``statement_timestamp()`` is fixed for the statement, so every reference in
    one statement sees the same instant.
    """
    if dialect == "postgresql":
        return cast(extract("epoch", func.statement_timestamp()), Double)
    return (func.julianday("now") - _UNIX_EPOCH_JULIAN_DAY) * _SECONDS_PER_DAY
