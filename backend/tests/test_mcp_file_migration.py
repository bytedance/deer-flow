"""Tests for translating MCP-produced local files into virtual sandbox paths.

Regression coverage for GitHub issue #3597: Playwright MCP (and similar stdio
servers) write files to a path the sandbox/artifact API cannot resolve. The MCP
tool wrapper pins stdio cwd/temp under the thread's mounted user-data tree and
rewrites returned file references to ``/mnt/user-data/...`` virtual paths.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from mcp.types import CallToolResult, ResourceLink, TextContent

from deerflow.config.paths import VIRTUAL_PATH_PREFIX, Paths
from deerflow.mcp import tools as mcp_tools


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(tmp_path)


def _patch_paths(paths: Paths):
    return patch("deerflow.mcp.tools.get_paths", return_value=paths)


def _workspace_file(paths: Paths, relative_path: str, *, content: bytes = b"data") -> Path:
    file_path = paths.sandbox_work_dir("t1", user_id="u1") / relative_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)
    return file_path


class TestLocalPathFromUri:
    def test_file_uri(self):
        assert mcp_tools._local_path_from_uri("file:///tmp/shot.png") == Path("/tmp/shot.png")

    def test_bare_absolute_path(self):
        assert mcp_tools._local_path_from_uri("/var/data/out.pdf") == Path("/var/data/out.pdf")

    def test_file_uri_with_url_encoded_spaces(self):
        assert mcp_tools._local_path_from_uri("file:///tmp/my%20shot.png") == Path("/tmp/my shot.png")

    def test_remote_uri_is_ignored(self):
        assert mcp_tools._local_path_from_uri("https://example.com/a.png") is None
        assert mcp_tools._local_path_from_uri("data:image/png;base64,AAAA") is None

    def test_relative_path_is_ignored_without_base_dir(self):
        assert mcp_tools._local_path_from_uri("relative/path.txt") is None

    def test_relative_path_uses_base_dir_when_provided(self, tmp_path: Path):
        assert mcp_tools._local_path_from_uri("./shot.png", base_dir=tmp_path) == tmp_path / "shot.png"
        assert mcp_tools._local_path_from_uri("temp/page.yml", base_dir=tmp_path) == tmp_path / "temp/page.yml"

    def test_file_uri_with_relative_path_is_ignored(self):
        assert mcp_tools._local_path_from_uri("file:relative.txt") is None

    def test_file_uri_with_empty_path_is_ignored(self):
        assert mcp_tools._local_path_from_uri("file://") is None

    def test_file_uri_with_localhost_host(self):
        # file://localhost/abs/path is the host form of file:///abs/path.
        assert mcp_tools._local_path_from_uri("file://localhost/tmp/shot.png") == Path("/tmp/shot.png")

    def test_empty_is_ignored(self):
        assert mcp_tools._local_path_from_uri("") is None


class TestLocalUriToVirtualPath:
    def test_workspace_file_translates_to_virtual_workspace_path(self, paths: Paths):
        src = _workspace_file(paths, "temp/page.yml")

        with _patch_paths(paths):
            result = mcp_tools._local_uri_to_virtual_path(str(src), thread_id="t1", user_id="u1")

        assert result == f"{VIRTUAL_PATH_PREFIX}/workspace/temp/page.yml"

    def test_outputs_file_translates_without_copy(self, paths: Paths):
        outputs = paths.sandbox_outputs_dir("t1", user_id="u1")
        outputs.mkdir(parents=True)
        src = outputs / "report.pdf"
        src.write_bytes(b"pdf")

        with _patch_paths(paths):
            result = mcp_tools._local_uri_to_virtual_path(str(src), thread_id="t1", user_id="u1")

        assert result == f"{VIRTUAL_PATH_PREFIX}/outputs/report.pdf"
        assert list(outputs.iterdir()) == [src]

    def test_relative_review_case_translates_against_cwd(self, paths: Paths):
        workspace = paths.sandbox_work_dir("t1", user_id="u1")
        _workspace_file(paths, "temp/page-2026-06-16T10-21-46-864Z.yml")

        with _patch_paths(paths):
            result = mcp_tools._local_uri_to_virtual_path(
                "temp/page-2026-06-16T10-21-46-864Z.yml",
                thread_id="t1",
                user_id="u1",
                source_base_dir=workspace,
            )

        assert result == f"{VIRTUAL_PATH_PREFIX}/workspace/temp/page-2026-06-16T10-21-46-864Z.yml"

    def test_file_uri_inside_user_data_translates(self, paths: Paths):
        src = _workspace_file(paths, "shot.png")

        with _patch_paths(paths):
            result = mcp_tools._local_uri_to_virtual_path(f"file://{src}", thread_id="t1", user_id="u1")

        assert result == f"{VIRTUAL_PATH_PREFIX}/workspace/shot.png"

    def test_file_outside_user_data_is_not_exposed(self, tmp_path: Path, paths: Paths):
        src = tmp_path / "outside.txt"
        src.write_text("secret")

        with _patch_paths(paths):
            result = mcp_tools._local_uri_to_virtual_path(str(src), thread_id="t1", user_id="u1")

        assert result is None
        assert not paths.sandbox_outputs_dir("t1", user_id="u1").exists()

    def test_missing_file_directory_and_remote_uri_are_ignored(self, tmp_path: Path, paths: Paths):
        with _patch_paths(paths):
            assert mcp_tools._local_uri_to_virtual_path(str(tmp_path / "missing.png"), thread_id="t1", user_id="u1") is None
            assert mcp_tools._local_uri_to_virtual_path(str(tmp_path), thread_id="t1", user_id="u1") is None
            assert mcp_tools._local_uri_to_virtual_path("https://example.com/a.png", thread_id="t1", user_id="u1") is None

    def test_symlink_escape_is_not_exposed(self, tmp_path: Path, paths: Paths):
        outside = tmp_path / "outside.txt"
        outside.write_text("secret")
        link = paths.sandbox_work_dir("t1", user_id="u1") / "link.txt"
        link.parent.mkdir(parents=True)
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")

        with _patch_paths(paths):
            result = mcp_tools._local_uri_to_virtual_path(str(link), thread_id="t1", user_id="u1")

        assert result is None


class TestRewriteLocalPathsInText:
    def test_review_case_temp_relative_path_is_rewritten(self, paths: Paths):
        workspace = paths.sandbox_work_dir("t1", user_id="u1")
        _workspace_file(paths, "temp/page-2026-06-16T10-21-46-864Z.yml")
        text = "Saved as temp/page-2026-06-16T10-21-46-864Z.yml."

        with _patch_paths(paths):
            result = mcp_tools._rewrite_local_paths_in_text(text, thread_id="t1", user_id="u1", source_base_dir=workspace)

        assert result == f"Saved as {VIRTUAL_PATH_PREFIX}/workspace/temp/page-2026-06-16T10-21-46-864Z.yml."

    def test_relative_output_dir_path_is_rewritten(self, paths: Paths):
        workspace = paths.sandbox_work_dir("t1", user_id="u1")
        _workspace_file(paths, "artifacts/page.png")
        text = "Screenshot saved to artifacts/page.png"

        with _patch_paths(paths):
            result = mcp_tools._rewrite_local_paths_in_text(text, thread_id="t1", user_id="u1", source_base_dir=workspace)

        assert result == f"Screenshot saved to {VIRTUAL_PATH_PREFIX}/workspace/artifacts/page.png"

    def test_absolute_output_dir_path_inside_user_data_is_rewritten(self, paths: Paths):
        src = _workspace_file(paths, "absolute-output/page.png")
        text = f"Screenshot saved to {src}"

        with _patch_paths(paths):
            result = mcp_tools._rewrite_local_paths_in_text(text, thread_id="t1", user_id="u1")

        assert result == f"Screenshot saved to {VIRTUAL_PATH_PREFIX}/workspace/absolute-output/page.png"

    def test_tmpdir_output_under_workspace_is_rewritten(self, paths: Paths):
        src = _workspace_file(paths, ".mcp/tmp/page.png")
        text = f"Saved to {src}"

        with _patch_paths(paths):
            result = mcp_tools._rewrite_local_paths_in_text(text, thread_id="t1", user_id="u1")

        assert result == f"Saved to {VIRTUAL_PATH_PREFIX}/workspace/.mcp/tmp/page.png"

    def test_old_tmp_path_outside_user_data_is_left_untouched(self, tmp_path: Path, paths: Paths):
        src = tmp_path / "playwright-mcp-output" / "page.png"
        src.parent.mkdir()
        src.write_bytes(b"png")
        text = f"Saved to {src}"

        with _patch_paths(paths):
            result = mcp_tools._rewrite_local_paths_in_text(text, thread_id="t1", user_id="u1")

        assert result == text

    def test_playwright_markdown_path_is_rewritten_twice_without_copy(self, paths: Paths):
        workspace = paths.sandbox_work_dir("t1", user_id="u1")
        _workspace_file(paths, ".playwright-mcp/page.png", content=b"png")
        text = "### Result\n- [Screenshot](.playwright-mcp/page.png)\npath: '.playwright-mcp/page.png'"

        with _patch_paths(paths):
            result = mcp_tools._rewrite_local_paths_in_text(text, thread_id="t1", user_id="u1", source_base_dir=workspace)

        assert result.count(f"{VIRTUAL_PATH_PREFIX}/workspace/.playwright-mcp/page.png") == 2
        assert not paths.sandbox_outputs_dir("t1", user_id="u1").exists()

    def test_bare_filename_is_rewritten_only_when_changed_file_matches_uniquely(self, paths: Paths):
        workspace = paths.sandbox_work_dir("t1", user_id="u1")
        src = _workspace_file(paths, "page-2026-06-16T10-21-46-864Z.yml")
        text = "Saved as page-2026-06-16T10-21-46-864Z.yml."

        with _patch_paths(paths):
            result = mcp_tools._rewrite_local_paths_in_text(
                text,
                thread_id="t1",
                user_id="u1",
                source_base_dir=workspace,
                changed_files=[src],
            )

        assert result == f"Saved as {VIRTUAL_PATH_PREFIX}/workspace/page-2026-06-16T10-21-46-864Z.yml."

    def test_bare_filename_without_changed_file_is_left_untouched(self, paths: Paths):
        workspace = paths.sandbox_work_dir("t1", user_id="u1")
        _workspace_file(paths, "page.yml")
        text = "Saved as page.yml"

        with _patch_paths(paths):
            result = mcp_tools._rewrite_local_paths_in_text(text, thread_id="t1", user_id="u1", source_base_dir=workspace)

        assert result == text

    def test_bare_filename_with_multiple_changed_matches_is_left_untouched(self, paths: Paths):
        workspace = paths.sandbox_work_dir("t1", user_id="u1")
        a = _workspace_file(paths, "a/page.yml")
        b = _workspace_file(paths, "b/page.yml")
        text = "Saved as page.yml"

        with _patch_paths(paths):
            result = mcp_tools._rewrite_local_paths_in_text(
                text,
                thread_id="t1",
                user_id="u1",
                source_base_dir=workspace,
                changed_files=[a, b],
            )

        assert result == text

    def test_bare_filename_does_not_rewrite_longer_filename(self, paths: Paths):
        workspace = paths.sandbox_work_dir("t1", user_id="u1")
        src = _workspace_file(paths, "page.yml")
        text = "Backup is page.yml.bak"

        with _patch_paths(paths):
            result = mcp_tools._rewrite_local_paths_in_text(
                text,
                thread_id="t1",
                user_id="u1",
                source_base_dir=workspace,
                changed_files=[src],
            )

        assert result == text

    def test_multiple_distinct_paths_in_one_message_all_rewritten(self, paths: Paths):
        workspace = paths.sandbox_work_dir("t1", user_id="u1")
        _workspace_file(paths, "temp/a.png")
        _workspace_file(paths, "temp/b.png")
        text = "Saved temp/a.png and temp/b.png together."

        with _patch_paths(paths):
            result = mcp_tools._rewrite_local_paths_in_text(text, thread_id="t1", user_id="u1", source_base_dir=workspace)

        assert result == (f"Saved {VIRTUAL_PATH_PREFIX}/workspace/temp/a.png and {VIRTUAL_PATH_PREFIX}/workspace/temp/b.png together.")

    def test_markdown_link_in_parentheses_is_rewritten_without_eating_paren(self, paths: Paths):
        workspace = paths.sandbox_work_dir("t1", user_id="u1")
        _workspace_file(paths, "temp/shot.png")
        text = "See ![shot](temp/shot.png) now"

        with _patch_paths(paths):
            result = mcp_tools._rewrite_local_paths_in_text(text, thread_id="t1", user_id="u1", source_base_dir=workspace)

        assert result == f"See ![shot]({VIRTUAL_PATH_PREFIX}/workspace/temp/shot.png) now"

    def test_path_for_nonexistent_relative_file_is_left_untouched(self, paths: Paths):
        workspace = paths.sandbox_work_dir("t1", user_id="u1")
        text = "Saved as temp/never-created.png"

        with _patch_paths(paths):
            result = mcp_tools._rewrite_local_paths_in_text(text, thread_id="t1", user_id="u1", source_base_dir=workspace)

        assert result == text

    def test_bare_filename_is_case_sensitive(self, paths: Paths):
        workspace = paths.sandbox_work_dir("t1", user_id="u1")
        src = _workspace_file(paths, "Page.yml")
        text = "saved as page.yml"

        with _patch_paths(paths):
            result = mcp_tools._rewrite_local_paths_in_text(
                text,
                thread_id="t1",
                user_id="u1",
                source_base_dir=workspace,
                changed_files=[src],
            )

        assert result == text

    def test_bare_filename_not_rewritten_when_used_as_directory_segment(self, paths: Paths):
        workspace = paths.sandbox_work_dir("t1", user_id="u1")
        src = _workspace_file(paths, "page.yml")
        text = "nested page.yml/inner.txt path"

        with _patch_paths(paths):
            result = mcp_tools._rewrite_local_paths_in_text(
                text,
                thread_id="t1",
                user_id="u1",
                source_base_dir=workspace,
                changed_files=[src],
            )

        assert result == text


class TestWorkspaceSnapshots:
    def test_changed_workspace_files_detects_created_and_modified_files(self, paths: Paths):
        import time

        workspace = paths.sandbox_work_dir("t1", user_id="u1")
        existing = _workspace_file(paths, "existing.txt", content=b"old")
        before = mcp_tools._snapshot_workspace_files(workspace)

        # Ensure the mtime advances so the change is detectable.  Without the
        # sleep, write_bytes(b"new") may land in the same nanosecond as the
        # snapshot, and since b"old" and b"new" have the same length, the
        # (mtime_ns, size) signature stays identical → _changed_workspace_files
        # misses the modification.
        time.sleep(0.05)
        existing.write_bytes(b"new_content")  # different length guarantees size change too
        created = _workspace_file(paths, "created.txt", content=b"created")

        changed = set(mcp_tools._changed_workspace_files(workspace, before))

        assert changed == {existing, created}

    def test_snapshot_of_missing_directory_is_empty(self, tmp_path: Path):
        assert mcp_tools._snapshot_workspace_files(tmp_path / "does-not-exist") == {}

    def test_no_change_yields_no_changed_files(self, paths: Paths):
        workspace = paths.sandbox_work_dir("t1", user_id="u1")
        _workspace_file(paths, "stable.txt")
        before = mcp_tools._snapshot_workspace_files(workspace)

        assert mcp_tools._changed_workspace_files(workspace, before) == []

    def test_deleted_file_is_not_reported_as_changed(self, paths: Paths):
        workspace = paths.sandbox_work_dir("t1", user_id="u1")
        victim = _workspace_file(paths, "victim.txt")
        before = mcp_tools._snapshot_workspace_files(workspace)

        victim.unlink()

        assert mcp_tools._changed_workspace_files(workspace, before) == []


class TestPrepareStdioWorkspace:
    def test_creates_dirs_and_returns_snapshot(self, paths: Paths):
        existing = _workspace_file(paths, "existing.txt", content=b"old")

        source_base_dir, tmp_dir, before = mcp_tools._prepare_stdio_workspace(paths, thread_id="t1", user_id="u1")

        assert source_base_dir == paths.sandbox_work_dir("t1", user_id="u1")
        assert tmp_dir == source_base_dir / mcp_tools._MCP_TMP_SUBDIR
        assert tmp_dir.is_dir()
        assert before == {existing: (existing.stat().st_mtime_ns, existing.stat().st_size)}


class TestResultHasTextContent:
    def test_text_content_is_detected(self):
        result = CallToolResult(content=[TextContent(type="text", text="hi")], isError=False)
        assert mcp_tools._result_has_text_content(result) is True

    def test_embedded_text_resource_is_detected(self):
        from mcp.types import EmbeddedResource, TextResourceContents

        res = TextResourceContents(uri="mem://n.txt", text="n", mimeType="text/plain")
        result = CallToolResult(content=[EmbeddedResource(type="resource", resource=res)], isError=False)
        assert mcp_tools._result_has_text_content(result) is True

    def test_image_only_result_has_no_text(self):
        from mcp.types import ImageContent

        result = CallToolResult(content=[ImageContent(type="image", data="QUJD", mimeType="image/png")], isError=False)
        assert mcp_tools._result_has_text_content(result) is False

    def test_empty_content_has_no_text(self):
        result = CallToolResult(content=[], isError=False)
        assert mcp_tools._result_has_text_content(result) is False


class TestConvertCallToolResultRewrites:
    def test_resource_link_image_inside_workspace_rewritten(self, paths: Paths):
        src = _workspace_file(paths, "page.png", content=b"png")
        result = CallToolResult(
            content=[ResourceLink(type="resource_link", name="page", uri=f"file://{src}", mimeType="image/png")],
            isError=False,
        )

        with _patch_paths(paths):
            content, _ = mcp_tools._convert_call_tool_result(result, thread_id="t1", user_id="u1")

        assert content[0]["type"] == "image"
        assert content[0]["url"] == f"{VIRTUAL_PATH_PREFIX}/workspace/page.png"

    def test_resource_link_file_inside_outputs_rewritten(self, paths: Paths):
        outputs = paths.sandbox_outputs_dir("t1", user_id="u1")
        outputs.mkdir(parents=True)
        src = outputs / "doc.pdf"
        src.write_bytes(b"pdf")
        result = CallToolResult(
            content=[ResourceLink(type="resource_link", name="doc", uri=f"file://{src}", mimeType="application/pdf")],
            isError=False,
        )

        with _patch_paths(paths):
            content, _ = mcp_tools._convert_call_tool_result(result, thread_id="t1", user_id="u1")

        assert content[0]["type"] == "file"
        assert content[0]["url"] == f"{VIRTUAL_PATH_PREFIX}/outputs/doc.pdf"

    def test_resource_link_outside_user_data_untouched(self, tmp_path: Path, paths: Paths):
        src = tmp_path / "page.png"
        src.write_bytes(b"png")
        uri = f"file://{src}"
        result = CallToolResult(
            content=[ResourceLink(type="resource_link", name="page", uri=uri, mimeType="image/png")],
            isError=False,
        )

        with _patch_paths(paths):
            content, _ = mcp_tools._convert_call_tool_result(result, thread_id="t1", user_id="u1")

        assert content[0]["url"] == uri

    def test_remote_resource_link_untouched(self, paths: Paths):
        url = "https://example.com/remote.png"
        result = CallToolResult(
            content=[ResourceLink(type="resource_link", name="r", uri=url, mimeType="image/png")],
            isError=False,
        )

        with _patch_paths(paths):
            content, _ = mcp_tools._convert_call_tool_result(result, thread_id="t1", user_id="u1")

        assert content[0]["url"] == url

    def test_text_review_case_rewritten(self, paths: Paths):
        workspace = paths.sandbox_work_dir("t1", user_id="u1")
        _workspace_file(paths, "temp/page-2026-06-16T10-21-46-864Z.yml")
        result = CallToolResult(
            content=[TextContent(type="text", text="Saved as temp/page-2026-06-16T10-21-46-864Z.yml")],
            isError=False,
        )

        with _patch_paths(paths):
            content, _ = mcp_tools._convert_call_tool_result(result, thread_id="t1", user_id="u1", source_base_dir=workspace)

        assert content[0]["text"] == f"Saved as {VIRTUAL_PATH_PREFIX}/workspace/temp/page-2026-06-16T10-21-46-864Z.yml"

    def test_text_bare_filename_rewritten_from_changed_files(self, paths: Paths):
        workspace = paths.sandbox_work_dir("t1", user_id="u1")
        src = _workspace_file(paths, "page-2026.yml")
        result = CallToolResult(content=[TextContent(type="text", text="Saved as page-2026.yml")], isError=False)

        with _patch_paths(paths):
            content, _ = mcp_tools._convert_call_tool_result(
                result,
                thread_id="t1",
                user_id="u1",
                source_base_dir=workspace,
                changed_files=[src],
            )

        assert content[0]["text"] == f"Saved as {VIRTUAL_PATH_PREFIX}/workspace/page-2026.yml"

    def test_no_context_does_not_rewrite(self, paths: Paths):
        src = _workspace_file(paths, "x.png", content=b"png")
        uri = f"file://{src}"
        result = CallToolResult(
            content=[ResourceLink(type="resource_link", name="x", uri=uri, mimeType="image/png")],
            isError=False,
        )

        with _patch_paths(paths):
            content, _ = mcp_tools._convert_call_tool_result(result)

        assert content[0]["url"] == uri

    def test_text_content_passthrough(self, paths: Paths):
        result = CallToolResult(content=[TextContent(type="text", text="hello")], isError=False)

        with _patch_paths(paths):
            content, _ = mcp_tools._convert_call_tool_result(result, thread_id="t1", user_id="u1")

        assert content[0]["type"] == "text"
        assert content[0]["text"] == "hello"

    def test_image_content_passthrough(self, paths: Paths):
        from mcp.types import ImageContent

        result = CallToolResult(content=[ImageContent(type="image", data="QUJD", mimeType="image/png")], isError=False)

        with _patch_paths(paths):
            content, _ = mcp_tools._convert_call_tool_result(result, thread_id="t1", user_id="u1")

        assert content[0]["type"] == "image"

    def test_embedded_text_resource(self, paths: Paths):
        from mcp.types import EmbeddedResource, TextResourceContents

        res = TextResourceContents(uri="mem://note.txt", text="note", mimeType="text/plain")
        result = CallToolResult(content=[EmbeddedResource(type="resource", resource=res)], isError=False)

        with _patch_paths(paths):
            content, _ = mcp_tools._convert_call_tool_result(result, thread_id="t1", user_id="u1")

        assert content[0]["type"] == "text"
        assert content[0]["text"] == "note"

    def test_embedded_blob_image_resource(self, paths: Paths):
        from mcp.types import BlobResourceContents, EmbeddedResource

        res = BlobResourceContents(uri="mem://img.png", blob="QUJD", mimeType="image/png")
        result = CallToolResult(content=[EmbeddedResource(type="resource", resource=res)], isError=False)

        with _patch_paths(paths):
            content, _ = mcp_tools._convert_call_tool_result(result, thread_id="t1", user_id="u1")

        assert content[0]["type"] == "image"

    def test_embedded_blob_file_resource(self, paths: Paths):
        from mcp.types import BlobResourceContents, EmbeddedResource

        res = BlobResourceContents(uri="mem://doc.pdf", blob="QUJD", mimeType="application/pdf")
        result = CallToolResult(content=[EmbeddedResource(type="resource", resource=res)], isError=False)

        with _patch_paths(paths):
            content, _ = mcp_tools._convert_call_tool_result(result, thread_id="t1", user_id="u1")

        assert content[0]["type"] == "file"

    def test_unknown_content_item_stringified(self, paths: Paths):
        class _Weird:
            def __str__(self) -> str:
                return "weird-item"

        result = CallToolResult(content=[TextContent(type="text", text="x")], isError=False)
        result.content = [_Weird()]  # bypass pydantic validation on the union

        with _patch_paths(paths):
            content, _ = mcp_tools._convert_call_tool_result(result, thread_id="t1", user_id="u1")

        assert content[0]["type"] == "text"
        assert content[0]["text"] == "weird-item"

    def test_error_result_raises_tool_exception(self, paths: Paths):
        from langchain_core.tools import ToolException

        result = CallToolResult(content=[TextContent(type="text", text="boom")], isError=True)

        with _patch_paths(paths), pytest.raises(ToolException, match="boom"):
            mcp_tools._convert_call_tool_result(result, thread_id="t1", user_id="u1")

    def test_structured_content_becomes_artifact(self, paths: Paths):
        result = CallToolResult(content=[TextContent(type="text", text="ok")], structuredContent={"k": "v"}, isError=False)

        with _patch_paths(paths):
            _, artifact = mcp_tools._convert_call_tool_result(result, thread_id="t1", user_id="u1")

        assert artifact == {"structured_content": {"k": "v"}}
