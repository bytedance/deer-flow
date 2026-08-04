"""Deterministic, local checks for input and streamed assistant text."""

from dataclasses import dataclass
from typing import Self

BLOCKED_RESPONSE_TEXT = "抱歉，当前请求或回复内容可能违反平台内容安全规范，已停止生成。"


@dataclass(frozen=True)
class SafetyVerdict:
    blocked: bool
    category: str | None = None
    severity: str | None = None
    redacted_excerpt: str | None = None
    user_message: str | None = None

    @classmethod
    def allow(cls) -> Self:
        return cls(blocked=False)


@dataclass(frozen=True)
class RuleSet:
    terms: tuple[str, ...]
    version: str = "local-v1"

    @classmethod
    def from_terms(cls, terms: list[str], *, version: str = "local-v1") -> Self:
        return cls(tuple(term.casefold().strip() for term in terms if term.strip()), version)


# First-party rules stay local to the Gateway. They are a conservative
# emergency baseline; platform rules can extend this set without forwarding
# user prompts to a third-party service.
DEFAULT_RULE_SET = RuleSet.from_terms(
    ["自杀方法", "制作炸弹", "儿童色情", "how to make a bomb", "child sexual abuse"],
)


class StreamingContentGuard:
    def __init__(self, rule_set: RuleSet, *, window_chars: int = 120) -> None:
        if window_chars < 1:
            raise ValueError("window_chars must be positive")
        self._rule_set = rule_set
        self._window_chars = window_chars
        self._pending = ""
        self._tail = ""
        self._blocked = False

    def inspect_input(self, text: str) -> SafetyVerdict:
        return self._inspect(text)

    def push_output(self, delta: str) -> tuple[SafetyVerdict, list[str]]:
        if self._blocked:
            return self._blocked_verdict(self._pending), []
        self._pending += delta
        verdict = self._inspect(self._tail + self._pending)
        if verdict.blocked:
            self._blocked = True
            return verdict, []
        if len(self._pending) <= self._window_chars:
            return verdict, []
        release_count = len(self._pending) - self._window_chars
        released, self._pending = self._pending[:release_count], self._pending[release_count:]
        self._tail = (self._tail + released)[-self._window_chars :]
        return verdict, [released]

    def flush(self) -> list[str]:
        if self._blocked or not self._pending:
            return []
        released, self._pending = self._pending, ""
        self._tail = (self._tail + released)[-self._window_chars :]
        return [released]

    def _inspect(self, text: str) -> SafetyVerdict:
        lowered = text.casefold()
        if any(term in lowered for term in self._rule_set.terms):
            return self._blocked_verdict(text)
        return SafetyVerdict.allow()

    @staticmethod
    def _redact(text: str) -> str:
        compact = " ".join(text.split())
        return f"{compact[:20]}***" if len(compact) > 20 else "***"

    def _blocked_verdict(self, text: str) -> SafetyVerdict:
        return SafetyVerdict(
            blocked=True,
            category="unsafe_content",
            severity="high",
            redacted_excerpt=self._redact(text),
            user_message=BLOCKED_RESPONSE_TEXT,
        )
