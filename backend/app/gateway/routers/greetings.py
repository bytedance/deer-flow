"""Personalized greeting endpoint for new conversation threads."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from deerflow.agents.memory.updater import get_memory_data
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.rpc.machine_service import MachineServiceClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/threads", tags=["greetings"])

_GREETING_TIMEOUT_SECONDS = 2.0
_ALERT_QUERY_TIMEOUT_SECONDS = 0.5
_TICKET_QUERY_TIMEOUT_SECONDS = 0.5
_MAINTENANCE_QUERY_TIMEOUT_SECONDS = 0.5
_TICKET_STALE_DAYS = 30
_MAINTENANCE_WINDOW_DAYS = 14
_CLOSED_RECENT_DAYS = 7

_GREETING_TEMPLATES: dict[str, dict[str, str]] = {
    "zh-CN": {
        "morning": "早上好！有什么我可以帮您的吗？",
        "afternoon": "下午好！今天需要分析什么？",
        "evening": "晚上好！有什么需要我帮忙的吗？",
    },
    "en-US": {
        "morning": "Good morning! How can I help you today?",
        "afternoon": "Good afternoon! What would you like to analyze?",
        "evening": "Good evening! What can I help you with?",
    },
}

_DEFAULT_SUGGESTIONS: dict[str, list[str]] = {
    "zh-CN": ["查看设备状态", "生成今日报告", "分析异常趋势"],
    "en-US": ["Check device status", "Generate today's report", "Analyze anomaly trends"],
}


def _detect_language(text: str | None) -> str:
    if not text:
        return "zh-CN"
    cjk_count = sum(1 for ch in text if "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿")
    latin_count = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    return "zh-CN" if cjk_count >= latin_count else "en-US"


def _time_of_day_key() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return "morning"
    if hour < 18:
        return "afternoon"
    return "evening"


async def _get_active_alerts(user_id: int, org_id: int) -> list[dict[str, Any]]:
    """Query devices with active alarms (non-blocking, 500ms timeout)."""
    try:
        client = MachineServiceClient()
        result = await asyncio.wait_for(
            client.get_machine_detail_info(
                user_id=user_id,
                org_id=org_id,
                alarm_status="alarm",
                page_size=5,
            ),
            timeout=_ALERT_QUERY_TIMEOUT_SECONDS,
        )
        if isinstance(result, dict) and "records" in result:
            return result["records"][:5]
        return []
    except (asyncio.TimeoutError, Exception) as e:
        logger.debug("Alert query failed: %s", e)
        return []


async def _get_recent_closure_tickets(user_id: int, org_id: int) -> list[dict[str, Any]]:
    """Query recently closed tickets (non-blocking, 500ms timeout).

    Filters out tickets closed more than _TICKET_STALE_DAYS ago.
    """
    try:
        client = MachineServiceClient()
        cutoff = datetime.now(timezone.utc) - timedelta(days=_TICKET_STALE_DAYS)
        result = await asyncio.wait_for(
            client.get_machine_detail_info(
                user_id=user_id,
                org_id=org_id,
                alarm_status="all",
                page_size=5,
            ),
            timeout=_TICKET_QUERY_TIMEOUT_SECONDS,
        )
        if isinstance(result, dict) and "records" in result:
            recent = []
            for record in result["records"]:
                closed_at = record.get("closed_at") or record.get("update_time")
                if closed_at:
                    try:
                        closed_dt = datetime.fromisoformat(str(closed_at).replace("Z", "+00:00"))
                        if closed_dt.replace(tzinfo=timezone.utc) >= cutoff:
                            recent.append(record)
                    except (ValueError, TypeError):
                        pass
            return recent[:5]
        return []
    except (asyncio.TimeoutError, Exception) as e:
        logger.debug("Closure ticket query failed: %s", e)
        return []


async def _get_upcoming_maintenance(user_id: int, org_id: int) -> list[dict[str, Any]]:
    """Query equipment with scheduled maintenance within _MAINTENANCE_WINDOW_DAYS (non-blocking)."""
    try:
        client = MachineServiceClient()
        result = await asyncio.wait_for(
            client.get_machine_detail_info(
                user_id=user_id,
                org_id=org_id,
                alarm_status="all",
                page_size=10,
            ),
            timeout=_MAINTENANCE_QUERY_TIMEOUT_SECONDS,
        )
        if isinstance(result, dict) and "records" in result:
            now = datetime.now(timezone.utc)
            window = now + timedelta(days=_MAINTENANCE_WINDOW_DAYS)
            upcoming = []
            for record in result["records"]:
                maint_date = record.get("next_maintenance_date") or record.get("maintenance_date")
                if maint_date:
                    try:
                        maint_dt = datetime.fromisoformat(str(maint_date).replace("Z", "+00:00"))
                        if now <= maint_dt.replace(tzinfo=timezone.utc) <= window:
                            upcoming.append(record)
                    except (ValueError, TypeError):
                        pass
            return upcoming[:5]
        return []
    except (asyncio.TimeoutError, Exception) as e:
        logger.debug("Maintenance query failed: %s", e)
        return []


def _sort_suggestions_by_priority(suggestions: list[str], memory: dict[str, Any]) -> list[str]:
    """Sort suggestions by equipment criticality and recent anomalies.

    For now, this is a simple implementation that prioritizes suggestions
    containing keywords from recent memory facts. Future enhancement could
    query equipment metadata for criticality levels.
    """
    recent_facts = memory.get("recentMonths", "") + " " + memory.get("userContext", {}).get("workContext", "")

    def priority_score(suggestion: str) -> int:
        score = 0
        for keyword in ["泵", "pump", "振动", "vibration", "异常", "anomaly", "告警", "alarm"]:
            if keyword in suggestion.lower() or keyword in recent_facts.lower():
                score += 1
        return score

    return sorted(suggestions, key=priority_score, reverse=True)


def _build_suggestions(memory: dict[str, Any], lang: str) -> list[str]:
    defaults = _DEFAULT_SUGGESTIONS.get(lang, _DEFAULT_SUGGESTIONS["zh-CN"])
    suggestions: list[str] = []

    recent_months = memory.get("recentMonths", "")
    if recent_months and lang == "zh-CN":
        suggestions.append("继续上次的工作")
    elif recent_months and lang == "en-US":
        suggestions.append("Continue where we left off")

    facts = memory.get("facts", [])
    for fact in facts[:2]:
        content = fact.get("content", "") if isinstance(fact, dict) else ""
        if content and len(content) < 40:
            suggestions.append(content)
            break

    while len(suggestions) < 3:
        remaining = [s for s in defaults if s not in suggestions]
        if not remaining:
            break
        suggestions.append(remaining[0])

    suggestions = _sort_suggestions_by_priority(suggestions[:3], memory)
    return suggestions[:3]


async def _generate_greeting(thread_id: str) -> dict[str, Any]:
    user_id = get_effective_user_id()
    memory = get_memory_data(user_id=user_id)

    last_message_lang = _detect_language(None)

    lang = last_message_lang
    time_key = _time_of_day_key()
    templates = _GREETING_TEMPLATES.get(lang, _GREETING_TEMPLATES["zh-CN"])
    greeting_text = templates.get(time_key, templates["morning"])
    suggestions = _build_suggestions(memory, lang)

    work_context = memory.get("userContext", {}).get("workContext", "")
    if work_context and lang == "zh-CN":
        greeting_text = f"您好！我记得您之前关注的是{work_context[:30]}，需要继续跟进吗？"
    elif work_context and lang == "en-US":
        greeting_text = f"Hi! I recall you were working on {work_context[:30]}. Would you like to continue?"

    pending_followup = None
    for fact in memory.get("facts", []):
        if isinstance(fact, dict) and fact.get("category") == "followup":
            pending_followup = fact.get("content", "")
            break

    if pending_followup and lang == "zh-CN":
        greeting_text = f"上次您分析了相关内容，需要我继续跟进吗？"
    elif pending_followup and lang == "en-US":
        greeting_text = "Last time you analyzed some data. Would you like me to follow up?"

    alerts = await _get_active_alerts(user_id=1, org_id=1)
    if alerts:
        alert_count = len(alerts)
        if lang == "zh-CN":
            alert_msg = f"⚠️ 注意：当前有 {alert_count} 台设备存在告警，需要立即查看吗？"
        else:
            alert_msg = f"⚠️ Alert: {alert_count} device(s) currently have active alarms. Would you like to check?"
        greeting_text = f"{alert_msg}\n\n{greeting_text}"

    tickets, maintenance = await asyncio.gather(
        _get_recent_closure_tickets(user_id=1, org_id=1),
        _get_upcoming_maintenance(user_id=1, org_id=1),
    )

    follow_ups: list[str] = []

    if tickets:
        ticket_names = [t.get("device_name") or t.get("name") or "" for t in tickets[:2]]
        ticket_names = [n for n in ticket_names if n]
        if ticket_names:
            names_str = "、".join(ticket_names)
            if lang == "zh-CN":
                follow_ups.append(f"📋 您之前为{names_str}开的闭环单已有新进展，需要查看吗？")
            else:
                follow_ups.append(f"📋 Closure tickets for {names_str} have updates. Want to check?")

    if maintenance:
        maint_names = [m.get("device_name") or m.get("name") or "" for m in maintenance[:2]]
        maint_names = [n for n in maint_names if n]
        if maint_names:
            names_str = "、".join(maint_names)
            if lang == "zh-CN":
                follow_ups.append(f"🔧 {names_str}的预防性维护日期临近，需要生成维护前状态评估报告吗？")
                suggestions = [f"查看{maint_names[0]}维护计划" if maint_names else "查看维护计划"] + suggestions[:2]
            else:
                follow_ups.append(f"🔧 Maintenance for {names_str} is approaching. Generate a pre-maintenance assessment?")
                suggestions = [f"Check {maint_names[0]} maintenance plan" if maint_names else "Check maintenance plan"] + suggestions[:2]

    if follow_ups:
        greeting_text = f"{greeting_text}\n\n" + "\n".join(follow_ups)

    return {
        "greeting": greeting_text,
        "suggestions": suggestions,
        "language": lang,
        "alert_count": len(alerts),
    }


@router.get("/{thread_id}/greeting")
async def get_greeting(thread_id: str) -> dict[str, Any]:
    try:
        result = await asyncio.wait_for(
            _generate_greeting(thread_id),
            timeout=_GREETING_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("Greeting generation timed out for thread %s, using default", thread_id)
        lang = "zh-CN"
        time_key = _time_of_day_key()
        result = {
            "greeting": _GREETING_TEMPLATES[lang][time_key],
            "suggestions": _DEFAULT_SUGGESTIONS[lang],
            "language": lang,
        }
    return result
