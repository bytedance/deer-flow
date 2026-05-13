from __future__ import annotations

import os

from pydantic import BaseModel, Field


class HttpConnectorConfig(BaseModel):
    """Configuration for a named HTTP connector endpoint."""

    name: str = Field(..., description="Connector name, used by Agent to invoke")
    url: str = Field(..., description="Target URL")
    method: str = Field(default="GET", description="HTTP method: GET | POST | PUT")
    headers: dict[str, str] = Field(default_factory=dict)
    auth_type: str = Field(default="none", description="none | bearer | api_key")
    auth_token_env: str | None = Field(
        default=None, description="Environment variable name holding the auth token"
    )
    auth_header: str = Field(
        default="Authorization", description="Header name for the auth token"
    )
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)
    description: str = Field(default="", description="Description shown to Agent")
    max_response_bytes: int = Field(
        default=512 * 1024,
        description="Max response size in bytes before truncation (default 512KB)",
    )
    max_retries: int = Field(default=1, ge=0, le=5, description="Max retry attempts (0=no retry)")
    retry_on_status: list[int] = Field(
        default_factory=lambda: [502, 503, 504],
        description="HTTP status codes that trigger a retry",
    )
    cache_ttl_seconds: int | None = Field(
        default=None,
        description="Response cache TTL in seconds. None=no caching.",
    )

    def resolved_headers(self) -> dict[str, str]:
        """Resolve auth token from environment and merge into headers."""
        result = dict(self.headers)
        if self.auth_type == "bearer" and self.auth_token_env:
            token = os.environ.get(self.auth_token_env, "")
            if token:
                result[self.auth_header] = f"Bearer {token}"
        elif self.auth_type == "api_key" and self.auth_token_env:
            token = os.environ.get(self.auth_token_env, "")
            if token:
                result[self.auth_header] = token
        return result
