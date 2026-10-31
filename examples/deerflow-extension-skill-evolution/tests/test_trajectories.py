import asyncio
import json
from types import SimpleNamespace

from deerflow_extension_skill_evolution.evolved import EvolvedSkillStore
from deerflow_extension_skill_evolution.service import CapabilityHandle
from deerflow_extension_skill_evolution.trajectories import SkillTrajectories


def _ctx(user_id: str = "user-1") -> SimpleNamespace:
    return SimpleNamespace(principal=SimpleNamespace(user_id=user_id))


def _snapshot(owner="user-1", sealed=True, origin="interactive", coverage="lead-journal-v1", ref="snap-1", thread_id="t-0", run_id="r-0", status="completed", event_count=3):
    return SimpleNamespace(
        snapshot_ref=ref if sealed else "",
        owner_id=owner,
        seal_state="sealed" if sealed else "partial",
        origin=origin,
        coverage=coverage,
        thread_id=thread_id,
        run_id=run_id,
        status=status,
        event_count=event_count,
    )


def _event(seq, event_type, content=None, category=None, event_id=None):
    return SimpleNamespace(
        event_id=event_id if event_id is not None else f"e-{seq}",
        seq=seq,
        event_type=event_type,
        category=category or "middleware" if event_type.startswith("middleware:") else "message",
        content_json=json.dumps(content) if content is not None else "{}",
        metadata_json="{}",
        content_bytes=16,
        content_sha256="0" * 64,
        truncated=False,
    )


def _activation(seq, skill="demo-evolution", event_id=None):
    return _event(
        seq,
        "middleware:skill_activation",
        {
            "name": "SkillActivationMiddleware",
            "hook": "before_model",
            "action": "activate",
            "changes": {"skill_name": skill, "category": "public", "path": f"/skills/{skill}/SKILL.md", "content_hash": "a" * 64},
        },
        event_id=event_id,
    )


class FakeReader:
    """Snapshots are listed oldest-first; each carries its own event pages."""

    def __init__(self, runs, page_size=200):
        # runs: list of (RunStatusView-like, snapshot, [event pages])
        self._runs = runs
        self._page_size = page_size
        self.read_events_calls = []

    async def list_changed_runs(self, *, cursor=None, limit=200):
        # Oldest-first by change_seq; the cursor is the offset into the list.
        offset = 0 if cursor is None else int(cursor.split(":")[-1])
        window = self._runs[offset : offset + min(self._page_size, limit)]
        next_offset = offset + len(window)
        return SimpleNamespace(
            items=tuple(run[0] for run in window),
            next_cursor=f"runs:{next_offset}" if next_offset < len(self._runs) else None,
            has_more=next_offset < len(self._runs),
        )

    async def get_snapshot(self, *, thread_id, run_id):
        for status, snapshot, _ in self._runs:
            if snapshot.run_id == run_id:
                return snapshot
        return None

    async def read_events(self, *, snapshot_ref, cursor=None, limits=None):
        self.read_events_calls.append((snapshot_ref, cursor, limits))
        for _, snapshot, pages in self._runs:
            if snapshot.snapshot_ref == snapshot_ref:
                index = 0 if cursor is None else int(cursor.split(":")[-1])
                page = pages[index]
                return SimpleNamespace(items=page, next_cursor=f"events:{index + 1}" if index + 1 < len(pages) else None, has_more=index + 1 < len(pages))
        raise AssertionError(snapshot_ref)


def _status(run_id, thread_id="t-0", created_at="2026-10-01T00:00:00Z", stop_reason=None):
    return SimpleNamespace(thread_id=thread_id, run_id=run_id, status="completed", created_at=created_at, updated_at=created_at, error=None, stop_reason=stop_reason)


def _wired(reader, store=None):
    handle = CapabilityHandle()
    if reader is not None:
        handle.bind(reader)
    return SkillTrajectories(handle, store)


def test_list_requires_authentication_and_a_granted_reader(tmp_path) -> None:
    trajectories = _wired(None, EvolvedSkillStore(tmp_path / "evolved.sqlite"))
    assert asyncio.run(trajectories.list({}, None)) == {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
    assert asyncio.run(trajectories.list({"skill_name": "demo-evolution"}, _ctx())) == {"ok": False, "error": {"code": "UNAVAILABLE"}}


def test_list_validates_the_payload(tmp_path) -> None:
    trajectories = _wired(FakeReader([]), EvolvedSkillStore(tmp_path / "evolved.sqlite"))
    for payload in (None, {}, {"skill_name": "Demo"}, {"skill_name": "demo-evolution", "extra": 1}, {"skill_name": ""}):
        assert asyncio.run(trajectories.list(payload, _ctx())) == {"ok": False, "error": {"code": "INVALID_REQUEST"}}


def test_list_returns_matching_runs_newest_first_with_invocation_points(tmp_path) -> None:
    reader = FakeReader(
        [
            (_status("r-old", created_at="2026-09-01"), _snapshot(ref="snap-old", run_id="r-old", thread_id="t-old", event_count=2), [[_activation(1), _event(2, "llm.ai.response")]]),
            (_status("r-new", created_at="2026-10-01"), _snapshot(ref="snap-new", run_id="r-new", thread_id="t-new", event_count=2), [[_event(1, "llm.human.input"), _activation(2, event_id="e-2")]]),
            (_status("r-none", created_at="2026-10-02"), _snapshot(ref="snap-none", run_id="r-none", thread_id="t-none", event_count=1), [[_event(1, "llm.human.input")]]),
        ]
    )
    trajectories = _wired(reader, EvolvedSkillStore(tmp_path / "evolved.sqlite"))
    result = asyncio.run(trajectories.list({"skill_name": "demo-evolution"}, _ctx()))
    assert result["ok"] is True
    # Only runs that activated the skill are kept, newest first.
    assert [traj["run_id"] for traj in result["trajectories"]] == ["r-new", "r-old"]
    newest = result["trajectories"][0]
    assert newest["thread_id"] == "t-new"
    assert newest["created_at"] == "2026-10-01"
    assert newest["event_count"] == 2
    # The skeleton keeps event identity; only the activation carries detail.
    assert [event["invocation"] for event in newest["events"]] == [False, True]
    assert newest["events"][1]["detail"]["skill_name"] == "demo-evolution"
    assert newest["events"][1]["detail"]["path"] == "/skills/demo-evolution/SKILL.md"
    assert all(event["detail"] is None for event in newest["events"][:1])
    assert newest["annotations"] == []


def test_list_is_scoped_to_the_caller_and_skips_foreign_or_unsealed_runs(tmp_path) -> None:
    reader = FakeReader(
        [
            (_status("r-foreign"), _snapshot(owner="user-2", ref="snap-foreign", run_id="r-foreign"), [[_activation(1)]]),
            (_status("r-partial"), _snapshot(sealed=False, ref="snap-partial", run_id="r-partial"), [[_activation(1)]]),
            (_status("r-api"), _snapshot(origin="api", ref="snap-api", run_id="r-api"), [[_activation(1)]]),
            (_status("r-mine"), _snapshot(ref="snap-mine", run_id="r-mine"), [[_activation(1)]]),
        ]
    )
    trajectories = _wired(reader, EvolvedSkillStore(tmp_path / "evolved.sqlite"))
    result = asyncio.run(trajectories.list({"skill_name": "demo-evolution"}, _ctx()))
    assert result["ok"] is True
    assert [traj["run_id"] for traj in result["trajectories"]] == ["r-mine"]


def test_list_continues_paging_within_the_timeline_budget(tmp_path) -> None:
    pages = [[_event(i, "llm.tool.result") for i in range(1, 4)], [_activation(4)], [_activation(5)]]
    reader = FakeReader([(_status("r-1"), _snapshot(ref="snap-1", run_id="r-1", event_count=5), pages)])
    trajectories = _wired(reader, EvolvedSkillStore(tmp_path / "evolved.sqlite"))
    result = asyncio.run(trajectories.list({"skill_name": "demo-evolution"}, _ctx()))
    assert result["ok"] is True
    assert [call[1] for call in reader.read_events_calls] == [None, "events:1", "events:2"]
    # Small timelines retain all visible context, even across three pages.
    (traj,) = result["trajectories"]
    assert [event["seq"] for event in traj["events"]] == [1, 2, 3, 4, 5]


def test_list_stops_after_three_matching_trajectories(tmp_path) -> None:
    runs = [(_status(f"r-{index}", created_at=f"2026-10-0{index + 1}"), _snapshot(ref=f"snap-{index}", run_id=f"r-{index}", thread_id=f"t-{index}"), [[_activation(1)]]) for index in range(5)]
    reader = FakeReader(runs)
    trajectories = _wired(reader, EvolvedSkillStore(tmp_path / "evolved.sqlite"))
    result = asyncio.run(trajectories.list({"skill_name": "demo-evolution"}, _ctx()))
    assert [traj["run_id"] for traj in result["trajectories"]] == ["r-4", "r-3", "r-2"]


def test_list_pages_past_the_first_changed_runs_page(tmp_path) -> None:
    # The changed-runs feed is oldest-first: the newest runs (the ones that
    # actually activated the skill) sit on the LAST page, so the scan must
    # follow the cursor instead of stopping after the first page.
    runs = [(_status(f"r-old-{index}", created_at=f"2026-09-0{index + 1}"), _snapshot(ref=f"snap-old-{index}", run_id=f"r-old-{index}", thread_id=f"t-old-{index}"), [[_event(1, "llm.human.input")]]) for index in range(3)]
    runs.append((_status("r-new", created_at="2026-10-01"), _snapshot(ref="snap-new", run_id="r-new", thread_id="t-new"), [[_activation(1)]]))
    reader = FakeReader(runs, page_size=2)
    trajectories = _wired(reader, EvolvedSkillStore(tmp_path / "evolved.sqlite"))
    result = asyncio.run(trajectories.list({"skill_name": "demo-evolution"}, _ctx()))
    assert result["ok"] is True
    assert [traj["run_id"] for traj in result["trajectories"]] == ["r-new"]


def test_list_renders_readable_previews_and_filters_noise(tmp_path) -> None:
    events = [
        _event(1, "run.start", {"chain": "unknown"}),
        _event(2, "llm.human.input", {"content": [{"type": "text", "text": "@demo-evolution 帮我继续测试\n第二行"}]}),
        _event(3, "llm.ai.response", {"content": ""}),
        _event(4, "llm.ai.response", {"content": "计划分三步：先验证 write_file，再测 remove_file。"}),
        _event(5, "llm.tool.result", {"content": "Wrote 'references/mutation-log.md' for custom skill 'demo-evolution'.", "name": "skill_manage"}),
        _event(6, "context:memory", {"content_sha256": "x" * 64}),
        _activation(7),
    ]
    reader = FakeReader([(_status("r-1"), _snapshot(ref="snap-1", run_id="r-1", event_count=7), [events])])
    trajectories = _wired(reader, EvolvedSkillStore(tmp_path / "evolved.sqlite"))
    result = asyncio.run(trajectories.list({"skill_name": "demo-evolution"}, _ctx()))
    (traj,) = result["trajectories"]
    # System noise and textless model turns are dropped; the rest carry a
    # kind, an optional tool label and a bounded preview of the caller's own
    # content so the timeline is readable for annotation.
    assert [(event["kind"], event["label"]) for event in traj["events"]] == [
        ("human", None),
        ("ai", None),
        ("tool", "skill_manage"),
        ("activation", None),
    ]
    previews = [event["preview"] for event in traj["events"]]
    assert previews[0] == "@demo-evolution 帮我继续测试 第二行"
    assert previews[1] == "计划分三步：先验证 write_file，再测 remove_file。"
    assert previews[2].startswith("Wrote 'references/mutation-log.md'")
    assert previews[3] is None


def test_previews_are_bounded_excerpts(tmp_path) -> None:
    events = [
        _event(1, "llm.human.input", {"content": [{"type": "text", "text": "  word " * 200}]}),
        _activation(2),
    ]
    reader = FakeReader([(_status("r-1"), _snapshot(ref="snap-1", run_id="r-1", event_count=2), [events])])
    trajectories = _wired(reader, EvolvedSkillStore(tmp_path / "evolved.sqlite"))
    result = asyncio.run(trajectories.list({"skill_name": "demo-evolution"}, _ctx()))
    (traj,) = result["trajectories"]
    (human, _activation_event) = traj["events"]
    # Whitespace is collapsed and the excerpt capped at 200 chars + ellipsis.
    assert 199 <= len(human["preview"]) <= 201
    assert human["preview"].endswith("…")
    assert "\n" not in human["preview"]


def test_list_joins_the_caller_annotations(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    store.save_annotation(owner="user-1", skill_name="demo-evolution", run_id="r-1", event_id="e-2", note="checked")
    store.save_annotation(owner="user-2", skill_name="demo-evolution", run_id="r-1", event_id="e-2", note="foreign")
    reader = FakeReader([(_status("r-1"), _snapshot(ref="snap-1", run_id="r-1"), [[_activation(1, event_id="e-1"), _activation(2, event_id="e-2")]])])
    trajectories = _wired(reader, store)
    result = asyncio.run(trajectories.list({"skill_name": "demo-evolution"}, _ctx()))
    (traj,) = result["trajectories"]
    assert traj["annotations"] == [{"run_id": "r-1", "event_id": "e-2", "note": "checked", "updated_at": traj["annotations"][0]["updated_at"]}]


def test_list_works_without_storage_but_annotate_is_unavailable() -> None:
    reader = FakeReader([(_status("r-1"), _snapshot(ref="snap-1", run_id="r-1"), [[_activation(1)]])])
    trajectories = _wired(reader, None)
    result = asyncio.run(trajectories.list({"skill_name": "demo-evolution"}, _ctx()))
    assert result["ok"] is True
    assert result["trajectories"][0]["annotations"] == []
    assert asyncio.run(trajectories.annotate({"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1", "note": "n"}, _ctx())) == {"ok": False, "error": {"code": "UNAVAILABLE"}}
    assert asyncio.run(trajectories.unannotate({"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1"}, _ctx())) == {"ok": False, "error": {"code": "UNAVAILABLE"}}


def _annotation_reader(owner="user-1", run_id="r-1"):
    return FakeReader([(_status(run_id), _snapshot(run_id=run_id, owner=owner), [[_activation(1)]])])


def test_annotate_persists_and_unannotate_removes(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    trajectories = _wired(_annotation_reader(), store)
    payload = {"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1", "note": "first"}
    assert asyncio.run(trajectories.annotate(payload, _ctx())) == {"ok": True}
    assert [(row["run_id"], row["event_id"], row["note"]) for row in store.list_annotations(owner="user-1", skill_name="demo-evolution")] == [("r-1", "e-1", "first")]
    assert asyncio.run(trajectories.annotate({**payload, "note": "second"}, _ctx())) == {"ok": True}
    listed = store.list_annotations(owner="user-1", skill_name="demo-evolution")
    assert len(listed) == 1 and listed[0]["note"] == "second"
    assert asyncio.run(trajectories.unannotate({"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1"}, _ctx())) == {"ok": True}
    assert store.list_annotations(owner="user-1", skill_name="demo-evolution") == []


def test_annotation_actions_validate_payloads_and_identity(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    trajectories = _wired(None, store)
    for payload in (
        None,
        {},
        {"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1"},
        {"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1", "note": ""},
        {"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1", "note": "x" * 2001},
        {"skill_name": "Demo", "run_id": "r-1", "event_id": "e-1", "note": "ok"},
        {"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1", "note": "ok", "extra": 1},
    ):
        assert asyncio.run(trajectories.annotate(payload, _ctx())) == {"ok": False, "error": {"code": "INVALID_REQUEST"}}
    for payload in (None, {}, {"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1", "note": "x"}):
        assert asyncio.run(trajectories.unannotate(payload, _ctx())) == {"ok": False, "error": {"code": "INVALID_REQUEST"}}
    assert asyncio.run(trajectories.annotate({"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1", "note": "ok"}, None)) == {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
    assert asyncio.run(trajectories.unannotate({"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1"}, None)) == {"ok": False, "error": {"code": "UNAUTHENTICATED"}}


def test_annotation_notes_are_owner_scoped(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    trajectories = _wired(_annotation_reader(), store)
    payload = {"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1", "note": "mine"}
    assert asyncio.run(trajectories.annotate(payload, _ctx("user-1"))) == {"ok": True}
    other = _wired(_annotation_reader(owner="user-2", run_id="r-2"), store)
    assert asyncio.run(other.annotate({**payload, "run_id": "r-2", "note": "theirs"}, _ctx("user-2"))) == {"ok": True}
    assert [row["note"] for row in store.list_annotations(owner="user-1", skill_name="demo-evolution")] == ["mine"]
    assert [row["note"] for row in store.list_annotations(owner="user-2", skill_name="demo-evolution")] == ["theirs"]
    assert asyncio.run(trajectories.unannotate({"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1"}, _ctx("user-1"))) == {"ok": True}
    assert store.list_annotations(owner="user-1", skill_name="demo-evolution") == []
    assert [row["note"] for row in store.list_annotations(owner="user-2", skill_name="demo-evolution")] == ["theirs"]


def _seed_job(store: EvolvedSkillStore, *, status: str, content: str = "# Improved\n") -> None:
    assert store.start_job(owner="user-1", skill_name="demo-evolution", job_id="job-1", base_content="# Base", feedback_count=0)
    store.finish_job(owner="user-1", job_id="job-1", status=status, result_content=content if status == "succeeded" else None, error_code=None if status == "succeeded" else "MODEL_FAILED")


def _seed_commit(store: EvolvedSkillStore, content: str, operation_id: str) -> None:
    store.record_stage(owner="user-1", proposal_id=f"prop-{operation_id}", name="demo-evolution", content=content)
    store.record_outcome(owner="user-1", name="demo-evolution", method="commit", operation_id=operation_id, proposal_id=f"prop-{operation_id}")


def test_annotate_auto_clears_a_published_evolution_job(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    trajectories = _wired(_annotation_reader(), store)
    _seed_job(store, status="succeeded", content="# Improved\n")
    _seed_commit(store, "# Improved", "op-1")
    assert store.job_is_published(owner="user-1", name="demo-evolution", job=store.latest_job(owner="user-1", skill_name="demo-evolution")) is True
    # Saving an annotation (new or edited) supersedes the consumed draft:
    # the job record disappears and the panel returns to the trigger state.
    assert asyncio.run(trajectories.annotate({"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1", "note": "again"}, _ctx())) == {"ok": True}
    assert store.latest_job(owner="user-1", skill_name="demo-evolution") is None
    # The annotation itself and the version journal are untouched.
    assert [row["note"] for row in store.list_annotations(owner="user-1", skill_name="demo-evolution")] == ["again"]
    assert store.latest_committed_content(owner="user-1", name="demo-evolution") == "# Improved"


def test_annotate_auto_clears_an_unchanged_evolution_job(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    trajectories = _wired(_annotation_reader(), store)
    # The model returned the input content unchanged: consumed like a
    # published draft, so a fresh annotation returns to the trigger state.
    _seed_job(store, status="succeeded", content="# Base")
    job = store.latest_job(owner="user-1", skill_name="demo-evolution")
    assert job is not None and store.job_is_unchanged(job) is True
    assert asyncio.run(trajectories.annotate({"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1", "note": "note"}, _ctx())) == {"ok": True}
    assert store.latest_job(owner="user-1", skill_name="demo-evolution") is None


def test_annotate_keeps_pending_and_failed_jobs(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "evolved.sqlite")
    trajectories = _wired(_annotation_reader(), store)
    # A succeeded draft that was NOT published yet stays for review.
    _seed_job(store, status="succeeded", content="# Pending draft\n")
    assert asyncio.run(trajectories.annotate({"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1", "note": "note"}, _ctx())) == {"ok": True}
    assert store.latest_job(owner="user-1", skill_name="demo-evolution") is not None
    # So does a failed job (it still shows its error code).
    store.delete_job(owner="user-1", job_id="job-1")
    _seed_job(store, status="failed")
    assert asyncio.run(trajectories.annotate({"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1", "note": "note"}, _ctx())) == {"ok": True}
    job = store.latest_job(owner="user-1", skill_name="demo-evolution")
    assert job is not None and job["status"] == "failed"


def test_recent_trajectories_are_on_the_final_page_even_with_many_old_runs(tmp_path):
    runs = [(_status(f"r-{i}"), _snapshot(ref=f"snap-{i}", run_id=f"r-{i}"), [[_activation(1)]]) for i in range(80)]
    reader = FakeReader(runs, page_size=30)
    result = asyncio.run(_wired(reader, EvolvedSkillStore(tmp_path / "evolved.sqlite")).list({"skill_name": "demo-evolution"}, _ctx()))
    assert result["ok"]
    assert [traj["run_id"] for traj in result["trajectories"]] == ["r-79", "r-78", "r-77"]
    assert len(reader.read_events_calls) == 3


def test_list_discovers_late_activation_and_bounds_the_returned_timeline(tmp_path):
    pages = [[_event(i, "llm.tool.result", {"content": str(i)}) for i in range(start, start + 100)] for start in (1, 101, 201, 301)]
    pages[2][49] = _activation(250)
    reader = FakeReader([(_status("long"), _snapshot(run_id="long", event_count=400), pages)])
    store = EvolvedSkillStore(tmp_path / "window.sqlite")
    store.save_annotation(owner="user-1", skill_name="demo-evolution", run_id="long", event_id="e-1", note="outside window")
    store.save_annotation(owner="user-1", skill_name="demo-evolution", run_id="long", event_id="e-250", note="visible")
    result = asyncio.run(_wired(reader, store).list({"skill_name": "demo-evolution"}, _ctx()))
    assert result["ok"]
    (trajectory,) = result["trajectories"]
    assert trajectory["timeline_truncated"]
    assert [note["event_id"] for note in trajectory["annotations"]] == ["e-250"]
    assert len(trajectory["events"]) <= 200
    assert any(event["seq"] == 250 and event["invocation"] for event in trajectory["events"])
    assert any(event["seq"] < 250 for event in trajectory["events"])
    assert any(event["seq"] > 250 for event in trajectory["events"])


def test_annotation_requires_matching_owned_evidence_before_any_write(tmp_path):
    cases = [
        ([], "e-2"),
        ([(_status("r-1"), _snapshot(run_id="r-1", owner="user-2"), [[_activation(1), _event(2, "llm.tool.result")]])], "e-2"),
        ([(_status("r-1"), _snapshot(run_id="r-1", sealed=False), [[_activation(1), _event(2, "llm.tool.result")]])], "e-2"),
        ([(_status("r-1"), _snapshot(run_id="r-1"), [[_activation(1)]])], "invented"),
        ([(_status("r-1"), _snapshot(run_id="r-1"), [[_activation(1, skill="other-skill"), _event(2, "llm.tool.result")]])], "e-2"),
        ([(_status("r-1"), _snapshot(run_id="r-1"), [[_activation(1), _event(2, "run.start")]])], "e-2"),
        ([(_status("r-1"), _snapshot(run_id="r-1"), [[_activation(1), _activation(2, skill="other-skill")]])], "e-2"),
    ]
    for index, (runs, event_id) in enumerate(cases):
        store = EvolvedSkillStore(tmp_path / f"invalid-{index}.sqlite")
        _seed_job(store, status="succeeded", content="# Base")
        result = asyncio.run(_wired(FakeReader(runs), store).annotate({"skill_name": "demo-evolution", "run_id": "r-1", "event_id": event_id, "note": "invented"}, _ctx()))
        assert result == {"ok": False, "error": {"code": "NOT_FOUND_OR_FORBIDDEN"}}
        assert store.list_annotations(owner="user-1", skill_name="demo-evolution") == []
        assert store.latest_job(owner="user-1", skill_name="demo-evolution") is not None


def test_annotation_validates_event_and_activation_across_pages(tmp_path):
    pages = [[_event(1, "llm.human.input", {"content": [{"text": "request"}]})], [_event(2, "llm.tool.result")], [_activation(3)]]
    reader = FakeReader([(_status("r-1"), _snapshot(run_id="r-1"), pages)])
    store = EvolvedSkillStore(tmp_path / "valid.sqlite")
    result = asyncio.run(_wired(reader, store).annotate({"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1", "note": "valid context"}, _ctx()))
    assert result == {"ok": True}
    assert len(reader.read_events_calls) == 3


def test_annotation_without_evidence_fails_closed(tmp_path):
    result = asyncio.run(_wired(None, EvolvedSkillStore(tmp_path / "none.sqlite")).annotate({"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1", "note": "invalid"}, _ctx()))
    assert result == {"ok": False, "error": {"code": "UNAVAILABLE"}}


def test_annotation_can_reference_a_late_event_outside_the_display_window(tmp_path):
    pages = [[_activation(1)], [_event(101, "llm.tool.result")], [_event(201, "llm.tool.result")]]
    reader = FakeReader([(_status("r-1"), _snapshot(run_id="r-1"), pages)])
    store = EvolvedSkillStore(tmp_path / "late.sqlite")
    assert asyncio.run(_wired(reader, store).annotate({"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-201", "note": "late"}, _ctx())) == {"ok": True}
    assert len(reader.read_events_calls) == 3


def test_annotation_finds_old_runs_beyond_the_recent_display_lookback(tmp_path):
    runs = [(_status("r-1"), _snapshot(run_id="r-1"), [[_activation(1)]])]
    runs.extend((_status(f"other-{i}"), _snapshot(run_id=f"other-{i}"), [[_activation(1)]]) for i in range(30))
    store = EvolvedSkillStore(tmp_path / "old.sqlite")
    result = asyncio.run(_wired(FakeReader(runs, page_size=1), store).annotate({"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1", "note": "old but valid"}, _ctx()))
    assert result == {"ok": True}


def test_event_scan_rejects_repeated_or_missing_cursors_and_never_writes(tmp_path):
    for cursor in (None, "", "repeat"):

        class Reader(FakeReader):
            async def read_events(self, **kwargs):
                return SimpleNamespace(items=[_event(1, "llm.tool.result")], next_cursor=cursor, has_more=True)

        reader = Reader([(_status("r-1"), _snapshot(run_id="r-1"), [])])
        store = EvolvedSkillStore(tmp_path / f"cursor-{cursor}.sqlite")
        trajectories = _wired(reader, store)
        assert asyncio.run(trajectories.list({"skill_name": "demo-evolution"}, _ctx())) == {"ok": False, "error": {"code": "UNAVAILABLE"}}
        assert asyncio.run(trajectories.annotate({"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1", "note": "no proof"}, _ctx())) == {"ok": False, "error": {"code": "UNAVAILABLE"}}
        assert store.list_annotations(owner="user-1", skill_name="demo-evolution") == []


def test_event_scan_budget_reports_incomplete_discovery_explicitly(tmp_path, monkeypatch):
    from deerflow_extension_skill_evolution import trajectories as module

    monkeypatch.setattr(module, "_MAX_EVENT_SCAN_PAGES", 2)
    pages = [[_event(1, "llm.tool.result")], [_event(2, "llm.tool.result")], [_activation(3)]]
    reader = FakeReader([(_status("r-1"), _snapshot(run_id="r-1"), pages)])
    store = EvolvedSkillStore(tmp_path / "quota.sqlite")
    trajectories = _wired(reader, store)
    assert asyncio.run(trajectories.list({"skill_name": "demo-evolution"}, _ctx())) == {"ok": False, "error": {"code": "QUOTA_EXCEEDED"}}
    assert asyncio.run(trajectories.annotate({"skill_name": "demo-evolution", "run_id": "r-1", "event_id": "e-1", "note": "unproven"}, _ctx())) == {"ok": False, "error": {"code": "QUOTA_EXCEEDED"}}
    assert store.list_annotations(owner="user-1", skill_name="demo-evolution") == []
