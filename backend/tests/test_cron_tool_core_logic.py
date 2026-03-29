"""Core behavior tests for cron tool and cron handler logic."""

import importlib
from types import SimpleNamespace

from src.cron.types import CronJob, CronPayload, CronSchedule

cron_tool_module = importlib.import_module("deerflow.tools.builtins.cron_tool")
cron_handler_module = importlib.import_module("src.cron.handler")


def _make_runtime(
    *,
    context: dict | None = None,
    configurable: dict | None = None,
    metadata: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        context=context or {"thread_id": "thread-1"},
        config={
            "configurable": configurable or {},
            "metadata": metadata or {},
        },
        state={},
    )


def test_cron_tool_defaults_deliver_to_true_for_channel_requests_and_drops_default_agent_name(monkeypatch):
    captured: dict = {}

    def fake_request(method, path, *, params=None, json_body=None):
        captured["method"] = method
        captured["path"] = path
        captured["params"] = params
        captured["json_body"] = json_body
        return {
            "id": "job-1",
            "state": {"next_run_at": "2026-03-11T20:00:00+08:00"},
        }

    monkeypatch.setattr(cron_tool_module, "_cron_api_request", fake_request)

    runtime = _make_runtime(
        context={
            "thread_id": "thread-1",
            "channel_name": "feishu",
            "chat_id": "chat-123",
            "thread_ts": "msg-456",
        },
        metadata={
            "agent_name": "default",
            "thinking_enabled": True,
            "subagent_enabled": False,
        },
    )

    result = cron_tool_module.cron_tool.func(
        runtime=runtime,
        action="add",
        tool_call_id="tc-1",
        message="Remind me to eat",
        at="2026-03-11T20:00:00+08:00",
    )

    payload = captured["json_body"]["payload"]
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/cron"
    assert payload["deliver"] is True
    assert payload["assistant_id"] is None
    assert payload["agent_name"] is None
    assert payload["channel"] == "feishu"
    assert payload["to"] == "chat-123"
    assert payload["thread_ts"] == "msg-456"
    assert payload["thread_id"] == "thread-1"
    assert captured["json_body"]["delete_after_run"] is True
    assert "Task scheduled" in result


def test_cron_tool_allows_explicit_deliver_false_for_channel_requests(monkeypatch):
    captured: dict = {}

    def fake_request(method, path, *, params=None, json_body=None):
        del method, path, params
        captured["json_body"] = json_body
        return {"id": "job-1b", "state": {"next_run_at": None}}

    monkeypatch.setattr(cron_tool_module, "_cron_api_request", fake_request)

    runtime = _make_runtime(
        context={
            "thread_id": "thread-1",
            "channel_name": "feishu",
            "chat_id": "chat-123",
            "thread_ts": "msg-456",
        }
    )

    cron_tool_module.cron_tool.func(
        runtime=runtime,
        action="add",
        tool_call_id="tc-1b",
        message="Silent reminder",
        at="2026-03-11T20:00:00+08:00",
        deliver=False,
    )

    payload = captured["json_body"]["payload"]
    assert payload["deliver"] is False
    assert payload["channel"] is None
    assert payload["to"] is None
    assert payload["thread_ts"] is None


def test_cron_tool_preserves_non_default_agent_name(monkeypatch):
    captured: dict = {}

    def fake_request(method, path, *, params=None, json_body=None):
        del method, path, params
        captured["json_body"] = json_body
        return {"id": "job-2", "state": {"next_run_at": None}}

    monkeypatch.setattr(cron_tool_module, "_cron_api_request", fake_request)

    runtime = _make_runtime(
        configurable={"agent_name": "ops-helper"},
        metadata={"thinking_enabled": False, "subagent_enabled": True},
    )

    cron_tool_module.cron_tool.func(
        runtime=runtime,
        action="add",
        tool_call_id="tc-2",
        message="Check system health",
        every="1h",
    )

    payload = captured["json_body"]["payload"]
    assert payload["deliver"] is False
    assert payload["assistant_id"] is None
    assert payload["agent_name"] == "ops-helper"
    assert payload["thinking_enabled"] is False
    assert payload["subagent_enabled"] is True


def test_cron_tool_formats_at_next_run_using_runtime_timezone(monkeypatch):
    def fake_request(method, path, *, params=None, json_body=None):
        del method, path, params, json_body
        return {
            "id": "job-3",
            "schedule": {
                "kind": "at",
                "at_ms": 1_742_648_400_000,
                "every_ms": None,
                "expr": None,
                "tz": None,
            },
            "state": {"next_run_at": "2026-03-29T11:20:00+00:00"},
        }

    monkeypatch.setattr(cron_tool_module, "_cron_api_request", fake_request)

    runtime = _make_runtime(context={"thread_id": "thread-1", "timezone": "Asia/Shanghai"})

    result = cron_tool_module.cron_tool.func(
        runtime=runtime,
        action="add",
        tool_call_id="tc-3",
        message="Water the plants",
        at="in 1 minute",
    )

    assert "2026-03-29T19:20:00+08:00" in result


def test_cron_tool_list_formats_next_run_using_runtime_timezone(monkeypatch):
    def fake_request(method, path, *, params=None, json_body=None):
        del method, path, params, json_body
        return [
            {
                "id": "job-4",
                "name": "Water the plants",
                "enabled": True,
                "schedule": {
                    "kind": "at",
                    "at_ms": 1_742_648_400_000,
                    "every_ms": None,
                    "expr": None,
                    "tz": None,
                },
                "state": {"next_run_at": "2026-03-29T11:20:00+00:00"},
            }
        ]

    monkeypatch.setattr(cron_tool_module, "_cron_api_request", fake_request)

    runtime = _make_runtime(context={"thread_id": "thread-1", "timezone": "Asia/Shanghai"})

    result = cron_tool_module.cron_tool.func(
        runtime=runtime,
        action="list",
        tool_call_id="tc-4",
    )

    assert "2026-03-29T19:20:00+08:00" in result


def test_cron_tool_uses_runtime_context_timezone_for_cron_jobs(monkeypatch):
    captured: dict = {}

    def fake_request(method, path, *, params=None, json_body=None):
        del method, path, params
        captured["json_body"] = json_body
        return {"id": "job-5", "state": {"next_run_at": None}}

    monkeypatch.setattr(cron_tool_module, "_cron_api_request", fake_request)

    runtime = _make_runtime(context={"thread_id": "thread-1", "timezone": "Asia/Shanghai"})

    cron_tool_module.cron_tool.func(
        runtime=runtime,
        action="add",
        tool_call_id="tc-5",
        message="Dinner reminder",
        cron_expr="30 17 * * *",
    )

    assert captured["json_body"]["schedule"]["tz"] == "Asia/Shanghai"


def test_cron_tool_uses_default_timezone_for_cron_jobs_when_runtime_context_missing(monkeypatch):
    captured: dict = {}

    def fake_request(method, path, *, params=None, json_body=None):
        del method, path, params
        captured["json_body"] = json_body
        return {"id": "job-6", "state": {"next_run_at": None}}

    monkeypatch.setattr(cron_tool_module, "_cron_api_request", fake_request)
    monkeypatch.setattr(cron_tool_module, "get_default_timezone_name", lambda: "Asia/Tokyo")

    runtime = _make_runtime(context={"thread_id": "thread-1", "channel_name": "feishu"})

    cron_tool_module.cron_tool.func(
        runtime=runtime,
        action="add",
        tool_call_id="tc-6",
        message="Sleep reminder",
        cron_expr="30 20 * * *",
    )

    assert captured["json_body"]["schedule"]["tz"] == "Asia/Tokyo"


def test_cron_tool_formats_at_next_run_using_default_timezone_when_runtime_context_missing(monkeypatch):
    def fake_request(method, path, *, params=None, json_body=None):
        del method, path, params, json_body
        return {
            "id": "job-7",
            "schedule": {
                "kind": "at",
                "at_ms": 1_742_648_400_000,
                "every_ms": None,
                "expr": None,
                "tz": None,
            },
            "state": {"next_run_at": "2026-03-29T11:20:00+00:00"},
        }

    monkeypatch.setattr(cron_tool_module, "_cron_api_request", fake_request)
    monkeypatch.setattr(cron_tool_module, "get_default_timezone_name", lambda: "Asia/Tokyo")

    runtime = _make_runtime(context={"thread_id": "thread-1", "channel_name": "feishu"})

    result = cron_tool_module.cron_tool.func(
        runtime=runtime,
        action="add",
        tool_call_id="tc-7",
        message="Water the plants",
        at="in 1 minute",
    )

    assert "2026-03-29T20:20:00+09:00" in result


def test_build_run_settings_includes_channel_context_and_overrides():
    job = CronJob(
        id="job-8",
        name="Dinner reminder",
        schedule=CronSchedule(kind="at", at_ms=1),
        payload=CronPayload(
            message="Remind me to eat",
            channel="feishu",
            to="chat-123",
            thread_ts="msg-456",
            agent_name="ops-helper",
            thinking_enabled=False,
            subagent_enabled=True,
        ),
    )

    assistant_id, run_config, run_context = cron_handler_module._build_run_settings(job, "thread-1")

    assert assistant_id == "lead_agent"
    assert run_config["recursion_limit"] == 100
    assert run_context["thread_id"] == "thread-1"
    assert run_context["is_cron"] is True
    assert run_context["agent_name"] == "ops-helper"
    assert run_context["thinking_enabled"] is False
    assert run_context["subagent_enabled"] is True
    assert run_context["channel_name"] == "feishu"
    assert run_context["chat_id"] == "chat-123"
    assert run_context["thread_ts"] == "msg-456"


def test_build_run_settings_falls_back_from_default_assistant_id():
    job = CronJob(
        id="job-9",
        name="Dinner reminder",
        schedule=CronSchedule(kind="at", at_ms=1),
        payload=CronPayload(
            message="Remind me to eat",
            assistant_id="default",
        ),
    )

    assistant_id, _, _ = cron_handler_module._build_run_settings(job, "thread-1")

    assert assistant_id == "lead_agent"
