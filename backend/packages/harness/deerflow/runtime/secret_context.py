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

# Reserved sub-key of the run context that holds request-scoped secrets.
SECRETS_CONTEXT_KEY = "secrets"


def extract_request_secrets(context: Any) -> dict[str, str]:
    """Return the request-scoped secrets mapping from a run context, or ``{}``.

    Only string-keyed, string-valued entries are kept; anything else is ignored
    so a malformed carrier can never crash secret resolution or injection.
    """
    if not isinstance(context, dict):
        return {}
    raw = context.get(SECRETS_CONTEXT_KEY)
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if isinstance(key, str) and isinstance(value, str)}
