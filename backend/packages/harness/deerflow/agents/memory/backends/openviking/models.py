"""Small transport-neutral models used by the OpenViking adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OpenVikingIdentity:
    account: str
    user: str


@dataclass(frozen=True)
class OpenVikingMessage:
    message_id: str
    role: str
    content: str

    def as_request(self) -> dict[str, Any]:
        # OpenViking AddMessageRequest generates its own message ID and rejects
        # unknown request fields, so the DeerFlow ID remains adapter-local for
        # watermarking and is not sent over the wire.
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class OpenVikingCommitResult:
    status: str
    task_id: str | None
    archive_uri: str | None
    archived: bool


@dataclass(frozen=True)
class OpenVikingSearchHit:
    uri: str
    context_type: str
    category: str
    score: float
    abstract: str
    overview: str | None
    match_reason: str

    @classmethod
    def from_response(cls, value: dict[str, Any]) -> OpenVikingSearchHit:
        return cls(
            uri=str(value.get("uri") or ""),
            context_type=str(value.get("context_type") or "memory"),
            category=str(value.get("category") or "memory"),
            score=float(value.get("score") or 0.0),
            abstract=str(value.get("abstract") or ""),
            overview=str(value["overview"]) if value.get("overview") else None,
            match_reason=str(value.get("match_reason") or ""),
        )


@dataclass(frozen=True)
class OpenVikingSessionContext:
    latest_archive_overview: str
    messages: list[dict[str, Any]]
    estimated_tokens: int
