"""Core behaviour tests for UploadsMiddleware.

Covers:
- _files_from_kwargs: parsing, validation, existence check, virtual-path construction
- _create_files_message: output format with new-only and new+historical files
- before_agent: full injection pipeline (string & list content, preserved
  additional_kwargs, historical files from uploads dir, edge-cases)
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.uploads_middleware import UploadsMiddleware
from deerflow.config.paths import Paths
from deerflow.uploads.manager import write_docx_sidecar_manifest

THREAD_ID = "thread-abc123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _middleware(tmp_path: Path) -> UploadsMiddleware:
    return UploadsMiddleware(base_dir=str(tmp_path))


def _runtime(thread_id: str | None = THREAD_ID) -> MagicMock:
    rt = MagicMock()
    rt.context = {"thread_id": thread_id}
    return rt


def _uploads_dir(tmp_path: Path, thread_id: str = THREAD_ID) -> Path:
    d = Paths(str(tmp_path)).sandbox_uploads_dir(thread_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _human(content, files=None, **extra_kwargs):
    additional_kwargs = dict(extra_kwargs)
    if files is not None:
        additional_kwargs["files"] = files
    return HumanMessage(content=content, additional_kwargs=additional_kwargs)


# ---------------------------------------------------------------------------
# _files_from_kwargs
# ---------------------------------------------------------------------------


class TestFilesFromKwargs:
    def test_returns_none_when_files_field_absent(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = HumanMessage(content="hello")
        assert mw._files_from_kwargs(msg) is None

    def test_returns_none_for_empty_files_list(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = _human("hello", files=[])
        assert mw._files_from_kwargs(msg) is None

    def test_returns_none_for_non_list_files(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = _human("hello", files="not-a-list")
        assert mw._files_from_kwargs(msg) is None

    def test_skips_non_dict_entries(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = _human("hi", files=["bad", 42, None])
        assert mw._files_from_kwargs(msg) is None

    def test_skips_entries_with_empty_filename(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = _human("hi", files=[{"filename": "", "size": 100, "path": "/mnt/user-data/uploads/x"}])
        assert mw._files_from_kwargs(msg) is None

    def test_always_uses_virtual_path(self, tmp_path):
        """path field must be /mnt/user-data/uploads/<filename> regardless of what the frontend sent."""
        mw = _middleware(tmp_path)
        msg = _human(
            "hi",
            files=[{"filename": "report.pdf", "size": 1024, "path": "/some/arbitrary/path/report.pdf"}],
        )
        result = mw._files_from_kwargs(msg)
        assert result is not None
        assert result[0]["path"] == "/mnt/user-data/uploads/report.pdf"

    def test_skips_file_that_does_not_exist_on_disk(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        # file is NOT written to disk
        msg = _human("hi", files=[{"filename": "missing.txt", "size": 50, "path": "/mnt/user-data/uploads/missing.txt"}])
        assert mw._files_from_kwargs(msg, uploads_dir) is None

    def test_accepts_file_that_exists_on_disk(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "data.csv").write_text("a,b,c")
        msg = _human("hi", files=[{"filename": "data.csv", "size": 5, "path": "/mnt/user-data/uploads/data.csv"}])
        result = mw._files_from_kwargs(msg, uploads_dir)
        assert result is not None
        assert len(result) == 1
        assert result[0]["filename"] == "data.csv"
        assert result[0]["path"] == "/mnt/user-data/uploads/data.csv"

    def test_skips_nonexistent_but_accepts_existing_in_mixed_list(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "present.txt").write_text("here")
        msg = _human(
            "hi",
            files=[
                {"filename": "present.txt", "size": 4, "path": "/mnt/user-data/uploads/present.txt"},
                {"filename": "gone.txt", "size": 4, "path": "/mnt/user-data/uploads/gone.txt"},
            ],
        )
        result = mw._files_from_kwargs(msg, uploads_dir)
        assert result is not None
        assert [f["filename"] for f in result] == ["present.txt"]

    def test_no_existence_check_when_uploads_dir_is_none(self, tmp_path):
        """Without an uploads_dir argument the existence check is skipped entirely."""
        mw = _middleware(tmp_path)
        msg = _human("hi", files=[{"filename": "phantom.txt", "size": 10, "path": "/mnt/user-data/uploads/phantom.txt"}])
        result = mw._files_from_kwargs(msg, uploads_dir=None)
        assert result is not None
        assert result[0]["filename"] == "phantom.txt"

    def test_size_is_coerced_to_int(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = _human("hi", files=[{"filename": "f.txt", "size": "2048", "path": "/mnt/user-data/uploads/f.txt"}])
        result = mw._files_from_kwargs(msg)
        assert result is not None
        assert result[0]["size"] == 2048

    def test_missing_size_defaults_to_zero(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = _human("hi", files=[{"filename": "f.txt", "path": "/mnt/user-data/uploads/f.txt"}])
        result = mw._files_from_kwargs(msg)
        assert result is not None
        assert result[0]["size"] == 0

    def test_preserves_extracted_images_metadata(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "report.docx").write_bytes(b"docx")
        (uploads_dir / "report__image1.png").write_bytes(b"png")
        msg = _human(
            "hi",
            files=[
                {
                    "filename": "report.docx",
                    "size": 12,
                    "path": "/mnt/user-data/uploads/report.docx",
                    "extracted_images": [
                        {
                            "filename": "report__image1.png",
                            "size": 3,
                            "path": "/mnt/user-data/uploads/report__image1.png",
                            "virtual_path": "/mnt/user-data/uploads/report__image1.png",
                            "artifact_url": "/api/threads/thread-abc123/artifacts/mnt/user-data/uploads/report__image1.png",
                        }
                    ],
                }
            ],
        )

        result = mw._files_from_kwargs(msg, uploads_dir)

        assert result is not None
        assert result[0]["extracted_images"][0]["filename"] == "report__image1.png"


# ---------------------------------------------------------------------------
# _create_files_message
# ---------------------------------------------------------------------------


class TestCreateFilesMessage:
    def _new_file(self, filename="notes.txt", size=1024):
        return {"filename": filename, "size": size, "path": f"/mnt/user-data/uploads/{filename}"}

    def test_new_files_section_always_present(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = mw._create_files_message([self._new_file()], [])
        assert "<uploaded_files>" in msg
        assert "</uploaded_files>" in msg
        assert "uploaded in this message" in msg
        assert "notes.txt" in msg
        assert "/mnt/user-data/uploads/notes.txt" in msg

    def test_historical_section_present_only_when_non_empty(self, tmp_path):
        mw = _middleware(tmp_path)

        msg_no_hist = mw._create_files_message([self._new_file()], [])
        assert "previous messages" not in msg_no_hist

        hist = self._new_file("old.txt")
        msg_with_hist = mw._create_files_message([self._new_file()], [hist])
        assert "previous messages" in msg_with_hist
        assert "old.txt" in msg_with_hist

    def test_size_formatting_kb(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = mw._create_files_message([self._new_file(size=2048)], [])
        assert "2.0 KB" in msg

    def test_size_formatting_mb(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = mw._create_files_message([self._new_file(size=2 * 1024 * 1024)], [])
        assert "2.0 MB" in msg

    def test_read_file_instruction_included(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = mw._create_files_message([self._new_file()], [])
        assert "read_file" in msg

    def test_extracted_images_include_view_image_guidance(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = mw._create_files_message(
            [
                {
                    "filename": "report.docx",
                    "size": 1024,
                    "path": "/mnt/user-data/uploads/report.docx",
                    "extracted_images": [
                        {
                            "filename": "report__image1.png",
                            "path": "/mnt/user-data/uploads/report__image1.png",
                        }
                    ],
                }
            ],
            [],
        )

        assert "report__image1.png" in msg
        assert "view_image" in msg

    def test_empty_new_files_produces_empty_marker(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = mw._create_files_message([], [])
        assert "(empty)" in msg
        assert "<uploaded_files>" in msg
        assert "</uploaded_files>" in msg


# ---------------------------------------------------------------------------
# before_agent
# ---------------------------------------------------------------------------


class TestBeforeAgent:
    def _state(self, *messages):
        return {"messages": list(messages)}

    def test_returns_none_when_messages_empty(self, tmp_path):
        mw = _middleware(tmp_path)
        assert mw.before_agent({"messages": []}, _runtime()) is None

    def test_returns_none_when_last_message_is_not_human(self, tmp_path):
        mw = _middleware(tmp_path)
        state = self._state(HumanMessage(content="q"), AIMessage(content="a"))
        assert mw.before_agent(state, _runtime()) is None

    def test_returns_none_when_no_files_in_kwargs(self, tmp_path):
        mw = _middleware(tmp_path)
        state = self._state(_human("plain message"))
        assert mw.before_agent(state, _runtime()) is None

    def test_returns_none_when_all_files_missing_from_disk(self, tmp_path):
        mw = _middleware(tmp_path)
        _uploads_dir(tmp_path)  # directory exists but is empty
        msg = _human("hi", files=[{"filename": "ghost.txt", "size": 10, "path": "/mnt/user-data/uploads/ghost.txt"}])
        state = self._state(msg)
        assert mw.before_agent(state, _runtime()) is None

    def test_injects_uploaded_files_tag_into_string_content(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "report.pdf").write_bytes(b"pdf")

        msg = _human("please analyse", files=[{"filename": "report.pdf", "size": 3, "path": "/mnt/user-data/uploads/report.pdf"}])
        state = self._state(msg)
        result = mw.before_agent(state, _runtime())

        assert result is not None
        updated_msg = result["messages"][-1]
        assert isinstance(updated_msg.content, str)
        assert "<uploaded_files>" in updated_msg.content
        assert "report.pdf" in updated_msg.content
        assert "please analyse" in updated_msg.content

    def test_injects_uploaded_files_tag_into_list_content(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "data.csv").write_bytes(b"a,b")

        msg = _human(
            [{"type": "text", "text": "analyse this"}],
            files=[{"filename": "data.csv", "size": 3, "path": "/mnt/user-data/uploads/data.csv"}],
        )
        state = self._state(msg)
        result = mw.before_agent(state, _runtime())

        assert result is not None
        updated_msg = result["messages"][-1]
        assert "<uploaded_files>" in updated_msg.content
        assert "analyse this" in updated_msg.content

    def test_preserves_additional_kwargs_on_updated_message(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "img.png").write_bytes(b"png")

        files_meta = [{"filename": "img.png", "size": 3, "path": "/mnt/user-data/uploads/img.png", "status": "uploaded"}]
        msg = _human("check image", files=files_meta, element="task")
        state = self._state(msg)
        result = mw.before_agent(state, _runtime())

        assert result is not None
        updated_kwargs = result["messages"][-1].additional_kwargs
        assert updated_kwargs.get("files") == files_meta
        assert updated_kwargs.get("element") == "task"

    def test_uploaded_files_returned_in_state_update(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "notes.txt").write_bytes(b"hello")

        msg = _human("review", files=[{"filename": "notes.txt", "size": 5, "path": "/mnt/user-data/uploads/notes.txt"}])
        result = mw.before_agent(self._state(msg), _runtime())

        assert result is not None
        assert result["uploaded_files"] == [
            {
                "filename": "notes.txt",
                "size": 5,
                "path": "/mnt/user-data/uploads/notes.txt",
                "extension": ".txt",
                "outline": [],
                "outline_preview": [],
            }
        ]

    def test_uploaded_files_include_extracted_images_in_state_update(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "report.docx").write_bytes(b"docx")
        (uploads_dir / "report__image1.png").write_bytes(b"png")

        msg = _human(
            "review",
            files=[
                {
                    "filename": "report.docx",
                    "size": 5,
                    "path": "/mnt/user-data/uploads/report.docx",
                    "extracted_images": [
                        {
                            "filename": "report__image1.png",
                            "size": 3,
                            "path": "/mnt/user-data/uploads/report__image1.png",
                            "virtual_path": "/mnt/user-data/uploads/report__image1.png",
                            "artifact_url": "/api/threads/thread-abc123/artifacts/mnt/user-data/uploads/report__image1.png",
                        }
                    ],
                }
            ],
        )
        result = mw.before_agent(self._state(msg), _runtime())

        assert result is not None
        assert result["uploaded_files"][0]["extracted_images"][0]["filename"] == "report__image1.png"

    def test_historical_files_from_uploads_dir_excluding_new(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "old.txt").write_bytes(b"old")
        (uploads_dir / "new.txt").write_bytes(b"new")

        msg = _human("go", files=[{"filename": "new.txt", "size": 3, "path": "/mnt/user-data/uploads/new.txt"}])
        result = mw.before_agent(self._state(msg), _runtime())

        assert result is not None
        content = result["messages"][-1].content
        assert "uploaded in this message" in content
        assert "new.txt" in content
        assert "previous messages" in content
        assert "old.txt" in content

    def test_abefore_agent_offloads_historical_file_loading(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "old.txt").write_bytes(b"old")
        (uploads_dir / "new.txt").write_bytes(b"new")

        msg = _human("go", files=[{"filename": "new.txt", "size": 3, "path": "/mnt/user-data/uploads/new.txt"}])
        state = self._state(msg)
        expected_historical_files = [
            {
                "filename": "old.txt",
                "size": 3,
                "path": "/mnt/user-data/uploads/old.txt",
                "extension": ".txt",
            }
        ]

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        with (
            patch.object(mw, "_load_historical_files", return_value=expected_historical_files) as load_historical_files,
            patch(
                "deerflow.agents.middlewares.uploads_middleware.asyncio.to_thread",
                new=AsyncMock(side_effect=fake_to_thread),
            ) as to_thread,
        ):
            result = asyncio.run(mw.abefore_agent(state, _runtime()))

        assert result is not None
        to_thread.assert_awaited_once()
        load_historical_files.assert_called_once_with(
            uploads_dir,
            THREAD_ID,
            {"new.txt"},
        )
        content = result["messages"][-1].content
        assert "previous messages" in content
        assert "old.txt" in content

    def test_no_historical_section_when_upload_dir_is_empty(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "only.txt").write_bytes(b"x")

        msg = _human("go", files=[{"filename": "only.txt", "size": 1, "path": "/mnt/user-data/uploads/only.txt"}])
        result = mw.before_agent(self._state(msg), _runtime())

        content = result["messages"][-1].content
        assert "previous messages" not in content

    def test_no_historical_scan_when_thread_id_is_none(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = _human("go", files=[{"filename": "f.txt", "size": 1, "path": "/mnt/user-data/uploads/f.txt"}])
        # thread_id=None → _files_from_kwargs skips existence check, no dir scan
        result = mw.before_agent(self._state(msg), _runtime(thread_id=None))
        # With no existence check, the file passes through and injection happens
        assert result is not None
        content = result["messages"][-1].content
        assert "previous messages" not in content

    def test_message_id_preserved_on_updated_message(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "f.txt").write_bytes(b"x")

        msg = _human("go", files=[{"filename": "f.txt", "size": 1, "path": "/mnt/user-data/uploads/f.txt"}])
        msg.id = "original-id-42"
        result = mw.before_agent(self._state(msg), _runtime())

        assert result["messages"][-1].id == "original-id-42"

    def test_outline_injected_when_md_file_exists(self, tmp_path):
        """When a converted .md file exists alongside the upload, its outline is injected."""
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "report.pdf").write_bytes(b"%PDF fake")
        # Simulate the .md produced by the conversion pipeline
        (uploads_dir / "report.md").write_text(
            "# PART I\n\n## ITEM 1. BUSINESS\n\nBody text.\n\n## ITEM 2. RISK\n",
            encoding="utf-8",
        )

        msg = _human("summarise", files=[{"filename": "report.pdf", "size": 9, "path": "/mnt/user-data/uploads/report.pdf"}])
        result = mw.before_agent(self._state(msg), _runtime())

        assert result is not None
        content = result["messages"][-1].content
        assert "Document outline" in content
        assert "PART I" in content
        assert "ITEM 1. BUSINESS" in content
        assert "ITEM 2. RISK" in content
        assert "read_file" in content

    def test_no_outline_when_no_md_file(self, tmp_path):
        """Files without a sibling .md have no outline section."""
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "data.xlsx").write_bytes(b"fake-xlsx")

        msg = _human("analyse", files=[{"filename": "data.xlsx", "size": 9, "path": "/mnt/user-data/uploads/data.xlsx"}])
        result = mw.before_agent(self._state(msg), _runtime())

        assert result is not None
        content = result["messages"][-1].content
        assert "Document outline" not in content

    def test_outline_truncation_hint_shown(self, tmp_path):
        """When outline is truncated, a hint line is appended after the last visible entry."""
        from deerflow.utils.file_conversion import MAX_OUTLINE_ENTRIES

        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "big.pdf").write_bytes(b"%PDF fake")
        # Write MAX_OUTLINE_ENTRIES + 5 headings so truncation is triggered
        headings = "\n".join(f"# Heading {i}" for i in range(MAX_OUTLINE_ENTRIES + 5))
        (uploads_dir / "big.md").write_text(headings, encoding="utf-8")

        msg = _human("read", files=[{"filename": "big.pdf", "size": 9, "path": "/mnt/user-data/uploads/big.pdf"}])
        result = mw.before_agent(self._state(msg), _runtime())

        assert result is not None
        content = result["messages"][-1].content
        assert f"showing first {MAX_OUTLINE_ENTRIES} headings" in content
        assert "use `read_file` to explore further" in content

    def test_no_truncation_hint_for_short_outline(self, tmp_path):
        """Short outlines (under the cap) must not show a truncation hint."""
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "short.pdf").write_bytes(b"%PDF fake")
        (uploads_dir / "short.md").write_text("# Intro\n\n# Conclusion\n", encoding="utf-8")

        msg = _human("read", files=[{"filename": "short.pdf", "size": 9, "path": "/mnt/user-data/uploads/short.pdf"}])
        result = mw.before_agent(self._state(msg), _runtime())

        assert result is not None
        content = result["messages"][-1].content
        assert "showing first" not in content

    def test_historical_file_outline_injected(self, tmp_path):
        """Outline is also shown for historical (previously uploaded) files."""
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        # Historical file with .md
        (uploads_dir / "old_report.pdf").write_bytes(b"%PDF old")
        (uploads_dir / "old_report.md").write_text(
            "# Chapter 1\n\n# Chapter 2\n",
            encoding="utf-8",
        )
        # New file without .md
        (uploads_dir / "new.txt").write_bytes(b"new")

        msg = _human("go", files=[{"filename": "new.txt", "size": 3, "path": "/mnt/user-data/uploads/new.txt"}])
        result = mw.before_agent(self._state(msg), _runtime())

        assert result is not None
        content = result["messages"][-1].content
        assert "Chapter 1" in content
        assert "Chapter 2" in content

    def test_historical_docx_groups_sidecar_images_under_source_file(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        source = uploads_dir / "report.docx"
        source.write_bytes(b"docx")
        (uploads_dir / "report.md").write_text("converted", encoding="utf-8")
        image = uploads_dir / "report__image1.png"
        image.write_bytes(b"png")
        write_docx_sidecar_manifest(source, [image])

        result = mw.before_agent(self._state(_human("analyse historical uploads")), _runtime())

        assert result is not None
        content = result["messages"][-1].content
        assert "report.docx" in content
        assert "report__image1.png" in content
        assert "view_image" in content
        assert "- report__image1.png" not in content

    def test_historical_docx_includes_persisted_image_descriptions(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        source = uploads_dir / "report.docx"
        source.write_bytes(b"docx")
        (uploads_dir / "report.md").write_text("converted", encoding="utf-8")
        image = uploads_dir / "report__image1.png"
        image.write_bytes(b"png")
        write_docx_sidecar_manifest(source, [image])

        result = mw.before_agent(
            {
                "messages": [_human("analyse historical uploads")],
                "uploaded_image_descriptions": {
                    "report.docx": {
                        "status": "parsed",
                        "document": "report.docx",
                        "markdown_path": "/mnt/user-data/uploads/report.md",
                        "images": [
                            {
                                "filename": "report__image1.png",
                                "path": "/mnt/user-data/uploads/report__image1.png",
                                "description": "A workflow diagram with arrows between processing steps.",
                            }
                        ],
                    }
                },
            },
            _runtime(),
        )

        assert result is not None
        content = result["messages"][-1].content
        assert "Persisted image descriptions:" in content
        assert "A workflow diagram with arrows between processing steps." in content
        assert "report__image1.png" not in content
        assert "view_image" not in content

    def test_historical_docx_failed_descriptions_keep_paths_and_view_image(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        source = uploads_dir / "report.docx"
        source.write_bytes(b"docx")
        image = uploads_dir / "report__image1.png"
        image.write_bytes(b"png")
        write_docx_sidecar_manifest(source, [image])

        result = mw.before_agent(
            {
                "messages": [_human("analyse historical uploads")],
                "uploaded_image_descriptions": {
                    "report.docx": {
                        "status": "failed",
                        "document": "report.docx",
                        "images": [
                            {
                                "filename": "report__image1.png",
                                "path": "/mnt/user-data/uploads/report__image1.png",
                                "description": "Image descriptions unavailable. Use view_image on the extracted image paths if visual details matter.",
                            }
                        ],
                    }
                },
            },
            _runtime(),
        )

        assert result is not None
        content = result["messages"][-1].content
        assert "Image descriptions unavailable" in content
        assert "report__image1.png" in content
        assert "view_image" in content

    def test_reupload_clears_persisted_descriptions_for_same_docx(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "report.docx").write_bytes(b"docx")

        msg = _human(
            "review updated upload",
            files=[
                {
                    "filename": "report.docx",
                    "size": 5,
                    "path": "/mnt/user-data/uploads/report.docx",
                }
            ],
        )
        result = mw.before_agent(
            {
                "messages": [msg],
                "uploaded_image_descriptions": {
                    "report.docx": {
                        "status": "parsed",
                        "document": "report.docx",
                        "images": [{"filename": "report__image1.png", "description": "old"}],
                    }
                },
            },
            _runtime(),
        )

        assert result is not None
        assert result["uploaded_image_descriptions"] == {}

    def test_fallback_preview_shown_when_outline_empty(self, tmp_path):
        """When .md exists but has no headings, first lines are shown as a preview."""
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "report.pdf").write_bytes(b"%PDF fake")
        # .md with no # headings — plain prose only
        (uploads_dir / "report.md").write_text(
            "Annual Financial Report 2024\n\nThis document summarises key findings.\n\nRevenue grew by 12%.\n",
            encoding="utf-8",
        )

        msg = _human("analyse", files=[{"filename": "report.pdf", "size": 9, "path": "/mnt/user-data/uploads/report.pdf"}])
        result = mw.before_agent(self._state(msg), _runtime())

        assert result is not None
        content = result["messages"][-1].content
        # Outline section must NOT appear
        assert "Document outline" not in content
        # Preview lines must appear
        assert "Annual Financial Report 2024" in content
        assert "No structural headings detected" in content
        # grep hint must appear
        assert "grep" in content

    def test_fallback_grep_hint_shown_when_no_md_file(self, tmp_path):
        """Files with no sibling .md still get the grep hint (outline is empty)."""
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "data.csv").write_bytes(b"a,b,c\n1,2,3\n")

        msg = _human("analyse", files=[{"filename": "data.csv", "size": 12, "path": "/mnt/user-data/uploads/data.csv"}])
        result = mw.before_agent(self._state(msg), _runtime())

        assert result is not None
        content = result["messages"][-1].content
        assert "Document outline" not in content
        assert "grep" in content


# ---------------------------------------------------------------------------
# wrap_model_call
# ---------------------------------------------------------------------------


class TestWrapModelCall:
    def _state(self, *messages, uploaded_files=None, uploaded_image_descriptions=None):
        state = {"messages": list(messages)}
        if uploaded_files is not None:
            state["uploaded_files"] = uploaded_files
        if uploaded_image_descriptions is not None:
            state["uploaded_image_descriptions"] = uploaded_image_descriptions
        return state

    def _request(self, state):
        request = MagicMock()
        request.state = state
        request.runtime = _runtime()
        request.messages = list(state["messages"])
        request.override.return_value = MagicMock()
        return request

    def test_injects_multimodal_context_for_new_docx_images_without_mutating_state_messages(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "report.docx").write_bytes(b"docx")
        (uploads_dir / "report.md").write_text("converted", encoding="utf-8")
        (uploads_dir / "report__image1.png").write_bytes(b"png")

        state = self._state(
            _human("review the document"),
            uploaded_files=[
                {
                    "filename": "report.docx",
                    "size": 5,
                    "path": "/mnt/user-data/uploads/report.docx",
                    "markdown_file": "report.md",
                    "markdown_path": "/mnt/user-data/uploads/report.md",
                    "extracted_images": [
                        {
                            "filename": "report__image1.png",
                            "size": 3,
                            "path": "/mnt/user-data/uploads/report__image1.png",
                        }
                    ],
                }
            ],
        )
        request = self._request(state)
        handler = MagicMock(return_value="response")

        with patch.object(mw, "_runtime_supports_vision", return_value=True):
            result = mw.wrap_model_call(request, handler)

        assert result == "response"
        request.override.assert_called_once()
        passed_messages = request.override.call_args.kwargs["messages"]
        content = passed_messages[-1].content
        assert isinstance(content, list)
        assert content[0]["type"] == "text"
        assert "report.docx" in content[0]["text"]
        assert "report.md" in content[0]["text"]
        assert "Summarize the relevant visual information" in content[0]["text"]
        assert "<document_image_descriptions>" in content[0]["text"]
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert request.messages == state["messages"]
        handler.assert_called_once_with(request.override.return_value)

    def test_does_not_inject_images_once_descriptions_exist_for_docx(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "report__image1.png").write_bytes(b"png")

        state = self._state(
            _human("review the document"),
            uploaded_files=[
                {
                    "filename": "report.docx",
                    "size": 5,
                    "path": "/mnt/user-data/uploads/report.docx",
                    "extracted_images": [{"filename": "report__image1.png", "size": 3, "path": "/mnt/user-data/uploads/report__image1.png"}],
                }
            ],
            uploaded_image_descriptions={
                "report.docx": {
                    "status": "parsed",
                    "document": "report.docx",
                    "images": [{"filename": "report__image1.png", "description": "A user interface screenshot."}],
                }
            },
        )
        request = self._request(state)
        handler = MagicMock(return_value="response")

        with patch.object(mw, "_runtime_supports_vision", return_value=True):
            result = mw.wrap_model_call(request, handler)

        assert result == "response"
        request.override.assert_not_called()
        handler.assert_called_once_with(request)

    def test_does_not_inject_images_once_failure_placeholder_exists(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "report__image1.png").write_bytes(b"png")

        state = self._state(
            _human("review the document"),
            uploaded_files=[
                {
                    "filename": "report.docx",
                    "size": 5,
                    "path": "/mnt/user-data/uploads/report.docx",
                    "extracted_images": [{"filename": "report__image1.png", "size": 3, "path": "/mnt/user-data/uploads/report__image1.png"}],
                }
            ],
            uploaded_image_descriptions={
                "report.docx": {
                    "status": "failed",
                    "document": "report.docx",
                    "images": [
                        {
                            "filename": "report__image1.png",
                            "path": "/mnt/user-data/uploads/report__image1.png",
                            "description": "Image descriptions unavailable. Use view_image on the extracted image paths if visual details matter.",
                        }
                    ],
                }
            },
        )
        request = self._request(state)
        handler = MagicMock(return_value="response")

        with patch.object(mw, "_runtime_supports_vision", return_value=True):
            result = mw.wrap_model_call(request, handler)

        assert result == "response"
        request.override.assert_not_called()
        handler.assert_called_once_with(request)


class TestAwrapModelCall:
    @pytest.mark.anyio
    async def test_async_wrap_model_call_injects_visual_message(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "report.docx").write_bytes(b"docx")
        (uploads_dir / "report__image1.png").write_bytes(b"png")

        state = {
            "messages": [_human("review the document")],
            "uploaded_files": [
                {
                    "filename": "report.docx",
                    "size": 5,
                    "path": "/mnt/user-data/uploads/report.docx",
                    "extracted_images": [{"filename": "report__image1.png", "size": 3, "path": "/mnt/user-data/uploads/report__image1.png"}],
                }
            ],
        }
        request = MagicMock()
        request.state = state
        request.runtime = _runtime()
        request.messages = list(state["messages"])
        request.override.return_value = MagicMock()
        handler = AsyncMock(return_value="response")

        with patch.object(mw, "_runtime_supports_vision", return_value=True):
            result = await mw.awrap_model_call(request, handler)

        assert result == "response"
        request.override.assert_called_once()
        handler.assert_called_once_with(request.override.return_value)

    @pytest.mark.anyio
    async def test_async_wrap_model_call_offloads_visual_message_build(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "report.docx").write_bytes(b"docx")
        (uploads_dir / "report__image1.png").write_bytes(b"png")

        state = {
            "messages": [_human("review the document")],
            "uploaded_files": [
                {
                    "filename": "report.docx",
                    "size": 5,
                    "path": "/mnt/user-data/uploads/report.docx",
                    "extracted_images": [{"filename": "report__image1.png", "size": 3, "path": "/mnt/user-data/uploads/report__image1.png"}],
                }
            ],
        }
        request = MagicMock()
        request.state = state
        request.runtime = _runtime()
        request.messages = list(state["messages"])
        request.override.return_value = MagicMock()
        handler = AsyncMock(return_value="response")

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch.object(mw, "_runtime_supports_vision", return_value=True),
            patch(
                "deerflow.agents.middlewares.uploads_middleware.asyncio.to_thread",
                new=AsyncMock(side_effect=fake_to_thread),
            ) as to_thread,
        ):
            result = await mw.awrap_model_call(request, handler)

        assert result == "response"
        to_thread.assert_awaited_once()
        request.override.assert_called_once()
        handler.assert_called_once_with(request.override.return_value)


# ---------------------------------------------------------------------------
# after_model
# ---------------------------------------------------------------------------


class TestAfterModel:
    def _state(self, *messages, uploaded_files=None, uploaded_image_descriptions=None):
        state = {"messages": list(messages)}
        if uploaded_files is not None:
            state["uploaded_files"] = uploaded_files
        if uploaded_image_descriptions is not None:
            state["uploaded_image_descriptions"] = uploaded_image_descriptions
        return state

    def test_persists_valid_document_image_description_payload_and_strips_it(self, tmp_path):
        mw = _middleware(tmp_path)
        ai = AIMessage(
            content=[
                {
                    "type": "output_text",
                    "text": (
                        "Final answer.\n\n"
                        "<document_image_descriptions>\n"
                        '{"documents":[{"document":"report.docx","markdown_path":"/mnt/user-data/uploads/report.md","images":[{"filename":"report__image1.png","description":"A workflow diagram with three connected stages."}]}]}\n'
                        "</document_image_descriptions>"
                    ),
                }
            ]
        )
        state = self._state(
            _human("review"),
            ai,
            uploaded_files=[
                {
                    "filename": "report.docx",
                    "markdown_path": "/mnt/user-data/uploads/report.md",
                    "extracted_images": [
                        {
                            "filename": "report__image1.png",
                            "path": "/mnt/user-data/uploads/report__image1.png",
                        }
                    ],
                }
            ],
        )

        with patch.object(mw, "_runtime_supports_vision", return_value=True):
            result = mw.after_model(state, _runtime())

        assert result is not None
        assert result["uploaded_image_descriptions"]["report.docx"]["status"] == "parsed"
        assert result["uploaded_image_descriptions"]["report.docx"]["images"][0]["description"] == ("A workflow diagram with three connected stages.")
        assert result["messages"][0].content == [{"type": "output_text", "text": "Final answer."}]

    def test_malformed_payload_persists_failed_placeholder(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "report.docx").write_bytes(b"docx")
        (uploads_dir / "report__image1.png").write_bytes(b"png")
        ai = AIMessage(content=('Final answer.\n<document_image_descriptions>\n{"documents":[{"document":"report.docx","images":[{"filename":"report__image1.png"}]}]}\n</document_image_descriptions>'))
        state = self._state(
            _human("review"),
            ai,
            uploaded_files=[
                {
                    "filename": "report.docx",
                    "extracted_images": [{"filename": "report__image1.png"}],
                }
            ],
        )

        with patch.object(mw, "_runtime_supports_vision", return_value=True):
            result = mw.after_model(state, _runtime())

        assert result is not None
        assert result["uploaded_image_descriptions"]["report.docx"]["status"] == "failed"
        assert "Image descriptions unavailable" in result["uploaded_image_descriptions"]["report.docx"]["images"][0]["description"]
        assert result["messages"][0].content == "Final answer."

    def test_missing_payload_after_visual_attempt_persists_failed_placeholder(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "report.docx").write_bytes(b"docx")
        (uploads_dir / "report__image1.png").write_bytes(b"png")
        ai = AIMessage(content="Final answer without payload.")
        state = self._state(
            _human("review"),
            ai,
            uploaded_files=[
                {
                    "filename": "report.docx",
                    "markdown_path": "/mnt/user-data/uploads/report.md",
                    "extracted_images": [
                        {
                            "filename": "report__image1.png",
                            "path": "/mnt/user-data/uploads/report__image1.png",
                        }
                    ],
                }
            ],
        )

        with patch.object(mw, "_runtime_supports_vision", return_value=True):
            result = mw.after_model(state, _runtime())

        assert result is not None
        assert result["uploaded_image_descriptions"]["report.docx"]["status"] == "failed"
        assert result["uploaded_image_descriptions"]["report.docx"]["images"][0]["path"] == "/mnt/user-data/uploads/report__image1.png"
        assert "messages" not in result

    def test_missing_payload_persists_failed_placeholder_without_rebuilding_visual_message(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "report.docx").write_bytes(b"docx")
        (uploads_dir / "report__image1.png").write_bytes(b"png")
        ai = AIMessage(content="Final answer without payload.")
        state = self._state(
            _human("review"),
            ai,
            uploaded_files=[
                {
                    "filename": "report.docx",
                    "markdown_path": "/mnt/user-data/uploads/report.md",
                    "extracted_images": [
                        {
                            "filename": "report__image1.png",
                            "path": "/mnt/user-data/uploads/report__image1.png",
                        }
                    ],
                }
            ],
        )

        with (
            patch.object(mw, "_runtime_supports_vision", return_value=True),
            patch.object(
                mw,
                "_create_uploaded_visual_context_message",
                side_effect=AssertionError("after_model should not rebuild visual context"),
            ),
        ):
            result = mw.after_model(state, _runtime())

        assert result is not None
        assert result["uploaded_image_descriptions"]["report.docx"]["status"] == "failed"

    def test_missing_payload_without_visual_attempt_does_not_persist_failed_placeholder(self, tmp_path):
        mw = _middleware(tmp_path)
        ai = AIMessage(content="Final answer without payload.")
        state = self._state(
            _human("review"),
            ai,
            uploaded_files=[
                {
                    "filename": "report.docx",
                    "markdown_path": "/mnt/user-data/uploads/report.md",
                    "extracted_images": [
                        {
                            "filename": "report__image1.png",
                            "path": "/mnt/user-data/uploads/report__image1.png",
                        }
                    ],
                }
            ],
        )

        with patch.object(mw, "_runtime_supports_vision", return_value=True):
            result = mw.after_model(state, _runtime(thread_id=None))

        assert result is None
