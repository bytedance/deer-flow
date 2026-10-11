"""Tests for shared Gateway utility helpers."""

import pytest

from app.gateway.utils import constant_time_equals


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("token", "token", True),
        ("token", "other", False),
        ("tok\xe9n", "tok\xe9n", True),
        ("token", "tok\xe9n", False),
        ("tok\xe9n", "token", False),
        ("tok\ud800n", "token", False),
        ("", "", True),
    ],
)
def test_constant_time_equals_never_raises_on_non_ascii(a, b, expected):
    assert constant_time_equals(a, b) is expected
