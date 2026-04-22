from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from store.persistence.base_model import Base, UniversalText, id_key


class Run(Base):
    """Run metadata table."""

    __tablename__ = "runs"

    id: Mapped[id_key] = mapped_column(init=False)

    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)

    assistant_id: Mapped[str | None] = mapped_column(String(64), default=None)
    user_id: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    model_name: Mapped[str | None] = mapped_column(String(128), default=None)
    multitask_strategy: Mapped[str] = mapped_column(String(32), default="reject")
    error: Mapped[str | None] = mapped_column(UniversalText, default=None)
    follow_up_to_run_id: Mapped[str | None] = mapped_column(String(64), default=None)

    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default_factory=dict)
    kwargs: Mapped[dict[str, Any]] = mapped_column(JSON, default_factory=dict)

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