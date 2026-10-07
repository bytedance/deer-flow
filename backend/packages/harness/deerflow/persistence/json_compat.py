"""Dialect-aware JSON value matching for SQLAlchemy (SQLite + PostgreSQL)."""

from __future__ import annotations

import re
from collections.abc import Mapping
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

# Keep filter inputs portable: SQLite cannot bind integers outside signed
# 64-bit range. Stored JSON numbers may still be larger on either backend.
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
    ``[-2**63, 2**63 - 1]`` so filters remain portable to SQLite, which
    cannot bind larger integer values.
    """
    if not isinstance(value, ALLOWED_FILTER_VALUE_TYPES):
        return False
    if isinstance(value, int) and not isinstance(value, bool):
        if not (_INT64_MIN <= value <= _INT64_MAX):
            return False
    return True


def json_value_matches(values: Mapping[str, Any], key: str, expected: object) -> bool:
    """Match one JSON object field with the same type semantics as :class:`JsonMatch`.

    Missing keys differ from explicit JSON null, booleans differ from integers,
    integer filters accept only JSON integers, and float filters accept either
    JSON integer or real values. Callers validate filter keys and values at
    their API boundary; unsupported expected values never match.
    """
    if key not in values:
        return False

    actual = values[key]
    if expected is None:
        return actual is None
    if isinstance(expected, bool):
        return isinstance(actual, bool) and actual is expected
    if isinstance(expected, int):
        return isinstance(actual, int) and not isinstance(actual, bool) and actual == expected
    if isinstance(expected, float):
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return False
        try:
            return float(actual) == expected
        except OverflowError:
            return False
    if isinstance(expected, str):
        return isinstance(actual, str) and actual == expected
    return False


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
        ("value_type", InternalTraversal.dp_string),
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
        # Python considers True == 1 == 1.0 and gives them the same hash.
        # Include the JSON filter type in SQLAlchemy's cache key so a compiled
        # boolean predicate can never be reused for a numeric query (or vice versa).
        self.value_type = type(value).__name__
        self.value = value
        super().__init__()


@dataclass(frozen=True)
class _Dialect:
    """Per-dialect names used when emitting JSON type/value comparisons."""

    null_type: str
    num_types: tuple[str, ...]
    num_cast: str
    # PostgreSQL raises on JSON numbers outside DOUBLE PRECISION range; SQLite's
    # REAL cast saturates to +/-inf or +/-0.0 instead.
    num_cast_raises: bool
    int_types: tuple[str, ...]
    # PostgreSQL ->> returns the JSON number spelling; SQLite json_extract
    # returns a native integer or a (possibly lossy) real for large integers.
    int_as_text: bool
    string_type: str
    bool_type: str | None


_SQLITE = _Dialect(
    null_type="null",
    num_types=("integer", "real"),
    num_cast="REAL",
    num_cast_raises=False,
    int_types=("integer",),
    int_as_text=False,
    string_type="text",
    bool_type=None,
)

_PG = _Dialect(
    null_type="null",
    num_types=("number",),
    num_cast="DOUBLE PRECISION",
    num_cast_raises=True,
    int_types=("number",),
    int_as_text=True,
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


# Exact float8 rounding midpoints. Shortened spellings such as 1.7976931348623158e+308
# only round-trip; they do not mark where rounding flips. Both midpoints tie away
# from a finite nonzero float8 under ties-to-even (to inf and to 0), so they raise.
# DBL_MAX + half an ulp, a 309-digit integer.
_FLOAT8_OVERFLOW_MIDPOINT = str(2**1024 - 2**970)
# Half the min positive denormal, 2**-1075 == 5**1075 * 10**-1075, exactly.
_FLOAT8_UNDERFLOW_MIDPOINT = f"{5**1075}e-1075"
# CAST AS NUMERIC raises past 131072 integer digits (1e131072, 131073 nines) and
# past 16383 fractional digits (1e-16384). 10,000 characters plus an exponent of
# at most 6,000 stays under both, and float8 needs far less than either.
_NUMERIC_SAFE_CHARS = 10000
_NUMERIC_SAFE_EXPONENT = 6000
_ZERO_SPELLING = r"^-?0(\.0+)?([eE][+-]?[0-9]+)?$"
# Exponent digits without sign; JSON allows leading zeros (1.5e-0001 == 0.15).
_EXPONENT_DIGITS = r"[eE][+-]?([0-9]+)$"


def _pg_float_guard(typeof: str, extract: str, comparison: str, bp: str) -> str:
    """Skip JSON numbers that CAST AS DOUBLE PRECISION would reject (SQLSTATE 22003).

    Portable to PostgreSQL 14: do not use ``pg_input_is_valid`` (PostgreSQL 16+).
    CASE, unlike AND, guarantees evaluation order so the raising float8 cast only
    runs after cheaper, non-raising checks. CAST AS NUMERIC itself raises on
    1e131072 and on 1e-16384, so ``char_length`` and the exponent magnitude run
    first. The exponent is compared as a number after stripping leading zeros:
    its digit count is checked before CAST AS INTEGER so that cast cannot fail.
    Exact-zero spellings (including ``0e400``) are matched without a numeric cast
    so a huge exponent cannot overflow NUMERIC on a stored zero; they still match
    a ``0.0`` filter. Underflow such as ``1e-400`` is not an exact zero and never
    matches, whereas SQLite saturates it to 0.0. The float8 range check uses the
    exact rounding midpoints, so a value that rounds to DBL_MAX or 5e-324 still
    matches and one that rounds to inf or 0 is skipped instead of raising.
    """
    n = f"CAST({extract} AS NUMERIC)"
    # NULL without an exponent, so both exponent WHENs fall through.
    exponent = f"ltrim(substring({extract} FROM '{_EXPONENT_DIGITS}'), '0')"
    return (
        "CASE "
        f"WHEN {typeof} <> 'number' THEN false "
        f"WHEN {extract} ~ '{_ZERO_SPELLING}' THEN {bp} = 0 "
        f"WHEN char_length({extract}) > {_NUMERIC_SAFE_CHARS} THEN false "
        f"WHEN char_length({exponent}) > {len(str(_NUMERIC_SAFE_EXPONENT))} THEN false "
        f"WHEN CAST('0' || {exponent} AS INTEGER) > {_NUMERIC_SAFE_EXPONENT} THEN false "
        f"WHEN abs({n}) >= CAST('{_FLOAT8_OVERFLOW_MIDPOINT}' AS NUMERIC) THEN false "
        f"WHEN abs({n}) <= CAST('{_FLOAT8_UNDERFLOW_MIDPOINT}' AS NUMERIC) THEN false "
        f"ELSE {comparison} END"
    )


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
        if dialect.int_as_text:
            # JSON integer spellings are canonical except for -0. Comparing
            # text avoids overflowing BIGINT (or even NUMERIC) on stored values
            # and still excludes decimal/exponent spellings from int filters.
            bp = _bind(compiler, str(value), String(), **kw)
            comparison = f"{extract} IN ({bp}, '-0')" if value == 0 else f"{extract} = {bp}"
        else:
            bp = _bind(compiler, value, BigInteger(), **kw)
            # json_type reports 'integer' for oversized JSON integers too, but
            # json_extract returns REAL. Casting that REAL to INTEGER clamps it
            # to an int64 boundary and would create a false positive.
            comparison = f"typeof({extract}) = 'integer' AND {extract} = {bp}"
        return f"({_type_check(typeof, dialect.int_types)} AND {comparison})"
    if isinstance(value, float):
        bp = _bind(compiler, value, Float(), **kw)
        comparison = f"CAST({extract} AS {dialect.num_cast}) = {bp}"
        if dialect.num_cast_raises:
            # Overflow (1e400) and underflow to zero (1e-400) both raise 22003,
            # so one such stored value would fail the whole query. The CASE
            # folds the type check in: AND has no evaluation-order guarantee.
            return f"({_pg_float_guard(typeof, extract, comparison, bp)})"
        return f"({_type_check(typeof, dialect.num_types)} AND {comparison})"
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
