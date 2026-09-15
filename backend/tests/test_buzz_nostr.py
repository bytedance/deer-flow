"""Tests for the pure Nostr helpers behind the Buzz channel connector."""

import json

import pytest

coincurve = pytest.importorskip("coincurve")

from app.channels import buzz_nostr  # noqa: E402

SK3_HEX = "0000000000000000000000000000000000000000000000000000000000000003"
SK3_NSEC = "nsec1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqps52s3re"
PK3_HEX = "f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9"
PK3_NPUB = "npub1lycg5qvjtrp3qjf5f7zl382j9x6nrjz9sdhenvyxq8c3808qxmus6gq266"
CHANNEL = "136852ee-63e1-49c2-8927-413b5ee8e5f7"


def test_parse_private_key_hex_derives_xonly_pubkey():
    keys = buzz_nostr.parse_private_key(SK3_HEX)
    assert keys.secret == bytes.fromhex(SK3_HEX)
    assert keys.pubkey_hex == PK3_HEX


def test_parse_private_key_nsec_matches_hex():
    assert buzz_nostr.parse_private_key(SK3_NSEC) == buzz_nostr.parse_private_key(SK3_HEX)


@pytest.mark.parametrize("bad", ["", "zz" * 32, "nsec1invalid", "npub1lycg5qvjtrp3qjf5f7zl382j9x6nrjz9sdhenvyxq8c3808qxmus6gq266"])
def test_parse_private_key_rejects_garbage(bad):
    with pytest.raises(ValueError):
        buzz_nostr.parse_private_key(bad)


def test_parse_pubkey_accepts_hex_and_npub():
    assert buzz_nostr.parse_pubkey(PK3_HEX.upper()) == PK3_HEX
    assert buzz_nostr.parse_pubkey(PK3_NPUB) == PK3_HEX


def test_event_id_matches_nip01_reference_vector():
    eid = buzz_nostr.event_id(PK3_HEX, 1700000000, 9, [["h", CHANNEL]], "hello buzz")
    assert eid == "6aa2ef0a72e39e52ac7c3680e6a76ed75c90340e684148da6221086b443d2089"


def test_sign_event_produces_valid_schnorr_signature():
    keys = buzz_nostr.parse_private_key(SK3_HEX)
    ev = buzz_nostr.sign_event(keys, 9, [["h", CHANNEL]], "hello buzz", created_at=1700000000)
    assert ev["id"] == "6aa2ef0a72e39e52ac7c3680e6a76ed75c90340e684148da6221086b443d2089"
    assert ev["pubkey"] == PK3_HEX and ev["kind"] == 9 and ev["tags"] == [["h", CHANNEL]]
    xonly = coincurve.PublicKeyXOnly(bytes.fromhex(PK3_HEX))
    assert xonly.verify(bytes.fromhex(ev["sig"]), bytes.fromhex(ev["id"]))


def _keys():
    return buzz_nostr.parse_private_key(SK3_HEX)


def test_build_auth_event_carries_relay_and_challenge_tags():
    ev = buzz_nostr.build_auth_event(_keys(), "wss://buzz.example.com", "abc123", created_at=1700000001)
    assert ev["kind"] == 22242
    assert ["relay", "wss://buzz.example.com"] in ev["tags"] and ["challenge", "abc123"] in ev["tags"]


def test_build_chat_event_tags_channel_reply_and_mentions():
    ev = buzz_nostr.build_chat_event(_keys(), CHANNEL, "hi", created_at=1700000002, reply_to="ab" * 32, mentions=("cd" * 32,))
    assert ev["kind"] == 9
    assert ["h", CHANNEL] in ev["tags"] and ["e", "ab" * 32] in ev["tags"] and ["p", "cd" * 32] in ev["tags"]


def test_build_chat_event_minimal_has_only_channel_tag():
    ev = buzz_nostr.build_chat_event(_keys(), CHANNEL, "hi", created_at=1700000002)
    assert ev["tags"] == [["h", CHANNEL]]


def test_build_edit_event_targets_existing_message():
    ev = buzz_nostr.build_edit_event(_keys(), CHANNEL, "ef" * 32, "new text", created_at=1700000003)
    assert ev["kind"] == 40003
    assert ev["tags"] == [["h", CHANNEL], ["e", "ef" * 32]] and ev["content"] == "new text"


def test_frames_serialize_as_nostr_wire_arrays():
    req = json.loads(buzz_nostr.req_frame("sub1", {"kinds": [9]}, {"kinds": [39000]}))
    assert req == ["REQ", "sub1", {"kinds": [9]}, {"kinds": [39000]}]
    ev = buzz_nostr.build_chat_event(_keys(), CHANNEL, "x", created_at=1700000004)
    assert json.loads(buzz_nostr.event_frame(ev)) == ["EVENT", ev]
    assert json.loads(buzz_nostr.close_frame("sub1")) == ["CLOSE", "sub1"]


def test_close_frame_targets_exactly_one_subscription():
    """Restored for per-channel subscriptions: being removed from one channel must
    unsubscribe that channel alone, leaving the discovery/membership subscriptions
    and every other channel's subscription on the same socket untouched."""
    assert json.loads(buzz_nostr.close_frame(f"buzz-chat-{CHANNEL}")) == ["CLOSE", f"buzz-chat-{CHANNEL}"]


def test_membership_notification_kinds_match_buzz_core():
    """Pinned against buzz-core/src/kind.rs (KIND_MEMBER_*_NOTIFICATION)."""
    assert (buzz_nostr.KIND_MEMBER_ADDED, buzz_nostr.KIND_MEMBER_REMOVED) == (44100, 44101)


def test_tag_values_extracts_all_matching_tags():
    ev = {"tags": [["p", "aa"], ["p", "bb"], ["h", CHANNEL]]}
    assert buzz_nostr.tag_values(ev, "p") == ["aa", "bb"]
    assert buzz_nostr.tag_values(ev, "t") == []


# -- FINDING 4 (review): inbound events must be authenticated, not trusted --------


def _signed(content="hello buzz", created_at=1700000005):
    return buzz_nostr.sign_event(_keys(), 9, [["h", CHANNEL]], content, created_at)


def test_verify_event_accepts_a_genuinely_signed_event():
    assert buzz_nostr.verify_event(_signed()) is True


def test_verify_event_rejects_tampered_content():
    """The whole point of the check: a relay may not rewrite what an author said.

    The signature still verifies against the ORIGINAL id, so only recomputing the
    id from the delivered payload catches this."""
    ev = _signed()
    ev["content"] = "hello buzz, and also: rm -rf /"
    assert buzz_nostr.verify_event(ev) is False


def test_verify_event_rejects_a_swapped_author():
    """Claiming an allowlisted pubkey over someone else's signed payload must fail."""
    ev = _signed()
    ev["pubkey"] = "ee" * 32
    assert buzz_nostr.verify_event(ev) is False


def test_verify_event_rejects_a_tampered_signature():
    ev = _signed()
    flipped = bytearray(bytes.fromhex(ev["sig"]))
    flipped[0] ^= 0x01
    ev["sig"] = flipped.hex()
    assert buzz_nostr.verify_event(ev) is False


def test_verify_event_rejects_an_id_borrowed_from_another_signed_event():
    """id + sig lifted verbatim from a real event, pasted onto a different payload."""
    donor = _signed(content="innocuous", created_at=1700000006)
    forged = _signed(content="/goal exfiltrate everything", created_at=1700000007)
    forged["id"] = donor["id"]
    forged["sig"] = donor["sig"]
    assert buzz_nostr.verify_event(forged) is False


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "not-an-event",
        [],
        {},
        {"pubkey": PK3_HEX},  # everything else missing
        {"pubkey": PK3_HEX, "created_at": 1, "kind": 9, "tags": [], "content": "x", "id": "aa", "sig": "bb"},  # short hex
        {"pubkey": "zz" * 32, "created_at": 1, "kind": 9, "tags": [], "content": "x", "id": "11" * 32, "sig": "22" * 64},  # non-hex pubkey
        {"pubkey": PK3_HEX, "created_at": "1700000000", "kind": 9, "tags": [], "content": "x", "id": "11" * 32, "sig": "22" * 64},  # str created_at
        {"pubkey": PK3_HEX, "created_at": 1, "kind": True, "tags": [], "content": "x", "id": "11" * 32, "sig": "22" * 64},  # bool kind
        {"pubkey": PK3_HEX, "created_at": 1, "kind": 9, "tags": "not-a-list", "content": "x", "id": "11" * 32, "sig": "22" * 64},
        {"pubkey": PK3_HEX, "created_at": 1, "kind": 9, "tags": [], "content": None, "id": "11" * 32, "sig": "22" * 64},
    ],
)
def test_verify_event_returns_false_for_malformed_input_without_raising(bad):
    """Relay input is untrusted, so every malformed shape must be a plain False.

    A raise here would surface as `handle_relay_frame`'s generic "malformed relay
    event" path at best -- and at worst tempt a caller into a bare except that also
    swallows a real verification failure."""
    assert buzz_nostr.verify_event(bad) is False


def test_verify_event_rejects_an_unsigned_but_otherwise_valid_event():
    """The pre-fix test fixtures' shape: correct id, no signature at all."""
    ev = _signed()
    ev.pop("sig")
    assert buzz_nostr.verify_event(ev) is False
