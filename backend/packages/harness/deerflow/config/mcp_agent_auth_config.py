"""Operator-owned grants for named agents on deployment MCP servers."""

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from deerflow.config.extensions_config import McpOAuthConfig

DefinitionDigest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
BindingId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]


class McpAgentCredentialBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    enabled: bool = True
    server: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    owners: list[str]
    definition_digests: list[DefinitionDigest] = Field(min_length=1)
    oauth: McpOAuthConfig = Field(repr=False)

    @field_validator("agent")
    @classmethod
    def _agent_name(cls, value: str) -> str:
        from deerflow.config.agents_config import validate_agent_name

        validate_agent_name(value)
        return value

    @field_validator("owners")
    @classmethod
    def _explicit_owners(cls, value: list[str]) -> list[str]:
        if any(not owner.strip() or owner != owner.strip() or owner == "*" for owner in value):
            raise ValueError("MCP agent bindings require explicit, nonblank owner IDs")
        if len(value) != len(set(value)):
            raise ValueError("MCP agent binding owner IDs must be unique")
        return value

    @model_validator(mode="after")
    def _client_credentials(self) -> Self:
        if self.oauth.grant_type != "client_credentials":
            raise ValueError("MCP agent bindings support OAuth client_credentials")
        if self.enabled and (not self.oauth.enabled or not self.oauth.client_id or not self.oauth.client_secret):
            raise ValueError("An enabled MCP agent binding requires enabled OAuth with a client ID and secret")
        return self
