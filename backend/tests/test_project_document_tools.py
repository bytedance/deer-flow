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
    yield SimpleNamespace(paths=paths_mod.get_paths(), sf=sf, projects=projects, docs=docs, project=project)
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
    """§6.3/§13: conversion runs outside any database transaction and stages
    its output under ``.staging/``; only the publish — revalidate the live row,
    then atomically rename into ``derived/`` — holds the document row lock. A
    trash/purge that commits before the publish makes conversion decline with
    nothing published; one arriving during the publish blocks until it
    commits. On SQLite that lock is database-wide, so a conversion holding it
    would stall every unrelated writer."""

    @staticmethod
    def _no_temp_left(env, row: dict) -> bool:
        staging = env.paths.project_documents_dir(_USER, row["project_id"]) / ".staging"
        return not staging.exists() or list(staging.iterdir()) == []

    @staticmethod
    def _gated_convert(started: threading.Event, finish: threading.Event):
        async def fake_convert(file_path, output_path=None):
            # Stall after the output exists, so every cleanup path has a file to remove.
            output_path.write_text("# converted markdown", encoding="utf-8")
            started.set()
            assert finish.wait(10)
            return output_path

        return fake_convert

    async def test_conversion_does_not_block_unrelated_database_writes(self, env, monkeypatch):
        from deerflow.persistence.thread_meta.sql import ThreadMetaRepository
        from deerflow.projects import documents as documents_mod

        started = threading.Event()
        finish = threading.Event()
        monkeypatch.setattr(documents_mod, "convert_file_to_markdown", self._gated_convert(started, finish))
        monkeypatch.setattr("deerflow.projects.tools._resolve_auto_convert", lambda: True)
        row = await _shelve(env, name="report.docx", data=b"\x00docx-bytes")

        # Driven through the agent tool, the path a first read actually takes.
        read = asyncio.create_task(_read_project_document_impl(_runtime(project_id=env.project["id"]), document_id=row["id"], offset=0, limit=100))
        try:
            assert await asyncio.to_thread(started.wait, 10)
            # Another user's thread-metadata write lands while the conversion is still running.
            await asyncio.wait_for(ThreadMetaRepository(env.sf).create("t-unrelated", user_id="u2"), 5)
        finally:
            finish.set()
        assert json.loads(await read)["content"] == "# converted markdown"
        assert converted_markdown_path(env.paths, user_id=_USER, row=row).is_file()
        assert self._no_temp_left(env, row)

    async def test_restored_document_converts_from_its_new_project_into_its_original_namespace(self, env, monkeypatch):
        from deerflow.projects import documents as documents_mod

        async def fake_convert(file_path, output_path=None):
            output_path.write_text("# converted markdown", encoding="utf-8")
            return output_path

        monkeypatch.setattr(documents_mod, "convert_file_to_markdown", fake_convert)
        monkeypatch.setattr("deerflow.projects.tools._resolve_auto_convert", lambda: True)
        row = await _shelve(env, name="report.docx", data=b"\x00docx-bytes")
        target = await env.projects.create(name="T", user_id=_USER)
        assert await env.docs.trash(row["id"], user_id=_USER) is True
        outcome, restored = await env.docs.restore(row["id"], target_project_id=target["id"], user_id=_USER)
        assert outcome == "restored"
        # Restore re-points the row without moving bytes: the namespace stays
        # under the source project while staging happens under the target.
        assert restored["project_id"] == target["id"]
        assert restored["stored_relpath"].startswith(f"{env.project['id']}/")

        result = json.loads(await _read_project_document_impl(_runtime(project_id=target["id"]), document_id=row["id"], offset=0, limit=100))
        assert result["content"] == "# converted markdown"
        assert converted_markdown_path(env.paths, user_id=_USER, row=restored).is_file()
        assert self._no_temp_left(env, restored)

    async def test_purge_during_conversion_proceeds_and_conversion_publishes_nothing(self, env, monkeypatch):
        from deerflow.projects import documents as documents_mod

        started = threading.Event()
        finish = threading.Event()
        monkeypatch.setattr(documents_mod, "convert_file_to_markdown", self._gated_convert(started, finish))
        row = await _shelve(env, name="report.docx", data=b"\x00docx-bytes")

        conversion = asyncio.create_task(ensure_converted_markdown(env.docs, env.paths, user_id=_USER, row=row, auto_convert=True))
        try:
            assert await asyncio.to_thread(started.wait, 10)
            assert await asyncio.wait_for(env.docs.trash(row["id"], user_id=_USER), 5) is True
            assert await asyncio.wait_for(env.docs.purge(row["id"], remove_files=make_purge_file_remover(env.paths, user_id=_USER), user_id=_USER), 5) is True
        finally:
            finish.set()
        served, reason = await conversion
        # The locked revalidation finds the row gone, so the staged output is
        # discarded instead of published after the purge.
        assert (served, reason) == (None, "content_missing")
        assert await env.docs.get(row["id"], include_trashed=True, user_id=_USER) is None
        # The output never lived in the namespace, so purge removed all of it.
        assert not env.paths.project_document_path(_USER, row["stored_relpath"]).exists()
        assert self._no_temp_left(env, row)

    async def test_trash_during_conversion_proceeds_and_conversion_publishes_nothing(self, env, monkeypatch):
        from deerflow.projects import documents as documents_mod

        started = threading.Event()
        finish = threading.Event()
        monkeypatch.setattr(documents_mod, "convert_file_to_markdown", self._gated_convert(started, finish))
        row = await _shelve(env, name="report.docx", data=b"\x00docx-bytes")
        derived = converted_markdown_path(env.paths, user_id=_USER, row=row)

        conversion = asyncio.create_task(ensure_converted_markdown(env.docs, env.paths, user_id=_USER, row=row, auto_convert=True))
        try:
            assert await asyncio.to_thread(started.wait, 10)
            assert await asyncio.wait_for(env.docs.trash(row["id"], user_id=_USER), 5) is True
        finally:
            finish.set()
        served, reason = await conversion
        assert (served, reason) == (None, "content_missing")
        assert not derived.exists()
        assert self._no_temp_left(env, row)

    async def test_failed_conversion_of_a_row_purged_meanwhile_reports_content_missing(self, env, monkeypatch):
        from deerflow.projects import documents as documents_mod

        started = threading.Event()
        finish = threading.Event()

        async def failing_convert(file_path, output_path=None):
            started.set()
            assert finish.wait(10)
            return None

        monkeypatch.setattr(documents_mod, "convert_file_to_markdown", failing_convert)
        row = await _shelve(env, name="report.docx", data=b"\x00docx-bytes")

        conversion = asyncio.create_task(ensure_converted_markdown(env.docs, env.paths, user_id=_USER, row=row, auto_convert=True))
        try:
            assert await asyncio.to_thread(started.wait, 10)
            assert await asyncio.wait_for(env.docs.trash(row["id"], user_id=_USER), 5) is True
            assert await asyncio.wait_for(env.docs.purge(row["id"], remove_files=make_purge_file_remover(env.paths, user_id=_USER), user_id=_USER), 5) is True
        finally:
            finish.set()
        # The failure is revalidated under the lock: the row is gone, so the
        # reason is content_missing rather than binary.
        assert await conversion == (None, "content_missing")
        assert self._no_temp_left(env, row)

    async def test_cancelled_conversion_drains_and_leaves_no_staged_output(self, env, monkeypatch):
        from deerflow.projects import documents as documents_mod

        started = threading.Event()
        finish = threading.Event()
        monkeypatch.setattr(documents_mod, "convert_file_to_markdown", self._gated_convert(started, finish))
        row = await _shelve(env, name="report.docx", data=b"\x00docx-bytes")
        derived = converted_markdown_path(env.paths, user_id=_USER, row=row)

        conversion = asyncio.create_task(ensure_converted_markdown(env.docs, env.paths, user_id=_USER, row=row, auto_convert=True))
        assert await asyncio.to_thread(started.wait, 10)
        conversion.cancel()
        await asyncio.sleep(0.2)
        # The worker cannot be interrupted: the cancellation waits for it, so
        # the staged output is removed after the worker's last write.
        assert not conversion.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await conversion
        assert not derived.exists()
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


class TestConversionSingleFlight:
    """Concurrent first reads of one document share a single conversion.

    Conversion occupies a bounded file-IO pool thread for its whole duration,
    so duplicates would starve unrelated offloaded file work. Followers wait
    on the leader without holding a pool thread — from any event loop, since
    the tool also runs on the isolated subagent loop — and a cancelled leader
    hands the work to a follower instead of failing it."""

    @staticmethod
    def _counting_gated_convert(started: threading.Event, finish: threading.Event, calls: list[str]):
        async def fake_convert(file_path, output_path=None):
            calls.append(str(file_path))
            started.set()
            assert finish.wait(10)
            output_path.write_text("# converted markdown", encoding="utf-8")
            return output_path

        return fake_convert

    async def test_concurrent_first_reads_share_one_conversion_across_event_loops(self, env, monkeypatch):
        from deerflow.projects import documents as documents_mod

        started = threading.Event()
        finish = threading.Event()
        calls: list[str] = []
        monkeypatch.setattr(documents_mod, "convert_file_to_markdown", self._counting_gated_convert(started, finish, calls))
        row = await _shelve(env, name="report.docx", data=b"\x00docx-bytes")
        derived = converted_markdown_path(env.paths, user_id=_USER, row=row)

        def read() -> asyncio.Task:
            return asyncio.create_task(ensure_converted_markdown(env.docs, env.paths, user_id=_USER, row=row, auto_convert=True))

        leader = read()
        try:
            assert await asyncio.to_thread(started.wait, 10)
            followers = [read(), read()]
            # A follower on another event loop, like the isolated subagent loop.
            other_loop = asyncio.create_task(asyncio.to_thread(asyncio.run, ensure_converted_markdown(env.docs, env.paths, user_id=_USER, row=row, auto_convert=True)))
            await asyncio.sleep(0.2)
            assert len(calls) == 1
        finally:
            finish.set()
        results = await asyncio.gather(leader, *followers, other_loop)
        assert results == [(derived, None)] * 4
        assert len(calls) == 1
        assert documents_mod._inflight_conversions == {}

    async def test_cancelled_follower_leaves_the_shared_conversion_running(self, env, monkeypatch):
        from deerflow.projects import documents as documents_mod

        started = threading.Event()
        finish = threading.Event()
        calls: list[str] = []
        monkeypatch.setattr(documents_mod, "convert_file_to_markdown", self._counting_gated_convert(started, finish, calls))
        row = await _shelve(env, name="report.docx", data=b"\x00docx-bytes")
        derived = converted_markdown_path(env.paths, user_id=_USER, row=row)

        leader = asyncio.create_task(ensure_converted_markdown(env.docs, env.paths, user_id=_USER, row=row, auto_convert=True))
        try:
            assert await asyncio.to_thread(started.wait, 10)
            follower = asyncio.create_task(ensure_converted_markdown(env.docs, env.paths, user_id=_USER, row=row, auto_convert=True))
            await asyncio.sleep(0.2)
            follower.cancel()
            with pytest.raises(asyncio.CancelledError):
                await follower
        finally:
            finish.set()
        assert await leader == (derived, None)
        assert len(calls) == 1
        assert documents_mod._inflight_conversions == {}

    async def test_follower_takes_over_when_the_leader_is_cancelled(self, env, monkeypatch):
        from deerflow.projects import documents as documents_mod

        started = threading.Event()
        finish = threading.Event()
        calls: list[str] = []
        monkeypatch.setattr(documents_mod, "convert_file_to_markdown", self._counting_gated_convert(started, finish, calls))
        row = await _shelve(env, name="report.docx", data=b"\x00docx-bytes")
        derived = converted_markdown_path(env.paths, user_id=_USER, row=row)

        leader = asyncio.create_task(ensure_converted_markdown(env.docs, env.paths, user_id=_USER, row=row, auto_convert=True))
        try:
            assert await asyncio.to_thread(started.wait, 10)
            follower = asyncio.create_task(ensure_converted_markdown(env.docs, env.paths, user_id=_USER, row=row, auto_convert=True))
            await asyncio.sleep(0.2)
            leader.cancel()
        finally:
            finish.set()
        with pytest.raises(asyncio.CancelledError):
            await leader
        # The cancelled leader published nothing; the follower converted again
        # instead of inheriting the cancellation.
        assert await follower == (derived, None)
        assert len(calls) == 2
        assert documents_mod._inflight_conversions == {}
