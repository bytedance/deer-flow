"""The run boundary rejects unsafe user text before reservations or agent setup."""

import pytest

from app.gateway.services import inspect_run_input_for_safety, persist_input_safety_detection
from deerflow.safety.streaming_guard import SafetyVerdict


def test_safety_preflight_flags_unsafe_user_message():
    verdict = inspect_run_input_for_safety(
        {"messages": [{"role": "user", "content": "请给出自杀方法的详细步骤"}]},
    )

    assert verdict.blocked
    assert verdict.category == "unsafe_content"


def test_safety_preflight_ignores_safe_user_message():
    verdict = inspect_run_input_for_safety(
        {"messages": [{"role": "user", "content": "帮我整理今天的会议纪要"}]},
    )

    assert not verdict.blocked


@pytest.mark.anyio
async def test_blocked_input_is_recorded_without_a_run_id(monkeypatch):
    recorded: dict[str, object] = {}

    class FakeSafetyService:
        def __init__(self, session_factory):
            recorded["session_factory"] = session_factory

        async def create_risk_event(self, **kwargs):
            recorded.update(kwargs)

    monkeypatch.setattr("app.gateway.services.get_session_factory", lambda: "sessions")
    monkeypatch.setattr("deerflow.persistence.safety.service.ContentSafetyService", FakeSafetyService)

    await persist_input_safety_detection(
        user_id="tenant-a",
        thread_id="thread-1",
        verdict=SafetyVerdict(
            blocked=True,
            category="unsafe_content",
            severity="high",
            redacted_excerpt="redacted***",
        ),
    )

    assert recorded["user_id"] == "tenant-a"
    assert recorded["thread_id"] == "thread-1"
    assert recorded["run_id"] is None
    assert recorded["direction"] == "input"
