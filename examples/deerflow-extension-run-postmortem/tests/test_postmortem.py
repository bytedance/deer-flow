"""Pure derivation: persisted event shapes in, verdict and anomalies out."""

from __future__ import annotations

import json

from deerflow_extension_api import CompletedRunEvent, CompletedRunSnapshot

from deerflow_extension_run_postmortem.postmortem import build_postmortem, render_markdown, to_dict


def event(seq: int, event_type: str, category: str, content) -> CompletedRunEvent:
    return CompletedRunEvent(event_id=f"e{seq}", seq=seq, event_type=event_type, category=category, content_json=json.dumps(content), content_bytes=0, content_sha256="")


def snapshot(**overrides) -> CompletedRunSnapshot:
    base = {
        "snapshot_ref": "snap",
        "evidence_revision": "rev",
        "thread_id": "t1",
        "run_id": "r1",
        "owner_id": "alice",
        "agent_id": "lead_agent",
        "origin": "interactive",
        "status": "success",
        "seal_state": "sealed",
        "event_count": 0,
        "coverage_limits": ("No complete background subagent coverage.",),
    }
    base.update(overrides)
    return CompletedRunSnapshot(**base)


def test_success_run_reports_no_anomalies():
    postmortem = build_postmortem(
        snapshot(event_count=3),
        [
            event(1, "run.start", "trace", {"status": "running"}),
            event(2, "llm.human.input", "message", {"content": "write the report"}),
            event(3, "run.end", "outputs", {"status": "success"}),
        ],
    )

    assert postmortem.verdict == "Run completed successfully."
    assert postmortem.anomalies == ()
    assert postmortem.message_counts["user"] == 1
    assert postmortem.owner_id == "alice"
    assert postmortem.timeline[1].summary == "user: write the report"
    assert to_dict(postmortem)["verdict"] == "Run completed successfully."


def test_error_run_surfaces_every_failure_signal():
    events = [
        event(1, "run.start", "trace", {}),
        event(2, "llm.ai.response", "message", {"content": "", "tool_calls": [{"name": "present_files"}]}),
        event(3, "llm.tool.result", "message", {"name": "present_files", "content": "Error: only outputs can be presented"}),
        event(4, "middleware:guardrail", "middleware", {"message": "loop warning"}),
        event(5, "run.delivery", "outputs", {"satisfied": False, "presented": 0, "produced_paths": ["/mnt/user-data/outputs/report.md"]}),
        event(6, "run.error", "error", {"message": "Artifact delivery incomplete: no produced output artifact was presented"}),
    ]
    postmortem = build_postmortem(
        snapshot(status="error", stop_reason="recursion_capped", seal_state="partial", seal_error="journal flush interrupted", event_count=8),
        events,
    )

    codes = {anomaly.code for anomaly in postmortem.anomalies}
    assert {
        "evidence_partial",
        "run_failed",
        "run_or_model_errors",
        "guardrail_triggered",
        "delivery_incomplete",
        "tool_failures",
        "stopped_early",
        "evidence_incomplete",
    } <= codes
    assert postmortem.timeline[1].summary == "assistant → present_files"
    assert postmortem.tool_failures == 1
    assert postmortem.delivery.satisfied is False
    assert postmortem.delivery.produced == 1
    assert postmortem.verdict == "Run ended with status error."


def test_subagent_and_workspace_summaries_are_readable():
    events = [
        event(1, "subagent.start", "subagent", {"name": "researcher"}),
        event(2, "workspace_changes", "outputs", {"files": [{"path": "a.md"}, {"path": "b.md"}]}),
        event(3, "context:memory", "context", "remembered preference"),
    ]
    postmortem = build_postmortem(snapshot(event_count=3), events)

    assert postmortem.timeline[0].summary == "subagent start: researcher"
    assert postmortem.timeline[1].summary == "workspace: 2 file(s) changed"
    assert postmortem.timeline[2].summary == "memory context: remembered preference"
    assert {anomaly.code for anomaly in postmortem.anomalies} == {"subagent_unfinished"}


def test_payloads_are_bounded_and_truncation_is_reported():
    long_text = "x" * 5000
    postmortem = build_postmortem(snapshot(event_count=1), [event(1, "llm.ai.response", "message", {"content": long_text})])

    assert len(postmortem.timeline[0].summary) <= 240
    assert postmortem.timeline[0].summary.endswith("…")


def test_markdown_escapes_table_cells_and_lists_the_caveats():
    events = [event(1, "llm.human.input", "message", {"content": "a | b"}), event(2, "run.delivery", "outputs", {"satisfied": False, "presented": 0, "produced_paths": ["x"]})]
    markdown = render_markdown(build_postmortem(snapshot(status="error", event_count=2), events))

    assert markdown.startswith("# Run postmortem — `r1`")
    assert "## Anomalies" in markdown
    assert "delivery_incomplete" in markdown
    assert "a \\| b" in markdown
    assert "No complete background subagent coverage." in markdown


def test_unparsable_event_content_falls_back_to_the_raw_string():
    raw = CompletedRunEvent(event_id="e1", seq=1, event_type="unknown.thing", category="trace", content_json="{not json", content_bytes=8, content_sha256="")
    postmortem = build_postmortem(snapshot(event_count=1), [raw])

    assert postmortem.timeline[0].summary == "{not json"


def test_bounded_read_is_reported_as_the_caller_bound_not_as_damage():
    events = [event(1, "run.start", "trace", {}), event(2, "run.end", "outputs", {"status": "success"})]
    postmortem = build_postmortem(snapshot(event_count=512), events, max_events=2)

    codes = {anomaly.code for anomaly in postmortem.anomalies}
    assert "evidence_bounded" in codes
    assert "evidence_incomplete" not in codes
    assert "evidence_truncated" not in codes
    assert any("bounded by max_events=2" in anomaly.detail for anomaly in postmortem.anomalies)
    assert any("max_events=2" in caveat for caveat in postmortem.caveats)


def test_truncated_payloads_are_reported_on_their_own():
    truncated = CompletedRunEvent(event_id="e1", seq=1, event_type="llm.ai.response", category="message", content_json='{"content": "x"}', content_bytes=1, content_sha256="", truncated=True)
    postmortem = build_postmortem(snapshot(event_count=1), [truncated])

    assert {anomaly.code for anomaly in postmortem.anomalies} == {"evidence_truncated"}


def test_prose_starting_with_error_is_not_a_tool_failure():
    prose = event(1, "llm.tool.result", "message", {"name": "read_file", "content": "Error handling in this tool is documented here."})
    marker = event(2, "llm.tool.result", "message", {"name": "read_file", "content": "Error: file not found"})

    prose_only = build_postmortem(snapshot(event_count=1), [prose])
    marker_only = build_postmortem(snapshot(event_count=1), [marker])

    assert prose_only.tool_failures == 0
    assert marker_only.tool_failures == 1
