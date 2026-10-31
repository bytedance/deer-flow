import asyncio
from contextlib import closing
from types import SimpleNamespace

import pytest

from deerflow_extension_skill_evolution.evolved import EvolvedSkills, EvolvedSkillStore


def _ctx(user_id: str = "user-1") -> SimpleNamespace:
    return SimpleNamespace(principal=SimpleNamespace(user_id=user_id))


def test_store_requires_an_absolute_deployment_owned_path(tmp_path: pytest.TempPathFactory) -> None:
    with pytest.raises(ValueError, match="absolute"):
        EvolvedSkillStore("relative.sqlite")
    assert not (tmp_path / "relative.sqlite").exists()


def test_store_keeps_the_latest_outcome_per_skill_and_owner(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    store.record_outcome(owner="user-1", name="demo-evolution", method="commit", operation_id="op-1")
    store.record_outcome(owner="user-1", name="demo-evolution", method="revert", operation_id="op-2", reverts_operation_id="op-1")
    store.record_outcome(owner="user-1", name="another-skill", method="commit", operation_id="op-3")
    store.record_outcome(owner="user-2", name="demo-evolution", method="commit", operation_id="op-4")
    listed = store.list_skills(owner="user-1")
    assert [(row["name"], row["method"], row["operation_id"]) for row in listed] == [
        ("another-skill", "commit", "op-3"),
        ("demo-evolution", "revert", "op-2"),
    ]
    assert all(row["updated_at"] for row in listed)


def test_store_survives_reopen_and_rejects_bad_records(tmp_path) -> None:
    path = tmp_path / "evolved.sqlite"
    store = EvolvedSkillStore(path)
    store.record_outcome(owner="user-1", name="demo-evolution", method="commit", operation_id="op-1")
    reopened = EvolvedSkillStore(path)
    assert [row["name"] for row in reopened.list_skills(owner="user-1")] == ["demo-evolution"]
    with pytest.raises(ValueError, match="method"):
        reopened.record_outcome(owner="user-1", name="x-skill", method="publish", operation_id="op-2")
    with pytest.raises(ValueError):
        reopened.record_outcome(owner="", name="x-skill", method="commit", operation_id="op-2")
    with pytest.raises(ValueError):
        reopened.record_outcome(owner="user-1", name="x-skill", method="commit", operation_id="bad\x01id")
    assert len(reopened.list_skills(owner="user-1")) == 1


def test_journal_attaches_staged_content_to_commits(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    store.record_stage(owner="user-1", proposal_id="prop-1", name="demo-evolution", content="# v1")
    store.record_outcome(owner="user-1", name="demo-evolution", method="commit", operation_id="op-1", proposal_id="prop-1")
    entry = store.get_version(owner="user-1", operation_id="op-1")
    assert entry == {
        "seq": entry["seq"],
        "name": "demo-evolution",
        "method": "commit",
        "operation_id": "op-1",
        "updated_at": entry["updated_at"],
        "content": "# v1",
    }


def test_journal_commit_without_a_staged_snapshot_has_no_content(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    store.record_outcome(owner="user-1", name="demo-evolution", method="commit", operation_id="op-1", proposal_id="prop-missing")
    entry = store.get_version(owner="user-1", operation_id="op-1")
    assert entry is not None and entry["content"] is None


def test_journal_revert_restores_the_preceding_version_content(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    store.record_stage(owner="user-1", proposal_id="prop-1", name="demo-evolution", content="# v1")
    store.record_stage(owner="user-1", proposal_id="prop-2", name="demo-evolution", content="# v2")
    store.record_outcome(owner="user-1", name="demo-evolution", method="commit", operation_id="op-1", proposal_id="prop-1")
    store.record_outcome(owner="user-1", name="demo-evolution", method="commit", operation_id="op-2", proposal_id="prop-2")
    # Undo op-2: the resulting state is op-1's content.
    store.record_outcome(owner="user-1", name="demo-evolution", method="revert", operation_id="op-3", reverts_operation_id="op-2")
    assert store.get_version(owner="user-1", operation_id="op-3")["content"] == "# v1"
    # Undo op-3 (redo op-2): the resulting state is op-2's content.
    store.record_outcome(owner="user-1", name="demo-evolution", method="revert", operation_id="op-4", reverts_operation_id="op-3")
    assert store.get_version(owner="user-1", operation_id="op-4")["content"] == "# v2"


def test_journal_revert_of_an_unknown_operation_has_no_content(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    store.record_outcome(owner="user-1", name="demo-evolution", method="revert", operation_id="op-1", reverts_operation_id="op-unknown")
    entry = store.get_version(owner="user-1", operation_id="op-1")
    assert entry is not None and entry["content"] is None


def test_journal_records_are_per_owner(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    store.record_stage(owner="user-1", proposal_id="prop-1", name="demo-evolution", content="# mine")
    store.record_outcome(owner="user-1", name="demo-evolution", method="commit", operation_id="op-1", proposal_id="prop-1")
    store.record_stage(owner="user-2", proposal_id="prop-2", name="demo-evolution", content="# theirs")
    # user-2's commit claims a proposal it never staged: no content attached.
    store.record_outcome(owner="user-2", name="demo-evolution", method="commit", operation_id="op-2", proposal_id="prop-1")
    assert store.get_version(owner="user-2", operation_id="op-2")["content"] is None
    assert store.get_version(owner="user-1", operation_id="op-1")["content"] == "# mine"


def test_list_reports_the_version_history_without_content(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    store.record_stage(owner="user-1", proposal_id="prop-1", name="demo-evolution", content="# v1")
    store.record_outcome(owner="user-1", name="demo-evolution", method="commit", operation_id="op-1", proposal_id="prop-1")
    store.record_outcome(owner="user-1", name="demo-evolution", method="commit", operation_id="op-2")
    listed = store.list_skills(owner="user-1")
    (row,) = listed
    history = row["history"]
    assert [entry["operation_id"] for entry in history] == ["op-2", "op-1"]
    assert [entry["has_content"] for entry in history] == [False, True]
    assert all("content" not in entry for entry in history)


def test_action_lists_only_the_callers_skills(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    store.record_outcome(owner="user-1", name="demo-evolution", method="commit", operation_id="op-1")
    handler = EvolvedSkills(store).list
    result = asyncio.run(handler({}, _ctx()))
    assert result["ok"] is True
    assert [row["name"] for row in result["skills"]] == ["demo-evolution"]
    assert asyncio.run(handler({}, _ctx("user-2"))) == {"ok": True, "skills": []}


def test_action_is_fail_closed_on_payload_and_identity(tmp_path) -> None:
    handler = EvolvedSkills(EvolvedSkillStore(tmp_path / "evolved.sqlite")).list
    assert asyncio.run(handler({"name": "x"}, _ctx())) == {"ok": False, "error": {"code": "INVALID_REQUEST"}}
    assert asyncio.run(handler(None, _ctx()))["ok"] is True  # empty payload is the page contract
    assert asyncio.run(handler({}, SimpleNamespace(principal=SimpleNamespace(user_id="")))) == {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
    assert asyncio.run(handler({}, None)) == {"ok": False, "error": {"code": "UNAUTHENTICATED"}}


def test_action_reports_unavailable_without_configured_storage() -> None:
    handler = EvolvedSkills(None).list
    assert asyncio.run(handler({}, _ctx())) == {"ok": False, "error": {"code": "UNAVAILABLE"}}


def test_version_action_returns_the_callers_snapshot(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    store.record_stage(owner="user-1", proposal_id="prop-1", name="demo-evolution", content="# v1")
    store.record_outcome(owner="user-1", name="demo-evolution", method="commit", operation_id="op-1", proposal_id="prop-1")
    handler = EvolvedSkills(store).version
    result = asyncio.run(handler({"operation_id": "op-1"}, _ctx()))
    assert result["ok"] is True
    assert result["version"]["content"] == "# v1"
    assert result["version"]["name"] == "demo-evolution"


def test_version_action_is_owner_scoped_and_fail_closed(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    store.record_stage(owner="user-1", proposal_id="prop-1", name="demo-evolution", content="# v1")
    store.record_outcome(owner="user-1", name="demo-evolution", method="commit", operation_id="op-1", proposal_id="prop-1")
    store.record_outcome(owner="user-1", name="demo-evolution", method="commit", operation_id="op-2")  # no content
    handler = EvolvedSkills(store).version
    # Another user's entry is indistinguishable from a missing one.
    assert asyncio.run(handler({"operation_id": "op-1"}, _ctx("user-2"))) == {"ok": False, "error": {"code": "NOT_FOUND_OR_FORBIDDEN"}}
    # Entries without a content snapshot are not restorable.
    assert asyncio.run(handler({"operation_id": "op-2"}, _ctx())) == {"ok": False, "error": {"code": "NOT_FOUND_OR_FORBIDDEN"}}
    for payload in ({}, {"operation_id": ""}, {"operation_id": 7}, {"operation_id": "op-1", "extra": 1}, None):
        assert asyncio.run(handler(payload, _ctx())) == {"ok": False, "error": {"code": "INVALID_REQUEST"}}
    assert asyncio.run(handler({"operation_id": "op-1"}, None)) == {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
    assert asyncio.run(EvolvedSkills(None).version({"operation_id": "op-1"}, _ctx())) == {"ok": False, "error": {"code": "UNAVAILABLE"}}


def test_annotations_roundtrip_per_owner_and_skill(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    store.save_annotation(owner="user-1", skill_name="demo-evolution", run_id="run-1", event_id="42", note="first note")
    store.save_annotation(owner="user-1", skill_name="demo-evolution", run_id="run-1", event_id="43", note="second note")
    store.save_annotation(owner="user-2", skill_name="demo-evolution", run_id="run-1", event_id="42", note="other owner")
    store.save_annotation(owner="user-1", skill_name="other-skill", run_id="run-1", event_id="42", note="other skill")
    listed = store.list_annotations(owner="user-1", skill_name="demo-evolution")
    assert {(row["run_id"], row["event_id"], row["note"]) for row in listed} == {
        ("run-1", "42", "first note"),
        ("run-1", "43", "second note"),
    }
    # Upsert replaces the note in place.
    store.save_annotation(owner="user-1", skill_name="demo-evolution", run_id="run-1", event_id="42", note="updated")
    assert {(row["event_id"], row["note"]) for row in store.list_annotations(owner="user-1", skill_name="demo-evolution")} == {
        ("42", "updated"),
        ("43", "second note"),
    }
    # Delete is scoped and reports whether a row existed.
    assert store.delete_annotation(owner="user-1", skill_name="demo-evolution", run_id="run-1", event_id="42") is True
    assert store.delete_annotation(owner="user-1", skill_name="demo-evolution", run_id="run-1", event_id="42") is False
    assert store.delete_annotation(owner="user-2", skill_name="demo-evolution", run_id="run-1", event_id="42") is True
    assert store.list_annotations(owner="user-1", skill_name="demo-evolution")[0]["event_id"] == "43"


def test_annotations_reject_bad_rows(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    with pytest.raises(ValueError, match="note"):
        store.save_annotation(owner="user-1", skill_name="demo-evolution", run_id="run-1", event_id="42", note="")
    with pytest.raises(ValueError, match="note"):
        store.save_annotation(owner="user-1", skill_name="demo-evolution", run_id="run-1", event_id="42", note="x" * 2001)
    with pytest.raises(ValueError, match="bounded"):
        store.save_annotation(owner="", skill_name="demo-evolution", run_id="run-1", event_id="42", note="ok")
    with pytest.raises(ValueError, match="bounded"):
        store.save_annotation(owner="user-1", skill_name="demo-evolution", run_id="run-1", event_id="bad\nid", note="ok")


def test_evolution_job_roundtrip(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    assert store.start_job(owner="user-1", skill_name="demo-evolution", job_id="job-1", base_content="# Demo", feedback_count=2)
    # At most one running job per (owner, skill); other skills are unaffected.
    assert store.start_job(owner="user-1", skill_name="demo-evolution", job_id="job-2", base_content="# Demo", feedback_count=0) is False
    assert store.start_job(owner="user-2", skill_name="demo-evolution", job_id="job-3", base_content="# Demo", feedback_count=0)
    # finish_job is CAS-fenced: only a running job can be terminal-written.
    assert store.finish_job(owner="user-1", job_id="job-1", status="succeeded", result_content="# New", resolved_model="m", input_tokens=1, output_tokens=2)
    assert store.finish_job(owner="user-1", job_id="job-1", status="failed", error_code="INTERNAL") is False
    latest = store.latest_job(owner="user-1", skill_name="demo-evolution")
    assert latest is not None
    assert latest["job_id"] == "job-1"
    assert latest["status"] == "succeeded"
    assert latest["result_content"] == "# New"
    assert latest["resolved_model"] == "m"
    assert latest["feedback_count"] == 2
    # After the terminal write a new job may run again.
    assert store.start_job(owner="user-1", skill_name="demo-evolution", job_id="job-4", base_content="# New", feedback_count=0)
    assert store.latest_job(owner="user-1", skill_name="demo-evolution")["job_id"] == "job-4"
    # latest_job is owner-scoped and skill-scoped.
    assert store.latest_job(owner="user-2", skill_name="demo-evolution")["job_id"] == "job-3"
    assert store.latest_job(owner="user-1", skill_name="other-skill") is None
    # delete_job is owner-scoped.
    assert store.delete_job(owner="user-1", job_id="job-4") is True
    assert store.delete_job(owner="user-1", job_id="job-4") is False
    assert store.delete_job(owner="user-2", job_id="job-3") is True


def test_evolution_jobs_prune_to_a_bounded_history(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    for index in range(12):
        job_id = f"job-{index:02d}"
        assert store.start_job(owner="user-1", skill_name="demo-evolution", job_id=job_id, base_content="# Demo", feedback_count=0)
        assert store.finish_job(owner="user-1", job_id=job_id, status="failed", error_code="MODEL_FAILED")
    with closing(store.connect()) as db:
        count = db.execute("SELECT COUNT(*) FROM evolution_jobs WHERE owner='user-1' AND skill_name='demo-evolution'").fetchone()[0]
    assert count == store._JOB_KEEP
    assert store.latest_job(owner="user-1", skill_name="demo-evolution")["job_id"] == "job-11"


def test_evolution_job_fields_are_validated(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    with pytest.raises(ValueError, match="bounded"):
        store.start_job(owner="", skill_name="demo-evolution", job_id="job-1", base_content="# Demo", feedback_count=0)
    with pytest.raises(ValueError, match="content"):
        store.start_job(owner="user-1", skill_name="demo-evolution", job_id="job-1", base_content="", feedback_count=0)
    with pytest.raises(ValueError, match="feedback_count"):
        store.start_job(owner="user-1", skill_name="demo-evolution", job_id="job-1", base_content="# Demo", feedback_count=-1)
    with pytest.raises(ValueError, match="status"):
        store.finish_job(owner="user-1", job_id="job-1", status="running")
