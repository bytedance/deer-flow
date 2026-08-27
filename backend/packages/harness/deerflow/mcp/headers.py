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
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping


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
