"""Shared pieces for the memory judging hooks: pre-screening and signal classification.

Both hooks judge **the same batch text**, build **the same wire state** and need
**the same kind of answer cache**, so those three things live here instead of
three times over (two adapters plus the coordinator).

What deliberately does **not** live here: the questions, rubrics, thresholds,
decision direction, modes, and failure policy. Pre-screening skips a call when the
text looks worthless (failure ⇒ extract as usual); signal classification only adds
hint text (failure ⇒ fall back to the deterministic signals). Those are adapter
policy, documented in:

* ``docs/superpowers/specs/2026-09-25-jev-memory-prescreening-design.en.md``
* ``docs/superpowers/specs/2026-09-25-jev-memory-signal-classification-design.en.md``
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from deerflow.typesafe.client import Answer

_DIGEST_CHARS = 16


def batch_digest(batch_text: str) -> str:
    """The batch's identity: its formatted text hashed. Cache key and audit identifier."""
    return hashlib.sha256(batch_text.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]


def conversation_tail_state(batch_text: str) -> dict[str, dict[str, str]]:
    """The wire state both hooks send: the formatted batch, and nothing else.

    Neither hook sends existing memory, fact ids, tool arguments, or the signals —
    "is this worth keeping / does this endorse something" is judged from the text
    alone (pre-screening design L10, signal-classification design S8).
    """
    return {"conversation_tail": {"text": batch_text}}


def batch_chars(batch_text: str) -> int:
    """The judged batch's length, for a side's ``max_state_chars`` limit.

    A **character** count of the formatted text, never its UTF-8 byte count: the
    shared client's ``wire_size`` reports bytes and replaces no consumer's limit
    (shared-client design §2.4). Counting bytes would move the fallback boundary
    — one CJK character is three of them (pre-screening design L5 / S16).
    """
    return len(batch_text)


@dataclass(frozen=True)
class CachedVerdict:
    """A judged state's validated answers, each tagged with the model that served it.

    ``models`` keeps provenance per answer rather than one model for the whole
    bucket: a later partial response merges into the bucket without re-attributing
    an earlier answer (served by a different model) to the new one, so a subsequent
    full cache hit still reports the model that actually produced the verdict.
    """

    answers: Mapping[str, Answer]
    models: Mapping[str, str]

    def model_for(self, question_ids: Iterable[str]) -> str:
        """The one model that served every *answered* ``question_ids`` entry, or "" when mixed.

        Only ids with a recorded model count: a question the bucket never answered
        is not consumed evidence, so a partially answered side attributes to the
        model that actually served the answers it used.
        """
        served = {self.models[question_id] for question_id in question_ids if question_id in self.models}
        return served.pop() if len(served) == 1 else ""


class AnswerCache:
    """FIFO + monotonic-TTL cache of validated answers, one entry per judged state.

    Cache semantics are the memory layer's own, never the shared transport's
    (pre-screening design L11, signal-classification design §2.2.6):

    * only **validated** answers are written, so a missing or malformed answer is a
      miss next time rather than a remembered failure;
    * an entry's ``answers`` is a per-question mapping, so a partial response is a
      partial entry: the consumer must subtract what the entry holds from the
      questions it wants and re-ask the difference, never read a partial entry as a
      full hit (signal-classification design §2.2.6 / S18);
    * a whole-request failure writes nothing;
    * ``size <= 0`` or ``ttl_seconds <= 0`` disables caching.

    ``key`` is opaque to this class; callers choose the namespace (a single side
    uses the digest, the coordinator adds its configuration fingerprint and the
    logical question set).
    """

    def __init__(self, *, size: int, ttl_seconds: float) -> None:
        self._size = size
        self._ttl_seconds = ttl_seconds
        self._entries: OrderedDict[object, tuple[CachedVerdict, float]] = OrderedDict()

    @property
    def enabled(self) -> bool:
        return self._size > 0 and self._ttl_seconds > 0

    def get(self, key: object) -> CachedVerdict | None:
        if not self.enabled:
            return None
        entry = self._entries.get(key)
        if entry is None:
            return None
        verdict, expires_at = entry
        if expires_at <= time.monotonic():
            # pop(): the memory queue's Timer thread and an executor-thread flush
            # can reach the same expired key, and a bare ``del`` would raise where
            # this must simply be a miss.
            self._entries.pop(key, None)
            return None
        return verdict

    def put(self, key: object, verdict: CachedVerdict) -> None:
        if not self.enabled:
            return
        self._entries[key] = (verdict, time.monotonic() + self._ttl_seconds)
        while len(self._entries) > self._size:
            self._entries.popitem(last=False)


__all__ = ["AnswerCache", "CachedVerdict", "batch_chars", "batch_digest", "conversation_tail_state"]
