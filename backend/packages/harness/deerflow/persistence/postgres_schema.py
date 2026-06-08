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
identifiers, so these helpers do not re-validate; they only assemble the
driver payloads.
"""

from __future__ import annotations

import shlex
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


def _merge_search_path_option(existing_options: str, schema: str) -> str:
    """Return libpq options with search_path replaced while preserving others."""
    new_option = build_psycopg_options(schema)
    if not new_option:
        return existing_options

    if not existing_options:
        return new_option

    try:
        tokens = shlex.split(existing_options)
    except ValueError:
        # Keep existing options even when they cannot be parsed safely; libpq
        # applies later -c values after earlier ones, so the appended
        # search_path still wins.
        return f"{existing_options} {new_option}"

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

    merged.extend(shlex.split(new_option))
    return shlex.join(merged)


def create_schema_sql(schema: str) -> str | None:
    """Return a safe CREATE SCHEMA statement for a validated plain identifier."""
    if not schema:
        return None
    return f'CREATE SCHEMA IF NOT EXISTS "{schema}"'


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

    if parts.scheme not in {"postgres", "postgresql"}:
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
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
