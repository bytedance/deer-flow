"""Inbound channel file helpers reject payload shapes that int() cannot parse."""

from __future__ import annotations

import pytest

from app.channels.inbound_files import coerce_file_size


@pytest.mark.parametrize("value", ["²", "③", "½", "Ⅻ"])
def test_coerce_file_size_ignores_non_decimal_digit_strings(value: str) -> None:
    # "²" and "③" are isdigit() but not isdecimal(): int() raises on them, so
    # they exercise the isdigit -> isdecimal switch. "½" and "Ⅻ" are numeric
    # (Numeric_Type=Numeric) but not digits, so they also passed before the
    # change and are kept as extra regression coverage.
    assert coerce_file_size(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("12", 12),
        (" 12 ", 12),
        ("١٢", 12),
        (12, 12),
        (12.0, 12),
    ],
)
def test_coerce_file_size_accepts_decimal_values(value: object, expected: int) -> None:
    assert coerce_file_size(value) == expected


@pytest.mark.parametrize("value", [True, False, -1, 1.5, "", "abc", None, [], {}])
def test_coerce_file_size_rejects_other_shapes(value: object) -> None:
    assert coerce_file_size(value) is None
