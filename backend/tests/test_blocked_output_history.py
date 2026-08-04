"""Blocked output must remain replaced after a thread-history refresh."""

from app.gateway.routers.thread_runs import redact_blocked_output_messages
from deerflow.safety.streaming_guard import BLOCKED_RESPONSE_TEXT


def test_blocked_run_history_replaces_ai_output_with_one_safe_message():
    rows = [
        {"seq": 1, "run_id": "run-1", "content": {"type": "human", "content": "question"}},
        {"seq": 2, "run_id": "run-1", "content": {"type": "ai", "content": "safe prefix"}},
        {"seq": 3, "run_id": "run-1", "content": {"type": "ai", "content": "unsafe suffix"}},
        {"seq": 4, "run_id": "run-2", "content": {"type": "ai", "content": "normal"}},
    ]

    result = redact_blocked_output_messages(rows, {"run-1"})

    assert [row["seq"] for row in result] == [1, 2, 4]
    assert result[1]["content"]["content"] == BLOCKED_RESPONSE_TEXT
    assert result[1]["content"]["additional_kwargs"]["content_blocked"] is True
    assert result[2]["content"]["content"] == "normal"
