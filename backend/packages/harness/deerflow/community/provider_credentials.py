"""Single owner for the credential rules the bundled retrieval providers share.

``community/lightrag`` and ``community/ragflow`` are two read-only retrieval
providers that each carried a byte-identical copy of three rules: how a
configured API key is unwrapped from a ``SecretStr`` and normalized, how that
key is scrubbed out of text before it reaches a log line or a tool error, and
why a configured base URL must not carry userinfo. Two owners for one rule means
a fix to one provider can silently leave the other one leaking.

The marker and the message are module constants because the strings are part of
the contract: provider tests and operators' log grep patterns assert on them.
"""

from __future__ import annotations

from pydantic import AnyHttpUrl, SecretStr

REDACTION_MARKER = "[REDACTED]"
URL_USERINFO_ERROR = "base_url must not contain username or password information"


def resolve_api_key(raw: str | SecretStr | None) -> str | None:
    """Return the configured key with surrounding whitespace removed.

    Blank or absent reads as ``None``: a missing key is not an error, it is an
    unconfigured provider. Unwrapping happens only here, so no provider can end
    up comparing (or printing) the repr of a ``SecretStr`` instead of its value.
    """
    value = raw.get_secret_value() if isinstance(raw, SecretStr) else raw
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def redact_secret(value: object, secret: str | None) -> str:
    """Stringify ``value`` and replace every occurrence of ``secret``.

    Applied to error text, provider payloads and configured base URLs alike, so
    a key embedded in a URL or an exception message cannot reach a log. A
    ``None`` secret leaves the text untouched rather than raising.
    """
    text = str(value)
    if secret:
        text = text.replace(secret, REDACTION_MARKER)
    return text


def reject_url_userinfo(value: AnyHttpUrl) -> AnyHttpUrl:
    """Reject a configured base URL that smuggles credentials in userinfo."""
    if value.username is not None or value.password is not None:
        raise ValueError(URL_USERINFO_ERROR)
    return value
