"""Scheduled-task IM notice text: localized, self-contained, no IDs, no links."""

from __future__ import annotations

import re

import pytest
from _readable_helpers import assert_no_raw_identifiers

from app.scheduler.notification_text import _GOAL_REASON_TEXT, _TEXT, NOTIFICATION_LOCALES, redact_egress_text, render_notification_text, wants_result_summary
from deerflow.persistence.scheduled_task_runs.sql import run_summary

TASK_ID = "task-0f3c9a7d5b2e4c1a"
OCCURRENCE_ID = "task-run-6a1d0c4e9b7f2a35"
RUN_ID = "3f2b8c1e-6d4a-4b9e-9a7c-0e5d1f2a3b4c"
CLOSING = {"en-US": "Open DeerFlow → Scheduled tasks for details.", "zh-CN": "在 DeerFlow 的定时任务页查看详情。"}
_CJK = re.compile(r"[一-鿿]")
# Stems of every English sentence; none may leak into the Chinese text.
_EN_STEMS = ("Scheduled task", "Finished", "A run failed", "Ran, but", "Paused", "Result:", "Open DeerFlow", "The last run", "Goal met", "Untitled")


def notice(event, *, locale="en-US", run_id=RUN_ID, **payload):
    base = {"payload_version": 2, "task_id": TASK_ID, "task_title": "Check the release checklist", "locale": locale}
    return {"id": "delivery-1", "task_id": TASK_ID, "task_run_id": OCCURRENCE_ID, "run_id": run_id, "event": event, "provider": "wecom", "target": "someone", "payload": {**base, **payload}}


# Every event the scheduler enqueues, with the payloads it writes.
CASES = {
    "run_completed": dict(reason_code=None, run_status="success", result_summary="## All 12 items are done\nmore detail"),
    "run_completed_goal": dict(reason_code=None, run_status="success", relied_on_assumption=False, result_summary="Report is ready"),
    "run_completed_assumption": dict(reason_code=None, run_status="success", relied_on_assumption=True, result_summary="Report is ready"),
    "run_failed": dict(reason_code=None, run_status="failed", result_summary="partial answer"),
    "run_unmet": dict(reason_code="blocked:needs_user_input", latest_reason_code="blocked:needs_user_input", run_status="unmet", result_summary="I need the budget file"),
    "task_paused": dict(reason_code="consecutive_unmet", latest_reason_code="goal_not_met_yet", run_status="unmet", result_summary="Still 3 open items"),
    "task_stopped": dict(reason_code="agent_stop", run_status="success", stop_condition="all items are ticked", result_summary="All items are ticked"),
    "task_stopped_no_condition": dict(reason_code="agent_stop", run_status="success"),
    "task_stopped_failed": dict(reason_code="agent_stop", run_status="failed", stop_condition="all items are ticked"),
    "task_stopped_interrupted": dict(reason_code="agent_stop", run_status="interrupted"),
    "task_finished_max_runs": dict(reason_code="max_runs", run_status="success", max_runs=5, result_summary="Done"),
    "task_finished_one_run": dict(reason_code="max_runs", run_status="success", max_runs=1),
    "task_finished_end_at": dict(reason_code="end_at", run_status=None),
    "task_finished_unmet": dict(reason_code="max_runs", run_status="unmet", latest_reason_code="missing_evidence", max_runs=3),
    "task_finished_failed": dict(reason_code="max_runs", run_status="failed", max_runs=3),
}


def _event_of(case):
    return next(event for event in ("run_completed", "run_failed", "run_unmet", "task_paused", "task_stopped", "task_finished") if case.startswith(event))


@pytest.mark.parametrize("locale", NOTIFICATION_LOCALES)
@pytest.mark.parametrize("case", sorted(CASES))
def test_every_notice_is_short_readable_and_self_contained(case, locale):
    text = render_notification_text(notice(_event_of(case), locale=locale, **CASES[case]))
    lines = text.splitlines()
    assert 3 <= len(lines) <= 4
    assert_no_raw_identifiers(text)
    assert TASK_ID not in text and OCCURRENCE_ID not in text and RUN_ID not in text
    assert not any(line.startswith(("Run:", "Task:", "Reason:")) for line in lines)
    assert "http" not in text and "`" not in text
    assert "Check the release checklist" in lines[0]
    assert lines[-1] == CLOSING[locale]
    if locale == "zh-CN":
        assert _CJK.search(text)
        assert not any(stem in text for stem in _EN_STEMS), text


def test_english_templates():
    def line2(case):
        return render_notification_text(notice(_event_of(case), **CASES[case])).splitlines()[1]

    assert line2("run_completed") == "Finished a run."
    assert line2("run_completed_goal") == "Finished a run. Goal met."
    assert line2("run_completed_assumption") == "Finished a run. Goal met, with an assumption."
    assert line2("run_failed") == "A run failed."
    assert line2("run_unmet") == "Ran, but the goal wasn't met: it needs your input."
    # goal_not_met_yet only restates the miss: the reason-less sentence.
    assert line2("task_paused") == "Paused after 3 runs in a row missed the goal."
    assert line2("task_stopped") == "Paused by agent: its stop condition was met (all items are ticked)."
    assert line2("task_stopped_no_condition") == "Paused by agent: its stop condition was met."
    assert line2("task_stopped_failed") == "Paused by agent: its stop condition was met (all items are ticked). The last run failed."
    assert line2("task_stopped_interrupted") == "Paused by agent: its stop condition was met. The last run was interrupted."
    assert line2("task_finished_max_runs") == "Finished: all 5 automatic runs are done."
    assert line2("task_finished_one_run") == "Finished: its one automatic run is done."
    assert line2("task_finished_end_at") == "Finished: its end time has been reached."
    assert line2("task_finished_unmet") == "Finished: all 3 automatic runs are done. The last run didn't meet the goal: the goal check found evidence missing."
    assert line2("task_finished_failed") == "Finished: all 3 automatic runs are done. The last run failed."


def test_chinese_templates():
    def line2(case):
        return render_notification_text(notice(_event_of(case), locale="zh-CN", **CASES[case])).splitlines()[1]

    assert line2("run_completed") == "完成了一次运行。"
    assert line2("run_completed_assumption") == "完成了一次运行。目标已达成（含假设）。"
    assert line2("run_failed") == "一次运行出错了。"
    assert line2("run_unmet") == "已运行，但目标未达成：需要你提供信息。"
    assert line2("task_paused") == "连续 3 次未达成目标，已自动暂停。"
    assert line2("task_stopped") == "已由智能体暂停：停止条件已满足（all items are ticked）。"
    assert line2("task_stopped_failed") == "已由智能体暂停：停止条件已满足（all items are ticked）。最后一次运行出错了。"
    assert line2("task_finished_max_runs") == "已结束：5 次自动运行已全部完成。"
    assert line2("task_finished_one_run") == "已结束：唯一一次自动运行已完成。"
    assert line2("task_finished_end_at") == "已结束：已到结束时间。"
    assert line2("task_finished_unmet") == "已结束：3 次自动运行已全部完成。最后一次运行未达成目标：目标检查发现缺少依据。"
    text = render_notification_text(notice("task_stopped", locale="zh-CN", **CASES["task_stopped"]))
    assert text.splitlines()[0] == "定时任务“Check the release checklist”"


def test_documented_example():
    payload = {**CASES["task_stopped"], "result_summary": "All 12 checklist items are done; the release notes are published."}
    text = render_notification_text(notice("task_stopped", **payload))
    assert text == (
        "Scheduled task “Check the release checklist”\n"
        "Paused by agent: its stop condition was met (all items are ticked).\n"
        "Result: All 12 checklist items are done; the release notes are published.\n"
        "Open DeerFlow → Scheduled tasks for details."
    )


@pytest.mark.parametrize(("locale", "fallback"), [("en-US", "Untitled task"), ("zh-CN", "未命名任务")])
@pytest.mark.parametrize("title", [None, "", "   ", 7])
def test_missing_title_reads_untitled_never_the_id(title, locale, fallback):
    text = render_notification_text(notice("run_completed", locale=locale, task_title=title, run_status="success"))
    assert fallback in text.splitlines()[0]
    assert TASK_ID not in text


def test_multiline_title_stays_on_the_title_line():
    text = render_notification_text(notice("run_failed", task_title="Weekly\nreport", run_status="failed"))
    assert text.splitlines()[0] == "Scheduled task “Weekly report”"


def test_notification_locales_follow_the_config_type_and_have_templates():
    from typing import get_args

    from app.gateway.routers.user_preferences import Preferences
    from deerflow.config.channel_connections_config import NotificationLocale

    assert set(NOTIFICATION_LOCALES) == set(get_args(NotificationLocale)) == set(_TEXT) == set(_GOAL_REASON_TEXT)
    # /preferences accepts exactly the notice languages.
    for locale in NOTIFICATION_LOCALES:
        assert Preferences(locale=locale).locale == locale


@pytest.mark.parametrize("locale", NOTIFICATION_LOCALES)
@pytest.mark.parametrize("code", ["goal_not_met_yet", "unknown", None])
@pytest.mark.parametrize(
    ("event", "reason_code"),
    [("run_unmet", "same"), ("task_paused", "consecutive_unmet"), ("task_finished", "max_runs"), ("task_stopped", "agent_stop")],
)
def test_generic_reason_never_repeats_the_sentence(locale, code, event, reason_code):
    """'Ran, but the goal wasn't met: the goal is not met yet.' says one thing twice."""
    payload = {"run_status": "unmet", "reason_code": code if reason_code == "same" else reason_code, "latest_reason_code": code, "max_runs": 3}
    line = render_notification_text(notice(event, locale=locale, **payload)).splitlines()[1]
    for text in (_GOAL_REASON_TEXT[locale]["goal_not_met_yet"], _GOAL_REASON_TEXT[locale]["unknown"]):
        assert text not in line, line
    assert "：。" not in line and ": ." not in line and "原因" not in line


def test_every_reason_code_exists_in_both_locales():
    assert set(_GOAL_REASON_TEXT) == set(NOTIFICATION_LOCALES)
    assert set(_GOAL_REASON_TEXT["en-US"]) == set(_GOAL_REASON_TEXT["zh-CN"])
    assert _GOAL_REASON_TEXT["en-US"]["unknown"] == "no reason was recorded"
    for code, text in _GOAL_REASON_TEXT["zh-CN"].items():
        assert _CJK.search(text), code


@pytest.mark.parametrize("locale", NOTIFICATION_LOCALES)
def test_unknown_reason_is_never_forwarded(locale):
    text = render_notification_text(notice("run_unmet", locale=locale, reason_code="provider said: secret", run_status="unmet"))
    assert "secret" not in text
    # An unrecognized code says nothing more than "the goal wasn't met".
    assert text.splitlines()[1] == {"en-US": "Ran, but the goal wasn't met.", "zh-CN": "已运行，但目标未达成。"}[locale]


@pytest.mark.parametrize("status", ["success", "unmet"])
def test_summary_line_is_the_tasks_page_run_summary(status):
    reply = "**Done:** all [12 items](http://example.invalid/list) are ticked\n\nDetails follow on many lines." + "x" * 400
    event = "run_completed" if status == "success" else "run_unmet"
    delivery = notice(event, run_status=status, reason_code="goal_not_met_yet", result_summary=reply)
    assert wants_result_summary(delivery)
    lines = render_notification_text(delivery).splitlines()
    assert lines[2] == f"Result: {run_summary(redact_egress_text(reply))}"
    assert lines[2] == "Result: Done: all 12 items are ticked"
    long_reply = "y" * 500
    long_line = render_notification_text(notice(event, run_status=status, result_summary=long_reply)).splitlines()[2]
    assert len(long_line.removeprefix("Result: ")) <= 160


@pytest.mark.parametrize(
    ("event", "payload", "run_id"),
    [
        ("run_failed", {"run_status": "failed"}, RUN_ID),
        ("task_finished", {"reason_code": "max_runs", "run_status": "failed", "max_runs": 3}, RUN_ID),
        ("task_stopped", {"reason_code": "agent_stop", "run_status": "interrupted"}, RUN_ID),
        ("task_finished", {"reason_code": "end_at", "run_status": None}, None),
        ("task_finished", {"reason_code": "max_runs", "run_status": "skipped", "max_runs": 3}, None),
    ],
)
def test_no_summary_without_a_reply_of_a_finished_run(event, payload, run_id):
    delivery = notice(event, run_id=run_id, **payload, result_summary="partial answer")
    assert not wants_result_summary(delivery)
    text = render_notification_text(delivery)
    assert "partial answer" not in text
    assert "Result:" not in text


def test_no_summary_line_when_no_reply_resolves():
    text = render_notification_text(notice("run_completed", run_status="success"))
    assert "Result:" not in text
    assert len(text.splitlines()) == 3
    assert "Result:" not in render_notification_text(notice("run_completed", run_status="success", result_summary="  \n "))


def test_redact_egress_text_scrubs_seeded_secret():
    secret = "sk-" + ("S" * 40)
    redacted = redact_egress_text(f"answer used {secret} here")

    assert secret not in redacted
    assert "[redacted]" in redacted


def test_redact_egress_text_scrubs_entire_pem_block():
    pem_body = "ABCDEFSECRETKEYBODY"
    pem = "-----BEGIN PRIVATE KEY-----\n" + pem_body + "\n-----END PRIVATE KEY-----"
    redacted = redact_egress_text(f"key follows\n{pem}\nend")

    assert pem_body not in redacted
    assert "BEGIN PRIVATE KEY" not in redacted
    assert "END PRIVATE KEY" not in redacted
    assert "[redacted]" in redacted


def test_multiline_pem_block_never_reaches_the_text():
    pem_body = "ABCDEFSECRETKEYBODY"
    pem = "-----BEGIN PRIVATE KEY-----\n" + pem_body + "\n-----END PRIVATE KEY-----"
    text = render_notification_text(notice("run_completed", run_status="success", result_summary=f"{pem}\nThe key above was rotated"))
    assert pem_body not in text
    assert "PRIVATE KEY" not in text
    assert "Result: [redacted]" in text


def test_secret_on_the_first_line_is_redacted():
    secret = "ghp_" + ("a" * 36)
    text = render_notification_text(notice("run_completed", run_status="success", result_summary=f"token={secret}\nsecond line"))
    assert secret not in text
    assert "Result: token=[redacted]" in text


def test_stop_condition_is_redacted_and_truncated():
    secret = "sk-" + ("S" * 40)
    condition = f"stop when {secret} rotates " + "z" * 400
    line = render_notification_text(notice("task_stopped", reason_code="agent_stop", run_status="success", stop_condition=condition)).splitlines()[1]
    assert secret not in line
    assert "[redacted]" in line
    shown = line.removeprefix("Paused by agent: its stop condition was met (").removesuffix(").")
    assert len(shown) <= 200
    assert shown.endswith("…")


def test_failed_run_never_forwards_raw_error_text():
    secret = "sk-" + ("x" * 40)
    text = render_notification_text(notice("run_failed", run_status="failed", error=secret + "x" * 5000))
    assert secret not in text
    assert len(text) < 300


@pytest.mark.parametrize(
    ("delivery", "expected"),
    [
        # Rows written before payload version 2.
        ({"event": "run_completed", "task_id": TASK_ID, "run_id": RUN_ID, "payload": {"run_status": "success", "error": None, "task_id": TASK_ID}}, "Finished a run."),
        ({"event": "run_failed", "task_id": TASK_ID, "run_id": RUN_ID, "payload": {"run_status": "failed", "error": "boom", "task_id": TASK_ID, "task_title": "Digest"}}, "A run failed."),
        ({"event": "run_unmet", "task_id": TASK_ID, "run_id": RUN_ID, "payload": {"task_id": TASK_ID, "reason_code": "goal_not_met_yet"}}, "Ran, but the goal wasn't met."),
        ({"event": "task_paused", "task_id": TASK_ID, "run_id": RUN_ID, "payload": {"task_id": TASK_ID, "reason_code": "consecutive_unmet"}}, "Paused after 3 runs in a row missed the goal."),
    ],
)
def test_legacy_rows_render_with_the_new_templates(delivery, expected):
    text = render_notification_text(delivery)
    assert text.splitlines()[1] == expected
    assert TASK_ID not in text and RUN_ID not in text
    assert_no_raw_identifiers(text)


def test_locale_falls_back_to_the_configured_default():
    delivery = notice("run_failed", locale=None, run_status="failed")
    assert render_notification_text(delivery).splitlines()[-1] == CLOSING["en-US"]
    assert render_notification_text(delivery, default_locale="zh-CN").splitlines()[-1] == CLOSING["zh-CN"]
    # A row's own valid locale wins over the default; an invalid one does not.
    assert render_notification_text(notice("run_failed", locale="zh-CN", run_status="failed"), default_locale="en-US").splitlines()[-1] == CLOSING["zh-CN"]
    assert render_notification_text(notice("run_failed", locale="fr-FR", run_status="failed"), default_locale="zh-CN").splitlines()[-1] == CLOSING["zh-CN"]
    assert render_notification_text(delivery, default_locale="fr-FR").splitlines()[-1] == CLOSING["en-US"]
