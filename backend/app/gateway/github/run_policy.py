"""Per-run policy for inbound GitHub events."""

from __future__ import annotations


def register_policy() -> None:
    """Register the GitHub channel's :class:`ChannelRunPolicy` entry.

    Called once from the gateway bootstrap so the manager finds the
    policy on first delivery. Also invoked at module-import time below
    so test code that constructs a :class:`ChannelManager` directly
    (bypassing the gateway bootstrap) gets the same registration as
    soon as anything inside ``app.gateway.github`` is imported.
    Idempotent — registering twice just overwrites the same row.
    """
    from app.channels.run_policy import CHANNEL_RUN_POLICY, ChannelRunPolicy

    CHANNEL_RUN_POLICY["github"] = ChannelRunPolicy(
        # GitHub webhooks have no synchronous human — ask_clarification
        # would dead-end the run.
        is_interactive=False,
        interaction_mode="webhook",
        # Autonomous coder runs (clone -> edit -> test -> push -> PR)
        # routinely need more than 100 super-steps.
        # Per-agent overrides via GitHubAgentConfig.recursion_limit still
        # win (read in ChannelManager._resolve_run_params from msg.metadata).
        default_recursion_limit=250,
        # GitHub deliveries are HMAC-authenticated at the webhook route,
        # and the binding from "sender" to DeerFlow user is encoded in
        # the agent's config.yaml ownership (not in the channel-connections
        # table). There is no per-sender /connect handshake — opting out
        # of the bound-identity gate is what lets webhook events reach
        # the agent even when channel_connections.enabled=True for
        # interactive IM channels in the same deployment.
        requires_bound_identity=False,
        # GitHub agents use configured tools for outbound actions. The
        # channel's ``send`` is log-only by design. We don't need to keep an HTTP stream open on
        # ``runs.wait`` for ~6-minute coding runs and then watch it die
        # at the SDK's 300s ``httpx.ReadTimeout``. Fire-and-forget swaps
        # the manager call to ``runs.create`` (returns immediately once
        # the run is ``pending``) and skips the response-extraction +
        # outbound-publish block. ``ConflictError`` on a busy thread is
        # still raised synchronously by ``start_run`` before the run is
        # accepted, so the busy-thread path is preserved.
        fire_and_forget=True,
        # GitHub's ``send`` is log-only,
        # so a busy-thread ``THREAD_BUSY_MESSAGE`` is otherwise invisible to
        # the commenter — a concurrent comment is silently dropped from
        # their point of view (issue #4121). Buffering + draining follow-ups
        # once the busy run ends directly fixes that for the one channel
        # where it is a real, routinely-triggered problem; other
        # fire_and_forget channels keep the dataclass default (False) until
        # they have the same log-only-send shape and opt in explicitly.
        buffer_followups_on_busy=True,
    )


# Auto-register on import. Splitting CHANNEL_RUN_POLICY into
# ``app.channels.run_policy`` (not ``manager``) avoids the circular
# import that would otherwise arise: this module is imported via the
# github package, which the manager's shim methods reach into.
register_policy()
