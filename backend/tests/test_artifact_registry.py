"""Tests for the persistent artifact handle registry (issue #4676)."""

import json

from langchain_core.messages import ToolMessage

from deerflow.agents.thread_state import (
    _TOOL_ARTIFACT_MAX_ENTRIES_DEFAULT,
    configure_tool_artifact_max_entries,
    merge_tool_artifacts,
)
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


def test_merge_tool_artifacts_cap():
    entries = [
        {
            "handle": f"art_{i:08x}",
            "tool_name": "t",
            "tool_call_id": f"call-{i}",
            "call_index": 0,
            "artifact_type": "file",
            "display_name": f"{i}.txt",
            "real_ref": f"/tmp/{i}.txt",
            "created_at": "2026-08-19T00:00:00Z",
        }
        for i in range(150)
    ]
    merged = merge_tool_artifacts(None, entries)
    assert len(merged) == 100
    assert merged[0]["handle"] == "art_00000032"


def test_merge_tool_artifacts_respects_configured_cap():
    entries = [_entry(f"art_{i:08x}", i) for i in range(30)]
    configure_tool_artifact_max_entries(20)
    try:
        merged = merge_tool_artifacts(None, entries)
        assert len(merged) == 20
        assert merged[0]["handle"] == "art_0000000a"
        merged2 = merge_tool_artifacts(entries[:10], entries[10:])
        assert len(merged2) == 20
    finally:
        configure_tool_artifact_max_entries(_TOOL_ARTIFACT_MAX_ENTRIES_DEFAULT)


def test_configure_tool_artifact_max_entries_clamps():
    configure_tool_artifact_max_entries(5)
    try:
        entries = [_entry(f"art_{i:08x}", i) for i in range(30)]
        assert len(merge_tool_artifacts(None, entries)) == 10
    finally:
        configure_tool_artifact_max_entries(_TOOL_ARTIFACT_MAX_ENTRIES_DEFAULT)
    configure_tool_artifact_max_entries(5000)
    try:
        entries = [_entry(f"art_{i:08x}", i) for i in range(1100)]
        assert len(merge_tool_artifacts(None, entries)) == 1000
    finally:
        configure_tool_artifact_max_entries(_TOOL_ARTIFACT_MAX_ENTRIES_DEFAULT)