"""Shared utility helpers for the Gateway layer."""

import hmac


def sanitize_log_param(value: str) -> str:
    """Strip control characters to prevent log injection."""
    return value.replace("\n", "").replace("\r", "").replace("\x00", "")


def constant_time_equals(a: str, b: str) -> bool:
    """Compare two secret strings in constant time, never raising on content.

    ``hmac.compare_digest`` raises ``TypeError`` for ``str`` operands holding
    non-ASCII characters, and headers, cookies and query values are client
    controlled, so a stray byte would turn a rejection into a 500. Comparing
    the UTF-8 encodings keeps the same result for ASCII input; ``surrogatepass``
    lets even a lone surrogate encode instead of raising.
    """
    return hmac.compare_digest(a.encode("utf-8", "surrogatepass"), b.encode("utf-8", "surrogatepass"))
