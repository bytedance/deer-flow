"""Tests for the shared host→virtual output-mask pattern (``sandbox/path_patterns.py``).

The rule these pin is not "the regex is correct" — that is #4035/#4053 — but
"there is exactly one copy of it, and extracting it did not change either call
site's matching". The two sites differ on one axis only (separator handling),
and that asymmetry is load-bearing: erasing it would widen ``LocalSandbox``'s
masking or narrow ``sandbox.tools``'s.

The move itself was cleared by a differential against the *real* pre-extraction
expressions, run once on the parent commit. That run cannot be committed: after
this lands there is no old inline expression left to diff against, only the
frozen copies below. So the committed guard is the weaker snapshot, and its
red-ness rests on those literals — not on the length of ``_BASES``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.path_patterns import build_output_mask_pattern
from deerflow.sandbox.tools import _compiled_mask_patterns


def _legacy_tools_pattern(base: str) -> re.Pattern[str]:
    """The expression ``_compiled_mask_patterns`` inlined before the extraction."""
    escaped = re.escape(base).replace(r"\\", r"[/\\]")
    return re.compile(escaped + r"(?=/|$|[^\w./-])" + r"(?:[/\\][^\s\"';&|<>()]*)?")


def _legacy_local_pattern(base: str) -> re.Pattern[str]:
    """The expression ``_reverse_output_patterns`` inlined before the extraction."""
    return re.compile(re.escape(base) + r"(?=/|$|[^\w./-])" + r"(?:[/\\][^\s\"';&|<>()]*)?")


_BASES = [
    "/host/skills",
    "/host/dir with spaces",
    "/host/re+meta(chars)[x]",
    "/host/dots.in.name",
    "/Users/a/.deer-flow/users/u1/threads/t1/user-data",
    "C:\\host\\skills",
    "/host/技能",
    # Drive root: the only base either caller can hand the helper that still ends in a
    # separator (``Path.resolve()`` strips them everywhere else), so it is the one shape
    # that goes red if the helper starts normalizing the base it is given.
    "C:\\",
]


@pytest.mark.parametrize("base", _BASES)
def test_helper_reproduces_the_pre_extraction_expressions(base: str) -> None:
    """Byte-identical to what each call site built inline, for both separator modes.

    This is the anchor for the move itself: edit the helper in a way that changes
    either site's regex and this goes red.
    """
    assert build_output_mask_pattern(base, separator_agnostic=True).pattern == _legacy_tools_pattern(base).pattern
    assert build_output_mask_pattern(base).pattern == _legacy_local_pattern(base).pattern


def test_separator_agnostic_is_the_only_difference_between_the_two_modes() -> None:
    """The asymmetry the helper must preserve rather than unify.

    ``sandbox.tools`` derives bases from ``_path_variants`` (Windows spellings)
    and matches them against output whose separators it does not control, so a
    ``\\``-spelled base must still match ``/``-spelled output. ``LocalSandbox``
    resolves its bases from the running platform and must not be widened.
    """
    windows_base = "C:\\host\\skills"
    posix_spelling = "C:/host/skills/file.md"

    assert build_output_mask_pattern(windows_base, separator_agnostic=True).search(posix_spelling)
    assert build_output_mask_pattern(windows_base).search(posix_spelling) is None

    # On a base with no separator ambiguity the two modes agree exactly.
    posix_base = "/host/skills"
    assert build_output_mask_pattern(posix_base, separator_agnostic=True).pattern == build_output_mask_pattern(posix_base).pattern


def test_boundary_still_rejects_prefix_siblings_and_accepts_real_segments() -> None:
    """The #4035/#4053 rule itself, now asserted once against the shared helper."""
    pattern = build_output_mask_pattern("/host/skills")

    # Matches: the root itself, a child, a Windows-separated child, and a root
    # followed by text punctuation (``$`` and the ``[^\w./-]`` class).
    assert pattern.fullmatch("/host/skills")
    assert pattern.match("/host/skills/a/b.md")
    assert pattern.match("/host/skills\\a\\b.md")
    assert pattern.search("paths: /host/skills, and more")

    # Does not match inside a sibling that merely shares the prefix.
    assert pattern.search("/host/skills-extra/file.md") is None
    assert pattern.search("/host/skills.bak") is None
    assert pattern.search("/host/skills2/file.md") is None


def test_local_sandbox_reverse_patterns_route_through_the_helper(tmp_path: Path) -> None:
    """Call-site wiring: a re-inlined copy that *diverges* from the shared rule goes red.

    It does not (and cannot) catch a byte-identical re-inline — that is not yet a
    defect. What it catches is the shape of the actual regression: #4035 changed
    one copy of the rule and left the other behind.
    """
    local = tmp_path / "skills"
    local.mkdir()
    sandbox = LocalSandbox(
        id="local",
        path_mappings=[PathMapping(container_path="/mnt/skills", local_path=str(local), read_only=True)],
    )

    resolved = str(Path(local).resolve())
    assert [p.pattern for p in sandbox._reverse_output_patterns] == [build_output_mask_pattern(resolved).pattern]


def test_tools_mask_patterns_route_through_the_helper(tmp_path: Path) -> None:
    """Same wiring check for the other copy — and it must stay separator-agnostic."""
    host = tmp_path / "skills"
    host.mkdir()

    compiled = _compiled_mask_patterns(((str(host), "/mnt/skills"),))

    assert compiled
    for pattern, variant, virtual_base in compiled:
        assert virtual_base == "/mnt/skills"
        assert pattern.pattern == build_output_mask_pattern(variant, separator_agnostic=True).pattern
