#!/usr/bin/env python3
"""Print the checkout `.env` as shell `export` lines for `serve.sh`.

`serve.sh` used to `source` the file, so bash ran it as a script: `$$` became
the shell's PID, backticks and `$(...)` ran commands, and an unquoted value
with a space ran its second word as a command (exit 127 under `set -e`). The
Gateway reads the same file with python-dotenv but never overrides a variable
that is already exported, so the shell's reading won.

This reads the file as data instead and never executes any of it:

- Statements are tokenized like python-dotenv (comments, `export` prefixes,
  single/double quotes and their escapes, multi-line quoted values, inline
  comments after unquoted values), so a value means what the Gateway reads.
- The launcher's own semantics stay, as `support_bundle.py` mirrors them:
  `.env` assignments override inherited variables, even with an empty value;
  `$NAME`, `${NAME}` and `${NAME:-literal}` expand in unquoted and
  double-quoted values from the environment, the checkout `PWD` and earlier
  assignments; `\\$` is a literal dollar and `$$` stays as written; an
  unquoted leading `~` expands; single-quoted values stay literal.

Each assignment is printed as `export NAME=<shell-quoted value>` for `eval`.
Statements that do not parse, and keys that are not shell variable names, are
skipped with a warning on stderr naming only the line or key, never a value.
An unreadable or non-UTF-8 file exits 1 before anything is printed.

Intentionally implemented with the standard library only: `serve.sh` runs this
with the host Python before `uv sync` has populated the venv.
"""

from __future__ import annotations

import codecs
import os
import re
import shlex
import sys
from collections.abc import Mapping
from pathlib import Path

# Statement grammar of python-dotenv's parser (`dotenv/parser.py`).
_LEADING_SPACE = re.compile(r"\s*")
_EXPORT = re.compile(r"(?:export[^\S\r\n]+)?")
_SINGLE_QUOTED_KEY = re.compile(r"'([^']+)'")
_UNQUOTED_KEY = re.compile(r"([^=\#\s]+)")
_SPACE = re.compile(r"[^\S\r\n]*")
_EQUAL_SIGN = re.compile(r"=[^\S\r\n]*")
_SINGLE_QUOTED_VALUE = re.compile(r"'((?:\\'|[^'])*)'")
_DOUBLE_QUOTED_VALUE = re.compile(r'"((?:\\"|[^"])*)"')
_UNQUOTED_VALUE = re.compile(r"[^\r\n]*")
_COMMENT = re.compile(r"(?:[^\S\r\n]*#[^\r\n]*)?")
_END_OF_LINE = re.compile(r"[^\S\r\n]*(?:\r\n|\n|\r|$)")
_REST_OF_LINE = re.compile(r"[^\r\n]*(?:\r\n|\n|\r)?")
_SINGLE_QUOTE_ESCAPES = re.compile(r"\\[\\']")
_DOUBLE_QUOTE_ESCAPES = re.compile(r"\\[\\'\"abfnrtv]")

# The launcher's variable references, as support_bundle.py resolves them. `$$`
# is one token, as in the shell, so its second `$` never starts a reference.
_REFERENCE = re.compile(r"\\\$|\$\$|\$(?:\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}|([A-Za-z_][A-Za-z0-9_]*))")
_SHELL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class _Unparsed(Exception):
    pass


def _match(pattern: re.Pattern[str], text: str, position: int) -> re.Match[str]:
    match = pattern.match(text, position)
    if match is None:
        raise _Unparsed
    return match


def _decode_escapes(pattern: re.Pattern[str], value: str) -> str:
    return pattern.sub(lambda match: codecs.decode(match[0], "unicode-escape"), value)


def _expand_references(value: str, environment: Mapping[str, str]) -> str:
    """Expand simple shell references in one pass, without executing shell syntax."""

    def replace(match: re.Match[str]) -> str:
        if match[0] == "\\$":
            return "$"
        if match[0] == "$$":
            return "$$"
        resolved = environment.get(match[1] or match[3], "")
        return match[2] if match[2] is not None and not resolved else resolved

    return _REFERENCE.sub(replace, value)


def parse_dotenv(text: str, environment: Mapping[str, str]) -> list[tuple[str, str]]:
    """Return the `(name, value)` assignments in `text`, in file order."""
    scope = dict(environment)
    assignments: list[tuple[str, str]] = []
    position = 0
    while position < len(text):
        position = _LEADING_SPACE.match(text, position).end()
        if position >= len(text):
            break
        line = text.count("\n", 0, position) + 1
        try:
            position = _EXPORT.match(text, position).end()
            key = None
            if text.startswith("'", position):
                match = _match(_SINGLE_QUOTED_KEY, text, position)
                key, position = match[1], match.end()
            elif not text.startswith("#", position):
                match = _match(_UNQUOTED_KEY, text, position)
                key, position = match[1], match.end()
            position = _SPACE.match(text, position).end()
            quote = ""
            value = None
            if text.startswith("=", position):
                position = _EQUAL_SIGN.match(text, position).end()
                quote = text[position : position + 1]
                if quote == "'":
                    match = _match(_SINGLE_QUOTED_VALUE, text, position)
                    value = _decode_escapes(_SINGLE_QUOTE_ESCAPES, match[1])
                elif quote == '"':
                    match = _match(_DOUBLE_QUOTED_VALUE, text, position)
                    value = _decode_escapes(_DOUBLE_QUOTE_ESCAPES, match[1])
                else:
                    match = _UNQUOTED_VALUE.match(text, position)
                    value = re.sub(r"\s+#.*", "", match[0]).rstrip()
                position = match.end()
            position = _COMMENT.match(text, position).end()
            position = _match(_END_OF_LINE, text, position).end()
        except _Unparsed:
            print(f"dotenv_exports: skipping a statement that does not parse at line {line}", file=sys.stderr)
            position = _REST_OF_LINE.match(text, position).end()
            continue
        # A comment, or a bare name without `=`, assigns nothing.
        if key is None or value is None:
            continue
        if not _SHELL_NAME.match(key):
            print(f"dotenv_exports: skipping {key!r} at line {line}: not a shell variable name", file=sys.stderr)
            continue
        if quote != "'":
            if quote != '"':
                value = os.path.expanduser(value)
            value = _expand_references(value, scope)
        scope[key] = value
        assignments.append((key, value))
    return assignments


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: dotenv_exports.py <path-to-.env>", file=sys.stderr)
        return 2
    path = Path(args[0])
    try:
        # utf-8-sig drops a leading BOM, which would otherwise join the first key.
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        print(f"dotenv_exports: {path} is not valid UTF-8", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"dotenv_exports: cannot read {path}: {exc.strerror or exc}", file=sys.stderr)
        return 1
    environment = dict(os.environ)
    # serve.sh runs this from the checkout, so `$PWD` resolves against it.
    environment.setdefault("PWD", os.getcwd())
    exports = "".join(f"export {name}={shlex.quote(value)}\n" for name, value in parse_dotenv(text, environment))
    # Bytes with "\n" endings: Windows text mode would add a "\r" to every value.
    sys.stdout.buffer.write(exports.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
