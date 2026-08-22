"""Per-run policy hooks for the GitHub channel.

The generic ``ChannelManager`` looks up a :class:`ChannelRunPolicy`
keyed on ``msg.channel_name`` and applies it after ``_resolve_run_params``
but before the agent runs. The GitHub channel registers its policy
entry from :func:`register_policy`, called once from the gateway
bootstrap.

Keeping the GitHub-specific provider closure here (rather than inline
in ``ChannelManager``) lets every new webhook channel ship its own
``run_policy.py`` with the same shape, with no edits to the manager.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.channels.message_bus import InboundMessage

logger = logging.getLogger(__name__)


async def inject_github_credentials(msg: InboundMessage, run_context: dict[str, Any]) -> None:
    """Install a GitHub App installation token in ``run_context``.

    The GitHub fan-out dispatcher carries each binding's
    ``installation_id`` in ``msg.metadata["github"]``. We mint a
    short-lived (1h) installation token and put the resulting **string**
    into ``run_context["github_token"]``.

    Why a string and not a closure:
        ``run_context`` is passed to ``client.runs.wait(context=…)``
        on the ``langgraph_sdk`` HTTP client, which JSON-encodes the
        payload before sending it to Gateway's LangGraph-compatible
        runtime over HTTP — even when that runtime is embedded in the
        same process. A Python callable does not survive that
        encoding (``TypeError: Type is not JSON serializable: function``).
        The harness side (``_github_env_from_runtime`` in
        ``packages/harness/deerflow/sandbox/tools.py``) already accepts
        either a ``str`` or a zero-arg sync callable from
        ``runtime.context["github_token"]``; only the ``str`` shape
        round-trips through the SDK transport, so that is what we
        ship.

    Failure modes for autonomous runs that span past the 1h token TTL:
        The minted token is valid for 1h. Most agent runs complete well
        inside that window. Truly long coder runs (multi-hour refactors
        on the higher ``recursion_limit=250`` ceiling) may see a 401 on
        a late ``git push`` / ``gh pr create``. The fix for that —
        re-installing a token-refresh hook on the **runtime side** by
        pushing the ``installation_id`` through ``run_context`` and
        looking up a process-local provider in the harness — is
        deliberately deferred: it crosses the harness/app boundary
        (``tests/test_harness_boundary.py``) and needs a registered
        token-provider lookup, not a string-vs-closure switch.

    Minting on the bus-consumer side (not in the webhook route) keeps
    GitHub's 10s delivery timeout safe. Mint failures propagate up to
    :meth:`ChannelManager._apply_channel_policy`, which logs and lets
    the run proceed without credentials (read-only is better than no
    response).
    """
    if msg.channel_name != "github":
        return
    meta = msg.metadata if isinstance(msg.metadata, dict) else {}
    gh = meta.get("github")
    if not isinstance(gh, dict):
        return
    installation_id = gh.get("installation_id")
    if not isinstance(installation_id, int) or installation_id <= 0:
        return

    from app.gateway.github.app_auth import mint_installation_token

    # Mint and ship the token string. ``mint_installation_token`` caches
    # with a 5-min leeway, so subsequent runs against the same
    # installation reuse the cached token until ~55 min into its TTL.
    # Failures (bad App id, wrong installation_id, missing private key)
    # propagate to ``_apply_channel_policy``, which handles logging
    # without dropping the delivery.
    token = await mint_installation_token(installation_id)
    run_context["github_token"] = token
    logger.info(
        "[github-run-policy] installed installation token for installation_id=%s (TTL ~1h)",
        installation_id,
    )


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
        # Autonomous coder runs (clone -> edit -> test -> push -> PR)
        # routinely need more than the 100 super-step interactive ceiling.
        # Per-agent overrides via GitHubAgentConfig.recursion_limit still
        # win (read in ChannelManager._resolve_run_params from msg.metadata).
        default_recursion_limit=250,
        credentials_provider=inject_github_credentials,
        # GitHub deliveries are HMAC-authenticated at the webhook route,
        # and the binding from "sender" to DeerFlow user is encoded in
        # the agent's config.yaml ownership (not in the channel-connections
        # table). There is no per-sender /connect handshake — opting out
        # of the bound-identity gate is what lets webhook events reach
        # the agent even when channel_connections.enabled=True for
        # interactive IM channels in the same deployment.
        requires_bound_identity=False,
        # GitHub agents post their own outbound to the issue/PR via the
        # ``gh`` CLI in the sandbox; the channel's ``send`` is log-only
        # by design. We don't need to keep an HTTP stream open on
        # ``runs.wait`` for ~6-minute coding runs and then watch it die
        # at the SDK's 300s ``httpx.ReadTimeout``. Fire-and-forget swaps
        # the manager call to ``runs.create`` (returns immediately once
        # the run is ``pending``) and skips the response-extraction +
        # outbound-publish block. ``ConflictError`` on a busy thread is
        # still raised synchronously by ``start_run`` before the run is
        # accepted, so the busy-thread path is preserved.
        fire_and_forget=True,
    )


# Auto-register on import. Splitting CHANNEL_RUN_POLICY into
# ``app.channels.run_policy`` (not ``manager``) avoids the circular
# import that would otherwise arise: this module is imported via the
# github package, which the manager's shim methods reach into.
register_policy()
