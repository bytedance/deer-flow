#!/usr/bin/env python3
"""Resolve uv extras for local `uv sync` based on environment + config.yaml.

Order of resolution:
1. `UV_EXTRAS` env var. Comma- or whitespace-separated names so multiple
   extras can be layered (e.g. ``UV_EXTRAS=postgres,ollama``). The same
   parsing semantics apply in the Docker dev container via
   ``docker/dev-entrypoint.sh``. The Docker image-build path
   (``backend/Dockerfile``) still treats `UV_EXTRAS` as a single token, so
   ``UV_EXTRAS=postgres,ollama`` would only install ``postgres,ollama`` as
   one (invalid) extra at build time — author build-time values as a
   single name.
2. Auto-detection from config.yaml — currently maps:
   - database.backend == postgres        -> postgres
   - checkpointer.type == postgres       -> postgres

Each extra name is validated against ``^[A-Za-z][A-Za-z0-9_-]*$`` (the same
shape uv enforces for `[project.optional-dependencies]` keys). Anything else
is dropped with a stderr warning so a stray shell metacharacter in `.env`
cannot reach the `uv sync` invocation downstream.

Output: space-separated `--extra <name>` flags ready for splat into
`uv sync`, e.g. `--extra postgres`. Empty output means "no extras".

Intentionally implemented with the standard library only: this script must run
*before* `uv sync` has populated the venv, so it cannot depend on PyYAML.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Mirrors uv's accepted shape for extra names — keeps the eventual
# `uv sync --extra <name>` invocation free of shell metacharacters even when
# `UV_EXTRAS` comes from `.env` or another semi-trusted source.
_EXTRA_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def _validate_extras(names: list[str]) -> list[str]:
    valid: list[str] = []
    for name in names:
        if _EXTRA_NAME_RE.match(name):
            valid.append(name)
        else:
            print(
                f"detect_uv_extras: ignoring invalid UV_EXTRAS entry {name!r} (must match [A-Za-z][A-Za-z0-9_-]*)",
                file=sys.stderr,
            )
    return valid


def parse_env_extras(value: str) -> list[str]:
    """Split UV_EXTRAS into a list, accepting comma or whitespace separators."""
    parts = re.split(r"[\s,]+", value.strip())
    return _validate_extras([p for p in parts if p])


def find_config_file() -> Path | None:
    """Locate config.yaml using the same precedence as serve.sh."""
    explicit = os.environ.get("DEER_FLOW_CONFIG_PATH")
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return candidate
    for path in (Path("config.yaml"), Path("backend/config.yaml")):
        if path.is_file():
            return path
    return None


_SECTION_RE = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*$")
_KEY_RE = re.compile(r"^\s+([A-Za-z_][\w-]*)\s*:\s*(\S.*?)\s*$")


def _strip_comment(line: str) -> str:
    """Drop trailing `#` comments while preserving `#` inside quoted strings."""
    in_quote: str | None = None
    out: list[str] = []
    for ch in line:
        if in_quote is not None:
            out.append(ch)
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ("'", '"'):
            in_quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def section_value(lines: list[str], section: str, key: str) -> str | None:
    """Return the value of `section.key` from a flat-ish YAML, or None.

    Only handles the shallow shape DeerFlow uses for these settings:
        database:
          backend: postgres
    Nested mappings deeper than the immediate child level are ignored on
    purpose — that keeps this parser predictable without a full YAML stack.
    """
    inside = False
    child_indent: int | None = None
    for raw in lines:
        line = _strip_comment(raw)
        if not line.strip():
            continue
        sect_match = _SECTION_RE.match(line)
        if sect_match:
            inside = sect_match.group(1) == section
            child_indent = None
            continue
        if not inside:
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if indent == 0:
            inside = False
            continue
        if child_indent is None:
            child_indent = indent
        if indent < child_indent:
            inside = False
            continue
        if indent != child_indent:
            continue
        key_match = _KEY_RE.match(line)
        if key_match and key_match.group(1) == key:
            return _unquote(key_match.group(2).strip())
    return None


def detect_from_config(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    extras: set[str] = set()
    if (section_value(lines, "database", "backend") or "").lower() == "postgres":
        extras.add("postgres")
    if (section_value(lines, "checkpointer", "type") or "").lower() == "postgres":
        extras.add("postgres")
    return sorted(extras)


def resolve_extras() -> list[str]:
    env = os.environ.get("UV_EXTRAS", "")
    if env.strip():
        return parse_env_extras(env)
    config = find_config_file()
    if config is None:
        return []
    return detect_from_config(config)


def format_flags(extras: list[str]) -> str:
    return " ".join(f"--extra {e}" for e in extras)


def main() -> int:
    extras = resolve_extras()
    if extras:
        sys.stdout.write(format_flags(extras))
    return 0


if __name__ == "__main__":
    sys.exit(main())
