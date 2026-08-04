from types import SimpleNamespace

import pytest

from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.worker import persist_output_safety_detection, streamed_message_text
from deerflow.safety.streaming_guard import SafetyVerdict


def test_streamed_message_text_reads_langchain_message_tuple_content():
    assert streamed_message_text((SimpleNamespace(content="partial response"), {})) == "partial response"


def test_streamed_message_text_ignores_non_text_chunks():
    assert streamed_message_text((SimpleNamespace(content=[{"type": "image"}]), {})) == ""


@pytest.mark.anyio
async def test_output_safety_detection_is_scoped_to_the_run_owner(monkeypatch):
    recorded: dict[str, object] = {}

    class FakeSafetyService:
        def __init__(self, session_factory):
            recorded["session_factory"] = session_factory

        async def create_risk_event(self, **kwargs):
            recorded.update(kwargs)

    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: "sessions")
    monkeypatch.setattr("deerflow.persistence.safety.service.ContentSafetyService", FakeSafetyService)
    record = RunRecord(
        run_id="run-1",
        thread_id="thread-1",
        assistant_id=None,
        status=RunStatus.running,
        on_disconnect="continue",
        user_id="tenant-a",
    )
    verdict = SafetyVerdict(
        blocked=True,
        category="unsafe_content",
        severity="high",
        redacted_excerpt="redacted***",
    )

    await persist_output_safety_detection(record, verdict)

    assert recorded["user_id"] == "tenant-a"
    assert recorded["thread_id"] == "thread-1"
    assert recorded["run_id"] == "run-1"
    assert recorded["direction"] == "output"
    assert recorded["redacted_excerpt"] == "redacted***"
