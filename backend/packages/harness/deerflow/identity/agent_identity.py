from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langgraph.types import RunnableConfig

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


def _validate_id(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not _SAFE_ID_RE.match(value):
        raise ValueError(
            f"Invalid {field_name} {value!r}: must match [a-zA-Z0-9_.-]{{1,64}}"
        )
    return value


@dataclass
class AgentIdentity:
    """Three-tier agent identity: department / user / agent.

    Maps to OpenViking's three-layer isolation:
      dept_id    → X-OpenViking-Account
      user_id    → X-OpenViking-User
      agent_name → X-OpenViking-Agent
    """

    dept_id: str | None = field(default=None)
    user_id: str | None = field(default=None)
    agent_name: str | None = field(default=None)

    def __post_init__(self) -> None:
        self.dept_id = _validate_id(self.dept_id, "dept_id")
        self.user_id = _validate_id(self.user_id, "user_id")
        self.agent_name = _validate_id(self.agent_name, "agent_name")

    @classmethod
    def from_config(cls, config: "RunnableConfig") -> "AgentIdentity":
        """Extract identity from a LangGraph RunnableConfig."""
        cfg = config.get("configurable", {}) if config else {}
        return cls(
            dept_id=cfg.get("dept_id") or None,
            user_id=cfg.get("user_id") or None,
            agent_name=cfg.get("agent_name") or None,
        )

    # ------------------------------------------------------------------ #
    # OpenViking header values                                             #
    # ------------------------------------------------------------------ #

    @property
    def ov_account(self) -> str:
        """X-OpenViking-Account value (dept_id or 'default')."""
        return self.dept_id or "default"

    @property
    def ov_user(self) -> str:
        """X-OpenViking-User value (user_id or 'default')."""
        return self.user_id or "default"

    @property
    def ov_agent(self) -> str:
        """X-OpenViking-Agent value (agent_name or 'default')."""
        return self.agent_name or "default"

    @property
    def ov_headers(self) -> dict[str, str]:
        """All three OV identity headers as a dict."""
        return {
            "X-OpenViking-Account": self.ov_account,
            "X-OpenViking-User": self.ov_user,
            "X-OpenViking-Agent": self.ov_agent,
        }

    # ------------------------------------------------------------------ #
    # Convenience predicates                                               #
    # ------------------------------------------------------------------ #

    @property
    def is_global(self) -> bool:
        """True when no dept or user is set (global/legacy mode)."""
        return not (self.dept_id or self.user_id)

    @property
    def has_dept(self) -> bool:
        return self.dept_id is not None

    @property
    def has_user(self) -> bool:
        return self.user_id is not None

    @property
    def has_agent(self) -> bool:
        return self.agent_name is not None

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def __str__(self) -> str:
        parts = []
        if self.dept_id:
            parts.append(f"dept={self.dept_id}")
        if self.user_id:
            parts.append(f"user={self.user_id}")
        if self.agent_name:
            parts.append(f"agent={self.agent_name}")
        return f"AgentIdentity({', '.join(parts) or 'global'})"
