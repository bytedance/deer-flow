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
    # ``*PASS*`` subsumes the full ``PASSWORD``/``PASSWD`` spellings *and* the
    # ubiquitous abbreviated form (``DB_PASS``, ``SMTP_PASS``, ``MYSQL_PASS``, ...),
    # whose plaintext value is the password itself. It also covers ``PGPASSFILE``
    # (libpq's ``.pgpass`` locator).
    #
    # It deliberately also catches the ``*_ASKPASS`` credential helpers
    # (``GIT_ASKPASS``, ``SSH_ASKPASS``, ``SUDO_ASKPASS``). Those name a *program*
    # rather than a secret, but that program exists to hand the caller a
    # credential — inheriting the pointer is the same leak class this module
    # closes, so scrubbing them is intended, not incidental.
    #
    # Incidental names that merely contain ``PASS`` (``COMPASS_*``, ``BYPASS_*``)
    # are scrubbed too. That is the fail-safe direction for this module: a skill
    # that genuinely needs any scrubbed name declares it via required-secrets.
    # Benign ``PWD``/``OLDPWD`` carry no ``PASS`` substring and are unaffected.
    "*PASS*",
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
# The same reasoning covers the credential sources those clients read directly.
# ``MYSQL_PWD`` and ``REDISCLI_AUTH`` are the documented no-flag credential
# sources for ``mysql`` and ``redis-cli``. ``REDIS_AUTH`` is *not* canonical for
# any standard Redis client — it is blocked defensively because client libraries
# and deployment charts commonly set it. ``PGSERVICEFILE`` is the Postgres analog:
# libpq reads the ``pg_service.conf`` it points at (which may carry a password
# field) with no flag; its sibling ``PGPASSFILE`` is already caught by ``*PASS*``.
# These need exact entries: ``PWD``/``AUTH``/``SERVICEFILE`` cannot be wildcarded,
# since ``*PWD*`` would strip ``PWD``/``OLDPWD`` and no shared token is unique to
# them. (``*PASS*`` already covers ``PGPASSWORD``, ``MYSQL_PASSWORD``, ``DB_PASS``,
# ``PGPASSFILE``, ...)
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
        "PGSERVICEFILE",
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
