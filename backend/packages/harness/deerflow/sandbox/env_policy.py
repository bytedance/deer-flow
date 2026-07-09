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
    "*DSN*",  # data source name — almost always a connection string with a password
)

# Connection-string / credential-bearing variable names that carry no
# KEY/SECRET/TOKEN/DSN substring but routinely embed a password (e.g.
# ``postgresql://user:pw@host/db``). A blanket ``*URL*`` block is intentionally
# avoided — it would strip benign service URLs a skill may legitimately read.
# A skill that genuinely needs one of these must declare it via required-secrets
# (the caller then supplies it through context.secrets, and injection wins).
#
# The same reasoning covers the password variables those clients read directly.
# ``MYSQL_PWD`` and ``REDISCLI_AUTH`` are the documented no-flag credential
# sources for ``mysql`` and ``redis-cli``. ``REDIS_AUTH`` is *not* canonical for
# any standard Redis client — it is blocked defensively because client libraries
# and deployment charts commonly set it.
# All three need exact entries: ``PWD``/``AUTH`` cannot be wildcarded, since
# ``*PWD*`` would strip ``PWD`` and ``OLDPWD``. (``*PASSWORD*``/``*PASSWD*``
# already cover ``PGPASSWORD``, ``MYSQL_PASSWORD``, ``REDIS_PASSWORD``, ...)
_BLOCKED_EXACT_NAMES: frozenset[str] = frozenset(
    {
        "DATABASE_URL",
        "DATABASE_URI",
        "REDIS_URL",
        "MONGODB_URI",
        "MONGO_URL",
        "AMQP_URL",
        "RABBITMQ_URL",
        "POSTGRES_URL",
        "POSTGRESQL_URL",
        "MYSQL_URL",
        "CLICKHOUSE_URL",
        "CONNECTION_STRING",
        "CONN_STR",
        "GH_PAT",
        "GITHUB_PAT",
        "MYSQL_PWD",
        "REDISCLI_AUTH",
        "REDIS_AUTH",
    }
)


def is_blocked_env_name(name: str) -> bool:
    """Return True if ``name`` looks like a credential that must not be inherited
    by a sandbox subprocess."""
    upper = name.upper()
    if upper in _BLOCKED_EXACT_NAMES:
        return True
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
