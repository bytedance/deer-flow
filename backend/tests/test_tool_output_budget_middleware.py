"""Comprehensive tests for ToolOutputBudgetMiddleware.

Covers: pass-through, disk externalization, fallback truncation, UTF-8
boundaries, Command results, model-request history patching, config
variations, exempt tools, per-tool overrides, edge cases, and both
sync/async code paths.
"""

from __future__ import annotations

import json
import os
import tempfile
from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from deerflow.agents.middlewares.tool_output_budget_middleware import (
    ToolOutputBudgetMiddleware,
    _build_fallback,
    _build_preview,
    _effective_trigger,
    _externalize,
    _message_text,
    _needs_budget,
    _patch_model_messages,
    _sanitize_tool_name,
    _snap_start_to_line_boundary,
    _snap_to_line_boundary,
    _tool_message_over_budget,
)
from deerflow.agents.middlewares.tool_output_synopsis import build_tool_output_synopsis
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.tool_output_config import ToolOutputConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lines_then_long_line(total: int, newline_ratio: float = 0.6) -> str:
    """Content that is line-oriented for the first *newline_ratio*, then one unbroken line.

    Mirrors real bash/web_fetch output that logs progress lines and then dumps a
    single-line artifact (minified JSON, base64 blob). The last newline lands in
    the second half of the content, which is what exercises line snapping around
    the tail offset.
    """
    head_len = int(total * newline_ratio)
    lines = "".join(f"[info] step {i} ok\n" for i in range(head_len // 18 + 1))[:head_len]
    lines = lines[:-1] + "\n" if not lines.endswith("\n") else lines
    return lines + "A" * (total - len(lines))


def _make_request(tool_name: str = "remote_executor", tool_call_id: str = "tc-1", outputs_path: str | None = None) -> SimpleNamespace:
    thread_data = {"outputs_path": outputs_path} if outputs_path else None
    state = {"thread_data": thread_data} if thread_data else {}
    runtime = SimpleNamespace(state=state)
    return SimpleNamespace(
        tool_call={"name": tool_name, "id": tool_call_id},
        runtime=runtime,
    )


def _tm(content: str = "ok", name: str = "tool", tool_call_id: str = "tc-1") -> ToolMessage:
    return ToolMessage(content=content, name=name, tool_call_id=tool_call_id)


# ===========================================================================
# Unit tests for helper functions
# ===========================================================================


class TestMessageText:
    def test_string_content(self):
        assert _message_text("hello") == "hello"

    def test_none_content(self):
        assert _message_text(None) is None

    def test_list_of_strings(self):
        assert _message_text(["a", "b"]) == "a\nb"

    def test_list_of_text_dicts(self):
        assert _message_text([{"text": "x"}, {"text": "y"}]) == "x\ny"

    def test_list_with_image_returns_none(self):
        assert _message_text([{"type": "image", "data": "..."}]) is None

    def test_empty_list(self):
        assert _message_text([]) is None

    def test_non_string_non_list(self):
        assert _message_text(42) is None


class TestSnapToLineBoundary:
    def test_snaps_to_newline(self):
        text = "line1\nline2\nline3"
        pos = 14  # inside "line3"
        result = _snap_to_line_boundary(text, pos)
        assert text[result - 1] == "\n"

    def test_no_snap_when_no_newline_in_range(self):
        text = "abcdefghij"
        assert _snap_to_line_boundary(text, 8) == 8

    def test_zero_pos(self):
        assert _snap_to_line_boundary("abc", 0) == 0

    def test_pos_beyond_length(self):
        assert _snap_to_line_boundary("abc", 10) == 10


class TestSnapStartToLineBoundary:
    def test_snaps_forward_to_newline(self):
        text = "line1\nline2\nline3"
        result = _snap_start_to_line_boundary(text, 2)  # inside "line1"
        assert text[result - 1] == "\n"
        assert result >= 2

    def test_never_moves_backwards(self):
        text = "aaaa\n" + "b" * 20
        for pos in range(1, len(text)):
            assert _snap_start_to_line_boundary(text, pos) >= pos

    def test_no_snap_when_no_newline_in_range(self):
        assert _snap_start_to_line_boundary("abcdefghij", 2) == 2

    def test_zero_pos(self):
        assert _snap_start_to_line_boundary("a\nbc", 0) == 0

    def test_pos_beyond_length(self):
        assert _snap_start_to_line_boundary("abc", 10) == 10


class TestExternalize:
    def test_writes_file_and_returns_virtual_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _externalize(
                "full content here",
                tool_name="bash",
                tool_call_id="tc-1",
                outputs_path=tmpdir,
                storage_subdir=".tool-results",
            )
            assert path is not None
            assert path.startswith("/mnt/user-data/outputs/.tool-results/bash-")
            assert path.endswith(".log")

            # Verify actual file on disk
            storage_dir = os.path.join(tmpdir, ".tool-results")
            files = os.listdir(storage_dir)
            assert len(files) == 1
            with open(os.path.join(storage_dir, files[0]), encoding="utf-8") as f:
                assert f.read() == "full content here"

    def test_returns_none_on_invalid_path(self):
        # ``/dev/null`` is a character device on both Linux and macOS, so
        # ``os.makedirs`` cannot create any subdirectory under it for any
        # user (including root). The previously-used ``/nonexistent/...``
        # path was silently created by ``mkdir -p`` when the test process
        # ran as root inside the CI container, which made this test fail
        # in CI independently of the externalization logic under test.
        path = _externalize(
            "data",
            tool_name="test",
            tool_call_id="tc-1",
            outputs_path="/dev/null/cannot-mkdir-here",
            storage_subdir=".tool-results",
        )
        assert path is None

    def test_txt_extension_for_unknown_tool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _externalize(
                "data",
                tool_name="unknown_tool",
                tool_call_id="tc-1",
                outputs_path=tmpdir,
                storage_subdir=".tool-results",
            )
            assert path is not None
            assert path.endswith(".txt")


class TestSanitizeToolName:
    def test_strips_path_separators(self):
        assert _sanitize_tool_name("../../etc/passwd") == "passwd"

    def test_strips_backslashes(self):
        result = _sanitize_tool_name("..\\..\\windows\\system32")
        assert ".." not in result
        assert "/" not in result

    def test_normal_name_unchanged(self):
        assert _sanitize_tool_name("bash") == "bash"

    def test_empty_becomes_unknown(self):
        assert _sanitize_tool_name("") == "unknown"

    def test_dots_only_becomes_unknown(self):
        assert _sanitize_tool_name("..") == "unknown"


class TestExternalizePathTraversal:
    def test_traversal_tool_name_is_sanitized(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _externalize(
                "data",
                tool_name="../../etc/passwd",
                tool_call_id="tc-1",
                outputs_path=tmpdir,
                storage_subdir=".tool-results",
            )
            assert path is not None
            assert "passwd-" in path
            assert "../" not in path

    def test_absolute_storage_subdir_rejected(self):
        path = _externalize(
            "data",
            tool_name="tool",
            tool_call_id="tc-1",
            outputs_path="/tmp",
            storage_subdir="/etc/evil",
        )
        assert path is None

    def test_traversal_storage_subdir_rejected(self):
        path = _externalize(
            "data",
            tool_name="tool",
            tool_call_id="tc-1",
            outputs_path="/tmp",
            storage_subdir="../../../etc",
        )
        assert path is None


class TestNeedsBudget:
    def test_small_output_does_not_need_budget(self):
        config = ToolOutputConfig(externalize_min_chars=1000)
        msg = _tm("small", name="tool")
        assert _needs_budget(msg, config) is False

    def test_large_output_needs_budget(self):
        config = ToolOutputConfig(externalize_min_chars=50)
        msg = _tm("x" * 100, name="tool")
        assert _needs_budget(msg, config) is True

    def test_exempt_tool_does_not_need_budget(self):
        config = ToolOutputConfig(externalize_min_chars=10)
        msg = _tm("x" * 100, name="read_file")
        assert _needs_budget(msg, config) is False

    def test_multimodal_does_not_need_budget(self):
        config = ToolOutputConfig(externalize_min_chars=10)
        msg = ToolMessage(content=[{"type": "image", "data": "x" * 100}], name="tool", tool_call_id="tc-1")
        assert _needs_budget(msg, config) is False


class TestBuildPreview:
    def test_contains_typed_summary_and_reference(self):
        content = "HEAD_" + "x" * 5000 + "_TAIL"
        preview = _build_preview(
            content,
            tool_name="bash",
            virtual_path="/mnt/test/bash-abc.log",
            head_chars=100,
            tail_chars=50,
        )
        assert preview.startswith("[Full bash output saved to /mnt/test/bash-abc.log")
        assert "Preview kind: text" in preview
        assert "Text output" in preview
        assert "/mnt/test/bash-abc.log" in preview
        assert "read_file" in preview
        assert "start_line and end_line" in preview

    def test_reports_total_chars(self):
        content = "a" * 10000
        preview = _build_preview(
            content,
            tool_name="web_search",
            virtual_path="/mnt/test/file.txt",
            head_chars=200,
            tail_chars=100,
        )
        assert "10000 chars" in preview

    def test_json_preview_includes_structure_and_raw_sample(self):
        content = '{"meta":{"source":"unit"},"items":[{"id":1,"name":"alpha"},{"id":2,"name":"beta"}],"payload":"' + "x" * 5000 + '","tail_marker":"SHOULD_NOT_NEED_TAIL"}'
        preview = _build_preview(
            content,
            tool_name="mcp_json",
            virtual_path="/mnt/test/result.json",
            head_chars=80,
            tail_chars=40,
        )
        assert "Preview kind: json" in preview
        assert "JSON object with 4 top-level keys" in preview
        assert "Top-level keys: meta, items, payload, tail_marker" in preview
        assert "items: array length 2" in preview
        assert '$.meta.source: "unit"' in preview
        assert not preview.startswith('{"meta"')
        # The synopsis no longer hides the raw head/tail bytes; the model
        # gets the typed synopsis AND inline raw samples so it can read
        # the file with a tighter start_line range.
        assert "Raw sample (head + tail" in preview
        # payload segment dominates the document, so even with head_chars=80
        # the raw head sample is almost entirely 'x' characters.
        assert preview.count("x") >= 50

    def test_json_preview_reports_nested_paths_and_line_hints(self):
        content = json.dumps(
            {
                "data": {
                    "items": [{"id": idx, "name": f"item-{idx}"} for idx in range(47)],
                    "next_cursor": "cursor-2",
                },
                "meta": {"source": "unit"},
            },
            indent=2,
        )
        preview = _build_preview(
            content,
            tool_name="api_tool",
            virtual_path="/mnt/test/api.json",
            head_chars=80,
            tail_chars=40,
        )
        assert "$.data: object keys 2; keys items, next_cursor" in preview
        assert "$.data.items: array length 47; first item object" in preview
        # Location hints were removed: they are wrong when a key string also
        # appears as a value earlier in the document, or when the same key
        # recurs at multiple depths.
        assert "line " not in preview.split("Access:")[0]
        assert "byte offset " not in preview

    def test_json_paths_are_emitted_without_line_hints(self):
        content = "\n\n" + json.dumps({"data": {"items": [1, 2, 3]}}, indent=2)
        preview = _build_preview(
            content,
            tool_name="api_tool",
            virtual_path="/mnt/test/api.json",
            head_chars=80,
            tail_chars=40,
        )
        assert "$.data: object keys 1; keys items" in preview
        assert "line " not in preview.split("Access:")[0]
        assert "byte offset " not in preview

    def test_table_preview_extracts_columns(self):
        content = "name,score\n" + "\n".join(f"Ada{i},{90 + i}" for i in range(10)) + "\n"
        preview = _build_preview(
            content,
            tool_name="csv_tool",
            virtual_path="/mnt/test/table.csv",
            head_chars=80,
            tail_chars=40,
        )
        assert "Preview kind: csv" in preview
        assert "CSV table with 10 data rows and 2 columns" in preview
        assert "columns: name, score" in preview
        assert "first data row: name=Ada0 | score=90" in preview


class TestToolOutputSynopsis:
    def test_code_synopsis_extracts_imports_and_symbols(self):
        content = "import os\nfrom pathlib import Path\n\nclass Runner:\n    pass\n\ndef main():\n    return Path(os.getcwd())\n"
        synopsis = build_tool_output_synopsis(content, tool_name="python")
        assert synopsis.kind == "code"
        assert "line count" in synopsis.structure[0]
        assert any("imports: os, pathlib" in item for item in synopsis.structure)
        assert "class Runner" in synopsis.notable_items
        assert "def main" in synopsis.notable_items

    def test_yaml_synopsis_extracts_top_level_keys(self):
        content = "name: deer\nsettings:\n  enabled: true\n  retries: 3\nitems:\n  - alpha\n"
        synopsis = build_tool_output_synopsis(content, tool_name="config")
        assert synopsis.kind == "yaml"
        assert "Top-level keys: name, settings, items" in synopsis.summary
        assert "settings: object" in synopsis.structure
        assert "items: array" in synopsis.structure

    def test_xml_synopsis_extracts_root_and_children(self):
        content = '<feed><entry id="1"/><entry id="2"/><meta/></feed>'
        synopsis = build_tool_output_synopsis(content, tool_name="xml")
        assert synopsis.kind == "xml"
        assert "XML document with root tag feed." in synopsis.summary
        assert "root tag: feed" in synopsis.structure
        assert "entry: 2" in synopsis.structure

    # ------------------------------------------------------------------
    # Regression tests for the @willem-bd review of PR #3377.
    # Each test pins one of the eight findings so a future change cannot
    # silently regress the fix.
    # ------------------------------------------------------------------

    def test_review_5_log_lines_are_not_misclassified_as_yaml(self):
        # 200 lines of log output shaped like "LEVEL: message". The previous
        # _looks_yaml counted 2 'key:' lines and accepted it; _try_yaml then
        # produced a "YAML object with 3 top-level keys: INFO, ERROR, WARN"
        # summary that hid every line, count, and middle-of-log signal.
        content = "INFO: starting service\nERROR: failed to connect\nWARN: retrying\nINFO: connected\n" * 200
        synopsis = build_tool_output_synopsis(content, tool_name="bash")
        assert synopsis.kind == "text", f"expected text, got {synopsis.kind!r}: {synopsis.summary}"

    def test_review_6_json_paths_are_emitted_without_byte_offset(self):
        # The previous _json_path_location anchored at the first textual
        # occurrence of the key string, which is wrong when the key also
        # appears as a value earlier in the document.
        content = '{"label": "items", "items": {"id": 1, "name": "foo"}}'
        preview = _build_preview(
            content,
            tool_name="api_tool",
            virtual_path="/mnt/test/api.json",
            head_chars=200,
            tail_chars=200,
        )
        assert "byte offset" not in preview
        # The path itself is still useful navigation.
        assert "$.items" in preview

    def test_review_7_scalar_examples_respects_depth_cap(self):
        # build_tool_output_synopsis used to recurse without a depth cap
        # in _scalar_examples, which could trigger RecursionError on
        # deeply nested JSON. The cap is now mirrored from
        # _JSON_STRUCTURE_DEPTH.
        deep = {"k": 1}
        for _ in range(500):
            deep = {"k": deep}
        # Should not raise.
        synopsis = build_tool_output_synopsis(json.dumps(deep))
        assert synopsis.kind == "json"

    def test_review_8_csv_first_row_quoted_cells_round_trip(self):
        # delimiter.join(rows[1]) silently re-split cells containing the
        # delimiter inside a quoted cell, misleading the model about
        # column count.
        header = "name,description,score"
        rows = [
            'Ada,"a fine, brilliant logician",98',
            'Grace,"a creator, of compilers",99',
            'Alan,"a pioneer, of computing",95',
            'Kurt,"a poet, of logic",91',
            'Ada2,"another, fine mind",97',
            'Grace2,"yet another, creator",93',
        ]
        content = header + "\n" + "\n".join(rows) + "\n"
        synopsis = build_tool_output_synopsis(content, tool_name="csv_tool")
        assert synopsis.kind == "csv"
        first_row = next((line for line in synopsis.structure if line.startswith("first data row:")), "")
        # All three columns must be present, and the quoted cell must
        # round-trip without losing the embedded comma.
        assert "name=Ada" in first_row
        assert "score=98" in first_row
        assert "a fine, brilliant logician" in first_row
        # The re-joined comma-broken row is the failure mode we are guarding.
        assert "Ada,a fine, brilliant" not in first_row

    def test_review_9_tsv_detector_rejects_tab_indented_bash(self):
        # Tab-indented output (ls -l, tree, indented logs) used to be
        # accepted as TSV because _try_table only checked that the
        # delimiter is present and rows agree on width.
        row = "drwxr-xr-x  2 user  group   64 Jun 24 17:00 dir"
        bash_out = "ls -l output:\n\ttotal 0\n" + "\n".join(f"\t{row}{i}" for i in range(1, 6)) + "\n"
        synopsis = build_tool_output_synopsis(bash_out, tool_name="bash")
        assert synopsis.kind == "text", f"expected text, got {synopsis.kind!r}: {synopsis.summary}"

    def test_review_10_preview_includes_raw_head_and_tail_sample(self):
        # Default behavior change in the PR removed the inline raw bytes
        # for non-binary previews. The fix restores them so the model
        # can see the actual first/last KB without a follow-up read_file.
        content = "log line 1\n" * 200
        preview = _build_preview(
            content,
            tool_name="bash",
            virtual_path="/mnt/test/run.log",
            head_chars=400,
            tail_chars=400,
        )
        assert "Raw sample (head + tail" in preview
        # head_chars=400 should capture the first 80 'log line 1' lines
        # verbatim; tail_chars=400 should capture the last 80.
        assert preview.count("log line 1") >= 70  # line snapping may lose a few

    def test_review_11_short_text_does_not_duplicate_excerpts(self):
        # For inputs shorter than 2 * _TEXT_EXCERPT_CHARS, the previous
        # opener/closer slices overlapped and the model saw the same
        # body twice. build_tool_output_synopsis is reachable directly
        # from tests and other callers that pass small inputs.
        short = "hello world " * 30  # ~360 chars
        synopsis = build_tool_output_synopsis(short)
        opener_line = next((ln for ln in synopsis.summary if ln.startswith("Opening excerpt: ")), "")
        # Closer is now suppressed entirely for short inputs.
        assert all(not ln.startswith("Closing excerpt: ") for ln in synopsis.summary), f"unexpected closer for short input: {synopsis.summary}"
        assert opener_line, "opening excerpt should still be present"

    def test_review_12_preview_head_tail_chars_are_operational(self):
        # preview_head_chars / preview_tail_chars were silently no-op
        # for every non-binary kind. The fix plumbs them through
        # render_tool_output_preview as an explicit 'Raw sample' section.
        content = "alpha " * 1000  # 6000 chars
        preview = _build_preview(
            content,
            tool_name="bash",
            virtual_path="/mnt/test/run.log",
            head_chars=300,
            tail_chars=300,
        )
        # The head sample should contain 'alpha' more times than the
        # tail (or split-count), proving head_chars=300 took effect.
        # The full document has 1000 'alpha' tokens; without head_chars
        # we'd see fewer than 50 in the head sample.
        assert preview.count("alpha") >= 50


class TestBuildFallback:
    def test_short_content_unchanged(self):
        assert _build_fallback("short", tool_name="t", max_chars=100, head_chars=50, tail_chars=50) == "short"

    def test_zero_max_disables(self):
        content = "a" * 1000
        assert _build_fallback(content, tool_name="t", max_chars=0, head_chars=50, tail_chars=50) == content

    def test_truncates_long_content(self):
        content = "H" * 5000 + "M" * 20000 + "T" * 5000
        result = _build_fallback(content, tool_name="bash", max_chars=12000, head_chars=6000, tail_chars=3000)
        assert len(result) < len(content)
        assert "omitted from bash output" in result
        assert "Persistent storage unavailable" in result

    def test_preserves_head_and_tail(self):
        content = "HEADSTART" + "x" * 50000 + "TAILEND"
        result = _build_fallback(content, tool_name="t", max_chars=20000, head_chars=10000, tail_chars=5000)
        assert result.startswith("HEADSTART")
        assert "TAILEND" in result

    def test_result_never_exceeds_max_chars(self):
        """The marker itself has non-zero length; total must still respect max_chars."""
        for max_chars in [200, 500, 1000, 5000, 20000]:
            content = "x" * 50000
            result = _build_fallback(content, tool_name="long_tool_name", max_chars=max_chars, head_chars=max_chars // 2, tail_chars=max_chars // 4)
            assert len(result) <= max_chars, f"max_chars={max_chars}: got {len(result)}"

    def test_result_never_exceeds_max_chars_with_newlines(self):
        """Same guarantee as above, on content that actually exercises line snapping.

        ``test_result_never_exceeds_max_chars`` passes newline-free content, so the
        tail offset is never snapped. Real bash/web_fetch output has newlines.
        """
        for total in [50_000, 200_000, 1_000_000]:
            content = _lines_then_long_line(total)
            result = _build_fallback(content, tool_name="bash", max_chars=30_000, head_chars=8_000, tail_chars=3_000)
            assert len(result) <= 30_000, f"total={total}: got {len(result)}"

    def test_fallback_forward_snaps_tail_onto_line_boundary(self):
        """The tail must begin *after* the newline, never before it.

        The bound test above never moves the tail offset: its content has no
        newline inside the snap window, so it would pass even with the snap
        removed. Placing a newline in the window pins the direction instead —
        a backward snap leaves the tail starting mid-line.
        """
        total, newline_pos = 100_000, 98_000  # window is [97_000, 98_500)
        content = "A" * newline_pos + "\n" + "B" * (total - newline_pos - 1)
        result = _build_fallback(content, tool_name="bash", max_chars=30_000, head_chars=8_000, tail_chars=3_000)
        assert len(result) <= 30_000
        tail = result.rsplit("]\n\n", 1)[1]
        assert tail.startswith("B"), f"tail begins mid-line: {tail[:20]!r}"

    def test_very_small_max_chars_does_not_crash(self):
        content = "x" * 1000
        result = _build_fallback(content, tool_name="t", max_chars=50, head_chars=20, tail_chars=10)
        assert len(result) <= 50


# ===========================================================================
# Middleware integration tests — wrap_tool_call
# ===========================================================================


class TestWrapToolCallPassThrough:
    def test_small_output_passes_through(self):
        mw = ToolOutputBudgetMiddleware(config=ToolOutputConfig(externalize_min_chars=1000))
        msg = _tm("small output", name="bash")
        result = mw.wrap_tool_call(_make_request(), lambda _: msg)
        assert result is msg

    def test_disabled_middleware_passes_through(self):
        mw = ToolOutputBudgetMiddleware(config=ToolOutputConfig(enabled=False, externalize_min_chars=10, fallback_max_chars=20))
        msg = _tm("x" * 50000, name="bash")
        result = mw.wrap_tool_call(_make_request(), lambda _: msg)
        assert result is msg


class TestWrapToolCallExternalize:
    def test_oversized_output_externalized_to_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ToolOutputConfig(externalize_min_chars=100, preview_head_chars=50, preview_tail_chars=30)
            mw = ToolOutputBudgetMiddleware(config=config)
            content = "x" * 500
            msg = _tm(content, name="remote_executor")
            req = _make_request(outputs_path=tmpdir)

            result = mw.wrap_tool_call(req, lambda _: msg)

            assert isinstance(result, ToolMessage)
            assert result is not msg
            assert "Full remote_executor output saved to" in result.content
            assert "read_file" in result.content
            assert result.tool_call_id == "tc-1"

            # Verify file was written
            storage_dir = os.path.join(tmpdir, ".tool-results")
            assert os.path.isdir(storage_dir)
            files = os.listdir(storage_dir)
            assert len(files) == 1
            with open(os.path.join(storage_dir, files[0]), encoding="utf-8") as f:
                assert f.read() == content

    def test_preview_contains_typed_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ToolOutputConfig(externalize_min_chars=50, preview_head_chars=20, preview_tail_chars=10)
            mw = ToolOutputBudgetMiddleware(config=config)
            content = "HEADPART_" + "m" * 200 + "_TAILPART"
            msg = _tm(content, name="web_search")
            req = _make_request(outputs_path=tmpdir)

            result = mw.wrap_tool_call(req, lambda _: msg)

            assert result.content.startswith("[Full web_search output saved to")
            assert "Preview kind: text" in result.content
            assert "Text output" in result.content
            assert "HEADPART_" in result.content


class TestWrapToolCallFallback:
    def test_fallback_when_no_outputs_path(self):
        config = ToolOutputConfig(
            externalize_min_chars=50,
            fallback_max_chars=200,
            fallback_head_chars=80,
            fallback_tail_chars=40,
        )
        mw = ToolOutputBudgetMiddleware(config=config)
        content = "x" * 500
        msg = _tm(content, name="mcp_tool")
        req = _make_request(outputs_path=None)

        result = mw.wrap_tool_call(req, lambda _: msg)

        assert isinstance(result, ToolMessage)
        assert result is not msg
        assert "omitted from mcp_tool output" in result.content
        assert "Persistent storage unavailable" in result.content
        assert len(result.content) < len(content)

    def test_fallback_when_disk_write_fails(self):
        config = ToolOutputConfig(
            externalize_min_chars=50,
            fallback_max_chars=200,
            fallback_head_chars=80,
            fallback_tail_chars=40,
        )
        mw = ToolOutputBudgetMiddleware(config=config)
        content = "x" * 500
        msg = _tm(content, name="tool")
        req = _make_request(outputs_path="/dev/null/cannot-mkdir-here")

        result = mw.wrap_tool_call(req, lambda _: msg)

        assert isinstance(result, ToolMessage)
        assert "omitted from tool output" in result.content


class TestWrapToolCallExemption:
    def test_read_file_exempt(self):
        config = ToolOutputConfig(externalize_min_chars=10, fallback_max_chars=50)
        mw = ToolOutputBudgetMiddleware(config=config)
        content = "x" * 100
        msg = _tm(content, name="read_file")

        result = mw.wrap_tool_call(_make_request(tool_name="read_file"), lambda _: msg)

        assert result is msg

    def test_read_file_tool_exempt(self):
        config = ToolOutputConfig(externalize_min_chars=10, fallback_max_chars=50)
        mw = ToolOutputBudgetMiddleware(config=config)
        content = "x" * 100
        msg = _tm(content, name="read_file_tool")

        result = mw.wrap_tool_call(_make_request(tool_name="read_file_tool"), lambda _: msg)

        assert result is msg

    def test_custom_exempt_tool(self):
        config = ToolOutputConfig(externalize_min_chars=10, fallback_max_chars=50, exempt_tools=["my_tool"])
        mw = ToolOutputBudgetMiddleware(config=config)
        content = "x" * 100
        msg = _tm(content, name="my_tool")

        result = mw.wrap_tool_call(_make_request(tool_name="my_tool"), lambda _: msg)

        assert result is msg


class TestWrapToolCallPerToolOverride:
    def test_per_tool_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ToolOutputConfig(
                externalize_min_chars=50000,  # global: high
                tool_overrides={"sensitive_tool": 100},  # override: low
            )
            mw = ToolOutputBudgetMiddleware(config=config)
            content = "x" * 500
            msg = _tm(content, name="sensitive_tool")
            req = _make_request(tool_name="sensitive_tool", outputs_path=tmpdir)

            result = mw.wrap_tool_call(req, lambda _: msg)

            assert result is not msg
            assert "Full sensitive_tool output saved to" in result.content

    def test_per_tool_zero_disables_externalization(self):
        config = ToolOutputConfig(
            externalize_min_chars=50,
            tool_overrides={"bash": 0},
            fallback_max_chars=200,
            fallback_head_chars=80,
            fallback_tail_chars=40,
        )
        mw = ToolOutputBudgetMiddleware(config=config)
        content = "x" * 500
        msg = _tm(content, name="bash")
        # Even with outputs_path, externalization disabled for bash
        req = _make_request(tool_name="bash", outputs_path="/tmp/test")

        result = mw.wrap_tool_call(req, lambda _: msg)

        assert isinstance(result, ToolMessage)
        # Should use fallback instead of externalization
        assert "Persistent storage unavailable" in result.content or "omitted" in result.content


class TestWrapToolCallCommand:
    def test_command_messages_are_patched(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ToolOutputConfig(externalize_min_chars=50, preview_head_chars=20, preview_tail_chars=10)
            mw = ToolOutputBudgetMiddleware(config=config)
            tool_msg = _tm("x" * 200, name="present_files")
            command = Command(update={"messages": [tool_msg], "artifacts": ["/mnt/report.html"]})
            req = _make_request(tool_name="present_files", outputs_path=tmpdir)

            result = mw.wrap_tool_call(req, lambda _: command)

            assert isinstance(result, Command)
            assert result is not command
            assert result.update["artifacts"] == ["/mnt/report.html"]
            new_msg = result.update["messages"][0]
            assert isinstance(new_msg, ToolMessage)
            assert "Full present_files output saved to" in new_msg.content

    def test_command_without_messages_unchanged(self):
        config = ToolOutputConfig(externalize_min_chars=10)
        mw = ToolOutputBudgetMiddleware(config=config)
        command = Command(update={"key": "value"})
        result = mw.wrap_tool_call(_make_request(), lambda _: command)
        assert result is command


class TestWrapToolCallEdgeCases:
    def test_none_content_passes_through(self):
        config = ToolOutputConfig(externalize_min_chars=10, fallback_max_chars=20)
        mw = ToolOutputBudgetMiddleware(config=config)
        msg = ToolMessage(content=None, name="tool", tool_call_id="tc-1")

        result = mw.wrap_tool_call(_make_request(), lambda _: msg)

        assert result is msg

    def test_empty_string_passes_through(self):
        config = ToolOutputConfig(externalize_min_chars=10, fallback_max_chars=20)
        mw = ToolOutputBudgetMiddleware(config=config)
        msg = _tm("", name="tool")

        result = mw.wrap_tool_call(_make_request(), lambda _: msg)

        assert result is msg

    def test_multimodal_content_skipped(self):
        config = ToolOutputConfig(externalize_min_chars=10, fallback_max_chars=20)
        mw = ToolOutputBudgetMiddleware(config=config)
        content = [{"type": "image", "data": "x" * 100}]
        msg = ToolMessage(content=content, name="tool", tool_call_id="tc-1")

        result = mw.wrap_tool_call(_make_request(), lambda _: msg)

        assert result is msg

    def test_exactly_at_threshold_passes_through(self):
        config = ToolOutputConfig(externalize_min_chars=100, fallback_max_chars=100)
        mw = ToolOutputBudgetMiddleware(config=config)
        msg = _tm("x" * 100, name="tool")

        result = mw.wrap_tool_call(_make_request(), lambda _: msg)

        assert result is msg

    def test_one_char_over_threshold_triggers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ToolOutputConfig(externalize_min_chars=100)
            mw = ToolOutputBudgetMiddleware(config=config)
            msg = _tm("x" * 101, name="tool")
            req = _make_request(outputs_path=tmpdir)

            result = mw.wrap_tool_call(req, lambda _: msg)

            assert result is not msg

    def test_chinese_content_preserved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ToolOutputConfig(externalize_min_chars=50, preview_head_chars=20, preview_tail_chars=10)
            mw = ToolOutputBudgetMiddleware(config=config)
            content = "你好世界" * 50
            msg = _tm(content, name="tool")
            req = _make_request(outputs_path=tmpdir)

            result = mw.wrap_tool_call(req, lambda _: msg)

            assert isinstance(result, ToolMessage)
            # File should contain the full Chinese content
            storage_dir = os.path.join(tmpdir, ".tool-results")
            files = os.listdir(storage_dir)
            with open(os.path.join(storage_dir, files[0]), encoding="utf-8") as f:
                assert f.read() == content

    def test_no_runtime_state_uses_fallback(self):
        config = ToolOutputConfig(
            externalize_min_chars=50,
            fallback_max_chars=500,
            fallback_head_chars=100,
            fallback_tail_chars=50,
        )
        mw = ToolOutputBudgetMiddleware(config=config)
        content = "x" * 1000
        msg = _tm(content, name="tool")
        req = SimpleNamespace(
            tool_call={"name": "tool", "id": "tc-1"},
            runtime=None,
        )

        result = mw.wrap_tool_call(req, lambda _: msg)

        assert isinstance(result, ToolMessage)
        assert "omitted" in result.content
        assert len(result.content) <= 500


# ===========================================================================
# MCP content_and_artifact format tests
# ===========================================================================


class TestMCPContentAndArtifact:
    """MCP tools return content as list of content blocks, not plain strings."""

    def test_text_content_blocks_are_budgeted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ToolOutputConfig(externalize_min_chars=50, preview_head_chars=20, preview_tail_chars=10)
            mw = ToolOutputBudgetMiddleware(config=config)
            content = [{"type": "text", "text": "x" * 200}]
            msg = ToolMessage(content=content, name="mcp_tool", tool_call_id="tc-mcp")
            req = _make_request(tool_name="mcp_tool", outputs_path=tmpdir)

            result = mw.wrap_tool_call(req, lambda _: msg)

            assert result is not msg
            assert isinstance(result.content, str)
            assert "Full mcp_tool output saved to" in result.content
            assert result.tool_call_id == "tc-mcp"

    def test_multiple_text_blocks_joined_and_budgeted(self):
        config = ToolOutputConfig(externalize_min_chars=50, fallback_max_chars=500, fallback_head_chars=100, fallback_tail_chars=50)
        mw = ToolOutputBudgetMiddleware(config=config)
        content = [{"type": "text", "text": "a" * 300}, {"type": "text", "text": "b" * 300}]
        msg = ToolMessage(content=content, name="mcp_tool", tool_call_id="tc-mcp2")
        req = _make_request(tool_name="mcp_tool")

        result = mw.wrap_tool_call(req, lambda _: msg)

        assert result is not msg
        assert "omitted" in result.content

    def test_image_content_blocks_are_skipped(self):
        config = ToolOutputConfig(externalize_min_chars=10, fallback_max_chars=20)
        mw = ToolOutputBudgetMiddleware(config=config)
        content = [{"type": "image", "data": "base64data" * 100}]
        msg = ToolMessage(content=content, name="mcp_tool", tool_call_id="tc-img")
        req = _make_request(tool_name="mcp_tool")

        result = mw.wrap_tool_call(req, lambda _: msg)

        assert result is msg

    def test_mixed_text_and_image_blocks_are_skipped(self):
        config = ToolOutputConfig(externalize_min_chars=10)
        mw = ToolOutputBudgetMiddleware(config=config)
        content = [{"type": "text", "text": "x" * 100}, {"type": "image", "data": "base64"}]
        msg = ToolMessage(content=content, name="mcp_tool", tool_call_id="tc-mix")
        req = _make_request(tool_name="mcp_tool")

        result = mw.wrap_tool_call(req, lambda _: msg)

        assert result is msg

    def test_small_text_blocks_pass_through(self):
        config = ToolOutputConfig(externalize_min_chars=1000)
        mw = ToolOutputBudgetMiddleware(config=config)
        content = [{"type": "text", "text": "small result"}]
        msg = ToolMessage(content=content, name="mcp_tool", tool_call_id="tc-sm")
        req = _make_request(tool_name="mcp_tool")

        result = mw.wrap_tool_call(req, lambda _: msg)

        assert result is msg


# ===========================================================================
# Async path tests
# ===========================================================================


class TestAsyncPaths:
    @pytest.mark.anyio
    async def test_async_tool_call_externalized(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ToolOutputConfig(externalize_min_chars=50, preview_head_chars=20, preview_tail_chars=10)
            mw = ToolOutputBudgetMiddleware(config=config)
            content = "x" * 200
            msg = _tm(content, name="async_tool")
            req = _make_request(tool_name="async_tool", outputs_path=tmpdir)

            async def handler(_):
                return msg

            result = await mw.awrap_tool_call(req, handler)

            assert isinstance(result, ToolMessage)
            assert result is not msg
            assert "Full async_tool output saved to" in result.content

    @pytest.mark.anyio
    async def test_async_model_call_patches_history(self):
        config = ToolOutputConfig(fallback_max_chars=500, fallback_head_chars=100, fallback_tail_chars=50)
        mw = ToolOutputBudgetMiddleware(config=config)
        oversized = _tm("h" * 1000, name="tool", tool_call_id="tc-h")
        request = ModelRequest(model=None, messages=[oversized], tools=[], state={})
        captured: dict[str, ModelRequest] = {}

        async def handler(req):
            captured["request"] = req
            return []

        await mw.awrap_model_call(request, handler)

        forwarded = captured["request"]
        assert forwarded is not request
        msg = forwarded.messages[0]
        assert isinstance(msg, ToolMessage)
        assert "omitted" in msg.content


# ===========================================================================
# wrap_model_call — historical message patching
# ===========================================================================


class TestWrapModelCall:
    def test_oversized_historical_messages_truncated(self):
        config = ToolOutputConfig(fallback_max_chars=500, fallback_head_chars=100, fallback_tail_chars=50)
        mw = ToolOutputBudgetMiddleware(config=config)
        oversized = _tm("q" * 1000, name="tool", tool_call_id="tc-q")
        request = ModelRequest(model=None, messages=[oversized], tools=[], state={})
        captured: dict[str, ModelRequest] = {}

        def handler(req):
            captured["request"] = req
            return []

        mw.wrap_model_call(request, handler)

        forwarded = captured["request"]
        assert forwarded is not request
        msg = forwarded.messages[0]
        assert isinstance(msg, ToolMessage)
        assert "omitted" in msg.content
        assert len(msg.content) < len(oversized.content) + 150

    def test_small_historical_messages_unchanged(self):
        config = ToolOutputConfig(fallback_max_chars=1000)
        mw = ToolOutputBudgetMiddleware(config=config)
        small = _tm("small", name="tool")
        request = ModelRequest(model=None, messages=[small], tools=[], state={})
        captured: dict[str, ModelRequest] = {}

        def handler(req):
            captured["request"] = req
            return []

        mw.wrap_model_call(request, handler)

        assert captured["request"] is request

    def test_exempt_tools_in_history_unchanged(self):
        config = ToolOutputConfig(fallback_max_chars=50)
        mw = ToolOutputBudgetMiddleware(config=config)
        read_msg = _tm("x" * 200, name="read_file", tool_call_id="tc-r")
        request = ModelRequest(model=None, messages=[read_msg], tools=[], state={})
        captured: dict[str, ModelRequest] = {}

        def handler(req):
            captured["request"] = req
            return []

        mw.wrap_model_call(request, handler)

        assert captured["request"] is request

    def test_non_tool_messages_preserved(self):
        config = ToolOutputConfig(fallback_max_chars=500, fallback_head_chars=100, fallback_tail_chars=50)
        mw = ToolOutputBudgetMiddleware(config=config)
        human = HumanMessage(content="x" * 200)
        ai = AIMessage(content="y" * 200)
        oversized_tool = _tm("z" * 1000, name="tool")
        request = ModelRequest(model=None, messages=[human, ai, oversized_tool], tools=[], state={})
        captured: dict[str, ModelRequest] = {}

        def handler(req):
            captured["request"] = req
            return []

        mw.wrap_model_call(request, handler)

        msgs = captured["request"].messages
        assert msgs[0] is human
        assert msgs[1] is ai
        assert isinstance(msgs[2], ToolMessage)
        assert "omitted" in msgs[2].content


# ===========================================================================
# Config integration
# ===========================================================================


class TestFromAppConfig:
    def test_from_app_config_with_tool_output(self):
        config = AppConfig(
            sandbox=SandboxConfig(use="test"),
            tool_output={"externalize_min_chars": 5000, "preview_head_chars": 500},
        )
        mw = ToolOutputBudgetMiddleware.from_app_config(config)
        assert mw._config.externalize_min_chars == 5000
        assert mw._config.preview_head_chars == 500

    def test_from_app_config_defaults(self):
        config = AppConfig(sandbox=SandboxConfig(use="test"))
        mw = ToolOutputBudgetMiddleware.from_app_config(config)
        assert mw._config.externalize_min_chars == 12000


class TestPatchModelMessages:
    def test_returns_none_when_no_changes(self):
        config = ToolOutputConfig(fallback_max_chars=1000)
        messages = [_tm("short", name="tool")]
        assert _patch_model_messages(messages, config) is None

    def test_patches_oversized_messages(self):
        config = ToolOutputConfig(fallback_max_chars=500, fallback_head_chars=100, fallback_tail_chars=50)
        messages = [_tm("x" * 1000, name="tool")]
        result = _patch_model_messages(messages, config)
        assert result is not None
        assert len(result) == 1
        assert "omitted" in result[0].content


# ===========================================================================
# Pre-scan helpers (_effective_trigger / _tool_message_over_budget / _needs_budget)
# These guard the fast-path optimization — a false negative here is a real bug
# (budgeting silently skipped), so per-tool overrides must be honored.
# ===========================================================================


class TestPreScanHelpers:
    def test_effective_trigger_uses_global_externalize(self):
        config = ToolOutputConfig(externalize_min_chars=12000, fallback_max_chars=30000)
        # smallest of the two thresholds wins
        assert _effective_trigger("any_tool", config) == 12000

    def test_effective_trigger_respects_per_tool_override(self):
        config = ToolOutputConfig(externalize_min_chars=50000, fallback_max_chars=0, tool_overrides={"sensitive": 100})
        assert _effective_trigger("sensitive", config) == 100
        # other tools fall back to the (high) global
        assert _effective_trigger("other", config) == 50000

    def test_effective_trigger_per_tool_zero_falls_to_fallback(self):
        config = ToolOutputConfig(externalize_min_chars=50, tool_overrides={"bash": 0}, fallback_max_chars=200)
        # externalize disabled for bash → only fallback can trigger
        assert _effective_trigger("bash", config) == 200

    def test_effective_trigger_returns_negative_when_fully_disabled(self):
        config = ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=0)
        assert _effective_trigger("any", config) == -1

    def test_pre_scan_does_not_short_circuit_per_tool_override(self):
        """Regression: pre-scan must honor per-tool overrides, not just global threshold."""
        config = ToolOutputConfig(externalize_min_chars=50000, fallback_max_chars=0, tool_overrides={"sensitive": 100})
        msg = _tm("x" * 500, name="sensitive")
        # 500 < global 50000 but > per-tool 100 → must still be flagged
        assert _tool_message_over_budget(msg, config) is True
        assert _needs_budget(msg, config) is True

    def test_exempt_tool_never_over_budget(self):
        config = ToolOutputConfig(externalize_min_chars=10, fallback_max_chars=20, exempt_tools=["read_file"])
        msg = _tm("x" * 1000, name="read_file")
        assert _tool_message_over_budget(msg, config) is False

    def test_model_call_pre_scan_skips_when_nothing_oversized(self):
        """_patch_model_messages returns None (no list rebuild) when all messages are small."""
        config = ToolOutputConfig(externalize_min_chars=12000, fallback_max_chars=30000)
        messages = [_tm("small", name="tool"), HumanMessage(content="hi"), _tm("also small", name="bash")]
        assert _patch_model_messages(messages, config) is None


# ===========================================================================
# Middleware ordering in the chain
# ===========================================================================


class TestMiddlewareChainIntegration:
    def test_budget_middleware_is_first_in_chain(self):
        from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares

        app_config = AppConfig(sandbox=SandboxConfig(use="test"))
        middlewares = build_subagent_runtime_middlewares(app_config=app_config, lazy_init=False)

        # InputSanitizationMiddleware is the outermost wrap_model_call wrapper;
        # ToolOutputBudgetMiddleware is the first wrap_tool_call handler.
        from deerflow.agents.middlewares.input_sanitization_middleware import InputSanitizationMiddleware

        assert isinstance(middlewares[0], InputSanitizationMiddleware)
        assert isinstance(middlewares[1], ToolOutputBudgetMiddleware)

    def test_budget_middleware_in_lead_chain(self):
        from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares

        app_config = AppConfig(sandbox=SandboxConfig(use="test"))
        middlewares = build_lead_runtime_middlewares(app_config=app_config, lazy_init=False)

        from deerflow.agents.middlewares.input_sanitization_middleware import InputSanitizationMiddleware

        assert isinstance(middlewares[0], InputSanitizationMiddleware)
        assert isinstance(middlewares[1], ToolOutputBudgetMiddleware)


# ===========================================================================
# Config version bump
# ===========================================================================


class TestConfigVersion:
    def test_config_version_bumped(self):
        import yaml

        example_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.example.yaml")
        if os.path.exists(example_path):
            with open(example_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            assert data.get("config_version", 0) >= 11

    def test_config_example_has_tool_output_section(self):
        import yaml

        example_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.example.yaml")
        if os.path.exists(example_path):
            with open(example_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            assert "tool_output" in data
            tool_output = data["tool_output"]
            assert tool_output["enabled"] is True
            assert tool_output["externalize_min_chars"] == 12000
            assert "read_file" in tool_output["exempt_tools"]


# ===========================================================================
# externalize into sandbox for non-mounted (remote) sandboxes
# ===========================================================================


class _FakeSandbox:
    """In-memory stand-in for a Sandbox. Records calls and supports failure injection."""

    def __init__(self, *, write_ok: bool = True, check_result: str = "OK") -> None:
        self.commands: list[str] = []
        self.writes: list[tuple[str, str]] = []
        self._write_ok = write_ok
        self._check_result = check_result

    def execute_command(
        self,
        command: str,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> str:
        del env, timeout
        self.commands.append(command)
        if command.startswith("test -s"):
            return self._check_result
        return ""

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        if not self._write_ok:
            raise RuntimeError("simulated write failure")
        self.writes.append((path, content))


class _FakeProvider:
    """Minimal SandboxProvider stand-in for monkeypatching get_sandbox_provider."""

    def __init__(self, *, uses_thread_data_mounts: bool, sandbox: _FakeSandbox | None = None) -> None:
        self.uses_thread_data_mounts = uses_thread_data_mounts
        self._sandbox = sandbox

    def get(self, sandbox_id: str):
        return self._sandbox


class TestExternalizeToSandbox:
    def test_writes_and_returns_virtual_path(self):
        from deerflow.agents.middlewares.tool_output_budget_middleware import (
            _externalize_to_sandbox,
        )

        sb = _FakeSandbox()
        result = _externalize_to_sandbox(
            "x" * 100,
            tool_name="bash",
            tool_call_id="tc-1",
            storage_subdir=".tool-results",
            sandbox=sb,
        )
        assert result is not None
        assert result.startswith("/mnt/user-data/outputs/.tool-results/bash-")
        assert result.endswith(".log")
        assert any(c.startswith("mkdir -p ") for c in sb.commands)
        assert any(c.startswith("test -s ") for c in sb.commands)
        assert sb.writes and sb.writes[0][0] == result
        assert sb.writes[0][1] == "x" * 100

    def test_returns_none_when_write_raises(self):
        from deerflow.agents.middlewares.tool_output_budget_middleware import (
            _externalize_to_sandbox,
        )

        result = _externalize_to_sandbox(
            "x" * 100,
            tool_name="web_fetch",
            tool_call_id="tc-2",
            storage_subdir=".tool-results",
            sandbox=_FakeSandbox(write_ok=False),
        )
        assert result is None

    def test_returns_none_when_validation_fails(self):
        from deerflow.agents.middlewares.tool_output_budget_middleware import (
            _externalize_to_sandbox,
        )

        result = _externalize_to_sandbox(
            "x" * 100,
            tool_name="bash",
            tool_call_id="tc-3",
            storage_subdir=".tool-results",
            sandbox=_FakeSandbox(check_result="MISSING"),
        )
        assert result is None

    def test_rejects_unsafe_storage_subdir(self):
        from deerflow.agents.middlewares.tool_output_budget_middleware import (
            _externalize_to_sandbox,
        )

        sb = _FakeSandbox()
        assert (
            _externalize_to_sandbox(
                "x" * 100,
                tool_name="bash",
                tool_call_id="tc-4",
                storage_subdir="../escape",
                sandbox=sb,
            )
            is None
        )
        assert (
            _externalize_to_sandbox(
                "x" * 100,
                tool_name="bash",
                tool_call_id="tc-5",
                storage_subdir="/abs/path",
                sandbox=sb,
            )
            is None
        )
        # Sandbox must not be touched when the subdir is rejected up-front.
        assert sb.commands == []
        assert sb.writes == []

    def test_default_extension_for_unknown_tool(self):
        from deerflow.agents.middlewares.tool_output_budget_middleware import (
            _externalize_to_sandbox,
        )

        result = _externalize_to_sandbox(
            "data",
            tool_name="unknown_tool",
            tool_call_id="tc-6",
            storage_subdir=".tool-results",
            sandbox=_FakeSandbox(),
        )
        assert result is not None and result.endswith(".txt")


class TestBudgetContentSandboxDispatch:
    """_budget_content must branch on uses_thread_data_mounts (issue #3416)."""

    def test_mounted_sandbox_uses_host_disk(self, monkeypatch, tmp_path):
        from deerflow.agents.middlewares import tool_output_budget_middleware as mod

        sb = _FakeSandbox()
        monkeypatch.setattr(
            mod,
            "get_sandbox_provider",
            lambda: _FakeProvider(uses_thread_data_mounts=True, sandbox=sb),
        )
        config = ToolOutputConfig(externalize_min_chars=50, preview_head_chars=20, preview_tail_chars=10)
        result = mod._budget_content(
            "x" * 500,
            tool_name="remote_executor",
            tool_call_id="tc-m",
            outputs_path=str(tmp_path),
            config=config,
            sandbox=sb,
        )
        assert result is not None
        assert "Full remote_executor output saved to /mnt/user-data/outputs/" in result
        # Mounted path must NOT touch the sandbox.
        assert sb.commands == []
        assert sb.writes == []
        # And the host file must exist.
        storage_dir = tmp_path / ".tool-results"
        assert storage_dir.is_dir()
        assert len(list(storage_dir.iterdir())) == 1

    def test_non_mounted_sandbox_writes_to_sandbox(self, monkeypatch, tmp_path):
        from deerflow.agents.middlewares import tool_output_budget_middleware as mod

        sb = _FakeSandbox()
        monkeypatch.setattr(
            mod,
            "get_sandbox_provider",
            lambda: _FakeProvider(uses_thread_data_mounts=False, sandbox=sb),
        )
        config = ToolOutputConfig(externalize_min_chars=50, preview_head_chars=20, preview_tail_chars=10)
        result = mod._budget_content(
            "x" * 500,
            tool_name="remote_executor",
            tool_call_id="tc-n",
            outputs_path=str(tmp_path),  # present, but ignored on non-mounted path
            config=config,
            sandbox=sb,
        )
        assert result is not None
        assert "Full remote_executor output saved to /mnt/user-data/outputs/" in result
        # Non-mounted path MUST write into the sandbox.
        assert sb.writes and sb.writes[0][1] == "x" * 500
        # And MUST NOT touch the host.
        assert not (tmp_path / ".tool-results").exists()

    def test_non_mounted_without_sandbox_falls_back(self, monkeypatch):
        from deerflow.agents.middlewares import tool_output_budget_middleware as mod

        monkeypatch.setattr(
            mod,
            "get_sandbox_provider",
            lambda: _FakeProvider(uses_thread_data_mounts=False, sandbox=None),
        )
        config = ToolOutputConfig(
            externalize_min_chars=50,
            fallback_max_chars=500,
            fallback_head_chars=100,
            fallback_tail_chars=50,
        )
        result = mod._budget_content(
            "x" * 5000,
            tool_name="web_search",
            tool_call_id="tc-fb",
            outputs_path=None,
            config=config,
            sandbox=None,
        )
        assert result is not None
        assert "Persistent storage unavailable" in result


class TestResolveSandbox:
    def test_returns_none_when_no_state(self):
        from deerflow.agents.middlewares.tool_output_budget_middleware import _resolve_sandbox

        req = SimpleNamespace(runtime=None)
        assert _resolve_sandbox(req) is None

    def test_returns_none_when_state_has_no_sandbox(self):
        from deerflow.agents.middlewares.tool_output_budget_middleware import _resolve_sandbox

        req = SimpleNamespace(runtime=SimpleNamespace(state={}))
        assert _resolve_sandbox(req) is None

    def test_returns_none_when_sandbox_id_missing(self):
        from deerflow.agents.middlewares.tool_output_budget_middleware import _resolve_sandbox

        req = SimpleNamespace(runtime=SimpleNamespace(state={"sandbox": {}}))
        assert _resolve_sandbox(req) is None

    def test_returns_sandbox_from_provider(self, monkeypatch):
        from deerflow.agents.middlewares import tool_output_budget_middleware as mod

        sb = _FakeSandbox()
        monkeypatch.setattr(
            mod,
            "get_sandbox_provider",
            lambda: _FakeProvider(uses_thread_data_mounts=False, sandbox=sb),
        )
        req = SimpleNamespace(runtime=SimpleNamespace(state={"sandbox": {"sandbox_id": "sb-1"}}))
        assert mod._resolve_sandbox(req) is sb

    def test_returns_none_on_provider_exception(self, monkeypatch):
        from deerflow.agents.middlewares import tool_output_budget_middleware as mod

        class _Boom:
            def get(self, sandbox_id):
                raise RuntimeError("boom")

        monkeypatch.setattr(mod, "get_sandbox_provider", lambda: _Boom())
        req = SimpleNamespace(runtime=SimpleNamespace(state={"sandbox": {"sandbox_id": "sb-x"}}))
        assert mod._resolve_sandbox(req) is None


class TestWrapToolCallSandboxIntegration:
    """End-to-end via wrap_tool_call for the non-mounted path (issue #3416)."""

    def test_oversized_output_lands_in_sandbox_not_host(self, monkeypatch, tmp_path):
        from deerflow.agents.middlewares import tool_output_budget_middleware as mod

        sb = _FakeSandbox()
        monkeypatch.setattr(
            mod,
            "get_sandbox_provider",
            lambda: _FakeProvider(uses_thread_data_mounts=False, sandbox=sb),
        )

        config = ToolOutputConfig(externalize_min_chars=50, preview_head_chars=20, preview_tail_chars=10)
        mw = ToolOutputBudgetMiddleware(config=config)
        content = "x" * 500
        msg = _tm(content, name="remote_executor")
        # Request carries BOTH outputs_path (host) AND a sandbox_id; the
        # non-mounted branch must ignore outputs_path and write into sandbox.
        req = SimpleNamespace(
            tool_call={"name": "remote_executor", "id": "tc-1"},
            runtime=SimpleNamespace(
                state={
                    "thread_data": {"outputs_path": str(tmp_path)},
                    "sandbox": {"sandbox_id": "sb-1"},
                }
            ),
        )

        result = mw.wrap_tool_call(req, lambda _: msg)

        assert isinstance(result, ToolMessage)
        assert "Full remote_executor output saved to /mnt/user-data/outputs/" in result.content
        assert sb.writes and sb.writes[0][1] == content
        # Host disk must not have been written.
        assert not (tmp_path / ".tool-results").exists()


class TestBudgetContentNoSandboxNoProviderCall:
    """Without a sandbox, _budget_content must NOT call get_sandbox_provider.

    This is the legacy host-disk path (and the CI-without-config.yaml path):
    touching the provider would raise and force inline fallback, regressing
    issue #3416's fix and breaking environments that never opt into sandbox.
    """

    def test_no_provider_call_when_sandbox_absent(self, monkeypatch, tmp_path):
        from deerflow.agents.middlewares import tool_output_budget_middleware as mod

        called = {"n": 0}

        def boom():
            called["n"] += 1
            raise RuntimeError("provider must not be called on the legacy path")

        monkeypatch.setattr(mod, "get_sandbox_provider", boom)
        config = ToolOutputConfig(externalize_min_chars=50, preview_head_chars=20, preview_tail_chars=10)
        result = mod._budget_content(
            "x" * 500,
            tool_name="remote_executor",
            tool_call_id="tc-legacy",
            outputs_path=str(tmp_path),
            config=config,
            sandbox=None,
        )
        assert result is not None
        assert "Full remote_executor output saved to /mnt/user-data/outputs/" in result
        assert called["n"] == 0
        assert (tmp_path / ".tool-results").is_dir()
