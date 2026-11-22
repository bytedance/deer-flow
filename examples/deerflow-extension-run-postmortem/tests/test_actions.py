"""Browser actions: shared derivation, owner binding and result sentinels."""

from __future__ import annotations

import json

import pytest
from deerflow_extension_api import CompletedRunEvent, CompletedRunEventPage, CompletedRunSnapshot, EvidenceLimits, ExtensionPrincipal, ExtensionRuntimeDeps
from deerflow_extension_api.plugins import ActionContext
from deerflow_extension_api.run_evidence import RunPage, RunStatusView

from deerflow_extension_run_postmortem.service import PostmortemService, build_actions


def snapshot(*, run_id: str = "r1", owner: str = "alice", status: str = "success") -> CompletedRunSnapshot:
    return CompletedRunSnapshot(snapshot_ref=f"snap-{run_id}", thread_id="t1", run_id=run_id, owner_id=owner, agent_id="lead_agent", origin="interactive", status=status, seal_state="sealed", event_count=1)


class FakeEvidence:
    def __init__(self, *, runs: tuple[RunStatusView, ...] = (), snapshots: dict[str, CompletedRunSnapshot] | None = None, run_pages: dict[str | None, RunPage] | None = None) -> None:
        self.runs = runs
        self.run_pages = run_pages
        self.run_calls: list[str | None] = []
        self.snapshots = snapshots or {"r1": snapshot()}

    async def list_changed_runs(self, *, cursor: str | None = None, limit: int = 200) -> RunPage:
        self.run_calls.append(cursor)
        if self.run_pages is not None:
            return self.run_pages.get(cursor, RunPage(items=(), next_cursor=None, has_more=False))
        return RunPage(items=self.runs, next_cursor=None, has_more=False)

    async def get_snapshot(self, *, thread_id: str, run_id: str, limits: EvidenceLimits = EvidenceLimits()) -> CompletedRunSnapshot:
        return self.snapshots[run_id]

    async def read_events(self, *, snapshot_ref: str, cursor: str | None = None, limits: EvidenceLimits = EvidenceLimits()) -> CompletedRunEventPage:
        if cursor is not None:
            return CompletedRunEventPage()
        return CompletedRunEventPage(items=(CompletedRunEvent(event_id="e1", seq=1, event_type="run.start", category="trace", content_json=json.dumps({"status": "running"}), content_bytes=0, content_sha256=""),))


async def service_with(evidence: FakeEvidence) -> tuple[PostmortemService, tuple]:
    service = PostmortemService()
    await service.start(ExtensionRuntimeDeps(completed_run_evidence=evidence))
    return service, build_actions(service)


def actions_by_name(actions: tuple) -> dict:
    return {action.name: action.handler for action in actions}


def user(name: str) -> ActionContext:
    return ActionContext(ExtensionPrincipal(name), {})


async def test_report_action_serves_the_same_derivation_as_the_route():
    _, actions = await service_with(FakeEvidence())

    report = await actions_by_name(actions)["report"]({"thread_id": "t1", "run_id": "r1", "max_events": 50}, user("alice"))

    assert report["run_id"] == "r1"
    assert report["verdict"] == "Run completed successfully."
    assert [item["event_type"] for item in report["timeline"]] == ["run.start"]


async def test_markdown_action_returns_a_downloadable_document():
    _, actions = await service_with(FakeEvidence())

    document = await actions_by_name(actions)["markdown"]({"thread_id": "t1", "run_id": "r1"}, user("alice"))

    assert document["filename"] == "postmortem-r1.md"
    assert document["markdown"].startswith("# Run postmortem — `r1`")


@pytest.mark.parametrize("action_name", ["report", "markdown"])
async def test_another_owners_run_answers_not_found(action_name: str):
    _, actions = await service_with(FakeEvidence(snapshots={"r1": snapshot(owner="bob")}))

    result = await actions_by_name(actions)[action_name]({"thread_id": "t1", "run_id": "r1"}, user("alice"))

    assert result == {"not_found": True}


async def test_latest_run_skips_runs_the_caller_does_not_own():
    evidence = FakeEvidence(
        runs=(
            RunStatusView(thread_id="t1", run_id="old", status="success"),
            RunStatusView(thread_id="t1", run_id="theirs", status="success"),
            RunStatusView(thread_id="t1", run_id="new", status="error"),
            RunStatusView(thread_id="other", run_id="elsewhere", status="success"),
        ),
        snapshots={"old": snapshot(run_id="old"), "theirs": snapshot(run_id="theirs", owner="bob"), "new": snapshot(run_id="new", status="error")},
    )
    _, actions = await service_with(evidence)

    result = await actions_by_name(actions)["latest"]({"thread_id": "t1"}, user("alice"))

    assert result == {"run": {"run_id": "new", "status": "error", "updated_at": ""}, "complete": True, "scanned": 4}


async def test_latest_run_answers_none_when_the_thread_has_no_owned_run():
    evidence = FakeEvidence(
        runs=(RunStatusView(thread_id="t1", run_id="theirs", status="success"),),
        snapshots={"theirs": snapshot(run_id="theirs", owner="bob")},
    )
    _, actions = await service_with(evidence)

    assert await actions_by_name(actions)["latest"]({"thread_id": "t1"}, user("alice")) == {"run": None, "complete": True, "scanned": 1}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"thread_id": "", "run_id": "r1"},
        {"thread_id": "t1", "run_id": "r1", "max_events": 0},
        {"thread_id": "t1", "run_id": "r1", "max_events": "many"},
        {"thread_id": "t1" * 200, "run_id": "r1"},
    ],
    ids=["missing", "blank-thread", "zero-events", "non-numeric-events", "oversized-thread"],
)
async def test_invalid_action_payloads_are_refused(payload: dict):
    _, actions = await service_with(FakeEvidence())

    with pytest.raises(ValueError):
        await actions_by_name(actions)["report"](payload, user("alice"))


async def test_latest_run_follows_the_feed_to_its_end():
    evidence = FakeEvidence(
        run_pages={
            None: RunPage(items=(RunStatusView(thread_id="t1", run_id="old", status="success"),), next_cursor="c2", has_more=True),
            "c2": RunPage(items=(RunStatusView(thread_id="t1", run_id="new", status="error"),), next_cursor=None, has_more=False),
        },
        snapshots={"old": snapshot(run_id="old"), "new": snapshot(run_id="new", status="error")},
    )
    _, actions = await service_with(evidence)

    result = await actions_by_name(actions)["latest"]({"thread_id": "t1"}, user("alice"))

    assert result == {"run": {"run_id": "new", "status": "error", "updated_at": ""}, "complete": True, "scanned": 2}
    assert evidence.run_calls == [None, "c2"]


async def test_an_unscanned_feed_never_reports_an_older_run_as_latest():
    # The feed is ordered across every thread in the grant, so a run beyond the
    # scan bound may be newer than anything this thread showed.
    evidence = FakeEvidence(
        run_pages={
            None: RunPage(items=(RunStatusView(thread_id="t1", run_id="old", status="success"),), next_cursor="c2", has_more=True),
            "c2": RunPage(items=(RunStatusView(thread_id="t2", run_id="other", status="success"),), next_cursor="c3", has_more=True),
            "c3": RunPage(items=(RunStatusView(thread_id="t2", run_id="other-2", status="success"),), next_cursor="c4", has_more=True),
        },
        snapshots={"old": snapshot(run_id="old")},
    )
    _, actions = await service_with(evidence)

    result = await actions_by_name(actions)["latest"]({"thread_id": "t1"}, user("alice"))

    assert result == {"run": None, "complete": False, "scanned": 3}
    assert evidence.run_calls == [None, "c2", "c3"]
