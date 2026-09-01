"""Shared host→virtual output-path matching rules.

The boundary and tail are deliberately private. Callers use either
``build_output_mask_pattern`` for low-cardinality stable roots or
``replace_output_path_matches`` for high-cardinality dynamic roots, so a third
site cannot hand-roll a variant that drifts from the other two.

Two independent call sites rewrite host paths back to their virtual form in
text that flows to the model: ``LocalSandbox`` and ``sandbox.tools``. They must
agree on where a host base is allowed to end, because both feed the same
downstream contract — a match that stops short of a real segment boundary is
rewritten to a container path that forward resolution then refuses to map back.

Keeping one copy of that rule per file is what let it drift: #4035 added the
segment boundary to the reverse patterns and missed the masking patterns, and
#4053 had to add the same boundary to the other copy. This module holds the
rule once so a third copy cannot silently disagree.

The two sites are *not* identical, and the difference is deliberate — see
``separator_agnostic``.
"""

from __future__ import annotations

import re
from collections.abc import Callable

# Only match where a host base ends at a real path-segment boundary, so a mount
# root does not match inside a sibling that merely shares its prefix
# (``.../skills`` inside ``.../skills-extra``).
#
# The class is text-oriented, not shell-oriented (contrast
# ``LocalSandbox._command_pattern``): both callers run over arbitrary command
# output or file listings, where a root can legitimately be followed by ``,``
# ``:`` or ``\``, all of which a shell-oriented class would reject.
#
# ``$`` is load-bearing: output ending exactly at a mount root would otherwise
# fail the lookahead and be emitted as the raw host path.
_SEGMENT_BOUNDARY = r"(?=/|$|[^\w./-])"

# The path tail following the base. ``[/\\]`` keeps Windows-separated paths
# matching; the negated class stops at whitespace and shell punctuation so a
# path embedded in a larger line is not over-consumed.
_PATH_TAIL = r"(?:[/\\][^\s\"';&|<>()]*)?"

_SEGMENT_BOUNDARY_CHAR = re.compile(r"[^\w./-]")
_PATH_TAIL_TERMINATORS = frozenset("\"';&|<>()")


def build_output_mask_pattern(base: str, *, separator_agnostic: bool = False) -> re.Pattern[str]:
    """Compile the matcher for one host ``base`` in model-visible output.

    Args:
        base: Host path root to match (already resolved by the caller).
        separator_agnostic: Accept either separator *inside* the base, so a
            base captured with ``\\`` still matches output that spells the same
            path with ``/``. ``sandbox.tools`` needs this because it derives its
            bases from ``_path_variants`` (which yields Windows-style spellings)
            and matches them against output whose separators it does not
            control. ``LocalSandbox`` does not: its bases come from filesystem
            resolution on the running platform, and relaxing them would widen
            what it masks.

    Returns:
        A compiled pattern matching ``base`` at a segment boundary, plus an
        optional path tail.
    """
    escaped = re.escape(base)
    if separator_agnostic:
        escaped = escaped.replace(r"\\", r"[/\\]")
    return re.compile(escaped + _SEGMENT_BOUNDARY + _PATH_TAIL)


def replace_output_path_matches(
    output: str,
    base: str,
    replacement: str | Callable[[str], str],
    *,
    separator_agnostic: bool = False,
) -> str:
    """Replace ``base`` path matches without compiling a path-specific regex.

    Dynamic thread roots are high-cardinality. Compiling one regex per root
    leaves those roots in Python's global ``re`` caches after DeerFlow evicts
    the owning sandbox. This scanner preserves the same boundary and path-tail
    contract while keeping no process-level reference to ``base``.
    """
    if not output or not base:
        return output

    searchable_output = output.replace("\\", "/") if separator_agnostic and "\\" in output else output
    searchable_base = base.replace("\\", "/") if separator_agnostic and "\\" in base else base
    chunks: list[str] = []
    copied_until = 0
    search_from = 0

    while True:
        match_start = searchable_output.find(searchable_base, search_from)
        if match_start < 0:
            break

        base_end = match_start + len(searchable_base)
        match_end = base_end
        if base_end < len(searchable_output):
            next_char = searchable_output[base_end]
            if next_char in "/\\":
                match_end += 1
                while match_end < len(output):
                    char = output[match_end]
                    if char.isspace() or char in _PATH_TAIL_TERMINATORS:
                        break
                    match_end += 1
            elif _SEGMENT_BOUNDARY_CHAR.fullmatch(next_char) is None:
                search_from = match_start + 1
                continue

        matched_path = output[match_start:match_end]
        if callable(replacement):
            replaced_path = replacement(matched_path)
        else:
            relative = matched_path[len(base) :].lstrip("/\\")
            replaced_path = f"{replacement}/{relative}" if relative else replacement

        chunks.append(output[copied_until:match_start])
        chunks.append(replaced_path)
        copied_until = match_end
        search_from = match_end

    if not chunks:
        return output
    chunks.append(output[copied_until:])
    return "".join(chunks)
