"""Operator-owned workspace activation; never a client permission assertion."""

from pydantic import BaseModel, ConfigDict, StrictBool


class WorkspacesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: StrictBool = False
