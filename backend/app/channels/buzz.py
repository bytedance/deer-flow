"""Buzz (Nostr) channel: DeerFlow as a member of a Buzz workspace relay.

One NIP-42-authenticated WebSocket to ``relay_url``. Inbound kind-9 chat events are
gated (pubkey allowlist, then mention/DM/thread-follow) and published to the bus;
outbound replies post one kind-9 message and then stream via kind-40003 in-place edits.

Subscriptions are CHANNEL-SCOPED, which is the shape the relay actually serves:

- ``REQ {"kinds":[9]}`` (global) is accepted and answered with EOSE, but the relay
  never fans a chat event out to it -- a connector subscribed that way authenticates
  successfully and then receives nothing, forever. Proved against a live relay.
- ``REQ {"kinds":[9], "#h":[uuid]}`` works, and a multi-value ``#h`` does NOT, so
  there is exactly one chat subscription per channel (matching Buzz's own agent
  harness, whose ``subscribe_channel_from`` is likewise per channel).

So each connection: authenticate, discover the channels this identity belongs to
with a historical ``kinds:[39000]`` REQ, open one ``#h`` chat subscription per
discovered channel, and keep a live ``kinds:[44100,44101] #p=<us>`` subscription so
channels we are added to (or removed from) later are picked up without a reconnect.

Every one of those subscriptions can be killed by a single relay ``CLOSED`` frame,
and each one dying is a *silent* outage (a dead chat subscription deafens one
channel; a dead ``buzz-membership`` stops us ever learning we were added to or
removed from a channel; a dead ``buzz-discovery`` kills the completeness sweep).
So a ``CLOSED`` is recovered rather than merely forgotten -- bounded by
``MAX_RESUBSCRIBE_ATTEMPTS`` per subscription per connection, and only when the
relay's stated reason suggests re-issuing the same REQ could work at all (see
``_is_transient_close``). Every subscription that goes unlistened is named at
WARNING, because "listening to nothing" must never again be indistinguishable from
"nothing is being said".

KNOWN BOUND (documented, not fixed): the relay caps historical delivery at 2000
events per subscription and serves them NEWEST-FIRST, even with a ``since``. So a
channel that accumulated more than 2000 unread messages across one disconnect
loses the oldest of them: the relay never sends them, and the watermark advances
past them as the newer ones are processed. This is the one bounded skip path that
remains, it needs a disconnect plus >2000 messages in a single channel to trigger,
and closing it would require paging the backlog with descending ``until`` queries.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any
from urllib.parse import urlparse

from app.channels import buzz_nostr
from app.channels.base import Channel
from app.channels.buzz_seen_events import BuzzSeenEventStore
from app.channels.commands import is_known_channel_command
from app.channels.connection_identity import attach_connection_identity
from app.channels.message_bus import InboundMessage, InboundMessageType, InboundQueueFullError, MessageBus, OutboundMessage

logger = logging.getLogger(__name__)

# Headroom under the relay's 64KB edit-content cap (kind-40003 events).
EDIT_MAX_BYTES = 60_000

# Ceiling for how far ahead of our own clock a peer-supplied ``created_at`` may be
# and still advance the resubscribe watermark (see ``_advance_watermark``).
MAX_FUTURE_SKEW_SECONDS = 60

# Cap on the kind-39000 metadata cache. Any relay member can publish channel
# metadata, so this map is remote-fed and would otherwise grow without bound for
# the process lifetime; evicting the oldest entry only costs us the DM mention
# exemption for that channel until its metadata is seen again (``_is_dm`` fails
# closed on a cache miss).
MAX_CACHED_CHANNELS = 512

# Cap on how many per-channel chat subscriptions one connection may hold. The
# channel list is remote-fed (kind-39000 metadata and kind-44100 membership
# notifications both come off the wire), and each entry is a real REQ on the socket,
# so this is bounded twice over: well under buzz-relay's own per-connection ceiling
# (``MAX_SUBSCRIPTIONS = 1024`` in its REQ handler) and far above any plausible
# workspace. At the cap we REFUSE new subscriptions and log, rather than evicting an
# existing one: eviction would silently deafen a channel that is currently working,
# whereas refusing leaves every established channel intact and names the one that
# did not fit.
MAX_CHANNEL_SUBSCRIPTIONS = 256

# Subscription ids. Deterministic so a subscription can be replaced or closed
# individually (``CLOSE``) without disturbing the others on the same socket.
DISCOVERY_SUB_ID = "buzz-discovery"
MEMBERSHIP_SUB_ID = "buzz-membership"
CHAT_SUB_PREFIX = "buzz-chat-"

# How many times ONE subscription may be re-opened after the relay ``CLOSED`` it,
# per connection and per auth epoch. Re-issuing a closed REQ immediately and
# unconditionally is a tight loop against a relay that keeps closing it (each
# CLOSED provokes a REQ which provokes a CLOSED), so the budget is what makes
# recovery safe rather than the backoff: at the cap we stop, say so loudly, and
# leave it to the next reconnect -- which rebuilds every subscription anyway.
MAX_RESUBSCRIBE_ATTEMPTS = 3

# Backoff between re-subscribe attempts. The FIRST retry is immediate: a one-off
# relay hiccup is the common case and should be repaired without a stall. Later
# retries back off (1s, then 2s), which is what a persistently-closing relay gets.
# The delay is awaited inline in the relay read loop rather than handed to a
# background task -- 3s of worst-case delayed frame processing per subscription
# per connection is cheaper than a task that can outlive its own socket and fire a
# REQ into a connection that no longer exists.
RESUBSCRIBE_BASE_DELAY_SECONDS = 1.0

# How far BEFORE the socket opened the live membership subscription starts.
#
# Without any ``since`` the relay replays its whole stored 44100/44101 history on
# every connection: each historical "you were added" reads as live (re-subscribing
# channels we have since been removed from and re-running discovery once per
# event), and each historical "you were removed" transiently unsubscribes a channel
# we are still in. Anchoring ``since`` at connection time fixes that, but a bare
# ``now`` would open a hole: the relay stamps ``created_at`` with ITS clock, and a
# membership change published during our connect/auth handshake is genuinely live
# yet already in the past by the time the REQ goes out. This slack covers both --
# it can only ever cost the replay of the last minute of membership changes, which
# is idempotent (``_ensure_chat_subscription`` no-ops on a channel already
# subscribed), whereas being one second short costs a channel we never hear from.
MEMBERSHIP_LOOKBACK_SECONDS = 60

# Bound on how long ``stop()`` waits for the cancelled relay loop to finish.
STOP_TIMEOUT_SECONDS = 5.0

# NIP-42's machine-readable ``CLOSED`` prefix for "authenticate first".
#
# BEFORE this connection has completed its NIP-42 handshake this is not a refusal
# at all -- it is the expected bootstrap sequence. ``_session`` deliberately opens
# the control subscriptions immediately, in case the relay serves unauthenticated
# reads; a closed relay answers ``auth-required:`` and an ``AUTH`` challenge, and
# the auth branch then re-opens every subscription. Treating that as a permanent
# refusal produced an operator-facing warning claiming discovery/membership
# tracking was DOWN at the exact moment it was coming up -- observed live, in the
# same run where discovery then completed, every channel was subscribed, and a
# brand-new channel's kind-44100 was picked up one second later.
#
# AFTER the handshake the same reason means the relay stopped accepting our
# authenticated session, which is a genuine outage and stays loud.
#
# "Completed its NIP-42 handshake" means the relay has ACKNOWLEDGED our AUTH
# event (an ``OK ... true`` for it, or -- if the relay never sends one --
# ``_confirm_auth_if_pending``'s fallback), never merely that we SENT it. A live
# relay was observed still processing an AUTH we had already sent when it closed
# the just-reopened control subscriptions with this same reason, so a flag set at
# send-time misclassified that as a post-auth refusal instead of the bootstrap
# race it still was.
_AUTH_REQUIRED_CLOSE_PREFIX = "auth-required:"

# NIP-01 asks relays to give ``CLOSED`` a machine-readable prefix. These are the
# ones where re-issuing the IDENTICAL REQ cannot succeed, so retrying is just
# fighting the relay:
#   auth-required: -- the relay wants a NIP-42 AUTH, and it sends an ``AUTH``
#                     challenge to say so; ``_session``'s auth branch re-opens every
#                     subscription once that completes, which is the real recovery.
#   restricted: / blocked: / mute: -- this identity is not permitted to read this.
#   invalid: / pow: -- the filter itself was rejected; the same filter will be again.
_PERMANENT_CLOSE_PREFIXES = (_AUTH_REQUIRED_CLOSE_PREFIX, "restricted:", "blocked:", "mute:", "invalid:", "pow:")

# buzz-relay does not always use a NIP-01 prefix -- it closes a channel's
# subscription with prose when access is revoked (e.g. the channel was archived, or
# we were removed from it) -- and NIP-01's generic categories (``error:``,
# ``rate-limited:``) leave the actual condition in the human-readable remainder, so
# ``error: channel not found`` is a permanent close wearing a retryable category.
# The prose is therefore matched regardless of prefix. Matching is deliberately
# narrow and everything unmatched DEFAULTS TO TRANSIENT: the failure this whole
# change exists to remove is going silently deaf, so an unrecognised reason resolves
# toward "keep listening", and ``MAX_RESUBSCRIBE_ATTEMPTS`` bounds the cost of
# guessing wrong in that direction.
_PERMANENT_CLOSE_MARKERS = ("revoke", "not a member", "not a channel member", "no longer a member", "access denied", "unauthorized", "forbidden", "archiv", "not found", "does not exist")

# Wording mirrors every sibling adapter's `/connect` reply style (discord.py's
# `_send_connection_reply`, slack.py's `_post_connection_reply`, and the same
# templates in wecom.py / feishu.py / dingtalk.py / wechat.py), substituting
# "Buzz" for the platform name.
_CONNECT_REPLY_TEXT = {
    "success": "Buzz connected to DeerFlow.",
    "invalid": "Buzz connection code is invalid or expired.",
    "error": "Buzz connection could not be completed from this message.",
}


def _chunk_text(text: str, limit: int = EDIT_MAX_BYTES) -> list[str]:
    """Split *text* into chunks whose UTF-8 ENCODED byte length never exceeds *limit*.

    Operates character-by-character (not on raw encoded bytes), so a multi-byte
    UTF-8 character is always appended to a chunk whole -- it is measured before
    being added and, if it would push the running byte total over *limit*, the
    chunk is flushed first and the character starts the next one. This makes a
    split-mid-character corruption structurally impossible, regardless of
    whether *limit* happens to be a multiple of any character's byte width.
    """
    chunks, current, size = [], [], 0
    for ch in text:
        b = len(ch.encode())
        if size + b > limit and current:
            chunks.append("".join(current))
            current, size = [], 0
        current.append(ch)
        size += b
    if current:
        chunks.append("".join(current))
    return chunks or [""]


def _is_auth_required_close(reason: str) -> bool:
    """Does the relay's ``CLOSED`` reason say "authenticate first" (NIP-42)?"""
    return (reason or "").strip().lower().startswith(_AUTH_REQUIRED_CLOSE_PREFIX)


# DeerFlow's hidden model-context wrappers. These are literal tags this codebase
# injects into the model's input and never into an assistant reply:
# ``DynamicContextMiddleware`` wraps recalled memory in ``<memory>`` and the date
# reminder in ``<system-reminder>``; ``DurableContextMiddleware`` wraps the
# conversation summary, delegation ledger and active skills in
# ``<durable_context_data>``. Matching the opening tag (not the words) is what
# keeps an ordinary reply that merely talks about memory publishable.
_HIDDEN_CONTEXT_MARKERS = ("<memory>", "<durable_context_data>", "<system-reminder>")


def _hidden_context_marker(text: str) -> str | None:
    """Return the hidden-context wrapper *text* carries, if any."""
    lowered = (text or "").lower()
    return next((marker for marker in _HIDDEN_CONTEXT_MARKERS if marker in lowered), None)


def _is_transient_close(reason: str) -> bool:
    """Could re-issuing the identical REQ plausibly succeed?

    This is the whole distinction between "recover from a relay hiccup" and "fight
    the relay over a channel we are no longer in". It reads only the relay's stated
    reason, so it is exactly as good as what the relay chose to say -- which is why
    the two directions are weighted differently:

    - A recognised *permanent* reason (a NIP-01/NIP-42 category prefix, or
      revocation/removal prose anywhere in the message) is believed and NOT retried.
      Re-subscribing to a channel we have been thrown out of would achieve nothing
      and look like an attack from the relay's side.
    - Anything else -- a generic ``rate-limited:``/``error:`` category, or a
      ``CLOSED`` with no reason at all, which NIP-01 permits -- is treated as
      transient and retried. The connector's worst failure mode is going silently
      deaf, so an unknown reason resolves toward "keep listening";
      ``MAX_RESUBSCRIBE_ATTEMPTS`` is what stops that from becoming a loop when the
      guess is wrong.
    """
    text = (reason or "").strip().lower()
    if text.startswith(_PERMANENT_CLOSE_PREFIXES):
        return False
    return not any(marker in text for marker in _PERMANENT_CLOSE_MARKERS)


class BuzzChannel(Channel):
    _connect: Any = None  # test seam: async callable returning an async-context-manager transport

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        super().__init__(name="buzz", bus=bus, config=config)
        self._relay_url = str(config.get("relay_url", "")).strip()
        if not self._relay_url.startswith(("ws://", "wss://")):
            raise ValueError("channels.buzz.relay_url must be a ws:// or wss:// URL")
        # One community per relay URL (see the design's multi-community note), so the
        # relay host is this channel's workspace: it scopes inbound dedupe, the
        # persisted connection row written by `/connect`, and the lookup that resolves
        # that row back on the inbound path. Computed once here so those three uses
        # can never drift apart.
        self._workspace_id = urlparse(self._relay_url).netloc
        self._private_key_raw = str(config.get("private_key", ""))
        self._keys: buzz_nostr.NostrKeys | None = None  # parsed in start() so coincurve stays lazy
        self._allowed_users = {buzz_nostr.parse_pubkey(v) for v in config.get("allowed_users", []) or []}
        self._require_mention = bool(config.get("require_mention", True))
        self._mention_free = {str(c) for c in config.get("mention_free_channels", []) or []}
        self._channel_meta: dict[str, dict[str, Any]] = {}
        self._stream_targets: dict[tuple[str, str | None], str] = {}
        self._stream_tails: dict[tuple[str, str | None], list[str]] = {}  # overflow chunk ids beyond chunk 0, per conversation
        self._last_requester: dict[tuple[str, str | None], str] = {}
        self._pending_auth_challenge: str | None = None  # set from an AUTH relay frame; consumed by the NIP-42 flow in _session
        self._seen_created_at: dict[str, int] = {}  # channel id -> high-water mark of PROCESSED created_at (see _advance_watermark)
        # Persistent processed-event-id record. The resubscribe filter replays
        # by design (inclusive ``since``), and the manager's inbound dedupe has
        # a 10-minute in-process TTL — so without durable ids, every relay
        # reconnect (or gateway restart) re-answers the last message in each
        # channel. Dedupe here is by exact event id only, never timestamp, so
        # it cannot skip a genuinely new event. ``seen_event_store`` is a test
        # seam; the default persists under ``{base_dir}/channels/``.
        self._seen_events: BuzzSeenEventStore = config.get("seen_event_store") or BuzzSeenEventStore(config.get("seen_event_store_path"))
        self._chat_subscriptions: set[str] = set()  # channel ids with a live per-channel REQ on the CURRENT connection
        self._resubscribe_attempts: dict[str, int] = {}  # sub id -> CLOSED-recovery attempts spent on the current connection/auth epoch
        self._auth_completed = False  # has THIS socket's NIP-42 handshake been ACKNOWLEDGED by the relay? (see _handle_auth_ok, _AUTH_REQUIRED_CLOSE_PREFIX)
        self._pending_auth_event_id: str | None = None  # id of the AUTH event most recently sent, awaiting a matching OK (see _handle_auth_ok / _confirm_auth_if_pending)
        self._session_started_at: int | None = None  # wall clock at which the CURRENT socket opened; anchors the live membership filter
        self._transport: Any = None
        self._task: asyncio.Task | None = None
        self._publish = self.bus.publish_inbound  # test seam (discord.py idiom)

    @property
    def supports_streaming(self) -> bool:
        return True

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._keys = buzz_nostr.parse_private_key(self._private_key_raw)
        if not self._allowed_users:
            # Deny-by-default is deliberate (unlike siblings, where an empty
            # allowlist means "allow all"), so this cannot be a hard failure --
            # but a configured-and-connected channel that silently drops every
            # message looks exactly like a broken relay to the operator. Say so
            # once, loudly, at the only point where it is actionable.
            logger.warning("[buzz] channels.buzz.allowed_users is empty: EVERY inbound chat message will be dropped (Buzz denies by default). Add member pubkeys (hex or npub) to enable the channel.")
        self.bus.subscribe_outbound(self._on_outbound)
        self._spawn_connection()
        self._running = True
        logger.info("[buzz] channel started (relay=%s pubkey=%s allowed_users=%d)", self._relay_url, self._keys.pubkey_hex, len(self._allowed_users))

    def _spawn_connection(self) -> None:
        self._task = asyncio.create_task(self._run_loop(), name="buzz-relay-loop")

    async def stop(self) -> None:
        """Cancel the relay loop and drop every piece of per-connection state.

        Teardown is *bounded* and *coherent*, in that order:

        - Bounded: the cancelled task is awaited via ``asyncio.wait`` rather than
          ``asyncio.wait_for``. ``wait_for`` guarantees the awaited task is
          finished before it raises ``TimeoutError``, so a task that swallows
          ``CancelledError`` (a bug, but the exact case a timeout exists for)
          would hang ``stop()`` forever instead of the intended 5s.
          ``asyncio.wait`` returns after the timeout regardless and cancels
          nothing further, so this always returns.
        - Coherent: the reviewer's finding was that a timed-out ``_task`` was
          dropped while it might still own ``_transport``, leaving an abandoned
          task posting on a socket the channel believed it no longer held. The
          ``finally`` now clears ``_transport`` (so ``_post_event`` fails fast
          rather than writing through a socket nobody owns) alongside ``_task``,
          and the timeout is logged instead of passing silently.

        Per-connection bookkeeping (stream placeholders, overflow tails, last
        requester, half-consumed auth challenge, remote-fed channel metadata,
        per-channel chat subscriptions) is also cleared: those maps key on relay
        event ids and subscription ids from the session being torn down, so a
        later ``start()`` must not resume editing placeholders -- or believe it is
        still subscribed to anything -- from a previous process lifetime. The
        per-channel replay cursors (``_seen_created_at``) deliberately survive, so
        a restart resumes where it left off instead of replaying every channel.
        """
        if not self._running:
            return
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)
        if self._task is not None:
            task = self._task
            task.cancel()
            try:
                _, pending = await asyncio.wait({task}, timeout=STOP_TIMEOUT_SECONDS)
                if pending:
                    logger.warning("[buzz] relay loop did not finish within %ss of cancellation; abandoning it", STOP_TIMEOUT_SECONDS)
                elif not task.cancelled() and task.exception() is not None:
                    # _run_loop is designed to never end on an ordinary connection error (it
                    # backs off and retries instead -- see its docstring), but stop() must
                    # still complete cleanly rather than re-raise whatever a genuine bug in
                    # the relay loop task ended with.
                    logger.error("[buzz] relay loop task ended with an error during stop: %s", task.exception())
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[buzz] failed to await the relay loop task during stop")
            finally:
                self._task = None
                self._transport = None
        self._stream_targets.clear()
        self._stream_tails.clear()
        self._last_requester.clear()
        self._channel_meta.clear()
        self._chat_subscriptions.clear()
        self._resubscribe_attempts.clear()
        self._auth_completed = False
        self._pending_auth_event_id = None
        self._session_started_at = None
        self._pending_auth_challenge = None
        # Seen-id persistence is coalesced (FLUSH_DELAY_SECONDS); a clean stop
        # must not lose records still inside that window to a replay on restart.
        self._seen_events.flush()
        logger.info("[buzz] channel stopped")

    # -- subscriptions ------------------------------------------------------

    @staticmethod
    def _chat_sub_id(channel_id: str) -> str:
        return f"{CHAT_SUB_PREFIX}{channel_id}"

    def _chat_filter(self, channel_id: str) -> dict:
        """The NIP-01 filter for ONE channel's chat subscription.

        ``#h`` is not an optimization -- it is the only shape the relay fans kind-9
        events out to (see the module docstring), and it may carry exactly one value.

        ``since`` rides along only once we have a watermark for THIS channel
        (``_seen_created_at``, advanced by ``_advance_watermark``): a channel we
        have not processed anything in yet gets no ``since``, so the relay's default
        backlog applies, and afterwards it is the newest ``created_at`` we have
        already processed in that channel -- so re-subscribing after a drop neither
        replays the whole channel nor silently skips what was published while we
        were disconnected.

        "Processed" means accepted-and-published (or a fully handled ``/connect``),
        never merely received. That is strictly safer for the skip direction: the
        cursor can only ever be lower than it would have been under an
        advance-on-everything rule, so any event that rule would have covered is
        still covered. What it costs is replay -- events we already dropped come
        back after a reconnect and are dropped again by the same gates, which is
        idempotent -- plus one guaranteed redelivery of the boundary event itself,
        since NIP-01 ``since`` is inclusive; the manager's inbound dedupe (keyed on
        our ``event_id`` metadata within this workspace) is what keeps that from
        starting a second run.

        KNOWN BOUND: ``since`` narrows the query but does not lift the relay's cap on
        how much history one subscription may be served -- buzz-relay answers with at
        most 2000 stored events, NEWEST-FIRST. So if a single channel accumulated more
        than 2000 messages while we were disconnected, the relay simply never sends
        the oldest of them, and the watermark advances past them as the newer ones are
        processed. That is the one bounded skip path that remains after this fix
        (everything else fails toward replay); closing it would mean paging the
        backlog with descending ``until`` queries rather than one REQ per channel.
        """
        chat_filter: dict = {"kinds": [buzz_nostr.KIND_CHAT], "#h": [channel_id]}
        since = self._seen_created_at.get(channel_id)
        if since:
            chat_filter["since"] = since
        return chat_filter

    def _discovery_filter(self) -> dict:
        """Historical kind-39000 query: which channels is this identity a member of?

        Deliberately unfiltered beyond the kind. The relay scopes kind-39000 by
        membership itself, returning one stored event per channel we belong to
        followed by EOSE -- adding ``#p`` (an obvious-looking narrowing) matches
        nothing and returns zero channels, verified against a live relay.
        """
        return {"kinds": [buzz_nostr.KIND_CHANNEL_META]}

    def _membership_filter(self) -> dict:
        """Live membership notifications addressed to us: added to / removed from a channel.

        ``since`` is not an optimization, it is the difference between "live" and
        "the entire history of this identity's membership, replayed as news".
        buzz-relay STORES 44100/44101 events and serves history newest-first with a
        default limit of 2000, so an unscoped filter meant every connection:

        - logged "added to channel ...; subscribing" once per historical add, each
          re-issuing the discovery REQ, so one connect produced M+1 discovery passes
          over N stored kind-39000 events (the two "channel discovery complete"
          lines seen live, and the channel that logged as ``<unnamed>`` because the
          44100 path subscribed before its metadata had arrived);
        - re-subscribed every channel we were EVER added to, including ones we have
          since been removed from, burning subscription-cap slots; and
        - let a historical 44101 unsubscribe (and ``_channel_meta.pop``) a channel we
          are still in -- recovered only incidentally, because newest-first ordering
          happens to deliver the oldest add last.

        The window this must not lose is a membership change published DURING the
        connect/auth handshake: it is genuinely live, but the relay stamps it with
        its own clock and it is already in the past by the time the post-auth REQ
        goes out. ``MEMBERSHIP_LOOKBACK_SECONDS`` of slack behind the moment the
        socket opened covers both that window and relay/DeerFlow clock skew. Cost of
        the slack: at most the last minute of membership changes replayed, which is
        idempotent (``_ensure_chat_subscription`` no-ops on an already-subscribed
        channel, and ``_handle_membership_event`` only re-runs discovery when the
        channel's metadata is actually missing). Cost of not having it: a channel we
        were added to during the handshake is never heard from until a reconnect.
        """
        assert self._keys is not None
        started_at = self._session_started_at if self._session_started_at is not None else int(time.time())
        since = max(0, started_at - MEMBERSHIP_LOOKBACK_SECONDS)
        return {"kinds": [buzz_nostr.KIND_MEMBER_ADDED, buzz_nostr.KIND_MEMBER_REMOVED], "#p": [self._keys.pubkey_hex], "since": since}

    async def _open_control_subscriptions(self, ws) -> None:
        """Channel discovery plus membership notifications: the two per-connection subscriptions."""
        await ws.send(buzz_nostr.req_frame(DISCOVERY_SUB_ID, self._discovery_filter()))
        await ws.send(buzz_nostr.req_frame(MEMBERSHIP_SUB_ID, self._membership_filter()))

    async def _ensure_chat_subscription(self, channel_id: str) -> None:
        """Open this channel's chat subscription unless it is already open on this connection.

        Never raises: it runs from the relay read loop, where a failed REQ must not
        take down the connection. A failure simply leaves the channel unsubscribed
        and out of ``_chat_subscriptions``, so the discovery EOSE sweep (or the next
        kind-39000 for it, or a reconnect) retries.
        """
        if not channel_id or channel_id in self._chat_subscriptions:
            return
        transport = self._transport
        if transport is None:
            return  # no connection: subscriptions are per-socket and are rebuilt by _session
        if len(self._chat_subscriptions) >= MAX_CHANNEL_SUBSCRIPTIONS:
            logger.warning("[buzz] per-channel subscription limit reached (%d); not listening to channel %s", MAX_CHANNEL_SUBSCRIPTIONS, channel_id)
            return
        try:
            await transport.send(buzz_nostr.req_frame(self._chat_sub_id(channel_id), self._chat_filter(channel_id)))
        except Exception:
            logger.warning("[buzz] failed to subscribe to channel %s; will retry", channel_id, exc_info=True)
            return
        self._chat_subscriptions.add(channel_id)
        logger.info("[buzz] listening to channel %s (%s)", self._channel_meta.get(channel_id, {}).get("name") or "<unnamed>", channel_id)

    async def _close_chat_subscription(self, channel_id: str) -> None:
        """Stop listening to one channel, leaving every other subscription on this socket alone."""
        if channel_id not in self._chat_subscriptions:
            return
        self._chat_subscriptions.discard(channel_id)
        transport = self._transport
        if transport is None:
            return
        try:
            await transport.send(buzz_nostr.close_frame(self._chat_sub_id(channel_id)))
        except Exception:
            logger.warning("[buzz] failed to unsubscribe from channel %s", channel_id, exc_info=True)

    def _claim_resubscribe_attempt(self, sub_id: str) -> int | None:
        """Spend one retry from *sub_id*'s budget for this connection; ``None`` once spent.

        The counter deliberately does NOT reset when a re-subscribe succeeds. A relay
        that accepts the REQ and then closes it again is the exact loop the budget
        exists to bound, and "it worked for a moment" is not evidence that it is
        working. The whole map is reset when the socket (or the auth epoch) changes,
        which is the only event that genuinely makes the past irrelevant.

        Keys are our own subscription ids and only ever added for subscriptions we
        actually held, but a long-lived connection can cycle through many channels,
        so the map is FIFO-capped like the other per-channel maps. Eviction only ever
        hands a channel a fresh retry budget.
        """
        used = self._resubscribe_attempts.get(sub_id, 0)
        if used >= MAX_RESUBSCRIBE_ATTEMPTS:
            return None
        self._resubscribe_attempts[sub_id] = used + 1
        while len(self._resubscribe_attempts) > MAX_CACHED_CHANNELS:
            self._resubscribe_attempts.pop(next(iter(self._resubscribe_attempts)))
        return used + 1

    async def _resubscribe_backoff(self, attempt: int) -> None:
        """Pause before re-issuing a closed REQ; the first attempt is immediate."""
        if attempt <= 1:
            return
        await asyncio.sleep(RESUBSCRIBE_BASE_DELAY_SECONDS * 2 ** (attempt - 2))

    async def _handle_closed(self, sub_id: str, reason: str) -> None:
        """Route a relay ``CLOSED`` frame to the recovery its subscription needs.

        A ``CLOSED`` is the relay dropping a subscription, and EVERY subscription on
        this socket fails silently when that happens: a chat subscription deafens one
        channel, ``buzz-membership`` stops us learning about channels we are added to
        or removed from, ``buzz-discovery`` kills the completeness sweep and the
        "no channels" warning. Forgetting the subscription is therefore only half a
        response -- something has to re-open it, or the connector runs the rest of
        that socket's life quietly missing traffic it believes it is receiving.

        The one close that is NOT an outage is ``auth-required:`` before this
        socket has completed its NIP-42 handshake: that is the bootstrap sequence
        working as designed (opportunistic pre-auth REQs, refused by a closed
        relay, re-opened wholesale by ``_session``'s auth branch). It is handled
        here, ahead of every recovery path, so it consumes neither the
        permanent-refusal branch nor the retry budget and says nothing alarming --
        the previous behaviour warned that discovery/membership tracking was down
        at the exact moment it was coming up. A chat subscription is still dropped
        from the live set, because it genuinely is not subscribed from this moment
        and the auth branch/discovery sweep is what re-opens it.
        """
        if _is_auth_required_close(reason) and not self._auth_completed:
            if sub_id.startswith(CHAT_SUB_PREFIX):
                self._chat_subscriptions.discard(sub_id[len(CHAT_SUB_PREFIX) :])
            logger.debug("[buzz] relay closed %s pending NIP-42 auth (%s); the auth handshake re-opens it", sub_id, reason or "<no reason>")
            return
        if sub_id == DISCOVERY_SUB_ID or sub_id == MEMBERSHIP_SUB_ID:
            await self._recover_control_subscription(sub_id, reason)
        elif sub_id.startswith(CHAT_SUB_PREFIX):
            await self._recover_chat_subscription(sub_id[len(CHAT_SUB_PREFIX) :], reason)
        else:
            logger.info("[buzz] relay closed unrecognized subscription %s: %s", sub_id, reason or "<no reason>")

    async def _recover_control_subscription(self, sub_id: str, reason: str) -> None:
        """Re-issue a closed ``buzz-discovery`` / ``buzz-membership`` REQ, bounded.

        These two are opened ONLY by ``_open_control_subscriptions`` -- at session
        start and in the auth branch -- so before this existed a post-auth ``CLOSED``
        for either one was terminal for the connection: nothing else in the process
        would ever send that REQ again.

        A permanent reason is not retried here, and for ``auth-required:`` that is
        not a gap: the relay pairs it with an ``AUTH`` challenge, and ``_session``'s
        auth branch re-opens both control subscriptions once the NIP-42 handshake
        completes. Re-issuing here as well would only race that. (The *pre*-auth
        ``auth-required:`` case never reaches this function at all -- see
        ``_handle_closed`` -- because there nothing is down.)

        The two permanent branches are logged separately because they are not the
        same outage. A relay demanding re-authentication mid-session is recovered
        by the next ``AUTH`` challenge; a ``restricted:``/``blocked:``/``invalid:``
        refusal is not recovered until the connection is rebuilt. Saying "down
        until the next reconnect or NIP-42 re-auth" for both was what made the
        bootstrap warning read as an outage report.
        """
        logger.warning("[buzz] relay closed control subscription %s: %s", sub_id, reason or "<no reason>")
        if not _is_transient_close(reason):
            if _is_auth_required_close(reason):
                logger.warning("[buzz] relay demanded re-authentication for %s AFTER this connection completed NIP-42 auth. It stays down until the relay's next AUTH challenge re-opens it, or until the next reconnect.", sub_id)
            else:
                logger.warning("[buzz] not re-opening %s: the relay refused it. Channel discovery/membership tracking is down until the next reconnect.", sub_id)
            return
        attempt = self._claim_resubscribe_attempt(sub_id)
        if attempt is None:
            logger.warning("[buzz] gave up re-opening control subscription %s after %d attempts; it stays down until the next reconnect", sub_id, MAX_RESUBSCRIBE_ATTEMPTS)
            return
        await self._resubscribe_backoff(attempt)
        transport = self._transport
        if transport is None:
            return  # the socket went away while backing off; _session rebuilds everything
        sub_filter = self._discovery_filter() if sub_id == DISCOVERY_SUB_ID else self._membership_filter()
        try:
            await transport.send(buzz_nostr.req_frame(sub_id, sub_filter))
        except Exception:
            logger.warning("[buzz] failed to re-open control subscription %s", sub_id, exc_info=True)
            return
        logger.info("[buzz] re-opened control subscription %s (attempt %d/%d)", sub_id, attempt, MAX_RESUBSCRIBE_ATTEMPTS)

    async def _recover_chat_subscription(self, channel_id: str, reason: str) -> None:
        """Re-open one channel's chat subscription after the relay closed it, bounded.

        Only for a subscription we actually held. A ``CLOSED`` frame is relay-supplied
        input, so treating one for an unknown channel as a recovery would let any
        relay induce a chat subscription to a channel of its choosing simply by naming
        it -- and would also let it grow ``_resubscribe_attempts`` without bound.

        The channel is dropped from ``_chat_subscriptions`` first, unconditionally: it
        is genuinely not subscribed from this moment, and leaving it there would make
        the retry (and any later kind-44100 or discovery sweep) a no-op -- the original
        reason ``_forget_subscription`` existed.
        """
        if channel_id not in self._chat_subscriptions:
            logger.info("[buzz] relay closed chat subscription for channel %s, which we were not subscribed to: %s", channel_id, reason or "<no reason>")
            return
        self._chat_subscriptions.discard(channel_id)
        name = self._channel_meta.get(channel_id, {}).get("name") or "<unnamed>"
        logger.warning("[buzz] relay closed the chat subscription for channel %s (%s), so it is now UNLISTENED: %s", name, channel_id, reason or "<no reason>")
        if not _is_transient_close(reason):
            # Removed from the channel, or not authorized to read it: re-subscribing
            # would be fighting the relay over a channel that is no longer ours. The
            # metadata entry is deliberately left alone -- the next discovery pass is
            # authoritative about membership, and ``_on_discovery_complete`` already
            # documents the one-REQ-per-stale-channel cost of a stale entry.
            logger.warning("[buzz] not re-subscribing to channel %s: the relay's reason says the subscription is no longer ours", channel_id)
            return
        attempt = self._claim_resubscribe_attempt(self._chat_sub_id(channel_id))
        if attempt is None:
            logger.warning("[buzz] gave up re-subscribing to channel %s (%s) after %d attempts; it stays unlistened until the next reconnect", name, channel_id, MAX_RESUBSCRIBE_ATTEMPTS)
            return
        await self._resubscribe_backoff(attempt)
        await self._ensure_chat_subscription(channel_id)

    def _confirm_auth_if_pending(self) -> None:
        """Fallback NIP-42 confirmation for a relay that never sends an ``OK`` for AUTH.

        NIP-42 says a relay SHOULD reply ``OK`` to an AUTH event, but "should" is
        not "does", and this connector must not depend on relay behaviour it
        cannot control to ever leave its pre-auth-confirmed state. Without this
        fallback, a relay that silently accepts the AUTH but never sends an ``OK``
        would leave ``_auth_completed`` false for the rest of the connection, and
        EVERY later ``auth-required:`` close would misclassify as bootstrap noise
        -- the same lie this whole fix removes, just permanently instead of for
        one race window.

        Chosen over a bounded sleep/timeout: this is driven by the relay's own
        response rather than the wall clock, so it needs no sleep, cannot fire
        early, and adds no unbounded wait to the read loop. Reaching the discovery
        subscription's EOSE is a safe signal because it only happens on a REQ the
        relay actually served: an auth-rejecting relay CLOSEs the just-reopened
        control subscriptions instead (routed to ``_handle_closed``, never here),
        so seeing EOSE without a CLOSED first is itself proof the AUTH we sent was
        accepted, explicit ``OK`` or not.

        Scoped to "we sent an AUTH and have not yet seen an ``OK`` for it"
        (``_pending_auth_event_id`` set) so it can never fire before an AUTH was
        even attempted -- where "not yet authenticated" is already the correct
        read and this must stay a no-op.
        """
        if self._pending_auth_event_id is None:
            return
        self._pending_auth_event_id = None
        self._auth_completed = True
        logger.info("[buzz] treating successful discovery as implicit NIP-42 confirmation (relay sent no explicit OK for our AUTH event)")

    async def _on_discovery_complete(self) -> None:
        """EOSE for the discovery subscription: every channel we belong to has now been sent.

        Chat subscriptions are opened as each kind-39000 arrives, so this is normally
        a no-op sweep. It exists because that is the point where the result can be
        relied on: a channel whose REQ failed mid-discovery is retried here, and a
        connector that discovered nothing is called out rather than sitting silent.

        The sweep runs over the whole metadata cache rather than only what this
        connection discovered, which can re-subscribe to a channel we were removed
        from while disconnected (kind-44101 prunes the cache, but only if we were
        connected to receive it). That is self-correcting and deliberately not
        engineered around: the relay answers with ``CLOSED``, whose reason names a
        removal or a revocation, so ``_recover_chat_subscription`` classifies it as
        permanent, drops the subscription, and does NOT retry -- the cost is one REQ
        per stale channel per reconnect and never a wrong-channel message, since the
        allowlist and signature gates are what decide whether anything is acted on.

        Also the (fallback) point where ``_confirm_auth_if_pending`` is given its
        chance to run: reaching this EOSE at all is only possible on a REQ the
        relay actually served, which is evidence the AUTH we sent was accepted even
        if the relay never sent an explicit ``OK`` for it. See that method's
        docstring for why this is a safe signal and why a bounded sleep was not
        used instead.
        """
        self._confirm_auth_if_pending()
        for channel_id in list(self._channel_meta):
            await self._ensure_chat_subscription(channel_id)
        if self._chat_subscriptions:
            logger.info("[buzz] channel discovery complete: listening to %d channel(s)", len(self._chat_subscriptions))
        else:
            logger.warning("[buzz] channel discovery returned no channels: this identity is not a member of any channel on %s (add it with `buzz channels add-member`)", self._relay_url)

    def _handle_auth_ok(self, event_id: str, accepted: bool, message: str) -> None:
        """React to a relay ``OK`` acknowledgment, specifically for our outstanding NIP-42 AUTH event.

        NIP-01 sends ``["OK", <event_id>, <accepted>, <message>]`` for every event
        this connector publishes -- a chat post, an edit, an AUTH -- not only AUTH,
        and this connector does not otherwise track its own published event ids to
        correlate them against. So anything that is not the one outstanding AUTH
        event id is silently ignored here: a rejected chat publish is a delivery
        problem for ``send()``'s own retry path, not this session's auth
        bookkeeping.

        This -- the relay's own affirmative reply for the EXACT event id we sent
        -- is what is allowed to flip ``_auth_completed``, never the act of
        sending the AUTH event itself. Sending only means we tried: a live relay
        was observed still processing the AUTH it would eventually accept while it
        closed the just-reopened control subscriptions with ``auth-required:``, and
        a flag set at send-time misread that ordinary bootstrap tail as a genuine
        post-auth refusal (see ``_AUTH_REQUIRED_CLOSE_PREFIX`` and
        ``_handle_closed``). A relay that never sends an ``OK`` at all is covered
        by ``_confirm_auth_if_pending``'s fallback instead.

        ``OK ... false`` is the other half of this fix: the relay REJECTED our
        AUTH, which is a real, actionable problem (a bad key, clock skew outside
        the relay's tolerance, a relay-side policy) and is logged loudly here
        rather than silently leaving the connection merely "not yet
        authenticated". It must never set ``_auth_completed`` -- the session stays
        in its pre-auth-confirmed state, quiet-recoverable the normal way if a
        fresh ``AUTH`` challenge arrives.
        """
        if event_id != self._pending_auth_event_id:
            return
        self._pending_auth_event_id = None
        if accepted:
            self._auth_completed = True
            logger.info("[buzz] relay acknowledged our NIP-42 AUTH event")
        else:
            logger.warning("[buzz] relay REJECTED our NIP-42 AUTH event: %s", message or "<no reason given>")

    async def _session(self, ws) -> None:
        """Run one relay connection's lifetime: authenticate, discover, subscribe, read frames.

        ``self._transport`` is set for the duration of this connection so ``send()``
        / ``_post_event()`` can post outbound events on it, and is unconditionally
        cleared in ``finally`` on the way out -- including on error -- so a stale
        reference can never survive past this connection (``_post_event`` reads it
        fresh on every call and raises when it is ``None``; see its docstring).
        ``_chat_subscriptions`` is per-socket bookkeeping and is cleared alongside
        it, so the next connection re-sends every REQ instead of believing
        subscriptions from a dead socket are still live.

        NIP-42 auth is opportunistic, not upfront: discovery/membership REQs are
        sent immediately in case the relay allows unauthenticated reads, but
        ``handle_relay_frame`` records any ``AUTH`` challenge the relay sends onto
        ``self._pending_auth_challenge``, and this loop reacts to it the next time
        around by signing and sending the AUTH event and then RE-RUNNING DISCOVERY
        -- our relay is closed, so the pre-auth REQs may have been rejected, and
        without redoing them we would end up authenticated but listening to nothing.
        The per-channel subscription set is dropped at the same moment for the same
        reason: a chat REQ issued pre-auth may have been rejected too, so it must
        not be remembered as live. A fresh challenge is per-connection (the relay
        mints a new one on every new socket), so all of this runs again from
        scratch on every reconnect.

        ``_resubscribe_attempts`` (the per-subscription ``CLOSED``-recovery budget)
        is reset at exactly those two points, and for the same reason: a pre-auth
        REQ that the relay closed because we had not authenticated yet is recovered
        wholesale by the auth branch, and must not spend the budget that protects the
        authenticated session from a relay that keeps closing a live subscription.

        ``_auth_completed`` is the same boundary expressed as a flag, and it is
        strictly per socket (cleared on entry AND in ``finally``): it is what lets
        ``_handle_closed`` tell the expected bootstrap ``auth-required:`` refusal
        apart from a relay that stops honouring an already-authenticated session.

        It is set ONLY once the relay has ACKNOWLEDGED our AUTH event with a
        matching ``OK ... true`` (``_handle_auth_ok``) -- never merely because we
        sent one. A live relay was observed still processing the AUTH we had
        already sent when it closed the just-reopened control subscriptions with
        this same ``auth-required:`` reason, so a flag set at send-time
        misclassified the tail of the ordinary bootstrap race as a post-auth
        refusal (the operator-facing warning that started this fix). Sending AUTH
        here only records ``_pending_auth_event_id`` so the eventual ``OK`` can be
        matched back to it; a relay that never sends one at all is covered by
        ``_confirm_auth_if_pending``'s fallback (see its docstring). A relay that
        REJECTS the AUTH (``OK ... false``) is a real, actionable problem and is
        logged loudly by ``_handle_auth_ok`` -- without ever setting this flag, so
        the connection is never mistaken for authenticated.
        """
        self._transport = ws
        self._session_started_at = int(time.time())
        self._chat_subscriptions.clear()
        self._resubscribe_attempts.clear()
        self._auth_completed = False
        self._pending_auth_event_id = None
        try:
            await self._open_control_subscriptions(ws)
            async for raw in ws:
                await self.handle_relay_frame(raw)
                if self._pending_auth_challenge is not None:
                    assert self._keys is not None
                    challenge = self._pending_auth_challenge
                    self._pending_auth_challenge = None
                    auth = buzz_nostr.build_auth_event(self._keys, self._relay_url, challenge, created_at=int(time.time()))
                    self._pending_auth_event_id = auth["id"]
                    await ws.send(json.dumps(["AUTH", auth], separators=(",", ":")))
                    self._chat_subscriptions.clear()
                    self._resubscribe_attempts.clear()
                    await self._open_control_subscriptions(ws)
        finally:
            self._transport = None
            self._chat_subscriptions.clear()
            self._resubscribe_attempts.clear()
            self._auth_completed = False
            self._pending_auth_event_id = None
            self._session_started_at = None

    async def _run_loop(self) -> None:
        """Own the relay connection for the channel's lifetime: connect, run one session, retry forever.

        Runs as the asyncio task ``_spawn_connection`` starts; ``stop()`` cancels it.
        Every sibling connector (wecom.py, discord.py, feishu.py) delegates
        reconnection to its vendor SDK -- Buzz has no SDK, so this loop owns
        reconnect/backoff itself: exponential backoff capped at 60s with jitter
        (so a thundering herd of Buzz-connected agents restarting together does not
        all retry in lockstep), reset to 0 after any connection that actually got
        established (so a long stable run doesn't leave a stale attempt count that
        punishes the next transient blip with a large initial delay).

        A clean stream end -- ``_session`` returning normally because the relay
        closed the socket on us -- is treated the same as a connection error: both
        fall through to the backoff-and-retry below rather than ending the loop,
        because for a relay client "the peer hung up" is exactly the situation
        reconnection exists for.

        ``asyncio.CancelledError`` is re-raised immediately rather than reaching the
        generic ``except Exception`` below -- it isn't an ``Exception`` subclass in
        the supported Python version anyway, but the explicit clause documents the
        contract: this is how the guarded ``stop()`` (Task 3) actually stops this
        otherwise-infinite loop, and it must never be swallowed here.

        Untrusted relay input is guarded one layer down: ``handle_relay_frame``
        already logs-and-drops a non-JSON payload or a malformed ``EVENT`` instead
        of raising, so a single bad frame reaches neither this loop's
        ``except Exception`` (reconnect) nor kills the read loop -- it is simply
        skipped and iteration continues.
        """
        attempt = 0
        while True:
            try:
                if self._connect is not None:
                    ws = await self._connect()
                else:
                    import websockets

                    ws = await websockets.connect(self._relay_url)
                async with ws:
                    attempt = 0  # reset only once a connection is actually established
                    await self._session(ws)
                # Clean stream end (relay closed on us): reconnect with backoff too.
                attempt += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempt += 1
                logger.warning("[buzz] relay connection error (attempt %d): %s", attempt, exc)
            # Cap the counter itself, not just the delay: 2**10 already exceeds the
            # 60s ceiling below, so clamping here keeps the exponent computation
            # cheap indefinitely instead of growing the attempt count (and the
            # bigint math behind 2**attempt) without bound across a very long
            # outage.
            attempt = min(attempt, 10)
            delay = min(60, 2**attempt) + random.uniform(0, 1)
            await asyncio.sleep(delay)

    # -- inbound -------------------------------------------------------------

    async def handle_relay_frame(self, raw: str) -> None:
        """Route one raw relay WebSocket frame (Task 6 calls this per frame received).

        Relay input is untrusted: a non-JSON payload, an unexpected frame shape, or
        an ``EVENT`` payload whose tags/timestamp are malformed is logged and dropped
        rather than raised, so one bad frame can never crash the read loop.

        Every ``EVENT`` is signature-verified (``buzz_nostr.verify_event``) here,
        at the single entry point, BEFORE either handler runs. The relay operator
        is not necessarily the DeerFlow operator on a team-run Buzz relay, and
        ``ev["pubkey"]`` is just a field in a relay-supplied JSON object -- without
        this check a malicious or compromised relay could name any allowlisted
        author it liked and trigger tool-executing runs, or bind a victim's pubkey
        to an attacker's DeerFlow account through ``/connect``. Both handlers make
        authorization decisions from the event (the chat gate uses ``pubkey`` as
        the principal; kind-39000 metadata can relax the mention requirement), so
        verifying at the choke point rather than inside each one leaves no path
        where an unverified event reaches a decision.

        Chosen over verifying later, behind the cheap self/kind/channel gates, on
        purpose: a Schnorr verify is tens of microseconds against human-rate chat
        traffic, so the throughput saved by gating first is worth less than the
        guarantee that no future edit can reorder a gate ahead of the check.
        """
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("[buzz] non-JSON relay frame ignored")
            return
        if not isinstance(frame, list) or not frame:
            return
        kind = frame[0]
        if kind == "AUTH" and len(frame) >= 2:
            self._pending_auth_challenge = str(frame[1])
        elif kind == "OK" and len(frame) >= 3:
            self._handle_auth_ok(str(frame[1]), frame[2] is True, str(frame[3]) if len(frame) >= 4 else "")
        elif kind == "EOSE" and len(frame) >= 2 and frame[1] == DISCOVERY_SUB_ID:
            await self._on_discovery_complete()
        elif kind == "CLOSED" and len(frame) >= 2:
            await self._handle_closed(str(frame[1]), str(frame[2]) if len(frame) >= 3 else "")
        elif kind == "EVENT" and len(frame) >= 3 and isinstance(frame[2], dict):
            ev = frame[2]
            if not buzz_nostr.verify_event(ev):
                logger.warning("[buzz] dropped relay event with an invalid id/signature (claimed pubkey=%s kind=%s)", ev.get("pubkey"), ev.get("kind"))
                return
            try:
                ev_kind = ev.get("kind")
                if ev_kind == buzz_nostr.KIND_CHANNEL_META:
                    channel_id = self._handle_meta_event(ev)
                    if channel_id:
                        await self._ensure_chat_subscription(channel_id)
                elif ev_kind == buzz_nostr.KIND_CHAT:
                    await self._handle_chat_event(ev)
                elif ev_kind in (buzz_nostr.KIND_MEMBER_ADDED, buzz_nostr.KIND_MEMBER_REMOVED):
                    await self._handle_membership_event(ev)
            except InboundQueueFullError:
                # This is not malformed relay input. Escape to _run_loop so the
                # connection is reopened with the last processed watermark and
                # relay history can retry the message once intake has capacity.
                raise
            except Exception:
                # Defense in depth against malformed tags/timestamps inside an
                # otherwise well-shaped EVENT frame (e.g. a non-integer created_at,
                # or a "tags" field that isn't a list of [name, value, ...] lists).
                logger.warning("[buzz] malformed relay event ignored", exc_info=True)
        # other EOSE / NOTICE frames need no action

    def _handle_meta_event(self, ev: dict) -> str | None:
        """Cache kind-39000 channel metadata: ``d`` = channel id, ``t`` = type, ``name``.

        Returns the channel id it cached (or ``None``), because kind-39000 is also
        the channel-DISCOVERY event: the caller turns each one into that channel's
        chat subscription. The two uses share one handler on purpose -- the set of
        channels we hold metadata for is exactly the set we are a member of.

        Trust assumption (authorship, not authenticity): ``handle_relay_frame``
        has already proved this event really was signed by the pubkey it names,
        but this does not check WHICH pubkey that is. In the Buzz protocol,
        kind-39000 channel-discovery events are expected to be published by the
        relay's own keypair, not by ordinary members. So any relay member able to
        publish an event can still legitimately sign one and mark an arbitrary
        channel ``type: "dm"``, which relaxes the mention gate for that channel
        (see ``_is_dm``) — it does NOT bypass the independent pubkey allowlist
        gate in ``_handle_chat_event``. Closing this gap needs a trusted relay
        pubkey to check the author against, and nothing already configured
        identifies one: ``relay_url`` is a network address, not a signing key.
        Deliberately left as a follow-up rather than inventing a new required
        config key (e.g. ``relay_pubkey``) for it here.

        The cache is remote-fed, so it is capped (``MAX_CACHED_CHANNELS``) on a
        first-in-first-out basis: an unbounded map would let any member grow this
        process's memory one forged ``d`` tag at a time. Eviction is safe by
        construction — a channel we hold no metadata for is treated as a non-DM
        (``_is_dm`` fails closed), and the next kind-39000 event for it repopulates
        the entry.
        """
        d_values = buzz_nostr.tag_values(ev, "d")
        if not d_values:
            return None
        names = buzz_nostr.tag_values(ev, "name")
        types = buzz_nostr.tag_values(ev, "t")
        channel_id = d_values[0]
        meta = {"type": types[0] if types else "stream", "name": names[0] if names else ""}
        self._channel_meta[channel_id] = meta
        while len(self._channel_meta) > MAX_CACHED_CHANNELS:
            self._channel_meta.pop(next(iter(self._channel_meta)))
        logger.debug("[buzz] channel metadata cached: %s (%s) type=%s", meta["name"] or "<unnamed>", channel_id, meta["type"])
        return channel_id

    async def _handle_membership_event(self, ev: dict) -> None:
        """React to a relay-signed kind-44100 / kind-44101 membership notification.

        This is what makes a newly added channel work WITHOUT a reconnect: the relay
        publishes one of these (``p`` = the affected member, ``h`` = the channel
        uuid) on the membership subscription opened for every connection, so being
        added to a channel is a live event rather than something we would only
        notice the next time the socket happened to drop.

        The ``#p`` filter on the subscription is the relay's claim, not a proof, so
        the ``p`` tag is re-checked here: another member's membership change must
        never make us subscribe to a channel we do not belong to. (The event's
        signature is already verified at ``handle_relay_frame``; what is trusted, as
        for kind-39000, is that the signer is the relay -- see the class docstring's
        trust model. A member who forges one can at most make us open a subscription
        the relay will refuse or answer with nothing.)

        Removal drops the cached metadata too: the entry would otherwise keep the
        channel in the discovery-EOSE sweep and make every later reconnect
        re-subscribe to a channel we have been thrown out of.
        """
        assert self._keys is not None
        if self._keys.pubkey_hex not in buzz_nostr.tag_values(ev, "p"):
            return  # someone else's membership change
        channel_ids = buzz_nostr.tag_values(ev, "h")
        if not channel_ids:
            return
        channel_id = channel_ids[0]
        if ev.get("kind") == buzz_nostr.KIND_MEMBER_ADDED:
            known = channel_id in self._channel_meta
            logger.info("[buzz] added to channel %s; subscribing", channel_id)
            # Subscribe first so no message is missed while metadata catches up, then
            # re-run discovery: the new channel's name and type (which drives the DM
            # mention exemption) are only carried by its kind-39000 event.
            await self._ensure_chat_subscription(channel_id)
            if not known:
                # ... but only when there is something to learn. Discovery re-issues
                # the REQ on its own subscription id, so the relay answers with every
                # stored kind-39000 and a fresh EOSE -- i.e. a whole extra discovery
                # pass. A 44100 for a channel whose metadata we already hold tells us
                # nothing new, and re-running discovery for it is how a burst of
                # membership notifications multiplied into M+1 discovery passes per
                # connect. ``since`` (see ``_membership_filter``) is what stops that
                # burst arriving at all; this is the second, independent stop.
                await self._refresh_channel_discovery()
        else:
            logger.info("[buzz] removed from channel %s; unsubscribing", channel_id)
            await self._close_chat_subscription(channel_id)
            self._channel_meta.pop(channel_id, None)

    async def _refresh_channel_discovery(self) -> None:
        """Re-issue the discovery REQ on its existing subscription id.

        Replaces the subscription in place, so the relay re-sends every kind-39000
        it holds for us: metadata for the new channel arrives, and each event runs
        through ``_ensure_chat_subscription``, which is a no-op for channels already
        subscribed. Cheaper to reason about than a one-off narrowed query, and it
        reconciles anything else that changed while we were connected.
        """
        transport = self._transport
        if transport is None:
            return
        try:
            await transport.send(buzz_nostr.req_frame(DISCOVERY_SUB_ID, self._discovery_filter()))
        except Exception:
            logger.warning("[buzz] failed to refresh channel discovery", exc_info=True)

    def _is_dm(self, channel_id: str) -> bool:
        """True only when metadata was positively cached as ``type == "dm"``.

        Fails closed: a channel we have no kind-39000 metadata for yet is never
        treated as a DM, even though ``dict.get(..., {})`` would otherwise make an
        absent entry look indistinguishable from an unset (non-DM) type.
        """
        return self._channel_meta.get(channel_id, {}).get("type") == "dm"

    def _thread_root(self, ev: dict) -> str | None:
        e_tags = buzz_nostr.tag_values(ev, "e")
        return e_tags[0] if e_tags else None

    def _strip_own_mention(self, text: str) -> str:
        """Strip a single, unambiguous leading ``@mention`` token.

        Nostr chat events carry no verified mapping from the free-text "@Name" a
        client rendered into the message body to the pubkeys in the event's ``p``
        tags — the caller only confirms *some* p-tagged mention exists (see
        ``mentioned`` in ``_handle_chat_event``), never that the specific leading
        token names *us*. When a second ``@token`` immediately follows the first
        (e.g. "@Alice, @DeerFlow help"), guessing that the first one is ours risks
        silently discarding a different member's mention while leaving ours
        untouched, so the conservative choice is to leave the text completely
        alone rather than guess. The common single-mention case ("@DeerFlow
        hello") remains unambiguous and is still stripped.
        """
        stripped = text.lstrip()
        if not stripped.startswith("@"):
            return text.strip()
        _, sep, rest = stripped.partition(" ")
        if not sep:
            return stripped  # "@DeerFlow" alone: nothing to strip without losing the whole message
        if rest.lstrip().startswith("@"):
            return text.strip()  # ambiguous multi-mention prefix: don't guess which one is ours
        return rest.strip() or stripped

    async def _bind_connection(self, code: str, author: str, channel_id: str) -> None:
        """Consume a ``/connect <code>`` bind code for *author* (a Nostr pubkey hex).

        Always fully handles the request — valid code, invalid/expired/already-used
        code, or a connection-repo error — so the caller (``_handle_chat_event``) can
        unconditionally return right after awaiting this without ever falling through
        to ``_make_inbound``/``_publish``. Mirrors discord.py's / slack.py's
        ``_bind_connection_from_connect_code``.

        Bind success/failure is fully determined and logged by the try/except below
        BEFORE ``_reply_to_connect`` is ever invoked, so a failure to *send* the
        confirmation/error reply can never be attributed back to (or logged as) a
        bind failure — see ``_reply_to_connect``. This ordering is deliberate: an
        earlier review of this method flagged that sending from inside the same
        try/except that decides bind success would let a relay-send hiccup on an
        otherwise-successful bind get reported as "failed to bind".
        """
        if self._connection_repo is None:
            return  # unreachable in practice: _pending_connect_code already requires this
        try:
            state = await self._connection_repo.consume_oauth_state(provider="buzz", state=code)
            if state is None:
                logger.info("[buzz] /connect code invalid, expired, or already used (pubkey=%s)", author)
                outcome = "invalid"
            else:
                await self._connection_repo.upsert_connection(
                    owner_user_id=state["owner_user_id"],
                    provider="buzz",
                    external_account_id=author,
                    workspace_id=self._workspace_id,
                    metadata={"pubkey": author},
                    status="connected",
                )
                logger.info("[buzz] connected pubkey=%s to owner_user_id=%s", author, state["owner_user_id"])
                outcome = "success"
        except Exception:
            # A repo/DB error binding the code must not propagate: handle_relay_frame's
            # outer guard would also catch it, but catching here keeps the log specific
            # to the bind failure instead of a generic "malformed relay event ignored".
            logger.exception("[buzz] failed to bind /connect code for pubkey=%s", author)
            outcome = "error"

        # Bind success/failure is already fully decided and logged above; sending
        # the reply is a separate, best-effort concern from here on.
        await self._reply_to_connect(channel_id, author, _CONNECT_REPLY_TEXT[outcome])

    async def _reply_to_connect(self, channel_id: str, author: str, text: str) -> None:
        """Best-effort confirmation/error reply for a ``/connect`` attempt.

        The caller (``_bind_connection``) has already fully decided and logged the
        bind outcome before this runs. A failure here is a relay-send problem, not
        a bind problem: mirroring discord.py's ``_send_connection_reply`` / slack.py's
        ``_post_connection_reply``, it never raises and logs its own,
        distinctly-worded warning, so it can never be mistaken for (or logged as) a
        failed bind. Uses a single attempt (no retry/backoff): this is a courtesy
        notification, not the delivery-critical agent-response path ``send()``
        serves, so a transient relay hiccup here should not add retry latency to
        the inbound relay read loop.
        """
        assert self._keys is not None
        try:
            event = buzz_nostr.build_chat_event(self._keys, channel_id, text, created_at=int(time.time()), mentions=(author,))
            await self._send_with_retry(lambda: self._post_event(event), max_retries=1, operation_name="connect-reply")
        except Exception:
            logger.warning("[buzz] failed to send /connect reply to pubkey=%s", author)

    def _advance_watermark(self, channel_id: str, created_at: int) -> None:
        """Move THIS CHANNEL's resubscribe cursor to *created_at*, refusing future timestamps.

        The cursor is per channel because subscriptions are: a single global
        watermark is the newest event processed in ANY channel, so a busy channel
        would keep dragging it forward and a quiet channel's next REQ would ask for
        events newer than traffic that never belonged to it -- silently skipping
        everything published in the quiet channel while we were disconnected. That
        is the one direction this cursor must never fail in. Per channel costs one
        integer per channel and cannot skip.

        ``created_at`` is chosen by the event's author, and ``_chat_filter`` replays
        it as ``since`` on every reconnect. Accepting it unchecked was a remote
        denial of service: one event stamped year-5138 pinned the cursor there, so
        every subsequent REQ asked for events newer than that and the connector went
        permanently deaf with no log and no recovery short of a process restart.

        The cursor therefore never moves beyond ``now + MAX_FUTURE_SKEW_SECONDS``.
        An out-of-range timestamp is IGNORED rather than clamped down to the
        ceiling: clamping would still hand an attacker a blind window of exactly
        the slack, while ignoring leaves the cursor where the last plausible event
        put it. A legitimately fast-clocked member merely fails to advance the
        cursor, which costs replay (drops we re-apply) and never a miss.

        Channel ids arrive in remote ``h`` tags, so the map is remote-fed and capped
        the same way ``_channel_meta`` is. Eviction is safe by construction: a
        channel with no cursor simply re-subscribes without ``since`` and gets the
        relay's default backlog, i.e. eviction can only ever cost replay.
        """
        if created_at <= 0 or not channel_id:
            return
        ceiling = int(time.time()) + MAX_FUTURE_SKEW_SECONDS
        if created_at > ceiling:
            logger.debug("[buzz] ignoring future-dated created_at=%d for the resubscribe cursor (ceiling=%d)", created_at, ceiling)
            return
        self._seen_created_at[channel_id] = max(self._seen_created_at.get(channel_id, 0), created_at)
        while len(self._seen_created_at) > MAX_CACHED_CHANNELS:
            self._seen_created_at.pop(next(iter(self._seen_created_at)))

    async def _attach_connection_identity(self, inbound: InboundMessage) -> InboundMessage:
        """Resolve a persisted ``/connect`` binding for this pubkey, exactly as every sibling does.

        Without this the bind is write-only: ``connection_id`` / ``owner_user_id``
        stay ``None``, so ``ChannelManager`` runs the turn under a synthetic
        pubkey-derived user with its own memory and file buckets instead of the
        bound DeerFlow account, and revoking the connection has no runtime effect.

        ``fallback_without_workspace`` stays off (unlike discord/dingtalk/wecom,
        whose workspace is legitimately absent for DMs): ``_bind_connection``
        always writes ``workspace_id=<relay host>``, which ``__init__`` guarantees
        is non-empty, so every Buzz row is reachable by the primary lookup. Adding
        the ``None`` candidate could only ever match a row this connector did not
        write, and matching it would resolve a pubkey bound on some other relay —
        the one thing the workspace scoping exists to prevent.
        """
        return await attach_connection_identity(inbound, repo=self._connection_repo, provider="buzz", workspace_id=self._workspace_id)

    async def _handle_chat_event(self, ev: dict) -> None:
        assert self._keys is not None
        author = str(ev.get("pubkey", ""))
        channel_id_values = buzz_nostr.tag_values(ev, "h")
        if not channel_id_values or author == self._keys.pubkey_hex:
            return  # no channel tag, or our own event (no self-reply loops)
        channel_id = channel_id_values[0]
        created_at = int(ev.get("created_at", 0))
        text = str(ev.get("content", ""))
        event_id = str(ev.get("id", ""))

        # Drop redeliveries of events this connector already fully processed.
        # The resubscribe filter replays the watermark event on every reconnect
        # (inclusive ``since``), and after a long disconnect or cursor eviction
        # the relay's default backlog comes back too. The manager's inbound
        # dedupe only covers a 10-minute in-process window, so without this a
        # relay reconnect re-answers the last message in each channel. Matching
        # is by exact event id, so a new event — whatever its author-chosen
        # created_at — is never affected. Sits before the /connect branch
        # deliberately: a replayed /connect would otherwise be re-answered with
        # a spurious "code invalid or expired" reply on every reconnect.
        if self._seen_events.seen(channel_id, event_id):
            logger.debug("[buzz] dropped replayed event id=%s in channel %s", event_id, channel_id)
            return

        # /connect <code> must be consulted before the allowlist gate (framework
        # ordering rule — see Channel._pending_connect_code) so a not-yet-bound
        # user can bootstrap a binding even though they aren't allowlisted yet.
        # Unlike every other gate below, a /connect message is never published:
        # _bind_connection fully handles it (valid, invalid, or erroring code)
        # and this always returns immediately after, matching every sibling
        # adapter's _bind_connection_from_connect_code (discord.py, slack.py,
        # wecom.py, dingtalk.py, wechat.py, feishu.py). Falling through to the
        # mention/allowlist gates and publishing this as an ordinary chat message
        # would let any pubkey trigger a real agent run just by prefixing a
        # message with "/connect" — Buzz's run policy sets
        # requires_bound_identity=False, so the manager has no independent
        # bound-identity check to catch that.
        code = self._pending_connect_code(text)
        if code is not None:
            await self._bind_connection(code, author, channel_id)
            # A bind attempt (valid or not) is fully processed, so it may advance the
            # cursor: leaving it behind would replay this /connect on every reconnect
            # and answer each replay with a spurious "code invalid or expired" reply.
            self._advance_watermark(channel_id, created_at)
            self._seen_events.record(channel_id, event_id)
            return
        if author not in self._allowed_users:
            # Deny-by-default is intentional (see start()'s empty-allowlist warning),
            # but a silent drop is indistinguishable from a broken relay when an
            # operator forgets to allowlist someone. Debug level: an open relay can
            # carry plenty of chatter from members we never intend to serve.
            logger.debug("[buzz] dropped chat event from non-allowlisted pubkey=%s in channel %s (%s)", author, self._channel_meta.get(channel_id, {}).get("name") or "<unnamed>", channel_id)
            return

        # code is always None here: a non-None code was already fully handled
        # and returned above, so this gate only ever sees ordinary chat text.
        thread_root = self._thread_root(ev)
        mentioned = self._keys.pubkey_hex in buzz_nostr.tag_values(ev, "p")
        store = self.config.get("channel_store")
        engaged_thread = bool(thread_root and store is not None and store.get_thread_id(self.name, channel_id, topic_id=thread_root))
        allowed_without_mention = (not self._require_mention) or channel_id in self._mention_free or self._is_dm(channel_id) or engaged_thread
        if not mentioned and not allowed_without_mention:
            return

        if mentioned:
            text = self._strip_own_mention(text)

        msg_type = InboundMessageType.COMMAND if is_known_channel_command(text) else InboundMessageType.CHAT
        inbound: InboundMessage = self._make_inbound(chat_id=channel_id, user_id=author, text=text, msg_type=msg_type, thread_ts=thread_root, metadata={"event_id": str(ev.get("id", ""))})
        inbound.topic_id = thread_root
        inbound.workspace_id = self._workspace_id
        inbound = await self._attach_connection_identity(inbound)
        self._last_requester[(channel_id, thread_root)] = author
        await self._publish(inbound)
        # Only a fully accepted-and-published event advances the cursor, and only
        # after the publish actually succeeded. A dropped event must never move it
        # (that was the DoS), and a failed publish must leave it replayable. The
        # same rule applies to the persistent seen-id record: recording before a
        # failed publish would turn "replayable" into "silently skipped".
        self._advance_watermark(channel_id, created_at)
        self._seen_events.record(channel_id, event_id)

    # -- outbound --------------------------------------------------------------

    async def _post_event(self, event: dict) -> None:
        """Sign-and-post is already done by the caller; this only delivers the frame.

        Reads ``self._transport`` at call time (never cached): Task 6's relay loop
        sets it to a live WebSocket for the duration of a connection and back to
        ``None`` on disconnect, so a stale reference here would keep "succeeding"
        against a socket that is no longer attached to anything.
        """
        if self._transport is None:
            raise RuntimeError("[buzz] relay connection not established")
        await self._transport.send(buzz_nostr.event_frame(event))

    async def _edit_or_repost(self, msg: OutboundMessage, target: str, content: str, now: int, *, label: str) -> str:
        """Edit *target* in place; if that fails after retries, post a fresh message instead.

        Returns the event id later updates for this slot must target -- ``target``
        itself on success, the replacement's id after a degrade. Degrading rather
        than raising is the "never lose content" rule the placeholder path has
        always had; no mention rides the replacement because the requester was
        already notified by the original post and re-mentioning on every degraded
        edit would spam notifications.
        """
        assert self._keys is not None
        edit = buzz_nostr.build_edit_event(self._keys, msg.chat_id, target, content, created_at=now)
        try:
            await self._send_with_retry(lambda: self._post_event(edit), max_retries=3, operation_name=f"edit{label}")
            return target
        except Exception:
            fresh = buzz_nostr.build_chat_event(self._keys, msg.chat_id, content, created_at=now, reply_to=msg.thread_ts)
            await self._send_with_retry(lambda: self._post_event(fresh), max_retries=3, operation_name=f"post-degraded{label}")
            return fresh["id"]

    async def send(self, msg: OutboundMessage) -> None:
        """Post one placeholder chat message, then stream via in-place edits.

        The first message for a given ``(chat_id, thread_ts)`` is a kind-9 chat
        event (the only place a mention can ride, since kind-40003 edits carry
        only ``h``/``e`` tags — see ``buzz_nostr.build_edit_event``). Every
        subsequent update for the same key edits that placeholder in place via a
        kind-40003 event targeting its id. ``is_final`` clears the tracked target
        so the next run in this conversation starts a fresh placeholder instead of
        editing a stale, already-answered message.

        Oversize text is split by ``_chunk_text`` into <= ``EDIT_MAX_BYTES``-byte
        chunks: the first chunk rides the placeholder/edit, any remaining chunks
        ride follow-up kind-9 messages threaded to the same thread root, tracked
        per conversation in ``_stream_targets`` / ``_stream_tails`` respectively.

        Every chunk index is tracked, not just chunk 0, because the manager
        publishes CUMULATIVE text on each streaming update: an oversize reply
        therefore re-splits into >= 2 chunks on EVERY update, and posting
        ``chunks[1:]`` fresh each time flooded the channel with a near-duplicate
        tail per update (a ~100KB answer at ~1 update/sec produced dozens). A
        follow-up message is now posted only when the chunk count actually GROWS;
        an index we have already posted is edited in place, exactly like chunk 0.

        Raises whatever the underlying send raised (including ``_post_event``'s
        ``RuntimeError`` when ``_transport`` is ``None``) after retries are
        exhausted, so the framework's outer retry/error-logging path in
        ``Channel._on_outbound`` observes the failure instead of a reply being
        silently dropped. The ``is_final`` bookkeeping below runs in a
        ``finally`` block precisely so that a raised exception still propagates
        to the caller *and* still clears the stale target — see the ``finally``
        comment for why both matter.

        DEFENSE IN DEPTH: text carrying one of DeerFlow's hidden model-context
        wrappers is refused outright. The real fix is one layer up
        (``manager._accumulate_stream_text`` now allowlists assistant message
        types instead of denylisting tool ones), but this connector is the one
        where a leak cannot be taken back: every streaming update is an immutable
        public Nostr event, so a corrective edit only changes what clients render
        while the original leaked event stays on the relay. Posting nothing is
        therefore the right failure direction here, and it is deliberately not
        replicated into the sibling connectors, whose channels can be edited or
        deleted. See ``_HIDDEN_CONTEXT_MARKERS`` for why this cannot fire on an
        ordinary reply that merely talks about memory.
        """
        assert self._keys is not None
        key = (msg.chat_id, msg.thread_ts)
        now = int(time.time())
        if marker := _hidden_context_marker(msg.text):
            logger.error("[buzz] REFUSED to publish a reply carrying hidden model context (%s) to channel %s; this is a leak upstream of the connector, not a relay problem", marker, msg.chat_id)
            if msg.is_final:
                self._stream_targets.pop(key, None)
                self._stream_tails.pop(key, None)
            return
        chunks = _chunk_text(msg.text)
        target = self._stream_targets.get(key)

        try:
            if target is None:
                requester = self._last_requester.get(key)
                mentions = (requester,) if requester else ()
                first = buzz_nostr.build_chat_event(self._keys, msg.chat_id, chunks[0], created_at=now, reply_to=msg.thread_ts, mentions=mentions)
                await self._send_with_retry(lambda: self._post_event(first), max_retries=3, operation_name="post")
                self._stream_targets[key] = first["id"]
            else:
                self._stream_targets[key] = await self._edit_or_repost(msg, target, chunks[0], now, label="")

            tails = self._stream_tails.get(key)
            for index, extra in enumerate(chunks[1:]):
                if tails is not None and index < len(tails):
                    tails[index] = await self._edit_or_repost(msg, tails[index], extra, now, label="-overflow")
                    continue
                follow = buzz_nostr.build_chat_event(self._keys, msg.chat_id, extra, created_at=now, reply_to=msg.thread_ts)
                await self._send_with_retry(lambda ev=follow: self._post_event(ev), max_retries=3, operation_name="post-overflow")
                if tails is None:
                    tails = self._stream_tails.setdefault(key, [])
                tails.append(follow["id"])
        finally:
            # Reviewer finding: the degrade-to-fresh-post branch above and the
            # overflow-chunk loop can both raise after their own retries are
            # exhausted, which used to propagate out of send() *before* reaching
            # an unconditional pop at the end of the function -- leaking a stale
            # (or half-updated) _stream_targets[key] entry whenever the failing
            # call had is_final=True. Once the relay recovered, the next send()
            # for this conversation would then EDIT that abandoned placeholder
            # instead of starting a fresh message, contradicting this method's
            # own contract. A `finally` clears the bookkeeping on every path --
            # success or failure -- while still letting the exception propagate
            # (a `finally` block never suppresses an in-flight exception unless
            # it itself returns/raises), so `Channel._on_outbound` still logs
            # the failure exactly as before. The overflow-tail map added for the
            # message-flood fix is cleared on exactly the same terms, so a final
            # send can never leave the next run editing this run's tail messages.
            if msg.is_final:
                self._stream_targets.pop(key, None)
                self._stream_tails.pop(key, None)
