"""Prompt injection detection using heuristic pattern matching."""

from __future__ import annotations

import logging
import re

from deerflow.content_safety.provider import ContentSafetyDecision, ContentSafetyRequest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Injection patterns
# ---------------------------------------------------------------------------

_DIRECT_OVERRIDE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above|foregoing)\s+(instructions?|directives?|prompts?|messages?)", re.IGNORECASE),
    re.compile(r"忽略(所有)?(之前|前面|上述|以上)的?(指令|指示|提示|说明)", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(previous|prior|earlier)\s+(instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior)\s+(instructions?|directives?)", re.IGNORECASE),
    re.compile(r"override\s+(the\s+)?(system\s+)?(prompt|instructions?)", re.IGNORECASE),
    re.compile(r"do\s+not\s+follow\s+(previous|prior|original)\s+(instructions?|prompts?)", re.IGNORECASE),
]

_ROLEPLAY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"you\s+are\s+now\s+(DAN|STAN|DUDE)", re.IGNORECASE),
    re.compile(r"from\s+now\s+on\s+you\s+(are|will\s+be|act\s+as)\s+(a\s+)?(different|new)\s+(AI|assistant|model|persona)", re.IGNORECASE),
    re.compile(r"pretend\s+(you\s+are|to\s+be)\s+(a\s+)?(different|someone\s+else|another)", re.IGNORECASE),
    re.compile(r"你现在是\s*(DAN|STAN|越狱)", re.IGNORECASE),
    re.compile(r"从现在开始你(是|扮演|假装)", re.IGNORECASE),
]

_DELIMITER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"<\|begin_of_text\|>"),
    re.compile(r"<\|start_header_id\|>"),
    re.compile(r"<<SYS>>"),
    re.compile(r"<\|im_start\|>"),
    re.compile(r"<\|im_end\|>"),
    re.compile(r"---BEGIN\s+(SYSTEM|INSTRUCTIONS?)---"),
    re.compile(r"\[INST\]"),
    re.compile(r"\[/INST\]"),
    re.compile(r"\[SYSTEM\]"),
    re.compile(r"\[/SYSTEM\]"),
]

_OBFUSCATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"),
    re.compile(r"(.)\1{8,}"),
    re.compile(r"[​-‏ - ⁠-⁯­﻿]{3,}"),
]

_JAILBREAK_KEYWORDS: list[re.Pattern[str]] = [
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"越狱", re.IGNORECASE),
    re.compile(r"bypass\s+(safety|content|moderation|filter|restrictions?)", re.IGNORECASE),
    re.compile(r"绕过(安全|内容|审核|过滤|限制)", re.IGNORECASE),
    re.compile(r"remove\s+(your\s+)?(restrictions?|limitations?|constraints?|rules?)", re.IGNORECASE),
    re.compile(r"解除(你的)?(限制|约束|规则)", re.IGNORECASE),
]


class PromptInjectionProvider:
    """Heuristic prompt injection detection.

    Detects common injection techniques without external API dependencies.
    """

    name = "prompt_injection"

    def __init__(
        self,
        *,
        detect_override: bool = True,
        detect_roleplay: bool = True,
        detect_delimiters: bool = True,
        detect_obfuscation: bool = True,
        detect_jailbreak: bool = True,
        **_kwargs: object,
    ) -> None:
        self._detect_override = detect_override
        self._detect_roleplay = detect_roleplay
        self._detect_delimiters = detect_delimiters
        self._detect_obfuscation = detect_obfuscation
        self._detect_jailbreak = detect_jailbreak

    def evaluate(self, request: ContentSafetyRequest) -> ContentSafetyDecision:
        reasons: list[str] = []

        if self._detect_override:
            for pattern in _DIRECT_OVERRIDE_PATTERNS:
                if pattern.search(request.text):
                    reasons.append("direct_override")
                    break

        if self._detect_roleplay:
            for pattern in _ROLEPLAY_PATTERNS:
                if pattern.search(request.text):
                    reasons.append("roleplay_override")
                    break

        if self._detect_delimiters:
            for pattern in _DELIMITER_PATTERNS:
                if pattern.search(request.text):
                    reasons.append("delimiter_injection")
                    break

        if self._detect_obfuscation:
            for pattern in _OBFUSCATION_PATTERNS:
                if pattern.search(request.text):
                    reasons.append("obfuscation")
                    break

        if self._detect_jailbreak:
            for pattern in _JAILBREAK_KEYWORDS:
                if pattern.search(request.text):
                    reasons.append("jailbreak_attempt")
                    break

        if reasons:
            logger.warning("Prompt injection detected: %s", reasons)
            return ContentSafetyDecision(
                allowed=False,
                flagged_categories=["prompt_injection"],
                reasons=[f"Prompt injection detected: {', '.join(reasons)}"],
            )

        return ContentSafetyDecision(allowed=True)

    async def aevaluate(self, request: ContentSafetyRequest) -> ContentSafetyDecision:
        return self.evaluate(request)
