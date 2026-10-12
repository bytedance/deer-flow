"""Shared fail-closed parsing for channel user allowlists."""

from __future__ import annotations

import logging
from collections.abc import Callable, Hashable
from typing import Any


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
    if allowed_users is None or (isinstance(allowed_users, str) and not allowed_users.strip()):
        return None
    if warn_on_scalar_separators and isinstance(allowed_users, str) and ("," in allowed_users or any(char.isspace() for char in allowed_users.strip())):
        logger.warning(
            "[%s] allowed_users is a scalar string containing separators; treating it as one literal %s. Use a YAML list for multiple IDs",
            channel_name,
            valid_id_name,
        )
    entries = list(allowed_users) if isinstance(allowed_users, (list, tuple, set, frozenset)) else [allowed_users]
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
