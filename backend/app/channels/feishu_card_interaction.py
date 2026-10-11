"""Feishu interactive clarification cards — outbound half.

When an ``ask_clarification`` interrupt carries options, the Feishu channel can
render the question as an interactive button card instead of plain text. This
module owns the two pieces of that path:

- :class:`ClarificationCardRequest` — extracts the renderable request from an
  outbound message's ``human_input_request`` metadata (``choice_with_other``
  mode only; free-text and form clarifications keep the plain-text path).
- :class:`PendingCardRegistry` — the in-process pending-request table that the
  inbound half (card-action callbacks) validates clicks against.

Design rules (see .scratch/lark-card-auth/decisions.md):

- request ids come from the clarification middleware (``clarification:<id>``);
  they are unguessable to anyone who cannot see the run's tool calls, and the
  inbound half adds originator-open_id validation plus one-time consumption.
- the registry is process-local by design: under multi-worker deployments a
  callback landing on the wrong process finds no entry and must fail closed.
"""

from __future__ import annotations

import json
import logging
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


class PendingCardEntry(TypedDict, total=False):
    request_id: str
    thread_id: str
    chat_id: str
    originator_open_id: str
    options: tuple[str, ...]
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
    question: str
    options: tuple[str, ...]
    option_ids: tuple[str, ...]

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
        question = payload.get("question")
        raw_options = payload.get("options")
        if not (isinstance(request_id, str) and request_id):
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

        return cls(request_id=request_id, question=question, options=tuple(labels), option_ids=tuple(option_ids))


def build_button_card(request: ClarificationCardRequest) -> str:
    """Render the clarification as a Feishu interactive card with one button per option."""
    card = {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": "需要你的选择"}},
        "elements": [
            {"tag": "markdown", "content": request.question},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": label},
                        "type": "primary" if index == 1 else "default",
                        "value": {
                            "request_id": request.request_id,
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
    """Process-local table of unanswered button cards, keyed by request id.

    Consumption is one-time: a resolved (or expired) entry is removed before
    the caller acts on it, so replays see "unknown" and fail closed.
    """

    def __init__(self, *, ttl_seconds: float = PENDING_CARD_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._entries: dict[str, PendingCardEntry] = {}
        self._lock = threading.Lock()

    def register(
        self,
        *,
        request_id: str,
        thread_id: str,
        chat_id: str,
        originator_open_id: str,
        options: tuple[str, ...],
        card_message_id: str | None = None,
        topic_id: str | None = None,
        connection_id: str | None = None,
        owner_user_id: str | None = None,
    ) -> None:
        entry: PendingCardEntry = {
            "request_id": request_id,
            "thread_id": thread_id,
            "chat_id": chat_id,
            "originator_open_id": originator_open_id,
            "options": options,
            "created_at": time.time(),
            "card_message_id": card_message_id,
            "topic_id": topic_id,
            "connection_id": connection_id,
            "owner_user_id": owner_user_id,
        }
        with self._lock:
            self._entries[request_id] = entry

    def consume_if_originator(
        self,
        request_id: str,
        operator_open_id: str,
        *,
        option_value: str | None = None,
        now: float | None = None,
    ) -> tuple[PendingCardEntry | None, str | None]:
        """Atomically validate a click and consume the entry on success.

        Returns ``(entry, None)`` for the originator clicking a registered
        option; ``(None, "not_originator")`` for anyone else (entry kept — the
        real originator may still click); ``(None, "unknown")`` for unknown or
        expired request ids (entry dropped) and for option values the registry
        never issued (entry kept — the card payload itself is not trusted).
        """
        with self._lock:
            entry = self._entries.get(request_id)
            if entry is None:
                return None, "unknown"
            created_at = entry.get("created_at")
            now = time.time() if now is None else now
            if not isinstance(created_at, (int, float)) or now - created_at > self._ttl_seconds:
                del self._entries[request_id]
                logger.info("[Feishu] pending card request expired: request_id=%s", request_id)
                return None, "unknown"
            if entry.get("originator_open_id") != operator_open_id:
                return None, "not_originator"
            if option_value is not None and option_value not in entry.get("options", ()):
                return None, "unknown"
            del self._entries[request_id]
            return entry, None
