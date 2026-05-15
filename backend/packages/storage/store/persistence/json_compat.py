"""Dialect-aware JSON value matching for storage SQLAlchemy repositories."""

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

_KEY_CHARSET_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
ALLOWED_FILTER_VALUE_TYPES: tuple[type, ...] = (type(None), bool, int, float, str)

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def validate_metadata_filter_key(key: object) -> bool:
    """Return True when *key* is safe for JSON metadata filter SQL paths."""
    return isinstance(key, str) and bool(_KEY_CHARSET_RE.match(key))


def validate_metadata_filter_value(value: object) -> bool:
    """Return True when *value* can be compiled into a portable JSON predicate."""
    if not isinstance(value, ALLOWED_FILTER_VALUE_TYPES):
        return False
    if isinstance(value, int) and not isinstance(value, bool):
        return _INT64_MIN <= value <= _INT64_MAX
    return True


class JsonMatch(ColumnElement[bool]):
    """Dialect-portable ``column[key] == value`` for JSON columns."""

    inherit_cache = True
    type = Boolean()
    _is_implicitly_boolean = True

    _traverse_internals = [
        ("column", InternalTraversal.dp_clauseelement),
        ("key", InternalTraversal.dp_string),
        ("value", InternalTraversal.dp_plain_obj),
        ("value_type", InternalTraversal.dp_string),
    ]

    def __init__(self, column: ColumnElement[Any], key: str, value: object) -> None:
        if not validate_metadata_filter_key(key):
            raise ValueError(f"JsonMatch key must match {_KEY_CHARSET_RE.pattern!r}; got: {key!r}")
        if not validate_metadata_filter_value(value):
            if isinstance(value, int) and not isinstance(value, bool):
                raise TypeError(f"JsonMatch int value out of signed 64-bit range [-2**63, 2**63-1]: {value!r}")
            raise TypeError(f"JsonMatch value must be None, bool, int, float, or str; got: {type(value).__name__!r}")
        self.column = column
        self.key = key
        self.value = value
        self.value_type = type(value).__qualname__
        super().__init__()


@dataclass(frozen=True)
class _Dialect:
    null_type: str
    num_types: tuple[str, ...]
    num_cast: str
    int_types: tuple[str, ...]
    int_cast: str
    int_guard: str | None
    string_type: str
    bool_type: str | None
    true_value: str
    false_value: str


_SQLITE = _Dialect(
    null_type="null",
    num_types=("integer", "real"),
    num_cast="REAL",
    int_types=("integer",),
    int_cast="INTEGER",
    int_guard=None,
    string_type="text",
    bool_type=None,
    true_value="true",
    false_value="false",
)

_POSTGRES = _Dialect(
    null_type="null",
    num_types=("number",),
    num_cast="DOUBLE PRECISION",
    int_types=("number",),
    int_cast="BIGINT",
    int_guard="'^-?[0-9]+$'",
    string_type="string",
    bool_type="boolean",
    true_value="true",
    false_value="false",
)

_MYSQL = _Dialect(
    null_type="NULL",
    num_types=("INTEGER", "DOUBLE", "DECIMAL"),
    num_cast="DOUBLE",
    int_types=("INTEGER",),
    int_cast="SIGNED",
    int_guard=None,
    string_type="STRING",
    bool_type="BOOLEAN",
    true_value="true",
    false_value="false",
)


def _bind(compiler: SQLCompiler, value: object, sa_type: TypeEngine[Any], **kw: Any) -> str:
    param = bindparam(None, value, type_=sa_type)
    return compiler.process(param, **kw)


def _type_check(typeof: str, types: tuple[str, ...]) -> str:
    if len(types) == 1:
        return f"{typeof} = '{types[0]}'"
    quoted = ", ".join(f"'{type_name}'" for type_name in types)
    return f"{typeof} IN ({quoted})"


def _build_clause(compiler: SQLCompiler, typeof: str, extract: str, value: object, dialect: _Dialect, **kw: Any) -> str:
    if value is None:
        return f"{typeof} = '{dialect.null_type}'"
    if isinstance(value, bool):
        bool_str = dialect.true_value if value else dialect.false_value
        if dialect.bool_type is None:
            return f"{typeof} = '{bool_str}'"
        return f"({typeof} = '{dialect.bool_type}' AND {extract} = '{bool_str}')"
    if isinstance(value, int):
        bp = _bind(compiler, value, BigInteger(), **kw)
        if dialect.int_guard:
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
def _compile_postgres(element: JsonMatch, compiler: SQLCompiler, **kw: Any) -> str:
    if not validate_metadata_filter_key(element.key):
        raise ValueError(f"Key escaped validation: {element.key!r}")
    col = compiler.process(element.column, **kw)
    typeof = f"json_typeof({col} -> '{element.key}')"
    extract = f"({col} ->> '{element.key}')"
    return _build_clause(compiler, typeof, extract, element.value, _POSTGRES, **kw)


@compiles(JsonMatch, "mysql")
def _compile_mysql(element: JsonMatch, compiler: SQLCompiler, **kw: Any) -> str:
    if not validate_metadata_filter_key(element.key):
        raise ValueError(f"Key escaped validation: {element.key!r}")
    col = compiler.process(element.column, **kw)
    path = f'$."{element.key}"'
    typeof = f"JSON_TYPE(JSON_EXTRACT({col}, '{path}'))"
    extract = f"JSON_UNQUOTE(JSON_EXTRACT({col}, '{path}'))"
    return _build_clause(compiler, typeof, extract, element.value, _MYSQL, **kw)


@compiles(JsonMatch)
def _compile_default(element: JsonMatch, compiler: SQLCompiler, **kw: Any) -> str:
    raise NotImplementedError(f"JsonMatch supports sqlite, postgresql, and mysql; got dialect: {compiler.dialect.name}")


def json_match(column: ColumnElement[Any], key: str, value: object) -> JsonMatch:
    return JsonMatch(column, key, value)
