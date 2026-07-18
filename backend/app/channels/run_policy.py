"""Per-channel run policy registry.

Holds the global ``CHANNEL_RUN_POLICY`` map and its :class:`ChannelRunPolicy`
descriptor. Split into its own module so channels can register their own
policy entries (typically as a side-effect of importing their package)
without creating a circular dependency on :mod:`app.channels.manager`.

The dispatch path in :class:`app.channels.manager.ChannelManager` looks
up policy entries by ``msg.channel_name`` and applies them after
``_resolve_run_params``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.channels.message_bus import InboundMessage


@dataclass(frozen=True, slots=True)
class ChannelRunPolicy:
    """Per-channel knobs applied by :meth:`ChannelManager._apply_channel_policy`.

    Webhook-driven channels (GitHub today; others later) need four
    things the generic interactive-chat path does not: a higher
    ``recursion_limit`` for autonomous long runs, suppression of
    ``ask_clarification`` (no human is synchronously present), a
    credentials provider that mints platform tokens for the agent, and
    an opt-out from the per-sender bound-identity gate (authenticity is
    enforced at the webhook route by HMAC, and there is no equivalent
    of a per-user ``/connect`` handshake to perform).

    Declaring all four on one dataclass keeps the channel's run
    behavior in a single discoverable place and turns "add a new
    webhook channel" into a one-row registration instead of touching
    multiple separate methods on the manager.

    Attributes:
        is_interactive: When False, the manager sets
            ``run_context["disable_clarification"] = True`` so
            ``ClarificationMiddleware`` returns a "proceed with best
            judgment" ToolMessage instead of interrupting via
            ``Command(goto=END)``. Defaults to True (the safe default
            for an IM channel).
        default_recursion_limit: When set, the manager raises
            ``run_config["recursion_limit"]`` to ``max(existing,
            limit)``. None leaves the global default (100) untouched —
            interactive chat turns don't need 250 super-steps.
        credentials_provider: Optional async hook that mutates
            ``run_context`` with platform-specific credentials. Called
            after ``_resolve_run_params``. Exceptions are caught and
            logged so a credential failure degrades gracefully (agent
            runs read-only) instead of dropping the delivery.
        requires_bound_identity: When False, the manager skips the
            per-sender bound-identity gate (``_get_bound_identity_rejection``)
            for this channel even when ``channel_connections.enabled`` is
            on. Webhook-authenticated channels (GitHub) have no
            per-sender ``/connect`` handshake — authenticity is enforced
            by HMAC at the webhook route, and the binding from "sender"
            to DeerFlow user is encoded in the agent's ``config.yaml``
            ownership, not in the channel-connections table. Defaults to
            True (the safe default for an interactive IM channel).
        fire_and_forget: When True, the manager schedules the run with
            ``runs.create`` (returns immediately once the run is
            ``pending``) instead of ``runs.wait`` (which keeps an HTTP
            stream open for the entire run lifetime). Channels that do
            their own outbound during the run — e.g. GitHub, where the
            agent posts to the issue/PR via the ``gh`` CLI in its
            sandbox — don't need the manager to ferry a final state
            back. Eliminates the SDK's 300s ``httpx.ReadTimeout`` on
            runs that legitimately take more than 5 minutes, and the
            false "internal error" outbound that follows when it
            fires. Defaults to False (the safe default for an
            interactive IM channel that depends on the manager to
            publish the agent's reply).
        serialize_thread_runs: When True, the manager serializes
            same-thread inbound turns for this channel instead of
            surfacing the runtime's generic busy-thread error. This is
            useful for chat surfaces like Feishu topics where rapid
            follow-up messages should queue behind the active turn while
            unrelated DeerFlow threads continue concurrently. Defaults
            to False so existing channels keep the runtime's native
            multitask behavior unless they opt in explicitly.
    """

    is_interactive: bool = True
    default_recursion_limit: int | None = None
    credentials_provider: Callable[[InboundMessage, dict[str, Any]], Awaitable[None]] | None = None
    requires_bound_identity: bool = True
    fire_and_forget: bool = False
    serialize_thread_runs: bool = False


# Channel name → policy. Channels absent from this map fall through to
# the policy default (an interactive IM channel with no credential
# plumbing) — which is what every IM channel had before GitHub. Webhook
# channels register their entry at package-import time (see
# ``app.gateway.github.run_policy``).
CHANNEL_RUN_POLICY: dict[str, ChannelRunPolicy] = {}
