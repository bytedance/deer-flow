"""Operator-owned grants for named agents on deployment MCP servers."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from deerflow.config.extensions_config import McpOAuthConfig

DefinitionDigest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
BindingId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]


def validate_grant_owners(value: list[str]) -> list[str]:
    if any(not owner.strip() or owner != owner.strip() or owner == "*" for owner in value):
        raise ValueError("MCP agent bindings require explicit, nonblank owner IDs")
    if len(value) != len(set(value)):
        raise ValueError("MCP agent binding owner IDs must be unique")
    return value


class McpAgentCredentialBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    enabled: bool = True
    server: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    # "config": owners and digests below. "runtime": an administrator maintains
    # them through the Gateway admin API; until then the binding admits nobody.
    grants: Literal["config", "runtime"] = "config"
    owners: list[str] = Field(default_factory=list)
    definition_digests: list[DefinitionDigest] = Field(default_factory=list)
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
        return validate_grant_owners(value)

    @model_validator(mode="after")
    def _client_credentials(self) -> Self:
        if self.grants == "config" and not self.definition_digests:
            raise ValueError("An MCP agent binding with grants: config requires definition_digests")
        if self.grants == "runtime" and (self.owners or self.definition_digests):
            raise ValueError("An MCP agent binding with grants: runtime takes owners and definition_digests from the admin API, not config.yaml")
        if self.oauth.grant_type != "client_credentials":
            raise ValueError("MCP agent bindings support OAuth client_credentials")
        if self.enabled and (not self.oauth.enabled or not self.oauth.client_id or not self.oauth.client_secret):
            raise ValueError("An enabled MCP agent binding requires enabled OAuth with a client ID and secret")
        return self


class McpAgentGrant(BaseModel):
    """The runtime part of a ``grants: runtime`` binding, written by an administrator."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    owners: list[str] = Field(max_length=10000)
    definition_digests: list[DefinitionDigest] = Field(max_length=100)

    @field_validator("owners")
    @classmethod
    def _explicit_owners(cls, value: list[str]) -> list[str]:
        return validate_grant_owners(value)

    @field_validator("definition_digests")
    @classmethod
    def _unique_digests(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class McpAgentGrantSubject(BaseModel):
    """What an administrator approved a runtime grant for.

    The grant applies only while the binding still names this agent and server,
    the server keeps this destination, and the binding keeps this OAuth client
    (a nonsecret digest, so rotating the secret of the same account keeps it).
    """

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    agent: str
    server: str
    destination_digest: DefinitionDigest
    credential_digest: DefinitionDigest


class StoredMcpAgentGrant(McpAgentGrant):
    """A runtime grant as stored: the administrator's grant and what it was approved for."""

    approved_for: McpAgentGrantSubject
