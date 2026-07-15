"""Fan out a verified GitHub webhook delivery onto the channel bus.

This module replaces the old "build prompt, create thread, run agent,
post comment" one-shot dispatcher.  In the new architecture GitHub is a
first-class :class:`Channel` (see ``app/channels/github.py``):

    POST /api/webhooks/github
        → verify HMAC (route)
        → :func:`fanout_event` (this module)
            • look up bound agents
            • filter bots
            • drop redundant review-comment webhook noise, per binding
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
from deerflow.config.agents_config import GitHubAgentConfig, GitHubTriggerConfig

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


def _is_redundant_review_comment(payload: dict[str, Any]) -> bool:
    """Return True if this ``pull_request_review_comment`` has the *shape*
    of fan-out noise from a ``pull_request_review`` submission: a companion
    inline comment that the review event already covers.

    GitHub fires one ``pull_request_review_comment`` webhook per inline
    comment attached to a review submission, ON TOP OF the single
    ``pull_request_review`` event for the review as a whole. A bot
    reviewer (CodeRabbit routinely posts 20-30 inline comments per review)
    therefore floods the webhook with 20-30 near-duplicate deliveries.

    Each such companion comment carries ``pull_request_review_id`` (the id
    of the review it belongs to) and — the discriminator — no
    ``in_reply_to_id``. ``in_reply_to_id`` is only set when a human (or
    bot) is replying *within* an existing review-comment thread, which is
    a genuine new interaction, not fan-out, and must still fire.

    This mirrors the shape GitHub's REST API has always used for
    review-thread comments (``GET /repos/{owner}/{repo}/pulls/comments``),
    which the webhook ``comment`` object is drawn from:
    ``pull_request_review_id`` is present on every review-thread comment;
    ``in_reply_to_id`` is present only on replies.

    IMPORTANT: a ``True`` result is NOT by itself a "safe to drop" signal —
    see the per-binding gate in :func:`fanout_event`, which only suppresses
    a companion comment for a binding that *also* has its own
    ``pull_request_review`` trigger on the same repo AND whose *resolved*
    trigger does not itself require a mention (see the ``require_mention``
    gap note below) — i.e. an unconditional, independent path to the
    review. A binding that subscribes to ``pull_request_review_comment``
    alone never receives the parent review event, so unconditionally
    dropping its companion comments would be a silent, total loss of the
    review's inline content for it — not noise reduction (PR #4131 review
    feedback from willem-bd / zhfeng).

    ``require_mention`` gap (PR #4131 review, Medium finding, willem-bd —
    second round, against the per-binding gate above): a dual-subscribed
    binding's ``pull_request_review`` trigger is only a *guaranteed*
    independent path when that trigger does not itself gate on
    ``require_mention``. If it does, the paired review event can be
    silently dropped by :func:`app.gateway.github.triggers.event_should_fire`'s
    own mention check against ``review["body"]`` — the review's
    *top-level* summary, which this ``pull_request_review_comment``
    payload never carries (there is no way to see, from a comment
    delivery, what the sibling review's own summary said). A human
    ``@mention`` that lives only inside one inline comment — not the
    review summary — would otherwise be lost twice over: the review event
    is filtered out (``no_mention``) *and* the one inline comment that
    actually carries the mention is dropped here as "redundant", via a
    narrower path than the original bug. The per-binding gate therefore
    additionally requires ``require_mention`` to be false on the paired
    trigger before treating it as coverage. This trades a small amount of
    residual redundancy (an extra companion delivery on occasions when the
    review's own summary happened to carry the mention too, or
    ``allow_authors``/self-event would have let the review through anyway)
    for zero silent loss — the same trade the original fix already made at
    a coarser grain. It deliberately does not attempt to replay
    ``allow_authors`` or an ``actions`` whitelist that might also be
    configured on the paired trigger; those are accepted as out of scope
    for this narrower fix, same as ``self_event``.

    Residual caveat (PR #4131 review, Concern 3, zhfeng): GitHub documents
    ``pull_request_review_id`` on the review-comment schema as nullable
    ("integer or null"), confirming *some* review comments can lack a
    backing review, but public docs do not state whether the "Add single
    comment" UI action (as opposed to a multi-comment review) can ever
    produce a comment with ``pull_request_review_id`` set and
    ``in_reply_to_id`` absent *without* a companion ``pull_request_review``
    event also firing. If that combination is possible, a binding with its
    own ``pull_request_review`` trigger could still lose such a comment
    under the per-binding gate. Confirmed via a real/documented webhook
    payload capture before ruling this out; treat it as an open,
    low-probability risk rather than a settled non-issue. (Distinct from
    the ``require_mention`` gap above: this caveat questions whether the
    paired event fires *at all* for a given delivery shape; the
    ``require_mention`` gap is about a paired event that fires but is then
    filtered by its own trigger config, which the gate now accounts for.)
    """
    comment = payload.get("comment")
    if not isinstance(comment, dict):
        return False
    return comment.get("pull_request_review_id") is not None and comment.get("in_reply_to_id") is None


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

    # 3. Redundant review-comment fan-out filter — see
    #    :func:`_is_redundant_review_comment`. Whether the PAYLOAD has the
    #    shape of review fan-out is a property of the event and computed
    #    once here, but whether that fan-out is safe to DROP is a property
    #    of the individual binding: only a binding that also has its own
    #    ``pull_request_review`` trigger on this repo, WITHOUT that trigger
    #    itself requiring a mention, has a *guaranteed* independent path to
    #    the review's content — so the actual suppression decision is made
    #    per-agent below (next to the self-event gate), not here.
    #    ``review_trigger_by_binding`` reuses :func:`lookup_agents` against
    #    the registry we just built — a binding only appears in the
    #    ``(repo, "pull_request_review")`` slot if it explicitly lists that
    #    event under its own ``triggers:`` (opt-in per binding, see
    #    ``triggers.py``) — so this does not duplicate any trigger-matching
    #    logic, and it stays correctly scoped to this repo (an agent with a
    #    second binding on a *different* repo does not count). It maps to
    #    the binding's *resolved* :class:`GitHubTriggerConfig` (not just
    #    membership) so the per-agent gate below can also check
    #    ``require_mention`` — see the ``require_mention`` gap note on
    #    :func:`_is_redundant_review_comment` for why a mention-gated review
    #    trigger cannot be trusted as coverage (PR #4131 review, Medium
    #    finding, willem-bd).
    is_redundant_review_comment = event == "pull_request_review_comment" and _is_redundant_review_comment(payload)
    review_trigger_by_binding: dict[tuple[str, str], GitHubTriggerConfig] = {(m.user_id, m.agent.name): m.trigger for m in lookup_agents(registry, repo, "pull_request_review")} if is_redundant_review_comment else {}

    for match in matches:
        agent = match.agent
        # ``cfg.github`` is non-None on every match by construction —
        # the registry only emits agents that declared a ``github:`` block.
        github = agent.github
        assert github is not None
        trigger = match.trigger

        # 4. Self-event gate — skip events triggered by this agent's own
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

        # 5. Trigger filter — computed once, up front, rather than right
        #    before its own gate further below. ``default_mention_login``
        #    mirrors the precedence used by ``_is_self_event`` above, then
        #    extended with the operator default from
        #    ``channels.github.default_mention_login``:
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
        #
        # ``github.bot_login`` is normalized (whitespace-only -> None) by
        # ``GitHubAgentConfig``'s field validator, so this ``or`` chain
        # correctly falls through a misconfigured ``bot_login: "   "``
        # instead of comparing mentions against a literal whitespace
        # string. ``operator_default_mention_login`` is a plain function
        # argument (not a validated model field), so it is normalized here
        # explicitly.
        #
        # Computing this here (rather than at its old location right before
        # its own gate) lets the redundant-review-comment gate just below
        # also consult the verdict for a more precise skip reason, instead
        # of always reporting ``redundant_review_comment`` even when this
        # binding's own trigger would have skipped the event anyway for an
        # unrelated reason (PR #4131 review, Minor finding, willem-bd).
        # ``event_should_fire`` is a pure function of its arguments, so
        # computing it once here and reusing it below is not a behavior
        # change from calling it at the old step 6 location.
        operator_default = (operator_default_mention_login or "").strip() or None
        default_mention_login = github.bot_login or operator_default or agent.name
        fire, reason = event_should_fire(event, payload, trigger, default_mention_login)

        # 6. Redundant review-comment gate, per binding (PR #4131 review —
        #    willem-bd / zhfeng). Only suppress THIS binding's companion
        #    comment when it is also registered for ``pull_request_review``
        #    on this repo AND that trigger's own ``require_mention`` is not
        #    set — i.e. it has an unconditional, independent path to the
        #    review content that makes the companion comment genuinely
        #    redundant *for it*. A binding registered for
        #    ``pull_request_review_comment`` alone never receives the
        #    parent review event at all, so it still fires here even though
        #    the payload has the fan-out shape. A binding whose review
        #    trigger DOES require a mention is also not treated as covered:
        #    this ``pull_request_review_comment`` payload never carries the
        #    review's own top-level body, so there is no way to verify from
        #    here whether that mention check would actually pass for the
        #    paired review event — see the ``require_mention`` gap note on
        #    :func:`_is_redundant_review_comment`.
        #
        #    When this binding IS suppressed as redundant, the skip reason
        #    prefers this binding's own trigger verdict (``reason`` from
        #    step 5 above) over the generic ``redundant_review_comment``
        #    label whenever that verdict is ALSO a skip — e.g. this
        #    companion's own ``pull_request_review_comment`` trigger
        #    separately requires a mention it doesn't have. The event is
        #    skipped either way; this only makes the logged reason more
        #    useful for operator debugging (PR #4131 review, Minor finding,
        #    willem-bd).
        review_trigger = review_trigger_by_binding.get((match.user_id, agent.name))
        if is_redundant_review_comment and review_trigger is not None and not review_trigger.require_mention:
            skip_reason = reason if not fire else "redundant_review_comment"
            logger.info(
                "github_fanout: agent=%s skipped (reason=%s, repo=%s#%s, delivery=%s)",
                agent.name,
                skip_reason,
                repo,
                number,
                delivery_id,
            )
            skipped.append({"agent": agent.name, "reason": skip_reason})
            continue

        # 7. Apply the trigger filter's verdict from step 5.
        if not fire:
            logger.info(
                "github_fanout: agent=%s skipped (reason=%s)",
                agent.name,
                reason,
            )
            skipped.append({"agent": agent.name, "reason": reason})
            continue

        # 8. Build prompt + publish inbound message onto the bus.
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
        # Inbound dedupe identity for ChannelManager._is_duplicate_inbound,
        # mirroring the stable per-message id the other channels stamp (Slack
        # `ts`, Telegram `message_id`, WeChat/WeCom `message_id`, …) that the
        # dedupe added in PR #3584 keys on. ``X-GitHub-Delivery`` is GitHub's
        # globally-unique per-delivery GUID; it is reused verbatim when a
        # delivery is retried after a timeout or replayed via the repo/App
        # "Redeliver" button, so keying on it lets the manager absorb those
        # replays instead of re-running the agent (and its real side effects,
        # e.g. a duplicate PR comment). One delivery fans out to N agents
        # across potentially N different owning users, so the per-message id
        # is scoped to (delivery, user, agent): an identical redelivery
        # reproduces the same triples (deduped) while two agents matching the
        # same delivery — including two different users who each bind an
        # agent of the same name to the same repo+event — keep distinct ids
        # and both still fire. ``ChannelManager._inbound_dedupe_key`` indexes
        # on (channel, workspace_id, chat_id, message_id); workspace_id and
        # chat_id are both the repo here, so match.user_id is the only thing
        # that can separate two users in that key — see
        # test_dedupe_identity_distinguishes_same_agent_name_across_users.
        # Left None when the header is absent, so the manager fails open (no
        # dedupe) exactly as before rather than collapsing distinct deliveries.
        dedupe_message_id = f"{delivery_id}:{match.user_id}:{agent.name}" if delivery_id else None
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
            # Tenant key the manager's dedupe requires (it fails closed without
            # one, to avoid collapsing two workspaces). The repo is globally
            # unique and always present — mirrors Telegram/WeChat keying the
            # workspace on the chat id.
            workspace_id=repo,
            metadata={
                # Stable inbound-dedupe id keyed by the manager — see
                # ``dedupe_message_id`` above.
                "message_id": dedupe_message_id,
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
