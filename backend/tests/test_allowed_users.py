"""Shared allowlist warnings preserve literal IDs and channel opt-in."""

import logging
from typing import Any

import pytest

from app.channels.allowed_users import parse_allowed_users

logger = logging.getLogger(__name__)


def parse_string_id(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry.strip() or None
    return None


@pytest.mark.parametrize("channel_name, valid_id_name", [("qq", "OpenID"), ("WeChat", "user ID")])
@pytest.mark.parametrize("separator", [",", ", ", " ", "\t", "\n", "\u2003"])
def test_opted_in_scalar_separator_warning_preserves_literal_id(channel_name, valid_id_name, separator, caplog):
    literal_id = f"alice{separator}bob"
    with caplog.at_level(logging.WARNING, logger=logger.name):
        result = parse_allowed_users(
            literal_id,
            parse_user_id=parse_string_id,
            logger=logger,
            channel_name=channel_name,
            expected_id="a string ID",
            valid_id_name=valid_id_name,
            warn_on_scalar_separators=True,
        )

    assert result == frozenset({literal_id})
    assert len(caplog.records) == 1
    warning = caplog.records[0]
    assert warning.levelno == logging.WARNING
    assert f"[{channel_name}]" in warning.message
    assert f"one literal {valid_id_name}" in warning.message
    assert "YAML list" in warning.message
    assert "alice" not in warning.message
    assert "bob" not in warning.message


def test_scalar_separator_warning_is_opt_in(caplog):
    result = parse_allowed_users(
        "alice,bob",
        parse_user_id=parse_string_id,
        logger=logger,
        channel_name="other",
        expected_id="a string ID",
    )

    assert result == frozenset({"alice,bob"})
    assert caplog.records == []


@pytest.mark.parametrize(
    "allowed_users, expected",
    [
        ("alice", frozenset({"alice"})),
        (" \talice\n ", frozenset({"alice"})),
        (" \t\n ", None),
        (None, None),
        ([], None),
        (["alice,bob"], frozenset({"alice,bob"})),
        (("alice bob",), frozenset({"alice bob"})),
        ({"alice\tbob"}, frozenset({"alice\tbob"})),
        (frozenset({"alice\nbob"}), frozenset({"alice\nbob"})),
    ],
)
def test_opted_in_warning_only_checks_scalar_separators(allowed_users, expected, caplog):
    result = parse_allowed_users(
        allowed_users,
        parse_user_id=parse_string_id,
        logger=logger,
        channel_name="other",
        expected_id="a string ID",
        warn_on_scalar_separators=True,
    )

    assert result == expected
    assert caplog.records == []
