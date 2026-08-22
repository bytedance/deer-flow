"""GitHub channel — webhook-driven IM channel for PR/issue comments.

Unlike other IM channels (Feishu, Slack, Telegram) which long-poll or use
WebSockets, GitHub delivers messages via HTTP push webhooks. This channel
therefore has a no-op ``start``/``stop`` — inbound messages arrive through
``POST /api/webhooks/github`` and are published to the bus by the webhook
route handler.

**The channel does not auto-post the agent's final response.** Each GitHub
agent (coder, reviewer, …) has the `gh` CLI in its sandbox and is expected to
decide for itself what — if anything — to post on the issue or PR, and to use
``gh issue comment`` / ``gh pr comment`` / ``gh pr create`` during the run.
The agent's final assistant message is logged at INFO for visibility in
``gateway.log`` but is **not** sent to GitHub.

Why log-only rather than auto-post:

- Two agents can bind the same event (e.g. coder + reviewer on a mention).
  If both auto-posted their final messages, the user would see two replies
  for every mention even when only one had useful work to do. Letting the
  LLM call ``gh`` mid-run means silence is just "the LLM did not call gh."
- The agent often wants to post *intermediate* updates (an issue comment
  linking the PR, a separate comment on a new sub-issue, …) — the
  auto-post-the-final-message contract didn't model that and forced the
  final message to play double duty.
- The dispatcher's per-agent ``_is_self_event`` gate already prevents the
  comments the LLM posts via ``gh`` from looping the webhook back into a
  new run for the same agent.
"""

from __future__ import annotations

import logging
from typing import Any

from app.channels.base import Channel
from app.channels.message_bus import MessageBus, OutboundMessage

logger = logging.getLogger(__name__)


class GitHubChannel(Channel):
    """Webhook-driven GitHub channel.

    Inbound: ``POST /api/webhooks/github`` publishes ``InboundMessage`` to
    the bus. Outbound: ``send`` is log-only (see module docstring) — agents
    post to GitHub themselves via the ``gh`` CLI in their sandbox.

    Configuration keys (in ``config.yaml`` under ``channels.github``):

        - ``enabled`` (bool): set to ``true`` to activate.
        - ``default_mention_login`` (str, optional): bot handle used by
          ``require_mention`` when the agent binding does not set one.
          Falls back to ``"deerflow-bot"``.
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        super().__init__(name="github", bus=bus, config=config)

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Register the outbound callback.

        GitHub is push-based (webhooks), so no long-poll or socket
        listener is needed. We only register for outbound replies so the
        agent's final message gets logged.
        """
        if self._running:
            return
        self.bus.subscribe_outbound(self._on_outbound)
        self._running = True
        logger.info("GitHubChannel started (webhook-driven, no polling)")

    async def stop(self) -> None:
        """Unregister the outbound callback."""
        if not self._running:
            return
        self.bus.unsubscribe_outbound(self._on_outbound)
        self._running = False
        logger.info("GitHubChannel stopped")

    # -- outbound ----------------------------------------------------------

    async def send(self, msg: OutboundMessage) -> None:
        """Log the agent's final message — do NOT post it to GitHub.

        GitHub agents post to issues/PRs themselves via ``gh`` mid-run; the
        final assistant message is logged for ``gateway.log`` visibility but
        is not delivered to the platform. See the module docstring for why.

        Metadata layout (read for logging context only):
            - ``repo`` (str, e.g. ``"owner/name"``) — falls back to ``chat_id``
            - ``number`` (int, issue or PR number)
            - ``installation_id`` (int)
        """
        gh = msg.metadata.get("github", {}) if isinstance(msg.metadata, dict) else {}
        if not isinstance(gh, dict):
            gh = {}

        repo = gh.get("repo") or msg.chat_id
        number = gh.get("number")

        body = msg.text or ""

        logger.info(
            "[GitHubChannel] final message from agent for %s#%s (text_len=%d) — not posted; agents use `gh` directly",
            repo,
            number,
            len(body),
        )
        # Mirror the body itself at DEBUG so operators can correlate without
        # spamming INFO. Truncate to keep log lines bounded.
        if body:
            logger.debug("[GitHubChannel] final body (truncated to 2000 chars): %s", body[:2000])
