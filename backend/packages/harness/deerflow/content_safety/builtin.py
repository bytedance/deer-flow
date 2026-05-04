"""Built-in content safety providers that ship with DeerFlow."""

from __future__ import annotations

import logging
import re

from deerflow.content_safety.provider import ContentSafetyDecision, ContentSafetyProvider, ContentSafetyRequest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PII detection patterns
# ---------------------------------------------------------------------------

_CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,16}\b")

_PHONE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"1[3-9]\d{9}"),  # Chinese mobile
    re.compile(r"\+86[ -]?1[3-9]\d{9}"),  # Chinese mobile with country code
    re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"),  # US/Canada
]

_CHINESE_ID_PATTERN = re.compile(r"\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b")

_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

_IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _luhn_check(card_number: str) -> bool:
    """Validate a credit card number using the Luhn algorithm."""
    digits = [int(c) for c in card_number if c.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


class RegexPIIProvider:
    """Zero-dependency PII detection using regex patterns.

    Detects: credit card numbers, phone numbers, Chinese ID numbers,
    email addresses, and IP addresses.
    """

    name = "regex_pii"

    def __init__(
        self,
        *,
        detect_credit_cards: bool = True,
        detect_phones: bool = True,
        detect_chinese_ids: bool = True,
        detect_emails: bool = True,
        detect_ips: bool = False,
        action: str = "mask",
        **_kwargs: object,
    ) -> None:
        self._detect_credit_cards = detect_credit_cards
        self._detect_phones = detect_phones
        self._detect_chinese_ids = detect_chinese_ids
        self._detect_emails = detect_emails
        self._detect_ips = detect_ips
        self.action = action

    def evaluate(self, request: ContentSafetyRequest) -> ContentSafetyDecision:
        flagged: list[str] = []
        sanitized = request.text

        if self._detect_credit_cards:
            for match in _CREDIT_CARD_PATTERN.finditer(sanitized):
                card = match.group()
                cleaned = re.sub(r"[^0-9]", "", card)
                if _luhn_check(cleaned):
                    flagged.append("credit_card")
                    if self.action == "mask":
                        sanitized = sanitized.replace(card, "[CREDIT_CARD]")

        if self._detect_chinese_ids:
            for match in _CHINESE_ID_PATTERN.finditer(sanitized):
                flagged.append("chinese_id")
                if self.action == "mask":
                    sanitized = sanitized.replace(match.group(), "[CHINESE_ID]")

        if self._detect_phones:
            for pattern in _PHONE_PATTERNS:
                for match in pattern.finditer(sanitized):
                    flagged.append("phone")
                    if self.action == "mask":
                        sanitized = sanitized.replace(match.group(), "[PHONE]")

        if self._detect_emails:
            for match in _EMAIL_PATTERN.finditer(sanitized):
                flagged.append("email")
                if self.action == "mask":
                    sanitized = sanitized.replace(match.group(), "[EMAIL]")

        if self._detect_ips:
            for match in _IP_PATTERN.finditer(sanitized):
                flagged.append("ip_address")
                if self.action == "mask":
                    sanitized = sanitized.replace(match.group(), "[IP_ADDRESS]")

        if flagged and self.action == "block":
            return ContentSafetyDecision(
                allowed=False,
                flagged_categories=flagged,
                reasons=[f"PII detected: {', '.join(flagged)}"],
            )

        if flagged:
            return ContentSafetyDecision(
                allowed=True,
                flagged_categories=flagged,
                sanitized_text=sanitized,
                reasons=[f"PII masked: {', '.join(flagged)}"],
            )

        return ContentSafetyDecision(allowed=True)

    async def aevaluate(self, request: ContentSafetyRequest) -> ContentSafetyDecision:
        return self.evaluate(request)


class OpenAIModerationProvider:
    """Content moderation using the OpenAI Moderation API.

    Requires the ``openai`` package (already a transitive dependency).
    """

    name = "openai_moderation"

    def __init__(
        self,
        *,
        model: str = "text-moderation-latest",
        api_key: str | None = None,
        base_url: str | None = None,
        threshold: float = 0.5,
        blocked_categories: list[str] | None = None,
        **_kwargs: object,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._threshold = threshold
        self._blocked_categories = set(blocked_categories or ["hate", "sexual", "violence", "self-harm", "harassment"])
        self._client: object | None = None

    def _get_client(self) -> object:
        if self._client is None:
            from openai import OpenAI

            kwargs: dict = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = OpenAI(**kwargs)
        return self._client

    def evaluate(self, request: ContentSafetyRequest) -> ContentSafetyDecision:
        try:
            client = self._get_client()
            response = client.moderations.create(  # type: ignore[attr-defined]
                model=self._model,
                input=request.text,
            )
            result = response.results[0]
            flagged_categories = [
                cat for cat, flagged in result.categories.model_dump().items() if flagged and cat in self._blocked_categories
            ]
            if flagged_categories:
                return ContentSafetyDecision(
                    allowed=False,
                    flagged_categories=flagged_categories,
                    reasons=[f"Content flagged by moderation API: {', '.join(flagged_categories)}"],
                )
            return ContentSafetyDecision(allowed=True)
        except Exception:
            logger.exception("OpenAI Moderation API call failed")
            return ContentSafetyDecision(allowed=True, reasons=["Moderation API unavailable — allowing content"])

    async def aevaluate(self, request: ContentSafetyRequest) -> ContentSafetyDecision:
        try:
            from openai import AsyncOpenAI

            kwargs: dict = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._base_url:
                kwargs["base_url"] = self._base_url
            client = AsyncOpenAI(**kwargs)
            response = await client.moderations.create(
                model=self._model,
                input=request.text,
            )
            result = response.results[0]
            flagged_categories = [
                cat for cat, flagged in result.categories.model_dump().items() if flagged and cat in self._blocked_categories
            ]
            if flagged_categories:
                return ContentSafetyDecision(
                    allowed=False,
                    flagged_categories=flagged_categories,
                    reasons=[f"Content flagged by moderation API: {', '.join(flagged_categories)}"],
                )
            return ContentSafetyDecision(allowed=True)
        except Exception:
            logger.exception("OpenAI Moderation API async call failed")
            return ContentSafetyDecision(allowed=True, reasons=["Moderation API unavailable — allowing content"])
