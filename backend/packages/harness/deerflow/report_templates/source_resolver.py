"""JSONPath subset parser and evaluator for report template DSL.

Implements §5.6 of the design spec:
- Whitelist: ``$.<segment>(.<segment>|[*])*``
- Blacklist: filters, function calls, recursion (``..``), index access other than
  ``[*]``, arithmetic/boolean/string operators.
- Hand-written tokenizer + parser, NO third-party JSONPath libraries.
- AST node types: Root | FieldAccess | ArrayAll. Anything else → ``INVALID_SYNTAX``.
- Parser runs at validate time; evaluator at runtime only walks the AST.

Public API:
    parse(expr: str) -> list[ASTNode]      # tokens + AST; raises PathSyntaxError
    evaluate(ast, context) -> Any           # walks AST; raises PathNotFoundError

Top-level placeholder helpers (used by DSL ``{{ ... }}`` interpolation):
    extract_expressions(text)
    render(text, context)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

# Path depth limit (§5.6): max 8 segments after $.
_MAX_PATH_DEPTH: Final[int] = 8

# Allowed first-level roots (§5.6 whitelist).
_ALLOWED_ROOTS: Final[frozenset[str]] = frozenset({"form", "steps", "run", "template"})

# Identifier regex for field names — letters, digits, underscores, hyphens.
_IDENT_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]*")

# Placeholder regex: matches "{{ ... }}" with content captured.
_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(r"\{\{\s*(.*?)\s*\}\}")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class JSONPathError(Exception):
    """Base error for JSONPath subset issues."""


class PathSyntaxError(JSONPathError):
    """Raised by the parser when the expression violates whitelist syntax."""

    def __init__(self, message: str, expression: str, position: int = -1) -> None:
        self.expression = expression
        self.position = position
        super().__init__(f"{message} (in {expression!r}, pos={position})")


class PathNotFoundError(JSONPathError):
    """Raised by the evaluator when a path segment cannot be resolved."""

    def __init__(self, path: str, missing_segment: str) -> None:
        self.path = path
        self.missing_segment = missing_segment
        super().__init__(f"path segment {missing_segment!r} not found in {path!r}")


# ---------------------------------------------------------------------------
# AST node types — only these three are legal.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Root:
    """The leading ``$``."""


@dataclass(frozen=True)
class FieldAccess:
    """``.field_name`` — access a dict key."""

    name: str


@dataclass(frozen=True)
class ArrayAll:
    """``[*]`` — expand every element of an array.

    Must always be followed by a FieldAccess; the evaluator enforces this.
    """


ASTNode = Root | FieldAccess | ArrayAll


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse(expression: str) -> list[ASTNode]:
    """Parse a JSONPath subset expression into a flat AST node list.

    Accepts both ``$.form.x`` and the short form ``form.x`` (auto-prefixed).
    Raises ``PathSyntaxError`` on any blacklisted syntax.
    """
    if not isinstance(expression, str):
        raise PathSyntaxError("expression must be a string", expression=str(expression))

    raw = expression.strip()
    if not raw:
        raise PathSyntaxError("empty expression", expression=expression)

    # Auto-prefix ``$.`` for human-friendly short form (§5.6 last paragraph).
    if not raw.startswith("$"):
        raw = "$." + raw

    if raw == "$":
        raise PathSyntaxError("expression must reference at least one root key", expression=expression)

    if not raw.startswith("$."):
        raise PathSyntaxError("expression must start with '$.'", expression=expression, position=0)

    # Recursion ``..`` is forbidden (§5.6 blacklist).
    if ".." in raw:
        raise PathSyntaxError("recursive descent '..' is not allowed", expression=expression, position=raw.index(".."))

    ast: list[ASTNode] = [Root()]
    i = 2  # skip the leading "$."
    expect_field = True  # after Root or ArrayAll we must see a field name
    depth = 0
    first_segment = True

    while i < len(raw):
        ch = raw[i]
        if ch == ".":
            if expect_field:
                raise PathSyntaxError("unexpected '.'", expression=expression, position=i)
            expect_field = True
            i += 1
            continue
        if ch == "[":
            # Only "[*]" is allowed.
            if raw[i : i + 3] != "[*]":
                raise PathSyntaxError(
                    "only '[*]' is allowed inside brackets (no index, slice, or filter)",
                    expression=expression,
                    position=i,
                )
            if expect_field:
                raise PathSyntaxError(
                    "'[*]' must come after a field name, not immediately after '.'",
                    expression=expression,
                    position=i,
                )
            ast.append(ArrayAll())
            depth += 1
            if depth > _MAX_PATH_DEPTH:
                raise PathSyntaxError(
                    f"path depth exceeds {_MAX_PATH_DEPTH}", expression=expression, position=i
                )
            # ``[*]`` is itself a complete segment. The next character must be
            # ``.`` followed by a field name (``[*].field``); the post-parse check
            # below ensures ``[*]`` cannot be the trailing token.
            expect_field = False
            i += 3
            continue

        match = _IDENT_RE.match(raw, i)
        if not match:
            raise PathSyntaxError(
                f"unexpected character {ch!r}", expression=expression, position=i
            )
        name = match.group(0)
        if first_segment:
            if name not in _ALLOWED_ROOTS:
                raise PathSyntaxError(
                    f"root segment {name!r} not in {sorted(_ALLOWED_ROOTS)}",
                    expression=expression,
                    position=i,
                )
            first_segment = False
        ast.append(FieldAccess(name=name))
        depth += 1
        if depth > _MAX_PATH_DEPTH:
            raise PathSyntaxError(
                f"path depth exceeds {_MAX_PATH_DEPTH}", expression=expression, position=i
            )
        expect_field = False
        i = match.end()

    if expect_field:
        raise PathSyntaxError("trailing '.' or '[*]' with no following field", expression=expression)

    # `[*]` must always be followed by a FieldAccess (cannot be the last node).
    for idx, node in enumerate(ast):
        if isinstance(node, ArrayAll) and (idx == len(ast) - 1 or not isinstance(ast[idx + 1], FieldAccess)):
            raise PathSyntaxError(
                "'[*]' must be followed by a field access (e.g. '[*].field')",
                expression=expression,
            )

    return ast


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


def evaluate(ast: list[ASTNode], context: dict[str, Any]) -> Any:
    """Walk the AST against ``context`` and return the resolved value.

    ``ArrayAll`` collects across the array, expanding into a list of the
    subsequent FieldAccess values.
    """
    if not ast or not isinstance(ast[0], Root):
        raise PathSyntaxError("AST must start with Root", expression="<ast>")

    current: Any = context
    path_so_far = "$"

    i = 1
    while i < len(ast):
        node = ast[i]
        if isinstance(node, FieldAccess):
            if not isinstance(current, dict) or node.name not in current:
                raise PathNotFoundError(path_so_far, node.name)
            current = current[node.name]
            path_so_far = f"{path_so_far}.{node.name}"
            i += 1
            continue
        if isinstance(node, ArrayAll):
            if not isinstance(current, list):
                raise PathNotFoundError(path_so_far, "[*]")
            # The next node must be FieldAccess (parser already enforced).
            next_node = ast[i + 1]
            assert isinstance(next_node, FieldAccess)
            collected: list[Any] = []
            for elem in current:
                if not isinstance(elem, dict) or next_node.name not in elem:
                    raise PathNotFoundError(f"{path_so_far}[*]", next_node.name)
                collected.append(elem[next_node.name])
            current = collected
            path_so_far = f"{path_so_far}[*].{next_node.name}"
            i += 2
            continue
        raise PathSyntaxError(f"unknown AST node {type(node).__name__}", expression="<ast>")

    return current


# ---------------------------------------------------------------------------
# Placeholder helpers (used by validator/runtime for "{{ ... }}" strings).
# ---------------------------------------------------------------------------


def extract_expressions(text: str) -> list[str]:
    """Return all inner expressions inside ``{{ ... }}`` blocks in ``text``."""
    return _PLACEHOLDER_RE.findall(text)


def render(text: str, context: dict[str, Any]) -> str:
    """Substitute every ``{{ expr }}`` in ``text`` with ``evaluate(parse(expr), context)``.

    The result is stringified with ``str()``; callers that need typed values
    should call ``parse`` + ``evaluate`` directly.
    """

    def _replace(match: re.Match[str]) -> str:
        expr = match.group(1).strip()
        ast = parse(expr)
        return str(evaluate(ast, context))

    return _PLACEHOLDER_RE.sub(_replace, text)
