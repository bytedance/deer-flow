"""Service lifecycle, pagination and bounds against a contract-shaped fake host."""

from __future__ import annotations

import json

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
