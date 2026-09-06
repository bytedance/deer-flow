"""Tests for the Buzz (Nostr) channel connector."""

import asyncio
import json
import logging
import time
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("coincurve")

from app.channels import buzz_nostr
from app.channels.base import Channel
from app.channels.buzz import EDIT_MAX_BYTES, MAX_CACHED_CHANNELS, MAX_CHANNEL_SUBSCRIPTIONS, MAX_RESUBSCRIBE_ATTEMPTS, MEMBERSHIP_LOOKBACK_SECONDS, BuzzChannel, _chunk_text
from app.channels.manager import CHANNEL_CAPABILITIES
from app.channels.message_bus import InboundMessage, InboundMessageType, InboundQueueFullError, MessageBus, OutboundMessage
from app.channels.run_policy import CHANNEL_RUN_POLICY
from app.channels.service import _CHANNEL_CREDENTIAL_KEYS, _CHANNEL_REGISTRY

SK3_HEX = "0000000000000000000000000000000000000000000000000000000000000003"
PK3_HEX = "f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9"

# Review FINDING 4 made inbound events signature-verified, so test authors can no
# longer be arbitrary hex strings ("dd" * 32 has no private key and therefore no
# signature): every fixture author is now a real keypair whose events are signed
# exactly the way a relay member's client would sign them.
SK_OWNER = "0000000000000000000000000000000000000000000000000000000000000005"
SK_OUTSIDER = "0000000000000000000000000000000000000000000000000000000000000007"
SK_NEWCOMER = "0000000000000000000000000000000000000000000000000000000000000009"
# The relay's own keypair: it signs kind-39000 channel discovery events and the
# kind-44100/44101 membership notifications (buzz-relay's `state.relay_keypair`).
SK_RELAY = "000000000000000000000000000000000000000000000000000000000000000b"
OWNER = buzz_nostr.parse_private_key(SK_OWNER).pubkey_hex  # the one allowlisted author
OUTSIDER = buzz_nostr.parse_private_key(SK_OUTSIDER).pubkey_hex  # relay member, not allowlisted
NEWCOMER = buzz_nostr.parse_private_key(SK_NEWCOMER).pubkey_hex  # not allowlisted; binds via /connect
CHANNEL = "136852ee-63e1-49c2-8927-413b5ee8e5f7"
CHANNEL_B = "5e0209b6-2d67-5a2e-894c-9ea597f17202"


def _channel(**overrides) -> BuzzChannel:
    config = {"relay_url": "wss://buzz.example.com", "private_key": SK3_HEX, "allowed_users": [OWNER], **overrides}
    return BuzzChannel(bus=MessageBus(), config=config)


def test_registered_in_framework_registries():
    assert _CHANNEL_REGISTRY["buzz"] == "app.channels.buzz:BuzzChannel"
    assert _CHANNEL_CREDENTIAL_KEYS["buzz"] == ["private_key"]
    assert CHANNEL_CAPABILITIES["buzz"] == {"supports_streaming": True}
    policy = CHANNEL_RUN_POLICY["buzz"]
    assert policy.serialize_thread_runs is True and policy.requires_bound_identity is False


def test_is_a_channel_named_buzz_with_streaming():
    ch = _channel()
    assert isinstance(ch, Channel) and ch.name == "buzz" and ch.supports_streaming is True


def test_config_parsing_normalizes_allowlist_and_defaults():
    ch = _channel(allowed_users=[OWNER.upper()], mention_free_channels=[CHANNEL])
    assert ch._allowed_users == {OWNER}
    assert ch._require_mention is True and ch._mention_free == {CHANNEL}
    assert ch._relay_url == "wss://buzz.example.com"


def test_config_rejects_non_websocket_relay_url():
    with pytest.raises(ValueError):
        _channel(relay_url="https://buzz.example.com")


def test_start_and_stop_manage_outbound_subscription():
    async def run():
        ch = _channel()
        ch._spawn_connection = lambda: None  # skeleton: no real socket in tests
        await ch.start()
        assert ch.is_running and ch.bus._outbound_listeners == [ch._on_outbound]
        await ch.stop()
        assert not ch.is_running and ch.bus._outbound_listeners == []

    asyncio.run(run())


def test_start_is_idempotent_against_double_start():
    """A second start() while already running must not double-subscribe or re-spawn.

    Reproduces the review finding that calling start() twice appended
    `_on_outbound` to `bus._outbound_listeners` twice and spawned a second
    concurrent relay-loop task, since the original skeleton had no
    re-entrancy guard (unlike github.py / discord.py's `if self._running:
    return`).
    """

    async def run():
        ch = _channel()
        spawn_calls = 0

        def fake_spawn() -> None:
            nonlocal spawn_calls
            spawn_calls += 1

        ch._spawn_connection = fake_spawn

        await ch.start()
        await ch.start()  # must be a no-op: already running

        assert ch.bus._outbound_listeners == [ch._on_outbound]
        assert spawn_calls == 1

    asyncio.run(run())


def test_stop_is_safe_after_the_relay_task_already_crashed():
    """stop() must not re-raise a stored exception from an already-finished task.

    Reproduces the review finding that a later stop() awaited the finished relay
    task and only caught CancelledError/TimeoutError, so any other stored
    exception propagated out of stop() -- leaving `_task` non-None and skipping
    the "stopped" log.

    Updated for Task 6: this originally reproduced the crash via the Task-3
    skeleton's `_run_loop` stub, which raised `NotImplementedError` on its very
    first statement. Task 6 replaces that stub with a real reconnect-forever loop
    that, by design, does NOT crash on an ordinary connection error -- it backs
    off and retries instead (see test_run_loop_reconnects_after_connection_failure).
    Real network I/O is also not an option here: with no `_connect` seam configured,
    the real `_run_loop` would call `websockets.connect()` against this test's fake
    `wss://buzz.example.com` relay URL, which is real (slow, sandboxing-dependent)
    network I/O that must never run inside a unit test. So the "already crashed"
    scenario is now reproduced by monkeypatching `_run_loop` itself to simulate a
    hypothetical future bug there, while still exercising the REAL
    (non-monkeypatched) `_spawn_connection` -> real asyncio task path this test
    is about.
    """

    async def run():
        ch = _channel()

        async def crashing_run_loop() -> None:
            raise RuntimeError("simulated _run_loop bug")

        ch._run_loop = crashing_run_loop
        await ch.start()  # real _spawn_connection: creates a real asyncio task

        # Give the event loop a chance to run the (monkeypatched) _run_loop to
        # completion (it raises on its very first statement, so one or two
        # scheduling turns are enough).
        for _ in range(10):
            if ch._task is not None and ch._task.done():
                break
            await asyncio.sleep(0)
        assert ch._task is not None and ch._task.done()

        await ch.stop()  # must not raise the task's stored RuntimeError

        assert not ch.is_running
        assert ch._task is None

    asyncio.run(run())


def _event(*, sk=SK_OWNER, kind=9, content="@DeerFlow hello", channel=CHANNEL, mentions=(PK3_HEX,), reply_to=None, created_at=1700000100):
    """Build a REAL relay event: signed by *sk*, with the id the relay would see.

    Since FINDING 4 the connector verifies both, so a hand-built dict with a made-up
    id and no `sig` is now indistinguishable from a relay-forged event -- and is
    dropped as one. Fixtures must therefore be authentic."""
    tags = [["h", channel]]
    if reply_to:
        tags.append(["e", reply_to])
    tags.extend(["p", m] for m in mentions)
    return buzz_nostr.sign_event(buzz_nostr.parse_private_key(sk), kind, tags, content, created_at)


def _meta_event(channel=CHANNEL, *, name="general", channel_type="stream", sk=SK_RELAY, created_at=1700000060):
    """A real kind-39000 channel-discovery event, shaped exactly like buzz-relay's.

    Verified against the live relay: `d` = channel uuid, `name` = channel name,
    `t` = channel type (`stream` / `dm`), signed by the relay keypair."""
    return buzz_nostr.sign_event(buzz_nostr.parse_private_key(sk), buzz_nostr.KIND_CHANNEL_META, [["d", channel], ["name", name], ["t", channel_type]], "", created_at)


def _membership_event(kind, channel=CHANNEL, *, target=PK3_HEX, sk=SK_RELAY, created_at=1700000070):
    """A real kind-44100/44101 membership notification, shaped like buzz-relay's.

    Verified against the live relay: `p` = the affected member's pubkey, `h` = the
    channel uuid, content = a JSON blob naming the actor. Relay-signed."""
    event_type = "member_added" if kind == buzz_nostr.KIND_MEMBER_ADDED else "member_removed"
    content = json.dumps({"type": event_type, "channel_id": channel, "actor": OWNER})
    return buzz_nostr.sign_event(buzz_nostr.parse_private_key(sk), kind, [["p", target], ["h", channel]], content, created_at)


def _started(**overrides):
    ch = _channel(**overrides)
    ch._keys = buzz_nostr.parse_private_key(SK3_HEX)
    captured = []

    async def publish(msg):
        captured.append(msg)

    ch._publish = publish
    return ch, captured


def _dispatch(ch, ev):
    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "sub1", ev])))


def test_mentioned_allowed_author_is_published():
    ch, captured = _started()
    ev = _event()
    _dispatch(ch, ev)
    assert len(captured) == 1
    msg = captured[0]
    assert msg.channel_name == "buzz" and msg.chat_id == CHANNEL and msg.user_id == OWNER
    assert msg.text == "hello"  # own leading @mention stripped
    assert msg.metadata["event_id"] == ev["id"] and msg.workspace_id == "buzz.example.com"
    assert msg.msg_type == InboundMessageType.CHAT


def test_full_intake_escapes_relay_frame_handler_without_advancing_watermark():
    async def run():
        ch = _channel()
        ch.bus = MessageBus(inbound_queue_maxsize=1)
        ch._publish = ch.bus.publish_inbound
        ch._keys = buzz_nostr.parse_private_key(SK3_HEX)
        await ch.bus.publish_inbound(InboundMessage(channel_name="test", chat_id="busy", user_id="busy", text="busy"))
        ev = _event(created_at=1700000101)

        with pytest.raises(InboundQueueFullError):
            await ch.handle_relay_frame(json.dumps(["EVENT", "sub1", ev]))

        assert CHANNEL not in ch._seen_created_at

    asyncio.run(run())


def test_disallowed_author_is_dropped():
    ch, captured = _started()
    _dispatch(ch, _event(sk=SK_OUTSIDER))
    assert captured == []


def test_own_events_are_ignored():
    ch, captured = _started()
    _dispatch(ch, _event(sk=SK3_HEX))
    assert captured == []


def test_unmentioned_channel_message_is_dropped_but_dm_passes():
    ch, captured = _started()
    _dispatch(ch, _event(content="no mention here", mentions=()))
    assert captured == []
    ch._handle_meta_event({"kind": 39000, "tags": [["d", CHANNEL], ["t", "dm"], ["name", "DM"]]})
    _dispatch(ch, _event(content="dm without mention", mentions=()))
    assert len(captured) == 1 and captured[0].text == "dm without mention"


def test_mention_free_channel_and_thread_follow_pass_without_mention():
    ch, captured = _started(mention_free_channels=[CHANNEL])
    _dispatch(ch, _event(content="open channel", mentions=()))
    assert len(captured) == 1

    class FakeStore:
        def get_thread_id(self, channel_name, chat_id, topic_id=None):
            return "thread-1" if topic_id == "aa" * 32 else None

    ch2, captured2 = _started()
    ch2.config["channel_store"] = FakeStore()
    _dispatch(ch2, _event(content="follow-up", mentions=(), reply_to="aa" * 32))
    assert len(captured2) == 1 and captured2[0].topic_id == "aa" * 32


def test_thread_replies_map_topic_and_requester_and_watermark():
    ch, captured = _started()
    _dispatch(ch, _event(reply_to="aa" * 32, created_at=1700000200))
    assert captured[0].topic_id == "aa" * 32 and captured[0].thread_ts == "aa" * 32
    assert ch._last_requester[(CHANNEL, "aa" * 32)] == OWNER
    assert ch._seen_created_at[CHANNEL] == 1700000200


def test_auth_frame_records_challenge_and_meta_defaults_fail_closed():
    ch, captured = _started()
    asyncio.run(ch.handle_relay_frame('["AUTH","challenge-xyz"]'))
    assert ch._pending_auth_challenge == "challenge-xyz"
    # unknown channel type == not a DM -> unmentioned message still dropped
    _dispatch(ch, _event(channel="99999999-9999-4999-8999-999999999999", content="x", mentions=()))
    assert captured == []


# -- Task 4 review fixes -----------------------------------------------------


class FakeConnectionRepo:
    """Minimal test double for ChannelConnectionRepository: consume, upsert, and lookup.

    The lookup half was added for the review finding that the `/connect` bind was
    write-only, so it stores what `upsert_connection` wrote under the same
    (provider, external_account_id, workspace_id) identity the real repository keys
    on -- a lookup with the wrong workspace therefore misses, exactly as it would
    against SQL.
    """

    def __init__(self, *, states=None, raise_on_consume=False):
        self._states = dict(states or {})
        self._raise_on_consume = raise_on_consume
        self._connections: dict[tuple, dict] = {}
        self.upserts = []
        self.lookups = []

    async def consume_oauth_state(self, *, provider, state, now=None):
        if self._raise_on_consume:
            raise RuntimeError("boom")
        owner_user_id = self._states.pop(state, None)
        if owner_user_id is None:
            return None
        return {"owner_user_id": owner_user_id, "provider": provider, "requested_scopes": [], "metadata": {}, "redirect_after": None}

    async def upsert_connection(self, **kwargs):
        self.upserts.append(kwargs)
        connection = {"id": f"conn-{len(self.upserts)}", **kwargs}
        self._connections[(kwargs["provider"], kwargs["external_account_id"], kwargs.get("workspace_id"))] = connection
        return connection

    async def find_connection_by_external_identity(self, *, provider, external_account_id, workspace_id=None):
        self.lookups.append({"provider": provider, "external_account_id": external_account_id, "workspace_id": workspace_id})
        return self._connections.get((provider, external_account_id, workspace_id))


def test_connect_code_binds_and_never_publishes_even_for_unauthorized_author():
    """FINDING 1 (Critical): a valid /connect code from a non-allowlisted pubkey
    must bind via the connection repo and never reach _publish as a chat message."""
    repo = FakeConnectionRepo(states={"tok-1": "owner-xyz"})
    ch, captured = _started(connection_repo=repo)
    _dispatch(ch, _event(sk=SK_OUTSIDER, content="/connect tok-1", mentions=()))
    assert captured == []
    assert len(repo.upserts) == 1
    assert repo.upserts[0]["owner_user_id"] == "owner-xyz"
    assert repo.upserts[0]["external_account_id"] == OUTSIDER
    assert repo.upserts[0]["provider"] == "buzz"


def test_connect_code_invalid_never_publishes_and_does_not_bind():
    """An unrecognized/expired code must still never publish, and must not upsert."""
    repo = FakeConnectionRepo()
    ch, captured = _started(connection_repo=repo)
    _dispatch(ch, _event(sk=SK_OUTSIDER, content="/connect not-a-real-code", mentions=()))
    assert captured == []
    assert repo.upserts == []


def test_connect_code_repo_error_never_publishes_and_does_not_crash():
    """A connection-repo failure while binding must be swallowed, not crash the read loop,
    and must still never fall through to publish."""
    repo = FakeConnectionRepo(raise_on_consume=True)
    ch, captured = _started(connection_repo=repo)
    _dispatch(ch, _event(sk=SK_OUTSIDER, content="/connect tok-1", mentions=()))
    assert captured == []


def test_connect_code_never_publishes_even_for_already_allowed_and_mentioned_author():
    """Ruling: a /connect message must NEVER reach _publish, valid code or not --
    even when the author is already allowlisted and mentioned."""
    repo = FakeConnectionRepo(states={"tok-2": "owner-abc"})
    ch, captured = _started(connection_repo=repo)
    _dispatch(ch, _event(sk=SK_OWNER, content="/connect tok-2", mentions=(PK3_HEX,)))
    assert captured == []
    assert len(repo.upserts) == 1 and repo.upserts[0]["external_account_id"] == OWNER


def test_known_command_classifies_as_command_but_plain_text_stays_chat():
    """FINDING 3: is_known_channel_command classification had no direct coverage."""
    ch, captured = _started()
    _dispatch(ch, _event(content="@DeerFlow /goal ship it", mentions=(PK3_HEX,)))
    assert len(captured) == 1
    assert captured[0].msg_type == InboundMessageType.COMMAND
    assert captured[0].text == "/goal ship it"

    _dispatch(ch, _event(content="@DeerFlow just chatting", mentions=(PK3_HEX,)))
    assert len(captured) == 2
    assert captured[1].msg_type == InboundMessageType.CHAT


def test_strip_own_mention_leaves_ambiguous_multi_mention_text_untouched():
    """FINDING 4: "@Alice, @DeerFlow help" must not have Alice's mention dropped
    just because our own mention also appears in the message."""
    ch, captured = _started()
    _dispatch(ch, _event(content="@Alice, @DeerFlow help", mentions=(PK3_HEX,)))
    assert len(captured) == 1
    assert captured[0].text == "@Alice, @DeerFlow help"


# -- Task 5: outbound — placeholder post, streaming edits, final, oversize split ---


class FakeTransport:
    def __init__(self):
        self.sent = []

    async def send(self, text):
        self.sent.append(json.loads(text))


def _outbound(ch, text, *, is_final, thread_ts=None):
    return OutboundMessage(channel_name="buzz", chat_id=CHANNEL, thread_id="t1", text=text, is_final=is_final, thread_ts=thread_ts)


def _events_of(transport):
    return [f[1] for f in transport.sent if f[0] == "EVENT"]


def test_streaming_posts_placeholder_then_edits_then_final():
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport
    ch._last_requester[(CHANNEL, None)] = OWNER
    asyncio.run(ch.send(_outbound(ch, "Working…", is_final=False)))
    asyncio.run(ch.send(_outbound(ch, "Working… more", is_final=False)))
    asyncio.run(ch.send(_outbound(ch, "Final answer", is_final=True)))
    events = _events_of(transport)
    assert [e["kind"] for e in events] == [9, 40003, 40003]
    placeholder = events[0]
    assert ["p", OWNER] in placeholder["tags"]  # requester notified on the initial post
    assert all(["e", placeholder["id"]] in e["tags"] for e in events[1:])
    assert events[-1]["content"] == "Final answer"
    assert (CHANNEL, None) not in ch._stream_targets  # final clears the target


def test_thread_reply_targets_thread_root():
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport
    root = "aa" * 32
    asyncio.run(ch.send(_outbound(ch, "reply", is_final=True, thread_ts=root)))
    (ev,) = _events_of(transport)
    assert ev["kind"] == 9 and ["e", root] in ev["tags"]


def test_oversized_final_splits_into_followup_posts():
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport
    big = "x" * 130_000  # > 2 * EDIT_MAX_BYTES
    asyncio.run(ch.send(_outbound(ch, big, is_final=True)))
    events = _events_of(transport)
    assert events[0]["kind"] == 9 and all(e["kind"] == 9 for e in events[1:])
    assert "".join(e["content"] for e in events) == big
    assert all(len(e["content"].encode()) <= 60_000 for e in events)


def test_send_without_transport_raises_for_retry(monkeypatch):
    # Correction vs. the brief's literal snippet: _send_with_retry sleeps 2**attempt
    # seconds between its 3 attempts on a real failure, which would otherwise burn
    # ~3s of wall-clock time here for no benefit (this is a pure failure-path test).
    # Patching the shared retry helper's sleep call keeps it instant without
    # touching BuzzChannel/_send_with_retry itself.
    monkeypatch.setattr("app.channels.base.asyncio.sleep", AsyncMock())
    ch, _ = _started()
    with pytest.raises(RuntimeError):
        asyncio.run(ch.send(_outbound(ch, "hi", is_final=True)))


def test_chunk_text_never_splits_a_multibyte_character_across_chunks():
    """Correctness requirement beyond the brief's (ASCII-only) oversize test:
    splitting is by ENCODED BYTE LENGTH and must never cut a multi-byte UTF-8
    character in half. Uses a 4-byte-wide character (an emoji outside the BMP)
    with a limit that is deliberately NOT a multiple of 4, so a naive
    text.encode()[:limit]-style byte slice would corrupt a character; the
    real chunker must not."""
    text = "\U0001f600" * 50  # grinning-face emoji: 4 bytes each in UTF-8
    limit = 61
    chunks = _chunk_text(text, limit=limit)
    assert "".join(chunks) == text
    assert all(len(c.encode()) <= limit for c in chunks)
    # A split-mid-character chunk could never have a byte length that is an
    # exact multiple of the (uniform) 4-byte character width.
    assert all(len(c.encode()) % 4 == 0 for c in chunks)
    assert chunks[0] == "\U0001f600" * 15  # 15*4=60 <= 61 bytes; a 16th char would make 64 > 61


def test_edit_failure_degrades_to_fresh_post_and_retargets_stream(monkeypatch):
    """Correctness requirement beyond the brief's literal tests: if an edit fails
    after retries, BuzzChannel must degrade by posting a fresh message rather than
    losing the content, and must retarget _stream_targets at the new message so
    later edits in the same conversation land on it instead of the abandoned one."""
    monkeypatch.setattr("app.channels.base.asyncio.sleep", AsyncMock())
    ch, _ = _started()

    class FailingEditTransport:
        def __init__(self):
            self.sent = []

        async def send(self, text):
            frame = json.loads(text)
            if frame[0] == "EVENT" and frame[1]["kind"] == 40003:
                raise RuntimeError("relay rejected edit")
            self.sent.append(frame)

    transport = FailingEditTransport()
    ch._transport = transport

    asyncio.run(ch.send(_outbound(ch, "placeholder", is_final=False)))
    asyncio.run(ch.send(_outbound(ch, "update that fails to edit", is_final=False)))

    events = [f[1] for f in transport.sent if f[0] == "EVENT"]
    assert [e["kind"] for e in events] == [9, 9]  # placeholder + degraded fresh post, no successful edit
    assert events[1]["content"] == "update that fails to edit"
    assert ch._stream_targets[(CHANNEL, None)] == events[1]["id"]  # retargeted to the new message


# -- Review finding: _stream_targets must not leak when a FINAL send() raises -----


def test_stream_target_cleared_even_when_final_send_fails(monkeypatch):
    """FINDING (Important/spec): the edit->degrade path can raise (both the edit
    AND the degraded fresh-post attempts exhaust their retries), which used to
    propagate out of send() BEFORE reaching the `if msg.is_final: pop` at the end
    -- leaking a stale _stream_targets entry. This must hold regardless of
    success/failure: (a) send() must still raise (the framework's retry/error
    path in Channel._on_outbound must still see the failure), and (b) the stale
    target must not survive, so the NEXT send() for this conversation starts a
    fresh placeholder (kind 9) rather than editing the abandoned one (kind
    40003) once the relay recovers."""
    monkeypatch.setattr("app.channels.base.asyncio.sleep", AsyncMock())
    ch, _ = _started()

    class AlwaysFailingTransport:
        async def send(self, text):
            raise RuntimeError("relay down")

    ch._transport = AlwaysFailingTransport()

    # Seed an existing placeholder target, as a prior successful non-final
    # send() would have, so this final call takes the edit (not "first post")
    # branch -- the exact branch the finding calls out.
    key = (CHANNEL, None)
    ch._stream_targets[key] = "ff" * 32

    with pytest.raises(RuntimeError):
        asyncio.run(ch.send(_outbound(ch, "final answer", is_final=True)))

    assert key not in ch._stream_targets  # no stale/partial target survives a raised final send

    # Once the relay recovers, the next send() for the same conversation must
    # start a fresh placeholder, not an edit targeting the abandoned message.
    transport = FakeTransport()
    ch._transport = transport
    asyncio.run(ch.send(_outbound(ch, "retry after recovery", is_final=True)))
    (ev,) = _events_of(transport)
    assert ev["kind"] == 9


def test_stream_target_cleared_when_overflow_chunk_send_fails(monkeypatch):
    """Second FINDING regression case, pinning the other raise site named in the
    review: the overflow-chunk loop can also raise (a later chunk fails after
    retries even though the first chunk already succeeded). _stream_targets must
    still be cleared for this key -- not left pointing at the successfully-sent
    first chunk -- and the exception must still propagate."""
    monkeypatch.setattr("app.channels.base.asyncio.sleep", AsyncMock())
    ch, _ = _started()

    class FailsAfterFirstFrame:
        def __init__(self):
            self.sent = []

        async def send(self, text):
            frame = json.loads(text)
            if self.sent:  # the first frame succeeds; every one after raises
                raise RuntimeError("relay dropped mid-stream")
            self.sent.append(frame)

    transport = FailsAfterFirstFrame()
    ch._transport = transport
    key = (CHANNEL, None)
    big = "x" * 130_000  # forces at least one follow-up overflow chunk

    with pytest.raises(RuntimeError):
        asyncio.run(ch.send(_outbound(ch, big, is_final=True)))

    assert key not in ch._stream_targets


# -- Task 4 carry-forward: /connect must reply, and a failed reply send must ------
# -- never be reported as a failed bind -------------------------------------------


def test_connect_success_sends_confirmation_reply():
    repo = FakeConnectionRepo(states={"tok-conf": "owner-conf"})
    ch, captured = _started(connection_repo=repo)
    transport = FakeTransport()
    ch._transport = transport
    _dispatch(ch, _event(sk=SK_NEWCOMER, content="/connect tok-conf", mentions=()))
    events = _events_of(transport)
    assert len(events) == 1
    assert events[0]["kind"] == 9
    assert events[0]["content"] == "Buzz connected to DeerFlow."
    assert ["p", NEWCOMER] in events[0]["tags"]
    assert captured == []  # still never published as a chat message


def test_connect_invalid_code_sends_error_reply():
    repo = FakeConnectionRepo()
    ch, captured = _started(connection_repo=repo)
    transport = FakeTransport()
    ch._transport = transport
    _dispatch(ch, _event(sk=SK_NEWCOMER, content="/connect not-a-real-code", mentions=()))
    (event,) = _events_of(transport)
    assert event["content"] == "Buzz connection code is invalid or expired."


def test_connect_repo_error_sends_error_reply_and_does_not_crash():
    repo = FakeConnectionRepo(raise_on_consume=True)
    ch, captured = _started(connection_repo=repo)
    transport = FakeTransport()
    ch._transport = transport
    _dispatch(ch, _event(sk=SK_NEWCOMER, content="/connect tok-1", mentions=()))
    (event,) = _events_of(transport)
    assert event["content"] == "Buzz connection could not be completed from this message."


def test_connect_success_survives_a_failed_confirmation_send(caplog):
    """CRITICAL (Task 4 review carry-forward pitfall): a failure to SEND the
    confirmation for an otherwise-successful bind must never be reported or
    logged as a bind failure. ch._transport is left unset (None) so the reply
    attempt raises, but the bind itself (consume_oauth_state + upsert_connection)
    must still go through, and only a distinctly-worded send-failure warning may
    be logged -- never "failed to bind"."""
    repo = FakeConnectionRepo(states={"tok-fail-send": "owner-fail-send"})
    ch, captured = _started(connection_repo=repo)
    with caplog.at_level(logging.INFO, logger="app.channels.buzz"):
        _dispatch(ch, _event(sk=SK_NEWCOMER, content="/connect tok-fail-send", mentions=()))

    assert len(repo.upserts) == 1  # the bind itself succeeded despite the failed reply
    assert repo.upserts[0]["owner_user_id"] == "owner-fail-send"
    assert captured == []
    assert "failed to bind" not in caplog.text
    assert "failed to send" in caplog.text


# -- Task 6: relay connection loop -- connect, NIP-42 auth, subscribe, reconnect --


class ScriptedWS:
    """Async-iterable fake websocket: yields scripted frames, records sends."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []

    async def send(self, text):
        self.sent.append(json.loads(text))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.frames:
            raise StopAsyncIteration
        return self.frames.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def test_session_authenticates_then_subscribes_per_discovered_channel_with_since_cursor():
    """Rewritten for the live-test finding (see the per-channel section below).

    The original version of this test asserted the buggy shape: a GLOBAL
    `{"kinds":[9], "since": ...}` filter with no `#h`. The relay accepts that REQ
    and answers EOSE, but never fans a single chat event out to it, so the
    connector connected, authenticated, and stayed permanently silent. The
    assertions are otherwise unchanged in strength -- NIP-42 auth still happens,
    a kind-39000 discovery subscription is still opened, and the `since`
    watermark still rides the chat filter -- but that chat filter must now be
    `#h`-scoped to a channel we actually discovered.
    """
    ch, _ = _started()
    ch._seen_created_at[CHANNEL] = 1700000500
    ws = ScriptedWS(['["AUTH","challenge-1"]', json.dumps(["EVENT", "buzz-discovery", _meta_event()]), '["EOSE","buzz-discovery"]'])

    asyncio.run(ch._session(ws))
    auth_frames = [f for f in ws.sent if f[0] == "AUTH"]
    req_frames = [f for f in ws.sent if f[0] == "REQ"]
    assert len(auth_frames) == 1 and auth_frames[0][1]["kind"] == 22242
    assert ["challenge", "challenge-1"] in auth_frames[0][1]["tags"]
    assert req_frames, "expected a REQ subscription"
    filters = [f0 for f in req_frames for f0 in f[2:] if isinstance(f0, dict)]
    assert any(39000 in f.get("kinds", []) for f in filters)
    assert any(9 in f.get("kinds", []) and f.get("#h") == [CHANNEL] and f.get("since") == 1700000500 for f in filters)
    # ... and never the global kind-9 filter the relay silently ignores.
    assert not [f for f in filters if 9 in f.get("kinds", []) and not f.get("#h")]


def test_session_routes_events_through_handle_relay_frame():
    ch, captured = _started()
    ws = ScriptedWS([json.dumps(["EVENT", "s", _event()])])
    asyncio.run(ch._session(ws))
    assert len(captured) == 1


def test_run_loop_reconnects_after_connection_failure():
    """After a connect failure, _run_loop must back off and retry rather than giving up.

    Correction vs. the brief's literal mock setup: patching `app.channels.buzz.asyncio.sleep`
    with a bare `unittest.mock.AsyncMock()` patches the *shared* `asyncio` module object (since
    `buzz.py` does `import asyncio`, not `from asyncio import sleep`), so it also silently
    replaces the `asyncio.sleep(0)` this test's own polling loop relies on to yield control
    back to the event loop. A bare AsyncMock's returned coroutine has no real suspension point,
    so awaiting it never actually hands control back to the scheduler -- verified empirically
    (see task report) two ways: (a) with the polling loop's own `asyncio.sleep(0)` calls also
    silently mocked out, the `_run_loop` task never gets scheduled even once, so `attempts`
    stays empty and the test fails outright; (b) if only the polling loop is protected (e.g. by
    capturing a `real_sleep` reference before patching) while `_run_loop`'s internal backoff
    `await asyncio.sleep(delay)` remains a non-yielding mock, `_run_loop` can retry in a genuine
    infinite tight loop with zero suspension points anywhere in its call chain (mocked connect,
    trivial ScriptedWS stubs, non-yielding sleep) -- this reproducibly hung the interpreter at
    100% CPU in manual verification and had to be killed. The fix keeps the mock's call-count
    bookkeeping (`slept.await_count`) but gives its `side_effect` a genuine zero-duration
    `asyncio.sleep(0)` (captured before patching, so it cannot recursively call itself),
    so every backoff still really yields to the loop -- never a real multi-second delay, but
    never a non-yielding busy spin either. `asyncio.wait_for(..., timeout=10)` is an outer,
    real-wall-clock safety bound so a future regression here fails fast instead of hanging CI.
    """
    ch, _ = _started()
    attempts = []

    def make_connect():
        async def connect():
            attempts.append(1)
            if len(attempts) == 1:
                raise ConnectionError("boom")
            return ScriptedWS([json.dumps(["EVENT", "s", _event()])])

        return connect

    ch._connect = make_connect()

    async def run():
        import unittest.mock

        real_sleep = asyncio.sleep  # captured before patching: used by the mock's side_effect

        async def instant_yield(*_args, **_kwargs):
            await real_sleep(0)  # a genuine, zero-duration event-loop tick -- never real seconds

        with unittest.mock.patch("app.channels.buzz.asyncio.sleep", new=unittest.mock.AsyncMock(side_effect=instant_yield)) as slept:
            task = asyncio.get_running_loop().create_task(ch._run_loop())
            for _ in range(200):
                await asyncio.sleep(0)
                if len(attempts) >= 2 and task.done() is False and not ch._task:
                    break
                if len(attempts) >= 2:
                    break
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            assert slept.await_count >= 1  # backed off after the failure

    asyncio.run(asyncio.wait_for(run(), timeout=10))
    assert len(attempts) >= 2


def test_spawn_connection_cannot_fail_start_even_if_connect_immediately_errors():
    """Carried-forward invariant (from an earlier review, resolved in this task): in start(),
    `_running = True` is set AFTER `subscribe_outbound()` and `_spawn_connection()`. That was
    only safe while `_spawn_connection` was a bare `create_task(...)` call that could not itself
    raise. Task 6 gives `_run_loop` real, potentially-failing connect logic, so this pins that
    the invariant still holds: `_spawn_connection` remains non-fallible because it still only
    calls `asyncio.create_task(self._run_loop(), ...)`, which schedules the coroutine and
    returns without running any of its body -- a connect failure happens later, inside the
    spawned task, never synchronously inside start(). So even a connect that fails on its very
    first attempt cannot leave start() partially applied (outbound listener subscribed but
    `_running` still False, which would make the guarded stop() silently no-op and leak both).
    """

    async def run():
        import unittest.mock

        ch = _channel()

        async def immediately_failing_connect():
            raise RuntimeError("boom-on-first-connect")

        ch._connect = immediately_failing_connect

        with unittest.mock.patch("app.channels.buzz.asyncio.sleep", new=unittest.mock.AsyncMock()):
            await ch.start()  # must fully commit even though the spawned relay loop will
            # immediately hit immediately_failing_connect the first time it gets scheduled
            assert ch.is_running
            assert ch.bus._outbound_listeners == [ch._on_outbound]
            assert ch._task is not None

            await ch.stop()  # must cleanly unwind: no leaked listener/task either

        assert not ch.is_running
        assert ch.bus._outbound_listeners == []
        assert ch._task is None

    asyncio.run(run())


# -- Task 7: channel_connections config + browser provider wiring -----------------


def test_channel_connections_config_knows_buzz():
    """Correction vs. the brief's literal expected value: `provider_status()`
    computes `configured = enabled and bool(config.configured)`, so a disabled
    provider is always reported as `configured: False` -- confirmed by every
    sibling provider in test_channel_connections_config.py::
    test_provider_status_reports_disabled_and_unknown_providers (all
    {"enabled": False, "configured": False} on a default/disabled config).
    Buzz's `BindingCodeChannelConnectionConfig` (always-True `configured`
    property, same as discord/feishu/dingtalk/wechat/wecom) is therefore
    indistinguishable from its siblings here until it is also enabled."""
    from deerflow.config.channel_connections_config import ChannelConnectionsConfig

    cfg = ChannelConnectionsConfig()
    assert cfg.provider_status("buzz") == {"enabled": False, "configured": False}

    enabled_cfg = ChannelConnectionsConfig.model_validate({"enabled": True, "buzz": {"enabled": True}})
    assert enabled_cfg.provider_status("buzz") == {"enabled": True, "configured": True}


def test_browser_provider_wiring_for_buzz():
    from app.gateway.routers import channel_connections as cc

    assert cc._PROVIDER_META["buzz"] == {"display_name": "Buzz", "auth_mode": "binding_code"}
    assert {f["name"] for f in cc._CREDENTIAL_FIELDS["buzz"]} == {"relay_url", "private_key"}
    assert cc._RUNTIME_REQUIREMENTS["buzz"] == ("relay_url", "private_key")


# -- FINAL REVIEW FINDING 1 (Critical): the resubscribe cursor is peer-controlled --


def test_future_dated_event_from_a_dropped_author_never_moves_the_cursor():
    """Reproduces the remote DoS: any relay member -- allowlisted or not -- publishes
    one kind-9 event stamped year-5138. The event is correctly dropped by the
    allowlist, but the watermark used to be advanced BEFORE that gate, so every
    later REQ carried `since=99999999999999` and the connector went permanently
    deaf on this and every future connection, with no log and no recovery short of
    a process restart."""
    ch, captured = _started()
    _dispatch(ch, _event(sk=SK_OUTSIDER, created_at=99999999999999))
    assert captured == []
    assert ch._seen_created_at == {}
    assert "since" not in ch._chat_filter(CHANNEL)


def test_future_dated_event_from_an_allowlisted_author_is_delivered_but_capped():
    """The clamp is independent of the allowlist: an authorized member with a badly
    skewed (or deliberately absurd) clock still gets their message through, but must
    not be able to blind the connector's next reconnect either."""
    ch, captured = _started()
    _dispatch(ch, _event(created_at=99999999999999))
    assert len(captured) == 1
    assert ch._seen_created_at == {}


def test_dropped_event_with_a_plausible_timestamp_also_leaves_the_cursor_alone():
    """Advance-on-accept, not advance-on-receive: a non-allowlisted member's ordinary
    message must not silently move the cursor past events we would have accepted."""
    ch, captured = _started()
    _dispatch(ch, _event(sk=SK_OUTSIDER, created_at=1700000400))
    assert captured == []
    assert ch._seen_created_at == {}


def test_accepted_event_advances_the_cursor_and_rides_the_next_subscription():
    ch, captured = _started()
    _dispatch(ch, _event(created_at=1700000300))
    assert len(captured) == 1
    assert ch._seen_created_at[CHANNEL] == 1700000300
    assert ch._chat_filter(CHANNEL)["since"] == 1700000300


def test_a_handled_connect_advances_the_cursor_but_a_forged_one_does_not():
    """A fully processed /connect may advance the cursor (otherwise every reconnect
    replays it and answers with a spurious "code invalid or expired"), while an event
    that never gets processed at all must not."""
    repo = FakeConnectionRepo(states={"tok-cursor": "owner-cursor"})
    ch, _ = _started(connection_repo=repo)
    ch._transport = FakeTransport()
    _dispatch(ch, _event(sk=SK_NEWCOMER, content="/connect tok-cursor", mentions=(), created_at=1700000250))
    assert ch._seen_created_at[CHANNEL] == 1700000250

    forged = _event(sk=SK_OUTSIDER, content="/connect tok-cursor", mentions=(), created_at=1700000600)
    forged["content"] = "/connect tok-cursor-tampered"  # breaks the signature
    _dispatch(ch, forged)
    assert ch._seen_created_at[CHANNEL] == 1700000250


# -- FINAL REVIEW FINDING 2 (Important): /connect binds were never resolved inbound --


def test_bound_pubkey_inbound_message_carries_the_connection_identity():
    """Without `attach_connection_identity` the whole browser-connections feature was
    inert for Buzz: `connection_id`/`owner_user_id` stayed None, so the manager ran the
    turn under a synthetic pubkey-derived user (its own memory + file buckets) instead
    of the bound DeerFlow account, and DELETE /api/channels/connections/{id} had no
    runtime effect."""
    repo = FakeConnectionRepo(states={"tok-bind": "owner-bound"})
    ch, captured = _started(connection_repo=repo)
    ch._transport = FakeTransport()

    _dispatch(ch, _event(sk=SK_OWNER, content="/connect tok-bind", mentions=()))
    assert len(repo.upserts) == 1

    _dispatch(ch, _event(sk=SK_OWNER))
    assert len(captured) == 1
    assert captured[0].connection_id == "conn-1"
    assert captured[0].owner_user_id == "owner-bound"
    assert captured[0].workspace_id == "buzz.example.com"
    # Scoped to this relay: a bind written for buzz.example.com must be looked up the
    # same way, and never through a workspace-less fallback that would resolve a
    # pubkey bound on some *other* relay.
    assert repo.lookups[-1] == {"provider": "buzz", "external_account_id": OWNER, "workspace_id": "buzz.example.com"}


def test_unbound_pubkey_inbound_message_carries_no_connection_identity():
    repo = FakeConnectionRepo()
    ch, captured = _started(connection_repo=repo)
    _dispatch(ch, _event())
    assert len(captured) == 1
    assert captured[0].connection_id is None and captured[0].owner_user_id is None
    assert captured[0].workspace_id == "buzz.example.com"
    assert [lookup["workspace_id"] for lookup in repo.lookups] == ["buzz.example.com"]


# -- FINAL REVIEW FINDING 3 (Important): oversize streaming re-posted the tail ------


def _visible_conversation(transport):
    """Replay posts + edits the way a Buzz client renders them: id -> current text."""
    visible, order = {}, []
    for ev in _events_of(transport):
        if ev["kind"] == 9:
            visible[ev["id"]] = ev["content"]
            order.append(ev["id"])
        else:
            target = next(t[1] for t in ev["tags"] if t[0] == "e")
            visible[target] = ev["content"]
    return [visible[eid] for eid in order]


def test_successive_oversize_updates_edit_the_tail_instead_of_reposting_it():
    """The manager publishes CUMULATIVE text on every streaming update, so an oversize
    reply re-splits into >= 2 chunks on EVERY update. `chunks[1:]` used to be posted as
    brand-new, untracked kind-9 messages each time -- a realistic 100KB answer at
    ~1 update/sec flooded the channel with dozens of near-duplicate tails. Posts must
    now be bounded by the number of distinct chunk INDEXES ever needed."""
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport

    updates = ["x" * (EDIT_MAX_BYTES + 1_000), "y" * (EDIT_MAX_BYTES + 20_000), "z" * (2 * EDIT_MAX_BYTES + 1_000)]
    assert [len(_chunk_text(t)) for t in updates] == [2, 2, 3]  # the shape this test is about
    for index, text in enumerate(updates):
        asyncio.run(ch.send(_outbound(ch, text, is_final=index == len(updates) - 1)))

    events = _events_of(transport)
    posts = [e for e in events if e["kind"] == 9]
    edits = [e for e in events if e["kind"] == 40003]
    assert len(posts) == 3  # one per distinct chunk index (was 5: a fresh tail per update)
    assert len(edits) == 4  # chunk 0 twice, tail 0 twice
    assert "".join(_visible_conversation(transport)) == updates[-1]
    assert (CHANNEL, None) not in ch._stream_tails  # final clears the tail bookkeeping too


def test_repeated_oversize_updates_of_a_stable_size_post_nothing_new():
    """The flood's worst case: N updates that never grow past two chunks must produce
    exactly two messages in the channel, no matter how many updates arrive."""
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport

    def update(i):
        return f"u{i}" * (EDIT_MAX_BYTES // 2 + 500)  # 61_000 bytes: always exactly 2 chunks

    for i in range(6):
        asyncio.run(ch.send(_outbound(ch, update(i), is_final=i == 5)))

    posts = [e for e in _events_of(transport) if e["kind"] == 9]
    assert len(posts) == 2  # was 7: one placeholder plus a fresh tail on every update
    assert "".join(_visible_conversation(transport)) == update(5)


def test_tail_bookkeeping_is_cleared_even_when_a_final_oversize_send_fails(monkeypatch):
    """Same invariant the placeholder already had: a raised FINAL send must not leave
    tail ids behind for the next run to edit."""
    monkeypatch.setattr("app.channels.base.asyncio.sleep", AsyncMock())
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport
    key = (CHANNEL, None)
    asyncio.run(ch.send(_outbound(ch, "a" * (EDIT_MAX_BYTES + 1_000), is_final=False)))
    assert len(ch._stream_tails[key]) == 1

    class AlwaysFailingTransport:
        async def send(self, text):
            raise RuntimeError("relay down")

    ch._transport = AlwaysFailingTransport()
    with pytest.raises(RuntimeError):
        asyncio.run(ch.send(_outbound(ch, "b" * (EDIT_MAX_BYTES + 1_000), is_final=True)))
    assert key not in ch._stream_tails and key not in ch._stream_targets


# -- FINAL REVIEW FINDING 4 (Important): events were never signature-verified -------


def test_event_with_a_tampered_payload_never_reaches_publish():
    ch, captured = _started()
    ev = _event()
    ev["content"] = "@DeerFlow rm -rf /mnt/user-data"  # rewritten in flight by the relay
    _dispatch(ch, ev)
    assert captured == []


def test_relay_cannot_forge_an_allowlisted_author():
    """`ev["pubkey"]` is the authorization principal, and on a team-run relay the relay
    operator is not necessarily the DeerFlow operator: an unverified pubkey field let a
    malicious relay name an allowlisted author and trigger tool-executing runs."""
    ch, captured = _started()
    ev = _event(sk=SK_OUTSIDER)  # genuinely signed by a non-allowlisted member
    ev["pubkey"] = OWNER  # ... but delivered claiming the allowlisted one
    _dispatch(ch, ev)
    assert captured == []


def test_relay_cannot_forge_a_connect_event_to_bind_another_members_pubkey():
    """The bind path consumes `pubkey` too: forging it would bind a victim's identity to
    the attacker's DeerFlow account, so verification has to happen before /connect."""
    repo = FakeConnectionRepo(states={"tok-forge": "attacker"})
    ch, captured = _started(connection_repo=repo)
    ev = _event(sk=SK_OUTSIDER, content="/connect tok-forge", mentions=())
    ev["pubkey"] = OWNER
    _dispatch(ch, ev)
    assert repo.upserts == [] and captured == []


def test_unsigned_channel_metadata_is_rejected_before_it_can_relax_the_mention_gate():
    ch, captured = _started()
    fake_meta = {"id": "aa" * 32, "pubkey": OUTSIDER, "created_at": 1700000000, "kind": 39000, "tags": [["d", CHANNEL], ["t", "dm"]], "content": "", "sig": "00" * 64}
    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "s", fake_meta])))
    assert ch._channel_meta == {}
    _dispatch(ch, _event(content="dm without mention", mentions=()))
    assert captured == []


def test_signed_channel_metadata_is_still_cached_and_still_grants_the_dm_exemption():
    """Verification must not break the legitimate path it guards."""
    ch, captured = _started()
    meta = buzz_nostr.sign_event(buzz_nostr.parse_private_key(SK_OUTSIDER), 39000, [["d", CHANNEL], ["t", "dm"], ["name", "Ops DM"]], "", 1700000050)
    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "s", meta])))
    assert ch._channel_meta[CHANNEL] == {"type": "dm", "name": "Ops DM"}
    _dispatch(ch, _event(content="dm without mention", mentions=()))
    assert len(captured) == 1


# -- FINAL REVIEW FINDING 5: operability + bounded remote-fed state ----------------


def test_empty_allowlist_warns_at_startup(caplog):
    """Buzz keeps deny-by-default semantics (siblings treat empty as allow-all), so a
    misconfigured operator must not be left with a silently dead channel."""

    async def run():
        ch = _channel(allowed_users=[])
        ch._spawn_connection = lambda: None
        with caplog.at_level(logging.WARNING, logger="app.channels.buzz"):
            await ch.start()
        await ch.stop()

    asyncio.run(run())
    assert "allowed_users is empty" in caplog.text


def test_allowlist_drop_is_logged_at_debug(caplog):
    ch, captured = _started()
    with caplog.at_level(logging.DEBUG, logger="app.channels.buzz"):
        _dispatch(ch, _event(sk=SK_OUTSIDER))
    assert captured == []
    assert "non-allowlisted" in caplog.text


def test_stop_is_bounded_and_coherent_when_the_relay_loop_ignores_cancellation(monkeypatch, caplog):
    """`asyncio.wait_for` waits for the cancelled task to actually finish, so a loop that
    swallows CancelledError hung stop() forever instead of timing out; and the timeout
    path dropped `_task` while the task might still own `_transport`, leaving an
    abandoned task posting on a socket the channel believed it had released."""
    monkeypatch.setattr("app.channels.buzz.STOP_TIMEOUT_SECONDS", 0.01)

    async def run():
        ch = _channel()
        started = asyncio.Event()

        async def wedged_run_loop():
            ch._transport = FakeTransport()
            started.set()
            for _ in range(20):  # bounded (~0.2s) so the test can never wedge the suite
                try:
                    await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    pass  # deliberately swallow the cancel stop() sends

        ch._run_loop = wedged_run_loop
        await ch.start()
        task = ch._task
        await asyncio.wait_for(started.wait(), timeout=5)

        with caplog.at_level(logging.WARNING, logger="app.channels.buzz"):
            await asyncio.wait_for(ch.stop(), timeout=5)

        assert ch._task is None and ch._transport is None
        await asyncio.wait_for(task, timeout=5)  # let the abandoned loop retire cleanly

    asyncio.run(run())
    assert "did not finish" in caplog.text


def test_stop_clears_per_connection_state_so_a_restart_cannot_edit_stale_placeholders():
    async def run():
        ch = _channel()
        ch._spawn_connection = lambda: None
        await ch.start()
        ch._stream_targets[(CHANNEL, None)] = "aa" * 32
        ch._stream_tails[(CHANNEL, None)] = ["bb" * 32]
        ch._last_requester[(CHANNEL, None)] = OWNER
        ch._channel_meta[CHANNEL] = {"type": "dm", "name": "x"}
        ch._pending_auth_challenge = "challenge"
        ch._pending_auth_event_id = "auth-event-id"

        await ch.stop()

        assert not ch._stream_targets and not ch._stream_tails and not ch._last_requester
        assert not ch._channel_meta and ch._pending_auth_challenge is None
        assert ch._pending_auth_event_id is None

    asyncio.run(run())


def test_channel_metadata_cache_is_bounded_against_remote_feeding():
    """Any relay member can publish kind-39000 events, so the cache is remote-fed and
    must not grow for the process lifetime one forged `d` tag at a time."""
    ch, _ = _started()
    for i in range(MAX_CACHED_CHANNELS + 25):
        ch._handle_meta_event({"kind": 39000, "tags": [["d", f"chan-{i}"], ["t", "stream"]]})
    assert len(ch._channel_meta) == MAX_CACHED_CHANNELS
    assert "chan-0" not in ch._channel_meta  # oldest evicted first
    assert f"chan-{MAX_CACHED_CHANNELS + 24}" in ch._channel_meta


# -- LIVE-TEST FINDING: the relay only fans out to channel-scoped subscriptions ----
#
# Proved against a real Buzz relay (wss://buzz.atg.one), with a second identity
# publishing into a channel the connector is a member of, while both subscription
# shapes were open on the same authenticated socket:
#
#   REQ {"kinds":[9]}                      -> accepted, EOSE, and ZERO live events
#   REQ {"kinds":[9], "#h":[uuid]}         -> the event arrives
#   REQ {"kinds":[9], "#h":[uuid-a,uuid-b]}-> ZERO events (so one REQ per channel)
#
# The connector therefore has to discover its channels (historical kind-39000 REQ)
# and open ONE chat subscription per channel, and learn about channels it is added
# to afterwards from the relay-signed kind-44100/44101 membership notifications.


def _req_filters(transport):
    """Every filter object across every REQ frame the connector sent."""
    return [f for frame in transport.sent if frame[0] == "REQ" for f in frame[2:] if isinstance(f, dict)]


def _reqs_by_sub(transport):
    return {frame[1]: [f for f in frame[2:] if isinstance(f, dict)] for frame in transport.sent if frame[0] == "REQ"}


def _closed_subs(transport):
    return [frame[1] for frame in transport.sent if frame[0] == "CLOSE"]


def test_chat_subscription_is_opened_per_channel_and_never_globally():
    """THE BUG: one global `{"kinds":[9]}` filter matched nothing the relay fans out.

    Fails against the pre-fix connector, which sent exactly one un-scoped kind-9
    filter for the whole connection and no per-channel REQ at all."""
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport

    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-discovery", _meta_event(CHANNEL, name="home-network")])))
    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-discovery", _meta_event(CHANNEL_B, name="general")])))

    by_sub = _reqs_by_sub(transport)
    assert by_sub[f"buzz-chat-{CHANNEL}"] == [{"kinds": [9], "#h": [CHANNEL]}]
    assert by_sub[f"buzz-chat-{CHANNEL_B}"] == [{"kinds": [9], "#h": [CHANNEL_B]}]
    # No global kind-9 filter, and no multi-value `#h` (the relay drops both).
    for f in _req_filters(transport):
        if 9 in f.get("kinds", []):
            assert len(f.get("#h", [])) == 1, f


def test_discovery_events_populate_metadata_and_drive_chat_subscriptions():
    """Discovery does double duty: it is the DM-detection cache AND the channel list."""
    ch, captured = _started()
    transport = FakeTransport()
    ch._transport = transport

    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-discovery", _meta_event(CHANNEL, name="Ops DM", channel_type="dm")])))

    assert ch._channel_meta[CHANNEL] == {"type": "dm", "name": "Ops DM"}
    assert f"buzz-chat-{CHANNEL}" in _reqs_by_sub(transport)
    # ... and the cached type still relaxes the mention gate, as before.
    _dispatch(ch, _event(content="dm without mention", mentions=()))
    assert len(captured) == 1


def test_repeated_metadata_for_a_known_channel_does_not_resubscribe():
    """kind-39000 is addressable and re-emitted on every channel edit; one REQ is enough."""
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport
    for _ in range(4):
        asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-discovery", _meta_event(CHANNEL)])))
    assert len([frame for frame in transport.sent if frame[0] == "REQ"]) == 1


def test_discovery_eose_resubscribes_any_channel_whose_req_failed():
    """The discovery EOSE is the completeness barrier: by then every discovered
    channel must have a live chat subscription, including one whose REQ lost a race
    with a flaky socket."""
    ch, _ = _started()

    class DropsFirstSend:
        def __init__(self):
            self.sent = []
            self.failed = False

        async def send(self, text):
            if not self.failed:
                self.failed = True
                raise RuntimeError("relay hiccup")
            self.sent.append(json.loads(text))

    transport = DropsFirstSend()
    ch._transport = transport
    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-discovery", _meta_event(CHANNEL)])))
    assert _reqs_by_sub(transport) == {}  # the REQ was lost, and must not be remembered as open

    asyncio.run(ch.handle_relay_frame('["EOSE","buzz-discovery"]'))
    assert f"buzz-chat-{CHANNEL}" in _reqs_by_sub(transport)


def test_membership_notification_subscribes_to_a_new_channel_without_a_reconnect():
    """kind-44100 for OUR pubkey is how the connector learns it was added to a channel
    mid-connection. It must subscribe immediately -- a channel that only starts
    working after the next reconnect is the same silent failure in slow motion."""
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport

    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-membership", _membership_event(buzz_nostr.KIND_MEMBER_ADDED, CHANNEL_B)])))

    by_sub = _reqs_by_sub(transport)
    assert by_sub[f"buzz-chat-{CHANNEL_B}"] == [{"kinds": [9], "#h": [CHANNEL_B]}]
    # ... and the discovery subscription is re-issued so the new channel's name/type
    # (which drives DM detection) is refreshed rather than staying unknown.
    assert by_sub["buzz-discovery"] == [{"kinds": [39000]}]


def test_membership_notification_for_another_member_is_ignored():
    """The membership subscription is `#p`-filtered, but the filter is the relay's
    claim; someone else's add must not make us subscribe to their channel."""
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport
    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-membership", _membership_event(buzz_nostr.KIND_MEMBER_ADDED, CHANNEL_B, target=OUTSIDER)])))
    assert transport.sent == []


def test_member_removed_closes_only_that_channels_subscription():
    """kind-44101: stop listening to that channel, keep every other subscription on
    the same socket (this is what `close_frame` exists for)."""
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport
    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-discovery", _meta_event(CHANNEL)])))
    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-discovery", _meta_event(CHANNEL_B, name="general")])))

    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-membership", _membership_event(buzz_nostr.KIND_MEMBER_REMOVED, CHANNEL)])))

    assert _closed_subs(transport) == [f"buzz-chat-{CHANNEL}"]
    assert ch._chat_subscriptions == {CHANNEL_B}
    assert CHANNEL not in ch._channel_meta  # stale metadata must not survive the removal

    # Being re-added later must work on the same connection.
    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-membership", _membership_event(buzz_nostr.KIND_MEMBER_ADDED, CHANNEL)])))
    assert ch._chat_subscriptions == {CHANNEL, CHANNEL_B}


def test_relay_closing_a_chat_subscription_is_forgotten_so_it_can_be_reopened():
    """buzz-relay CLOSEs a channel's subscription when access is revoked (e.g. the
    channel is archived). Remembering it as live would make the later 44100
    resubscribe a no-op."""
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport
    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-discovery", _meta_event(CHANNEL)])))
    assert ch._chat_subscriptions == {CHANNEL}

    asyncio.run(ch.handle_relay_frame(json.dumps(["CLOSED", f"buzz-chat-{CHANNEL}", "channel access revoked"])))
    assert ch._chat_subscriptions == set()

    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-membership", _membership_event(buzz_nostr.KIND_MEMBER_ADDED, CHANNEL)])))
    assert ch._chat_subscriptions == {CHANNEL}


def test_watermark_is_per_channel_so_a_quiet_channel_is_never_skipped():
    """A single global `since` is the unsafe direction here: it is the newest event
    processed in ANY channel, so a quiet channel's REQ would ask for events newer
    than a busy channel's traffic and silently skip everything published in the
    quiet one while we were disconnected."""
    ch, captured = _started(mention_free_channels=[CHANNEL, CHANNEL_B])
    _dispatch(ch, _event(channel=CHANNEL, content="busy", mentions=(), created_at=1700000900))
    _dispatch(ch, _event(channel=CHANNEL_B, content="quiet", mentions=(), created_at=1700000100))
    assert len(captured) == 2

    assert ch._chat_filter(CHANNEL)["since"] == 1700000900
    assert ch._chat_filter(CHANNEL_B)["since"] == 1700000100  # not dragged forward by the busy channel


def test_watermark_map_is_bounded_against_remote_feeding():
    """Channel ids come from remote `h` tags, so the cursor map is remote-fed too.
    Eviction only ever costs replay (the relay's default backlog), never a skip."""
    ch, _ = _started()
    for i in range(MAX_CACHED_CHANNELS + 25):
        ch._advance_watermark(f"chan-{i}", 1700000000 + i)
    assert len(ch._seen_created_at) == MAX_CACHED_CHANNELS
    assert "chan-0" not in ch._seen_created_at
    assert f"chan-{MAX_CACHED_CHANNELS + 24}" in ch._seen_created_at


def test_chat_subscription_count_is_bounded(caplog):
    """One REQ per channel means the subscription count is driven by remote-fed
    channel metadata; it must be capped rather than tracking it without limit."""
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport
    with caplog.at_level(logging.WARNING, logger="app.channels.buzz"):
        for i in range(MAX_CHANNEL_SUBSCRIPTIONS + 5):
            asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-discovery", _meta_event(f"chan-{i}")])))
    assert len(ch._chat_subscriptions) == MAX_CHANNEL_SUBSCRIPTIONS
    assert "chan-0" in ch._chat_subscriptions  # a working subscription is never evicted for a new one
    assert "subscription limit" in caplog.text


def test_session_reestablishes_auth_discovery_and_per_channel_subscriptions_on_reconnect():
    """Every subscription is per-connection state: a reconnect must redo NIP-42 auth,
    re-run discovery, and reopen a chat subscription per channel. Before this fix the
    reconnect faithfully restored a subscription that received nothing."""
    ch, _ = _started()

    frames = ['["AUTH","challenge-{n}"]', None, '["EOSE","buzz-discovery"]']
    sockets = []

    def make_socket(n):
        ws = ScriptedWS([frames[0].format(n=n), json.dumps(["EVENT", "buzz-discovery", _meta_event(CHANNEL)]), frames[2]])
        sockets.append(ws)
        return ws

    connects = []

    async def connect():
        connects.append(1)
        if len(connects) == 1:
            return make_socket(1)
        if len(connects) == 2:
            return make_socket(2)
        raise asyncio.CancelledError()

    ch._connect = connect

    async def run():
        import unittest.mock

        real_sleep = asyncio.sleep

        async def instant_yield(*_a, **_kw):
            await real_sleep(0)

        with unittest.mock.patch("app.channels.buzz.asyncio.sleep", new=unittest.mock.AsyncMock(side_effect=instant_yield)):
            task = asyncio.get_running_loop().create_task(ch._run_loop())
            for _ in range(500):
                await real_sleep(0)
                if len(connects) >= 3:
                    break
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    started_at = int(time.time())
    asyncio.run(asyncio.wait_for(run(), timeout=10))

    assert len(sockets) == 2, "expected the relay loop to reconnect"
    for ws in sockets:
        by_sub = _reqs_by_sub(ws)
        assert [f for f in ws.sent if f[0] == "AUTH"], "expected NIP-42 auth on every connection"
        assert by_sub["buzz-discovery"] == [{"kinds": [39000]}]
        assert by_sub[f"buzz-chat-{CHANNEL}"] == [{"kinds": [9], "#h": [CHANNEL]}]
        # Membership is LIVE-only: the kinds/#p shape is unchanged, plus a `since`
        # anchored at this connection so the relay's stored membership history is
        # never replayed as if it had just happened (resilience FINDING 3).
        (membership_filter,) = by_sub["buzz-membership"]
        assert membership_filter["kinds"] == [44100, 44101] and membership_filter["#p"] == [PK3_HEX]
        assert membership_filter["since"] >= started_at - MEMBERSHIP_LOOKBACK_SECONDS


def test_session_end_drops_chat_subscription_bookkeeping():
    """Subscriptions do not survive their socket; remembering them would make the
    next connection skip the REQs it must re-send."""
    ch, _ = _started()
    ws = ScriptedWS([json.dumps(["EVENT", "buzz-discovery", _meta_event(CHANNEL)])])
    asyncio.run(ch._session(ws))
    assert ch._chat_subscriptions == set()
    assert ch._transport is None


# -- RESILIENCE REVIEW: a CLOSED subscription must not deafen the connector --------
#
# FINDING 1: a post-auth `CLOSED` for a control subscription (`buzz-discovery` /
#   `buzz-membership`) was logged at INFO and never re-issued, so the connector
#   silently stopped learning about channels it is added to or removed from for the
#   life of that socket.
# FINDING 2: a `CLOSED` for a chat subscription was forgotten with no retry, so a
#   transient relay CLOSE deafened exactly one channel for the rest of the
#   connection -- invisibly. Nothing re-opened it until a 44100 for that channel or
#   a full reconnect.
# FINDING 3: the membership filter carried no `since`, so every connection replayed
#   the entire stored membership history: each historical 44100 logged "added to
#   channel ...; subscribing" as if it were live and re-ran discovery, producing
#   M+1 discovery passes per connect (the live log's TWO "channel discovery
#   complete" lines), re-subscribing channels we have since been removed from, and
#   letting a historical 44101 transiently drop a channel we ARE still in.


def _reqs_for(transport, sub_id):
    return [f for f in transport.sent if f[0] == "REQ" and f[1] == sub_id]


def test_post_auth_close_of_a_control_subscription_is_reopened(monkeypatch, caplog):
    """FINDING 1: the control subscriptions are opened ONLY by
    `_open_control_subscriptions`, which runs at session start and in the auth
    branch. A relay hiccup that CLOSEs `buzz-membership` after auth therefore ended
    membership tracking for the life of the socket -- the connector stops learning
    about channels it is added to or removed from, and nothing says so. Same for
    `buzz-discovery`, whose death also kills the EOSE sweep and the "no channels"
    warning."""
    monkeypatch.setattr("app.channels.buzz.asyncio.sleep", AsyncMock())
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport

    with caplog.at_level(logging.WARNING, logger="app.channels.buzz"):
        asyncio.run(ch.handle_relay_frame(json.dumps(["CLOSED", "buzz-membership", "error: subscription dropped"])))
        asyncio.run(ch.handle_relay_frame(json.dumps(["CLOSED", "buzz-discovery", ""])))

    by_sub = _reqs_by_sub(transport)
    assert by_sub["buzz-discovery"] == [{"kinds": [39000]}]
    (membership_filter,) = by_sub["buzz-membership"]
    assert membership_filter["kinds"] == [buzz_nostr.KIND_MEMBER_ADDED, buzz_nostr.KIND_MEMBER_REMOVED]
    assert membership_filter["#p"] == [PK3_HEX]
    # A dead control subscription is an outage, not an INFO-level curiosity.
    assert "buzz-membership" in caplog.text and "buzz-discovery" in caplog.text


def test_control_resubscription_is_bounded_so_a_closing_relay_is_never_fought_forever(monkeypatch, caplog):
    """Re-issuing immediately is a tight loop if the relay keeps closing it, so the
    retries are bounded per connection and the exhaustion is loud."""
    monkeypatch.setattr("app.channels.buzz.asyncio.sleep", AsyncMock())
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport

    with caplog.at_level(logging.WARNING, logger="app.channels.buzz"):
        for _ in range(MAX_RESUBSCRIBE_ATTEMPTS + 4):
            asyncio.run(ch.handle_relay_frame(json.dumps(["CLOSED", "buzz-membership", "error: try again"])))

    assert len(_reqs_for(transport, "buzz-membership")) == MAX_RESUBSCRIBE_ATTEMPTS
    assert "gave up" in caplog.text


def test_re_auth_restores_the_control_resubscribe_budget():
    """The budget is per connection AND per auth epoch: pre-auth CLOSEDs (which the
    auth branch already recovers from wholesale) must not spend the budget that
    protects the authenticated session."""
    ch, _ = _started()
    ch._resubscribe_attempts["buzz-membership"] = MAX_RESUBSCRIBE_ATTEMPTS
    ws = ScriptedWS(['["AUTH","challenge-1"]'])
    asyncio.run(ch._session(ws))
    assert ch._resubscribe_attempts == {}


def test_transient_close_of_a_chat_subscription_reopens_that_channel(monkeypatch, caplog):
    """FINDING 2: the precise failure class this whole fix exists to eliminate -- one
    channel goes deaf for the rest of the connection and nothing says so."""
    monkeypatch.setattr("app.channels.buzz.asyncio.sleep", AsyncMock())
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport
    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-discovery", _meta_event(CHANNEL)])))
    assert ch._chat_subscriptions == {CHANNEL}

    with caplog.at_level(logging.WARNING, logger="app.channels.buzz"):
        asyncio.run(ch.handle_relay_frame(json.dumps(["CLOSED", f"buzz-chat-{CHANNEL}", "error: relay hiccup"])))

    assert ch._chat_subscriptions == {CHANNEL}  # re-opened, not silently dropped
    assert len(_reqs_for(transport, f"buzz-chat-{CHANNEL}")) == 2
    assert CHANNEL in caplog.text  # the channel going unlistened is named at WARNING


@pytest.mark.parametrize(
    "reason",
    [
        "channel access revoked",
        "restricted: you are not a member of this channel",
        "auth-required: we can only serve channel members",
        "blocked: pubkey is not allowed here",
        "invalid: unknown channel",
        # A permanent condition wearing a generic, retryable-looking category: the
        # NIP-01 prefix is only the category, the actual reason is the remainder.
        "error: channel not found",
    ],
)
def test_a_legitimate_close_of_a_chat_subscription_is_never_retried(monkeypatch, reason):
    """Do not fight the relay: a close that says we were removed, are unauthorized,
    or sent an unacceptable filter cannot be fixed by re-issuing the same REQ."""
    monkeypatch.setattr("app.channels.buzz.asyncio.sleep", AsyncMock())
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport
    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-discovery", _meta_event(CHANNEL)])))

    asyncio.run(ch.handle_relay_frame(json.dumps(["CLOSED", f"buzz-chat-{CHANNEL}", reason])))

    assert ch._chat_subscriptions == set()
    assert len(_reqs_for(transport, f"buzz-chat-{CHANNEL}")) == 1  # never re-issued


def test_chat_resubscription_is_bounded_per_connection(monkeypatch, caplog):
    ch, _ = _started()
    monkeypatch.setattr("app.channels.buzz.asyncio.sleep", AsyncMock())
    transport = FakeTransport()
    ch._transport = transport
    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-discovery", _meta_event(CHANNEL)])))

    with caplog.at_level(logging.WARNING, logger="app.channels.buzz"):
        for _ in range(MAX_RESUBSCRIBE_ATTEMPTS + 4):
            asyncio.run(ch.handle_relay_frame(json.dumps(["CLOSED", f"buzz-chat-{CHANNEL}", "error: flapping"])))

    # 1 original REQ + exactly MAX_RESUBSCRIBE_ATTEMPTS retries, then it stops.
    assert len(_reqs_for(transport, f"buzz-chat-{CHANNEL}")) == 1 + MAX_RESUBSCRIBE_ATTEMPTS
    assert ch._chat_subscriptions == set()
    assert "gave up" in caplog.text


def test_a_close_for_a_channel_we_never_subscribed_to_never_induces_a_subscription(monkeypatch):
    """A CLOSED frame is relay-supplied. Recovering one we never opened would let any
    relay induce a chat subscription to a channel of its choosing just by naming it."""
    monkeypatch.setattr("app.channels.buzz.asyncio.sleep", AsyncMock())
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport

    asyncio.run(ch.handle_relay_frame(json.dumps(["CLOSED", f"buzz-chat-{CHANNEL_B}", "error: hiccup"])))

    assert transport.sent == []
    assert ch._chat_subscriptions == set()


def test_membership_filter_is_scoped_to_live_events_so_history_is_never_replayed():
    """FINDING 3: buzz-relay STORES 44100/44101 events and serves history
    newest-first (default limit 2000). Without a `since`, every connection replayed
    the whole membership history: each stored 44100 logged "added to channel ...;
    subscribing" as if it were live, re-subscribed channels we have since been
    removed from, and a stored 44101 transiently dropped a channel we ARE still in."""
    ch, _ = _started()
    before = int(time.time())
    ws = ScriptedWS([])
    asyncio.run(ch._session(ws))
    after = int(time.time())

    (frame,) = _reqs_for(ws, "buzz-membership")
    (membership_filter,) = [f for f in frame[2:] if isinstance(f, dict)]
    assert membership_filter["kinds"] == [buzz_nostr.KIND_MEMBER_ADDED, buzz_nostr.KIND_MEMBER_REMOVED]
    assert membership_filter["#p"] == [PK3_HEX]
    since = membership_filter["since"]
    # Anchored at connection time (minus a bounded slack for relay clock skew and
    # the handshake window), never at the epoch.
    assert before - MEMBERSHIP_LOOKBACK_SECONDS <= since <= after
    # ... so nothing stored before this connection -- every fixture event included --
    # can come back as if it were live.
    assert since > 1700000070


CHANNEL_STALE = "9f1c4d3a-77b2-4e10-9a55-2c6d8e0b1f34"  # we were added to it once, and removed since


class StoringRelayWS:
    """A fake relay that STORES events and honours `since`, the way buzz-relay does.

    This is what makes the historical-replay symptom reproducible without a live
    relay: whether the connector's stored membership history comes back is decided
    by the connector's OWN filter, so an unscoped `buzz-membership` REQ replays it
    and a `since`-scoped one does not. It is also closed pre-auth (REQs are answered
    with `auth-required:` until the NIP-42 handshake completes), which is why the
    connector re-runs discovery after authenticating.
    """

    def __init__(self, stored, *, challenge="challenge-1"):
        self.stored = list(stored)
        self.sent = []
        self.authenticated = False
        self._pending = [json.dumps(["AUTH", challenge])]

    @staticmethod
    def _matches(ev, filt):
        if ev["kind"] not in filt.get("kinds", []):
            return False
        if "since" in filt and ev["created_at"] < filt["since"]:
            return False
        return all(set(buzz_nostr.tag_values(ev, key[1:])) & set(wanted) for key, wanted in filt.items() if key.startswith("#"))

    async def send(self, text):
        frame = json.loads(text)
        self.sent.append(frame)
        if frame[0] == "AUTH":
            self.authenticated = True
            return
        if frame[0] != "REQ":
            return
        sub_id, filters = frame[1], [f for f in frame[2:] if isinstance(f, dict)]
        if not self.authenticated:
            self._pending.append(json.dumps(["CLOSED", sub_id, "auth-required: we only serve authenticated members"]))
            return
        self._pending.extend(json.dumps(["EVENT", sub_id, ev]) for ev in self.stored if any(self._matches(ev, f) for f in filters))
        self._pending.append(json.dumps(["EOSE", sub_id]))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._pending:
            raise StopAsyncIteration
        return self._pending.pop(0)


def test_one_connect_performs_exactly_one_discovery_pass_and_replays_no_membership_history(caplog):
    """Directly pins the duplicate-discovery symptom seen live.

    buzz-relay stores 44100/44101 events, so an unscoped `buzz-membership` filter
    replayed the whole membership history on every connect. Each stored 44100 read
    as live: it logged "added to channel ...; subscribing", re-subscribed even to
    channels we have since been removed from, and re-issued the discovery REQ -- so
    one connect produced M+1 discovery passes over N stored kind-39000 events (the
    two "channel discovery complete" lines in the live log; the `<unnamed>` channel
    came from the 44100 path subscribing before that channel's metadata arrived).

    The relay double here honours `since` exactly as the real one does, so the
    connector's own filter is what decides the outcome."""
    ch, _ = _started()
    ws = StoringRelayWS(
        [
            _meta_event(CHANNEL, name="general"),
            _meta_event(CHANNEL_B, name="ops"),
            # Stored membership history: one add for a channel we are still in, one
            # for a channel we have since been removed from. Both long past.
            _membership_event(buzz_nostr.KIND_MEMBER_ADDED, CHANNEL, created_at=1600000000),
            _membership_event(buzz_nostr.KIND_MEMBER_ADDED, CHANNEL_STALE, created_at=1600000001),
        ]
    )

    with caplog.at_level(logging.INFO, logger="app.channels.buzz"):
        asyncio.run(ch._session(ws))

    assert caplog.text.count("channel discovery complete") == 1
    # The pre-auth REQ (which this relay answers with `auth-required:`) and its
    # post-auth re-issue -- and no third one from a replayed 44100.
    assert len(_reqs_for(ws, "buzz-discovery")) == 2
    # (`_chat_subscriptions` is per-socket and cleared by `_session`'s finally, so the
    # wire is what proves each discovered channel was subscribed exactly once.)
    for channel_id in (CHANNEL, CHANNEL_B):
        assert _reqs_for(ws, f"buzz-chat-{channel_id}") == [["REQ", f"buzz-chat-{channel_id}", {"kinds": [9], "#h": [channel_id]}]]
    # A channel we were removed from is never resurrected by its stored add.
    assert _reqs_for(ws, f"buzz-chat-{CHANNEL_STALE}") == []
    assert "added to channel" not in caplog.text
    assert "<unnamed>" not in caplog.text


def test_membership_add_for_an_already_known_channel_does_not_re_run_discovery():
    """Belt and braces for the same symptom: discovery is re-issued only when the new
    channel's name/type are actually missing, so a duplicate (or replayed) 44100
    cannot multiply discovery passes."""
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport
    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-discovery", _meta_event(CHANNEL)])))
    baseline = len(_reqs_for(transport, "buzz-discovery"))

    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-membership", _membership_event(buzz_nostr.KIND_MEMBER_ADDED, CHANNEL)])))

    assert len(_reqs_for(transport, "buzz-discovery")) == baseline
    assert ch._chat_subscriptions == {CHANNEL}


# -- LIVE-TEST FINDING 2: `auth-required` during bootstrap is not a refusal --------
#
# The connector opens its control subscriptions immediately (in case the relay
# serves unauthenticated reads), the relay CLOSEs them because NIP-42 auth has
# not happened yet, and the auth branch then legitimately re-opens both. Live:
#
#   WARNING [buzz] relay closed control subscription buzz-discovery: auth-required: not authenticated
#   WARNING [buzz] not re-opening buzz-discovery: the relay refused it. Channel
#           discovery/membership tracking is down until the next reconnect or NIP-42 re-auth.
#   ... discovery then completed, every channel was subscribed, and a live 44100
#       for a brand-new channel was picked up seconds later.
#
# So the operator-facing warning stated an outage that demonstrably was not
# happening. Pre-auth `auth-required` is now the expected bootstrap case (quiet,
# and it does not spend the permanent-refusal path or the retry budget); the same
# close AFTER a completed NIP-42 handshake is a genuine problem and stays loud.


def test_pre_auth_auth_required_close_is_the_expected_bootstrap_case_not_a_refusal(caplog):
    """The exact live sequence: control REQs go out pre-auth, the relay closes
    them with `auth-required:`, the AUTH handshake completes, and both control
    subscriptions come back. No permanent-refusal warning may be emitted, because
    nothing is down."""
    ch, _ = _started()
    ws = ScriptedWS(
        [
            json.dumps(["CLOSED", "buzz-discovery", "auth-required: not authenticated"]),
            json.dumps(["CLOSED", "buzz-membership", "auth-required: not authenticated"]),
            '["AUTH","challenge-1"]',
            json.dumps(["EVENT", "buzz-discovery", _meta_event(CHANNEL)]),
            '["EOSE","buzz-discovery"]',
        ]
    )

    with caplog.at_level(logging.DEBUG, logger="app.channels.buzz"):
        asyncio.run(ch._session(ws))

    # Opened pre-auth, closed by the relay, re-opened wholesale by the auth branch.
    assert len(_reqs_for(ws, "buzz-discovery")) == 2
    assert len(_reqs_for(ws, "buzz-membership")) == 2
    assert len(_reqs_for(ws, f"buzz-chat-{CHANNEL}")) == 1  # discovery ran and the channel was subscribed
    assert ch._chat_subscriptions == set()  # cleared on session end, but it WAS listening
    # The lie: nothing was down, so nothing may say it was.
    assert "not re-opening" not in caplog.text
    assert "discovery/membership tracking is down" not in caplog.text
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings == [], f"pre-auth bootstrap must be quiet, got: {[r.getMessage() for r in warnings]}"


def test_pre_auth_auth_required_close_does_not_spend_the_resubscribe_budget(monkeypatch):
    """The retry budget protects the AUTHENTICATED session from a relay that keeps
    closing a live subscription. A bootstrap close is recovered wholesale by the
    auth branch and must not consume it."""
    monkeypatch.setattr("app.channels.buzz.asyncio.sleep", AsyncMock())
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport

    for _ in range(MAX_RESUBSCRIBE_ATTEMPTS + 2):
        asyncio.run(ch.handle_relay_frame(json.dumps(["CLOSED", "buzz-discovery", "auth-required: not authenticated"])))

    assert ch._resubscribe_attempts == {}
    assert _reqs_for(transport, "buzz-discovery") == []  # the auth branch re-opens it, not this path


def test_post_auth_auth_required_close_is_still_treated_as_serious_and_logged_loudly(caplog):
    """After the NIP-42 handshake completed, the relay demanding auth again is a
    real problem: the subscription is genuinely down until a fresh AUTH challenge
    or a reconnect, and the operator has to be told."""
    ch, _ = _started()
    ch._auth_completed = True
    transport = FakeTransport()
    ch._transport = transport

    with caplog.at_level(logging.DEBUG, logger="app.channels.buzz"):
        asyncio.run(ch.handle_relay_frame(json.dumps(["CLOSED", "buzz-membership", "auth-required: not authenticated"])))

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "a post-auth auth-required close must be loud"
    assert any("buzz-membership" in message for message in warnings)
    assert _reqs_for(transport, "buzz-membership") == []  # still not fought over; re-auth is the recovery


def test_post_auth_permanent_refusal_still_says_tracking_is_down(caplog):
    """The truthful case the old wording was borrowed from: a non-auth permanent
    refusal really does leave discovery/membership tracking down until reconnect."""
    ch, _ = _started()
    ch._auth_completed = True
    ch._transport = FakeTransport()

    with caplog.at_level(logging.WARNING, logger="app.channels.buzz"):
        asyncio.run(ch.handle_relay_frame(json.dumps(["CLOSED", "buzz-discovery", "restricted: not permitted"])))

    assert "not re-opening" in caplog.text
    assert "down until the next reconnect" in caplog.text


def test_pre_auth_auth_required_close_of_a_chat_subscription_is_forgotten_so_auth_reopens_it(caplog):
    """A chat REQ issued before auth can be closed the same way. It must be dropped
    from the live set (so discovery re-opens it) without an UNLISTENED alarm."""
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport
    asyncio.run(ch.handle_relay_frame(json.dumps(["EVENT", "buzz-discovery", _meta_event(CHANNEL)])))
    assert ch._chat_subscriptions == {CHANNEL}

    with caplog.at_level(logging.WARNING, logger="app.channels.buzz"):
        asyncio.run(ch.handle_relay_frame(json.dumps(["CLOSED", f"buzz-chat-{CHANNEL}", "auth-required: not authenticated"])))

    assert ch._chat_subscriptions == set()
    assert len(_reqs_for(transport, f"buzz-chat-{CHANNEL}")) == 1  # not retried here; auth/discovery re-opens it
    assert "UNLISTENED" not in caplog.text


def test_auth_completed_flag_is_per_connection():
    """It anchors "pre-auth" to THIS socket: a fresh connection starts unauthenticated
    again, and a torn-down channel must not remember it was ever authenticated."""

    async def run():
        ch, _ = _started()
        ch._auth_completed = True
        await ch._session(ScriptedWS([]))
        assert ch._auth_completed is False
        ch._auth_completed = True
        await ch._session(ScriptedWS(['["AUTH","challenge-1"]']))
        assert ch._auth_completed is False

    asyncio.run(run())


def test_session_does_not_mark_auth_completed_merely_because_auth_was_sent():
    """Sending the AUTH event is only our half of the NIP-42 handshake.

    Replaces a previous version of this test that pinned the exact bug this fix
    removes: it asserted `_auth_completed` became true the instant AUTH was sent,
    with no `OK` anywhere in the script. A live relay was observed still
    processing an AUTH it had already received -- and closing the just-reopened
    control subscriptions with `auth-required:` -- well after the connector had
    sent it, so `_auth_completed` must stay false until the relay actually
    acknowledges the exact event id (see `test_ok_true_for_our_auth_event_marks_the_connection_authenticated`)."""
    ch, _ = _started()
    seen = []
    ws = ScriptedWS(['["AUTH","challenge-1"]'])
    original = ch._open_control_subscriptions

    async def spy(transport):
        seen.append(ch._auth_completed)
        await original(transport)

    ch._open_control_subscriptions = spy
    asyncio.run(ch._session(ws))
    assert seen == [False, False]  # pre-auth open, then the post-AUTH-SENT re-open -- still not ack'd
    assert ch._pending_auth_event_id is None  # cleared by _session's finally on teardown, ack or not


def test_auth_required_close_between_auth_sent_and_relay_ok_is_still_bootstrap(caplog):
    """THE LIVE DEFECT this fix removes.

    The relay is still processing our AUTH when it closes the control
    subscription the auth branch just re-opened. Before the relay's OK for THIS
    auth event arrives, that CLOSED must still read as the ordinary bootstrap
    race (quiet, recovered) -- not a post-auth outage. Fails against the pre-fix
    connector, which flipped `_auth_completed` true the moment AUTH was SENT, so
    this exact sequence misclassified as a genuine post-auth refusal and logged
    the live warning: "relay demanded re-authentication for buzz-membership AFTER
    this connection completed NIP-42 auth"."""
    ch, _ = _started()
    ws = ScriptedWS(
        [
            '["AUTH","challenge-1"]',
            json.dumps(["CLOSED", "buzz-membership", "auth-required: not authenticated"]),
        ]
    )

    with caplog.at_level(logging.DEBUG, logger="app.channels.buzz"):
        asyncio.run(ch._session(ws))

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings == [], f"must stay quiet before the relay OKs our AUTH, got: {warnings}"
    assert "pending NIP-42 auth" in caplog.text


def test_ok_true_for_our_auth_event_marks_the_connection_authenticated():
    ch, _ = _started()
    ch._pending_auth_event_id = "auth-event-id-1"
    asyncio.run(ch.handle_relay_frame(json.dumps(["OK", "auth-event-id-1", True, "welcome"])))
    assert ch._auth_completed is True
    assert ch._pending_auth_event_id is None


def test_ok_false_for_our_auth_event_is_a_loud_failure_and_does_not_authenticate(caplog):
    """A relay-rejected AUTH is a real, actionable problem -- surfaced loudly --
    and must never leave the connection looking authenticated."""
    ch, _ = _started()
    ch._pending_auth_event_id = "auth-event-id-1"

    with caplog.at_level(logging.WARNING, logger="app.channels.buzz"):
        asyncio.run(ch.handle_relay_frame(json.dumps(["OK", "auth-event-id-1", False, "bad signature"])))

    assert ch._auth_completed is False
    assert ch._pending_auth_event_id is None
    assert "bad signature" in caplog.text
    assert "REJECTED" in caplog.text


def test_ok_frame_for_an_unrelated_event_does_not_affect_auth_state():
    """OK is sent for every published event (chat posts, edits, AUTH), not only
    AUTH. Anything that is not the one outstanding AUTH event id must be a no-op
    here -- a rejected chat publish is send()'s own retry-path problem, not this
    session's auth bookkeeping."""
    ch, _ = _started()
    ch._pending_auth_event_id = "auth-event-id-1"
    asyncio.run(ch.handle_relay_frame(json.dumps(["OK", "some-other-event-id", True, ""])))
    assert ch._auth_completed is False
    assert ch._pending_auth_event_id == "auth-event-id-1"  # untouched


def test_auth_required_close_after_relay_ok_true_stays_loud_via_the_real_ok_path(caplog):
    """The complementary required case, driven through the real OK handler rather
    than a manually-set flag: once the relay has genuinely acknowledged our AUTH,
    the same `auth-required:` reason on a later close is a real problem again."""
    ch, _ = _started()
    ch._pending_auth_event_id = "auth-event-id-1"
    asyncio.run(ch.handle_relay_frame(json.dumps(["OK", "auth-event-id-1", True, ""])))
    assert ch._auth_completed is True
    ch._transport = FakeTransport()

    with caplog.at_level(logging.DEBUG, logger="app.channels.buzz"):
        asyncio.run(ch.handle_relay_frame(json.dumps(["CLOSED", "buzz-membership", "auth-required: not authenticated"])))

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("buzz-membership" in m and "AFTER this connection completed NIP-42 auth" in m for m in warnings), warnings


def test_discovery_eose_implicitly_confirms_auth_when_relay_sends_no_ok():
    """Fallback for a relay that never sends an explicit `OK` for AUTH (NIP-42 says
    it SHOULD, not that it MUST). Reaching discovery EOSE on a re-opened control
    subscription is only possible if the relay actually accepted the session --
    an auth-rejecting relay CLOSEs it instead -- so this is treated as implicit
    confirmation rather than leaving `_auth_completed` false (and every later
    `auth-required:` close misclassified as bootstrap noise) for the rest of the
    connection."""
    ch, _ = _started()
    ch._pending_auth_event_id = "auth-event-id-1"

    asyncio.run(ch._on_discovery_complete())

    assert ch._auth_completed is True
    assert ch._pending_auth_event_id is None


def test_discovery_eose_without_a_pending_auth_send_does_not_fabricate_confirmation():
    """The fallback must only fire for an AUTH we actually sent and are awaiting an
    ack for -- not on every ordinary discovery EOSE (e.g. the very first, pre-auth
    one, if the relay happens to allow unauthenticated discovery reads)."""
    ch, _ = _started()
    assert ch._pending_auth_event_id is None

    asyncio.run(ch._on_discovery_complete())

    assert ch._auth_completed is False


# -- FINDING 1 defense in depth: never publish DeerFlow's hidden model context -----
#
# The manager-side allowlist (`_accumulate_stream_text`) is the fix. This is the
# second layer, and it lives here rather than in a sibling connector because on
# Buzz a leak is PERMANENT: every streaming update is an immutable public Nostr
# event, so a corrective edit only changes what clients render -- the original
# leaked event stays on the relay forever.


@pytest.mark.parametrize(
    "leaked",
    [
        "<memory>\nFacts:\n- [context | 0.70] User interacts with the assistant through the DeerFlow chat channel.\n</memory>",
        "<durable_context_data>\n## Conversation summary so far\nprivate\n</durable_context_data>",
        "Sure! <system-reminder>Today is 2026-08-01</system-reminder>",
    ],
)
def test_hidden_context_is_never_posted_to_the_relay(leaked, caplog):
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport

    with caplog.at_level(logging.ERROR, logger="app.channels.buzz"):
        asyncio.run(ch.send(_outbound(ch, leaked, is_final=False)))

    assert transport.sent == []
    assert "hidden" in caplog.text.lower()


def test_a_blocked_final_still_clears_the_stream_bookkeeping():
    """Refusing to publish must not strand the placeholder, or the next run in this
    conversation would edit an already-answered message."""
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport
    asyncio.run(ch.send(_outbound(ch, "working", is_final=False)))
    assert (CHANNEL, None) in ch._stream_targets

    asyncio.run(ch.send(_outbound(ch, "<memory>leak</memory>", is_final=True)))

    assert ch._stream_targets == {} and ch._stream_tails == {}


def test_ordinary_replies_that_merely_mention_the_words_are_still_published():
    """The guard keys on DeerFlow's literal hidden-context wrappers, not on prose."""
    ch, _ = _started()
    transport = FakeTransport()
    ch._transport = transport
    asyncio.run(ch.send(_outbound(ch, "I stored that in memory and in the durable context data.", is_final=True)))
    assert len(_events_of(transport)) == 1
