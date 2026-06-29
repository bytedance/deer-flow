"""Environment-variable policy for sandbox command execution (issue #3861).

Skill scripts run as sandbox subprocesses. By default a subprocess inherits the
Gateway process's entire ``os.environ`` — which holds platform credentials
(``OPENAI_API_KEY``, tracing keys, community-provider keys, ...). That makes any
scoped request-secret injection pointless: a script could simply read those
inherited platform secrets. This module scrubs secret-looking variables from the
inherited environment before request-scoped secrets are layered on top.

The pattern set mirrors codex's ``*KEY*/*SECRET*/*TOKEN*`` default excludes and
hermes's fixed provider blocklist; unlike codex (which defaults the exclude
*off*), DeerFlow scrubs by default — security first.
"""

from __future__ import annotations

import fnmatch
import os

# Case-insensitive wildcard patterns for secret-looking variable names. Matched
# against the upper-cased variable name. Benign system vars (PATH, HOME, SHELL,
# LANG, PWD, TMPDIR, VIRTUAL_ENV, PYTHONPATH, ...) contain none of these tokens
# and are therefore preserved.
_SECRET_NAME_PATTERNS: tuple[str, ...] = (
    "*KEY*",
    "*SECRET*",
    "*TOKEN*",
    "*PASSWORD*",
    "*PASSWD*",
    "*CREDENTIAL*",
)


def is_blocked_env_name(name: str) -> bool:
    """Return True if ``name`` looks like a credential that must not be inherited
    by a sandbox subprocess."""
    upper = name.upper()
    return any(fnmatch.fnmatchcase(upper, pattern) for pattern in _SECRET_NAME_PATTERNS)


def build_sandbox_env(injected: dict[str, str] | None = None) -> dict[str, str]:
    """Build the environment dict for a sandbox subprocess.

    Inherits ``os.environ`` minus any secret-looking variables, then layers the
    explicitly injected request-scoped secrets on top. An injected secret wins
    even if its name matches a blocked pattern, because injection is authorized
    upstream (the skill declared it and the value came from the request, not from
    the host environment).
    """
    env = {key: value for key, value in os.environ.items() if not is_blocked_env_name(key)}
    if injected:
        env.update(injected)
    return env
