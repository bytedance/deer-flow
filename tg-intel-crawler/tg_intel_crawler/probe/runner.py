"""Per-candidate probe runner + classification pure function.

Talks to the bot via the existing BotSearchClient/BotResponseParser. The
classify() function is a pure mapping from (reply_status, previews) to one
of five categories — kept pure so it's trivially testable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from tg_intel_crawler.collector.bot_response_parser import BotPreview
from tg_intel_crawler.collector.bot_search_throttle import BotQueryLimitExceeded
from tg_intel_crawler.probe.sampler import SampledCandidate


# Maximum length to keep for raw bot replies in the report — protects
# against a bot dumping a megabyte of text.
_RAW_TRUNCATE = 4096


@dataclass
class ProbeRecord:
    """Outcome of probing a single candidate.

    ``reply_raw`` is truncated to _RAW_TRUNCATE chars with a marker suffix.
    ``matched_preview`` is None unless classification == 'direct_hit'.
    """

    candidate: SampledCandidate
    query_sent: str
    reply_status: str            # "ok" | "empty_reply" | "error"
    reply_raw: str               # may be truncated
    error: str | None            # exception class+message, only when reply_status='error'
    previews_count: int
    matched_preview: dict | None
    classification: str          # "direct_hit" | "indirect_hit" | "no_results"
                                 # | "empty_reply" | "error"


def classify(
    *,
    candidate_key: str,
    reply_status: str,
    previews: list[BotPreview],
) -> str:
    """Map (reply_status, previews) → category. Pure function.

    Order matters: error short-circuits, empty_reply next, then look at
    previews for hit/no_results.
    """
    if reply_status == "error":
        return "error"
    if reply_status == "empty_reply":
        return "empty_reply"

    if not previews:
        return "no_results"

    key_lower = candidate_key.lower()
    for p in previews:
        cu = (p.channel_username or "").lower()
        if cu and cu == key_lower:
            return "direct_hit"
    return "indirect_hit"


logger = logging.getLogger("tg_crawler")


class ProbeRunner:
    """Drive the probe over a list of SampledCandidate.

    The bot client / parser / throttle are injected so unit tests can stub
    them. Production code wires up BotSearchClient + BotResponseParser +
    BotQueryThrottle from main.py.
    """

    def __init__(self, *, bot_client, parser, throttle, bot_name: str):
        self._bot = bot_client
        self._parser = parser
        self._throttle = throttle
        self._bot_name = bot_name

    @staticmethod
    def _build_query(candidate: SampledCandidate) -> str:
        """Public → key as-is. Private → strip the leading '+' so the bot
        sees the bare invite hash (cleaner search input)."""
        if candidate.candidate_type == "private":
            return candidate.key.lstrip("+")
        return candidate.key

    @staticmethod
    def _truncate(text: str) -> str:
        if len(text) <= _RAW_TRUNCATE:
            return text
        return text[:_RAW_TRUNCATE] + "... [truncated]"

    @staticmethod
    def _matched_preview_dict(previews: list[BotPreview], key_lower: str) -> dict | None:
        for p in previews:
            cu = (p.channel_username or "").lower()
            if cu and cu == key_lower:
                return {
                    "channel_username": p.channel_username,
                    "msg_id": p.msg_id,
                    "text": p.text,
                    "deeplink": p.deeplink,
                    "raw_line": p.raw_line,
                }
        return None

    async def probe_one(self, candidate: SampledCandidate) -> ProbeRecord:
        """Probe one candidate. Catches all exceptions so a single bad one
        doesn't sink the whole batch."""
        query = self._build_query(candidate)
        reply_status = "ok"
        reply_raw = ""
        error: str | None = None
        previews: list[BotPreview] = []

        try:
            reply = await self._bot.query(query)
        except Exception as e:
            reply_status = "error"
            error = f"{type(e).__name__}: {e}"
            reply = None

        if reply_status != "error":
            if reply is None or not str(reply).strip():
                reply_status = "empty_reply"
                reply_raw = ""
            else:
                reply_raw = str(reply)
                try:
                    previews = self._parser.parse(
                        reply_raw, query=query, bot=self._bot_name,
                    )
                except Exception as e:
                    reply_status = "error"
                    error = f"{type(e).__name__}: {e}"
                    previews = []

        cls = classify(
            candidate_key=candidate.key,
            reply_status=reply_status,
            previews=previews,
        )

        matched = (
            self._matched_preview_dict(previews, candidate.key.lower())
            if cls == "direct_hit" else None
        )

        return ProbeRecord(
            candidate=candidate,
            query_sent=query,
            reply_status=reply_status,
            reply_raw=self._truncate(reply_raw),
            error=error,
            previews_count=len(previews),
            matched_preview=matched,
            classification=cls,
        )

    async def run(
        self, samples: list[SampledCandidate],
    ) -> tuple[list[ProbeRecord], bool]:
        """Probe every sample. Returns (records, truncated).

        If the throttle hits its per-run cap, we stop early and return
        what we have with truncated=True.
        """
        records: list[ProbeRecord] = []
        truncated = False
        for i, sample in enumerate(samples, 1):
            try:
                await self._throttle.acquire()
            except BotQueryLimitExceeded:
                logger.warning(
                    "probe: throttle cap reached after %d/%d samples",
                    i - 1, len(samples),
                )
                truncated = True
                break
            record = await self.probe_one(sample)
            records.append(record)
            logger.info(
                "probe %d/%d: %s [%s] → %s",
                i, len(samples), sample.key, sample.stratum, record.classification,
            )
        return records, truncated
