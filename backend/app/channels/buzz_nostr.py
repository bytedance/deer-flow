"""Pure Nostr (NIP-01) helpers for the Buzz channel connector.

No I/O, no wall-clock: callers supply ``created_at``. BIP-340 signing is done via
``coincurve``, which ships in the optional ``buzz`` dependency extra and is imported
lazily so the rest of the app never requires it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

COINCURVE_INSTALL_HINT = "The Buzz channel requires the 'buzz' extra: run `uv sync --extra buzz` (installs coincurve for BIP-340 signing)."


def _require_coincurve():
    try:
        import coincurve
    except ImportError as exc:  # pragma: no cover - exercised via BuzzChannel.start
        raise RuntimeError(COINCURVE_INSTALL_HINT) from exc
    return coincurve


@dataclass(frozen=True)
class NostrKeys:
    secret: bytes
    pubkey_hex: str


def _bech32_polymod(values: list[int]) -> int:
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if ((b >> i) & 1) else 0
    return chk


def _bech32_decode(expected_hrp: str, value: str) -> bytes:
    if "1" not in value:
        raise ValueError(f"not bech32: {value!r}")
    hrp, data_part = value.rsplit("1", 1)
    if hrp != expected_hrp:
        raise ValueError(f"expected {expected_hrp!r} bech32, got {hrp!r}")
    try:
        data = [_BECH32_CHARSET.index(c) for c in data_part]
    except ValueError as exc:
        raise ValueError(f"invalid bech32 character in {value!r}") from exc
    hrp_expanded = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
    if _bech32_polymod(hrp_expanded + data) != 1:
        raise ValueError(f"bad bech32 checksum in {value!r}")
    acc = bits = 0
    out = bytearray()
    for v in data[:-6]:
        acc = (acc << 5) | v
        bits += 5
        if bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
    if len(out) != 32:
        raise ValueError(f"expected 32-byte payload in {value!r}")
    return bytes(out)


def _parse_32_bytes(value: str, bech_hrp: str) -> bytes:
    value = value.strip()
    if value.lower().startswith(f"{bech_hrp}1"):
        return _bech32_decode(bech_hrp, value.lower())
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"expected 64-hex or {bech_hrp}1... value") from exc
    if len(raw) != 32:
        raise ValueError("expected exactly 32 bytes")
    return raw


def parse_private_key(value: str) -> NostrKeys:
    secret = _parse_32_bytes(value, "nsec")
    coincurve = _require_coincurve()
    pubkey = coincurve.PrivateKey(secret).public_key.format(compressed=True)[1:]
    return NostrKeys(secret=secret, pubkey_hex=pubkey.hex())


def parse_pubkey(value: str) -> str:
    return _parse_32_bytes(value, "npub").hex()


def event_id(pubkey_hex: str, created_at: int, kind: int, tags: list[list[str]], content: str) -> str:
    payload = json.dumps([0, pubkey_hex, created_at, kind, tags, content], separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def sign_event(keys: NostrKeys, kind: int, tags: list[list[str]], content: str, created_at: int) -> dict:
    coincurve = _require_coincurve()
    eid = event_id(keys.pubkey_hex, created_at, kind, tags, content)
    sig = coincurve.PrivateKey(keys.secret).sign_schnorr(bytes.fromhex(eid))
    return {"id": eid, "pubkey": keys.pubkey_hex, "created_at": created_at, "kind": kind, "tags": tags, "content": content, "sig": sig.hex()}


KIND_CHAT = 9
KIND_EDIT = 40003
KIND_AUTH = 22242
KIND_CHANNEL_META = 39000
# Relay-signed membership notifications (buzz-core's KIND_MEMBER_ADDED_NOTIFICATION /
# KIND_MEMBER_REMOVED_NOTIFICATION). Each carries ``p`` = the affected member's pubkey
# and ``h`` = the channel uuid, which is how a connected client learns it was added to
# (or removed from) a channel without reconnecting.
KIND_MEMBER_ADDED = 44100
KIND_MEMBER_REMOVED = 44101


def build_auth_event(keys: NostrKeys, relay_url: str, challenge: str, created_at: int) -> dict:
    return sign_event(keys, KIND_AUTH, [["relay", relay_url], ["challenge", challenge]], "", created_at)


def build_chat_event(keys: NostrKeys, channel_id: str, content: str, created_at: int, reply_to: str | None = None, mentions: tuple[str, ...] = ()) -> dict:
    tags: list[list[str]] = [["h", channel_id]]
    if reply_to:
        tags.append(["e", reply_to])
    tags.extend(["p", m] for m in mentions)
    return sign_event(keys, KIND_CHAT, tags, content, created_at)


def build_edit_event(keys: NostrKeys, channel_id: str, target_event_id: str, content: str, created_at: int) -> dict:
    return sign_event(keys, KIND_EDIT, [["h", channel_id], ["e", target_event_id]], content, created_at)


def verify_event(event: Any) -> bool:
    """True only when *event* carries a self-consistent id and a valid BIP-340 signature.

    Two independent checks, both required:

    1. The NIP-01 event id is RECOMPUTED from the event's own
       ``pubkey``/``created_at``/``kind``/``tags``/``content`` and must equal the
       ``id`` the sender claims -- so ``id`` cannot be borrowed from a different
       (legitimately signed) event while the payload is swapped.
    2. The Schnorr signature must verify against that id under the claimed
       ``pubkey``, which is what actually binds the payload to its author.

    Relay input is untrusted, so this NEVER raises: any missing, mistyped,
    non-hex, or wrong-length field -- or a payload that is not even a mapping --
    is simply an event that fails to verify, and callers must be able to treat
    "malformed" and "forged" identically without a try/except at every call site.
    A missing ``coincurve`` (the optional ``buzz`` extra) also lands here and
    fails closed; it is unreachable in practice because ``BuzzChannel.start()``
    already parses its private key through ``coincurve`` and would have failed
    with :data:`COINCURVE_INSTALL_HINT` long before any event arrived.
    """
    try:
        if not isinstance(event, dict):
            return False
        pubkey = event.get("pubkey")
        sig = event.get("sig")
        claimed_id = event.get("id")
        content = event.get("content")
        created_at = event.get("created_at")
        kind = event.get("kind")
        tags = event.get("tags")
        # bool is an int subclass; a JSON `true` in either numeric field would
        # otherwise serialize as "true" and silently change the canonical form.
        if not isinstance(pubkey, str) or not isinstance(sig, str) or not isinstance(claimed_id, str) or not isinstance(content, str) or not isinstance(tags, list):
            return False
        if not isinstance(created_at, int) or isinstance(created_at, bool) or not isinstance(kind, int) or isinstance(kind, bool):
            return False
        if event_id(pubkey, created_at, kind, tags, content) != claimed_id:
            return False
        coincurve = _require_coincurve()
        return bool(coincurve.PublicKeyXOnly(bytes.fromhex(pubkey)).verify(bytes.fromhex(sig), bytes.fromhex(claimed_id)))
    except Exception:
        return False


def req_frame(sub_id: str, *filters: dict) -> str:
    return json.dumps(["REQ", sub_id, *filters], separators=(",", ":"))


def event_frame(event: dict) -> str:
    return json.dumps(["EVENT", event], separators=(",", ":"))


def close_frame(sub_id: str) -> str:
    """NIP-01 ``CLOSE``: stop an individual subscription without dropping the socket.

    Needed because chat subscriptions are per channel (the relay only fans kind-9
    events out to ``#h``-scoped subscriptions), so being removed from a channel has
    to unsubscribe exactly that one -- the other channels' subscriptions, the
    discovery subscription, and the membership subscription all ride the same
    connection and must survive.
    """
    return json.dumps(["CLOSE", sub_id], separators=(",", ":"))


def tag_values(event: dict, name: str) -> list[str]:
    return [t[1] for t in event.get("tags", []) if len(t) >= 2 and t[0] == name]
