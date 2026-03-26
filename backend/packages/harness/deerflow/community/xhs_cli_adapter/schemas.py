from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SearchPostSummary:
    post_id: str
    title: str
    author_id: str | None
    author_nickname: str | None
    xsec_token: str | None = None


@dataclass(slots=True)
class SearchPostsOutput:
    query: str
    posts: list[SearchPostSummary] = field(default_factory=list)
    recommended_queries: list[str] = field(default_factory=list)
    page_count: int = 1
    raw_payloads: list[dict[str, Any]] = field(default_factory=list)
    rendered_text: str = ""


@dataclass(slots=True)
class PostComment:
    comment_id: str | None
    author_id: str | None
    author_nickname: str | None
    content: str
    created_at: str | None = None


@dataclass(slots=True)
class PostDetailOutput:
    post_id: str
    title: str
    content: str
    published_at: str | None
    updated_at: str | None
    xsec_token: str | None = None
    tags: list[str] = field(default_factory=list)
    comments: list[PostComment] = field(default_factory=list)
    raw_read_payload: dict[str, Any] = field(default_factory=dict)
    raw_comments_payload: dict[str, Any] = field(default_factory=dict)
    rendered_text: str = ""


@dataclass(slots=True)
class UserProfileOutput:
    user_id: str
    profile: dict[str, Any]
    posts: list[SearchPostSummary] = field(default_factory=list)
    raw_profile_payload: dict[str, Any] = field(default_factory=dict)
    raw_posts_payload: dict[str, Any] = field(default_factory=dict)
    rendered_text: str = ""
