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


@dataclass(frozen=True, slots=True)
class ClarificationCardRequest:
    """A button-renderable clarification extracted from outbound metadata."""

    request_id: str
    question: str
    options: tuple[str, ...]

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
        for raw in raw_options:
            if not isinstance(raw, dict):
                return None
            label = raw.get("label")
            if not (isinstance(label, str) and label):
                return None
            labels.append(label)

        return cls(request_id=request_id, question=question, options=tuple(labels))


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
                            "option_id": f"option-{index}",
                            "option_value": label,
                        },
                    }
                    for index, label in enumerate(request.options, start=1)
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
    ) -> None:
        entry: PendingCardEntry = {
            "request_id": request_id,
            "thread_id": thread_id,
            "chat_id": chat_id,
            "originator_open_id": originator_open_id,
            "options": options,
            "created_at": time.time(),
            "card_message_id": card_message_id,
        }
        with self._lock:
            self._entries[request_id] = entry

    def mark_sent(self, request_id: str, card_message_id: str) -> None:
        """Backfill the delivered card's message id once the send resolves."""
        with self._lock:
            entry = self._entries.get(request_id)
            if entry is not None:
                entry["card_message_id"] = card_message_id

    def consume(self, request_id: str, *, now: float | None = None) -> PendingCardEntry | None:
        """Pop the entry for *request_id*, or None when unknown or expired."""
        with self._lock:
            entry = self._entries.pop(request_id, None)
        if entry is None:
            return None
        created_at = entry.get("created_at")
        now = time.time() if now is None else now
        if not isinstance(created_at, (int, float)) or now - created_at > self._ttl_seconds:
            logger.info("[Feishu] pending card request expired: request_id=%s", request_id)
            return None
        return entry
