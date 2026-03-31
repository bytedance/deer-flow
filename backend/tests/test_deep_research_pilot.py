from __future__ import annotations

import json
import time
from pathlib import Path

from deerflow.client import StreamEvent
from deerflow.config.paths import Paths
from deerflow.pilot.deep_research import DeepResearchPilotRequest, DeepResearchPilotResult, DeepResearchPilotRunner


class FakeClient:
    def __init__(self, *, events=None, upload_files_response=None, error: Exception | None = None, delay_seconds: float = 0.0):
        self.events = list(events or [])
        self.upload_files_response = upload_files_response or {"files": []}
        self.error = error
        self.delay_seconds = delay_seconds
        self.stream_calls = 0
        self.last_prompt = ""
        self.last_thread_id = ""

    def stream(self, message: str, *, thread_id: str | None = None, **kwargs):
        self.stream_calls += 1
        self.last_prompt = message
        self.last_thread_id = thread_id or ""
        if self.error is not None:
            raise self.error
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)
        for event in self.events:
            yield event

    def upload_files(self, thread_id: str, files: list[str | Path]) -> dict[str, object]:
        return self.upload_files_response

    def list_skills(self, enabled_only: bool = False) -> dict[str, object]:
        return {"skills": [{"name": "deep-research"}]}


def _make_runner(tmp_path: Path, client: FakeClient, *, monotonic_values=None) -> DeepResearchPilotRunner:
    sequence = list(monotonic_values or [0.0, 0.1, 0.2, 0.3, 0.4, 0.5])
    state = {"index": 0, "last": sequence[-1]}

    def _next_value() -> float:
        if state["index"] < len(sequence):
            value = sequence[state["index"]]
            state["index"] += 1
            state["last"] = value
            return value
        return state["last"]

    return DeepResearchPilotRunner(
        client=client,
        base_dir=tmp_path,
        monotonic_fn=_next_value,
    )


def test_builds_prompt_and_persists_artifact_result(tmp_path: Path) -> None:
    outputs_dir = Paths(base_dir=tmp_path).sandbox_outputs_dir("deep-research-req-1")
    outputs_dir.mkdir(parents=True, exist_ok=True)
    artifact = outputs_dir / "req-1-executive-brief.md"
    artifact.write_text("# brief", encoding="utf-8")

    client = FakeClient(
        events=[
            StreamEvent(
                type="messages-tuple",
                data={
                    "type": "ai",
                    "content": "Short summary for the presence layer.",
                    "tool_calls": [
                        {
                            "name": "present_files",
                            "args": {"filepaths": ["/mnt/user-data/outputs/req-1-executive-brief.md"]},
                        }
                    ],
                },
            ),
            StreamEvent(type="values", data={"messages": [], "artifacts": []}),
            StreamEvent(type="end", data={"usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}}),
        ],
        upload_files_response={
            "files": [
                {
                    "filename": "context.md",
                    "virtual_path": "/mnt/user-data/uploads/context.md",
                    "markdown_file": "context.md",
                }
            ]
        },
    )
    runner = _make_runner(tmp_path, client)

    result = runner.run(
        DeepResearchPilotRequest(
            objective="Analyze the competitive landscape",
            request_id="req-1",
            thread_id="deep-research-req-1",
            attachments=["C:/tmp/context.md"],
            output_profile="founder",
        )
    )

    assert result.status == "completed"
    assert result.short_summary == "Short summary for the presence layer."
    assert result.token_usage["total_tokens"] == 30
    assert result.artifacts[0]["virtual_path"] == "/mnt/user-data/outputs/req-1-executive-brief.md"
    assert "/mnt/user-data/uploads/context.md" in client.last_prompt
    assert "EXECUTIVE_BRIEF_MARKDOWN_START" in client.last_prompt
    assert "Deep Research` as the only in-scope use case" in client.last_prompt
    assert "Selected profile: founder" in client.last_prompt
    assert "Format the executive brief as a founder memo." in client.last_prompt
    stored = json.loads((runner.request_dir("req-1") / "result.json").read_text(encoding="utf-8"))
    assert stored["status"] == "completed"
    assert stored["output_profile"] == "founder"


def test_normalizes_legacy_profile_aliases() -> None:
    assert DeepResearchPilotRequest(objective="x", output_profile="founder_memo").normalized().output_profile == "founder"
    assert DeepResearchPilotRequest(objective="x", output_profile="operator_memo").normalized().output_profile == "operator"


def test_rejects_unknown_output_profile() -> None:
    try:
        DeepResearchPilotRequest(
            objective="Analyze the competitive landscape",
            output_profile="board_deck",
        ).normalized()
    except ValueError as exc:
        assert "output_profile must be one of" in str(exc)
    else:
        raise AssertionError("Expected invalid output_profile to raise ValueError")


def test_idempotency_reuses_completed_result(tmp_path: Path) -> None:
    client = FakeClient()
    runner = _make_runner(tmp_path, client, monotonic_values=[0.0, 0.1, 0.2])
    cached_request_dir = runner.request_dir("existing-request")
    cached_request_dir.mkdir(parents=True, exist_ok=True)
    cached_result = DeepResearchPilotResult(
        request_id="existing-request",
        idempotency_key="same-key",
        thread_id="deep-research-existing-request",
        output_profile="operator",
        status="completed",
        short_summary="cached",
        artifacts=[],
    )
    runner.idempotency_dir.mkdir(parents=True, exist_ok=True)
    (runner.idempotency_dir / "same-key.json").write_text(
        json.dumps({"idempotency_key": "same-key", "request_id": "existing-request"}),
        encoding="utf-8",
    )
    (cached_request_dir / "result.json").write_text(json.dumps(cached_result.to_dict()), encoding="utf-8")

    result = runner.run(
        DeepResearchPilotRequest(
            objective="Repeat objective",
            request_id="new-request",
            thread_id="deep-research-new-request",
            idempotency_key="same-key",
        )
    )

    assert result.status == "completed"
    assert result.request_id == "existing-request"
    assert result.output_profile == "operator"
    assert client.stream_calls == 0


def test_heartbeat_written_when_stream_is_quiet(tmp_path: Path) -> None:
    client = FakeClient(events=[], delay_seconds=0.35)
    monotonic_values = [0.0, 0.05, 0.1, 0.35, 0.7, 1.1, 1.4, 1.6, 1.8]
    runner = _make_runner(tmp_path, client, monotonic_values=monotonic_values)
    request = DeepResearchPilotRequest(
        objective="Timeout and heartbeat test",
        request_id="hb-1",
        thread_id="deep-research-hb-1",
        timeout_seconds=2,
        heartbeat_interval_seconds=0.2,
        heartbeat_start_after_seconds=0,
    )

    result = runner.run(request)

    assert result.status == "failed"
    events_text = (runner.request_dir("hb-1") / "events.jsonl").read_text(encoding="utf-8")
    assert "\"kind\": \"heartbeat\"" in events_text


def test_timeout_preserves_partial_result(tmp_path: Path) -> None:
    outputs_dir = Paths(base_dir=tmp_path).sandbox_outputs_dir("deep-research-timeout-1")
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "timeout-1-executive-brief.md").write_text("# partial", encoding="utf-8")

    client = FakeClient(
        events=[
            StreamEvent(
                type="messages-tuple",
                data={"type": "ai", "content": "Partial but useful summary before timeout."},
            ),
        ]
    )
    monotonic_values = [0.0, 0.1, 0.2, 0.3, 1.2, 1.4]
    runner = _make_runner(tmp_path, client, monotonic_values=monotonic_values)

    result = runner.run(
        DeepResearchPilotRequest(
            objective="Force a timeout",
            request_id="timeout-1",
            thread_id="deep-research-timeout-1",
            timeout_seconds=1,
            heartbeat_interval_seconds=1,
            heartbeat_start_after_seconds=0,
        )
    )

    assert result.status == "failed"
    assert result.error_code == "timeout"
    assert result.partial_result_available is True
    assert result.short_summary == "Partial but useful summary before timeout."
    assert result.artifacts[0]["virtual_path"] == "/mnt/user-data/outputs/timeout-1-executive-brief.md"


def test_materializes_fallback_markdown_when_model_cannot_write_file(tmp_path: Path) -> None:
    client = FakeClient(
        events=[
            StreamEvent(
                type="messages-tuple",
                data={
                    "type": "ai",
                    "content": (
                        "File writes are blocked in this runtime.\n\n"
                        "EXECUTIVE_BRIEF_MARKDOWN_START\n"
                        "# Sprint 1 Brief\n\n"
                        "- Scope: Deep Research only\n"
                        "- Guardrails: tracing, timeout, idempotency\n"
                        "EXECUTIVE_BRIEF_MARKDOWN_END"
                    ),
                },
            ),
            StreamEvent(type="end", data={"usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}}),
        ]
    )
    runner = _make_runner(tmp_path, client, monotonic_values=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5])

    result = runner.run(
        DeepResearchPilotRequest(
            objective="Fallback artifact generation",
            request_id="fallback-1",
            thread_id="deep-research-fallback-1",
        )
    )

    assert result.status == "completed"
    assert "EXECUTIVE_BRIEF_MARKDOWN_START" not in result.short_summary
    assert result.artifacts[0]["virtual_path"] == "/mnt/user-data/outputs/fallback-1-executive-brief.md"
    artifact_path = Paths(base_dir=tmp_path).sandbox_outputs_dir("deep-research-fallback-1") / "fallback-1-executive-brief.md"
    assert artifact_path.exists()
    assert "# Sprint 1 Brief" in artifact_path.read_text(encoding="utf-8")


def test_operator_profile_short_summary_ignores_metadata_lines(tmp_path: Path) -> None:
    client = FakeClient(
        events=[
            StreamEvent(
                type="messages-tuple",
                data={
                    "type": "ai",
                    "content": (
                        "EXECUTIVE_BRIEF_MARKDOWN_START\n"
                        "# Operator Handoff Memo — DeerFlow-only Hardening Cycle\n"
                        "**Request ID:** profile-20260331-operator-v1\n"
                        "**Thread ID:** deep-research-profile-operator-v1\n"
                        "**Date:** 2026-03-31 (UTC)\n"
                        "\n"
                        "## 1) Objective\n"
                        "Harden the DeerFlow-only Sprint 1 pilot so operators can run, trace, and evaluate real Deep Research tasks.\n"
                        "\n"
                        "## 9) Next Concrete Actions\n"
                        "Freeze the adapter contract, rerun the pilot batch, and publish the evidence pack.\n"
                        "EXECUTIVE_BRIEF_MARKDOWN_END"
                    ),
                },
            ),
            StreamEvent(type="end", data={"usage": {"input_tokens": 5, "output_tokens": 7, "total_tokens": 12}}),
        ]
    )
    runner = _make_runner(tmp_path, client, monotonic_values=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5])

    result = runner.run(
        DeepResearchPilotRequest(
            objective="Operator memo summary shaping",
            request_id="operator-summary-1",
            thread_id="deep-research-operator-summary-1",
            output_profile="operator",
        )
    )

    assert result.status == "completed"
    assert "Request ID" not in result.short_summary
    assert "Thread ID" not in result.short_summary
    assert "Harden the DeerFlow-only Sprint 1 pilot" in result.short_summary
