"""Slack OAuth and Events helpers for user-owned channel connections."""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any

import httpx

SLACK_OAUTH_ACCESS_URL = "https://slack.com/api/oauth.v2.access"
SLACK_SIGNATURE_VERSION = "v0"
SLACK_SIGNATURE_TOLERANCE_SECONDS = 60 * 5


class SlackConnectError(RuntimeError):
    """Raised when Slack OAuth or request verification fails."""


@dataclass(frozen=True)
class SlackInstall:
    team_id: str
    team_name: str | None
    authed_user_id: str
    bot_user_id: str | None
    bot_access_token: str
    scopes: list[str]
    raw: dict[str, Any]


def verify_slack_signature(
    *,
    signing_secret: str,
    timestamp: str | None,
    body: bytes,
    signature: str | None,
    now: int | None = None,
) -> bool:
    if not signing_secret or not timestamp or not signature:
        return False

    try:
        timestamp_int = int(timestamp)
    except (TypeError, ValueError):
        return False

    current_time = int(time.time()) if now is None else now
    if abs(current_time - timestamp_int) > SLACK_SIGNATURE_TOLERANCE_SECONDS:
        return False

    base = f"{SLACK_SIGNATURE_VERSION}:{timestamp}:".encode() + body
    digest = hmac.new(signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    expected = f"{SLACK_SIGNATURE_VERSION}={digest}"
    return hmac.compare_digest(expected, signature)


def _split_scopes(value: str | None) -> list[str]:
    if not value:
        return []
    return [scope.strip() for scope in value.split(",") if scope.strip()]


async def exchange_slack_oauth_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    http_client: httpx.AsyncClient | None = None,
) -> SlackInstall:
    async def _post(client: httpx.AsyncClient) -> dict[str, Any]:
        response = await client.post(
            SLACK_OAUTH_ACCESS_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    if http_client is None:
        async with httpx.AsyncClient() as client:
            payload = await _post(client)
    else:
        payload = await _post(http_client)

    if not payload.get("ok"):
        raise SlackConnectError(str(payload.get("error") or "Slack OAuth exchange failed"))

    access_token = payload.get("access_token")
    team = payload.get("team") or {}
    authed_user = payload.get("authed_user") or {}
    if not access_token or not team.get("id") or not authed_user.get("id"):
        raise SlackConnectError("Slack OAuth response did not include required installation fields")

    return SlackInstall(
        team_id=str(team["id"]),
        team_name=team.get("name"),
        authed_user_id=str(authed_user["id"]),
        bot_user_id=payload.get("bot_user_id"),
        bot_access_token=str(access_token),
        scopes=_split_scopes(payload.get("scope")),
        raw=payload,
    )
