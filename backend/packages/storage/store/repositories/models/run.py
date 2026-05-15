from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from store.persistence.base_model import DataClassBase, TimeZone, UniversalText, current_time


class Run(DataClassBase):
    """Run metadata table."""

    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_thread_status", "thread_id", "status"),
        {"comment": "Run metadata table."},
    )

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)

    assistant_id: Mapped[str | None] = mapped_column(String(128), default=None)
    user_id: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    model_name: Mapped[str | None] = mapped_column(String(128), default=None)
    multitask_strategy: Mapped[str] = mapped_column(String(20), default="reject")
    error: Mapped[str | None] = mapped_column(UniversalText, default=None)
    follow_up_to_run_id: Mapped[str | None] = mapped_column(String(64), default=None)

    meta: Mapped[dict[str, Any]] = mapped_column("metadata_json", JSON, default_factory=dict)
    kwargs: Mapped[dict[str, Any]] = mapped_column("kwargs_json", JSON, default_factory=dict)

    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_call_count: Mapped[int] = mapped_column(Integer, default=0)
    lead_agent_tokens: Mapped[int] = mapped_column(Integer, default=0)
    subagent_tokens: Mapped[int] = mapped_column(Integer, default=0)
    middleware_tokens: Mapped[int] = mapped_column(Integer, default=0)

    message_count: Mapped[int] = mapped_column(Integer, default=0)
    first_human_message: Mapped[str | None] = mapped_column(UniversalText, default=None)
    last_ai_message: Mapped[str | None] = mapped_column(UniversalText, default=None)

    created_time: Mapped[datetime] = mapped_column(
        "created_at",
        TimeZone,
        init=False,
        default_factory=current_time,
        sort_order=999,
        comment="Created at",
    )
    updated_time: Mapped[datetime | None] = mapped_column(
        "updated_at",
        TimeZone,
        init=False,
        default=None,
        onupdate=current_time,
        sort_order=999,
        comment="Updated at",
    )
