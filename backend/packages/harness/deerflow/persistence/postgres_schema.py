"""PostgreSQL schema helpers (Issue #3380).

Centralizes the driver-specific ways of pinning a connection's
``search_path`` to a target schema. The two PostgreSQL drivers DeerFlow
uses expect different mechanisms:

- **asyncpg** (app ORM engine): only honours ``server_settings`` passed
  via SQLAlchemy ``connect_args``. It does not understand libpq's
  ``options=-c ...`` syntax.
- **psycopg** (LangGraph checkpointer/store): uses the libpq
  ``options=-c search_path=...`` connection parameter, either as a pool
  kwarg or encoded into the DSN query string.

Schema names are validated upstream by
:class:`deerflow.config.database_config.DatabaseConfig` to be plain
identifiers. SQL-emitting helpers re-validate at the boundary as
defense-in-depth; connection-argument helpers only assemble driver payloads.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit


def build_asyncpg_connect_args(schema: str) -> dict:
    """Return SQLAlchemy ``connect_args`` that pin asyncpg's search_path.

    Empty *schema* yields ``{}`` so the engine keeps the server default.
    """
    if not schema:
        return {}
    return {"server_settings": {"search_path": schema}}


def build_psycopg_options(schema: str) -> str | None:
    """Return the libpq ``options`` value for psycopg pool kwargs.

    Empty *schema* yields ``None`` so callers can skip setting the kwarg.
    """
    if not schema:
        return None
    return f"-c search_path={schema}"


def _split_libpq_options(options: str) -> list[str]:
    """Tokenize a libpq ``options`` string.

    libpq splits on unescaped whitespace; a backslash escapes the next
    character (so ``\\ `` is a literal space and ``\\\\`` a literal backslash).
    This is NOT POSIX shell quoting -- single/double quotes are literal here.
    """
    tokens: list[str] = []
    current: list[str] = []
    in_token = False
    escaped = False
    for char in options:
        if escaped:
            current.append(char)
            escaped = False
            in_token = True
            continue
        if char == "\\":
            escaped = True
            in_token = True
            continue
        if char.isspace():
            if in_token:
                tokens.append("".join(current))
                current = []
                in_token = False
            continue
        current.append(char)
        in_token = True
    if in_token:
        tokens.append("".join(current))
    return tokens


def _join_libpq_options(tokens: list[str]) -> str:
    """Join tokens into a libpq ``options`` string.

    Whitespace and backslashes inside a token are backslash-escaped so libpq
    keeps each token intact. ``shlex.join`` cannot be used: it emits POSIX
    shell quoting (single quotes), which libpq treats as literal characters.

    All whitespace bytes are escaped, not just spaces: ``_split_libpq_options``
    preserves a backslash-escaped TAB/CR/LF as part of one token, so re-joining
    with a bare whitespace byte would let libpq re-tokenize on it and corrupt a
    caller's pre-existing ``options`` value.
    """
    escaped = [re.sub(r"([\\\s])", r"\\\1", token) for token in tokens]
    return " ".join(escaped)


def _merge_search_path_option(existing_options: str, schema: str) -> str:
    """Return libpq options with search_path replaced while preserving others."""
    new_option = build_psycopg_options(schema)
    if not new_option:
        return existing_options

    if not existing_options:
        return new_option

    tokens = _split_libpq_options(existing_options)

    merged: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "-c" and index + 1 < len(tokens):
            setting = tokens[index + 1]
            if setting.split("=", 1)[0] == "search_path":
                index += 2
                continue
            merged.extend([token, setting])
            index += 2
            continue
        if token.startswith("-csearch_path="):
            index += 1
            continue
        merged.append(token)
        index += 1

    merged.extend(_split_libpq_options(new_option))
    return _join_libpq_options(merged)


def create_schema_sql(schema: str) -> str | None:
    """Return a safe CREATE SCHEMA statement for a validated plain identifier.

    Defense-in-depth: the identifier is re-validated here rather than trusting
    the distant pydantic validator. ``create_schema_sql`` is publicly exported
    and psycopg accepts multiple ``;``-separated statements, so a future caller
    that bypasses ``DatabaseConfig``/``CheckpointerConfig`` (e.g. a test helper)
    must not be able to inject SQL through this f-string boundary.
    """
    if not schema:
        return None
    from deerflow.config.postgres_schema import validate_postgres_schema

    validate_postgres_schema(schema)
    return f'CREATE SCHEMA IF NOT EXISTS "{schema}"'


def normalize_libpq_dsn(dsn: str) -> str:
    """Return *dsn* with any SQLAlchemy ``+driver`` suffix dropped.

    ``DatabaseConfig.postgres_url`` may carry a SQLAlchemy driver suffix such
    as ``postgresql+asyncpg://``. psycopg's libpq only understands the bare
    ``postgres``/``postgresql`` scheme, so a raw ``+asyncpg`` DSN handed to
    ``psycopg.connect`` raises an opaque parse error. Keyword/DSN strings
    without a URL scheme (``host=... dbname=...``) are returned unchanged.

    Raises ``ValueError`` for URL schemes that are not a PostgreSQL variant.
    """
    parts = urlsplit(dsn)
    if not parts.scheme:
        return dsn
    scheme_base = parts.scheme.split("+", 1)[0]
    if scheme_base not in {"postgres", "postgresql"}:
        raise ValueError(f"Unsupported PostgreSQL DSN scheme for schema injection: {parts.scheme!r}")
    if scheme_base == parts.scheme:
        return dsn
    return urlunsplit((scheme_base, parts.netloc, parts.path, parts.query, parts.fragment))


def dsn_with_search_path(dsn: str, schema: str) -> str:
    """Return *dsn* with an ``options=-c search_path=<schema>`` query param.

    Used for psycopg ``from_conn_string`` call sites that take a DSN
    string rather than pool kwargs. The value contains a space and ``=``;
    both are percent-encoded so libpq parses the URL correctly.

    libpq only recognizes ``%XX`` percent-encoding in URI query values; it
    does NOT treat ``+`` as a space (that is an HTML-form convention). So
    the space MUST be encoded as ``%20`` rather than ``+``, otherwise libpq
    sees a single broken token ``-c+search_path=...`` and the search_path is
    never applied. Existing query parameters are preserved. Empty *schema*
    returns *dsn* unchanged.
    """
    if not schema:
        return dsn
    parts = urlsplit(dsn)

    if not parts.scheme:
        from psycopg.conninfo import conninfo_to_dict, make_conninfo

        params = conninfo_to_dict(dsn)
        params["options"] = _merge_search_path_option(params.get("options", ""), schema)
        return make_conninfo(**params)

    # DatabaseConfig.postgres_url may carry a SQLAlchemy driver suffix such as
    # ``postgresql+asyncpg://``. psycopg's libpq only understands the bare
    # ``postgres``/``postgresql`` scheme, so accept the compound form but emit
    # a psycopg-consumable DSN by dropping the ``+driver`` part.
    scheme_base = parts.scheme.split("+", 1)[0]
    if scheme_base not in {"postgres", "postgresql"}:
        raise ValueError(f"Unsupported PostgreSQL DSN scheme for schema injection: {parts.scheme!r}")

    options_values: list[str] = []
    query_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "options":
            options_values.append(value)
        else:
            query_pairs.append((key, value))

    options = _merge_search_path_option(" ".join(options_values), schema)
    query_pairs.append(("options", options))
    # quote_via=quote encodes space as %20 (libpq-safe), not + (form-style).
    query = urlencode(query_pairs, quote_via=quote)
    return urlunsplit((scheme_base, parts.netloc, parts.path, query, parts.fragment))


def ensure_postgres_schema(conn_string: str, schema: str, *, install_hint: str) -> None:
    """Create *schema* over a fresh sync psycopg connection.

    No-op when *schema* is empty. A missing ``psycopg`` dependency is mapped to
    *install_hint* so callers surface the same actionable message they use for
    the rest of the backend. The DSN is normalized so a SQLAlchemy ``+driver``
    suffix does not reach libpq.
    """
    statement = create_schema_sql(schema)
    if statement is None:
        return
    try:
        import psycopg
    except ImportError as exc:
        raise ImportError(install_hint) from exc

    # psycopg 3's ``Connection.__exit__`` only commits/rolls back -- it does NOT
    # close the connection (a documented psycopg2->3 change). Use try/finally so
    # the libpq connection is released deterministically, mirroring the async
    # counterpart, instead of leaking it until GC.
    conn = psycopg.connect(normalize_libpq_dsn(conn_string), autocommit=True)
    try:
        conn.execute(statement)
    finally:
        conn.close()


async def ensure_postgres_schema_async(conn_string: str, schema: str, *, install_hint: str) -> None:
    """Async counterpart of :func:`ensure_postgres_schema`."""
    statement = create_schema_sql(schema)
    if statement is None:
        return
    try:
        import psycopg
    except ImportError as exc:
        raise ImportError(install_hint) from exc

    conn = await psycopg.AsyncConnection.connect(normalize_libpq_dsn(conn_string), autocommit=True)
    try:
        await conn.execute(statement)
    finally:
        await conn.close()
