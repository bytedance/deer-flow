"""Text of scheduled-task IM notices.

A notice reads on its own, in the owner's language, with one item per line:

1. the task title (``Scheduled task “{title}”``);
2. what happened, plus the last run's outcome where the main sentence would
   otherwise hide it;
3. ``Result: {summary}``, the same one-line run summary the tasks page shows,
   only when the agent replied (a run that succeeded or missed its goal);
4. where to look: ``Open DeerFlow → Scheduled tasks for details.``

It carries no task, run or thread IDs, no URLs (most deployments run on
localhost or a LAN, so a link would be dead on the phone that receives it), no
timestamps and no internal codes. Agent-written text (the stop condition, the
reply) passes through :func:`redact_egress_text` before it leaves for a
third-party platform.

Payload (``payload_version`` 2, written by the scheduler's finalization
observer): ``task_title``, ``locale`` (``None`` = the configured default),
``reason_code``, ``latest_reason_code``, ``run_status``, optional
``relied_on_assumption`` (present only when a goal was met), ``stop_condition``
(``task_stopped``) and ``max_runs`` (``task_finished``). Rows written before
version 2 render with the same templates.
"""

from __future__ import annotations

import re
from typing import Any, get_args

from deerflow.config.channel_connections_config import NotificationLocale
from deerflow.persistence.scheduled_task_runs.sql import run_summary

# One source of truth: the config type that ``/preferences`` also accepts.
NOTIFICATION_LOCALES: tuple[str, ...] = get_args(NotificationLocale)
DEFAULT_NOTIFICATION_LOCALE = "en-US"

_CONDITION_LIMIT = 200
_TITLE_LIMIT = 200

_EGRESS_REDACTION = "[redacted]"
# Best-effort scrub before run content leaves for a third-party IM platform.
# Patterns mirror the high-confidence secret detectors in skillscan.
_EGRESS_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?im)\b(token|password|passwd|api[_-]?key|secret|credential)s?\b\s*[:=]\s*[\"']?([^\"'\s#]+)"),
)


def redact_egress_text(text: str) -> str:
    """Scrub likely secrets from text before it is pushed to external IM."""
    if not text:
        return text
    redacted = text
    for pattern in _EGRESS_SECRET_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(lambda match: f"{match.group(1)}={_EGRESS_REDACTION}", redacted)
        else:
            redacted = pattern.sub(_EGRESS_REDACTION, redacted)
    return redacted


# Readable text for host-defined goal reason codes (``blocked:`` prefix
# removed), per locale. Keys mirror the goal blockers and stand-down reasons;
# model or provider error text is never forwarded.
_GOAL_REASON_TEXT: dict[str, dict[str, str]] = {
    "en-US": {
        "missing_evidence": "the goal check found evidence missing",
        "needs_user_input": "it needs your input",
        "run_failed": "the goal check found the work unfinished",
        "external_wait": "it is waiting on something external",
        "goal_not_met_yet": "the goal is not met yet",
        "no_verdict": "no goal verdict was recorded",
        "consecutive_unmet": "3 scheduled runs in a row did not meet the goal",
        "evaluator_failed": "the goal check could not run",
        "max_continuations_reached": "the continuation limit was reached",
        "no_progress_detected": "no progress was made between turns",
        "token_capped": "the token budget was reached",
        "no_durable_end_of_turn": "no final reply was saved",
        "thread_changed_after_evaluation": "the conversation changed during the goal check",
        "thread_changed_before_continuation": "the conversation changed during the goal check",
        "unknown": "no reason was recorded",
    },
    "zh-CN": {
        "missing_evidence": "目标检查发现缺少依据",
        "needs_user_input": "需要你提供信息",
        "run_failed": "目标检查发现工作未完成",
        "external_wait": "正在等待外部条件",
        "goal_not_met_yet": "目标尚未达成",
        "no_verdict": "没有记录目标检查结果",
        "consecutive_unmet": "连续 3 次定时运行未达成目标",
        "evaluator_failed": "目标检查未能运行",
        "max_continuations_reached": "已达到继续处理的次数上限",
        "no_progress_detected": "多轮之间没有进展",
        "token_capped": "已达到 token 预算",
        "no_durable_end_of_turn": "没有保存最终回复",
        "thread_changed_after_evaluation": "目标检查期间对话发生了变化",
        "thread_changed_before_continuation": "目标检查期间对话发生了变化",
        "unknown": "没有记录原因",
    },
}

_TEXT: dict[str, dict[str, str]] = {
    "en-US": {
        "title": "Scheduled task “{title}”",
        "untitled": "Untitled task",
        "run_completed": "Finished a run.",
        "goal_met": "Goal met.",
        "goal_met_with_assumption": "Goal met, with an assumption.",
        "run_failed": "A run failed.",
        "run_unmet": "Ran, but the goal wasn't met: {reason}.",
        "run_unmet_bare": "Ran, but the goal wasn't met.",
        "task_paused": "Paused after 3 runs in a row missed the goal: {reason}.",
        "task_paused_bare": "Paused after 3 runs in a row missed the goal.",
        "task_stopped_condition": "Paused by agent: its stop condition was met ({condition}).",
        "task_stopped": "Paused by agent: its stop condition was met.",
        "finished_max_runs": "Finished: all {max_runs} automatic runs are done.",
        "finished_one_run": "Finished: its one automatic run is done.",
        "finished_all_runs": "Finished: all automatic runs are done.",
        "finished_end_at": "Finished: its end time has been reached.",
        "finished": "Finished.",
        "update": "There is an update.",
        "last_failed": "The last run failed.",
        "last_unmet": "The last run didn't meet the goal: {reason}.",
        "last_unmet_bare": "The last run didn't meet the goal.",
        "last_interrupted": "The last run was interrupted.",
        "result": "Result: {summary}",
        "closing": "Open DeerFlow → Scheduled tasks for details.",
        "sentence_gap": " ",
    },
    "zh-CN": {
        "title": "定时任务“{title}”",
        "untitled": "未命名任务",
        "run_completed": "完成了一次运行。",
        "goal_met": "目标已达成。",
        "goal_met_with_assumption": "目标已达成（含假设）。",
        "run_failed": "一次运行出错了。",
        "run_unmet": "已运行，但目标未达成：{reason}。",
        "run_unmet_bare": "已运行，但目标未达成。",
        "task_paused": "连续 3 次未达成目标，已自动暂停。最近一次的原因：{reason}。",
        "task_paused_bare": "连续 3 次未达成目标，已自动暂停。",
        "task_stopped_condition": "已由智能体暂停：停止条件已满足（{condition}）。",
        "task_stopped": "已由智能体暂停：停止条件已满足。",
        "finished_max_runs": "已结束：{max_runs} 次自动运行已全部完成。",
        "finished_one_run": "已结束：唯一一次自动运行已完成。",
        "finished_all_runs": "已结束：自动运行已全部完成。",
        "finished_end_at": "已结束：已到结束时间。",
        "finished": "已结束。",
        "update": "有新的动态。",
        "last_failed": "最后一次运行出错了。",
        "last_unmet": "最后一次运行未达成目标：{reason}。",
        "last_unmet_bare": "最后一次运行未达成目标。",
        "last_interrupted": "最后一次运行被中断了。",
        "result": "结果：{summary}",
        "closing": "在 DeerFlow 的定时任务页查看详情。",
        "sentence_gap": "",
    },
}

# Events whose notice may carry the run's one-line result, and the run
# outcomes that have one (the agent replied; a failed or interrupted run's
# partial reply is not a result).
_SUMMARY_EVENTS = frozenset({"run_completed", "run_unmet", "task_paused", "task_stopped", "task_finished"})
_SUMMARY_RUN_STATUSES = frozenset({"success", "unmet"})
# Rows written before payload version 2 carry no ``run_status`` for these.
_LEGACY_RUN_STATUS = {"run_completed": "success", "run_failed": "failed", "run_unmet": "unmet", "task_paused": "unmet"}


def _payload(delivery: dict[str, Any]) -> dict[str, Any]:
    payload = delivery.get("payload")
    return payload if isinstance(payload, dict) else {}


def _run_status(delivery: dict[str, Any]) -> str | None:
    status = _payload(delivery).get("run_status")
    if isinstance(status, str) and status:
        return status
    return _LEGACY_RUN_STATUS.get(delivery.get("event") or "")


def wants_result_summary(delivery: dict[str, Any]) -> bool:
    """Whether the notice carries a result line, so the worker resolves the run's reply."""
    return bool(delivery.get("run_id")) and delivery.get("event") in _SUMMARY_EVENTS and _run_status(delivery) in _SUMMARY_RUN_STATUSES


def resolve_locale(delivery: dict[str, Any], default_locale: str = DEFAULT_NOTIFICATION_LOCALE) -> str:
    """The row's locale (the owner's UI language), else the configured default."""
    locale = _payload(delivery).get("locale")
    if isinstance(locale, str) and locale in NOTIFICATION_LOCALES:
        return locale
    return default_locale if default_locale in NOTIFICATION_LOCALES else DEFAULT_NOTIFICATION_LOCALE


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _truncate(text: str, *, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# Codes that only restate "the goal wasn't met" (or say nothing): the notice
# uses its reason-less sentence instead of "…wasn't met: the goal is not met yet."
_NO_EXTRA_REASON = frozenset({"goal_not_met_yet", "unknown"})


def _reason_text(code: object, locale: str) -> str | None:
    """Readable reason for a goal code, or None when it would add nothing."""
    texts = _GOAL_REASON_TEXT[locale]
    if isinstance(code, str):
        code = code.removeprefix("blocked:")
    if not isinstance(code, str) or code not in texts or code in _NO_EXTRA_REASON:
        return None
    return texts[code]


def _with_reason(key: str, code: object, locale: str) -> str:
    """The ``key`` sentence with the reason, or its ``{key}_bare`` form without one."""
    reason = _reason_text(code, locale)
    text = _TEXT[locale]
    return text[f"{key}_bare"] if reason is None else text[key].format(reason=reason)


def _title(payload: dict[str, Any], locale: str) -> str:
    title = payload.get("task_title")
    title = _one_line(title) if isinstance(title, str) else ""
    return _truncate(title, limit=_TITLE_LIMIT) if title else _TEXT[locale]["untitled"]


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _last_run_suffix(event: str, run_status: str | None, payload: dict[str, Any], locale: str) -> str | None:
    """The last run's outcome, appended where the main sentence would hide it."""
    text = _TEXT[locale]
    if run_status == "failed":
        return text["last_failed"]
    if run_status == "unmet":
        return _with_reason("last_unmet", payload.get("latest_reason_code"), locale)
    if run_status == "interrupted" and event == "task_stopped":
        return text["last_interrupted"]
    return None


def _what_happened(delivery: dict[str, Any], locale: str) -> str:
    text = _TEXT[locale]
    payload = _payload(delivery)
    event = delivery.get("event") or ""
    run_status = _run_status(delivery)
    parts: list[str]
    if event == "run_completed":
        parts = [text["run_completed"]]
        if "relied_on_assumption" in payload:
            parts.append(text["goal_met_with_assumption"] if payload.get("relied_on_assumption") is True else text["goal_met"])
    elif event == "run_failed":
        # Raw error text never leaves: tracebacks can carry hosts, paths and tokens.
        parts = [text["run_failed"]]
    elif event == "run_unmet":
        parts = [_with_reason("run_unmet", payload.get("reason_code"), locale)]
    elif event == "task_paused":
        # The pause reason itself is fixed (3 misses); show the latest miss's reason.
        latest = payload.get("latest_reason_code")
        if latest is None and payload.get("reason_code") != "consecutive_unmet":
            latest = payload.get("reason_code")
        parts = [_with_reason("task_paused", latest, locale)]
    elif event == "task_stopped":
        condition = payload.get("stop_condition")
        condition = _truncate(_one_line(redact_egress_text(condition)), limit=_CONDITION_LIMIT) if isinstance(condition, str) else ""
        parts = [text["task_stopped_condition"].format(condition=condition) if condition else text["task_stopped"]]
        if (suffix := _last_run_suffix(event, run_status, payload, locale)) is not None:
            parts.append(suffix)
    elif event == "task_finished":
        reason = payload.get("reason_code")
        if reason == "end_at":
            parts = [text["finished_end_at"]]
        elif reason == "max_runs":
            max_runs = _positive_int(payload.get("max_runs"))
            parts = [text["finished_one_run"] if max_runs == 1 else text["finished_max_runs"].format(max_runs=max_runs) if max_runs is not None else text["finished_all_runs"]]
        else:
            parts = [text["finished"]]
        if (suffix := _last_run_suffix(event, run_status, payload, locale)) is not None:
            parts.append(suffix)
    else:
        parts = [text["update"]]
    return text["sentence_gap"].join(parts)


def render_notification_text(delivery: dict[str, Any], *, default_locale: str = DEFAULT_NOTIFICATION_LOCALE) -> str:
    """Render one self-contained notice: title, what happened, result, where to look.

    ``payload["result_summary"]`` is the run's final reply, attached by the
    delivery worker at send time; it is redacted as a whole (so a multi-line
    secret is gone before a line is taken) and reduced to the tasks page's
    one-line run summary.
    """
    locale = resolve_locale(delivery, default_locale)
    text = _TEXT[locale]
    payload = _payload(delivery)
    lines = [text["title"].format(title=_title(payload, locale)), _what_happened(delivery, locale)]
    reply = payload.get("result_summary")
    if wants_result_summary(delivery) and isinstance(reply, str):
        summary = run_summary(redact_egress_text(reply))
        if summary:
            lines.append(text["result"].format(summary=summary))
    lines.append(text["closing"])
    return "\n".join(lines)
