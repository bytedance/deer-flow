"""Case-insensitive header writes for MCP tool-call interceptors.

HTTP field names are case-insensitive (RFC 9110 §5.1), but every dictionary on
the path from config to the wire is case-*sensitive*: ``build_server_params``
copies the operator's static ``headers`` spelling verbatim, and
``langchain_mcp_adapters`` merges interceptor overrides with a plain
``{**connection_headers, **override_headers}`` splat. So a static
``authorization`` and an interceptor-written ``Authorization`` do not collide —
both survive, httpx puts both on the wire, and a server reading the field with a
single-value accessor sees the *first* one, which is the static entry the
override was supposed to replace.

The credential interceptors therefore write header names through
:func:`apply_header_overrides`, which drops any key differing only in case and
emits the spelling the connection already uses, so the adapter's merge replaces
the static entry instead of duplicating it.

They also refuse to inject a credential that cannot travel as a header value
(:func:`illegal_header_value_reason`): httpx encodes values as Latin-1 and h11
rejects line breaks and surrounding whitespace, and both render the *full
value* into the exception message — which ``ToolErrorHandlingMiddleware`` then
copies into a model-visible ToolMessage, putting the secret in the prompt,
the checkpoint, and traces. Rejecting up front keeps the error message to the
credential's name.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

# What h11 refuses inside a field value (its field_vchar is ``[^\x00\s]``):
# NUL and the vertical-whitespace characters. SP/HTAB are legal separators
# *between* visible characters but not at either end.
_FORBIDDEN_HEADER_VALUE_CHARS = re.compile(r"[\x00\n\x0b\x0c\r]")


def illegal_header_value_reason(value: str) -> str | None:
    """Explain why *value* cannot be sent as an HTTP header value, or ``None``.

    Mirrors what the transport enforces — httpx encodes header values as
    Latin-1, h11 rejects NUL/vertical whitespace and leading or trailing
    SP/HTAB — without repeating the value, so callers can fail closed with a
    message that names the credential instead of leaking it.
    """
    try:
        value.encode("latin-1")
    except UnicodeEncodeError:
        return "contains characters outside Latin-1"
    if _FORBIDDEN_HEADER_VALUE_CHARS.search(value):
        return "contains a line break or another forbidden control character"
    if value != value.strip(" \t"):
        return "has leading or trailing whitespace"
    return None


def header_spellings(names: Iterable[str] | None) -> dict[str, str]:
    """Index header names by their lowercased form.

    Used to pin the spelling an interceptor should emit: the connection's own
    static ``headers`` keys, which the adapter merges the override into. A
    server that declares none passes ``None`` here rather than being special-
    cased at each call site.
    """
    return {name.lower(): name for name in (names or ())}


def apply_header_overrides(
    base: Mapping[str, str] | None,
    overrides: Mapping[str, str],
    *,
    spellings: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return ``base`` with ``overrides`` applied, case-insensitively.

    ``spellings`` maps a lowercased header name to the spelling to emit and
    takes priority over ``base``'s own keys, so an override lands on the static
    connection header it is meant to replace even when an earlier interceptor
    already wrote a differently-cased variant. Any key of ``base`` that differs
    from the emitted name only in case is removed, so the result never carries
    one header under two spellings.
    """
    merged = dict(base or {})
    lookup = dict(spellings or {})
    for key in merged:
        lookup.setdefault(key.lower(), key)

    for name, value in overrides.items():
        lowered = name.lower()
        canonical = lookup.get(lowered, name)
        for existing in [key for key in merged if key != canonical and key.lower() == lowered]:
            del merged[existing]
        merged[canonical] = value
    return merged
