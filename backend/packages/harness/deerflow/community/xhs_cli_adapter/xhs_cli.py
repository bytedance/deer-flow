from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any, Protocol

from .schemas import (
    PostComment,
    PostDetailOutput,
    SearchPostsOutput,
    SearchPostSummary,
    UserProfileOutput,
)


class XhsCliError(RuntimeError):
    """Base adapter error."""


class XhsCliCommandError(XhsCliError):
    """Raised when the CLI returns a structured error or non-zero exit."""


class XhsCliProtocolError(XhsCliError):
    """Raised when the CLI returns unexpected JSON."""


class CommandRunner(Protocol):
    def __call__(self, args: Sequence[str]) -> str: ...


def _default_runner(args: Sequence[str]) -> str:
    completed = subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise XhsCliCommandError(stderr or f"command failed: {' '.join(args)}")
    return completed.stdout


class XhsCliAdapter:
    def __init__(
        self,
        runner: CommandRunner | None = None,
        executable: str = "xhs",
    ) -> None:
        self._runner = runner or _default_runner
        self._executable = executable
        self._note_xsec_tokens: dict[str, str] = {}
        self._post_titles: dict[str, str] = {}

    def search_posts(self, query: str, pages: int = 1) -> SearchPostsOutput:
        if pages < 1:
            raise ValueError("pages must be >= 1")

        payloads: list[dict[str, Any]] = []
        posts: list[SearchPostSummary] = []
        recommended_queries: list[str] = []
        seen_post_ids: set[str] = set()
        seen_queries: set[str] = set()

        for page in range(1, pages + 1):
            payload = self._run_json_command(
                [self._executable, "search", query, "--json", "--page", str(page)]
            )
            payloads.append(payload)

            items = _get_required_mapping(payload, "data").get("items", [])
            if not isinstance(items, list):
                raise XhsCliProtocolError("search data.items must be a list")

            for item in items:
                if not isinstance(item, Mapping):
                    continue

                model_type = str(item.get("model_type", ""))
                if model_type == "note":
                    summary = _extract_search_post_summary(item)
                    if summary and summary.post_id not in seen_post_ids:
                        posts.append(summary)
                        seen_post_ids.add(summary.post_id)
                        self._remember_post_summary(summary)
                    continue

                if model_type == "hot_query":
                    for recommendation in _extract_hot_queries(item):
                        if recommendation not in seen_queries:
                            recommended_queries.append(recommendation)
                            seen_queries.add(recommendation)

        rendered_text = _render_agent_block(
            "Search results",
            {
                "query": query,
                "page_count": pages,
                "posts": [_render_search_post_summary(post) for post in posts],
                "recommended_queries": recommended_queries,
            },
        )
        return SearchPostsOutput(
            query=query,
            posts=posts,
            recommended_queries=recommended_queries,
            page_count=pages,
            raw_payloads=[_sanitize_mapping(payload) for payload in payloads],
            rendered_text=rendered_text,
        )

    def fetch_post_detail(
        self,
        post_id: str,
        xsec_token: str | None = None,
    ) -> PostDetailOutput:
        resolved_xsec_token = xsec_token or self._note_xsec_tokens.get(post_id)
        read_args = [self._executable, "read", post_id]
        if resolved_xsec_token:
            read_args.extend(["--xsec-token", resolved_xsec_token])
        read_args.append("--json")
        read_payload = self._run_json_command(read_args)

        items = _get_required_mapping(read_payload, "data").get("items", [])
        if not isinstance(items, list) or not items:
            raise XhsCliProtocolError("read data.items must contain at least one item")

        first_item = items[0]
        if not isinstance(first_item, Mapping):
            raise XhsCliProtocolError("read data.items[0] must be an object")

        item_xsec_token = _extract_note_xsec_token(first_item)
        if item_xsec_token:
            self._note_xsec_tokens[post_id] = item_xsec_token
        resolved_xsec_token = resolved_xsec_token or item_xsec_token

        comments_args = [self._executable, "comments", post_id]
        if resolved_xsec_token:
            comments_args.extend(["--xsec-token", resolved_xsec_token])
        comments_args.append("--json")
        comments_payload = self._run_json_command(comments_args)

        note_card = _get_required_mapping(first_item, "note_card")
        title = _string_value(note_card.get("title"))
        content = _string_value(note_card.get("desc"))
        published_at = _optional_string(note_card.get("time"))
        updated_at = _optional_string(note_card.get("last_update_time"))
        tags = _extract_tags(note_card.get("tag_list"))
        comments = _extract_comments(comments_payload)
        if title:
            self._post_titles[post_id] = title

        rendered_text = _render_agent_block(
            "Post detail",
            {
                "post_id": post_id,
                "title": title,
                "content": content,
                "published_at": published_at,
                "updated_at": updated_at,
                "has_xsec_token": bool(resolved_xsec_token),
                "tags": tags,
                "comments": [asdict(comment) for comment in comments],
            },
        )
        return PostDetailOutput(
            post_id=post_id,
            title=title,
            content=content,
            published_at=published_at,
            updated_at=updated_at,
            xsec_token=resolved_xsec_token,
            tags=tags,
            comments=comments,
            raw_read_payload=_sanitize_mapping(read_payload),
            raw_comments_payload=_sanitize_mapping(comments_payload),
            rendered_text=rendered_text,
        )

    def fetch_user_profile(self, user_id: str) -> UserProfileOutput:
        profile_payload = self._run_json_command(
            [self._executable, "user", user_id, "--json"]
        )
        posts_payload = self._run_json_command(
            [self._executable, "user-posts", user_id, "--json"]
        )

        posts = _extract_listing_posts(posts_payload)
        for post in posts:
            self._remember_post_summary(post)
        profile_data = _get_required_mapping(profile_payload, "data")

        rendered_text = _render_agent_block(
            "User profile",
            {
                "user_id": user_id,
                "profile": _sanitize_mapping(profile_data),
                "posts": [_render_search_post_summary(post) for post in posts],
            },
        )
        return UserProfileOutput(
            user_id=user_id,
            profile=_sanitize_mapping(profile_data),
            posts=posts,
            raw_profile_payload=_sanitize_mapping(profile_payload),
            raw_posts_payload=_sanitize_mapping(posts_payload),
            rendered_text=rendered_text,
        )

    def _run_json_command(self, args: Sequence[str]) -> dict[str, Any]:
        raw_output = self._runner(args)
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise XhsCliProtocolError("CLI output is not valid JSON") from exc

        if not isinstance(payload, dict):
            raise XhsCliProtocolError("CLI output must be a JSON object")

        ok = payload.get("ok")
        if ok is False:
            error = payload.get("error")
            if isinstance(error, Mapping):
                code = _optional_string(error.get("code")) or "unknown_error"
                message = _optional_string(error.get("message")) or "unknown failure"
                raise XhsCliCommandError(f"{code}: {message}")
            raise XhsCliCommandError("CLI returned ok=false without a valid error")

        if ok is not True:
            raise XhsCliProtocolError("CLI payload must include ok=true on success")

        if "data" not in payload or not isinstance(payload["data"], Mapping):
            raise XhsCliProtocolError("CLI success payload must include object data")

        return payload

    def get_cached_post_title(self, post_id: str) -> str | None:
        return self._post_titles.get(post_id)

    def _remember_post_summary(self, post: SearchPostSummary) -> None:
        if post.xsec_token:
            self._note_xsec_tokens[post.post_id] = post.xsec_token
        if post.title:
            self._post_titles[post.post_id] = post.title


def _extract_search_post_summary(item: Mapping[str, Any]) -> SearchPostSummary | None:
    post_id = _optional_string(item.get("id"))
    note_card = item.get("note_card")
    if not post_id or not isinstance(note_card, Mapping):
        return None

    user = note_card.get("user")
    user_mapping = user if isinstance(user, Mapping) else {}
    title = _string_value(note_card.get("display_title") or note_card.get("title"))
    author_nickname = _optional_string(
        user_mapping.get("nickname") or user_mapping.get("nick_name")
    )
    author_id = _optional_string(user_mapping.get("user_id"))
    return SearchPostSummary(
        post_id=post_id,
        title=title,
        author_id=author_id,
        author_nickname=author_nickname,
        xsec_token=_extract_note_xsec_token(item),
    )


def _render_search_post_summary(post: SearchPostSummary) -> dict[str, Any]:
    return {
        "post_id": post.post_id,
        "title": post.title,
        "author_id": post.author_id,
        "author_nickname": post.author_nickname,
        "has_xsec_token": bool(post.xsec_token),
    }


def _extract_note_xsec_token(item: Mapping[str, Any]) -> str | None:
    direct_token = _optional_string(item.get("xsec_token"))
    if direct_token:
        return direct_token

    note_card = item.get("note_card")
    if isinstance(note_card, Mapping):
        return _optional_string(note_card.get("xsec_token"))
    return None


def _extract_hot_queries(item: Mapping[str, Any]) -> list[str]:
    hot_query = item.get("hot_query")
    if not isinstance(hot_query, Mapping):
        return []

    queries = hot_query.get("queries", [])
    if not isinstance(queries, list):
        return []

    collected: list[str] = []
    for query in queries:
        if not isinstance(query, Mapping):
            continue
        search_word = _optional_string(query.get("search_word"))
        if search_word:
            collected.append(search_word)
    return collected


def _extract_listing_posts(payload: Mapping[str, Any]) -> list[SearchPostSummary]:
    data = _get_required_mapping(payload, "data")
    items = data.get("items", [])
    if not isinstance(items, list):
        raise XhsCliProtocolError("listing data.items must be a list")

    posts: list[SearchPostSummary] = []
    seen_post_ids: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        summary = _extract_search_post_summary(item)
        if summary and summary.post_id not in seen_post_ids:
            posts.append(summary)
            seen_post_ids.add(summary.post_id)
    return posts


def _extract_comments(payload: Mapping[str, Any]) -> list[PostComment]:
    data = _get_required_mapping(payload, "data")
    items = _find_comment_items(data)

    comments: list[PostComment] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue

        content = _extract_comment_content(item)
        if not content:
            continue

        user = item.get("user_info") or item.get("user")
        user_mapping = user if isinstance(user, Mapping) else {}
        comments.append(
            PostComment(
                comment_id=_optional_string(
                    item.get("id") or item.get("comment_id") or item.get("root_comment_id")
                ),
                author_id=_optional_string(
                    user_mapping.get("user_id") or user_mapping.get("id")
                ),
                author_nickname=_optional_string(
                    user_mapping.get("nickname")
                    or user_mapping.get("nick_name")
                    or user_mapping.get("name")
                ),
                content=content,
                created_at=_optional_string(
                    item.get("create_time")
                    or item.get("created_at")
                    or item.get("time")
                ),
            )
        )
    return comments


def _find_comment_items(data: Mapping[str, Any]) -> list[Any]:
    candidates = (
        data.get("comments"),
        data.get("items"),
        data.get("list"),
        data.get("data"),
    )
    for candidate in candidates:
        if isinstance(candidate, list):
            return candidate
    return []


def _extract_comment_content(item: Mapping[str, Any]) -> str | None:
    candidate_keys = ("content", "text", "comment", "comment_text")
    for key in candidate_keys:
        value = _optional_string(item.get(key))
        if value:
            return value

    content_mapping = item.get("content_info") or item.get("content")
    if isinstance(content_mapping, Mapping):
        for key in ("content", "text"):
            value = _optional_string(content_mapping.get(key))
            if value:
                return value
    return None


def _extract_tags(raw_tags: Any) -> list[str]:
    if not isinstance(raw_tags, list):
        return []

    tags: list[str] = []
    for tag in raw_tags:
        if isinstance(tag, str) and tag.strip():
            tags.append(tag.strip())
            continue
        if isinstance(tag, Mapping):
            tag_name = _optional_string(
                tag.get("name") or tag.get("tag_name") or tag.get("title")
            )
            if tag_name:
                tags.append(tag_name)
    return tags


def _get_required_mapping(
    payload: Mapping[str, Any],
    key: str,
) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise XhsCliProtocolError(f"{key} must be an object")
    return value


def _string_value(value: Any) -> str:
    text = _optional_string(value)
    return text or ""


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _render_agent_block(title: str, data: Mapping[str, Any]) -> str:
    return f"{title}\n\n{_to_yaml(data)}"


def _to_yaml(value: Any, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(value, Mapping):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (Mapping, list)):
                lines.append(f"{prefix}{key}:")
                lines.append(_to_yaml(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_format_scalar(item)}")
        return "\n".join(lines)

    if isinstance(value, list):
        if not value:
            return f"{prefix}[]"

        lines = []
        for item in value:
            if isinstance(item, (Mapping, list)):
                lines.append(f"{prefix}-")
                lines.append(_to_yaml(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_format_scalar(item)}")
        return "\n".join(lines)

    return f"{prefix}{_format_scalar(value)}"


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)

    text = str(value)
    if text == "":
        return '""'
    if "\n" in text or any(char in text for char in [":", "#", "-", '"', "'"]):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


_SENSITIVE_KEYS = {
    "xsec_token",
    "sec_token",
    "cookie",
    "cookies",
    "authorization",
    "auth",
}


def _sanitize_mapping(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in _SENSITIVE_KEYS:
                continue
            sanitized[str(key)] = _sanitize_mapping(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_mapping(item) for item in value]
    return value
