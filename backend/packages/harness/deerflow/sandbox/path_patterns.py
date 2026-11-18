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

Both sites match separator-agnostically: ``sandbox.tools`` derives its bases
from ``_path_variants``, and ``LocalSandbox``'s forward resolution spells
resolved paths with forward slashes in commands and file content, so the
reverse direction has to accept both spellings of the same host path — see
``separator_agnostic``.
"""

from __future__ import annotations

import errno
import re
from collections.abc import Callable, Sequence

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

# The mirror rule on the left: a base must start a path, not continue one.
# Without it ``/mnt/user-data`` matches inside the artifact URL
# ``.../artifacts/mnt/user-data/outputs/x.html`` or a relative
# ``backup/mnt/user-data``, and a mount at ``/data`` inside ``/var/data``.
# ``/`` is deliberately allowed so ``file:///mnt/user-data`` still maps; ``.``
# and ``~`` reject ``./`` and ``~/`` relative spellings. Forward-resolution
# patterns (container → host) in ``LocalSandbox`` and ``sandbox.tools`` share
# this rule, so it is public.
#
# Known false negative: a value attached directly to a short option
# (``curl -o/data/x``, ``ssh -i/data/key``, ``gcc -I/data/inc``) follows a
# letter, so it is left virtual instead of being translated. Spell those with a
# space (``-o /data/x``) or ``=``. Rejecting embedded roots matters more: the
# alternative rewrites unrelated paths and URLs.
#
# The scanner and the regex lookbehind derive from one character class so
# ``replace_output_path_matches`` and ``build_output_mask_pattern`` cannot drift.
_PATH_START_BLOCKERS = re.compile(r"[\w.~-]")
PATH_START_BOUNDARY = rf"(?<!{_PATH_START_BLOCKERS.pattern})"

# The path tail following the base. ``[/\\]`` keeps Windows-separated paths
# matching; the negated class stops at whitespace and shell punctuation so a
# path embedded in a larger line is not over-consumed.
#
# ``:`` ends the tail as well. Scanning resumes after a match, so a tail that
# ran on through a ``:``-joined list ($PATH, $PYTHONPATH) carried every later
# entry under the same base to the model unmasked. ``;``, the Windows list
# separator, already ended it. A ``:`` inside one path (``grep -n`` output,
# a file name) only shortens the match; the rest is copied through verbatim.
_PATH_TAIL = r"(?:[/\\][^\s\"';&|<>():]*)?"

_SEGMENT_BOUNDARY_CHAR = re.compile(r"[^\w./-]")
_PATH_TAIL_TERMINATORS = frozenset("\"';&|<>():")


def normalize_mask_tail(tail: str) -> str:
    """Normalize a matched output tail for splicing onto a virtual prefix.

    Virtual paths are always POSIX-style, so drop leading separators and
    convert any remaining backslashes (Windows-spelled output) to forward
    slashes. Shared by the static-pattern closure in ``sandbox.tools`` and
    the direct scanner here so the splicing rule exists in exactly one copy
    and the two sites can only drift in their *matching* logic.
    """
    return tail.lstrip("/\\").replace("\\", "/")


def build_output_mask_pattern(base: str, *, separator_agnostic: bool = False) -> re.Pattern[str]:
    """Compile the matcher for one host ``base`` in model-visible output.

    Args:
        base: Host path root to match (already resolved by the caller).
        separator_agnostic: Accept either separator *inside* the base, so a
            base captured with ``\\`` still matches output that spells the same
            path with ``/``. Both call sites need this: ``sandbox.tools``
            derives its bases from ``_path_variants`` (which yields
            Windows-style spellings) and matches them against output whose
            separators it does not control, and ``LocalSandbox``'s forward
            resolution emits forward-slash spellings on Windows even though its
            bases are resolved with native separators.

    Returns:
        A compiled pattern matching ``base`` where it starts a path and ends
        at a segment boundary, plus an optional path tail.
    """
    escaped = re.escape(base)
    if separator_agnostic:
        escaped = escaped.replace(r"\\", r"[/\\]")
    return re.compile(PATH_START_BOUNDARY + escaped + _SEGMENT_BOUNDARY + _PATH_TAIL)


def _next_path_match(output: str, searchable_output: str, searchable_base: str, search_from: int) -> tuple[int, int] | None:
    """Return the ``(start, end)`` of the next match for one base, or ``None``.

    A match is a base occurrence that starts a path (not inside a longer
    word) and ends at a segment boundary, plus the path tail up to the next
    terminator. Candidates that fail the boundary are skipped, not returned,
    so the caller never sees a prefix sibling as a match.
    """
    while True:
        match_start = searchable_output.find(searchable_base, search_from)
        if match_start < 0:
            return None
        if match_start > 0 and _PATH_START_BLOCKERS.fullmatch(searchable_output[match_start - 1]):
            search_from = match_start + 1
            continue

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

        return match_start, match_end


def replace_output_path_matches(
    output: str,
    base: str,
    replacement: str | Callable[[str], str],
    *,
    separator_agnostic: bool = False,
    max_bytes: int | None = None,
) -> str:
    """Replace ``base`` path matches without compiling a path-specific regex.

    Dynamic thread roots are high-cardinality. Compiling one regex per root
    leaves those roots in Python's global ``re`` caches after DeerFlow evicts
    the owning sandbox. This scanner preserves the same boundary and path-tail
    contract while keeping no process-level reference to ``base``.

    ``max_bytes`` bounds the substituted output in bytes: the budget is
    enforced while the pieces are appended, so a caller that refuses an
    oversized result never materializes the expanded string first. A
    replacement that would push the running total past the budget raises
    ``OSError`` (``EFBIG``) at that match instead of completing the scan.
    """
    if not output or not base:
        return output

    searchable_output = output.replace("\\", "/") if separator_agnostic and "\\" in output else output
    searchable_base = base.replace("\\", "/") if separator_agnostic and "\\" in base else base
    chunks: list[str] = []
    copied_until = 0
    search_from = 0
    budgeted_size = 0

    def _append(piece: str) -> None:
        nonlocal budgeted_size
        chunks.append(piece)
        if max_bytes is not None:
            budgeted_size += len(piece.encode("utf-8"))
            if budgeted_size > max_bytes:
                raise OSError(errno.EFBIG, f"Substituted output exceeds maximum size of {max_bytes} bytes")

    while True:
        found = _next_path_match(output, searchable_output, searchable_base, search_from)
        if found is None:
            break
        match_start, match_end = found

        matched_path = output[match_start:match_end]
        if callable(replacement):
            replaced_path = replacement(matched_path)
        else:
            relative = normalize_mask_tail(matched_path[len(base) :])
            replaced_path = f"{replacement}/{relative}" if relative else replacement

        _append(output[copied_until:match_start])
        _append(replaced_path)
        copied_until = match_end
        search_from = match_end

    if not chunks:
        if max_bytes is not None and len(output.encode("utf-8")) > max_bytes:
            raise OSError(errno.EFBIG, f"Substituted output exceeds maximum size of {max_bytes} bytes")
        return output
    _append(output[copied_until:])
    return "".join(chunks)


def replace_output_path_matches_all(
    output: str,
    bases: Sequence[str],
    replacement: Callable[[str], str],
    *,
    separator_agnostic: bool = False,
    max_bytes: int | None = None,
) -> str:
    """Replace path matches for several bases in a single left-to-right scan.

    Same boundary and path-tail contract as ``replace_output_path_matches``,
    shared through ``_next_path_match`` so the two cannot drift. The scan
    differs in one way only: the budget applies to the fully substituted
    output, not to an intermediate pass. When an early base expands a path
    and a later base contracts others, a per-pass cap rejects an
    intermediate string the caller never sees; here the ceiling sees the
    net result (#8260, willem-bd P2). Allocation stays bounded all the same
    — the output is built piece by piece under one running budget, so a
    refused payload is never materialized. At the same start the longest
    base wins, matching the longest-local-first pass order of the sequential
    form; scanning resumes after each match, so replacement text is never
    rewritten a second time.
    """
    if not output or not bases:
        return output

    searchable_output = output.replace("\\", "/") if separator_agnostic and "\\" in output else output
    searchable_bases = [base.replace("\\", "/") if separator_agnostic and "\\" in base else base for base in bases]
    chunks: list[str] = []
    copied_until = 0
    search_from = 0
    budgeted_size = 0

    def _append(piece: str) -> None:
        nonlocal budgeted_size
        chunks.append(piece)
        if max_bytes is not None:
            budgeted_size += len(piece.encode("utf-8"))
            if budgeted_size > max_bytes:
                raise OSError(errno.EFBIG, f"Substituted output exceeds maximum size of {max_bytes} bytes")

    while True:
        best_start = -1
        best_end = -1
        best_base_len = -1
        for searchable_base in searchable_bases:
            found = _next_path_match(output, searchable_output, searchable_base, search_from)
            if found is None:
                continue
            start, end = found
            if best_start < 0 or start < best_start or (start == best_start and len(searchable_base) > best_base_len):
                best_start, best_end, best_base_len = start, end, len(searchable_base)
        if best_start < 0:
            break

        matched_path = output[best_start:best_end]
        replaced_path = replacement(matched_path)

        _append(output[copied_until:best_start])
        _append(replaced_path)
        copied_until = best_end
        search_from = best_end

    if not chunks:
        if max_bytes is not None and len(output.encode("utf-8")) > max_bytes:
            raise OSError(errno.EFBIG, f"Substituted output exceeds maximum size of {max_bytes} bytes")
        return output
    _append(output[copied_until:])
    return "".join(chunks)
