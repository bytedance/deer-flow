"""Operator-owned connection routing; no resource ACL database or client metadata."""

from __future__ import annotations

import re

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator


def native_id(value: object) -> str:
    # WeKnora uses UUID-like IDs. Reject path syntax before constructing URLs.
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
        raise ValueError("Invalid WeKnora resource ID")
    return value


class Space(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: AnyHttpUrl
    tenant_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    api_key_env: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    user_ids: tuple[str, ...] = Field(min_length=1)
    agent_names: tuple[str, ...] | None = Field(default=None, min_length=1)
    knowledge_base_ids: tuple[str, ...] | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("base_url")
    @classmethod
    def safe_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.username is not None or value.password is not None or value.query is not None or value.fragment is not None:
            raise ValueError("base_url must not contain credentials, query or fragment")
        return value

    @field_validator("user_ids", "agent_names")
    @classmethod
    def identities(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is not None and any(not item.strip() or item != item.strip() for item in value):
            raise ValueError("Identity bindings must be nonblank exact host identities")
        return value

    @field_validator("knowledge_base_ids")
    @classmethod
    def resource_ids(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is not None:
            for item in value:
                native_id(item)
        return value


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    spaces: tuple[Space, ...] = Field(min_length=1, max_length=20)
    timeout: float = Field(default=30, gt=0, le=120, allow_inf_nan=False)
    match_count: int = Field(default=8, ge=1, le=100, strict=True)

    @model_validator(mode="after")
    def unique_connections(self) -> Settings:
        keys = [(str(space.base_url).rstrip("/"), space.tenant_id) for space in self.spaces]
        if len(set(keys)) != len(keys):
            raise ValueError("Configure each endpoint/tenant once, with its explicit user bindings")
        return self
