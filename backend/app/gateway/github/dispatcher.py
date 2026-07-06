"""Fan out a verified GitHub webhook delivery onto the channel bus.

This module replaces the old "build prompt, create thread, run agent,
post comment" one-shot dispatcher.  In the new architecture GitHub is a
first-class :class:`Channel` (see ``app/channels/github.py``):

    POST /api/webhooks/github
        → verify HMAC (route)
        → :func:`fanout_event` (this module)
            • filter bots
            • look up bound agents
            • apply per-binding trigger filter
            • publish one :class:`InboundMessage` per surviving agent
        → ChannelManager picks it up off the bus
            • resolves run params (agent_name comes from message metadata)
            • creates thread / runs lead_agent with the custom-agent name
            • publishes outbound message
        → GitHubChannel.send() posts the reply as a GitHub comment

The webhook handler stays cheap (no langgraph calls) so GitHub's 10-second
delivery timeout is never at risk.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus
from app.gateway.github.identity import extract_target, resolve_thread_id
from app.gateway.github.prompts import build_prompt
from app.gateway.github.registry import build_github_agent_registry, lookup_agents
from app.gateway.github.triggers import event_should_fire
from deerflow.config.agents_config import GitHubAgentConfig

logger = logging.getLogger(__name__)


def _is_self_event(
    event: str,
    payload: dict[str, Any],
    agent_name: str,
    github: GitHubAgentConfig,
) -> bool:
    """Return True if this event was triggered by *this agent itself*.

    Checks whether ``sender.login`` (with the ``[bot]`` suffix stripped)
    matches one of the agent's self-identities. In order of preference:

    1. ``github.bot_login`` — the explicit GitHub App login this agent
       posts as. Set this when the agent's ``mention_login`` (the handle
       humans type to invoke it) differs from its actual posting identity.
    2. Every ``mention_login`` declared across the agent's bindings — the
       posting identity may match any handle the agent listens for, so we
       aggregate across all bindings, not just the one for the current
       ``(repo, event)``.
    3. The agent's own ``name`` as a final fallback — but ONLY when neither
       of the above is configured. Otherwise a real GitHub user whose
       login happens to equal an agent's directory name would be silently
       dropped here. ``agent.name`` is the same charset as a GitHub login
       (``^[A-Za-z0-9-]+$``), so collisions like ``reviewer`` or ``coder``
       are entirely possible.

    This is the per-agent self-loop gate: we skip events triggered by our
    own bot account (e.g. the coder replying to a PR, which would re-trigger
    the reviewer) but NOT events from other bots like Copilot or CodeRabbit —
    those are legitimate signals the agent should see.
    """
    sender = payload.get("sender") or {}
    if not isinstance(sender, dict):
        return False
    sender_login = sender.get("login")
    if not isinstance(sender_login, str):
        return False

    # Strip the GitHub bot suffix — ``llm-gateway-ai[bot]`` → ``llm-gateway-ai``.
    if sender_login.endswith("[bot]"):
        sender_login = sender_login[:-5]

    # Build the self-identity set: explicit bot_login wins, then every
    # mention_login the agent declares across its bindings (the agent's
    # posting identity is global, so we don't narrow to the current event).
    # ``agent.name`` is a TRUE fallback — only added when nothing explicit
    # was configured, so an operator who set ``bot_login`` correctly does
    # not also accidentally filter a real user whose login matches the
    # agent directory name.
    self_logins: set[str] = set()
    bot_login = github.bot_login
    if isinstance(bot_login, str) and bot_login.strip():
        self_logins.add(bot_login.strip())
    for binding in github.bindings:
        for trigger in binding.triggers.values():
            login = trigger.mention_login
            if isinstance(login, str) and login.strip():
                self_logins.add(login.strip())
    if not self_logins:
        self_logins.add(agent_name)

    return sender_login.lower() in {s.lower() for s in self_logins}


async def fanout_event(
    bus: MessageBus,
    event: str,
    delivery_id: str,
    payload: dict[str, Any],
    *,
    operator_default_mention_login: str | None = None,
) -> dict[str, Any]:
    """Translate one webhook delivery into N inbound messages.

    Args:
        bus: The channel ``MessageBus`` to publish inbound messages onto.
        event: ``X-GitHub-Event`` header value.
        delivery_id: ``X-GitHub-Delivery`` header value.
        payload: Parsed webhook payload.
        operator_default_mention_login: Optional fallback handle pulled
            from ``channels.github.default_mention_login`` in
            ``config.yaml``. Used in the ``require_mention`` precedence
            chain when neither the trigger nor the agent's
            ``github.bot_login`` declares one. The router resolves this
            from the live channel config and passes it through so the
            dispatcher stays decoupled from ``get_app_config()`` and
            remains testable without a singleton.

    Returns:
        A summary dict for the route response: ``{"matched_agents": [...],
        "fired_agents": [...], "skipped": [{"agent": "...", "reason": "..."}]}``.
        Useful for operator visibility when redelivering events via smee.
    """
    # 1. Extract (repo, number).
    target = extract_target(event, payload)
    if target is None:
        logger.info(
            "github_fanout: no (repo, number) target on event=%s delivery=%s, skipping",
            event,
            delivery_id,
        )
        return {"matched_agents": [], "fired_agents": [], "skipped": [{"reason": "no_target"}]}

    repo, number = target

    # 2. Bound-agent lookup. The registry is mtime-cached internally so
    #    the warm path is iterdir + stat only — but the cold path (and
    #    every first call after an operator edit) parses every
    #    config.yaml on disk. Run it off the event loop in both cases so
    #    a slow filesystem can't push us past GitHub's 10s timeout.
    registry = await asyncio.to_thread(build_github_agent_registry)
    matches = lookup_agents(registry, repo, event)
    if not matches:
        return {"matched_agents": [], "fired_agents": [], "skipped": []}

    matched_names = [m.agent.name for m in matches]
    fired: list[str] = []
    skipped: list[dict[str, str]] = []

    sender_login = (payload.get("sender") or {}).get("login")

    for match in matches:
        agent = match.agent
        # ``cfg.github`` is non-None on every match by construction —
        # the registry only emits agents that declared a ``github:`` block.
        github = agent.github
        assert github is not None
        trigger = match.trigger

        # 3. Self-event gate — skip events triggered by this agent's own
        #    bot account. Other bots (Copilot, CodeRabbit, Dependabot, …)
        #    are legitimate signals and pass through. The identity set is
        #    derived from the agent's whole ``github`` config (bot_login
        #    plus every mention_login it declares) so we don't have to
        #    re-walk the bindings here.
        if _is_self_event(event, payload, agent.name, github):
            logger.info(
                "github_fanout: agent=%s skipped (reason=self_event, sender=%s)",
                agent.name,
                sender_login,
            )
            skipped.append({"agent": agent.name, "reason": "self_event"})
            continue

        # 4. Trigger filter.
        # ``default_mention_login`` mirrors the precedence used by
        # ``_is_self_event`` above, then extended with the operator
        # default from ``channels.github.default_mention_login``:
        #
        #   1. ``trigger.mention_login`` — per-event override (handled
        #      inside ``event_should_fire``; we only pass the fallback).
        #   2. ``github.bot_login`` — the agent's own App identity.
        #   3. ``operator_default_mention_login`` — the global default
        #      from ``config.yaml`` ``channels.github.default_mention_login``,
        #      threaded through from the router.
        #   4. ``agent.name`` — last-resort fallback so the chain always
        #      resolves to something usable.
        #
        # An operator who sets ``channels.github.default_mention_login:
        # deerflow-bot`` reasonably expects every ``@deerflow-bot``
        # mention to gate on that handle by default. The previous version
        # of this expression skipped step 3 entirely, so an agent named
        # ``coder`` with ``require_mention: true`` and no per-trigger or
        # per-agent override silently required ``@coder`` mentions instead
        # of ``@deerflow-bot``.
        operator_default = (operator_default_mention_login or "").strip() or None
        default_mention_login = github.bot_login or operator_default or agent.name
        fire, reason = event_should_fire(event, payload, trigger, default_mention_login)
        if not fire:
            logger.info(
                "github_fanout: agent=%s skipped (reason=%s)",
                agent.name,
                reason,
            )
            skipped.append({"agent": agent.name, "reason": reason})
            continue

        # 5. Build prompt + publish inbound message onto the bus.
        prompt = build_prompt(event, payload)
        thread_id = resolve_thread_id(repo, number, agent.name)

        # We hand the ChannelManager a deterministic thread id via the
        # store so its _lookup_thread_id() hits on first arrival and
        # reuses the same thread on subsequent webhooks for the same
        # (PR, agent) pair. The store key is
        # ``("github", repo, f"{number}:{agent_name}")``, so each agent
        # bound to the same PR gets its own store row — coder and
        # reviewer on ``owner/repo#7`` never collide.
        # (The store accepts a pre-known thread id; manager will fall
        # through to _create_thread() the very first time.)
        topic_id = f"{number}:{agent.name}"
        msg = InboundMessage(
            channel_name="github",
            chat_id=repo,
            user_id=sender_login or "github",
            text=prompt,
            msg_type=InboundMessageType.CHAT,
            topic_id=topic_id,
            # owner_user_id drives which user bucket the run executes in
            # (custom agent lookup, sandbox, memory).
            owner_user_id=match.user_id,
            metadata={
                # Routes to the right custom agent inside the manager:
                # _resolve_run_params() pulls this and writes it into
                # run_context["agent_name"].
                "agent_name": agent.name,
                # Carried through the manager into OutboundMessage.metadata
                # so GitHubChannel.send() has the (repo, number, installation)
                # context for its log line. The channel does not post — agents
                # do that themselves via `gh` during the run.
                "github": {
                    "repo": repo,
                    "number": number,
                    "event": event,
                    "delivery_id": delivery_id,
                    "installation_id": github.installation_id,
                    "recursion_limit": github.recursion_limit,
                    "thread_id": thread_id,
                },
                # Deterministic thread id for the manager's first-create path:
                # _create_thread passes this to client.threads.create(thread_id=...)
                # so the same (repo, number) always maps to the same LangGraph
                # thread even if the channel store JSON is wiped. Subsequent
                # deliveries reuse it via the store mapping.
                "preferred_thread_id": thread_id,
            },
        )

        logger.info(
            "github_fanout: firing agent=%s repo=%s#%s event=%s reason=%s",
            agent.name,
            repo,
            number,
            event,
            reason,
        )
        await bus.publish_inbound(msg)
        fired.append(agent.name)

    return {
        "matched_agents": matched_names,
        "fired_agents": fired,
        "skipped": skipped,
    }
