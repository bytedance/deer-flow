"""Text of the IM ``/goal`` replies, mirroring the web goal bar.

The status reply follows ``describeGoalBar`` in
``frontend/src/components/workspace/goal-status-helpers.ts``: an active goal
wins over a met record; while a run is in flight, a stand-down left by an
earlier run is not shown; when idle, a stand-down, then a paused auto-continue,
then a plain set goal. Stop reasons are host-written codes
(``contracts/thread_goal_contract.json``) worded with the scheduled-notice
texts; the evaluator's own words and provider errors are never sent. A met goal
is cleared and recorded as ``goal_outcome``, which reads as met until the next
goal change.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from app.scheduler.notification_text import goal_reason_text
from deerflow.persistence.scheduled_task_runs.finalization import CHECK_FAILURE_CODES
from deerflow.runtime.goal import is_active_goal

_TEXT: dict[str, dict[str, str]] = {
    "en-US": {
        "goal": "Goal: {objective}",
        "met": "Goal met: {objective}",
        "met_with_assumption": "Goal met, with an assumption: {objective}",
        "none": "No active goal.",
        "in_progress": "In progress.",
        "continuing": "In progress: auto-continued {count}/{max} times.",
        "paused": "Paused: auto-continued {count}/{max} times; the run ended before the goal was confirmed.",
        "stopped": "Stopped: {reason}.",
        "stopped_bare": "Stopped.",
        "waiting_for_you": "Waiting for you: {reason}.",
        "waiting": "Waiting: {reason}.",
        "unchecked": "{reason}. It's checked again after your next message.",
        "cleared": "Goal cleared.",
        "fetch_failed": "Failed to fetch goal information.",
        "clear_failed": "Failed to clear goal.",
        "set_failed": "Failed to set goal.",
    },
    "zh-CN": {
        "goal": "目标：{objective}",
        "met": "目标已达成：{objective}",
        "met_with_assumption": "目标已达成（含假设）：{objective}",
        "none": "当前没有目标。",
        "in_progress": "进行中。",
        "continuing": "进行中：已自动续跑 {count}/{max} 次。",
        "paused": "已暂停：已自动续跑 {count}/{max} 次，运行在确认达成前结束了。",
        "stopped": "已停止：{reason}。",
        "stopped_bare": "已停止。",
        "waiting_for_you": "等你回复：{reason}。",
        "waiting": "等待中：{reason}。",
        "unchecked": "{reason}。下次发消息后会重新检查。",
        "cleared": "目标已清除。",
        "fetch_failed": "无法获取目标信息。",
        "clear_failed": "无法清除目标。",
        "set_failed": "无法设置目标。",
    },
}

# Stand-downs where the user, or something outside DeerFlow, acts next (the web bar's chips).
_WAITING_KEYS = {"needs_user_input": "waiting_for_you", "external_wait": "waiting"}


def goal_reply_text(key: str, locale: str) -> str:
    """A fixed ``/goal`` reply (``none``, ``cleared``, ``*_failed``) in ``locale``."""
    return _TEXT[locale][key]


def is_active_goal_state(value: object) -> bool:
    """An active goal with an objective, the web bar's ``isGoalState``."""
    return is_active_goal(value) and isinstance(value.get("objective"), str)


def _count(value: object) -> int:
    """A positive whole count, else 0 (the web bar's ``countOf``)."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value <= 0:
        return 0
    return math.floor(value)


def _stop_line(code: str, max_continuations: int, locale: str) -> str:
    """Why auto-continue stood down, by who acts next (the web bar's ``stopRowOf``)."""
    text = _TEXT[locale]
    if code in CHECK_FAILURE_CODES:
        # Not a verdict: the goal is checked again after the next message.
        reason = goal_reason_text(code, locale)
        return text["unchecked"].format(reason=reason[:1].upper() + reason[1:]) if reason else text["stopped_bare"]
    bare = code.removeprefix("blocked:")
    if bare == "max_continuations_reached" and max_continuations <= 0:
        # Auto-continue was off for this goal: the check just found it unmet.
        bare = "goal_not_met_yet"
    reason = goal_reason_text(bare, locale)
    if reason is None:
        return text["stopped_bare"]
    return text[_WAITING_KEYS.get(bare, "stopped")].format(reason=reason)


def goal_status_text(goal: object, outcome: object, *, running: bool, locale: str) -> str:
    """The ``/goal`` status reply: the active goal and its state, a met goal, or none.

    ``running`` says whether the thread has a run pending or in progress.
    """
    text = _TEXT[locale]
    if is_active_goal_state(goal):
        lines = [text["goal"].format(objective=goal["objective"])]
        evaluation = goal.get("last_evaluation")
        evaluation = evaluation if isinstance(evaluation, Mapping) else None
        code = evaluation.get("stand_down_reason") if evaluation is not None else None
        code = code.strip() if isinstance(code, str) else ""
        count = _count(goal.get("continuation_count"))
        maximum = _count(goal.get("max_continuations"))
        if running:
            satisfied = evaluation is not None and evaluation.get("satisfied") is True
            lines.append(text["continuing"].format(count=count, max=maximum) if not code and not satisfied and count > 0 else text["in_progress"])
        elif code:
            lines.append(_stop_line(code, maximum, locale))
        elif evaluation is not None and count > 0:
            lines.append(text["paused"].format(count=count, max=maximum))
        return "\n".join(lines)
    if isinstance(outcome, Mapping) and outcome.get("status") == "achieved" and isinstance(outcome.get("objective"), str) and isinstance(outcome.get("goal_created_at"), str):
        key = "met_with_assumption" if outcome.get("relied_on_assumption") is True else "met"
        return text[key].format(objective=outcome["objective"])
    return text["none"]
