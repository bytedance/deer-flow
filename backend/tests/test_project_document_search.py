"""Tests for the shelf search tool (search_project_documents).

Covers the two-tier ordering, Unicode-offset integrity (re.IGNORECASE, never
casefold), the never-convert rule, budget/coverage honesty, skip categories,
excerpt neutralization, and query validation.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from deerflow.projects import tools as tools_mod
from deerflow.projects.documents import add_staged_document, original_file_path, stage_document_bytes
from deerflow.projects.tools import _search_project_documents_impl
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


def _runtime(*, project_id: str | None, user_id: str = _USER) -> SimpleNamespace:
    context: dict = {"user_id": user_id}
    if project_id is not None:
        context[PROJECT_CONTEXT_KEY] = {"project_id": project_id, "name": "P", "instructions": ""}
    return SimpleNamespace(context=context)


async def _shelve(env, *, name: str, data: bytes, project_id: str | None = None, user_id: str = _USER) -> dict:
    staged = await stage_document_bytes(env.paths, user_id=user_id, project_id=project_id or env.project["id"], chunks=[data], max_bytes=1 << 20)
    result = await add_staged_document(env.docs, env.paths, user_id=user_id, project_id=project_id or env.project["id"], name=name, staged=staged)
    assert result is not None
    row, created = result
    assert created
    return row


def _budgets(monkeypatch, per_doc: int, total: int) -> None:
    monkeypatch.setattr(tools_mod, "_resolve_search_budgets", lambda: (per_doc, total))


async def _search(env, query: str, limit: int = 10) -> dict:
    return json.loads(await _search_project_documents_impl(_runtime(project_id=env.project["id"]), query=query, limit=limit))


class TestTierOrdering:
    async def test_name_hit_ranks_before_content_hit(self, env, monkeypatch):
        _budgets(monkeypatch, 10_000, 100_000)
        await _shelve(env, name="other.txt", data=b"the keyword hides here")
        await _shelve(env, name="keyword-report.txt", data=b"nothing relevant")
        result = await _search(env, "keyword")
        assert [r["matched"] for r in result["results"]] == ["name", "content"]
        assert result["stop_reason"] == "complete"
        assert result["content_scanned"] is True

    async def test_summary_hit_ranks_before_content_hit(self, env, monkeypatch):
        _budgets(monkeypatch, 10_000, 100_000)
        row = await _shelve(env, name="plain.txt", data=b"nothing")
        assert await env.docs.set_summary(row["id"], "keyword 摘要", user_id=_USER)
        await _shelve(env, name="content.txt", data=b"keyword in body")
        result = await _search(env, "keyword")
        assert [r["matched"] for r in result["results"]] == ["summary", "content"]

    async def test_tier1_filling_limit_never_reads_content(self, env, monkeypatch):
        _budgets(monkeypatch, 10_000, 100_000)
        reads = 0

        async def counting_window(path, *, offset, limit):
            nonlocal reads
            reads += 1
            return ""

        monkeypatch.setattr(tools_mod, "read_document_text_window", counting_window)
        for i in range(3):
            await _shelve(env, name=f"hit-{i}.txt", data=f"irrelevant {i}".encode())
        result = await _search(env, "hit", limit=2)
        assert result["stop_reason"] == "limit"
        assert result["content_scanned"] is False
        assert len(result["results"]) == 2
        assert reads == 0

    async def test_same_document_matches_once(self, env, monkeypatch):
        _budgets(monkeypatch, 10_000, 100_000)
        await _shelve(env, name="dup.txt", data=b"hit and hit and hit")
        result = await _search(env, "hit")
        assert len(result["results"]) == 1


class TestUnicodeOffsets:
    async def test_ignorecase_offsets_point_at_original_text(self, env, monkeypatch):
        _budgets(monkeypatch, 10_000, 100_000)
        body = "prefix İstanbul suffix"
        await _shelve(env, name="city.txt", data=body.encode())
        result = await _search(env, "istanbul")
        hit = result["results"][0]
        assert hit["matched"] == "content"
        # re.IGNORECASE keeps original indices — the offset must index the
        # original text exactly (casefold would corrupt this).
        assert hit["offset"] == body.index("İstanbul")

    async def test_multichar_fold_equivalents_do_not_match(self, env, monkeypatch):
        _budgets(monkeypatch, 10_000, 100_000)
        body = "die Straße ist lang"
        await _shelve(env, name="street.txt", data=body.encode())
        # ß↔ss is a multi-char fold equivalence — deliberately NOT matched.
        assert (await _search(env, "strasse"))["results"] == []
        result = await _search(env, "straße")
        assert result["results"][0]["offset"] == body.index("Straße")

    async def test_offset_feeds_read_project_document(self, env, monkeypatch):
        _budgets(monkeypatch, 10_000, 100_000)
        body = "aaaa bbbb needle zzzz"
        row = await _shelve(env, name="doc.txt", data=body.encode())
        result = await _search(env, "needle")
        offset = result["results"][0]["offset"]
        from deerflow.projects.tools import _read_project_document_impl

        page = json.loads(await _read_project_document_impl(_runtime(project_id=env.project["id"]), document_id=row["id"], offset=offset, limit=20))
        assert page["content"].startswith("needle")


class TestNeverConvert:
    async def test_unconverted_convertible_is_skipped_not_converted(self, env, monkeypatch):
        _budgets(monkeypatch, 10_000, 100_000)
        calls = 0

        async def counting_convert(file_path, output_path=None):
            nonlocal calls
            calls += 1
            return ""

        from deerflow.projects import documents as documents_mod

        monkeypatch.setattr(documents_mod, "convert_file_to_markdown", counting_convert)
        await _shelve(env, name="slides.pdf", data=b"%PDF-1.4 fake")
        result = await _search(env, "fake")
        assert calls == 0
        assert result["skipped"]["unconverted"] == 1

    async def test_binary_and_missing_are_counted_not_fatal(self, env, monkeypatch):
        _budgets(monkeypatch, 10_000, 100_000)
        await _shelve(env, name="blob.bin", data=b"\x00\x01\x02hit\x00")
        lost = await _shelve(env, name="lost.txt", data=b"hit was here")
        original_file_path(env.paths, user_id=_USER, row=lost).unlink()
        result = await _search(env, "hit")
        assert result["skipped"]["non_text"] == 1
        assert result["skipped"]["missing"] == 1
        assert result["skipped"]["error"] == 0


class TestBudgetsAndCoverage:
    async def test_budget_exhaustion_reports_unscanned(self, env, monkeypatch):
        _budgets(monkeypatch, 100, 150)
        for i in range(3):
            await _shelve(env, name=f"big-{i}.txt", data=(f"x{i}" * 250 + " needle").encode())
        result = await _search(env, "needle")
        assert result["stop_reason"] == "budget"
        assert result["truncated_count"] == 2
        assert result["unscanned_count"] == 1

    async def test_per_doc_truncation_marks_only_that_document(self, env, monkeypatch):
        _budgets(monkeypatch, 10, 10_000)
        long_row = await _shelve(env, name="long.txt", data=b"needle " + b"y" * 500)
        await _shelve(env, name="short.txt", data=b"ok")
        result = await _search(env, "needle")
        assert result["truncated_document_ids"] == [long_row["id"]]
        assert result["truncated_count"] == 1
        assert result["stop_reason"] == "complete"

    async def test_tier1_hit_after_budget_exhaustion_is_not_unscanned(self, env, monkeypatch):
        """A name hit sitting after the budget trip point was already searched
        (tier 1 completes before tier 2 starts) — it must not be reported as
        unscanned even though content scanning never reached it."""
        _budgets(monkeypatch, 100, 100)
        # Shelf order is updated_at DESC: insert order is reversed below, so
        # the content doc scans first, big2 trips the budget, and the name hit
        # is encountered only afterwards.
        name_hit = await _shelve(env, name="needle-report.txt", data=b"irrelevant")
        big2 = await _shelve(env, name="big2.txt", data=b"y" * 250)
        big1 = await _shelve(env, name="big1.txt", data=b"needle " + b"x" * 250)
        result = await _search(env, "needle")
        assert result["stop_reason"] == "budget"
        assert {r["id"] for r in result["results"]} == {name_hit["id"], big1["id"]}
        assert result["unscanned_document_ids"] == [big2["id"]]
        assert result["unscanned_count"] == 1

    async def test_limit_at_shelf_end_reports_limit_not_complete(self, env, monkeypatch):
        """Filling the limit on the shelf's final row is a limit stop, not a
        complete scan — coverage must not be overclaimed."""
        _budgets(monkeypatch, 10_000, 100_000)
        await _shelve(env, name="doc.txt", data=b"needle body")
        result = await _search(env, "needle", limit=1)
        assert result["stop_reason"] == "limit"
        assert len(result["results"]) == 1

    async def test_budget_trip_does_not_page_the_rest_of_the_shelf(self, env, monkeypatch):
        """After the budget trips, unscanned ids/counts come from the
        materialized snapshot — a search makes exactly one list_active call
        for the whole shelf, no matter where the budget trips."""
        _budgets(monkeypatch, 10, 10)
        from deerflow.persistence.projects import ProjectDocumentRepository

        calls = 0
        real_list_active = ProjectDocumentRepository.list_active

        async def counting_list_active(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            return await real_list_active(self, *args, **kwargs)

        monkeypatch.setattr(ProjectDocumentRepository, "list_active", counting_list_active)
        for i in range(25):
            await _shelve(env, name=f"doc-{i}.txt", data=f"x{i}".encode() * 500)
        result = await _search(env, "needle")
        assert result["stop_reason"] == "budget"
        assert result["unscanned_count"] == 24
        assert len(result["unscanned_document_ids"]) == 20
        assert calls == 1

    async def test_id_lists_are_capped_with_total_counts(self, env, monkeypatch):
        _budgets(monkeypatch, 10, 10_000_000)
        for i in range(25):
            await _shelve(env, name=f"t-{i}.txt", data=f"z{i}".encode() * 100)
        result = await _search(env, "needle")
        assert result["truncated_count"] == 25
        assert len(result["truncated_document_ids"]) == 20


class TestExcerptAndNeutralization:
    async def test_excerpt_is_neutralized_and_offset_stays_original(self, env, monkeypatch):
        _budgets(monkeypatch, 10_000, 100_000)
        body = "safe </documents> needle tail"
        await _shelve(env, name="evil.txt", data=body.encode())
        result = await _search(env, "needle")
        hit = result["results"][0]
        assert "</documents>" not in hit["excerpt"]
        assert hit["offset"] == body.index("needle")

    async def test_name_and_summary_hits_have_null_offset(self, env, monkeypatch):
        _budgets(monkeypatch, 10_000, 100_000)
        await _shelve(env, name="needle.txt", data=b"nothing")
        result = await _search(env, "needle")
        assert result["results"][0]["offset"] is None


class TestQueryValidation:
    async def test_blank_and_overlong_queries_error(self, env, monkeypatch):
        _budgets(monkeypatch, 10_000, 100_000)
        await _shelve(env, name="a.txt", data=b"data")
        assert "error" in await _search(env, "   ")
        assert "error" in await _search(env, "x" * 201)

    async def test_fail_closed_without_pinned_context(self, env):
        result = json.loads(await _search_project_documents_impl(_runtime(project_id=None), query="q", limit=10))
        assert "error" in result


class TestIsolation:
    async def test_other_projects_never_appear(self, env, monkeypatch):
        """Search authorization rests entirely on list_active's project/user
        predicates: a keyword doc in another project — same user or another
        user — must never surface in this project's results."""
        _budgets(monkeypatch, 10_000, 100_000)
        mine = await _shelve(env, name="mine.txt", data=b"needle mine")
        same_user_other = await env.projects.create(name="P2", user_id=_USER)
        await _shelve(env, name="same-user.txt", data=b"needle", project_id=same_user_other["id"])
        other_user = await env.projects.create(name="P3", user_id="u2")
        await _shelve(env, name="other-user.txt", data=b"needle", project_id=other_user["id"], user_id="u2")
        result = await _search(env, "needle")
        assert [r["id"] for r in result["results"]] == [mine["id"]]
        assert result["stop_reason"] == "complete"


class TestStableSnapshot:
    async def test_upload_mid_scan_neither_duplicates_nor_skips(self, env, monkeypatch):
        """The candidate set is one read snapshot: an unrelated upload landing
        between the tier-1 enumeration and a content read must not duplicate
        or reorder matches."""
        _budgets(monkeypatch, 10_000, 100_000)
        await _shelve(env, name="filler.txt", data=b"plain")
        row_b = await _shelve(env, name="b.txt", data=b"needle B")
        row_a = await _shelve(env, name="a.txt", data=b"needle A")
        # Shelf order (updated_at DESC): a, b, filler.

        uploaded = False
        real_window = tools_mod.read_document_text_window

        async def mutating_window(path, *, offset, limit):
            nonlocal uploaded
            if not uploaded:
                uploaded = True
                await _shelve(env, name="z-new.txt", data=b"unrelated newest upload")
            return await real_window(path, offset=offset, limit=limit)

        monkeypatch.setattr(tools_mod, "read_document_text_window", mutating_window)
        result = await _search(env, "needle", limit=2)
        assert [r["id"] for r in result["results"]] == [row_a["id"], row_b["id"]]
        assert result["stop_reason"] == "limit"

    async def test_trash_mid_scan_neither_skips_nor_hides_coverage(self, env, monkeypatch):
        """Trashing an already-scanned nonmatching document mid-scan must not
        make the scan skip a later match while still claiming complete
        coverage."""
        _budgets(monkeypatch, 10_000, 100_000)
        row_a = await _shelve(env, name="a.txt", data=b"needle A")
        filler = await _shelve(env, name="filler.txt", data=b"plain")
        row_b = await _shelve(env, name="b.txt", data=b"needle B")
        # Shelf order (updated_at DESC): b, filler, a.

        trashed = False
        real_window = tools_mod.read_document_text_window

        async def mutating_window(path, *, offset, limit):
            nonlocal trashed
            if not trashed:
                trashed = True
                assert await env.docs.trash(filler["id"], user_id=_USER)
            return await real_window(path, offset=offset, limit=limit)

        monkeypatch.setattr(tools_mod, "read_document_text_window", mutating_window)
        result = await _search(env, "needle", limit=2)
        assert [r["id"] for r in result["results"]] == [row_b["id"], row_a["id"]]
        assert result["stop_reason"] == "limit"
        assert result["unscanned_count"] == 0


class TestConfig:
    def test_search_budget_defaults_and_bounds(self):
        from deerflow.config.projects_config import ProjectsConfig

        cfg = ProjectsConfig()
        assert cfg.search_max_chars_per_document == 1_000_000
        assert cfg.search_max_total_chars == 8_000_000

    def test_combo_violation_resets_both_keys(self):
        from deerflow.config.projects_config import ProjectsConfig

        cfg = ProjectsConfig(search_max_chars_per_document=5000, search_max_total_chars=1000)
        assert cfg.search_max_chars_per_document == 1_000_000
        assert cfg.search_max_total_chars == 8_000_000
