"""Dialect-aware JSON value matching for SQLAlchemy (SQLite + PostgreSQL)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import BigInteger, Float, String, bindparam
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.expression import ColumnElement
from sqlalchemy.sql.visitors import InternalTraversal
from sqlalchemy.types import Boolean, TypeEngine

# Key is interpolated into compiled SQL; restrict charset to prevent injection.
_KEY_CHARSET_RE = re.compile(r"^[A-Za-z0-9_\-]+$")

# Allowed value types for metadata filter values (same set accepted by JsonMatch).
ALLOWED_FILTER_VALUE_TYPES: tuple[type, ...] = (type(None), bool, int, float, str)

# SQLite raises an overflow when binding values outside signed 64-bit range;
# PostgreSQL overflows during BIGINT cast. Reject at validation time instead.
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def validate_metadata_filter_key(key: object) -> bool:
    """Return True if *key* is safe for use as a JSON metadata filter key.

    A key is "safe" when it is a string matching ``[A-Za-z0-9_-]+``. The
    charset is restricted because the key is interpolated into the
    compiled SQL path expression (``$."<key>"`` / ``->`` literal), so any
    laxer pattern would open a SQL/JSONPath injection surface.
    """
    return isinstance(key, str) and bool(_KEY_CHARSET_RE.match(key))


def validate_metadata_filter_value(value: object) -> bool:
    """Return True if *value* is an allowed type for a JSON metadata filter.

    Matches the set of types ``_build_clause`` knows how to compile into
    a dialect-portable predicate. Anything else (list/dict/bytes/...) is
    intentionally rejected rather than silently coerced via ``str()`` —
    silent coercion would (a) produce wrong matches and (b) break
    SQLAlchemy's ``inherit_cache`` invariant when ``value`` is unhashable.

    Integer values are additionally restricted to the signed 64-bit range
    ``[-2**63, 2**63 - 1]``: SQLite overflows when binding larger values
    and PostgreSQL overflows during the ``BIGINT`` cast.
    """
    if not isinstance(value, ALLOWED_FILTER_VALUE_TYPES):
        return False
    if isinstance(value, int) and not isinstance(value, bool):
        if not (_INT64_MIN <= value <= _INT64_MAX):
            return False
    return True


class JsonMatch(ColumnElement):
    """Dialect-portable ``column[key] == value`` for JSON columns.

    Compiles to ``json_type``/``json_extract`` on SQLite and
    ``json_typeof``/``->>`` on PostgreSQL, with type-safe comparison
    that distinguishes bool vs int and NULL vs missing key.

    *key* must be a single literal key matching ``[A-Za-z0-9_-]+``.
    *value* must be one of: ``None``, ``bool``, ``int`` (signed 64-bit), ``float``, ``str``.
    """

    inherit_cache = True
    type = Boolean()
    _is_implicitly_boolean = True

    _traverse_internals = [
        ("column", InternalTraversal.dp_clauseelement),
        ("key", InternalTraversal.dp_string),
        ("value", InternalTraversal.dp_plain_obj),
    ]

    def __init__(self, column: ColumnElement, key: str, value: object) -> None:
        if not validate_metadata_filter_key(key):
            raise ValueError(f"JsonMatch key must match {_KEY_CHARSET_RE.pattern!r}; got: {key!r}")
        if not validate_metadata_filter_value(value):
            if isinstance(value, int) and not isinstance(value, bool):
                raise TypeError(f"JsonMatch int value out of signed 64-bit range [-2**63, 2**63-1]: {value!r}")
            raise TypeError(f"JsonMatch value must be None, bool, int, float, or str; got: {type(value).__name__!r}")
        self.column = column
        self.key = key
        self.value = value
        super().__init__()


@dataclass(frozen=True)
class _Dialect:
    """Per-dialect names used when emitting JSON type/value comparisons."""

    null_type: str
    num_types: tuple[str, ...]
    num_cast: str
    int_types: tuple[str, ...]
    int_cast: str
    # None for SQLite where json_type already returns 'integer'/'real';
    # regex literal for PostgreSQL where json_typeof returns 'number' for
    # both ints and floats, so an extra guard prevents CAST errors on floats.
    int_guard: str | None
    string_type: str
    bool_type: str | None


_SQLITE = _Dialect(
    null_type="null",
    num_types=("integer", "real"),
    num_cast="REAL",
    int_types=("integer",),
    int_cast="INTEGER",
    int_guard=None,
    string_type="text",
    bool_type=None,
)

_PG = _Dialect(
    null_type="null",
    num_types=("number",),
    num_cast="DOUBLE PRECISION",
    int_types=("number",),
    int_cast="BIGINT",
    int_guard="'^-?[0-9]+$'",
    string_type="string",
    bool_type="boolean",
)


def _bind(compiler: SQLCompiler, value: object, sa_type: TypeEngine[Any], **kw: Any) -> str:
    param = bindparam(None, value, type_=sa_type)
    return compiler.process(param, **kw)


def _type_check(typeof: str, types: tuple[str, ...]) -> str:
    if len(types) == 1:
        return f"{typeof} = '{types[0]}'"
    quoted = ", ".join(f"'{t}'" for t in types)
    return f"{typeof} IN ({quoted})"


def _build_clause(compiler: SQLCompiler, typeof: str, extract: str, value: object, dialect: _Dialect, **kw: Any) -> str:
    if value is None:
        return f"{typeof} = '{dialect.null_type}'"
    if isinstance(value, bool):
        # bool check must precede int check — bool is a subclass of int in Python
        bool_str = "true" if value else "false"
        if dialect.bool_type is None:
            return f"{typeof} = '{bool_str}'"
        return f"({typeof} = '{dialect.bool_type}' AND {extract} = '{bool_str}')"
    if isinstance(value, int):
        bp = _bind(compiler, value, BigInteger(), **kw)
        if dialect.int_guard:
            # CASE prevents CAST error when json_typeof = 'number' also matches floats
            return f"(CASE WHEN {_type_check(typeof, dialect.int_types)} AND {extract} ~ {dialect.int_guard} THEN CAST({extract} AS {dialect.int_cast}) END = {bp})"
        return f"({_type_check(typeof, dialect.int_types)} AND CAST({extract} AS {dialect.int_cast}) = {bp})"
    if isinstance(value, float):
        bp = _bind(compiler, value, Float(), **kw)
        return f"({_type_check(typeof, dialect.num_types)} AND CAST({extract} AS {dialect.num_cast}) = {bp})"
    bp = _bind(compiler, str(value), String(), **kw)
    return f"({typeof} = '{dialect.string_type}' AND {extract} = {bp})"


@compiles(JsonMatch, "sqlite")
def _compile_sqlite(element: JsonMatch, compiler: SQLCompiler, **kw: Any) -> str:
    if not validate_metadata_filter_key(element.key):
        raise ValueError(f"Key escaped validation: {element.key!r}")
    col = compiler.process(element.column, **kw)
    path = f'$."{element.key}"'
    typeof = f"json_type({col}, '{path}')"
    extract = f"json_extract({col}, '{path}')"
    return _build_clause(compiler, typeof, extract, element.value, _SQLITE, **kw)


@compiles(JsonMatch, "postgresql")
def _compile_pg(element: JsonMatch, compiler: SQLCompiler, **kw: Any) -> str:
    if not validate_metadata_filter_key(element.key):
        raise ValueError(f"Key escaped validation: {element.key!r}")
    col = compiler.process(element.column, **kw)
    typeof = f"json_typeof({col} -> '{element.key}')"
    extract = f"({col} ->> '{element.key}')"
    return _build_clause(compiler, typeof, extract, element.value, _PG, **kw)


@compiles(JsonMatch)
def _compile_default(element: JsonMatch, compiler: SQLCompiler, **kw: Any) -> str:
    raise NotImplementedError(f"JsonMatch supports only sqlite and postgresql; got dialect: {compiler.dialect.name}")


def json_match(column: ColumnElement, key: str, value: object) -> JsonMatch:
    return JsonMatch(column, key, value)
