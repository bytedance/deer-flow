"""Tests for the deterministic annotation-draft action (Plan A)."""

import asyncio
from types import SimpleNamespace

import pytest

from deerflow_extension_skill_evolution.drafts import (
    _MAX_DRAFT_NOTES,
    AnnotationDrafts,
)
from deerflow_extension_skill_evolution.evolved import EvolvedSkillStore

USER = "user-1"
OTHER = "user-2"


class _FakeEvolution:
    """Stands in for ManagedEvolution.read; records the call."""

    def __init__(self, content: str = "# Demo\n\nBody.", error: dict | None = None) -> None:
        self.content = content
        self.error = error
        self.calls: list[tuple[str, str | None]] = []

    async def read(self, *, user_id: str, source, skill_name) -> dict:
        self.calls.append((user_id, skill_name))
        if self.error is not None:
            return dict(self.error)
        return {"ok": True, "skill": {"name": skill_name, "content": self.content}}


def _ctx(user_id: str = USER) -> SimpleNamespace:
    return SimpleNamespace(principal=SimpleNamespace(user_id=user_id))


def _set_timestamps(store: EvolvedSkillStore, seconds_by_run: dict[str, str]) -> None:
    """Give annotations distinct updated_at values; CURRENT_TIMESTAMP has
    only second resolution, so rapid inserts would otherwise tie."""
    from contextlib import closing

    with closing(store.connect()) as db, db:
        for run_id, stamp in seconds_by_run.items():
            db.execute("UPDATE skill_annotations SET updated_at = ? WHERE run_id = ?", (stamp, run_id))


def _drafts(tmp_path, evolution, *, store=True, enabled=True) -> AnnotationDrafts:
    return AnnotationDrafts(
        evolution,
        EvolvedSkillStore(tmp_path / "store.sqlite") if store else None,
        mode_reader=lambda: "append" if enabled else "model",
    )


def test_draft_appends_the_feedback_section_from_annotations(tmp_path) -> None:
    evolution = _FakeEvolution(content="# Demo\n\nBody.")
    drafts = _drafts(tmp_path, evolution)
    drafts._store.save_annotation(owner=USER, skill_name="demo-evolution", run_id="run-0001", event_id="evt-01", note="Always forgets step 2")
    drafts._store.save_annotation(owner=USER, skill_name="demo-evolution", run_id="run-0002", event_id="evt-02", note="Great at summaries")
    _set_timestamps(drafts._store, {"run-0001": "2026-01-01 00:00:01", "run-0002": "2026-01-01 00:00:02"})

    result = asyncio.run(drafts.annotation_draft({"skill_name": "demo-evolution"}, _ctx()))

    assert result["ok"] is True
    assert result["skill_name"] == "demo-evolution"
    assert result["feedback_count"] == 2
    assert result["included_count"] == 2
    assert result["truncated"] is False
    assert result["content"].startswith("# Demo\n\nBody.")
    assert "## Usage Feedback" in result["content"]
    # Chronological order: the older note renders first.
    older = result["content"].index("Always forgets step 2")
    newer = result["content"].index("Great at summaries")
    assert older < newer
    assert "[run run-0001 · event evt-01" in result["content"]
    # The read went through the managed pipeline for this caller, with
    # auto-discovered (None) source.
    assert evolution.calls == [(USER, "demo-evolution")]


def test_draft_without_annotations_equals_the_current_content(tmp_path) -> None:
    drafts = _drafts(tmp_path, _FakeEvolution(content="# Demo"))
    result = asyncio.run(drafts.annotation_draft({"skill_name": "demo-evolution"}, _ctx()))
    assert result["ok"] is True
    assert result["content"] == "# Demo"
    assert result["feedback_count"] == 0
    assert result["included_count"] == 0
    assert result["truncated"] is False


def test_draft_without_store_degrades_to_the_current_content(tmp_path) -> None:
    drafts = _drafts(tmp_path, _FakeEvolution(content="# Demo"), store=False)
    result = asyncio.run(drafts.annotation_draft({"skill_name": "demo-evolution"}, _ctx()))
    assert result["ok"] is True
    assert result["content"] == "# Demo"
    assert result["feedback_count"] == 0


def test_draft_only_sees_the_callers_own_annotations(tmp_path) -> None:
    drafts = _drafts(tmp_path, _FakeEvolution(content="# Demo"))
    drafts._store.save_annotation(owner=OTHER, skill_name="demo-evolution", run_id="run-0001", event_id="evt-01", note="someone else")
    result = asyncio.run(drafts.annotation_draft({"skill_name": "demo-evolution"}, _ctx()))
    assert result["ok"] is True
    assert result["feedback_count"] == 0
    assert "someone else" not in result["content"]


def test_draft_caps_the_note_count_and_marks_truncation(tmp_path) -> None:
    drafts = _drafts(tmp_path, _FakeEvolution(content="# Demo"))
    for index in range(_MAX_DRAFT_NOTES + 5):
        drafts._store.save_annotation(owner=USER, skill_name="demo-evolution", run_id=f"run-{index:04d}", event_id=f"evt-{index:02d}", note=f"note {index}")
    _set_timestamps(drafts._store, {f"run-{index:04d}": f"2026-01-01 00:{index // 60:02d}:{index % 60:02d}" for index in range(_MAX_DRAFT_NOTES + 5)})
    result = asyncio.run(drafts.annotation_draft({"skill_name": "demo-evolution"}, _ctx()))
    assert result["ok"] is True
    assert result["feedback_count"] == _MAX_DRAFT_NOTES + 5
    assert result["included_count"] == _MAX_DRAFT_NOTES
    assert result["truncated"] is True
    # The newest notes are kept: note 0 was dropped, the last one kept.
    assert "note 0\n" not in result["content"]
    assert f"note {_MAX_DRAFT_NOTES + 4}" in result["content"]


def test_draft_caps_the_feedback_section_bytes(tmp_path) -> None:
    drafts = _drafts(tmp_path, _FakeEvolution(content="# Demo"))
    for index in range(3):
        drafts._store.save_annotation(owner=USER, skill_name="demo-evolution", run_id=f"run-{index:04d}", event_id=f"evt-{index:02d}", note="x" * 2000)
        _set_timestamps(drafts._store, {f"run-{index:04d}": f"2026-01-01 00:00:0{index}"})
    result = asyncio.run(drafts.annotation_draft({"skill_name": "demo-evolution"}, _ctx()))
    assert result["ok"] is True
    assert result["feedback_count"] == 3
    assert result["included_count"] == 1
    assert result["truncated"] is True


def test_draft_returns_the_pipeline_error_unchanged(tmp_path) -> None:
    error = {"ok": False, "error": {"code": "SOURCE_STALE_OR_GONE"}}
    drafts = _drafts(tmp_path, _FakeEvolution(error=error))
    result = asyncio.run(drafts.annotation_draft({"skill_name": "demo-evolution"}, _ctx()))
    assert result == error


def test_draft_is_unavailable_in_agent_mode(tmp_path) -> None:
    drafts = _drafts(tmp_path, _FakeEvolution(), enabled=False)  # mode: model
    result = asyncio.run(drafts.annotation_draft({"skill_name": "demo-evolution"}, _ctx()))
    assert result == {"ok": False, "error": {"code": "UNAVAILABLE"}}


@pytest.mark.parametrize(
    "payload",
    [{}, {"skill_name": "demo-evolution", "extra": 1}, "demo-evolution", None, {"skill_name": "Bad Name"}],
)
def test_draft_rejects_invalid_payloads(tmp_path, payload) -> None:
    drafts = _drafts(tmp_path, _FakeEvolution())
    result = asyncio.run(drafts.annotation_draft(payload, _ctx()))
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_REQUEST"


def test_draft_requires_an_authenticated_caller(tmp_path) -> None:
    drafts = _drafts(tmp_path, _FakeEvolution())
    result = asyncio.run(drafts.annotation_draft({"skill_name": "demo-evolution"}, SimpleNamespace(principal=None)))
    assert result == {"ok": False, "error": {"code": "UNAUTHENTICATED"}}


def test_append_is_idempotent_only_after_content_is_published(tmp_path):
    evolution = _FakeEvolution(content="# Demo")
    drafts = _drafts(tmp_path, evolution)
    drafts._store.save_annotation(owner=USER, skill_name="demo-evolution", run_id="run-0001", event_id="evt-01", note="反馈一")
    payload = {"skill_name": "demo-evolution"}
    first = asyncio.run(drafts.annotation_draft(payload, _ctx()))
    # Re-reading an uncommitted draft does not consume annotations.
    assert asyncio.run(drafts.annotation_draft(payload, _ctx()))["content"] == first["content"]
    evolution.content = first["content"]
    repeated = asyncio.run(drafts.annotation_draft(payload, _ctx()))
    assert repeated["content"] == first["content"]
    assert repeated["included_count"] == 0
    assert repeated["already_included_count"] == 1
    assert repeated["truncated"] is False
    # Editing a consumed annotation creates new feedback, even in the same second.
    drafts._store.save_annotation(owner=USER, skill_name="demo-evolution", run_id="run-0001", event_id="evt-01", note="反馈二")
    edited = asyncio.run(drafts.annotation_draft(payload, _ctx()))
    assert edited["included_count"] == 1
    assert "反馈二" in edited["content"]
    # Reverting to the original content makes feedback eligible again.
    evolution.content = "# Demo"
    assert asyncio.run(drafts.annotation_draft(payload, _ctx()))["included_count"] == 1


def test_append_dedup_uses_full_ids_and_filters_before_cap(tmp_path):
    evolution = _FakeEvolution(content="# Demo")
    drafts = _drafts(tmp_path, evolution)
    for i in range(_MAX_DRAFT_NOTES + 1):
        drafts._store.save_annotation(owner=USER, skill_name="demo-evolution", run_id=f"same-pre-{i:03d}", event_id="event-same-prefix", note="identical note")
    payload = {"skill_name": "demo-evolution"}
    first = asyncio.run(drafts.annotation_draft(payload, _ctx()))
    assert first["included_count"] == _MAX_DRAFT_NOTES
    evolution.content = first["content"]
    second = asyncio.run(drafts.annotation_draft(payload, _ctx()))
    assert second["included_count"] == 1
    assert second["truncated"] is False
    evolution.content = second["content"]
    assert asyncio.run(drafts.annotation_draft(payload, _ctx()))["included_count"] == 0


def test_append_deduplicates_legacy_rendered_feedback(tmp_path):
    evolution = _FakeEvolution()
    drafts = _drafts(tmp_path, evolution)
    drafts._store.save_annotation(owner=USER, skill_name="demo-evolution", run_id="run-0001", event_id="evt-01", note="legacy feedback")
    _set_timestamps(drafts._store, {"run-0001": "2026-01-01 00:00:01"})
    evolution.content = "# Demo\n\n## Usage Feedback\n\n- [run run-0001 · event evt-01 · 2026-01-01 00:00:01] legacy feedback"
    result = asyncio.run(drafts.annotation_draft({"skill_name": "demo-evolution"}, _ctx()))
    assert result["content"] == evolution.content
    assert result["included_count"] == 0


def test_resaving_identical_feedback_does_not_duplicate_it(tmp_path):
    evolution = _FakeEvolution(content="# Demo")
    drafts = _drafts(tmp_path, evolution)
    payload = {"skill_name": "demo-evolution"}
    annotation = dict(owner=USER, skill_name="demo-evolution", run_id="run-0001", event_id="evt-01", note="unchanged note")
    drafts._store.save_annotation(**annotation)
    first = asyncio.run(drafts.annotation_draft(payload, _ctx()))
    evolution.content = first["content"]
    drafts._store.save_annotation(**annotation)
    _set_timestamps(drafts._store, {"run-0001": "2027-01-01 00:00:00"})
    assert asyncio.run(drafts.annotation_draft(payload, _ctx()))["content"] == first["content"]
