"""Shared scalar-or-list parsing for channel ID configuration."""

from __future__ import annotations

import logging
from collections.abc import Callable, Hashable
from typing import Any


def _parse_id_entries(
    value: Any,
    *,
    logger: logging.Logger,
    channel_name: str,
    key_name: str,
    valid_id_name: str,
    warn_on_scalar_separators: bool,
) -> list[Any]:
    """Normalize config shape without splitting scalar IDs or iterating mappings."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return []
    if warn_on_scalar_separators and isinstance(value, str) and ("," in value or any(char.isspace() for char in value.strip())):
        logger.warning(
            "[%s] %s is a scalar string containing separators; treating it as one literal %s. Use a YAML list for multiple IDs",
            channel_name,
            key_name,
            valid_id_name,
        )
    return list(value) if isinstance(value, (list, tuple, set, frozenset)) else [value]


def parse_channel_ids(
    value: Any,
    *,
    logger: logging.Logger,
    channel_name: str,
    key_name: str,
    warn_on_scalar_separators: bool = False,
) -> frozenset[str]:
    """Return trimmed literal channel IDs; empty config grants no exemptions.

    These IDs are compared as strings by the connector. An unusable literal
    never matches, so it leaves the connector's mention requirement in force.
    """
    entries = _parse_id_entries(
        value,
        logger=logger,
        channel_name=channel_name,
        key_name=key_name,
        valid_id_name="channel id",
        warn_on_scalar_separators=warn_on_scalar_separators,
    )
    return frozenset(text for text in (str(entry).strip() for entry in entries) if text)


def parse_allowed_users[UserId: Hashable](
    allowed_users: Any,
    *,
    parse_user_id: Callable[[Any], UserId | None],
    logger: logging.Logger,
    channel_name: str,
    expected_id: str,
    valid_id_name: str = "user ID",
    warn_on_scalar_separators: bool = False,
) -> frozenset[UserId] | None:
    """Return ``None`` for an unset/empty allowlist, or its valid user IDs.

    Scalars are single entries; mappings must not authorize their keys. The
    channel's coercer validates each entry. Invalid entries warn and are dropped,
    but a configured value with no valid entry returns an empty set and logs an
    error, so callers deny everyone instead of silently removing the restriction.
    String-ID channels can opt into a scalar-separator warning without splitting
    the ID; surrounding whitespace alone does not trigger it.
    """
    entries = _parse_id_entries(
        allowed_users,
        logger=logger,
        channel_name=channel_name,
        key_name="allowed_users",
        valid_id_name=valid_id_name,
        warn_on_scalar_separators=warn_on_scalar_separators,
    )
    if not entries:
        return None

    user_ids: set[UserId] = set()
    for entry in entries:
        user_id = parse_user_id(entry)
        if user_id is None:
            logger.warning("[%s] Ignoring allowed_users entry %r: expected %s; list several IDs as a YAML list", channel_name, entry, expected_id)
        else:
            user_ids.add(user_id)
    if not user_ids:
        logger.error("[%s] allowed_users has no valid %s; denying every user until it is fixed", channel_name, valid_id_name)
    return frozenset(user_ids)


def parse_string_or_int_user_id(entry: Any) -> str | None:
    """A user ID from a non-blank string or an integer, else ``None``.

    An unquoted YAML number keeps matching its string form. Quote IDs with
    leading zeros.
    """
    if isinstance(entry, bool):
        # bool is an int subclass: ``true`` must not become the user "True".
        return None
    if isinstance(entry, int):
        return str(entry)
    if isinstance(entry, str):
        return entry.strip() or None
    return None
