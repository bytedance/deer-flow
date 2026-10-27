"""Tests for the persistent artifact handle registry (issue #4676)."""

import json

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.messages.content import create_file_block, create_image_block

from deerflow.agents.thread_state import merge_tool_artifacts
from deerflow.tools.artifact_registry import (
    _detect_refs_in_text,
    extract_artifacts_from_result,
    generate_handle,
)


def _entry(handle: str, i: int) -> dict:
    return {
        "handle": handle,
        "tool_name": "t",
        "tool_call_id": f"call-{i}",
        "call_index": 0,
        "artifact_type": "file",
        "display_name": f"{i}.txt",
        "real_ref": f"/tmp/{i}.txt",
        "created_at": "2026-08-19T00:00:00Z",
    }


def test_generate_handle_deterministic():
    assert generate_handle("thread-1", "call-1", 0) == generate_handle("thread-1", "call-1", 0)


def test_generate_handle_unique():
    assert generate_handle("thread-1", "call-1", 0) != generate_handle("thread-1", "call-1", 1)
    assert generate_handle("thread-1", "call-1", 0) != generate_handle("thread-1", "call-2", 0)
    assert generate_handle("thread-1", "call-1", 0) != generate_handle("thread-2", "call-1", 0)


def test_generate_handle_format():
    handle = generate_handle("thread-1", "call-1", 0)
    assert handle.startswith("art_")
    assert len(handle) == len("art_") + 8


@pytest.mark.parametrize(
    "url",
    [
        "https://files.example/report.pdf?token=part.csvX",
        "https://files.example/report.pdf#section.md-more",
        "https://files.example/report.pdf?token=abc&download=copy.csvX#page=2",
        "https://files.example/report.pdf?token=abc",
        "https://files.example/report.pdf#page=2",
        "https://files.example/report.pdf?token=part%EF%BC%89#section%EF%BC%8C",
    ],
)
@pytest.mark.parametrize("content_block", [False, True])
def test_text_file_urls_preserve_complete_query_and_fragment(url, content_block):
    text = f"Report: [{url}]"
    result = ToolMessage(content=[{"type": "text", "text": text}] if content_block else text, tool_call_id="call_url", name="remote_report")

    entries = extract_artifacts_from_result(result, thread_id="thread-url")

    assert [entry["real_ref"] for entry in entries] == [url]


@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param("\u3002", id="cjk-period"),
        pytest.param("\uff0c", id="fullwidth-comma"),
        pytest.param("\uff1b", id="fullwidth-semicolon"),
        pytest.param("\uff1a", id="fullwidth-colon"),
        pytest.param("\u3001", id="ideographic-comma"),
        pytest.param("\uff09", id="fullwidth-parenthesis"),
        pytest.param("\u3011", id="cjk-bracket"),
        pytest.param("\u300b", id="cjk-angle-bracket"),
        pytest.param("\u201d", id="closing-double-quote"),
        pytest.param("\u2019", id="closing-single-quote"),
        pytest.param("\u3002\u201d\uff09", id="combined-closers"),
    ],
)
@pytest.mark.parametrize(
    "ref",
    [
        "https://files.example/report.pdf",
        "https://files.example/report.pdf?token=part.csvX#page=2",
        "/mnt/user-data/outputs/report.pdf",
    ],
)
def test_text_refs_followed_by_cjk_punctuation(ref, suffix):
    assert [entry["ref"] for entry in _detect_refs_in_text(f"Report: {ref}{suffix}")] == [ref]


@pytest.mark.parametrize("content_block", [False, True])
@pytest.mark.parametrize("directory_name", ["项目（归档）", "项目【归档】", "项目《归档》", "项目“归档”", "项目‘归档’", "项目（归档【旧版】）", "项目）归档（完成）"])
def test_glob_result_preserves_balanced_cjk_directory_names(directory_name, content_block):
    from deerflow.sandbox.tools import _format_glob_results

    root = "/mnt/user-data/workspace"
    path = f"{root}/{directory_name}"
    text = _format_glob_results(root, [path], truncated=False)
    result = ToolMessage(content=[{"type": "text", "text": text}] if content_block else text, tool_call_id="call_glob", name="glob")

    entries = extract_artifacts_from_result(result, thread_id="thread-glob")

    assert [entry["real_ref"] for entry in entries] == [root, path]
    assert entries[-1]["display_name"] == directory_name


@pytest.mark.parametrize("suffix", ["", "。", "。）", "]"])
@pytest.mark.parametrize("ref", ["/mnt/user-data/workspace/项目（归档）", "https://files.example/report.pdf?label=项目（归档）"])
def test_text_refs_preserve_balanced_cjk_closers_while_stripping_prose(ref, suffix):
    assert [entry["ref"] for entry in _detect_refs_in_text(f"Report: （{ref}{suffix}")] == [ref]


@pytest.mark.parametrize(
    "url",
    [
        "https://files.example/report.PDF",
        "https://files.example/image.PNG",
        "https://files.example/report.PdF?token=part.csvX#section.md-more",
        "https://files.example/image.PnG?token=encoded%EF%BC%89",
    ],
)
def test_text_file_url_extension_case_insensitive_preserves_reference(url):
    assert [entry["ref"] for entry in _detect_refs_in_text(f"Download [{url}]")] == [url]


def test_structured_url_keeps_literal_cjk_punctuation():
    url = "https://files.example/report.pdf?token=literal\u3011"
    result = ToolMessage(content="done", tool_call_id="call_url", name="remote_report", artifact={"structured_content": {"url": url}})

    entries = extract_artifacts_from_result(result, thread_id="thread-url")

    assert [entry["real_ref"] for entry in entries] == [url]


@pytest.mark.parametrize(
    "url",
    [
        "https://files.example/report.pdf/download",
        "https://files.example/report.pdf.gz",
        "https://files.example/report.pdfx",
        "https://files.example/download?name=report.pdf",
        "https://files.example/download#report.pdf",
        "https://reports.pdf",
        "https://files.example/report.PDF/download",
        "https://files.example/report.PDFx",
        "https://REPORT.PDF",
    ],
)
def test_text_urls_require_a_file_extension_in_the_complete_path(url):
    assert _detect_refs_in_text(f"Result: {url}") == []


def test_extract_from_file_block():
    result = ToolMessage(
        content=[
            {
                "type": "file",
                "source": {"type": "url", "url": "/mnt/user-data/outputs/report.html", "mime_type": "text/html"},
            }
        ],
        tool_call_id="call-1",
        name="mcp_server_analyze",
    )
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["artifact_type"] == "file"
    assert entry["real_ref"] == "/mnt/user-data/outputs/report.html"
    assert entry["display_name"] == "report.html"
    assert entry["tool_name"] == "mcp_server_analyze"
    assert entry["tool_call_id"] == "call-1"
    assert entry["mime_type"] == "text/html"


def test_extract_from_image_block():
    result = ToolMessage(
        content=[
            {
                "type": "image",
                "source": {"type": "url", "url": "/mnt/user-data/outputs/chart.png", "mime_type": "image/png"},
            }
        ],
        tool_call_id="call-2",
        name="mcp_chart_gen",
    )
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    assert len(entries) == 1
    assert entries[0]["artifact_type"] == "image"
    assert entries[0]["real_ref"] == "/mnt/user-data/outputs/chart.png"


@pytest.mark.parametrize("make_block,artifact_type,mime", [(create_file_block, "file", "application/pdf"), (create_image_block, "image", "image/png")])
def test_extract_from_standard_url_block(make_block, artifact_type, mime):
    url = "https://example.com/report?download=1#page=2"
    result = ToolMessage(content=[make_block(url=url, mime_type=mime)], tool_call_id="call_1")

    (entry,) = extract_artifacts_from_result(result, thread_id="thread-1")

    assert (entry["real_ref"], entry["artifact_type"], entry["mime_type"]) == (url, artifact_type, mime)


@pytest.mark.parametrize("source", [{"url": "https://example.com/legacy.png", "mime_type": "image/jpeg"}, "malformed"])
@pytest.mark.parametrize("mime", ["image/png", None])
def test_standard_url_and_mime_take_precedence_over_legacy_source(source, mime):
    block = create_image_block(url="https://example.com/chart.png", mime_type=mime)
    block["source"] = source
    result = ToolMessage(content=[block], tool_call_id="call_1")

    (entry,) = extract_artifacts_from_result(result, thread_id="thread-1")

    assert entry["real_ref"] == "https://example.com/chart.png"
    assert entry.get("mime_type") == mime


@pytest.mark.parametrize("url", [None, "", "relative.png", "data:image/png;base64,AAAA", "blob:https://example.com/id"])
def test_invalid_standard_url_does_not_fall_back_to_conflicting_legacy_source(url):
    block = {"type": "image", "url": url, "source": {"url": "https://example.com/legacy.png"}}
    result = ToolMessage(content=[block], tool_call_id="call_1")

    assert extract_artifacts_from_result(result, thread_id="thread-1") == []


def test_standard_and_legacy_blocks_deduplicate_the_same_reference():
    url = "https://example.com/chart.png"
    result = ToolMessage(
        content=[
            create_image_block(url=url, mime_type="image/png"),
            {"type": "file", "source": {"url": url, "mime_type": "application/octet-stream"}},
            {"type": "text", "text": f"Chart: {url}"},
        ],
        tool_call_id="call_1",
    )

    (entry,) = extract_artifacts_from_result(result, thread_id="thread-1")

    assert (entry["real_ref"], entry["artifact_type"], entry["mime_type"]) == (url, "image", "image/png")


@pytest.mark.parametrize("standard", [False, True])
def test_file_block_rejects_data_and_blob_urls(standard):
    """Embedded-resource URIs must never enter the registry or tool args."""
    result = ToolMessage(
        content=[
            {"type": "file", "source": {"type": "url", "url": "data:text/plain;base64,QUFB" + "A" * 500}},
            {"type": "image", "source": {"type": "url", "url": "blob:https://example.com/uuid"}},
            {"type": "file", "source": {"type": "url", "url": "//cdn.example.com/pixel.gif"}},
            {"type": "file", "source": {"type": "url", "url": "/mnt/user-data/outputs/real.txt"}},
        ],
        tool_call_id="call-2b",
        name="mcp_embedded",
    )
    if standard:
        result.content = [{"type": block["type"], "url": block["source"]["url"]} for block in result.content]
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    refs = {entry["real_ref"] for entry in entries}
    assert refs == {"/mnt/user-data/outputs/real.txt"}


def test_structured_url_key_rejects_non_http_uris():
    """Structured refs get the same URI-shape gate as content blocks."""
    result = ToolMessage(
        content=[{"type": "text", "text": "done"}],
        tool_call_id="call-4g",
        name="mcp_embedded",
        artifact={
            "structured_content": {
                "url": "data:text/html;base64,PGh0bWw+" + "Q" * 300,
                "file": "/mnt/user-data/outputs/keep.md",
                "task_id": "job-11",
            }
        },
    )
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    refs = {entry["real_ref"] for entry in entries}
    assert refs == {"/mnt/user-data/outputs/keep.md", "job-11"}
    types = {entry["real_ref"]: entry["artifact_type"] for entry in entries}
    assert types["job-11"] == "task"


def test_extract_from_resource_links_artifact():
    """The MCP conversion layer preserves ResourceLinks under the artifact's
    ``resource_links`` key; a result whose ONLY artifact signal is that key
    still yields file entries, named after the link."""
    result = ToolMessage(
        content=[{"type": "text", "text": "done"}],
        tool_call_id="call-rl",
        name="mcp_report_gen",
        artifact={
            "resource_links": [
                {"name": "quarterly report", "uri": "https://example.com/report.pdf", "mime_type": "application/pdf"},
                {"name": "", "uri": "/mnt/user-data/outputs/notes.txt", "mime_type": "text/plain"},
            ]
        },
    )
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    assert [(entry["artifact_type"], entry["real_ref"]) for entry in entries] == [
        ("file", "https://example.com/report.pdf"),
        ("file", "/mnt/user-data/outputs/notes.txt"),
    ]
    assert entries[0]["display_name"] == "quarterly report"
    assert entries[0]["mime_type"] == "application/pdf"
    assert entries[1]["display_name"] == "notes.txt"


def test_resource_links_reject_unreferenceable_uris():
    """``resource_links`` entries get the same referenceability gate as every
    other ref source: embedded-payload and non-fetchable URIs stay out of
    thread state."""
    result = ToolMessage(
        content=[{"type": "text", "text": "done"}],
        tool_call_id="call-rl2",
        name="mcp_embedded",
        artifact={
            "resource_links": [
                {"name": "blob", "uri": "data:application/pdf;base64," + "A" * 500, "mime_type": "application/pdf"},
                {"name": "card", "uri": "ui://app/card.html", "mime_type": "text/html"},
                {"name": "keep", "uri": "/mnt/user-data/outputs/keep.md", "mime_type": "text/markdown"},
            ]
        },
    )
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    assert [entry["real_ref"] for entry in entries] == ["/mnt/user-data/outputs/keep.md"]


def test_resource_links_and_placeholder_text_dedup_same_ref():
    """The conversion layer writes both a ``resource_links`` artifact entry and
    a model-visible placeholder text for one downgraded ResourceLink: the
    registry must not mint two handles for the same ref — the typed
    ``resource_links`` entry (with its display name) wins."""
    path_uri = "/mnt/user-data/outputs/page.png"
    url_uri = "https://example.com/files/report.pdf"
    result = ToolMessage(
        content=[
            {
                "type": "text",
                "text": (f"[Resource: page (image/png) available at {path_uri}]\n[Resource: report (application/pdf) available at {url_uri}]"),
            }
        ],
        tool_call_id="call-dup",
        name="mcp_screenshot",
        artifact={
            "resource_links": [
                {"name": "page", "uri": path_uri, "mime_type": "image/png"},
                {"name": "report", "uri": url_uri, "mime_type": "application/pdf"},
            ]
        },
    )
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    assert [(entry["artifact_type"], entry["real_ref"]) for entry in entries] == [
        ("file", path_uri),
        ("file", url_uri),
    ]
    assert entries[0]["display_name"] == "page"
    assert entries[0]["mime_type"] == "image/png"
    assert entries[1]["display_name"] == "report"


def test_extract_from_text_with_path():
    result = ToolMessage(
        content=[{"type": "text", "text": "Report saved to /mnt/user-data/outputs/report.html"}],
        tool_call_id="call-3",
        name="mcp_server_analyze",
    )
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    assert len(entries) == 1
    assert entries[0]["artifact_type"] == "file"
    assert entries[0]["real_ref"] == "/mnt/user-data/outputs/report.html"


def test_extract_from_structured_content():
    result = ToolMessage(
        content=[{"type": "text", "text": "task submitted"}],
        tool_call_id="call-4",
        name="mcp_task_submit",
        artifact={"structured_content": {"task_id": "remote-task-42", "status": "working"}},
    )
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    assert len(entries) == 1
    assert entries[0]["artifact_type"] == "task"
    assert entries[0]["real_ref"] == "remote-task-42"
    assert entries[0]["display_name"] == "remote-task-42"


def test_extract_from_structured_file_key_is_concrete_ref():
    result = ToolMessage(
        content=[{"type": "text", "text": "saved"}],
        tool_call_id="call-4b",
        name="mcp_writer",
        artifact={"structured_content": {"file": "/mnt/user-data/outputs/report.md", "mime_type": "text/markdown"}},
    )
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    assert len(entries) == 1
    assert entries[0]["artifact_type"] == "file"
    assert entries[0]["real_ref"] == "/mnt/user-data/outputs/report.md"


def test_extract_from_structured_list_valued_keys():
    result = ToolMessage(
        content=[{"type": "text", "text": "saved"}],
        tool_call_id="call-4e",
        name="mcp_batch_writer",
        artifact={"structured_content": {"files": ["/mnt/user-data/outputs/a.txt", "/mnt/user-data/outputs/b.txt"], "task_ids": ["x"]}},
    )
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    refs = {entry["real_ref"] for entry in entries}
    assert refs == {"/mnt/user-data/outputs/a.txt", "/mnt/user-data/outputs/b.txt"}
    handles = {entry["handle"] for entry in entries}
    assert len(handles) == 2


def test_structured_generic_output_key_not_treated_as_ref():
    """Prose under generic result keys must not become a bogus file entry."""
    result = ToolMessage(
        content=[{"type": "text", "text": "done"}],
        tool_call_id="call-4f",
        name="mcp_analyst",
        artifact={"structured_content": {"output": "Analysis complete; revenue up 12% quarter over quarter."}},
    )
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    assert len(entries) == 1
    assert entries[0]["artifact_type"] == "data"
    assert "Analysis complete" in entries[0]["real_ref"]


def test_structured_fallback_whole_object_not_truncated():
    structured = {"custom_payload": {"nested": ["x" * 200] * 10}}
    result = ToolMessage(
        content=[{"type": "text", "text": "done"}],
        tool_call_id="call-4c",
        name="mcp_exotic",
        artifact={"structured_content": structured},
    )
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    assert len(entries) == 1
    assert entries[0]["artifact_type"] == "data"
    assert entries[0]["real_ref"] == json.dumps(structured, ensure_ascii=False)


def test_structured_content_does_not_skip_file_blocks():
    result = ToolMessage(
        content=[
            {
                "type": "file",
                "source": {"type": "url", "url": "/mnt/user-data/outputs/chart.png", "mime_type": "image/png"},
            }
        ],
        tool_call_id="call-4d",
        name="mcp_mixed",
        artifact={"structured_content": {"task_id": "job-7"}},
    )
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    refs = {entry["real_ref"] for entry in entries}
    assert "job-7" in refs
    assert "/mnt/user-data/outputs/chart.png" in refs


def test_two_refs_in_one_text_block_get_distinct_handles():
    result = ToolMessage(
        content=[{"type": "text", "text": "Saved /mnt/user-data/outputs/a.txt and /mnt/user-data/outputs/b.csv"}],
        tool_call_id="call-3b",
        name="mcp_server_analyze",
    )
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    assert len(entries) == 2
    handles = {entry["handle"] for entry in entries}
    assert len(handles) == 2
    assert {entry["real_ref"] for entry in entries} == {"/mnt/user-data/outputs/a.txt", "/mnt/user-data/outputs/b.csv"}


def test_string_content_with_path_captured():
    result = ToolMessage(
        content="Wrote /mnt/user-data/outputs/notes.md successfully",
        tool_call_id="call-6b",
        name="write_file",
    )
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    assert len(entries) == 1
    assert entries[0]["real_ref"] == "/mnt/user-data/outputs/notes.md"
    assert entries[0]["artifact_type"] == "file"


def test_detect_refs_in_text_flag_disables_text_scans():
    result = ToolMessage(
        content=[{"type": "text", "text": "Report saved to /mnt/user-data/outputs/report.html"}],
        tool_call_id="call-3c",
        name="mcp_server_analyze",
    )
    entries = extract_artifacts_from_result(result, thread_id="thread-1", detect_refs_in_text=False)
    assert entries == []


def test_no_extraction_from_error_result():
    result = ToolMessage(
        content="Error: Tool failed",
        tool_call_id="call-5",
        name="mcp_server_analyze",
        status="error",
    )
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    assert entries == []


def test_no_extraction_from_plain_text_without_refs():
    result = ToolMessage(content="All done", tool_call_id="call-6", name="mcp_server_analyze")
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    assert entries == []


def test_detect_refs_in_text_paths():
    refs = _detect_refs_in_text("See /mnt/user-data/outputs/a.txt and /mnt/user-data/outputs/b.csv here.")
    paths = [r["ref"] for r in refs]
    assert "/mnt/user-data/outputs/a.txt" in paths
    assert "/mnt/user-data/outputs/b.csv" in paths


def test_detect_refs_in_text_urls():
    refs = _detect_refs_in_text("Download https://example.com/files/report.pdf now.")
    assert len(refs) == 1
    assert refs[0]["ref"] == "https://example.com/files/report.pdf"


def test_detect_refs_in_text_noise():
    refs = _detect_refs_in_text("No references here, just text.")
    assert refs == []


def test_detect_refs_in_text_strips_quotes_backticks_brackets():
    text = 'Saved to `/mnt/user-data/outputs/report.md` and {"path": "/mnt/user-data/a.txt"} plus [/mnt/user-data/c.csv]'
    values = [ref["ref"] for ref in _detect_refs_in_text(text)]
    assert "/mnt/user-data/outputs/report.md" in values
    assert "/mnt/user-data/a.txt" in values
    assert "/mnt/user-data/c.csv" in values


def test_string_content_with_quoted_path_captured_cleanly():
    result = ToolMessage(
        content='Wrote "/mnt/user-data/outputs/notes.md" successfully',
        tool_call_id="call-6c",
        name="write_file",
    )
    entries = extract_artifacts_from_result(result, thread_id="thread-1")
    assert len(entries) == 1
    assert entries[0]["real_ref"] == "/mnt/user-data/outputs/notes.md"


def test_merge_tool_artifacts_append():
    existing = [
        {
            "handle": "art_00000001",
            "tool_name": "t1",
            "tool_call_id": "call-1",
            "call_index": 0,
            "artifact_type": "file",
            "display_name": "a.txt",
            "real_ref": "/tmp/a.txt",
            "created_at": "2026-08-19T00:00:00Z",
        }
    ]
    new = [
        {
            "handle": "art_00000002",
            "tool_name": "t2",
            "tool_call_id": "call-2",
            "call_index": 0,
            "artifact_type": "file",
            "display_name": "b.txt",
            "real_ref": "/tmp/b.txt",
            "created_at": "2026-08-19T00:00:01Z",
        }
    ]
    merged = merge_tool_artifacts(existing, new)
    assert len(merged) == 2
    assert merged[0]["handle"] == "art_00000001"
    assert merged[1]["handle"] == "art_00000002"


def test_merge_tool_artifacts_dedup_same_handle_latest_wins():
    existing = [
        {
            "handle": "art_00000001",
            "tool_name": "t1",
            "tool_call_id": "call-1",
            "call_index": 0,
            "artifact_type": "file",
            "display_name": "a.txt",
            "real_ref": "/tmp/a.txt",
            "created_at": "2026-08-19T00:00:00Z",
        }
    ]
    new = [
        {
            "handle": "art_00000001",
            "tool_name": "t1",
            "tool_call_id": "call-1",
            "call_index": 0,
            "artifact_type": "file",
            "display_name": "a.txt",
            "real_ref": "/tmp/a-new.txt",
            "consumed_by": ["call-9"],
            "created_at": "2026-08-19T00:00:01Z",
        }
    ]
    merged = merge_tool_artifacts(existing, new)
    assert len(merged) == 1
    assert merged[0]["real_ref"] == "/tmp/a-new.txt"
    assert merged[0]["consumed_by"] == ["call-9"]


def test_merge_tool_artifacts_empty_new_preserves_existing():
    existing = [
        {
            "handle": "art_00000001",
            "tool_name": "t1",
            "tool_call_id": "call-1",
            "call_index": 0,
            "artifact_type": "file",
            "display_name": "a.txt",
            "real_ref": "/tmp/a.txt",
            "created_at": "2026-08-19T00:00:00Z",
        }
    ]
    merged = merge_tool_artifacts(existing, None)
    assert merged == existing
    merged2 = merge_tool_artifacts(existing, [])
    assert merged2 == existing


def test_merge_tool_artifacts_trim_directive_slides_window():
    """A trailing trim directive makes the configured cap a sliding window."""
    existing = [_entry(f"art_{i:08x}", i) for i in range(20)]
    fresh = [_entry(f"art_new{i:02x}", 100 + i) for i in range(2)]
    update = [*fresh, {"op": "trim_to", "keep": 20}]

    merged = merge_tool_artifacts(existing, update)

    assert len(merged) == 20
    assert merged[0]["handle"] == "art_00000002", "oldest two must be evicted"
    handles = {entry["handle"] for entry in merged}
    assert {f"art_new{i:02x}" for i in range(2)} <= handles, "fresh entries must survive"
    assert "art_00000000" not in handles and "art_00000001" not in handles


def test_merge_tool_artifacts_no_trim_without_directive():
    existing = [_entry(f"art_{i:08x}", i) for i in range(5)]
    fresh = [_entry(f"art_new{i:02x}", 50 + i) for i in range(2)]
    merged = merge_tool_artifacts(existing, fresh)
    assert len(merged) == 7


def test_merge_tool_artifacts_trim_clamped_to_ceiling():
    entries = [_entry(f"art_{i:08x}", i) for i in range(1200)]
    update = [*entries, {"op": "trim_to", "keep": 5000}]
    merged = merge_tool_artifacts(None, update)
    assert len(merged) == 1000
    assert merged[0]["handle"] == f"art_{200:08x}"


def test_merge_tool_artifacts_cap():
    """Reducer enforces the absolute ceiling only; configured caps live in the middleware."""
    entries = [_entry(f"art_{i:08x}", i) for i in range(1500)]
    merged = merge_tool_artifacts(None, entries)
    assert len(merged) == 1000
    assert merged[0]["handle"] == f"art_{500:08x}"
    assert merged[-1]["handle"] == f"art_{1499:08x}"


def test_merge_tool_artifacts_consumption_update_does_not_grow_count():
    entries = [_entry(f"art_{i:08x}", i) for i in range(1000)]
    consumed = {**entries[0], "consumed_by": ["call-x"]}
    merged = merge_tool_artifacts(entries, [consumed])
    assert len(merged) == 1000


# --- delimited sandbox paths (issue #7303) ---------------------------------


@pytest.mark.parametrize("delimiter", ['"', "'", "`"])
def test_a_delimited_sandbox_path_keeps_its_spaces(delimiter):
    """A tool that quotes the filename means the whole quoted string is the path."""
    path = "/mnt/user-data/outputs/quarterly report (final).pdf"

    refs = _detect_refs_in_text(f"Created {delimiter}{path}{delimiter} successfully.")

    assert [ref["ref"] for ref in refs] == [path]
    assert refs[0]["display"] == "quarterly report (final).pdf"


def test_a_bare_sandbox_path_keeps_the_whitespace_boundary():
    """Nothing tells the free-text scan where an undelimited name with spaces ends, so it
    keeps the conservative boundary it always had."""
    refs = _detect_refs_in_text("Created /mnt/user-data/outputs/quarterly report.pdf successfully.")

    assert [ref["ref"] for ref in refs] == ["/mnt/user-data/outputs/quarterly"]


@pytest.mark.parametrize(
    "text",
    [
        # Never closed on this line.
        'Created "/mnt/user-data/outputs/quarterly report.pdf successfully.',
        "Created '/mnt/user-data/outputs/quarterly report.pdf",
        "Created `/mnt/user-data/outputs/quarterly report.pdf",
        # Closed, but only after the line break: a multi-line value is not one path.
        'Created "/mnt/user-data/outputs/quarterly report.pdf\nsuccessfully."',
    ],
)
def test_an_unterminated_delimited_span_produces_no_reference(text):
    """A prefix of a quoted filename names a file that does not exist, so it is not
    reported at all rather than reported truncated."""
    assert _detect_refs_in_text(text) == []


def test_delimited_paths_keep_their_order_and_deduplicate():
    first = "/mnt/user-data/outputs/a report.pdf"
    second = "/mnt/user-data/outputs/b report.csv"

    refs = _detect_refs_in_text(f'Published `{first}` and "{second}", then again "{first}".')

    assert [ref["ref"] for ref in refs] == [first, second]


def test_a_delimited_and_a_bare_path_in_one_result_are_both_captured():
    quoted = "/mnt/user-data/outputs/a report.pdf"

    refs = _detect_refs_in_text(f'Copied to "{quoted}"; log at /mnt/user-data/workspace/run.log.')

    assert [ref["ref"] for ref in refs] == [quoted, "/mnt/user-data/workspace/run.log"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('Output: "/mnt/user-data/outputs/report.pdf".', "/mnt/user-data/outputs/report.pdf"),
        ("Output: `/mnt/user-data/outputs/report.pdf`,", "/mnt/user-data/outputs/report.pdf"),
    ],
)
def test_punctuation_outside_the_delimiter_is_not_part_of_the_reference(text, expected):
    assert [ref["ref"] for ref in _detect_refs_in_text(text)] == [expected]


def test_extraction_registers_the_full_delimited_path_once():
    path = "/mnt/user-data/outputs/quarterly report.pdf"
    message = ToolMessage(
        content=f'Created "{path}" successfully.',
        tool_call_id="export-1",
        name="export_report",
    )

    entries = extract_artifacts_from_result(message, thread_id="demo")

    assert [entry["real_ref"] for entry in entries] == [path]
    assert entries[0]["display_name"] == "quarterly report.pdf"
    assert entries[0]["artifact_type"] == "file"


@pytest.mark.parametrize("separator", ["\n", "\r", "\r\n", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029", "\t"])
@pytest.mark.parametrize("delimiter", ['"', "'", "`"])
def test_delimited_sandbox_path_rejects_line_breaks_and_tabs(separator, delimiter):
    message = ToolMessage(
        content=f"Created {delimiter}/mnt/user-data/outputs/quarterly{separator}report.pdf{delimiter}.",
        tool_call_id="export-multiline",
        name="export_report",
    )

    assert extract_artifacts_from_result(message, thread_id="demo") == []


@pytest.mark.parametrize("delimiter", ['"', "'", "`"])
@pytest.mark.parametrize("content_block", [False, True])
def test_backslash_escaped_delimiters_keep_the_full_sandbox_path(delimiter, content_block):
    path = "/mnt/user-data/outputs/quarterly report (final).pdf"
    text = f"log: \\{delimiter}{path}\\{delimiter} done"
    message = ToolMessage(
        content=[{"type": "text", "text": text}] if content_block else text,
        tool_call_id="export-escaped",
        name="export_report",
    )

    entries = extract_artifacts_from_result(message, thread_id="demo")

    assert [entry["real_ref"] for entry in entries] == [path]
    assert entries[0]["display_name"] == "quarterly report (final).pdf"


@pytest.mark.parametrize("escaped", [False, True])
def test_delimited_sandbox_path_keeps_a_literal_trailing_backslash(escaped):
    path = "/mnt/user-data/outputs/report \\"
    delimiter = '\\"' if escaped else '"'

    assert [ref["ref"] for ref in _detect_refs_in_text(f"Created {delimiter}{path}{delimiter}.")] == [path]


def test_json_escaped_path_deduplicates_against_a_structured_reference():
    path = "/mnt/user-data/outputs/quarterly report.pdf"
    message = ToolMessage(
        content=json.dumps(f'Created "{path}" successfully.'),
        tool_call_id="export-json",
        name="export_report",
        artifact={"structured_content": {"path": path}},
    )

    entries = extract_artifacts_from_result(message, thread_id="demo")

    assert [entry["real_ref"] for entry in entries] == [path]


def test_escaped_sandbox_path_requires_a_matching_escaped_closer():
    assert _detect_refs_in_text(r'Created \"/mnt/user-data/outputs/quarterly report.pdf" successfully.') == []


_LINE_BREAKS = ["\n", "\r", "\r\n", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]
_CJK_QUOTE_PAIRS = [("“", "”"), ("‘", "’"), ("「", "」"), ("『", "』")]


@pytest.mark.parametrize("separator", [*_LINE_BREAKS, "\t"])
@pytest.mark.parametrize(("opener", "closer"), _CJK_QUOTE_PAIRS)
def test_delimited_sandbox_paths_reject_line_breaks_and_tabs(separator, opener, closer):
    path = f"/mnt/user-data/outputs/quarterly{separator}report.pdf"

    assert _detect_refs_in_text(f"Created {opener}{path}{closer}.") == []


@pytest.mark.parametrize("separator", _LINE_BREAKS)
def test_unterminated_path_does_not_swallow_a_reference_on_the_next_line(separator):
    valid = "/mnt/user-data/outputs/next.pdf"
    text = f'Created "/mnt/user-data/outputs/unfinished report.pdf{separator}Saved {valid}"'

    assert [ref["ref"] for ref in _detect_refs_in_text(text)] == [valid]


@pytest.mark.parametrize("delimiter", ['"', "'", "`"])
@pytest.mark.parametrize("escape_count", [3])
@pytest.mark.parametrize(("path", "display"), [("/mnt/user-data/outputs/a b.pdf", "a b.pdf"), (r"/mnt/user-data/outputs/folder\name report.pdf", "name report.pdf")])
def test_escaped_quote_wrappers_do_not_append_backslashes(delimiter, escape_count, path, display):
    marker = "\\" * escape_count + delimiter

    refs = _detect_refs_in_text(f"log: {marker}{path}{marker} done")

    assert [ref["ref"] for ref in refs] == [path]
    assert refs[0]["display"] == display


@pytest.mark.parametrize(("opener", "closer"), _CJK_QUOTE_PAIRS)
def test_cjk_quote_pairs_keep_the_entire_sandbox_path(opener, closer):
    path = "/mnt/user-data/outputs/输出 报告（最终）.pdf"

    refs = _detect_refs_in_text(f"已创建 {opener}{path}{closer}，完成。")

    assert [ref["ref"] for ref in refs] == [path]
    assert refs[0]["display"] == "输出 报告（最终）.pdf"


@pytest.mark.parametrize("opener", [opener for opener, _ in _CJK_QUOTE_PAIRS])
def test_unterminated_cjk_quotes_do_not_register_prefixes(opener):
    assert _detect_refs_in_text(f"已创建 {opener}/mnt/user-data/outputs/输出 报告.pdf") == []


@pytest.mark.parametrize("closer", [closer for _, closer in _CJK_QUOTE_PAIRS[-2:]])
def test_a_bare_path_drops_an_unpaired_corner_closer(closer):
    path = "/mnt/user-data/outputs/报告.pdf"

    assert [ref["ref"] for ref in _detect_refs_in_text(f"已生成 {path}{closer}，")] == [path]


def test_even_backslashes_before_a_quote_preserve_literal_path_backslashes():
    prefix = "\\" * 2
    path = "/mnt/user-data/outputs/a b\\"

    assert [ref["ref"] for ref in _detect_refs_in_text(f'{prefix}"{path}"')] == [path]


@pytest.mark.parametrize(("opener", "closer"), [('\\"', '\\"'), *_CJK_QUOTE_PAIRS])
@pytest.mark.parametrize("text_block", [False, True])
def test_review_quote_wrappers_deduplicate_structured_refs_and_keep_order(opener, closer, text_block):
    first = "/mnt/user-data/outputs/输出 报告.pdf"
    second = "/mnt/user-data/outputs/second report.csv"
    text = f"Created {opener}{first}{closer}, then {opener}{second}{closer}, then {opener}{first}{closer}."
    message = ToolMessage(
        content=[{"type": "text", "text": text}] if text_block else text,
        artifact={"structured_content": {"path": first}},
        tool_call_id="export-review",
        name="export_report",
    )

    entries = extract_artifacts_from_result(message, thread_id="demo")

    assert [entry["real_ref"] for entry in entries] == [first, second]
    assert [entry["display_name"] for entry in entries] == ["输出 报告.pdf", "second report.csv"]
    assert len({entry["handle"] for entry in entries}) == 2


@pytest.mark.parametrize("text_block", [False, True])
def test_raw_json_text_preserves_a_quoted_sandbox_path(text_block):
    path = "/mnt/user-data/outputs/quarterly report.pdf"
    text = json.dumps({"message": f'Created "{path}" successfully.'})
    message = ToolMessage(content=[{"type": "text", "text": text}] if text_block else text, tool_call_id="export-json", name="export_report")

    entries = extract_artifacts_from_result(message, thread_id="demo")

    assert [entry["real_ref"] for entry in entries] == [path]
    assert entries[0]["display_name"] == "quarterly report.pdf"
