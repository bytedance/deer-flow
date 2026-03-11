"""Cron job execution handler - invokes LangGraph agent for scheduled tasks."""

from __future__ import annotations

import logging
import os
from typing import Any

from .types import CronJob

logger = logging.getLogger(__name__)

DEFAULT_LANGGRAPH_URL = "http://localhost:2024"
DEFAULT_ASSISTANT_ID = "lead_agent"
DEFAULT_RUN_CONFIG: dict[str, Any] = {"recursion_limit": 100}
DEFAULT_RUN_CONTEXT: dict[str, Any] = {}

# LangGraph SDK client (lazy)
_langgraph_client = None


def _resolve_langgraph_url() -> str:
    env_url = os.getenv("DEERFLOW_LANGGRAPH_URL")
    if env_url:
        return env_url.rstrip("/")

    return DEFAULT_LANGGRAPH_URL


def _get_client():
    """Return the langgraph_sdk async client, creating it on first use."""
    global _langgraph_client
    if _langgraph_client is None:
        from langgraph_sdk import get_client

        _langgraph_client = get_client(url=_resolve_langgraph_url())
    return _langgraph_client


def _build_run_settings(job: CronJob, thread_id: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Build assistant, config, and context for a scheduled run."""
    payload = job.payload
    assistant_id = payload.assistant_id or DEFAULT_ASSISTANT_ID
    if not isinstance(assistant_id, str) or not assistant_id.strip() or assistant_id == "default":
        assistant_id = DEFAULT_ASSISTANT_ID

    run_config = dict(DEFAULT_RUN_CONFIG)

    run_context = dict(DEFAULT_RUN_CONTEXT)
    run_context.update(
        {
            "thread_id": thread_id,
            "is_cron": True,
            "cron_job_id": job.id,
            "cron_job_name": job.name,
            "is_plan_mode": False,
            "thinking_enabled": True,
            "subagent_enabled": False,
        }
    )

    if payload.agent_name and payload.agent_name != "default":
        run_context["agent_name"] = payload.agent_name
    if payload.thinking_enabled is not None:
        run_context["thinking_enabled"] = payload.thinking_enabled
    if payload.subagent_enabled is not None:
        run_context["subagent_enabled"] = payload.subagent_enabled
    if payload.channel:
        run_context["channel_name"] = payload.channel
    if payload.to:
        run_context["chat_id"] = payload.to
    if payload.thread_ts:
        run_context["thread_ts"] = payload.thread_ts

    return assistant_id, run_config, run_context


def _extract_response_text(result: dict | list) -> str:
    """Extract the last AI message text from a LangGraph runs.wait result."""
    if isinstance(result, list):
        messages = result
    elif isinstance(result, dict):
        messages = result.get("messages", [])
    else:
        return ""

    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue

        msg_type = msg.get("type")

        # Stop at the last human message
        if msg_type == "human":
            break

        # Check for tool messages from ask_clarification
        if msg_type == "tool" and msg.get("name") == "ask_clarification":
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                return content

        # Regular AI message with text content
        if msg_type == "ai":
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                return content
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                text = "".join(parts)
                if text:
                    return text
    return ""


async def handle_cron_job(job: CronJob) -> str | None:
    """Execute a cron job by invoking the LangGraph agent.

    This is the on_job callback for the CronService.

    Args:
        job: The cron job to execute

    Returns:
        Result string or None
    """
    logger.info("[CronHandler] executing job '%s' (id=%s)", job.name, job.id)

    try:
        client = _get_client()
        payload = job.payload

        # Determine thread_id: use existing or create new
        thread_id = payload.thread_id
        if not thread_id:
            thread = await client.threads.create()
            thread_id = thread["thread_id"]
            logger.info("[CronHandler] created new thread: %s", thread_id)
        else:
            logger.info("[CronHandler] using existing thread: %s", thread_id)

        assistant_id, run_config, run_context = _build_run_settings(job, thread_id)
        scheduled_prompt = (
            "[Scheduled Task] Timer finished.\n\n"
            f"Task '{job.name}' has been triggered.\n"
            f"Scheduled instruction: {payload.message}"
        )

        # Invoke the agent
        result = await client.runs.wait(
            thread_id,
            assistant_id,
            input={"messages": [{"role": "human", "content": scheduled_prompt}]},
            config=run_config,
            context=run_context,
        )

        response_text = _extract_response_text(result)
        logger.info(
            "[CronHandler] job '%s' completed, response_len=%d",
            job.name,
            len(response_text) if response_text else 0,
        )

        # Deliver result to channel if requested
        if payload.deliver and payload.channel and payload.to:
            await _deliver_to_channel(
                payload.channel,
                payload.to,
                response_text,
                thread_id,
                thread_ts=payload.thread_ts,
            )

        return response_text or None

    except Exception as e:
        logger.error("[CronHandler] job '%s' failed: %s", job.name, e, exc_info=True)
        raise


async def _deliver_to_channel(
    channel_name: str,
    chat_id: str,
    text: str,
    thread_id: str,
    *,
    thread_ts: str | None = None,
) -> None:
    """Deliver cron job result to a channel via MessageBus."""
    from src.channels.message_bus import OutboundMessage
    from src.channels.service import get_channel_service

    channel_service = get_channel_service()
    if channel_service is None:
        logger.warning("[CronHandler] ChannelService not available, cannot deliver result")
        return

    if not text:
        text = "(Task completed with no output)"

    outbound = OutboundMessage(
        channel_name=channel_name,
        chat_id=chat_id,
        thread_id=thread_id,
        text=text,
        is_final=True,
        thread_ts=thread_ts,
    )

    logger.info(
        "[CronHandler] delivering result to channel=%s, chat_id=%s",
        channel_name,
        chat_id,
    )
    await channel_service.bus.publish_outbound(outbound)
