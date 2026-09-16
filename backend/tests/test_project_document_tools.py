"""Tests for the project shelf tools (Phase-2 spec §7.3).

``list_project_documents`` / ``read_project_document`` take the pinned
project identity from ``runtime.context[PROJECT_CONTEXT_KEY]`` and the user
from ``resolve_runtime_user_id``, then read **live** shelf rows: slice
boundaries, limit clamps, binary decline, conversion honored/declined by
``uploads.auto_convert_documents``, stale-entry errors after trash, and
fail-closed behavior without a pinned context or session factory.
"""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

from deerflow.projects.documents import add_staged_document, converted_markdown_path, ensure_converted_markdown, original_file_path, stage_document_bytes
from deerflow.projects.tools import _list_project_documents_impl, _read_project_document_impl
from deerflow.projects.trash import make_purge_file_remover
from deerflow.runtime.context_keys import PROJECT_CONTEXT_KEY

pytestmark = pytest.mark.anyio

_USER = "u1"


@pytest.fixture
async def env(tmp_path, monkeypatch):
    """Real SQLite repos + a real per-user projects layout on disk."""
    import deerflow.config.paths as paths_mod
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths_mod, "_paths", None)
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    projects = ProjectRepository(sf)
    docs = ProjectDocumentRepository(sf)
    project = await projects.create(name="P", user_id=_USER)
    yield SimpleNamespace(paths=paths_mod.get_paths(), projects=projects, docs=docs, project=project)
    await close_engine()


def _runtime(*, project_id: str | None = "p-1", user_id: str = _USER) -> SimpleNamespace:
    context: dict = {"user_id": user_id}
    if project_id is not None:
        context[PROJECT_CONTEXT_KEY] = {"project_id": project_id, "name": "P", "instructions": ""}
    return SimpleNamespace(context=context)


async def _shelve(env, *, name: str, data: bytes, doc_sha: str | None = None, project_id: str | None = None) -> dict:
    staged = await stage_document_bytes(env.paths, user_id=_USER, project_id=project_id or env.project["id"], chunks=[data], max_bytes=1 << 20)
    result = await add_staged_document(env.docs, env.paths, user_id=_USER, project_id=project_id or env.project["id"], name=name, staged=staged)
    assert result is not None
    row, created = result
    assert created
    return row


class TestListProjectDocuments:
    async def test_pages_live_rows_in_index_order_with_total_and_next_offset(self, env):
        for i in range(5):
            await _shelve(env, name=f"f{i}.txt", data=f"content-{i}".encode())
        runtime = _runtime(project_id=env.project["id"])

        first = json.loads(await _list_project_documents_impl(runtime, offset=0, limit=2))
        assert first["total"] == 5
        assert first["next_offset"] == 2
        assert [d["id"] for d in first["documents"]] != []
        second = json.loads(await _list_project_documents_impl(runtime, offset=first["next_offset"], limit=2))
        assert second["next_offset"] == 4
        third = json.loads(await _list_project_documents_impl(runtime, offset=second["next_offset"], limit=2))
        assert third["next_offset"] is None
        walked = [d["id"] for d in first["documents"] + second["documents"] + third["documents"]]
        live = await env.docs.list_active(env.project["id"], limit=10, offset=0, user_id=_USER)
        assert walked == [r["id"] for r in live]

    async def test_limit_is_clamped_at_200(self, env):
        await _shelve(env, name="a.txt", data=b"a")
        result = json.loads(await _list_project_documents_impl(_runtime(project_id=env.project["id"]), offset=0, limit=5000))
        assert len(result["documents"]) == 1  # clamp accepted, no error

    async def test_trashed_rows_disappear_live(self, env):
        row = await _shelve(env, name="a.txt", data=b"a")
        runtime = _runtime(project_id=env.project["id"])
        assert json.loads(await _list_project_documents_impl(runtime, offset=0, limit=10))["total"] == 1
        assert await env.docs.trash(row["id"], user_id=_USER)
        assert json.loads(await _list_project_documents_impl(runtime, offset=0, limit=10))["total"] == 0

    async def test_fail_closed_without_pinned_context(self, env):
        result = json.loads(await _list_project_documents_impl(_runtime(project_id=None), offset=0, limit=10))
        assert "error" in result

    async def test_fail_closed_without_session_factory(self, env, monkeypatch):
        monkeypatch.setattr("deerflow.persistence.get_session_factory", lambda: None)
        result = json.loads(await _list_project_documents_impl(_runtime(project_id=env.project["id"]), offset=0, limit=10))
        assert "error" in result


class TestReadProjectDocument:
    async def test_reads_a_text_document(self, env):
        row = await _shelve(env, name="notes.txt", data=b"hello shelf")
        result = json.loads(await _read_project_document_impl(_runtime(project_id=env.project["id"]), document_id=row["id"], offset=0, limit=100))
        assert result == {
            "name": "notes.txt",
            "total_chars": 11,
            "offset": 0,
            "returned_chars": 11,
            "truncated": False,
            "content": "hello shelf",
        }

    async def test_slice_boundaries_at_and_over_total_chars(self, env):
        row = await _shelve(env, name="notes.txt", data=b"0123456789")
        runtime = _runtime(project_id=env.project["id"])
        page = json.loads(await _read_project_document_impl(runtime, document_id=row["id"], offset=0, limit=4))
        assert (page["content"], page["truncated"], page["returned_chars"]) == ("0123", True, 4)
        at_end = json.loads(await _read_project_document_impl(runtime, document_id=row["id"], offset=10, limit=4))
        assert (at_end["content"], at_end["returned_chars"], at_end["truncated"]) == ("", 0, False)
        past_end = json.loads(await _read_project_document_impl(runtime, document_id=row["id"], offset=99, limit=4))
        assert (past_end["content"], past_end["returned_chars"], past_end["truncated"]) == ("", 0, False)

    async def test_limit_is_clamped_at_20000(self, env):
        row = await _shelve(env, name="big.txt", data=b"x" * 30000)
        result = json.loads(await _read_project_document_impl(_runtime(project_id=env.project["id"]), document_id=row["id"], offset=0, limit=99999))
        assert result["returned_chars"] == 20000
        assert result["truncated"] is True

    async def test_binary_document_is_declined_naming_attach_to_thread(self, env):
        row = await _shelve(env, name="photo.bin", data=b"\x00\x01\x02binary")
        result = json.loads(await _read_project_document_impl(_runtime(project_id=env.project["id"]), document_id=row["id"], offset=0, limit=100))
        assert "error" in result
        assert "attach" in result["error"]

    async def test_convertible_document_converts_on_first_read_when_enabled(self, env, monkeypatch):
        from deerflow.projects import documents as documents_mod

        async def fake_convert(file_path, output_path=None):
            output_path.write_text("# converted markdown", encoding="utf-8")
            return output_path

        monkeypatch.setattr(documents_mod, "convert_file_to_markdown", fake_convert)
        monkeypatch.setattr("deerflow.projects.tools._resolve_auto_convert", lambda: True)
        row = await _shelve(env, name="report.docx", data=b"\x00docx-bytes")

        runtime = _runtime(project_id=env.project["id"])
        first = json.loads(await _read_project_document_impl(runtime, document_id=row["id"], offset=0, limit=100))
        assert first["content"] == "# converted markdown"
        # Served from the document-owned derived/converted.md companion.
        derived = documents_mod.converted_markdown_path(env.paths, user_id=_USER, row=row)
        assert derived.is_file()
        # Second read uses the cache without converting again.
        second = json.loads(await _read_project_document_impl(runtime, document_id=row["id"], offset=0, limit=100))
        assert second["content"] == "# converted markdown"

    async def test_convertible_document_is_declined_when_conversion_is_off(self, env, monkeypatch):
        monkeypatch.setattr("deerflow.projects.tools._resolve_auto_convert", lambda: False)
        row = await _shelve(env, name="report.docx", data=b"\x00docx-bytes")
        result = json.loads(await _read_project_document_impl(_runtime(project_id=env.project["id"]), document_id=row["id"], offset=0, limit=100))
        assert "error" in result
        assert "conversion" in result["error"]
        assert "attach" in result["error"]

    async def test_trashed_after_index_reports_no_longer_on_the_shelf(self, env):
        row = await _shelve(env, name="gone.txt", data=b"bye")
        assert await env.docs.trash(row["id"], user_id=_USER)
        result = json.loads(await _read_project_document_impl(_runtime(project_id=env.project["id"]), document_id=row["id"], offset=0, limit=100))
        assert "error" in result
        assert "no longer on the shelf" in result["error"]

    async def test_document_from_another_project_is_fail_closed(self, env):
        other = await env.projects.create(name="Other", user_id=_USER)
        row = await _shelve(env, name="theirs.txt", data=b"secret", project_id=other["id"])
        result = json.loads(await _read_project_document_impl(_runtime(project_id=env.project["id"]), document_id=row["id"], offset=0, limit=100))
        assert "error" in result
        assert "no longer on the shelf" in result["error"]

    async def test_missing_content_reports_content_missing(self, env):
        from deerflow.projects.documents import original_file_path

        row = await _shelve(env, name="lost.txt", data=b"was here")
        original_file_path(env.paths, user_id=_USER, row=row).unlink()
        result = json.loads(await _read_project_document_impl(_runtime(project_id=env.project["id"]), document_id=row["id"], offset=0, limit=100))
        assert "error" in result
        assert "content_missing" in result["error"]

    async def test_convertible_pdf_with_text_like_head_converts_instead_of_raw_serving(self, env, monkeypatch):
        """A convertible extension takes the conversion path BEFORE the
        null-byte text heuristic: an ASCII85-style PDF head samples as text
        but must never be raw-served."""
        from deerflow.projects import documents as documents_mod

        async def fake_convert(file_path, output_path=None):
            output_path.write_text("# converted markdown", encoding="utf-8")
            return output_path

        monkeypatch.setattr(documents_mod, "convert_file_to_markdown", fake_convert)
        monkeypatch.setattr("deerflow.projects.tools._resolve_auto_convert", lambda: True)
        row = await _shelve(env, name="report.pdf", data=b"%PDF-1.4\n1 0 obj<</Type/Catalog>>stream\nGBTor ASCII85 body\n")
        result = json.loads(await _read_project_document_impl(_runtime(project_id=env.project["id"]), document_id=row["id"], offset=0, limit=200))
        assert result["content"] == "# converted markdown"

    async def test_convertible_pdf_with_text_like_head_declined_when_conversion_is_off(self, env, monkeypatch):
        """With auto-convert off, a null-free-head convertible reports the
        conversion_disabled decline — never the raw PDF syntax."""
        monkeypatch.setattr("deerflow.projects.tools._resolve_auto_convert", lambda: False)
        row = await _shelve(env, name="report.pdf", data=b"%PDF-1.4\n1 0 obj<</Type/Catalog>>stream\nGBTor ASCII85 body\n")
        result = json.loads(await _read_project_document_impl(_runtime(project_id=env.project["id"]), document_id=row["id"], offset=0, limit=200))
        assert "error" in result
        assert "conversion" in result["error"]
        assert "%PDF" not in result["error"]

    async def test_fail_closed_without_pinned_context(self, env):
        result = json.loads(await _read_project_document_impl(_runtime(project_id=None), document_id="anything", offset=0, limit=100))
        assert "error" in result


class TestInsertFailureNamespacePreservation:
    """The shelf-insert failure path deletes placed bytes only when the row
    PROVABLY does not exist: a post-commit failure (e.g. the insert's
    trailing refresh) leaves a live row serving its bytes, and only a
    confirmed rollback cleans the namespace (§6.3/§10.3)."""

    async def test_refresh_failure_after_commit_keeps_row_and_bytes(self, env, monkeypatch):
        from sqlalchemy.ext.asyncio import AsyncSession

        from deerflow.persistence.projects.model import ProjectDocumentRow

        real_refresh = AsyncSession.refresh
        failed = False

        async def flaky_refresh(self, instance, *args, **kwargs):
            nonlocal failed
            if not failed and isinstance(instance, ProjectDocumentRow):
                failed = True
                raise RuntimeError("simulated post-commit refresh failure")
            return await real_refresh(self, instance, *args, **kwargs)

        monkeypatch.setattr(AsyncSession, "refresh", flaky_refresh)
        staged = await stage_document_bytes(env.paths, user_id=_USER, project_id=env.project["id"], chunks=[b"precious bytes"], max_bytes=1 << 20)
        result = await add_staged_document(env.docs, env.paths, user_id=_USER, project_id=env.project["id"], name="keep.txt", staged=staged)

        assert failed
        # The row committed: the insert is reported as success and the
        # namespace (and its bytes) survive.
        assert result is not None and result[1] is True
        row = result[0]
        assert original_file_path(env.paths, user_id=_USER, row=row).read_bytes() == b"precious bytes"

        # A re-upload of identical bytes dedup-hits the healthy row — no
        # self-perpetuating broken row, and the content reads.
        staged2 = await stage_document_bytes(env.paths, user_id=_USER, project_id=env.project["id"], chunks=[b"precious bytes"], max_bytes=1 << 20)
        result2 = await add_staged_document(env.docs, env.paths, user_id=_USER, project_id=env.project["id"], name="keep.txt", staged=staged2)
        assert result2 is not None and result2[1] is False
        assert result2[0]["id"] == row["id"]
        payload = json.loads(await _read_project_document_impl(_runtime(project_id=env.project["id"]), document_id=row["id"], offset=0, limit=100))
        assert payload["content"] == "precious bytes"

    async def test_pre_commit_failure_cleans_the_namespace(self, env, monkeypatch):
        from sqlalchemy.ext.asyncio import AsyncSession

        real_commit = AsyncSession.commit
        failed = False

        async def flaky_commit(self, **kwargs):
            nonlocal failed
            if not failed:
                failed = True
                raise RuntimeError("simulated pre-commit failure")
            return await real_commit(self, **kwargs)

        monkeypatch.setattr(AsyncSession, "commit", flaky_commit)
        staged = await stage_document_bytes(env.paths, user_id=_USER, project_id=env.project["id"], chunks=[b"never shelved"], max_bytes=1 << 20)
        with pytest.raises(RuntimeError, match="simulated pre-commit failure"):
            await add_staged_document(env.docs, env.paths, user_id=_USER, project_id=env.project["id"], name="gone.txt", staged=staged)

        # Confirmed rollback: no row, staging removed, namespace collected.
        assert failed
        assert await env.docs.count_active(env.project["id"], user_id=_USER) == 0
        assert not staged.staging_path.exists()
        documents_dir = env.paths.project_documents_dir(_USER, env.project["id"])
        assert list(documents_dir.rglob("gone.txt")) == []

    async def test_refresh_failure_with_row_trashed_before_recheck_preserves_bytes(self, env, monkeypatch):
        """Commit → concurrent trash → refresh failure: the recovery probe must
        see the TRASHED row (trash is recoverable), keep the namespace, and
        the row must restore with its content — the pre-fix code deleted the
        bytes because ``get`` filters trashed rows."""
        from sqlalchemy.ext.asyncio import AsyncSession

        from deerflow.persistence.projects.model import ProjectDocumentRow
        from deerflow.projects.trash import restore_document

        real_refresh = AsyncSession.refresh
        fired = False

        async def flaky_refresh(self, instance, *args, **kwargs):
            nonlocal fired
            if not fired and isinstance(instance, ProjectDocumentRow):
                fired = True
                # The commit already happened; a concurrent trash lands before
                # the recovery's liveness check.
                await env.docs.trash(instance.id, user_id=_USER)
                raise RuntimeError("simulated post-commit refresh failure")
            return await real_refresh(self, instance, *args, **kwargs)

        monkeypatch.setattr(AsyncSession, "refresh", flaky_refresh)
        staged = await stage_document_bytes(env.paths, user_id=_USER, project_id=env.project["id"], chunks=[b"recoverable bytes"], max_bytes=1 << 20)
        with pytest.raises(RuntimeError, match="simulated post-commit refresh failure"):
            await add_staged_document(env.docs, env.paths, user_id=_USER, project_id=env.project["id"], name="raced.txt", staged=staged)

        # The namespace survived on disk and no active row appeared.
        documents_dir = env.paths.project_documents_dir(_USER, env.project["id"])
        survivors = list(documents_dir.rglob("raced.txt"))
        assert len(survivors) == 1
        assert survivors[0].read_bytes() == b"recoverable bytes"
        assert await env.docs.count_active(env.project["id"], user_id=_USER) == 0
        # The teeth: the trashed row restores with its content intact.
        trashed = await env.docs.list_trashed(limit=10, offset=0, user_id=_USER)
        row = next(r for r in trashed if r["name"] == "raced.txt")
        outcome, _restored = await restore_document(env.docs, env.paths, user_id=_USER, document_id=row["id"], target_project_id=env.project["id"])
        assert outcome == "restored"
        payload = json.loads(await _read_project_document_impl(_runtime(project_id=env.project["id"]), document_id=row["id"], offset=0, limit=100))
        assert payload["content"] == "recoverable bytes"

    async def test_refresh_failure_with_project_deleted_before_recheck_preserves_bytes(self, env, monkeypatch):
        """Same race via a project deletion (which trashes the shelf): bytes
        survive and the row restores into another project."""
        from sqlalchemy.ext.asyncio import AsyncSession

        from deerflow.persistence.projects.model import ProjectDocumentRow
        from deerflow.projects.trash import restore_document

        real_refresh = AsyncSession.refresh
        fired = False

        async def flaky_refresh(self, instance, *args, **kwargs):
            nonlocal fired
            if not fired and isinstance(instance, ProjectDocumentRow):
                fired = True
                await env.projects.delete(instance.project_id, user_id=_USER)
                raise RuntimeError("simulated post-commit refresh failure")
            return await real_refresh(self, instance, *args, **kwargs)

        monkeypatch.setattr(AsyncSession, "refresh", flaky_refresh)
        staged = await stage_document_bytes(env.paths, user_id=_USER, project_id=env.project["id"], chunks=[b"rescued bytes"], max_bytes=1 << 20)
        with pytest.raises(RuntimeError, match="simulated post-commit refresh failure"):
            await add_staged_document(env.docs, env.paths, user_id=_USER, project_id=env.project["id"], name="orphaned.txt", staged=staged)

        documents_dir = env.paths.project_documents_dir(_USER, env.project["id"])
        survivors = list(documents_dir.rglob("orphaned.txt"))
        assert len(survivors) == 1
        assert survivors[0].read_bytes() == b"rescued bytes"
        other = await env.projects.create(name="T", user_id=_USER)
        trashed = await env.docs.list_trashed(limit=10, offset=0, user_id=_USER)
        row = next(r for r in trashed if r["name"] == "orphaned.txt")
        outcome, _restored = await restore_document(env.docs, env.paths, user_id=_USER, document_id=row["id"], target_project_id=other["id"])
        assert outcome == "restored"
        payload = json.loads(await _read_project_document_impl(_runtime(project_id=other["id"]), document_id=row["id"], offset=0, limit=100))
        assert payload["content"] == "rescued bytes"


class TestBoundedReads:
    """Paged reads are bounded: the windowed decode stops at the page's end
    and the total character count is computed once per content identity
    (immutable rows, §6.2) in a bounded process-local LRU."""

    async def test_early_window_never_reads_the_whole_file(self, env, monkeypatch):
        from deerflow.projects import documents as documents_mod

        payload = b"0123456789abcdef\n" * 300_000  # ~5.1 MiB
        staged = await stage_document_bytes(env.paths, user_id=_USER, project_id=env.project["id"], chunks=[payload], max_bytes=8 << 20)
        row, created = await add_staged_document(env.docs, env.paths, user_id=_USER, project_id=env.project["id"], name="big.txt", staged=staged)
        assert created
        runtime = _runtime(project_id=env.project["id"])

        first = json.loads(await _read_project_document_impl(runtime, document_id=row["id"], offset=0, limit=8000))
        assert first["total_chars"] == len(payload)
        assert first["content"] == payload[:8000].decode()

        # With the count cache warm, an early page must not touch anywhere
        # near the whole file.
        state = {"bytes": 0}
        real_open = open

        class CountingReader:
            def __init__(self, handle):
                self._handle = handle

            def read(self, size=-1):
                data = self._handle.read(size)
                state["bytes"] += len(data)
                return data

            def __enter__(self):
                self._handle.__enter__()
                return self

            def __exit__(self, *args):
                return self._handle.__exit__(*args)

        monkeypatch.setattr(documents_mod, "open", lambda *a, **kw: CountingReader(real_open(*a, **kw)), raising=False)
        second = json.loads(await _read_project_document_impl(runtime, document_id=row["id"], offset=0, limit=8000))
        assert second["content"] == payload[:8000].decode()
        assert second["total_chars"] == len(payload)
        assert state["bytes"] < 1 << 20

    async def test_total_chars_is_computed_once_and_cached_across_pages(self, env, monkeypatch):
        from deerflow.projects import documents as documents_mod

        calls = 0
        real_count = documents_mod._count_text_chars

        def counting(path):
            nonlocal calls
            calls += 1
            return real_count(path)

        monkeypatch.setattr(documents_mod, "_count_text_chars", counting)
        row = await _shelve(env, name="paged.txt", data=b"0123456789" * 100)
        runtime = _runtime(project_id=env.project["id"])
        page1 = json.loads(await _read_project_document_impl(runtime, document_id=row["id"], offset=0, limit=100))
        page2 = json.loads(await _read_project_document_impl(runtime, document_id=row["id"], offset=100, limit=100))
        page3 = json.loads(await _read_project_document_impl(runtime, document_id=row["id"], offset=1000, limit=100))
        assert (page1["total_chars"], page2["total_chars"], page3["total_chars"]) == (1000, 1000, 1000)
        assert calls == 1
        assert page2["content"] == (b"0123456789" * 10).decode()

    async def test_multibyte_split_across_chunks_decodes_correctly(self, env):
        payload = b"a" * 65535 + "中".encode() + b"tail"
        row = await _shelve(env, name="split.txt", data=payload)
        result = json.loads(await _read_project_document_impl(_runtime(project_id=env.project["id"]), document_id=row["id"], offset=65533, limit=8))
        assert result["content"] == "aa中tail"
        assert result["total_chars"] == 65535 + 1 + 4

    async def test_invalid_utf8_is_replacement_tolerated(self, env):
        row = await _shelve(env, name="mixed.txt", data=b"hello \xff\xfe world")
        result = json.loads(await _read_project_document_impl(_runtime(project_id=env.project["id"]), document_id=row["id"], offset=0, limit=100))
        assert result["content"] == "hello \ufffd\ufffd world"
        assert result["total_chars"] == 14


class TestReadOriginalIntegrity:
    """The serving path validates the immutable original (existence AND
    recorded size) before selecting either serving source (§6.2/§11): a
    truncated original is ``content_missing``, never served as complete, and
    the derived companion is only servable while its owning original
    validates."""

    async def test_truncated_original_reports_content_missing(self, env):
        row = await _shelve(env, name="notes.txt", data=b"hello shelf")
        original_file_path(env.paths, user_id=_USER, row=row).write_bytes(b"he")
        result = json.loads(await _read_project_document_impl(_runtime(project_id=env.project["id"]), document_id=row["id"], offset=0, limit=100))
        assert "error" in result
        assert "content_missing" in result["error"]

    async def test_zero_byte_original_with_recorded_size_reports_content_missing(self, env):
        row = await _shelve(env, name="notes.txt", data=b"hello shelf")
        original_file_path(env.paths, user_id=_USER, row=row).write_bytes(b"")
        result = json.loads(await _read_project_document_impl(_runtime(project_id=env.project["id"]), document_id=row["id"], offset=0, limit=100))
        assert "error" in result
        assert "content_missing" in result["error"]

    async def test_missing_original_with_cached_derived_reports_content_missing(self, env, monkeypatch):
        from deerflow.projects import documents as documents_mod

        async def fake_convert(file_path, output_path=None):
            output_path.write_text("# converted markdown", encoding="utf-8")
            return output_path

        monkeypatch.setattr(documents_mod, "convert_file_to_markdown", fake_convert)
        monkeypatch.setattr("deerflow.projects.tools._resolve_auto_convert", lambda: True)
        row = await _shelve(env, name="report.docx", data=b"\x00docx-bytes")
        runtime = _runtime(project_id=env.project["id"])
        first = json.loads(await _read_project_document_impl(runtime, document_id=row["id"], offset=0, limit=100))
        assert first["content"] == "# converted markdown"
        # The companion is valid only for the lifetime of its owning original.
        original_file_path(env.paths, user_id=_USER, row=row).unlink()
        result = json.loads(await _read_project_document_impl(runtime, document_id=row["id"], offset=0, limit=100))
        assert "error" in result
        assert "content_missing" in result["error"]

    async def test_valid_derived_is_served_without_reconversion(self, env, monkeypatch):
        from deerflow.projects import documents as documents_mod

        calls = 0

        async def fake_convert(file_path, output_path=None):
            nonlocal calls
            calls += 1
            output_path.write_text("# converted markdown", encoding="utf-8")
            return output_path

        monkeypatch.setattr(documents_mod, "convert_file_to_markdown", fake_convert)
        monkeypatch.setattr("deerflow.projects.tools._resolve_auto_convert", lambda: True)
        row = await _shelve(env, name="report.docx", data=b"\x00docx-bytes")
        runtime = _runtime(project_id=env.project["id"])
        first = json.loads(await _read_project_document_impl(runtime, document_id=row["id"], offset=0, limit=100))
        assert first["content"] == "# converted markdown"
        assert calls == 1
        second = json.loads(await _read_project_document_impl(runtime, document_id=row["id"], offset=0, limit=100))
        assert second["content"] == "# converted markdown"
        assert calls == 1


class TestConversionSerialization:
    """§6.3/§13: conversion holds the document row lock through publication,
    revalidating active state after locking — a trash/purge either commits
    first (conversion declines, nothing published) or blocks until the
    publish commits and then proceeds."""

    @staticmethod
    def _no_temp_left(env, row: dict) -> bool:
        namespace = env.paths.project_document_path(_USER, row["stored_relpath"])
        return not namespace.exists() or list(namespace.rglob("*.tmp")) == []

    async def test_conversion_first_purge_blocks_then_removes_everything(self, env, monkeypatch):
        from deerflow.projects import documents as documents_mod

        started = threading.Event()
        finish = threading.Event()

        async def fake_convert(file_path, output_path=None):
            started.set()
            assert finish.wait(10)
            output_path.write_text("# converted markdown", encoding="utf-8")
            return output_path

        monkeypatch.setattr(documents_mod, "convert_file_to_markdown", fake_convert)
        row = await _shelve(env, name="report.docx", data=b"\x00docx-bytes")
        original = original_file_path(env.paths, user_id=_USER, row=row)
        derived = converted_markdown_path(env.paths, user_id=_USER, row=row)

        conversion = asyncio.create_task(ensure_converted_markdown(env.docs, env.paths, user_id=_USER, row=row, auto_convert=True))
        assert await asyncio.to_thread(started.wait, 10)

        async def trash_and_purge() -> bool:
            assert await env.docs.trash(row["id"], user_id=_USER) is True
            return await env.docs.purge(row["id"], remove_files=make_purge_file_remover(env.paths, user_id=_USER), user_id=_USER)

        purge_task = asyncio.create_task(trash_and_purge())
        await asyncio.sleep(0.2)
        # Trash+purge is blocked on the row lock the conversion holds.
        assert not purge_task.done()
        finish.set()
        (served, reason), purged = await asyncio.gather(conversion, purge_task)
        assert reason is None and served == derived
        assert purged is True
        # Purge then removed original, derived, and the row; no partial
        # conversion temp file remains.
        assert not original.exists()
        assert not derived.exists()
        assert await env.docs.get(row["id"], include_trashed=True, user_id=_USER) is None
        assert self._no_temp_left(env, row)

    async def test_purge_committed_first_conversion_publishes_nothing(self, env, monkeypatch):
        from deerflow.projects import documents as documents_mod

        called = False

        async def fake_convert(file_path, output_path=None):
            nonlocal called
            called = True
            output_path.write_text("# converted markdown", encoding="utf-8")
            return output_path

        monkeypatch.setattr(documents_mod, "convert_file_to_markdown", fake_convert)
        row = await _shelve(env, name="report.docx", data=b"\x00docx-bytes")
        derived = converted_markdown_path(env.paths, user_id=_USER, row=row)
        assert await env.docs.trash(row["id"], user_id=_USER) is True
        assert await env.docs.purge(row["id"], remove_files=make_purge_file_remover(env.paths, user_id=_USER), user_id=_USER) is True

        served, reason = await ensure_converted_markdown(env.docs, env.paths, user_id=_USER, row=row, auto_convert=True)
        assert (served, reason) == (None, "content_missing")
        assert called is False
        assert not derived.exists()
        assert self._no_temp_left(env, row)

    async def test_trash_committed_first_conversion_publishes_nothing(self, env, monkeypatch):
        from deerflow.projects import documents as documents_mod

        called = False

        async def fake_convert(file_path, output_path=None):
            nonlocal called
            called = True
            output_path.write_text("# converted markdown", encoding="utf-8")
            return output_path

        monkeypatch.setattr(documents_mod, "convert_file_to_markdown", fake_convert)
        row = await _shelve(env, name="report.docx", data=b"\x00docx-bytes")
        derived = converted_markdown_path(env.paths, user_id=_USER, row=row)
        assert await env.docs.trash(row["id"], user_id=_USER) is True

        served, reason = await ensure_converted_markdown(env.docs, env.paths, user_id=_USER, row=row, auto_convert=True)
        assert (served, reason) == (None, "content_missing")
        assert called is False
        assert not derived.exists()
        assert self._no_temp_left(env, row)
