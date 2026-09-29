"""Eager configuration-value validation shared by the client and its consumers.

A bad deployment must fail when the provider is constructed, not on the first
tool call or the first memory write. These helpers reject the shapes JSON and
YAML make easy to get wrong — ``bool`` where a number is meant (Python's ``bool``
is an ``int`` subclass), ``NaN`` from a JSON literal, a float where a count is
meant — and their messages name the offending field without echoing the value's
type-driven surprises.
"""

from __future__ import annotations

import math
from collections.abc import Mapping


def finite_float(
    name: str,
    value: object,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    exclusive: bool = False,
) -> float:
    """Return ``value`` as a finite float, or raise ``ValueError`` naming ``name``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    if minimum is not None and (number <= minimum if exclusive else number < minimum):
        raise ValueError(f"{name} must be {'>' if exclusive else '>='} {minimum:g}, got {number!r}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{name} must be <= {maximum:g}, got {number!r}")
    return number


def whole_number(name: str, value: object, *, minimum: int) -> int:
    """Return ``value`` as an int, rejecting ``bool`` and non-integers."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value!r}")
    return value


def defaulted_text(name: str, value: object, fallback: str) -> str:
    """Return ``value`` when configured, else ``fallback``; blank text is a config error."""
    if value is None:
        return fallback
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def credential_text(name: str, value: str) -> str:
    """Return a credential that can be sent as a header value, or raise naming ``name``.

    A key with surrounding whitespace (a secret mounted from a file, a quoted
    ``.env`` value, a shell ``$(cat ...)``) or a non-printable character passes the
    old non-empty check and then reaches h11, whose ``LocalProtocolError`` message
    carries the whole ``Bearer <key>`` header — and the guardrail middleware's
    ``logger.exception`` prints that cause chain. Rejecting the shape here turns a
    per-call credential leak into a construction-time error.

    Interior spaces are allowed because they are legal in a header value and leak
    nothing; every character outside printable ASCII (plus leading and trailing
    whitespace) is rejected. The message never echoes ``value``.
    """
    if value != value.strip() or any(not 0x20 <= ord(character) <= 0x7E for character in value):
        raise ValueError(f"{name} must be printable ASCII with no leading or trailing whitespace: check the configured key and the environment variable it reads (the value is never echoed here or in any error message)")
    return value


def criteria_entry(criteria: Mapping[object, object] | None, flag: bool) -> object:
    """Look up a ``criteria`` entry under either the YAML or the JSON spelling.

    A YAML ``criteria: {true: ..., false: ...}`` block parses its keys as booleans,
    while a JSON-typed config keeps them as the strings ``"true"``/``"false"``.
    """
    if criteria is None:
        return None
    if not isinstance(criteria, Mapping):
        raise ValueError("criteria must be a mapping with optional 'true'/'false' entries")
    for key in (flag, "true" if flag else "false"):
        if key in criteria:
            return criteria[key]
    return None


__all__ = ["credential_text", "criteria_entry", "defaulted_text", "finite_float", "whole_number"]
