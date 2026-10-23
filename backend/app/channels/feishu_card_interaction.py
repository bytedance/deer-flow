"""Feishu interactive clarification cards — outbound half.

When an ``ask_clarification`` interrupt carries options, the Feishu channel can
render the question as an interactive button card instead of plain text. This
module owns the two pieces of that path:

- :class:`ClarificationCardRequest` — extracts the renderable request from an
  outbound message's ``human_input_request`` metadata (``choice_with_other``
  mode only; free-text and form clarifications keep the plain-text path).
- :class:`PendingCardRegistry` — the in-process pending-request table that the
  inbound half (card-action callbacks) validates clicks against.

Design rules:

- protocol request ids may repeat across runs; each rendered card gets a
  separate random callback token, bound to the originator and consumed once.
- the registry is process-local by design: under multi-worker deployments a
  callback landing on the wrong process finds no entry and must fail closed.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, TypedDict

from app.channels.message_bus import HUMAN_INPUT_REQUEST_METADATA_KEY

logger = logging.getLogger(__name__)

# Feishu renders one action row legibly up to four buttons; beyond that the
# plain-text fallback reads better than a wrapped button pile.
MAX_CARD_OPTIONS = 4

# Mirrors PENDING_CLARIFICATION_TTL_SECONDS: a clarification unanswered for 30
# minutes is abandoned, whether the answer path is typed text or a button.
PENDING_CARD_TTL_SECONDS = 30 * 60


class PendingCardEntry(TypedDict):
    request_id: str
    source: str
    thread_id: str
    chat_id: str
    originator_open_id: str
    options: tuple[str, ...]
    option_ids: tuple[str, ...]
    created_at: float
    card_message_id: str | None
    # Routing identity the ChannelManager keys on; without these the synthetic
    # inbound would open a new thread (groups) or be rejected as unbound.
    topic_id: str | None
    connection_id: str | None
    owner_user_id: str | None


@dataclass(frozen=True, slots=True)
class ClarificationCardRequest:
    """A button-renderable clarification extracted from outbound metadata."""

    request_id: str
    source: str
    question: str
    options: tuple[str, ...]
    option_ids: tuple[str, ...]
    callback_token: str
    context: str | None = None

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any] | None) -> ClarificationCardRequest | None:
        if not metadata:
            return None
        payload = metadata.get(HUMAN_INPUT_REQUEST_METADATA_KEY)
        if not isinstance(payload, dict):
            return None
        if payload.get("kind") != "human_input_request":
            return None
        if payload.get("input_mode") != "choice_with_other":
            return None

        request_id = payload.get("request_id")
        source = payload.get("source")
        question = payload.get("question")
        context = payload.get("context")
        raw_options = payload.get("options")
        if not (isinstance(request_id, str) and request_id):
            return None
        if not (isinstance(source, str) and source):
            return None
        if not (isinstance(question, str) and question):
            return None
        if not isinstance(raw_options, list) or not raw_options or len(raw_options) > MAX_CARD_OPTIONS:
            return None

        labels: list[str] = []
        option_ids: list[str] = []
        for index, raw in enumerate(raw_options, start=1):
            if not isinstance(raw, dict):
                return None
            label = raw.get("label")
            if not (isinstance(label, str) and label):
                return None
            option_id = raw.get("id")
            if not (isinstance(option_id, str) and option_id):
                option_id = f"option-{index}"
            labels.append(label)
            option_ids.append(option_id)

        return cls(
            request_id=request_id,
            source=source,
            question=question,
            options=tuple(labels),
            option_ids=tuple(option_ids),
            callback_token=secrets.token_urlsafe(32),
            context=context if isinstance(context, str) and context.strip() else None,
        )


def build_button_card(request: ClarificationCardRequest) -> str:
    """Render the clarification as a Feishu interactive card with one button per option."""
    content = f"{request.context}\n\n{request.question}" if request.context else request.question
    card = {
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {"title": {"tag": "plain_text", "content": "需要你的选择"}},
        "elements": [
            {"tag": "markdown", "content": content},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": label},
                        "type": "primary" if index == 1 else "default",
                        "value": {
                            "callback_token": request.callback_token,
                            "option_id": option_id,
                            "option_value": label,
                        },
                    }
                    for index, (option_id, label) in enumerate(zip(request.option_ids, request.options), start=1)
                ],
            },
        ],
    }
    return json.dumps(card, ensure_ascii=False)


class PendingCardRegistry:
    """Process-local table of unanswered button cards, keyed by callback token.

    Consumption is one-time: a resolved (or expired) entry is removed before
    the caller acts on it, so replays see "unknown" and fail closed.
    """

    def __init__(self, *, ttl_seconds: float = PENDING_CARD_TTL_SECONDS, max_entries: int = 1000) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._entries: dict[str, PendingCardEntry] = {}
        self._lock = threading.Lock()

    def register(
        self,
        *,
        callback_token: str,
        request_id: str,
        source: str,
        thread_id: str,
        chat_id: str,
        originator_open_id: str,
        options: tuple[str, ...],
        option_ids: tuple[str, ...],
        card_message_id: str | None = None,
        topic_id: str | None = None,
        connection_id: str | None = None,
        owner_user_id: str | None = None,
    ) -> None:
        entry: PendingCardEntry = {
            "request_id": request_id,
            "source": source,
            "thread_id": thread_id,
            "chat_id": chat_id,
            "originator_open_id": originator_open_id,
            "options": options,
            "option_ids": option_ids,
            "created_at": time.time(),
            "card_message_id": card_message_id,
            "topic_id": topic_id,
            "connection_id": connection_id,
            "owner_user_id": owner_user_id,
        }
        with self._lock:
            expired = [token for token, pending in self._entries.items() if entry["created_at"] - pending["created_at"] > self._ttl_seconds]
            for token in expired:
                del self._entries[token]
            if callback_token in self._entries:
                raise ValueError("A pending card already owns this callback token")
            if len(self._entries) >= self._max_entries:
                del self._entries[next(iter(self._entries))]
            self._entries[callback_token] = entry

    def consume_if_originator(
        self,
        callback_token: str,
        operator_open_id: str,
        *,
        option_id: str,
        option_value: str,
        now: float | None = None,
    ) -> tuple[PendingCardEntry | None, str | None]:
        """Atomically validate a click and consume the entry on success.

        Returns ``(entry, None)`` for the originator clicking a registered
        option; ``(None, "not_originator")`` for anyone else (entry kept — the
        real originator may still click); ``(None, "unknown")`` for unknown or
        expired tokens (entry dropped) and for option ID/value pairs the registry
        never issued (entry kept — the card payload itself is not trusted).
        """
        with self._lock:
            entry = self._entries.get(callback_token)
            if entry is None:
                return None, "unknown"
            created_at = entry.get("created_at")
            now = time.time() if now is None else now
            if not isinstance(created_at, (int, float)) or now - created_at > self._ttl_seconds:
                del self._entries[callback_token]
                logger.info("[Feishu] pending card request expired: request_id=%s", entry["request_id"])
                return None, "unknown"
            if entry.get("originator_open_id") != operator_open_id:
                return None, "not_originator"
            if (option_id, option_value) not in zip(entry["option_ids"], entry["options"]):
                return None, "unknown"
            del self._entries[callback_token]
            return entry, None

    def discard_card(self, chat_id: str, originator_open_id: str, card_message_id: str) -> None:
        """Retire a card answered through the accepted plain-text path."""
        with self._lock:
            tokens = [token for token, entry in self._entries.items() if (entry["chat_id"], entry["originator_open_id"], entry["card_message_id"]) == (chat_id, originator_open_id, card_message_id)]
            for token in tokens:
                del self._entries[token]

    def discard_thread(self, thread_id: str) -> int:
        """Retire all pending cards registered for a given thread."""
        with self._lock:
            tokens = [token for token, entry in self._entries.items() if entry.get("thread_id") == thread_id]
            for token in tokens:
                del self._entries[token]
            return len(tokens)

    def prune_expired(self, now: float | None = None) -> int:
        """Prune all expired entries from the registry and return the count."""
        now = time.time() if now is None else now
        with self._lock:
            expired = [token for token, pending in self._entries.items() if now - pending.get("created_at", 0) > self._ttl_seconds]
            for token in expired:
                del self._entries[token]
            return len(expired)

    def get_pending_entry(self, callback_token: str) -> PendingCardEntry | None:
        """Read-only lookup of a pending entry without consuming it."""
        with self._lock:
            entry = self._entries.get(callback_token)
            return dict(entry) if entry is not None else None  # type: ignore[return-value]

    def __len__(self) -> int:
        """Return the number of tracked pending cards."""
        with self._lock:
            return len(self._entries)
