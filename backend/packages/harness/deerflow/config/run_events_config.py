"""Run event storage configuration.

Controls where run events (messages + execution traces) are persisted.

Backends:
- memory: In-memory storage, data lost on restart. Suitable for
  development and testing.
- db: SQL database via SQLAlchemy ORM. Provides full query capability.
  Suitable for production deployments.
- jsonl: Append-only JSONL files. Lightweight alternative for
  single-node deployments that need persistence without a database.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from deerflow.config._boolean_guards import reject_boolean


class RunEventsConfig(BaseModel):
    producer_fencing: Literal["off", "strict"] = "off"
    producer_cutover_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def _validate_producer_fencing(self):
        if self.producer_fencing == "strict" and (self.backend != "db" or self.producer_cutover_id is None):
            raise ValueError("Strict producer fencing requires backend=db and an explicit offline cutover ID")
        return self

    backend: Literal["memory", "db", "jsonl"] = Field(
        default="memory",
        description="Storage backend for run events. 'memory' for development (no persistence), 'db' for production (SQL queries), 'jsonl' for lightweight single-node persistence.",
    )
    max_trace_content: int = Field(
        default=10240,
        ge=1,
        description="Maximum trace content size in bytes before truncation (db backend only).",
    )

    @field_validator("max_trace_content", mode="before")
    @classmethod
    def _reject_boolean_max_trace_content(cls, value: object, info: ValidationInfo) -> object:
        return reject_boolean(value, info, kind="an integer")

    track_token_usage: bool = Field(
        default=True,
        description="Whether RunJournal should accumulate token counts to RunRow.",
    )
