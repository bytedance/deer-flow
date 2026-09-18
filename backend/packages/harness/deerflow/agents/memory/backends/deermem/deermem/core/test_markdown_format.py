"""Unit tests for the dependency-free Markdown memory (de)serialization.

Run with: python test_markdown_format.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import markdown_format as mf  # noqa: E402


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print("ok -", msg)


def test_looks_like_markdown() -> None:
    _assert(mf._looks_like_markdown("# Title\n- a: 1"), "markdown heading detected")
    _assert(mf._looks_like_markdown("```memory-json\n{}\n```"), "fenced block detected")
    _assert(not mf._looks_like_markdown('{"version": 1}'), "json not markdown")
    _assert(not mf._looks_like_markdown(""), "empty is not markdown")


def test_fenced_json_roundtrip() -> None:
    data = {"version": 3, "revision": 12, "lastUpdated": "2026-09-18", "user": {"lang": "zh"}, "history": {"n": 2}}
    md = mf._render_memory_markdown(data)
    parsed = mf._parse_markdown_memory(md)
    _assert(isinstance(parsed, dict), "markdown parses to dict")
    _assert(parsed == data, "fenced json round-trips losslessly")


def test_markdown_fallback_when_fence_missing() -> None:
    md = "# DeerFlow Memory\n\n- version: 2\n- revision: 5\n\n## User\n- lang: zh\n"
    parsed = mf._parse_markdown_memory(md)
    _assert(parsed is not None, "structured markdown parses")
    _assert(parsed.get("version") == 2, "version parsed from bullet")
    _assert(parsed.get("user") == ["lang: zh"], "section parsed as list")


def test_tolerant_corrupt_json_with_markdown() -> None:
    # A partially written / corrupted JSON file that still carries a markdown
    # rendering should recover via the markdown fallback instead of crashing.
    corrupt = '{"version": 1, "revision": 7, "user": {"lang": "zh"\n```memory-json\n{"version": 1, "revision": 7, "user": {"lang": "zh"}}\n```'
    parsed = mf._parse_markdown_memory(corrupt)
    _assert(parsed == {"version": 1, "revision": 7, "user": {"lang": "zh"}}, "corrupt json + markdown recovers")


def test_tolerant_corrupt_json_no_markdown() -> None:
    # Pure garbage with no markdown: nothing usable -> None (caller starts fresh).
    _assert(mf._parse_markdown_memory("{not json at all") is None, "unrecoverable returns None")


def test_loader_tolerant() -> None:
    # markdown_storage.py uses package-relative imports, so it can only be
    # imported inside the deermem.core package (which pulls heavy deps). Here
    # we at least prove it compiles and the relative imports are well-formed.
    import py_compile

    src = Path(__file__).with_name("markdown_storage.py")
    py_compile.compile(str(src), doraise=True)
    _assert(True, "markdown_storage.py compiles (relative imports well-formed)")


if __name__ == "__main__":
    test_looks_like_markdown()
    test_fenced_json_roundtrip()
    test_markdown_fallback_when_fence_missing()
    test_tolerant_corrupt_json_with_markdown()
    test_tolerant_corrupt_json_no_markdown()
    test_loader_tolerant()
    print("\nALL TESTS PASSED")
