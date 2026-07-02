"""Run event storage configuration.

Controls where run events (messages + execution traces) are persisted.

Backends:
- memory: In-memory storage, data lost on restart. Suitable for
  development and testing.
- db: SQL database via SQLAlchemy ORM. Provides full query capability.
  Suitable for production deployments.
- jsonl: Append-only JSONL files. Lightweight alternative for
  single-node deployments that need persistence without a database.
- kurrent: Community prototype. Appends run events to per-thread KurrentDB
  streams (deerflow.community.kurrentdb.run_event_store.KurrentRunEventStore);
  requires the kurrentdbclient extra and KURRENTDB_CONNECTION_STRING.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RunEventsConfig(BaseModel):
    backend: Literal["memory", "db", "jsonl", "kurrent"] = Field(
        default="memory",
        description=(
            "Storage backend for run events. 'memory' for development (no persistence), 'db' for production (SQL queries), "
            "'jsonl' for lightweight single-node persistence, 'kurrent' for the community KurrentDB-backed prototype (requires KURRENTDB_CONNECTION_STRING)."
        ),
    )
    max_trace_content: int = Field(
        default=10240,
        description="Maximum trace content size in bytes before truncation (db backend only).",
    )
    track_token_usage: bool = Field(
        default=True,
        description="Whether RunJournal should accumulate token counts to RunRow.",
    )
