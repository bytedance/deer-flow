"""Service lifecycle, pagination and bounds against a contract-shaped fake host."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from deerflow_extension_api import CompletedRunEvent, CompletedRunEventPage, CompletedRunSnapshot, EvidenceLimits, ExtensionRuntimeDeps
from deerflow_extension_api.run_evidence import RunPage

from deerflow_extension_run_postmortem.service import PostmortemError, PostmortemService


def event(seq: int, event_type: str = "run.start") -> CompletedRunEvent:
    return CompletedRunEvent(event_id=f"e{seq}", seq=seq, event_type=event_type, category="trace", content_json=json.dumps({"status": "ok"}), content_bytes=2, content_sha256="")


def snapshot(owner: str = "alice") -> CompletedRunSnapshot:
    return CompletedRunSnapshot(snapshot_ref="snap", evidence_revision="rev", thread_id="t1", run_id="r1", owner_id=owner, agent_id="lead_agent", origin="interactive", status="success", seal_state="sealed", event_count=2)


class FakeEvidence:
    """Cursor-addressed pages; every call is recorded for assertion."""

    def __init__(self, pages: dict[str | None, CompletedRunEventPage] | None = None, snap: CompletedRunSnapshot | None = None) -> None:
        self.pages = pages or {None: CompletedRunEventPage(items=(event(1), event(2)))}
        self.snap = snap or snapshot()
        self.read_cursors: list[str | None] = []
        self.snapshot_limits: EvidenceLimits | None = None

    async def list_changed_runs(self, *, cursor: str | None = None, limit: int = 200) -> RunPage:
        return RunPage(items=())

    async def get_snapshot(self, *, thread_id: str, run_id: str, limits: EvidenceLimits = EvidenceLimits()) -> CompletedRunSnapshot:
        self.snapshot_limits = limits
        return self.snap

    async def read_events(self, *, snapshot_ref: str, cursor: str | None = None, limits: EvidenceLimits = EvidenceLimits()) -> CompletedRunEventPage:
        self.read_cursors.append(cursor)
        return self.pages.get(cursor, CompletedRunEventPage())


async def test_start_requires_the_evidence_capability():
    service = PostmortemService()

    with pytest.raises(PostmortemError) as excinfo:
        await service.start(ExtensionRuntimeDeps())

    assert excinfo.value.code == "NOT_GRANTED"
    assert "host_access.evidence" in str(excinfo.value)


async def test_requests_before_start_are_refused():
    service = PostmortemService()

    with pytest.raises(PostmortemError) as excinfo:
        await service.postmortem(thread_id="t1", run_id="r1")

    assert excinfo.value.code == "NOT_GRANTED"


async def test_pages_are_followed_until_the_host_stops():
    evidence = FakeEvidence(
        pages={
            None: CompletedRunEventPage(items=(event(1), event(2)), next_cursor="c2", has_more=True),
            "c2": CompletedRunEventPage(items=(event(3),), next_cursor=None, has_more=False),
        }
    )
    service = PostmortemService()
    await service.start(ExtensionRuntimeDeps(completed_run_evidence=evidence))

    postmortem = await service.postmortem(thread_id="t1", run_id="r1", max_events=20)

    assert [entry.seq for entry in postmortem.timeline] == [1, 2, 3]
    assert evidence.read_cursors == [None, "c2"]
    assert evidence.snapshot_limits == EvidenceLimits(max_events=20)


async def test_a_repeated_cursor_cannot_spin_the_request():
    evidence = FakeEvidence(
        pages={
            None: CompletedRunEventPage(items=(event(1),), next_cursor="same", has_more=True),
            "same": CompletedRunEventPage(items=(event(2),), next_cursor="same", has_more=True),
        }
    )
    service = PostmortemService()
    await service.start(ExtensionRuntimeDeps(completed_run_evidence=evidence))

    postmortem = await service.postmortem(thread_id="t1", run_id="r1", max_events=20)

    assert [entry.seq for entry in postmortem.timeline] == [1, 2]
    assert evidence.read_cursors == [None, "same"]


async def test_max_events_caps_the_read():
    evidence = FakeEvidence(
        pages={
            None: CompletedRunEventPage(items=(event(1), event(2)), next_cursor="c2", has_more=True),
            "c2": CompletedRunEventPage(items=(event(3), event(4)), next_cursor=None, has_more=False),
        }
    )
    service = PostmortemService()
    await service.start(ExtensionRuntimeDeps(completed_run_evidence=evidence))

    postmortem = await service.postmortem(thread_id="t1", run_id="r1", max_events=3)

    assert [entry.seq for entry in postmortem.timeline] == [1, 2, 3]


@pytest.mark.parametrize("max_events", [0, -1, 5000])
async def test_max_events_is_bounded(max_events: int):
    service = PostmortemService()
    await service.start(ExtensionRuntimeDeps(completed_run_evidence=FakeEvidence()))

    with pytest.raises(PostmortemError) as excinfo:
        await service.postmortem(thread_id="t1", run_id="r1", max_events=max_events)

    assert excinfo.value.code == "BAD_REQUEST"


class TwoRunEvidence:
    """Per-run snapshots and event pages keyed by snapshot ref."""

    def __init__(self) -> None:
        self.snapshots = {
            "base": CompletedRunSnapshot(snapshot_ref="snap-base", thread_id="t1", run_id="base", owner_id="alice", status="success", seal_state="sealed", event_count=1),
            "head": CompletedRunSnapshot(snapshot_ref="snap-head", thread_id="t1", run_id="head", owner_id="alice", status="error", seal_state="sealed", event_count=2),
        }
        self.pages = {
            "snap-base": CompletedRunEventPage(items=(event(1, "run.start"),)),
            "snap-head": CompletedRunEventPage(items=(event(1, "run.start"), event(2, "run.error"))),
        }

    async def list_changed_runs(self, *, cursor: str | None = None, limit: int = 200) -> RunPage:
        return RunPage(items=())

    async def get_snapshot(self, *, thread_id: str, run_id: str, limits: EvidenceLimits = EvidenceLimits()) -> CompletedRunSnapshot:
        return self.snapshots[run_id]

    async def read_events(self, *, snapshot_ref: str, cursor: str | None = None, limits: EvidenceLimits = EvidenceLimits()) -> CompletedRunEventPage:
        return self.pages[snapshot_ref]


async def test_comparison_reads_both_runs():
    service = PostmortemService()
    await service.start(ExtensionRuntimeDeps(completed_run_evidence=TwoRunEvidence()))

    comparison = await service.comparison(thread_id="t1", base_run_id="base", head_run_id="head")

    assert comparison.base.status == "success"
    assert comparison.head.status == "error"
    assert comparison.status_changed is True
    assert [metric.name for metric in comparison.metrics][:2] == ["events", "user_messages"]


class ChangingEvidence(TwoRunEvidence):
    """Completes the run between reads, as a real seal can."""

    def __init__(self) -> None:
        super().__init__()
        self.snapshots["base"] = replace(self.snapshots["base"], status="running")
        self.reads = 0

    async def get_snapshot(self, *, thread_id: str, run_id: str, limits: EvidenceLimits = EvidenceLimits()) -> CompletedRunSnapshot:
        self.reads += 1
        snapshot = self.snapshots[run_id]
        return snapshot if self.reads == 1 else replace(snapshot, status="success")


async def test_comparison_of_the_same_run_reads_it_once():
    evidence = ChangingEvidence()
    service = PostmortemService()
    await service.start(ExtensionRuntimeDeps(completed_run_evidence=evidence))

    comparison = await service.comparison(thread_id="t1", base_run_id="base", head_run_id="base")

    assert evidence.reads == 1
    assert comparison.status_changed is False
    assert all(metric.delta == 0 for metric in comparison.metrics)
