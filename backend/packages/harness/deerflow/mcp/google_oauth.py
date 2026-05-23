"""Google OAuth authorization_code exchange helper.

Minimal implementation targeted at the Gateway `/api/mcp/oauth/*` routes.
Uses only httpx (already a transitive deerflow dependency) — no Google SDK.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: str
    expires_in: int
    scope: str | None


def build_authorization_url(
    *,
    authorization_url: str,
    client_id: str,
    redirect_uri: str,
    scope: str,
    state: str,
    code_challenge: str,
    extra_params: dict[str, str] | None = None,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if extra_params:
        params.update(extra_params)
    return f"{authorization_url}?{urlencode(params)}"


async def exchange_code_for_tokens(
    *,
    token_url: str,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code_verifier: str,
) -> OAuthTokens:
    """Exchange an authorization code for (access_token, refresh_token).

    Raises:
        ValueError: if the response omits a required field.
        httpx.HTTPError: on transport failure.
    """
    import httpx  # pyright: ignore[reportMissingImports]

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(token_url, data=data)
        if response.status_code >= 400:
            logger.error(
                "OAuth token exchange failed: status=%s body=%s",
                response.status_code,
                response.text,
            )
        response.raise_for_status()
        payload = response.json()

    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if not access_token:
        raise ValueError("OAuth token response missing access_token")
    if not refresh_token:
        # Google only returns refresh_token when access_type=offline + prompt=consent.
        # If it's missing, we can't persist the connection, so surface a clear error.
        raise ValueError("OAuth token response missing refresh_token — ensure the preset sets access_type=offline and prompt=consent.")

    return OAuthTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=int(payload.get("expires_in", 3600)),
        scope=payload.get("scope"),
    )
