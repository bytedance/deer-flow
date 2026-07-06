"""Request-scoped secret carrier in the run context (issue #3861).

Callers pass per-request secrets out-of-band in ``config.context.secrets`` — a
mapping of name -> value. The value never enters the prompt, tool arguments, or
the executed command string; it is injected as an environment variable into a
skill's sandbox subprocess only when an activated skill declares it via the
``required-secrets`` frontmatter field.

This module centralises the reserved key name and safe extraction so the carrier
contract lives in one place, consumed by the skill-activation middleware (to
build the per-turn injection set) and the tracing redactor (to strip it from
trace payloads).
"""

from __future__ import annotations

from typing import Any

# Reserved sub-key of the run context that holds request-scoped secrets supplied
# by the caller. Source of truth for what a skill *may* receive.
SECRETS_CONTEXT_KEY = "secrets"

# Reserved sub-key holding the secrets resolved for the currently activated skill
# (binding point A). Written by the skill-activation middleware, read by the bash
# tool. Both reserved keys are stripped from trace payloads (see tracing redactor).
ACTIVE_SECRETS_CONTEXT_KEY = "__active_skill_secrets"


def _string_pairs(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if isinstance(key, str) and isinstance(value, str)}


def extract_request_secrets(context: Any) -> dict[str, str]:
    """Return the caller-supplied request-scoped secrets mapping, or ``{}``.

    Only string-keyed, string-valued entries are kept; anything else is ignored
    so a malformed carrier can never crash secret resolution or injection.
    """
    if not isinstance(context, dict):
        return {}
    return _string_pairs(context.get(SECRETS_CONTEXT_KEY))


def read_active_secrets(context: Any) -> dict[str, str]:
    """Return the secrets resolved for the active skill (the per-run injection
    set), or ``{}``. Read by the bash tool to build the subprocess env."""
    if not isinstance(context, dict):
        return {}
    return _string_pairs(context.get(ACTIVE_SECRETS_CONTEXT_KEY))


# Private run-context keys the skill-activation middleware uses to carry secret
# bindings across a run. Only ``secrets`` / ``__active_skill_secrets`` hold
# values; the binding-source and audit keys hold names only. All are listed so
# the redaction allowlist stays a complete guard even if a future edit starts
# storing a value under one of the name-only keys.
_SLASH_SECRET_SOURCE_KEY = "__slash_skill_secret_source"
_SECRETS_BINDING_AUDIT_KEY = "__skill_secrets_binding_audit"

# Run-context keys whose values are request-scoped secrets and must be stripped
# before a context mapping is serialized anywhere observable (traces, logs).
REDACTED_CONTEXT_KEYS = frozenset(
    {
        SECRETS_CONTEXT_KEY,
        ACTIVE_SECRETS_CONTEXT_KEY,
        _SLASH_SECRET_SOURCE_KEY,
        _SECRETS_BINDING_AUDIT_KEY,
    }
)


def redact_secret_context_keys(context: Any) -> Any:
    """Return a shallow copy of ``context`` with secret-bearing keys removed.

    Defensive helper for any code path that serializes the run context into an
    observable surface. DeerFlow's own trace-metadata builder never copies the
    context, so this is belt-and-suspenders for future call sites and custom
    tracer configurations.
    """
    if not isinstance(context, dict):
        return context
    return {key: value for key, value in context.items() if key not in REDACTED_CONTEXT_KEYS}


def redact_config_secrets(config: Any) -> Any:
    """Return a copy of a run config safe to persist or echo back to clients.

    The request config (``body.config``) is stored verbatim on the run record
    (``runs.kwargs_json``) and echoed by the run API. Strip the secret-bearing
    keys from its ``context`` so a request-scoped secret is never persisted or
    returned, while the live config that drives the run (built separately) keeps
    them. Non-dict / context-less configs pass through unchanged.
    """
    if not isinstance(config, dict):
        return config
    context = config.get("context")
    if not isinstance(context, dict):
        return config
    redacted = dict(config)
    redacted["context"] = redact_secret_context_keys(context)
    return redacted
