"""Tests for the per-document summary pipeline.

Covers the write-time output contract, the bounded queue, caller-side wait
semantics (slot retained until provider work finishes; late results never
written), provider-normalized length-cap detection, ``updated_at``
preservation, and owner-scoped identity on queued jobs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from deerflow.config.projects_config import ProjectsConfig
from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository
from deerflow.projects import summaries
from deerflow.projects.summaries import SummaryGenerator, _sanitize_summary
from deerflow.utils.oneshot_llm import OneshotLLMResult

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Output contract (pure)
# ---------------------------------------------------------------------------


class TestSanitizeSummary:
    def test_plain_line_passes_through(self):
        assert _sanitize_summary("Q3 营收报告", 256) == "Q3 营收报告"

    def test_code_fence_and_list_marker_unwrapped(self):
        assert _sanitize_summary("```\n- quarterly report\n```", 256) == "quarterly report"

    def test_surrounding_quotes_stripped(self):
        assert _sanitize_summary('"a short report"', 256) == "a short report"

    def test_curly_quotes_strip_as_pairs(self):
        assert _sanitize_summary("“季度报告”", 256) == "季度报告"
        assert _sanitize_summary("‘report’", 256) == "report"
        # Mismatched pairs are not stripped.
        assert _sanitize_summary("“report”".replace("”", '"'), 256) == '“report"'

    def test_newlines_collapse_to_one_line(self):
        result = _sanitize_summary("line one\n\nline two\tand more", 256)
        assert result == "line one line two and more"
        assert "\n" not in result

    def test_empty_after_clean_is_none(self):
        assert _sanitize_summary("```\n\n```", 256) is None
        assert _sanitize_summary("  \n ", 256) is None

    def test_truncation_respects_character_boundary(self):
        # 每 is 3 UTF-8 bytes; a 7-byte cap must not split the third character.
        result = _sanitize_summary("每每每每", 7)
        assert result == "每每"
        assert len(result.encode("utf-8")) <= 7

    def test_leading_think_block_stripped_before_truncation(self):
        reasoning = "<think>" + " deliberation" * 100 + "</think>"
        result = _sanitize_summary(f"{reasoning}\nQ3 营收报告", 256)
        assert result == "Q3 营收报告"

    def test_reasoning_only_output_is_none(self):
        assert _sanitize_summary("<think>only internal reasoning</think>", 256) is None
        # An unfinished reasoning section has no answer to store.
        assert _sanitize_summary("<think>unclosed reasoning", 256) is None

    def test_think_tag_inside_the_answer_is_kept_literal(self):
        result = _sanitize_summary("文档讨论了 <think> 标签的用法", 256)
        assert result == "文档讨论了 <think> 标签的用法"


# ---------------------------------------------------------------------------
# Repository: set_summary preserves updated_at


@pytest.fixture
async def repos(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    yield sf, ProjectRepository(sf), ProjectDocumentRepository(sf)
    await close_engine()


async def _shelf_row(projects, docs, *, user_id="u1"):
    project = await projects.create(name="P", user_id=user_id)
    row = await docs.insert_active(
        project["id"],
        document_id="doc-1",
        name="a.txt",
        relpath=f"{project['id']}/documents/ab/abcd/x",
        sha256="abcd",
        size_bytes=10,
        user_id=user_id,
    )
    assert row is not None
    return project, row


class TestSetSummary:
    async def test_summary_write_preserves_updated_at(self, repos):
        _sf, projects, docs = repos
        _project, row = await _shelf_row(projects, docs)
        before = row["updated_at"]

        assert await docs.set_summary("doc-1", "one line", user_id="u1") is True
        after = await docs.get("doc-1", user_id="u1")
        assert after["summary"] == "one line"
        # The shelf order key and rendered "modified" date must not move (§6.4).
        assert after["updated_at"] == before

    async def test_foreign_or_vanished_row_is_noop(self, repos):
        _sf, projects, docs = repos
        await _shelf_row(projects, docs)
        assert await docs.set_summary("doc-1", "x", user_id="u2") is False
        assert await docs.set_summary("gone", "x", user_id="u1") is False
        assert (await docs.get("doc-1", user_id="u1"))["summary"] is None


# ---------------------------------------------------------------------------
# Generator: queue, model-call semantics, identity
# ---------------------------------------------------------------------------


def _app_config(**overrides) -> SimpleNamespace:
    return SimpleNamespace(projects=ProjectsConfig(summaries_enabled=True, **overrides), uploads=None)


def _result(text: str, metadata: dict | None = None) -> OneshotLLMResult:
    message = AIMessage(content=text, response_metadata=metadata or {})
    return OneshotLLMResult(text=text, message=message)


def _patch_source(monkeypatch, serving: tuple[Path | None, str | None]):
    async def fake_serving_path(repo, paths, *, user_id, row, auto_convert):
        return serving

    monkeypatch.setattr(summaries, "read_text_serving_path", fake_serving_path)


@pytest.fixture
def text_file(tmp_path) -> Path:
    path = tmp_path / "doc.txt"
    path.write_text("Quarterly revenue report with regional breakdown.", encoding="utf-8")
    return path


async def _drain(generator: SummaryGenerator, timeout: float = 5.0) -> None:
    await asyncio.wait_for(generator._queue.join(), timeout)


class TestGenerator:
    async def test_success_writes_summary_and_counts(self, repos, text_file, monkeypatch):
        sf, projects, docs = repos
        await _shelf_row(projects, docs)
        _patch_source(monkeypatch, (text_file, None))
        monkeypatch.setattr(summaries, "run_oneshot_llm_detailed", lambda **kwargs: _fake_model("Q3 营收报告"))
        generator = SummaryGenerator(session_factory=sf, paths=None, app_config=_app_config())
        await generator.start()
        assert generator.enqueue(document_id="doc-1", project_id=(await docs.get("doc-1", user_id="u1"))["project_id"], user_id="u1")
        await _drain(generator)
        await generator.stop()

        assert (await docs.get("doc-1", user_id="u1"))["summary"] == "Q3 营收报告"
        assert generator.metrics()["success"] == 1
        assert generator.metrics()["eligible"] == 1

    async def test_ineligible_source_skips_without_model_call(self, repos, monkeypatch):
        sf, projects, docs = repos
        await _shelf_row(projects, docs)
        _patch_source(monkeypatch, (None, "binary"))
        called = False

        async def model(**kwargs):
            nonlocal called
            called = True
            return _result("x")

        monkeypatch.setattr(summaries, "run_oneshot_llm_detailed", model)
        generator = SummaryGenerator(session_factory=sf, paths=None, app_config=_app_config())
        await generator.start()
        generator.enqueue(document_id="doc-1", project_id=(await docs.get("doc-1", user_id="u1"))["project_id"], user_id="u1")
        await _drain(generator)
        await generator.stop()

        assert called is False
        assert (await docs.get("doc-1", user_id="u1"))["summary"] is None
        assert generator.metrics()["skipped"] == 1

    async def test_length_capped_response_stores_null(self, repos, text_file, monkeypatch):
        sf, projects, docs = repos
        await _shelf_row(projects, docs)
        _patch_source(monkeypatch, (text_file, None))
        monkeypatch.setattr(summaries, "run_oneshot_llm_detailed", lambda **kwargs: _fake_model("truncated …", {"finish_reason": "length"}))
        generator = SummaryGenerator(session_factory=sf, paths=None, app_config=_app_config())
        await generator.start()
        generator.enqueue(document_id="doc-1", project_id=(await docs.get("doc-1", user_id="u1"))["project_id"], user_id="u1")
        await _drain(generator)
        await generator.stop()

        assert (await docs.get("doc-1", user_id="u1"))["summary"] is None
        assert generator.metrics()["failed"] == 1

    async def test_anthropic_style_stop_reason_also_detected(self, repos, text_file, monkeypatch):
        sf, projects, docs = repos
        await _shelf_row(projects, docs)
        _patch_source(monkeypatch, (text_file, None))
        monkeypatch.setattr(summaries, "run_oneshot_llm_detailed", lambda **kwargs: _fake_model("partial", {"stop_reason": "max_tokens"}))
        generator = SummaryGenerator(session_factory=sf, paths=None, app_config=_app_config())
        await generator.start()
        generator.enqueue(document_id="doc-1", project_id=(await docs.get("doc-1", user_id="u1"))["project_id"], user_id="u1")
        await _drain(generator)
        await generator.stop()
        assert (await docs.get("doc-1", user_id="u1"))["summary"] is None

    async def test_missing_termination_metadata_accepted_and_counted(self, repos, text_file, monkeypatch):
        sf, projects, docs = repos
        await _shelf_row(projects, docs)
        _patch_source(monkeypatch, (text_file, None))
        monkeypatch.setattr(summaries, "run_oneshot_llm_detailed", lambda **kwargs: _fake_model("clean line"))
        generator = SummaryGenerator(session_factory=sf, paths=None, app_config=_app_config())
        await generator.start()
        generator.enqueue(document_id="doc-1", project_id=(await docs.get("doc-1", user_id="u1"))["project_id"], user_id="u1")
        await _drain(generator)
        await generator.stop()

        assert (await docs.get("doc-1", user_id="u1"))["summary"] == "clean line"
        assert generator.metrics()["uncapped_accepted"] == 1

    async def test_timeout_holds_slot_and_discards_late_result(self, repos, text_file, monkeypatch):
        sf, projects, docs = repos
        await _shelf_row(projects, docs)
        _patch_source(monkeypatch, (text_file, None))
        blocker = asyncio.Event()
        second_started = asyncio.Event()

        async def blocking_model(**kwargs):
            await blocker.wait()
            return _result("late")

        async def second_model(**kwargs):
            second_started.set()
            return _result("second")

        calls = iter([blocking_model, second_model])

        async def dispatch(**kwargs):
            return await next(calls)(**kwargs)

        monkeypatch.setattr(summaries, "run_oneshot_llm_detailed", dispatch)
        generator = SummaryGenerator(session_factory=sf, paths=None, app_config=_app_config(summary_concurrency=1))
        generator._timeout = 0.2  # shorten the caller-side wait for the test
        await generator.start()
        row = await docs.get("doc-1", user_id="u1")
        generator.enqueue(document_id="doc-1", project_id=row["project_id"], user_id="u1")
        generator.enqueue(document_id="doc-1", project_id=row["project_id"], user_id="u1")

        # The first job times out its wait; the worker must still hold the
        # slot until the provider call actually finishes, so the second job
        # cannot start while the first is blocked.
        await asyncio.sleep(0.5)
        assert not second_started.is_set()
        blocker.set()
        await _drain(generator)
        await generator.stop()

        assert second_started.is_set()
        # Late result never written; the timeout counted as a failure.
        assert (await docs.get("doc-1", user_id="u1"))["summary"] == "second"  # second job overwrites nothing late
        assert generator.metrics()["failed"] >= 1

    async def test_full_queue_drops_and_counts(self, repos, text_file, monkeypatch):
        sf, projects, docs = repos
        await _shelf_row(projects, docs)
        _patch_source(monkeypatch, (text_file, None))
        blocker = asyncio.Event()

        async def blocking_model(**kwargs):
            await blocker.wait()
            return _result("x")

        monkeypatch.setattr(summaries, "run_oneshot_llm_detailed", blocking_model)
        generator = SummaryGenerator(session_factory=sf, paths=None, app_config=_app_config(summary_concurrency=1, summary_queue_size=1))
        await generator.start()
        row = await docs.get("doc-1", user_id="u1")
        assert generator.enqueue(document_id="doc-1", project_id=row["project_id"], user_id="u1") is True  # in-flight
        # Let the single worker pick up the first job.
        await asyncio.sleep(0.1)
        assert generator.enqueue(document_id="doc-1", project_id=row["project_id"], user_id="u1") is True  # queued
        assert generator.enqueue(document_id="doc-1", project_id=row["project_id"], user_id="u1") is False  # dropped
        assert generator.metrics()["queue_dropped"] == 1
        blocker.set()
        await _drain(generator)
        await generator.stop()

    async def test_job_with_wrong_owner_writes_nothing(self, repos, text_file, monkeypatch):
        sf, projects, docs = repos
        await _shelf_row(projects, docs)
        _patch_source(monkeypatch, (text_file, None))
        monkeypatch.setattr(summaries, "run_oneshot_llm_detailed", lambda **kwargs: _fake_model("x"))
        generator = SummaryGenerator(session_factory=sf, paths=None, app_config=_app_config())
        await generator.start()
        row = await docs.get("doc-1", user_id="u1")
        # Identity comes from the job payload, not ambient context (§6.1):
        # a job carrying another user's id cannot even read the row.
        generator.enqueue(document_id="doc-1", project_id=row["project_id"], user_id="u2")
        await _drain(generator)
        await generator.stop()
        assert (await docs.get("doc-1", user_id="u1"))["summary"] is None

    async def test_disabled_generator_accepts_nothing(self, repos):
        sf, _projects, _docs = repos
        cfg = SimpleNamespace(projects=ProjectsConfig(summaries_enabled=False), uploads=None)
        generator = SummaryGenerator(session_factory=sf, paths=None, app_config=cfg)
        await generator.start()
        assert generator.enqueue(document_id="d", project_id="p", user_id="u") is False
        await generator.stop()

    async def test_invocation_tracing_user_is_the_job_owner(self, repos, text_file, monkeypatch):
        from deerflow.runtime.user_context import get_effective_user_id

        sf, projects, docs = repos
        await _shelf_row(projects, docs)
        _patch_source(monkeypatch, (text_file, None))
        seen: list[str] = []

        async def model(**kwargs):
            seen.append(get_effective_user_id())
            return _result("owned")

        monkeypatch.setattr(summaries, "run_oneshot_llm_detailed", model)
        generator = SummaryGenerator(session_factory=sf, paths=None, app_config=_app_config())
        await generator.start()
        row = await docs.get("doc-1", user_id="u1")
        generator.enqueue(document_id="doc-1", project_id=row["project_id"], user_id="u1")
        await _drain(generator)
        await generator.stop()

        # Workers run on the lifespan's empty context; without the explicit
        # binding this would be "default".
        assert seen == ["u1"]

    async def test_worker_cancellation_cancels_the_shielded_model_task(self, repos, text_file, monkeypatch):
        sf, projects, docs = repos
        await _shelf_row(projects, docs)
        _patch_source(monkeypatch, (text_file, None))
        model_started = asyncio.Event()
        model_cancelled = asyncio.Event()

        async def blocking_model(**kwargs):
            model_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                model_cancelled.set()
                raise
            return _result("unreachable")

        monkeypatch.setattr(summaries, "run_oneshot_llm_detailed", blocking_model)
        generator = SummaryGenerator(session_factory=sf, paths=None, app_config=_app_config())
        monkeypatch.setattr(summaries, "_STOP_GRACE_SECONDS", 0.1)
        await generator.start()
        workers = list(generator._workers)
        row = await docs.get("doc-1", user_id="u1")
        generator.enqueue(document_id="doc-1", project_id=row["project_id"], user_id="u1")
        await asyncio.wait_for(model_started.wait(), 2)

        # stop() cancels the worker after the grace budget; the shielded
        # child must be cancelled and settled with it — never left running
        # untracked after stop() returns.
        await generator.stop()
        assert model_cancelled.is_set()
        assert all(task.done() for task in workers)

    async def test_idle_workers_stop_without_waiting_out_the_grace(self, repos):
        import time

        sf, _projects, _docs = repos
        generator = SummaryGenerator(session_factory=sf, paths=None, app_config=_app_config())
        await generator.start()
        started = time.monotonic()
        await generator.stop()
        elapsed = time.monotonic() - started
        # Sentinels wake idle loops: an empty queue shuts down immediately
        # instead of consuming the full grace period.
        assert elapsed < 2.0
        assert generator._workers == []

    async def test_idle_stop_with_queue_smaller_than_worker_count(self, repos):
        """Regression: queue_size=1 < concurrency=2 must still wake BOTH idle
        workers — a sentinel dropped by a full queue would strand one worker
        until the grace expires."""
        import time

        sf, _projects, _docs = repos
        generator = SummaryGenerator(session_factory=sf, paths=None, app_config=_app_config(summary_concurrency=2, summary_queue_size=1))
        await generator.start()
        workers = list(generator._workers)
        started = time.monotonic()
        await generator.stop()
        assert time.monotonic() - started < 2.0
        assert all(task.done() for task in workers)


async def _fake_model(text: str, metadata: dict | None = None) -> OneshotLLMResult:
    return _result(text, metadata)
