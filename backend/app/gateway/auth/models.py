"""Pydantic models for authentication requests and responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, description="Username")
    password: str = Field(min_length=1, description="Password")


class TokenResponse(BaseModel):
    access_token: str = Field(description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(description="Token expiry in seconds")


class RefreshRequest(BaseModel):
    access_token: str = Field(description="Current (possibly expired) access token")


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="Human-readable name for this API key")


class ApiKeyResponse(BaseModel):
    id: str = Field(description="Unique key identifier")
    name: str = Field(description="Human-readable name")
    key_prefix: str = Field(description="First 8 characters of the key for identification")
    created_at: str = Field(description="ISO-8601 creation timestamp")
    last_used_at: str | None = Field(default=None, description="ISO-8601 last-used timestamp")


class ApiKeyCreateResponse(BaseModel):
    id: str = Field(description="Unique key identifier")
    name: str = Field(description="Human-readable name")
    raw_key: str = Field(description="The full API key — shown only once")
    key_prefix: str = Field(description="First 8 characters of the key for identification")
    created_at: str = Field(description="ISO-8601 creation timestamp")
