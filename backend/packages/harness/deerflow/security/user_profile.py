"""Validation for account-owned display preferences."""

import unicodedata


def normalize_nickname(value: str | None) -> str | None:
    """An empty nickname clears the preference; keep names short and single-line."""
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("Nickname must be at most 80 characters")
    if any(unicodedata.category(character) in {"Cc", "Cs"} or character in "\u2028\u2029\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069" for character in value):
        raise ValueError("Nickname must be a single line without control characters")
    return value.strip() or None
