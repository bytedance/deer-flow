"""Discord OAuth helpers for user-owned channel connections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

DISCORD_API_BASE_URL = "https://discord.com/api/v10"
DISCORD_TOKEN_URL = f"{DISCORD_API_BASE_URL}/oauth2/token"
DISCORD_CURRENT_USER_URL = f"{DISCORD_API_BASE_URL}/users/@me"
DISCORD_CURRENT_USER_GUILDS_URL = f"{DISCORD_API_BASE_URL}/users/@me/guilds"


class DiscordConnectError(RuntimeError):
    """Raised when Discord OAuth fails."""


@dataclass(frozen=True)
class DiscordIdentity:
    user_id: str
    display_name: str | None
    username: str | None
    guilds: list[dict[str, Any]]
    access_token: str
    refresh_token: str | None
    token_type: str | None
    scopes: list[str]
    expires_at: datetime | None
    raw_token: dict[str, Any]


def _split_scopes(value: str | None) -> list[str]:
    if not value:
        return []
    return [scope.strip() for scope in value.replace(",", " ").split() if scope.strip()]


def _display_name(user: dict[str, Any]) -> str | None:
    global_name = user.get("global_name")
    if isinstance(global_name, str) and global_name:
        return global_name
    username = user.get("username")
    return str(username) if username else None


async def complete_discord_oauth(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    http_client: httpx.AsyncClient | None = None,
) -> DiscordIdentity:
    async def _complete(client: httpx.AsyncClient) -> DiscordIdentity:
        token_response = await client.post(
            DISCORD_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        token_response.raise_for_status()
        token = token_response.json()
        access_token = token.get("access_token")
        if not access_token:
            raise DiscordConnectError("Discord OAuth response did not include an access token")

        auth_headers = {"Authorization": f"Bearer {access_token}"}
        user_response = await client.get(DISCORD_CURRENT_USER_URL, headers=auth_headers, timeout=10)
        user_response.raise_for_status()
        user = user_response.json()
        user_id = user.get("id")
        if not user_id:
            raise DiscordConnectError("Discord user response did not include a user id")

        guilds_response = await client.get(DISCORD_CURRENT_USER_GUILDS_URL, headers=auth_headers, timeout=10)
        guilds: list[dict[str, Any]] = []
        if guilds_response.status_code == 200:
            guilds = guilds_response.json()

        expires_at = None
        expires_in = token.get("expires_in")
        if isinstance(expires_in, int | float):
            expires_at = datetime.now(UTC) + timedelta(seconds=float(expires_in))

        return DiscordIdentity(
            user_id=str(user_id),
            display_name=_display_name(user),
            username=user.get("username"),
            guilds=guilds,
            access_token=str(access_token),
            refresh_token=token.get("refresh_token"),
            token_type=token.get("token_type"),
            scopes=_split_scopes(token.get("scope")),
            expires_at=expires_at,
            raw_token=token,
        )

    if http_client is None:
        async with httpx.AsyncClient() as client:
            return await _complete(client)
    return await _complete(http_client)
